from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from core.contracts import MemoryRetentionPolicy
from core.models import utc_now
from core.observability import OBSERVABILITY_METADATA_KEY
from core.retention import (
    DEBUG_METADATA_TTL,
    RETENTION_MAINTENANCE_KEY,
    SUPERSEDED_MEMORY_TTL,
    WORKING_MEMORY_TTL,
    source_item_retention_ttl,
)
from storage.base import (
    RetentionHealthSnapshot,
    RetentionLease,
    RetentionLeaseLostError,
    RetentionRunStats,
)
from storage.sqlite_schema import (
    AnnotationRecord,
    IndexEntryRecord,
    MaintenanceStateRecord,
    MemoryObjectRecord,
    RelationRecord,
    SourceItemRecord,
)


class SQLiteRetentionMixin:
    _RETENTION_LEASE_RENEWAL_BATCH = 50

    def claim_retention_lease(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> RetentionLease | None:
        claimed_at = now or utc_now()
        lease_expires_at = claimed_at + timedelta(seconds=max(1, lease_seconds))
        with self._session_factory.begin() as session:
            record = self._ensure_maintenance_state_record_in_session(session, RETENTION_MAINTENANCE_KEY, claimed_at)
            current_expiry = self._normalize_datetime(record.lease_expires_at)
            if current_expiry is not None and current_expiry > claimed_at:
                return None
            record.claimed_by = worker_id
            record.claimed_at = claimed_at
            record.lease_expires_at = lease_expires_at
            record.last_run_started_at = claimed_at
            record.updated_at = claimed_at
            return self._to_retention_lease(record)

    def renew_retention_lease(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> RetentionLease | None:
        renewed_at = now or utc_now()
        normalized_claimed_at = self._normalize_datetime(claimed_at) or claimed_at
        lease_expires_at = renewed_at + timedelta(seconds=max(1, lease_seconds))
        with self._session_factory.begin() as session:
            record = session.get(MaintenanceStateRecord, RETENTION_MAINTENANCE_KEY)
            if record is None:
                raise KeyError(RETENTION_MAINTENANCE_KEY)
            if not self._retention_lease_owned_in_session(
                session,
                worker_id=worker_id,
                claimed_at=normalized_claimed_at,
                now=renewed_at,
                allow_expired=False,
            ):
                return None
            record.lease_expires_at = lease_expires_at
            record.updated_at = renewed_at
            return self._to_retention_lease(record)

    def complete_retention_pass(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
        completed_at: datetime | None,
        stats: RetentionRunStats,
    ) -> bool:
        finished_at = completed_at or utc_now()
        normalized_claimed_at = self._normalize_datetime(claimed_at) or claimed_at
        with self._session_factory.begin() as session:
            record = session.get(MaintenanceStateRecord, RETENTION_MAINTENANCE_KEY)
            if record is None:
                raise KeyError(RETENTION_MAINTENANCE_KEY)
            if not self._retention_lease_owned_in_session(
                session,
                worker_id=worker_id,
                claimed_at=normalized_claimed_at,
                now=finished_at,
                allow_expired=False,
            ):
                return False
            record.claimed_by = None
            record.claimed_at = None
            record.lease_expires_at = None
            record.last_run_completed_at = finished_at
            record.last_run_stats_json = self._dumps(stats.as_dict())
            record.updated_at = finished_at
            return True

    def fail_retention_pass(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
    ) -> bool:
        failed_at = utc_now()
        normalized_claimed_at = self._normalize_datetime(claimed_at) or claimed_at
        with self._session_factory.begin() as session:
            record = session.get(MaintenanceStateRecord, RETENTION_MAINTENANCE_KEY)
            if record is None:
                raise KeyError(RETENTION_MAINTENANCE_KEY)
            if not self._retention_lease_owned_in_session(
                session,
                worker_id=worker_id,
                claimed_at=normalized_claimed_at,
                now=failed_at,
                allow_expired=False,
            ):
                return False
            record.claimed_by = None
            record.claimed_at = None
            record.lease_expires_at = None
            record.updated_at = failed_at
            return True

    def run_retention_pass(
        self,
        *,
        now: datetime,
        batch_size: int,
        lease: RetentionLease | None = None,
        lease_seconds: int | None = None,
        lease_now: datetime | None = None,
        retention_policy: MemoryRetentionPolicy | None = None,
    ) -> RetentionRunStats:
        durable_types = retention_policy.durable_types if retention_policy else frozenset()
        working_types = retention_policy.working_types if retention_policy else frozenset()
        orphan_delete_types = retention_policy.orphan_delete_types if retention_policy else frozenset()

        normalized_now = self._normalize_datetime(now) or now
        remaining = max(0, batch_size)
        stats = RetentionRunStats()
        if remaining == 0:
            return stats
        if lease is not None and lease_seconds is None:
            raise ValueError("lease_seconds is required when lease context is provided")

        while remaining > 0:
            self._renew_retention_lease_or_raise(lease=lease, lease_seconds=lease_seconds, lease_now=lease_now)
            chunk_limit = min(remaining, self._RETENTION_LEASE_RENEWAL_BATCH)
            chunk_stats = self._run_superseded_memory_retention_chunk(now=normalized_now, limit=chunk_limit)
            stats = self._merge_retention_stats(stats, chunk_stats)
            deleted_count = chunk_stats.deleted_memory_objects
            remaining = max(0, remaining - deleted_count)
            if deleted_count == 0:
                break

        while remaining > 0:
            self._renew_retention_lease_or_raise(lease=lease, lease_seconds=lease_seconds, lease_now=lease_now)
            chunk_stats = self._run_stale_working_memory_retention_chunk(
                now=normalized_now,
                limit=min(remaining, self._RETENTION_LEASE_RENEWAL_BATCH),
                working_types=working_types,
            )
            stats = self._merge_retention_stats(stats, chunk_stats)
            deleted_count = chunk_stats.deleted_memory_objects
            remaining = max(0, remaining - deleted_count)
            if deleted_count == 0:
                break

        if remaining > 0:
            source_scan_budget = max(remaining * 4, remaining)
            while remaining > 0 and source_scan_budget > 0:
                self._renew_retention_lease_or_raise(lease=lease, lease_seconds=lease_seconds, lease_now=lease_now)
                chunk_limit = min(remaining, self._RETENTION_LEASE_RENEWAL_BATCH)
                scan_limit = min(max(chunk_limit * 4, chunk_limit), source_scan_budget)
                chunk_stats, scanned_count = self._run_source_item_retention_chunk(
                    now=normalized_now,
                    delete_limit=chunk_limit,
                    scan_limit=scan_limit,
                    durable_types=durable_types,
                    working_types=working_types,
                    orphan_delete_types=orphan_delete_types,
                )
                stats = self._merge_retention_stats(stats, chunk_stats)
                remaining = max(0, remaining - chunk_stats.deleted_source_items)
                source_scan_budget = max(0, source_scan_budget - scanned_count)
                if scanned_count == 0:
                    break

        if remaining > 0:
            self._renew_retention_lease_or_raise(lease=lease, lease_seconds=lease_seconds, lease_now=lease_now)
            stats = self._merge_retention_stats(
                stats,
                self._run_debug_metadata_stripping_chunk(
                    now=normalized_now,
                    limit=min(remaining, self._RETENTION_LEASE_RENEWAL_BATCH),
                ),
            )

        return stats

    def _run_superseded_memory_retention_chunk(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> RetentionRunStats:
        if limit <= 0:
            return RetentionRunStats()
        with self._session_factory.begin() as session:
            superseded_cutoff = now - SUPERSEDED_MEMORY_TTL
            records = session.scalars(
                select(MemoryObjectRecord)
                .where(
                    MemoryObjectRecord.lifecycle == "superseded",
                    or_(MemoryObjectRecord.freshness_at == None, MemoryObjectRecord.freshness_at <= superseded_cutoff),
                )
                .order_by(MemoryObjectRecord.freshness_at.asc(), MemoryObjectRecord.created_at.asc(), MemoryObjectRecord.id.asc())
                .limit(limit)
            ).all()
            stats = RetentionRunStats()
            for record in records:
                stats = self._merge_retention_stats(stats, self._delete_memory_object_cascade_in_session(session, record.id))
            return stats

    def _run_stale_working_memory_retention_chunk(
        self,
        *,
        now: datetime,
        limit: int,
        working_types: frozenset[str],
    ) -> RetentionRunStats:
        if limit <= 0:
            return RetentionRunStats()
        with self._session_factory.begin() as session:
            stale_cutoff = now - WORKING_MEMORY_TTL
            scan_limit = max(limit * 4, limit)
            records = session.scalars(
                select(MemoryObjectRecord)
                .where(
                    MemoryObjectRecord.lifecycle == "active",
                    MemoryObjectRecord.type.in_(tuple(working_types)),
                )
                .order_by(
                    func.coalesce(MemoryObjectRecord.freshness_at, MemoryObjectRecord.created_at).asc(),
                    MemoryObjectRecord.created_at.asc(),
                    MemoryObjectRecord.id.asc(),
                )
                .limit(scan_limit)
            ).all()
            deleted_count = 0
            stats = RetentionRunStats()
            for record in records:
                if deleted_count >= limit:
                    break
                freshness_at = self._resolve_memory_object_freshness_in_session(session, record)
                if freshness_at is None or freshness_at > stale_cutoff:
                    continue
                stats = self._merge_retention_stats(stats, self._delete_memory_object_cascade_in_session(session, record.id))
                deleted_count += 1
            return stats

    def _run_source_item_retention_chunk(
        self,
        *,
        now: datetime,
        delete_limit: int,
        scan_limit: int,
        durable_types: frozenset[str],
        working_types: frozenset[str],
        orphan_delete_types: frozenset[str],
    ) -> tuple[RetentionRunStats, int]:
        if delete_limit <= 0 or scan_limit <= 0:
            return RetentionRunStats(), 0
        with self._session_factory.begin() as session:
            maintenance_record, candidates = self._next_source_retention_candidates_in_session(session, now=now, limit=scan_limit)
            stats = RetentionRunStats()
            deleted_sources = 0
            scanned_count = 0
            last_scanned_record: SourceItemRecord | None = None
            for record in candidates:
                scanned_count += 1
                last_scanned_record = record
                if not self._source_item_raw_ttl_expired(record, now=now):
                    if deleted_sources >= delete_limit:
                        break
                    continue
                if self._source_item_has_active_lease(record, now=now):
                    if deleted_sources >= delete_limit:
                        break
                    continue
                if self._source_item_is_protected(session, record.id, now=now, durable_types=durable_types, working_types=working_types):
                    stats = self._merge_retention_stats(stats, RetentionRunStats(skipped_protected_source_items=1))
                    if deleted_sources >= delete_limit:
                        break
                    continue
                stats = self._merge_retention_stats(stats, self._delete_source_item_cascade_in_session(session, record.id, durable_types=durable_types, working_types=working_types, orphan_delete_types=orphan_delete_types))
                deleted_sources += 1
                if deleted_sources >= delete_limit:
                    break
            if last_scanned_record is not None:
                self._set_source_scan_cursor_in_session(maintenance_record, last_scanned_record)
            return stats, scanned_count

    def _run_debug_metadata_stripping_chunk(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> RetentionRunStats:
        if limit <= 0:
            return RetentionRunStats()
        with self._session_factory.begin() as session:
            records = session.scalars(
                select(SourceItemRecord)
                .where(SourceItemRecord.created_at <= now - DEBUG_METADATA_TTL)
                .order_by(SourceItemRecord.created_at.asc(), SourceItemRecord.id.asc())
                .limit(limit)
            ).all()
            stats = RetentionRunStats()
            for record in records:
                metadata = self._loads(record.metadata_json)
                if OBSERVABILITY_METADATA_KEY not in metadata:
                    continue
                metadata.pop(OBSERVABILITY_METADATA_KEY, None)
                record.metadata_json = self._dumps(metadata)
                stats = self._merge_retention_stats(stats, RetentionRunStats(stripped_debug_metadata=1))
            return stats

    def _ensure_maintenance_state_record_in_session(
        self,
        session: Session,
        key: str,
        now: datetime,
    ) -> MaintenanceStateRecord:
        record = session.get(MaintenanceStateRecord, key)
        if record is not None:
            return record
        record = MaintenanceStateRecord(
            key=key,
            claimed_by=None,
            claimed_at=None,
            lease_expires_at=None,
            last_run_started_at=None,
            last_run_completed_at=None,
            last_run_stats_json=None,
            source_scan_cursor_created_at=None,
            source_scan_cursor_id=None,
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        session.flush()
        return record

    def _retention_lease_owned_in_session(
        self,
        session: Session,
        *,
        worker_id: str,
        claimed_at: datetime,
        now: datetime,
        allow_expired: bool,
    ) -> bool:
        record = session.get(MaintenanceStateRecord, RETENTION_MAINTENANCE_KEY)
        if record is None:
            return False
        record_claimed_at = self._normalize_datetime(record.claimed_at)
        lease_expires_at = self._normalize_datetime(record.lease_expires_at)
        if record.claimed_by != worker_id or record_claimed_at != claimed_at or lease_expires_at is None:
            return False
        if not allow_expired and lease_expires_at <= now:
            return False
        return True

    def _renew_retention_lease_or_raise(
        self,
        *,
        lease: RetentionLease | None,
        lease_seconds: int | None,
        lease_now: datetime | None,
    ) -> None:
        if lease is None:
            return
        if lease_seconds is None:
            raise ValueError("lease_seconds is required when lease context is provided")
        renewed = self.renew_retention_lease(
            worker_id=lease.claimed_by,
            claimed_at=lease.claimed_at,
            lease_seconds=lease_seconds,
            now=lease_now or utc_now(),
        )
        if renewed is None:
            raise RetentionLeaseLostError("retention lease lost during pass")

    def _next_source_retention_candidates_in_session(
        self,
        session: Session,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[MaintenanceStateRecord, list[SourceItemRecord]]:
        maintenance_record = self._ensure_maintenance_state_record_in_session(session, RETENTION_MAINTENANCE_KEY, now)
        if limit <= 0:
            return maintenance_record, []
        cursor_created_at = self._normalize_datetime(maintenance_record.source_scan_cursor_created_at)
        cursor_id = maintenance_record.source_scan_cursor_id
        statement = (
            select(SourceItemRecord)
            .where(SourceItemRecord.processing_status.in_(("completed", "failed", "skipped")))
            .order_by(SourceItemRecord.created_at.asc(), SourceItemRecord.id.asc())
        )
        if cursor_created_at is not None and cursor_id:
            statement = statement.where(
                or_(
                    SourceItemRecord.created_at > cursor_created_at,
                    (SourceItemRecord.created_at == cursor_created_at) & (SourceItemRecord.id > cursor_id),
                )
            )
        records = session.scalars(statement.limit(limit)).all()
        if not records and cursor_created_at is not None and cursor_id:
            self._clear_source_scan_cursor_in_session(maintenance_record)
            return maintenance_record, []
        return maintenance_record, records

    @staticmethod
    def _set_source_scan_cursor_in_session(record: MaintenanceStateRecord, source_record: SourceItemRecord) -> None:
        record.source_scan_cursor_created_at = source_record.created_at
        record.source_scan_cursor_id = source_record.id

    @staticmethod
    def _clear_source_scan_cursor_in_session(record: MaintenanceStateRecord) -> None:
        record.source_scan_cursor_created_at = None
        record.source_scan_cursor_id = None

    def _backfill_legacy_memory_freshness(self) -> None:
        with self._session_factory.begin() as session:
            records = session.scalars(
                select(MemoryObjectRecord).where(
                    MemoryObjectRecord.freshness_at.is_(None),
                )
            ).all()
            for record in records:
                self._refresh_memory_object_freshness_in_session(session, record.id)

    def _retention_health_snapshot(
        self,
        record: MaintenanceStateRecord | None,
        *,
        enabled: bool,
    ) -> RetentionHealthSnapshot:
        stats_payload = self._loads(record.last_run_stats_json) if record is not None else {}
        return RetentionHealthSnapshot(
            enabled=enabled,
            last_run_started_at=self._normalize_datetime(record.last_run_started_at) if record is not None else None,
            last_run_completed_at=self._normalize_datetime(record.last_run_completed_at) if record is not None else None,
            last_deleted_source_items=int(stats_payload.get("deleted_source_items", 0) or 0),
            last_deleted_memory_objects=int(stats_payload.get("deleted_memory_objects", 0) or 0),
            last_deleted_relations=int(stats_payload.get("deleted_relations", 0) or 0),
            last_deleted_index_entries=int(stats_payload.get("deleted_index_entries", 0) or 0),
            last_stripped_debug_metadata=int(stats_payload.get("stripped_debug_metadata", 0) or 0),
            last_skipped_protected_source_items=int(stats_payload.get("skipped_protected_source_items", 0) or 0),
        )

    def _refresh_memory_freshness_for_ids_in_session(self, session: Session, memory_object_ids: list[str]) -> None:
        session.flush()
        for memory_object_id in memory_object_ids:
            self._refresh_memory_object_freshness_in_session(session, memory_object_id)

    def _refresh_memory_object_freshness_in_session(self, session: Session, memory_object_id: str) -> datetime | None:
        record = session.get(MemoryObjectRecord, memory_object_id)
        if record is None:
            return None
        freshness_at = self._derive_memory_object_freshness_in_session(session, record)
        record.freshness_at = freshness_at
        return freshness_at

    def _resolve_memory_object_freshness_in_session(
        self,
        session: Session,
        record: MemoryObjectRecord,
    ) -> datetime | None:
        existing = self._normalize_datetime(record.freshness_at)
        if existing is not None:
            return existing
        freshness_at = self._derive_memory_object_freshness_in_session(session, record)
        record.freshness_at = freshness_at
        return freshness_at

    def _derive_memory_object_freshness_in_session(
        self,
        session: Session,
        record: MemoryObjectRecord,
    ) -> datetime:
        support_time = self._memory_support_time_in_session(session, record.id)
        created_at = self._normalize_datetime(record.created_at) or utc_now()
        candidates = [created_at]
        existing = self._normalize_datetime(record.freshness_at)
        if existing is not None:
            candidates.append(existing)
        if support_time is not None:
            candidates.append(support_time)
        return max(candidates)

    def _memory_support_time_in_session(self, session: Session, memory_object_id: str) -> datetime | None:
        relations = session.scalars(
            select(RelationRecord).where(
                RelationRecord.from_kind == "memory_object",
                RelationRecord.from_id == memory_object_id,
                RelationRecord.relation_type == "supported_by",
                RelationRecord.to_kind == "source_item",
            )
        ).all()
        latest: datetime | None = None
        for relation in relations:
            source_record = session.get(SourceItemRecord, relation.to_id)
            if source_record is None:
                continue
            effective = self._source_item_effective_time(source_record)
            if latest is None or effective > latest:
                latest = effective
        return latest

    def _source_item_effective_time(self, record: SourceItemRecord) -> datetime:
        return self._normalize_datetime(record.occurred_at) or self._normalize_datetime(record.created_at) or utc_now()

    def _source_item_raw_ttl_expired(self, record: SourceItemRecord, *, now: datetime) -> bool:
        ttl = source_item_retention_ttl(
            artifact_kind=record.artifact_kind,
            metadata=self._loads(record.metadata_json),
        )
        return self._source_item_effective_time(record) <= now - ttl

    def _source_item_has_active_lease(self, record: SourceItemRecord, *, now: datetime) -> bool:
        lease_expires_at = self._normalize_datetime(record.processing_lease_expires_at)
        return bool(record.processing_claimed_by) and lease_expires_at is not None and lease_expires_at > now

    def _source_item_is_protected(
        self,
        session: Session,
        source_item_id: str,
        *,
        now: datetime,
        durable_types: frozenset[str],
        working_types: frozenset[str],
    ) -> bool:
        relations = session.scalars(
            select(RelationRecord).where(
                RelationRecord.to_kind == "source_item",
                RelationRecord.to_id == source_item_id,
                RelationRecord.relation_type == "supported_by",
                RelationRecord.from_kind == "memory_object",
            )
        ).all()
        for relation in relations:
            memory_record = session.get(MemoryObjectRecord, relation.from_id)
            if memory_record is None or memory_record.lifecycle != "active":
                continue
            if memory_record.type in durable_types:
                return True
            freshness_at = self._resolve_memory_object_freshness_in_session(session, memory_record)
            if memory_record.type in working_types and freshness_at is not None and freshness_at > now - WORKING_MEMORY_TTL:
                return True
        return False

    def _delete_source_item_cascade_in_session(
        self,
        session: Session,
        source_item_id: str,
        *,
        durable_types: frozenset[str],
        working_types: frozenset[str],
        orphan_delete_types: frozenset[str],
    ) -> RetentionRunStats:
        relation_records = session.scalars(
            select(RelationRecord).where(
                or_(
                    (RelationRecord.to_kind == "source_item") & (RelationRecord.to_id == source_item_id),
                    (RelationRecord.from_kind == "source_item") & (RelationRecord.from_id == source_item_id),
                )
            )
        ).all()
        affected_memory_ids = {
            relation.from_id
            for relation in relation_records
            if relation.from_kind == "memory_object"
        }
        annotation_records = session.scalars(select(AnnotationRecord).where(AnnotationRecord.source_item_id == source_item_id)).all()
        source_index_records = session.scalars(
            select(IndexEntryRecord).where(
                IndexEntryRecord.target_kind == "source_item",
                IndexEntryRecord.target_id == source_item_id,
            )
        ).all()
        source_record = session.get(SourceItemRecord, source_item_id)
        if source_record is None:
            return RetentionRunStats()
        for relation in relation_records:
            session.delete(relation)
        for annotation in annotation_records:
            session.delete(annotation)
        for index_entry in source_index_records:
            session.delete(index_entry)
        session.delete(source_record)
        stats = RetentionRunStats(
            deleted_source_items=1,
            deleted_relations=len(relation_records),
            deleted_index_entries=len(source_index_records),
        )
        for memory_object_id in affected_memory_ids:
            stats = self._merge_retention_stats(stats, self._delete_orphan_memory_object_if_needed_in_session(session, memory_object_id, durable_types=durable_types, working_types=working_types, orphan_delete_types=orphan_delete_types))
        return stats

    def _delete_orphan_memory_object_if_needed_in_session(
        self,
        session: Session,
        memory_object_id: str,
        *,
        durable_types: frozenset[str],
        working_types: frozenset[str],
        orphan_delete_types: frozenset[str],
    ) -> RetentionRunStats:
        memory_record = session.get(MemoryObjectRecord, memory_object_id)
        if memory_record is None:
            return RetentionRunStats()
        if memory_record.type in durable_types or memory_record.type in working_types:
            return RetentionRunStats()
        remaining_support = session.scalar(
            select(RelationRecord.id)
            .where(
                RelationRecord.from_kind == "memory_object",
                RelationRecord.from_id == memory_object_id,
                RelationRecord.relation_type == "supported_by",
                RelationRecord.to_kind == "source_item",
            )
            .limit(1)
        )
        if remaining_support is not None:
            return RetentionRunStats()
        if memory_record.type not in orphan_delete_types and memory_record.lifecycle == "active":
            return RetentionRunStats()
        return self._delete_memory_object_cascade_in_session(session, memory_object_id)

    def _delete_memory_object_cascade_in_session(self, session: Session, memory_object_id: str) -> RetentionRunStats:
        memory_record = session.get(MemoryObjectRecord, memory_object_id)
        if memory_record is None:
            return RetentionRunStats()
        relation_records = session.scalars(
            select(RelationRecord).where(
                or_(
                    (RelationRecord.from_kind == "memory_object") & (RelationRecord.from_id == memory_object_id),
                    (RelationRecord.to_kind == "memory_object") & (RelationRecord.to_id == memory_object_id),
                )
            )
        ).all()
        index_records = session.scalars(
            select(IndexEntryRecord).where(
                IndexEntryRecord.target_kind == "memory_object",
                IndexEntryRecord.target_id == memory_object_id,
            )
        ).all()
        for relation in relation_records:
            session.delete(relation)
        for index_record in index_records:
            session.delete(index_record)
        session.delete(memory_record)
        return RetentionRunStats(
            deleted_memory_objects=1,
            deleted_relations=len(relation_records),
            deleted_index_entries=len(index_records),
        )

    @staticmethod
    def _merge_retention_stats(left: RetentionRunStats, right: RetentionRunStats) -> RetentionRunStats:
        return RetentionRunStats(
            deleted_source_items=left.deleted_source_items + right.deleted_source_items,
            deleted_memory_objects=left.deleted_memory_objects + right.deleted_memory_objects,
            deleted_relations=left.deleted_relations + right.deleted_relations,
            deleted_index_entries=left.deleted_index_entries + right.deleted_index_entries,
            stripped_debug_metadata=left.stripped_debug_metadata + right.stripped_debug_metadata,
            skipped_protected_source_items=left.skipped_protected_source_items + right.skipped_protected_source_items,
        )
