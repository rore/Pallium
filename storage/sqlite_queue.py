from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from core.contracts import ProcessResult, PromotionHint, SupersessionHint
from core.errors import ImmediateTransactionBusyError, is_transient_error
from core.visibility import visibility_matches_exact
from core.models import new_id, utc_now
from core.observability import OBSERVABILITY_METADATA_KEY
from core.retention import RETENTION_MAINTENANCE_KEY
from storage.sqlite_codec import extract_memory_subject
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
    OperationalFactPromotionLogRecord,
    PackageProcessingStatusRecord,
    RelationRecord,
    SourceItemRecord,
    ThreadProcessingLeaseRecord,
    insert_lexical_fts_row,
)

_CONTAINER_SCOPED_SUPERSESSION_TYPES = frozenset({
    "constraint_memory",
    "decision",
    "investigation_outcome",
})

# PR 4 of the operational_fact redesign (2026-07-02): a slot promotes
# to ``active`` once at least this many distinct threads support it via
# ``supported_by`` relations to source_items. Two threads = "the same
# question was answered independently twice, so it's a durable fact,
# not a one-off." Default 2, no config knob yet — TODO: read from
# ``pallium.local.toml [operational_fact] promotion_threads`` once the
# config surface stabilizes. Bumping this constant globally is safe;
# lowering it below 2 disables the whole recurrence gate.
PROMOTION_THREAD_THRESHOLD = 2
# Only constraints take the Jaccard-overlap branch. Decisions and
# investigation_outcomes were widened to container scope in T2
# (2026-06-04) but their canonical_key is now
# ``normalize_for_index(decision_text)`` — Jaccard at container scope on
# decision text would risk merging distinct decisions, so they stay on
# exact-equality only.
_JACCARD_ELIGIBLE_TYPES = frozenset({"constraint_memory"})
_CONTAINER_SCOPED_JACCARD_THRESHOLD = 0.5

# Types eligible for container-scoped near-duplicate supersession via
# SequenceMatcher.ratio over canonical_key. Mirrors the per-thread
# similarity logic in semantic/agent_conversation_memory_threads.py
# (build_thread_summary's hint emission). Used when the exact-equality
# and Jaccard branches above don't match — catches LLM paraphrases that
# byte-differ in canonical_key but describe the same finding.
#
# Threshold 0.85 measured against live data
# (evals/injection_policy_2026_06/near_dup_measure.py): high enough that
# legitimate distinct findings stay separate, low enough that the bulk
# of LLM paraphrases collapse. See
# docs/specs/2026-06-28-thread-near-dup-supersession.md.
_SIMILARITY_ELIGIBLE_TYPES = frozenset({"decision", "investigation_outcome"})
_CONTAINER_SCOPED_SIMILARITY_THRESHOLD = 0.85

# Sliding-window cap on the merge-history lists kept on the winner payload
# (`merged_from`, `previous_evidence_text`, `previous_rationale`). Without a
# cap, decisions on a hot thread accumulate evidence variants on every rebuild
# and the active winner's payload_json grows unbounded. Keep-last-K with
# K=16 covers realistic rebuild churn (the live DB shows 2-3 distinct evidence
# variants per group; K=16 gives 5x headroom without unbounded growth).
_MERGE_HISTORY_KEEP_LAST = 16


class SQLiteQueueMixin:
    _IMMEDIATE_ATTEMPTS = 3
    _IMMEDIATE_BUSY_TIMEOUT_MS = 100
    _DEFAULT_BUSY_TIMEOUT_MS = 15_000
    _IMMEDIATE_BACKOFF_SECONDS = 0.05

    @contextmanager
    def _begin_immediate(self):
        """Start a transaction with BEGIN IMMEDIATE for exclusive claim operations.

        SQLite's default DEFERRED transactions don't acquire a write lock until
        the first write statement.  When two processes run an UPDATE-with-subquery
        concurrently, both can evaluate the subquery before either acquires the
        lock, causing double-pickup of the same queue item.

        BEGIN IMMEDIATE acquires a RESERVED lock at transaction start, serialising
        concurrent claim attempts so only one process evaluates the subquery at a
        time.
        """
        session = None
        conn = None
        for attempt in range(self._IMMEDIATE_ATTEMPTS):
            session = self._session_factory()
            try:
                conn = session.connection(execution_options={"isolation_level": "AUTOCOMMIT"})
                conn.execute(text(f"PRAGMA busy_timeout={self._IMMEDIATE_BUSY_TIMEOUT_MS}"))
                conn.execute(text("BEGIN IMMEDIATE"))
                break
            except Exception as exc:
                if conn is not None:
                    try:
                        conn.execute(text(f"PRAGMA busy_timeout={self._DEFAULT_BUSY_TIMEOUT_MS}"))
                    except Exception:
                        pass
                session.close()
                session = None
                conn = None
                if not is_transient_error(exc):
                    raise
                if attempt == self._IMMEDIATE_ATTEMPTS - 1:
                    raise ImmediateTransactionBusyError("database is locked (immediate transaction retry exhausted)") from exc
                time.sleep(self._IMMEDIATE_BACKOFF_SECONDS * (attempt + 1))
        assert session is not None and conn is not None
        try:
            yield session
            session.flush()
            conn.execute(text("COMMIT"))
        except BaseException:
            try:
                conn.execute(text("ROLLBACK"))
            except Exception:
                pass
            raise
        finally:
            try:
                conn.execute(text(f"PRAGMA busy_timeout={self._DEFAULT_BUSY_TIMEOUT_MS}"))
            except Exception:
                pass
            finally:
                session.close()

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
                  AND NOT EXISTS (
                    SELECT 1 FROM package_processing_status pps
                    WHERE pps.source_item_id = source_items.id
                      AND pps.status IN ('pending', 'processing')
                  )
                ORDER BY created_at ASC, id ASC
                LIMIT 1
            )
            RETURNING id
            """
        )
        with self._begin_immediate() as session:
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

        def _do(session):
            record = session.get(SourceItemRecord, source_item_id)
            if record is None:
                raise KeyError(source_item_id)
            record.processing_status = "completed"
            record.processing_completed_at = finished_at
            record.processing_error = None
            record.processing_lease_expires_at = None
            record.processing_next_attempt_at = None

        self._with_retry(_do)

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

        def _do(session):
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

        self._with_retry(_do)

    def retry_failed_source_items(self, *, failure_category: str, limit: int) -> dict[str, int]:
        """Requeue terminal failures in one transaction without rerunning completed packages."""
        def _do(session):
            retried_sources = 0
            retried_packages = 0
            records = session.scalars(
                select(SourceItemRecord)
                .where(
                    SourceItemRecord.processing_status == "failed",
                    func.json_extract(
                        SourceItemRecord.metadata_json,
                        f"$.{OBSERVABILITY_METADATA_KEY}.failure_category",
                    ) == failure_category,
                )
                .order_by(SourceItemRecord.processing_completed_at, SourceItemRecord.id)
                .limit(limit)
            ).all()
            for record in records:
                observability = self._observability_state_from_metadata(record.metadata_json)
                packages = session.scalars(
                    select(PackageProcessingStatusRecord).where(
                        PackageProcessingStatusRecord.source_item_id == record.id
                    )
                ).all()
                failed_packages = [package for package in packages if package.status == "failed"]
                if packages and not failed_packages:
                    continue
                for package in failed_packages:
                    package.status = "pending"
                    package.attempts = 0
                    package.error = None
                    package.claimed_by = None
                    package.claimed_at = None
                    package.lease_expires_at = None
                    package.completed_at = None
                    package.next_attempt_at = None
                    retried_packages += 1
                observability["failure_category"] = None
                metadata = self._loads(record.metadata_json)
                metadata[OBSERVABILITY_METADATA_KEY] = observability
                record.metadata_json = self._dumps(metadata)
                record.processing_status = "pending"
                record.processing_attempts = sum(package.attempts or 0 for package in packages)
                record.processing_error = None
                record.processing_claimed_by = None
                record.processing_claimed_at = None
                record.processing_lease_expires_at = None
                record.processing_completed_at = None
                record.processing_next_attempt_at = None
                retried_sources += 1
                if retried_sources >= limit:
                    break
            return {"source_items": retried_sources, "package_tasks": retried_packages}

        return self._with_retry(_do)

    def commit_processed_source_item(
        self,
        *,
        source_item_id: str,
        result: ProcessResult,
        thread_rebuild_scope: ThreadProcessingScope | None = None,
        container_rebuild_scope: ThreadProcessingScope | None = None,
        completed_at: datetime | None = None,
    ) -> list[tuple[str, str]]:
        finished_at = completed_at or utc_now()

        def _do(session):
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
            if container_rebuild_scope is not None:
                self._upsert_thread_processing_scope_in_session(
                    session,
                    scope=container_rebuild_scope,
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

        return self._with_retry(_do)

    def commit_process_result(
        self,
        *,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]] | None = None,
    ) -> list[tuple[str, str]]:
        def _do(session):
            self._persist_process_result_in_session(session, result)
            resolved_pairs = self._resolve_supersession_pairs_in_session(session, result)
            all_pairs = resolved_pairs + (supersession_pairs or [])
            self._apply_supersession_pairs_in_session(session, all_pairs)
            self._apply_source_item_metadata_updates_in_session(session, result.source_item_metadata_updates)
            self._refresh_memory_freshness_for_ids_in_session(session, [memory.id for memory in result.memory_objects])
            return all_pairs

        return self._with_retry(_do)

    def commit_process_result_and_complete_scope(
        self,
        *,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]] | None = None,
        scope_key: str,
        worker_id: str,
        claimed_at: datetime,
        completed_at: datetime | None = None,
        collection_watermark_at: datetime | None = None,
    ) -> bool:
        finished_at = completed_at or utc_now()
        normalized_claimed_at = self._normalize_datetime(claimed_at) or claimed_at

        def _do(session):
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
            if collection_watermark_at is not None:
                record.collection_watermark_at = collection_watermark_at
            record.updated_at = finished_at
            return pending_after

        return self._with_retry(_do)

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
        with self._begin_immediate() as session:
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
        with self._begin_immediate() as session:
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

        def _do(session):
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

        return self._with_retry(_do)

    def get_thread_processing_lease(self, scope_key: str) -> ThreadProcessingLease | None:
        with self._session_factory() as session:
            record = session.get(ThreadProcessingLeaseRecord, scope_key)
            if record is None:
                return None
            return ThreadProcessingLease(
                scope_key=record.scope_key,
                use_case=record.use_case,
                container_ref=record.container_ref,
                thread_ref=record.thread_ref,
                visibility=record.visibility or "private",
                requested_at=self._normalize_datetime(record.requested_at),
                processing_claimed_by=record.processing_claimed_by,
                processing_claimed_at=self._normalize_datetime(record.processing_claimed_at),
                processing_lease_expires_at=self._normalize_datetime(record.processing_lease_expires_at),
                collection_watermark_at=self._normalize_datetime(record.collection_watermark_at),
            )

    def count_source_items_for_thread_after(
        self,
        *,
        container_ref: str,
        thread_ref: str,
        after_created_at: datetime,
    ) -> int:
        normalized = after_created_at.replace(tzinfo=None) if after_created_at.tzinfo else after_created_at
        with self._session_factory() as session:
            count = session.scalar(
                select(func.count())
                .select_from(SourceItemRecord)
                .where(
                    SourceItemRecord.container_ref == container_ref,
                    SourceItemRecord.thread_ref == thread_ref,
                    SourceItemRecord.created_at > normalized,
                )
            )
            return count or 0

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
            expired_package_lease_source_ids = set(session.scalars(
                select(PackageProcessingStatusRecord.source_item_id).where(
                    PackageProcessingStatusRecord.status == "processing",
                    PackageProcessingStatusRecord.attempts >= max_attempts,
                    PackageProcessingStatusRecord.lease_expires_at.isnot(None),
                    PackageProcessingStatusRecord.lease_expires_at <= normalized_now,
                )
            ).all())
            thread_records = session.scalars(select(ThreadProcessingLeaseRecord)).all()
            maintenance_record = session.get(MaintenanceStateRecord, RETENTION_MAINTENANCE_KEY)

        status_counts: dict[str, int] = {}
        status_counts_24h: dict[str, int] = {}
        pending_without_use_case_count = 0
        unclaimable_counts: dict[str, int] = {}
        oldest_pending_created_at: datetime | None = None
        leased_source_items: list[LeasedSourceItemInfo] = []
        recent_failures: list[RecentFailureInfo] = []
        cutoff_24h = normalized_now - timedelta(hours=24)

        for record in source_records:
            status = record.processing_status or "pending"
            status_counts[status] = status_counts.get(status, 0) + 1
            completed_at = self._normalize_datetime(record.processing_completed_at)
            if completed_at is not None and completed_at >= cutoff_24h:
                status_counts_24h[status] = status_counts_24h.get(status, 0) + 1
            created_at = self._normalize_datetime(record.created_at)
            if status == "pending":
                if not record.use_case:
                    pending_without_use_case_count += 1
                if created_at is not None and (oldest_pending_created_at is None or created_at < oldest_pending_created_at):
                    oldest_pending_created_at = created_at
                reason = (
                    "expired_package_lease_max_attempts"
                    if record.id in expired_package_lease_source_ids
                    else self._classify_unclaimable_pending_reason(
                        record,
                        now=normalized_now,
                        max_attempts=max_attempts,
                        known_use_cases=known_use_case_set,
                        scoped_use_cases=scoped_use_case_set,
                    )
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
            status_counts_24h=dict(sorted(status_counts_24h.items())),
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
                    subject=extract_memory_subject(memory_object),
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
            if index_entry.index_type == "lexical":
                container_ref = self._resolve_container_ref_in_session(
                    session, index_entry.target_kind, index_entry.target_id,
                )
                insert_lexical_fts_row(
                    session,
                    index_entry_id=index_entry.id,
                    target_kind=index_entry.target_kind,
                    target_id=index_entry.target_id,
                    text_view=index_entry.text_view,
                    text_view_name=index_entry.text_view_name,
                    container_ref=container_ref,
                )
        # PR 4 of the operational_fact redesign (2026-07-02): after
        # persisting candidate rows + their ``supported_by`` relations,
        # evaluate every promotion hint inside the SAME session. The
        # freshly-inserted rows are visible to the join
        # ``count_distinct_threads_for_conflict_slot`` so the hint's
        # slot count includes the just-emitted candidate. Any
        # slot that crosses the threshold flips every candidate row in
        # the slot (this hint's candidate plus any prior candidates in
        # the same container/slot) to ``lifecycle="active"`` and writes
        # an audit row.
        if result.promotion_hints:
            self._evaluate_promotion_hints_in_session(session, result.promotion_hints)

    def _evaluate_promotion_hints_in_session(
        self,
        session: Session,
        hints: list[PromotionHint],
    ) -> None:
        """Promote candidate operational_fact rows whose slot has
        crossed :data:`PROMOTION_THREAD_THRESHOLD` distinct
        supporting threads.

        Same-slot hints deduplicate by ``(container_ref, slot_key)``:
        two candidates in one hint list that share a slot only need
        one promotion pass. Promotion updates every candidate row in
        the slot (not just the one referenced by the hint) so a slot
        with 3 pre-existing candidates and 1 new candidate all flip
        together the first time the threshold is met. Idempotent:
        once every candidate in a slot has been promoted, the next
        hint for the same slot no-ops because there are no more
        candidate rows to update.

        Every promotion writes one row per flipped memory to
        ``operational_fact_promotion_log`` with
        ``distinct_threads_count`` set to the witness count at the
        moment of promotion. Rows are append-only.
        """
        from semantic.operational_fact import OPERATIONAL_FACT_TYPE

        # Deduplicate hints by (container, slot). Multiple hints for
        # the same slot only need one promotion pass.
        seen_slots: set[tuple[str, str, str, str, str, str]] = set()
        for hint in hints:
            slot_key = (
                hint.container_ref,
                hint.command_family,
                hint.artifact_role,
                hint.scope_kind,
                hint.scope_ref,
                hint.artifact_normalized,
            )
            if slot_key in seen_slots:
                continue
            seen_slots.add(slot_key)

            distinct_threads = self._count_distinct_threads_for_slot_in_session(
                session,
                container_ref=hint.container_ref,
                command_family=hint.command_family,
                artifact_role=hint.artifact_role,
                scope_kind=hint.scope_kind,
                scope_ref=hint.scope_ref,
                artifact_normalized=hint.artifact_normalized,
                visibility=hint.visibility,
            )
            if distinct_threads < PROMOTION_THREAD_THRESHOLD:
                continue

            # Every candidate row in the same slot for this container
            # AND at the same visibility scope promotes together. This
            # includes the just-emitted candidate (already visible to
            # this session) AND every prior candidate at that
            # visibility that had been accumulating below the
            # threshold. Anti-inflation guard: candidates only —
            # active rows already are active and re-flipping them is
            # a no-op that would still write a spurious audit row.
            # Visibility filter: private/global candidates must NEVER
            # collapse (defense-in-depth with the count query's
            # visibility scoping — plan §Invariants).
            candidate_records = session.scalars(
                select(MemoryObjectRecord).where(
                    MemoryObjectRecord.type == OPERATIONAL_FACT_TYPE,
                    MemoryObjectRecord.container_ref == hint.container_ref,
                    MemoryObjectRecord.visibility == hint.visibility,
                    MemoryObjectRecord.lifecycle == "candidate",
                    MemoryObjectRecord.is_soft_deleted == 0,
                )
            ).all()
            promoted_at = utc_now()
            for record in candidate_records:
                # Re-parse payload_json to filter on the slot key. The
                # SQL WHERE could do this with json_extract, but
                # SQLAlchemy expressions for json_extract are backend-
                # specific — a Python filter on a bounded candidate
                # set (few rows per container) is simpler and just as
                # correct.
                try:
                    payload = json.loads(record.payload_json or "{}")
                except Exception:
                    continue
                if (
                    str(payload.get("command_family") or "") == hint.command_family
                    and str(payload.get("artifact_role") or "") == hint.artifact_role
                    and str(payload.get("scope_kind") or "") == hint.scope_kind
                    and str(payload.get("scope_ref") or "") == hint.scope_ref
                    and str(payload.get("artifact_normalized") or "") == hint.artifact_normalized
                ):
                    record.lifecycle = "active"
                    session.add(
                        OperationalFactPromotionLogRecord(
                            id=new_id(),
                            memory_object_id=record.id,
                            from_lifecycle="candidate",
                            to_lifecycle="active",
                            reason="recurrence_threshold_met",
                            distinct_threads_count=distinct_threads,
                            promoted_at=promoted_at,
                        )
                    )

    def _count_distinct_threads_for_slot_in_session(
        self,
        session: Session,
        *,
        container_ref: str,
        command_family: str,
        artifact_role: str,
        scope_kind: str,
        scope_ref: str,
        artifact_normalized: str,
        visibility: str = "private",
    ) -> int:
        """Session-scoped variant of
        :meth:`SQLiteStorageProvider.count_distinct_threads_for_conflict_slot`.

        Must run within the transaction that just persisted the
        candidate rows and their ``supported_by`` relations — otherwise
        the count is off-by-one.

        Scope isolation: filters on ``visibility`` so a private
        candidate can't count as evidence for a global slot (or vice
        versa).
        """
        from semantic.operational_fact import OPERATIONAL_FACT_TYPE

        row = session.execute(
            text(
                "SELECT COUNT(DISTINCT s.thread_ref) "
                "FROM memory_objects m "
                "JOIN relations r ON r.from_id = m.id "
                "  AND r.relation_type = 'supported_by' "
                "  AND r.from_kind = 'memory_object' "
                "  AND r.to_kind = 'source_item' "
                "JOIN source_items s ON s.id = r.to_id "
                "WHERE m.type = :type "
                "  AND m.container_ref = :container_ref "
                "  AND m.visibility = :visibility "
                "  AND m.lifecycle IN ('candidate', 'active') "
                "  AND m.is_soft_deleted = 0 "
                "  AND json_extract(m.payload_json, '$.command_family') = :command_family "
                "  AND json_extract(m.payload_json, '$.artifact_role') = :artifact_role "
                "  AND json_extract(m.payload_json, '$.scope_kind') = :scope_kind "
                "  AND json_extract(m.payload_json, '$.scope_ref') = :scope_ref "
                "  AND json_extract(m.payload_json, '$.artifact_normalized') = :artifact_normalized "
                "  AND s.thread_ref IS NOT NULL"
            ),
            {
                "type": OPERATIONAL_FACT_TYPE,
                "container_ref": container_ref,
                "visibility": visibility,
                "command_family": command_family,
                "artifact_role": artifact_role,
                "scope_kind": scope_kind,
                "scope_ref": scope_ref,
                "artifact_normalized": artifact_normalized,
            },
        ).one()
        return int(row[0] or 0)

    def _delete_index_entries_for_target_in_session(
        self,
        session: Session,
        target_kind: str,
        target_id: str,
    ) -> int:
        """Delete all index entries for a target within an open session.

        Removes both the IndexEntryRecord and associated FTS5 shadow rows.
        The in-memory vector index is NOT updated here — reconciliation handles gaps.
        """
        records = session.scalars(
            select(IndexEntryRecord).where(
                IndexEntryRecord.target_kind == target_kind,
                IndexEntryRecord.target_id == target_id,
            )
        ).all()
        if not records:
            return 0
        for record in records:
            if record.index_type == "lexical":
                session.execute(
                    text("DELETE FROM lexical_fts WHERE index_entry_id = :id"),
                    {"id": record.id},
                )
            session.delete(record)
        return len(records)

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

            # Merge-not-collapse for decisions/investigations: union the loser's
            # evidence quote, rationale, and supported_by relations onto the
            # winner before flipping lifecycle. Avoids losing the loser's
            # distinct evidence text — see merge_policy.md (T2, 2026-06-04).
            if replacement.type in {"decision", "investigation_outcome"}:
                winner_payload = self._loads(replacement.payload_json)
                loser_payload = self._loads(superseded.payload_json)
                self._merge_decision_payload_into_winner(
                    winner_payload=winner_payload,
                    loser_payload=loser_payload,
                    loser_id=superseded_id,
                )
                replacement.payload_json = self._dumps(winner_payload) or "{}"
                self._reparent_supported_by_relations(
                    session,
                    from_memory_id=superseded_id,
                    to_memory_id=replacement_id,
                )

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
            self._delete_index_entries_for_target_in_session(
                session, "memory_object", superseded_id,
            )

    @staticmethod
    def _merge_decision_payload_into_winner(
        *,
        winner_payload: dict,
        loser_payload: dict,
        loser_id: str,
    ) -> None:
        """Append loser provenance fields onto winner payload in-place.

        Winner schema gains three optional list fields:
          - ``merged_from`` — loser memory ids (deduped, preserves order)
          - ``previous_evidence_text`` — older evidence quotes
          - ``previous_rationale`` — older non-null rationales

        The loser's *own* prior merge-history (``merged_from``,
        ``previous_evidence_text``, ``previous_rationale``) is also unioned
        into the winner so a multi-step chain A→B→C does not lose A's
        evidence when C absorbs B. Transitivity matters for hot rebuild
        chains; without it ``previous_evidence_text`` would only ever
        contain the immediate loser's quote.

        Each list is sliding-window bounded by ``_MERGE_HISTORY_KEEP_LAST``;
        the oldest entries fall off when the cap is reached. This prevents
        unbounded payload growth on hot threads where decisions are rebuilt
        many times with drifting evidence quotes.

        Winner's own ``decision_evidence_text`` / ``rationale`` are unchanged.
        """
        keep = _MERGE_HISTORY_KEEP_LAST

        def _append_unique(target: list, value) -> None:
            if value is None or value == "":
                return
            if value in target:
                return
            target.append(value)

        # merged_from = winner's existing chain + loser's chain + loser id.
        merged_from = list(winner_payload.get("merged_from") or [])
        for prior_id in (loser_payload.get("merged_from") or []):
            _append_unique(merged_from, prior_id)
        _append_unique(merged_from, loser_id)
        winner_payload["merged_from"] = merged_from[-keep:]

        # previous_evidence_text = winner's chain + loser's chain + loser's primary evidence.
        prev_ev = list(winner_payload.get("previous_evidence_text") or [])
        for prior_ev in (loser_payload.get("previous_evidence_text") or []):
            _append_unique(prev_ev, prior_ev)
        loser_evidence = (
            loser_payload.get("decision_evidence_text")
            or loser_payload.get("investigation_evidence_text")
        )
        _append_unique(prev_ev, loser_evidence)
        if prev_ev:
            winner_payload["previous_evidence_text"] = prev_ev[-keep:]

        # previous_rationale = winner's chain + loser's chain + loser's primary rationale.
        prev_r = list(winner_payload.get("previous_rationale") or [])
        for prior_r in (loser_payload.get("previous_rationale") or []):
            _append_unique(prev_r, prior_r)
        _append_unique(prev_r, loser_payload.get("rationale"))
        if prev_r:
            winner_payload["previous_rationale"] = prev_r[-keep:]

    @staticmethod
    def _reparent_supported_by_relations(
        session: Session,
        *,
        from_memory_id: str,
        to_memory_id: str,
    ) -> None:
        """Move ``supported_by`` relations from loser memory to winner memory.

        Deduplicates: if winner already has a ``supported_by`` edge to the same
        ``to_id``, the loser's edge is deleted rather than reparented (a memory
        cannot link to the same source item twice).
        """
        loser_relations = session.scalars(
            select(RelationRecord).where(
                RelationRecord.from_kind == "memory_object",
                RelationRecord.from_id == from_memory_id,
                RelationRecord.relation_type == "supported_by",
            )
        ).all()
        if not loser_relations:
            return
        existing_winner_targets = set(
            session.scalars(
                select(RelationRecord.to_id).where(
                    RelationRecord.from_kind == "memory_object",
                    RelationRecord.from_id == to_memory_id,
                    RelationRecord.relation_type == "supported_by",
                )
            ).all()
        )
        for relation in loser_relations:
            if relation.to_id in existing_winner_targets:
                session.delete(relation)
                continue
            relation.from_id = to_memory_id
            existing_winner_targets.add(relation.to_id)

    def _resolve_supersession_pairs_in_session(
        self,
        session: Session,
        result: ProcessResult,
    ) -> list[tuple[str, str]]:
        if not result.supersession_hints:
            return []
        replacements = {memory_object.id: memory_object for memory_object in result.memory_objects}
        # Exclude every replacement id in this ProcessResult from the
        # existing-record scan, not just the current hint's. Without this,
        # two new memories that share a canonical_key produce reciprocal
        # pairs (A→B and B→A), and `_apply_supersession_pairs_in_session`
        # then flips both — leaving zero active rows for that key. See P1.
        replacement_ids: set[str] = set(replacements.keys())
        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for hint in result.supersession_hints:
            replacement = replacements.get(hint.replacement_memory_id)
            if replacement is None:
                continue
            if not hint.container_ref or not hint.canonical_key:
                continue

            # Container-scoped supersession (for constraint_memory)
            if hint.thread_ref is None and hint.memory_type in _CONTAINER_SCOPED_SUPERSESSION_TYPES:
                existing_records = session.scalars(
                    select(MemoryObjectRecord).where(
                        MemoryObjectRecord.container_ref == hint.container_ref,
                        MemoryObjectRecord.type == hint.memory_type,
                        MemoryObjectRecord.lifecycle == "active",
                        MemoryObjectRecord.id.notin_(replacement_ids),
                    )
                ).all()
                new_key_tokens = set(hint.canonical_key.split()) if hint.canonical_key else set()
                for existing_record in existing_records:
                    # Visibility scope guard: never collapse a memory across visibility
                    # boundaries. Thread-scoped path enforces this via
                    # visibility_matches_exact on the source_item; the container-scoped
                    # path must enforce it on the memory_object directly.
                    if not visibility_matches_exact(existing_record.visibility, hint.visibility):
                        continue
                    existing_payload = self._loads(existing_record.payload_json)
                    existing_key = str(existing_payload.get("canonical_key") or "").strip()
                    if not existing_key:
                        continue
                    # Exact canonical_key match
                    if existing_key == hint.canonical_key:
                        pair = (existing_record.id, hint.replacement_memory_id)
                        if pair not in seen:
                            seen.add(pair)
                            pairs.append(pair)
                        continue
                    # Jaccard overlap on canonical_key tokens (catches paraphrases).
                    # Restricted to constraints — decisions/investigations key on
                    # decision_text and Jaccard at container scope would risk
                    # merging distinct decisions (see T2, 2026-06-04).
                    if hint.memory_type in _JACCARD_ELIGIBLE_TYPES and new_key_tokens:
                        existing_key_tokens = set(existing_key.split())
                        if existing_key_tokens:
                            intersection = new_key_tokens & existing_key_tokens
                            union = new_key_tokens | existing_key_tokens
                            jaccard = len(intersection) / len(union)
                            if jaccard >= _CONTAINER_SCOPED_JACCARD_THRESHOLD:
                                pair = (existing_record.id, hint.replacement_memory_id)
                                if pair not in seen:
                                    seen.add(pair)
                                    pairs.append(pair)
                                continue
                    # SequenceMatcher.ratio on canonical_key (catches paraphrases
                    # of decisions/investigations the LLM produces across rebuilds
                    # OR across per-item extractions on adjacent turns).
                    # Stricter than Jaccard's noun-overlap (which would over-merge
                    # decisions sharing common nouns) — character-level similarity
                    # is the right shape for these types. 2026-06-28 per-item fix.
                    if hint.memory_type in _SIMILARITY_ELIGIBLE_TYPES:
                        sim = SequenceMatcher(None, existing_key, hint.canonical_key).ratio()
                        if sim >= _CONTAINER_SCOPED_SIMILARITY_THRESHOLD:
                            pair = (existing_record.id, hint.replacement_memory_id)
                            if pair not in seen:
                                seen.add(pair)
                                pairs.append(pair)
                continue

            # Thread-scoped supersession (existing behavior for decisions/investigations)
            if not hint.thread_ref:
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
                    # Skip every replacement memory in this ProcessResult, not
                    # just the current hint's replacement. Same reasoning as
                    # the container-scoped path: avoids reciprocal A→B / B→A
                    # supersession that would leave zero active rows. See P1.
                    if candidate.id in replacement_ids:
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
        self._with_retry(lambda session: self._apply_source_item_metadata_updates_in_session(session, {source_item_id: metadata_patch}))

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

    # ── Multi-package processing tracking ──────────────────────────────────

    def create_package_processing_records(
        self,
        source_item_id: str,
        package_names: list[str],
        *,
        skip_packages: list[str] | None = None,
    ) -> None:
        skip_set = set(skip_packages or [])
        now = utc_now()

        def _do(session):
            source_record = session.get(SourceItemRecord, source_item_id)
            source_item_created_at = None
            if source_record is not None:
                source_item_created_at = self._normalize_datetime(source_record.created_at) or source_record.created_at
            for pkg in package_names:
                status = "skipped" if pkg in skip_set else "pending"
                session.add(
                    PackageProcessingStatusRecord(
                        source_item_id=source_item_id,
                        package_name=pkg,
                        status=status,
                        attempts=0,
                        source_item_created_at=source_item_created_at,
                        created_at=now,
                    )
                )

        self._with_retry(_do)

    def _finalize_expired_package_leases_at_attempt_limit(
        self,
        session: Session,
        *,
        now: datetime,
        max_attempts: int,
    ) -> None:
        records = session.scalars(
            select(PackageProcessingStatusRecord).where(
                PackageProcessingStatusRecord.status == "processing",
                PackageProcessingStatusRecord.attempts >= max_attempts,
                PackageProcessingStatusRecord.lease_expires_at.isnot(None),
                PackageProcessingStatusRecord.lease_expires_at <= now,
            )
        ).all()
        source_item_ids = {record.source_item_id for record in records}
        for record in records:
            record.status = "failed"
            record.error = record.error or "processing lease expired after maximum attempts"
            record.claimed_by = None
            record.claimed_at = None
            record.lease_expires_at = None
            record.completed_at = now
            record.next_attempt_at = None
        for source_item_id in source_item_ids:
            self._sync_source_item_if_all_packages_terminal(session, source_item_id, now)

    def claim_next_package_task(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
        now: datetime | None = None,
    ) -> tuple[SourceItem, str, int] | None:
        claimed_at = now or utc_now()
        lease_expires_at = claimed_at + timedelta(seconds=max(1, lease_seconds))
        statement = text(
            """
            UPDATE package_processing_status
            SET status = 'processing',
                attempts = COALESCE(attempts, 0) + 1,
                claimed_by = :worker_id,
                claimed_at = :claimed_at,
                lease_expires_at = :lease_expires_at,
                next_attempt_at = NULL
            WHERE id = (
                SELECT pps.id
                FROM package_processing_status pps
                WHERE (
                    (pps.status = 'pending'
                        AND COALESCE(pps.attempts, 0) < :max_attempts
                        AND (pps.next_attempt_at IS NULL OR pps.next_attempt_at <= :claimed_at))
                    OR (pps.status = 'failed'
                        AND COALESCE(pps.attempts, 0) < :max_attempts
                        AND pps.next_attempt_at IS NOT NULL
                        AND pps.next_attempt_at <= :claimed_at)
                    OR (pps.status = 'processing'
                        AND COALESCE(pps.attempts, 0) < :max_attempts
                        AND pps.lease_expires_at IS NOT NULL
                        AND pps.lease_expires_at <= :claimed_at)
                )
                ORDER BY COALESCE(pps.source_item_created_at, pps.created_at) ASC,
                         pps.source_item_id ASC,
                         pps.package_name ASC
                LIMIT 1
            )
            RETURNING id, source_item_id, package_name
            """
        )
        with self._begin_immediate() as session:
            self._finalize_expired_package_leases_at_attempt_limit(
                session,
                now=claimed_at,
                max_attempts=max_attempts,
            )
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
            source_item_id = row[1]
            package_name = row[2]
            record = session.get(SourceItemRecord, source_item_id)
            if record is None:
                return None
            # Read back the updated attempts count
            pps_record = self._find_package_task_record(session, source_item_id, package_name)
            attempts = pps_record.attempts if pps_record else 1
            return self._to_source_item(record), package_name, attempts

    def claim_next_package_task_for_item(
        self,
        source_item_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
        now: datetime | None = None,
    ) -> tuple[str, int] | None:
        """Claim the next pending package for a specific source_item."""
        claimed_at = now or utc_now()
        lease_expires_at = claimed_at + timedelta(seconds=max(1, lease_seconds))
        statement = text(
            """
            UPDATE package_processing_status
            SET status = 'processing',
                attempts = COALESCE(attempts, 0) + 1,
                claimed_by = :worker_id,
                claimed_at = :claimed_at,
                lease_expires_at = :lease_expires_at,
                next_attempt_at = NULL
            WHERE id = (
                SELECT pps.id
                FROM package_processing_status pps
                WHERE pps.source_item_id = :source_item_id
                  AND (
                    (pps.status = 'pending'
                        AND COALESCE(pps.attempts, 0) < :max_attempts
                        AND (pps.next_attempt_at IS NULL OR pps.next_attempt_at <= :claimed_at))
                    OR (pps.status = 'failed'
                        AND COALESCE(pps.attempts, 0) < :max_attempts
                        AND pps.next_attempt_at IS NOT NULL
                        AND pps.next_attempt_at <= :claimed_at)
                    OR (pps.status = 'processing'
                        AND COALESCE(pps.attempts, 0) < :max_attempts
                        AND pps.lease_expires_at IS NOT NULL
                        AND pps.lease_expires_at <= :claimed_at)
                  )
                ORDER BY pps.package_name ASC
                LIMIT 1
            )
            RETURNING package_name
            """
        )
        with self._begin_immediate() as session:
            self._finalize_expired_package_leases_at_attempt_limit(
                session,
                now=claimed_at,
                max_attempts=max_attempts,
            )
            row = session.execute(
                statement,
                {
                    "source_item_id": source_item_id,
                    "worker_id": worker_id,
                    "claimed_at": claimed_at,
                    "lease_expires_at": lease_expires_at,
                    "max_attempts": max_attempts,
                },
            ).first()
            if row is None:
                return None
            package_name = row[0]
            # Read back the updated attempts count
            pps_record = self._find_package_task_record(session, source_item_id, package_name)
            attempts = pps_record.attempts if pps_record else 1
            return package_name, attempts

    def complete_package_task(
        self,
        source_item_id: str,
        package_name: str,
        *,
        completed_at: datetime | None = None,
    ) -> None:
        finished_at = completed_at or utc_now()

        def _do(session):
            record = self._find_package_task_record(session, source_item_id, package_name)
            if record is None:
                raise KeyError(f"({source_item_id}, {package_name})")
            record.status = "completed"
            record.completed_at = finished_at
            record.error = None
            record.claimed_by = None
            record.claimed_at = None
            record.lease_expires_at = None
            record.next_attempt_at = None
            self._sync_source_item_if_all_packages_terminal(session, source_item_id, finished_at)

        self._with_retry(_do)

    def fail_package_task(
        self,
        source_item_id: str,
        package_name: str,
        *,
        error: str,
        next_attempt_at: datetime | None,
        final: bool,
    ) -> None:
        finished_at = utc_now()

        def _do(session):
            record = self._find_package_task_record(session, source_item_id, package_name)
            if record is None:
                raise KeyError(f"({source_item_id}, {package_name})")
            record.status = "failed" if final else "pending"
            record.error = error
            record.claimed_by = None
            record.claimed_at = None
            record.lease_expires_at = None
            record.completed_at = finished_at if final else None
            record.next_attempt_at = next_attempt_at
            if final:
                self._sync_source_item_if_all_packages_terminal(session, source_item_id, finished_at)

        self._with_retry(_do)

    def _sync_source_item_if_all_packages_terminal(
        self,
        session: Session,
        source_item_id: str,
        finished_at: datetime,
    ) -> None:
        """Update source_item processing state when all package tasks are terminal."""
        all_records = session.scalars(
            select(PackageProcessingStatusRecord).where(
                PackageProcessingStatusRecord.source_item_id == source_item_id,
            )
        ).all()
        if not all_records:
            return
        all_terminal = all(r.status in ("completed", "skipped", "failed") for r in all_records)
        if not all_terminal:
            return
        source_record = session.get(SourceItemRecord, source_item_id)
        if source_record is None:
            return
        any_failed = any(r.status == "failed" for r in all_records)
        source_record.processing_status = "failed" if any_failed else "completed"
        source_record.processing_completed_at = finished_at
        failed_record = next((r for r in all_records if r.status == "failed"), None)
        source_record.processing_error = failed_record.error if failed_record else None
        source_record.processing_claimed_by = None
        source_record.processing_claimed_at = None
        source_record.processing_lease_expires_at = None
        source_record.processing_next_attempt_at = None
        source_record.processing_attempts = sum(r.attempts for r in all_records)

    def _find_package_task_record(
        self,
        session: Session,
        source_item_id: str,
        package_name: str,
    ) -> PackageProcessingStatusRecord | None:
        return session.scalars(
            select(PackageProcessingStatusRecord).where(
                PackageProcessingStatusRecord.source_item_id == source_item_id,
                PackageProcessingStatusRecord.package_name == package_name,
            )
        ).first()

    def commit_package_process_result(
        self,
        *,
        source_item_id: str,
        result: ProcessResult,
        thread_rebuild_scope: ThreadProcessingScope | None = None,
        container_rebuild_scope: ThreadProcessingScope | None = None,
        completed_at: datetime | None = None,
    ) -> list[tuple[str, str]]:
        """Commit a process result from multi-package processing.

        Persists memory objects, relations, index entries, and handles supersession
        and thread rebuild scope — but does NOT modify source_item processing state.
        """
        finished_at = completed_at or utc_now()

        def _do(session):
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
            if container_rebuild_scope is not None:
                self._upsert_thread_processing_scope_in_session(
                    session,
                    scope=container_rebuild_scope,
                    requested_at=finished_at,
                )
            self._after_commit_processed_source_item_persist(
                session,
                source_item_id=source_item_id,
                result=result,
                supersession_pairs=supersession_pairs,
            )
            # NOTE: We intentionally do NOT touch source_item processing state here.
            # Source_item completion is managed by the caller after all packages are done.
            return supersession_pairs

        return self._with_retry(_do)

