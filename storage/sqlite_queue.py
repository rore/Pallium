from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from core.contracts import ProcessResult, SupersessionHint
from core.visibility import visibility_matches_exact
from core.models import new_id, utc_now
from core.observability import OBSERVABILITY_METADATA_KEY
from core.retention import RETENTION_MAINTENANCE_KEY
from storage.base import (
    LeasedSourceItemInfo,
    LeasedThreadScopeInfo,
    QueueHealthReasonCount,
    QueueHealthSnapshot,
    RecentFailureInfo,
    ThreadProcessingLease,
    ThreadProcessingScope,
)
from storage.sqlite_schema import (
    IndexEntryRecord,
    MaintenanceStateRecord,
    MemoryObjectRecord,
    RelationRecord,
    SourceItemRecord,
    ThreadProcessingLeaseRecord,
)


class SQLiteQueueMixin:
    def claim_next_source_item(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
        now: datetime | None = None,
    ):
        claimed_at = now or utc_now()
        lease_expires_at = claimed_at + timedelta(seconds=max(1, lease_seconds))
        statement = text(
            """
            UPDATE source_items
            SET processing_status = 'processing',
                processing_attempts = COALESCE(processing_attempts, 0) + 1,
                processing_claimed_by = :worker_id,
                processing_claimed_at = :claimed_at,
                processing_lease_expires_at = :lease_expires_at,
                processing_next_attempt_at = NULL
            WHERE id = (
                SELECT id
                FROM source_items
                WHERE use_case IS NOT NULL
                  AND (
                    (processing_status = 'pending'
                        AND COALESCE(processing_attempts, 0) < :max_attempts
                        AND (processing_next_attempt_at IS NULL OR processing_next_attempt_at <= :claimed_at))
                    OR (processing_status = 'failed'
                        AND COALESCE(processing_attempts, 0) < :max_attempts
                        AND processing_next_attempt_at IS NOT NULL
                        AND processing_next_attempt_at <= :claimed_at)
                    OR (processing_status = 'processing'
                        AND COALESCE(processing_attempts, 0) < :max_attempts
                        AND processing_lease_expires_at IS NOT NULL
                        AND processing_lease_expires_at <= :claimed_at)
                  )
                ORDER BY created_at ASC, id ASC
                LIMIT 1
            )
            RETURNING id
            """
        )
        with self._session_factory.begin() as session:
            row = session.execute(
                statement,
                {
                    "worker_id": worker_id,
                    "claimed_at": claimed_at,
                    "lease_expires_at": lease_expires_at,
                    "max_attempts": max_attempts,
                },
            ).first()
            if row is None:
                return None
            record = session.get(SourceItemRecord, row[0])
            if record is None:
                return None
            return self._to_source_item(record)

    def complete_source_item_processing(self, source_item_id: str, *, completed_at: datetime | None = None) -> None:
        finished_at = completed_at or utc_now()
        with self._session_factory.begin() as session:
            record = session.get(SourceItemRecord, source_item_id)
            if record is None:
                raise KeyError(source_item_id)
            record.processing_status = "completed"
            record.processing_completed_at = finished_at
            record.processing_error = None
            record.processing_lease_expires_at = None
            record.processing_next_attempt_at = None

    def fail_source_item_processing(
        self,
        source_item_id: str,
        *,
        error: str,
        next_attempt_at: datetime | None,
        final: bool,
        metadata_updates: dict[str, object] | None = None,
    ) -> None:
        finished_at = utc_now()
        with self._session_factory.begin() as session:
            record = session.get(SourceItemRecord, source_item_id)
            if record is None:
                raise KeyError(source_item_id)
            if metadata_updates:
                existing_metadata = self._loads(record.metadata_json)
                existing_metadata.update(metadata_updates)
                record.metadata_json = self._dumps(existing_metadata)
            record.processing_status = "failed" if final else "pending"
            record.processing_error = error
            record.processing_claimed_by = None
            record.processing_claimed_at = None
            record.processing_lease_expires_at = None
            record.processing_completed_at = finished_at if final else None
            record.processing_next_attempt_at = next_attempt_at

    def commit_processed_source_item(
        self,
        *,
        source_item_id: str,
        result: ProcessResult,
        thread_rebuild_scope: ThreadProcessingScope | None = None,
        completed_at: datetime | None = None,
    ) -> list[tuple[str, str]]:
        finished_at = completed_at or utc_now()
        with self._session_factory.begin() as session:
            self._persist_process_result_in_session(session, result)
            supersession_pairs = self._resolve_supersession_pairs_in_session(session, result)
            self._apply_supersession_pairs_in_session(session, supersession_pairs)
            self._apply_source_item_metadata_updates_in_session(session, result.source_item_metadata_updates)
            self._refresh_memory_freshness_for_ids_in_session(session, [memory.id for memory in result.memory_objects])
            if thread_rebuild_scope is not None:
                self._upsert_thread_processing_scope_in_session(
                    session,
                    scope=thread_rebuild_scope,
                    requested_at=finished_at,
                )
            self._after_commit_processed_source_item_persist(
                session,
                source_item_id=source_item_id,
                result=result,
                supersession_pairs=supersession_pairs,
            )
            record = session.get(SourceItemRecord, source_item_id)
            if record is None:
                raise KeyError(source_item_id)
            record.processing_status = "completed"
            record.processing_completed_at = finished_at
            record.processing_error = None
            record.processing_claimed_by = None
            record.processing_claimed_at = None
            record.processing_lease_expires_at = None
            record.processing_next_attempt_at = None
        return supersession_pairs

    def commit_process_result(
        self,
        *,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]] | None = None,
    ) -> list[tuple[str, str]]:
        with self._session_factory.begin() as session:
            self._persist_process_result_in_session(session, result)
            resolved_pairs = self._resolve_supersession_pairs_in_session(session, result)
            all_pairs = resolved_pairs + (supersession_pairs or [])
            self._apply_supersession_pairs_in_session(session, all_pairs)
            self._apply_source_item_metadata_updates_in_session(session, result.source_item_metadata_updates)
            self._refresh_memory_freshness_for_ids_in_session(session, [memory.id for memory in result.memory_objects])
        return all_pairs

    def commit_process_result_and_complete_scope(
        self,
        *,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]] | None = None,
        scope_key: str,
        worker_id: str,
        claimed_at: datetime,
        completed_at: datetime | None = None,
    ) -> bool:
        finished_at = completed_at or utc_now()
        normalized_claimed_at = self._normalize_datetime(claimed_at) or claimed_at
        with self._session_factory.begin() as session:
            self._persist_process_result_in_session(session, result)
            resolved_pairs = self._resolve_supersession_pairs_in_session(session, result)
            all_pairs = resolved_pairs + (supersession_pairs or [])
            self._apply_supersession_pairs_in_session(session, all_pairs)
            self._apply_source_item_metadata_updates_in_session(session, result.source_item_metadata_updates)
            self._refresh_memory_freshness_for_ids_in_session(session, [memory.id for memory in result.memory_objects])

            record = session.get(ThreadProcessingLeaseRecord, scope_key)
            if record is None:
                raise KeyError(scope_key)
            record_claimed_at = self._normalize_datetime(record.processing_claimed_at)
            if record.processing_claimed_by != worker_id or record_claimed_at != normalized_claimed_at:
                return record.requested_at is not None
            requested_at = self._normalize_datetime(record.requested_at)
            pending_after = requested_at is not None and requested_at > normalized_claimed_at
            if not pending_after:
                record.requested_at = None
            record.processing_completed_at = finished_at
            record.processing_claimed_by = None
            record.processing_claimed_at = None
            record.processing_lease_expires_at = None
            record.updated_at = finished_at
            return pending_after

    def claim_thread_processing_scope(
        self,
        *,
        scope: ThreadProcessingScope,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> ThreadProcessingLease | None:
        claimed_at = now or utc_now()
        lease_expires_at = claimed_at + timedelta(seconds=max(1, lease_seconds))
        statement = text(
            """
            UPDATE thread_processing_leases
            SET processing_claimed_by = :worker_id,
                processing_claimed_at = :claimed_at,
                processing_lease_expires_at = :lease_expires_at,
                updated_at = :claimed_at
            WHERE scope_key = :scope_key
              AND requested_at IS NOT NULL
              AND (processing_lease_expires_at IS NULL OR processing_lease_expires_at <= :claimed_at)
            RETURNING scope_key
            """
        )
        with self._session_factory.begin() as session:
            row = session.execute(
                statement,
                {
                    "scope_key": scope.scope_key,
                    "worker_id": worker_id,
                    "claimed_at": claimed_at,
                    "lease_expires_at": lease_expires_at,
                },
            ).first()
            if row is None:
                return None
            record = session.get(ThreadProcessingLeaseRecord, row[0])
            if record is None:
                return None
            return self._to_thread_processing_lease(record)

    def claim_next_thread_processing_scope(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> ThreadProcessingLease | None:
        claimed_at = now or utc_now()
        lease_expires_at = claimed_at + timedelta(seconds=max(1, lease_seconds))
        statement = text(
            """
            UPDATE thread_processing_leases
            SET processing_claimed_by = :worker_id,
                processing_claimed_at = :claimed_at,
                processing_lease_expires_at = :lease_expires_at,
                updated_at = :claimed_at
            WHERE scope_key = (
                SELECT scope_key
                FROM thread_processing_leases
                WHERE requested_at IS NOT NULL
                  AND (processing_lease_expires_at IS NULL OR processing_lease_expires_at <= :claimed_at)
                ORDER BY requested_at ASC, created_at ASC, scope_key ASC
                LIMIT 1
            )
            RETURNING scope_key
            """
        )
        with self._session_factory.begin() as session:
            row = session.execute(
                statement,
                {
                    "worker_id": worker_id,
                    "claimed_at": claimed_at,
                    "lease_expires_at": lease_expires_at,
                },
            ).first()
            if row is None:
                return None
            record = session.get(ThreadProcessingLeaseRecord, row[0])
            if record is None:
                return None
            return self._to_thread_processing_lease(record)

    def complete_thread_processing_scope(
        self,
        *,
        scope_key: str,
        worker_id: str,
        claimed_at: datetime,
        completed_at: datetime | None = None,
    ) -> bool:
        finished_at = completed_at or utc_now()
        normalized_claimed_at = self._normalize_datetime(claimed_at) or claimed_at
        with self._session_factory.begin() as session:
            record = session.get(ThreadProcessingLeaseRecord, scope_key)
            if record is None:
                raise KeyError(scope_key)
            record_claimed_at = self._normalize_datetime(record.processing_claimed_at)
            if record.processing_claimed_by != worker_id or record_claimed_at != normalized_claimed_at:
                return record.requested_at is not None
            requested_at = self._normalize_datetime(record.requested_at)
            pending_after = requested_at is not None and requested_at > normalized_claimed_at
            if not pending_after:
                record.requested_at = None
            record.processing_completed_at = finished_at
            record.processing_claimed_by = None
            record.processing_claimed_at = None
            record.processing_lease_expires_at = None
            record.updated_at = finished_at
            return pending_after

    def get_queue_health_snapshot(
        self,
        *,
        now: datetime,
        max_attempts: int,
        known_use_cases: tuple[str, ...],
        scoped_use_cases: tuple[str, ...],
        retention_enabled: bool,
        recent_failure_limit: int = 10,
    ) -> QueueHealthSnapshot:
        normalized_now = self._normalize_datetime(now) or now
        known_use_case_set = set(known_use_cases)
        scoped_use_case_set = set(scoped_use_cases)
        with self._session_factory() as session:
            source_records = session.scalars(select(SourceItemRecord)).all()
            thread_records = session.scalars(select(ThreadProcessingLeaseRecord)).all()
            maintenance_record = session.get(MaintenanceStateRecord, RETENTION_MAINTENANCE_KEY)

        status_counts: dict[str, int] = {}
        pending_without_use_case_count = 0
        unclaimable_counts: dict[str, int] = {}
        oldest_pending_created_at: datetime | None = None
        leased_source_items: list[LeasedSourceItemInfo] = []
        recent_failures: list[RecentFailureInfo] = []

        for record in source_records:
            status = record.processing_status or "pending"
            status_counts[status] = status_counts.get(status, 0) + 1
            created_at = self._normalize_datetime(record.created_at)
            if status == "pending":
                if not record.use_case:
                    pending_without_use_case_count += 1
                if created_at is not None and (oldest_pending_created_at is None or created_at < oldest_pending_created_at):
                    oldest_pending_created_at = created_at
                reason = self._classify_unclaimable_pending_reason(
                    record,
                    now=normalized_now,
                    max_attempts=max_attempts,
                    known_use_cases=known_use_case_set,
                    scoped_use_cases=scoped_use_case_set,
                )
                if reason is not None:
                    unclaimable_counts[reason] = unclaimable_counts.get(reason, 0) + 1
            lease_expires_at = self._normalize_datetime(record.processing_lease_expires_at)
            if status == "processing" and lease_expires_at is not None and lease_expires_at > normalized_now:
                leased_source_items.append(
                    LeasedSourceItemInfo(
                        source_item_id=record.id,
                        use_case=record.use_case,
                        processing_claimed_by=record.processing_claimed_by,
                        processing_claimed_at=self._normalize_datetime(record.processing_claimed_at),
                        processing_lease_expires_at=lease_expires_at,
                    )
                )
            if status == "failed":
                observability_state = self._observability_state_from_metadata(record.metadata_json)
                recent_failures.append(
                    RecentFailureInfo(
                        source_item_id=record.id,
                        use_case=record.use_case,
                        failure_category=(
                            str(observability_state.get("failure_category"))
                            if observability_state.get("failure_category") is not None
                            else None
                        ),
                        processing_error=record.processing_error,
                        processing_attempts=record.processing_attempts or 0,
                        processing_completed_at=self._normalize_datetime(record.processing_completed_at),
                    )
                )

        leased_thread_scopes = [
            LeasedThreadScopeInfo(
                scope_key=record.scope_key,
                use_case=record.use_case,
                container_ref=record.container_ref,
                thread_ref=record.thread_ref,
                visibility=record.visibility or "private",
                processing_claimed_by=record.processing_claimed_by,
                processing_claimed_at=self._normalize_datetime(record.processing_claimed_at),
                processing_lease_expires_at=self._normalize_datetime(record.processing_lease_expires_at),
            )
            for record in thread_records
            if record.processing_claimed_by is not None
            and (self._normalize_datetime(record.processing_lease_expires_at) or normalized_now) > normalized_now
        ]
        recent_failures.sort(
            key=lambda item: (item.processing_completed_at or datetime.min.replace(tzinfo=timezone.utc), item.source_item_id),
            reverse=True,
        )
        oldest_pending_age_seconds = None
        if oldest_pending_created_at is not None:
            oldest_pending_age_seconds = max(0, int((normalized_now - oldest_pending_created_at).total_seconds()))
        return QueueHealthSnapshot(
            status_counts=dict(sorted(status_counts.items())),
            oldest_pending_age_seconds=oldest_pending_age_seconds,
            pending_without_use_case_count=pending_without_use_case_count,
            unclaimable_pending_counts=tuple(
                QueueHealthReasonCount(reason=reason, count=count)
                for reason, count in sorted(unclaimable_counts.items())
            ),
            leased_source_items=tuple(
                sorted(
                    leased_source_items,
                    key=lambda item: (
                        item.processing_claimed_at or datetime.min.replace(tzinfo=timezone.utc),
                        item.source_item_id,
                    ),
                )
            ),
            leased_thread_scopes=tuple(
                sorted(
                    leased_thread_scopes,
                    key=lambda item: (
                        item.processing_claimed_at or datetime.min.replace(tzinfo=timezone.utc),
                        item.scope_key,
                    ),
                )
            ),
            recent_failures=tuple(recent_failures[:recent_failure_limit]),
            retention=self._retention_health_snapshot(maintenance_record, enabled=retention_enabled),
        )

    def _persist_process_result_in_session(self, session: Session, result: ProcessResult) -> None:
        for memory_object in result.memory_objects:
            session.add(
                MemoryObjectRecord(
                    id=memory_object.id,
                    type=memory_object.type,
                    schema_id=memory_object.schema_id,
                    schema_version=memory_object.schema_version,
                    payload_json=self._dumps(memory_object.payload) or "{}",
                    envelope_json=self._dump_memory_envelope(memory_object.envelope),
                    lifecycle=memory_object.lifecycle,
                    visibility=memory_object.visibility,
                    container_ref=memory_object.container_ref,
                    actor_ref=memory_object.actor_ref,
                    freshness_at=self._normalize_datetime(memory_object.freshness_at) or memory_object.created_at,
                    created_at=memory_object.created_at,
                )
            )
        for relation in result.relations:
            session.add(
                RelationRecord(
                    id=relation.id,
                    from_kind=relation.from_kind,
                    from_id=relation.from_id,
                    relation_type=relation.relation_type,
                    to_kind=relation.to_kind,
                    to_id=relation.to_id,
                )
            )
        for index_entry in result.index_entries:
            session.add(
                IndexEntryRecord(
                    id=index_entry.id,
                    target_kind=index_entry.target_kind,
                    target_id=index_entry.target_id,
                    index_type=index_entry.index_type,
                    text_view=index_entry.text_view,
                    text_view_name=index_entry.text_view_name,
                    provider_name=index_entry.provider_name,
                    provider_version=index_entry.provider_version,
                )
            )

    def _apply_supersession_pairs_in_session(self, session: Session, supersession_pairs: list[tuple[str, str]]) -> None:
        for superseded_id, replacement_id in supersession_pairs:
            superseded = session.get(MemoryObjectRecord, superseded_id)
            replacement = session.get(MemoryObjectRecord, replacement_id)
            if superseded is None or replacement is None:
                raise KeyError(superseded_id if superseded is None else replacement_id)
            if superseded.type != replacement.type:
                raise ValueError("Supersession requires matching memory object types")
            if superseded.lifecycle == "superseded":
                continue
            superseded.lifecycle = "superseded"
            session.add(
                RelationRecord(
                    id=new_id(),
                    from_kind="memory_object",
                    from_id=replacement_id,
                    relation_type="supersedes",
                    to_kind="memory_object",
                    to_id=superseded_id,
                )
            )

    def _resolve_supersession_pairs_in_session(
        self,
        session: Session,
        result: ProcessResult,
    ) -> list[tuple[str, str]]:
        if not result.supersession_hints:
            return []
        replacements = {memory_object.id: memory_object for memory_object in result.memory_objects}
        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for hint in result.supersession_hints:
            replacement = replacements.get(hint.replacement_memory_id)
            if replacement is None:
                continue
            if not hint.container_ref or not hint.thread_ref or not hint.canonical_key:
                continue
            thread_item_records = session.scalars(
                select(SourceItemRecord).where(
                    SourceItemRecord.container_ref == hint.container_ref,
                    SourceItemRecord.thread_ref == hint.thread_ref,
                )
            ).all()
            for item_record in thread_item_records:
                if not visibility_matches_exact(item_record.visibility, hint.visibility):
                    continue
                relation_records = session.scalars(
                    select(RelationRecord).where(
                        RelationRecord.relation_type == "supported_by",
                        RelationRecord.to_kind == "source_item",
                        RelationRecord.to_id == item_record.id,
                        RelationRecord.from_kind == "memory_object",
                    )
                ).all()
                memory_object_ids = [r.from_id for r in relation_records]
                if not memory_object_ids:
                    continue
                candidate_records = session.scalars(
                    select(MemoryObjectRecord).where(MemoryObjectRecord.id.in_(memory_object_ids))
                ).all()
                for candidate_record in candidate_records:
                    candidate = self._to_memory_object(candidate_record)
                    if candidate.id == replacement.id:
                        continue
                    if candidate.lifecycle != "active" or candidate.type != hint.memory_type:
                        continue
                    if not visibility_matches_exact(candidate.visibility, hint.visibility):
                        continue
                    candidate_key = str(candidate.payload.get("canonical_key") or "").strip()
                    if candidate_key != hint.canonical_key:
                        continue
                    pair = (candidate.id, replacement.id)
                    if pair in seen:
                        continue
                    seen.add(pair)
                    pairs.append(pair)
        return pairs

    def _apply_source_item_metadata_updates_in_session(
        self,
        session: Session,
        metadata_updates: dict[str, dict[str, object]],
    ) -> None:
        for source_item_id, metadata_patch in metadata_updates.items():
            record = session.get(SourceItemRecord, source_item_id)
            if record is None:
                raise KeyError(source_item_id)
            existing_metadata = self._loads(record.metadata_json)
            if not isinstance(existing_metadata, dict):
                existing_metadata = {}
            for key, value in metadata_patch.items():
                if isinstance(value, dict) and isinstance(existing_metadata.get(key), dict):
                    merged_value = dict(existing_metadata[key])
                    merged_value.update(value)
                    existing_metadata[key] = merged_value
                else:
                    existing_metadata[key] = value
            record.metadata_json = self._dumps(existing_metadata)

    def update_source_item_metadata(self, source_item_id: str, metadata_patch: dict[str, object]) -> None:
        with self._session_factory.begin() as session:
            self._apply_source_item_metadata_updates_in_session(session, {source_item_id: metadata_patch})

    def _upsert_thread_processing_scope_in_session(
        self,
        session: Session,
        *,
        scope: ThreadProcessingScope,
        requested_at: datetime,
    ) -> None:
        record = session.get(ThreadProcessingLeaseRecord, scope.scope_key)
        if record is None:
            session.add(
                ThreadProcessingLeaseRecord(
                    scope_key=scope.scope_key,
                    use_case=scope.use_case,
                    container_ref=scope.container_ref,
                    thread_ref=scope.thread_ref,
                    visibility=scope.visibility,
                    requested_at=requested_at,
                    processing_claimed_by=None,
                    processing_claimed_at=None,
                    processing_lease_expires_at=None,
                    processing_completed_at=None,
                    created_at=requested_at,
                    updated_at=requested_at,
                )
            )
            return
        existing_requested_at = self._normalize_datetime(record.requested_at)
        if existing_requested_at is None or requested_at > existing_requested_at:
            record.requested_at = requested_at
        record.updated_at = requested_at

    def _observability_state_from_metadata(self, metadata_json: str | None) -> dict[str, object]:
        metadata = self._loads(metadata_json)
        state = metadata.get(OBSERVABILITY_METADATA_KEY)
        return state if isinstance(state, dict) else {}

    def _classify_unclaimable_pending_reason(
        self,
        record: SourceItemRecord,
        *,
        now: datetime,
        max_attempts: int,
        known_use_cases: set[str],
        scoped_use_cases: set[str],
    ) -> str | None:
        if (record.processing_status or "pending") != "pending":
            return None
        if not record.use_case:
            return "missing_use_case"
        if (record.processing_attempts or 0) >= max_attempts:
            return "legacy_max_attempts_exhausted_pending"
        next_attempt_at = self._normalize_datetime(record.processing_next_attempt_at)
        if next_attempt_at is not None and next_attempt_at > now:
            return "retry_backoff_active"
        if record.use_case not in known_use_cases:
            return "unknown_use_case"
        if record.use_case in scoped_use_cases and not record.visibility:
            return "missing_visibility_for_scoped_use_case"
        return None

