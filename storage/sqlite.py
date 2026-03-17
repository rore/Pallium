from __future__ import annotations

import json
import re
from dataclasses import asdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, delete, func, or_, select, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from core.contracts import ProcessResult
from core.models import (
    Annotation,
    EvidenceReference,
    IndexEntry,
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    MemoryEnvelopeScope,
    MemoryObject,
    MemorySubjectAnchor,
    QueryFilters,
    Relation,
    SourceItem,
    new_id,
    utc_now,
)
from core.observability import OBSERVABILITY_METADATA_KEY
from core.retention import (
    DEBUG_METADATA_TTL,
    DURABLE_MEMORY_TYPES,
    FRESH_WORKING_MEMORY_TYPES,
    ORPHAN_DELETE_MEMORY_TYPES,
    RETENTION_MAINTENANCE_KEY,
    SUPERSEDED_MEMORY_TTL,
    WORKING_MEMORY_TTL,
    source_item_retention_ttl,
)
from core.visibility import VisibilityContext, VisibilityExclusion, visibility_context_is_visible
from storage.base import (
    IndexSearchHit,
    IndexSearchResult,
    LeasedSourceItemInfo,
    LeasedThreadScopeInfo,
    QueueHealthReasonCount,
    QueueHealthSnapshot,
    RecentFailureInfo,
    RetentionHealthSnapshot,
    RetentionLease,
    RetentionLeaseLostError,
    RetentionRunStats,
    StorageProvider,
    ThreadProcessingLease,
    ThreadProcessingScope,
)


Base = declarative_base()
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
MEMORY_ENVELOPE_SCHEMA_ID = "core.memory_envelope"
MEMORY_ENVELOPE_SCHEMA_VERSION = "v1"
MEMORY_ENVELOPE_KINDS = {"constraint", "finding", "episode", "next_step", "summary", "unknown"}
MEMORY_ENVELOPE_CONFIDENCES = {"high", "medium", "low", "unknown"}
MEMORY_ENVELOPE_PRODUCER_KINDS = {"item_extraction", "thread_aggregation", "consolidation"}
MEMORY_SUBJECT_ANCHOR_KINDS = {"workstream", "component", "surface"}

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None


class SourceItemRecord(Base):
    __tablename__ = "source_items"

    id = Column(String, primary_key=True)
    source_type = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=True)
    actor_ref = Column(String, nullable=True)
    role = Column(String, nullable=True)
    container_ref = Column(String, nullable=True)
    thread_ref = Column(String, nullable=True)
    session_ref = Column(String, nullable=True)
    source_ref = Column(String, nullable=True)
    artifact_kind = Column(String, nullable=True)
    visibility_kind = Column(String, nullable=True)
    visibility_id = Column(String, nullable=True)
    use_case = Column(String, nullable=True)
    processing_status = Column(String, nullable=False, default="pending")
    processing_attempts = Column(Integer, nullable=False, default=0)
    processing_claimed_by = Column(String, nullable=True)
    processing_claimed_at = Column(DateTime(timezone=True), nullable=True)
    processing_lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    processing_completed_at = Column(DateTime(timezone=True), nullable=True)
    processing_error = Column(Text, nullable=True)
    processing_next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class AnnotationRecord(Base):
    __tablename__ = "annotations"

    id = Column(String, primary_key=True)
    source_item_id = Column(String, nullable=False)
    type = Column(String, nullable=False)
    schema_id = Column(String, nullable=False)
    schema_version = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class MemoryObjectRecord(Base):
    __tablename__ = "memory_objects"

    id = Column(String, primary_key=True)
    type = Column(String, nullable=False)
    schema_id = Column(String, nullable=False)
    schema_version = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False)
    envelope_json = Column(Text, nullable=True)
    lifecycle = Column(String, nullable=False, default="active")
    visibility_kind = Column(String, nullable=True)
    visibility_id = Column(String, nullable=True)
    freshness_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class RelationRecord(Base):
    __tablename__ = "relations"

    id = Column(String, primary_key=True)
    from_kind = Column(String, nullable=False)
    from_id = Column(String, nullable=False)
    relation_type = Column(String, nullable=False)
    to_kind = Column(String, nullable=False)
    to_id = Column(String, nullable=False)


class IndexEntryRecord(Base):
    __tablename__ = "index_entries"

    id = Column(String, primary_key=True)
    target_kind = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    index_type = Column(String, nullable=False)
    text_view = Column(Text, nullable=False)
    text_view_name = Column(String, nullable=True)
    provider_name = Column(String, nullable=True)
    provider_version = Column(String, nullable=True)


class ThreadProcessingLeaseRecord(Base):
    __tablename__ = "thread_processing_leases"

    scope_key = Column(String, primary_key=True)
    use_case = Column(String, nullable=False)
    container_ref = Column(String, nullable=False)
    thread_ref = Column(String, nullable=False)
    visibility_kind = Column(String, nullable=True)
    visibility_id = Column(String, nullable=True)
    requested_at = Column(DateTime(timezone=True), nullable=True)
    processing_claimed_by = Column(String, nullable=True)
    processing_claimed_at = Column(DateTime(timezone=True), nullable=True)
    processing_lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    processing_completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MaintenanceStateRecord(Base):
    __tablename__ = "maintenance_state"

    key = Column(String, primary_key=True)
    claimed_by = Column(String, nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    last_run_started_at = Column(DateTime(timezone=True), nullable=True)
    last_run_completed_at = Column(DateTime(timezone=True), nullable=True)
    last_run_stats_json = Column(Text, nullable=True)
    source_scan_cursor_created_at = Column(DateTime(timezone=True), nullable=True)
    source_scan_cursor_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class SQLiteStorageProvider(StorageProvider):
    _SOURCE_ITEM_MIGRATIONS = {
        "occurred_at": "ALTER TABLE source_items ADD COLUMN occurred_at DATETIME",
        "actor_ref": "ALTER TABLE source_items ADD COLUMN actor_ref VARCHAR",
        "role": "ALTER TABLE source_items ADD COLUMN role VARCHAR",
        "container_ref": "ALTER TABLE source_items ADD COLUMN container_ref VARCHAR",
        "thread_ref": "ALTER TABLE source_items ADD COLUMN thread_ref VARCHAR",
        "session_ref": "ALTER TABLE source_items ADD COLUMN session_ref VARCHAR",
        "source_ref": "ALTER TABLE source_items ADD COLUMN source_ref VARCHAR",
        "artifact_kind": "ALTER TABLE source_items ADD COLUMN artifact_kind VARCHAR",
        "visibility_kind": "ALTER TABLE source_items ADD COLUMN visibility_kind VARCHAR",
        "visibility_id": "ALTER TABLE source_items ADD COLUMN visibility_id VARCHAR",
        "use_case": "ALTER TABLE source_items ADD COLUMN use_case VARCHAR",
        "processing_status": "ALTER TABLE source_items ADD COLUMN processing_status VARCHAR DEFAULT 'pending'",
        "processing_attempts": "ALTER TABLE source_items ADD COLUMN processing_attempts INTEGER DEFAULT 0",
        "processing_claimed_by": "ALTER TABLE source_items ADD COLUMN processing_claimed_by VARCHAR",
        "processing_claimed_at": "ALTER TABLE source_items ADD COLUMN processing_claimed_at DATETIME",
        "processing_lease_expires_at": "ALTER TABLE source_items ADD COLUMN processing_lease_expires_at DATETIME",
        "processing_completed_at": "ALTER TABLE source_items ADD COLUMN processing_completed_at DATETIME",
        "processing_error": "ALTER TABLE source_items ADD COLUMN processing_error TEXT",
        "processing_next_attempt_at": "ALTER TABLE source_items ADD COLUMN processing_next_attempt_at DATETIME",
    }
    _MEMORY_OBJECT_MIGRATIONS = {
        "lifecycle": "ALTER TABLE memory_objects ADD COLUMN lifecycle VARCHAR DEFAULT 'active'",
        "visibility_kind": "ALTER TABLE memory_objects ADD COLUMN visibility_kind VARCHAR",
        "visibility_id": "ALTER TABLE memory_objects ADD COLUMN visibility_id VARCHAR",
        "freshness_at": "ALTER TABLE memory_objects ADD COLUMN freshness_at DATETIME",
        "envelope_json": "ALTER TABLE memory_objects ADD COLUMN envelope_json TEXT",
    }
    _INDEX_ENTRY_MIGRATIONS = {
        "text_view_name": "ALTER TABLE index_entries ADD COLUMN text_view_name VARCHAR",
        "provider_name": "ALTER TABLE index_entries ADD COLUMN provider_name VARCHAR",
        "provider_version": "ALTER TABLE index_entries ADD COLUMN provider_version VARCHAR",
    }
    _MAINTENANCE_STATE_MIGRATIONS = {
        "source_scan_cursor_created_at": "ALTER TABLE maintenance_state ADD COLUMN source_scan_cursor_created_at DATETIME",
        "source_scan_cursor_id": "ALTER TABLE maintenance_state ADD COLUMN source_scan_cursor_id VARCHAR",
    }
    _RETENTION_LEASE_RENEWAL_BATCH = 50

    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self._engine = create_engine(database_url, future=True, connect_args=connect_args)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False, class_=Session)
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self._schema_initialization_lock():
            Base.metadata.create_all(self._engine)
            self._ensure_source_item_columns()
            self._ensure_memory_object_columns()
            self._ensure_index_entry_columns()
            self._ensure_maintenance_state_columns()
            self._backfill_legacy_memory_freshness()

    @contextmanager
    def _schema_initialization_lock(self):
        if self._engine.url.drivername != "sqlite":
            yield
            return

        lock_path = self._schema_lock_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock_file:
            lock_file.seek(0, 2)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            self._acquire_schema_file_lock(lock_file)
            try:
                yield
            finally:
                self._release_schema_file_lock(lock_file)

    def _schema_lock_path(self) -> Path:
        database = self._engine.url.database
        if not database or database == ":memory:":
            return Path(".pallium-schema-init.lock")
        database_path = Path(database)
        return database_path.with_name(f"{database_path.name}.schema.lock")

    @staticmethod
    def _acquire_schema_file_lock(lock_file) -> None:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            return
        if msvcrt is not None:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            return
        raise RuntimeError("no supported file-locking implementation available for sqlite schema initialization")

    @staticmethod
    def _release_schema_file_lock(lock_file) -> None:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            return
        if msvcrt is not None:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            return
        raise RuntimeError("no supported file-locking implementation available for sqlite schema initialization")

    def find_source_item(self, source_type: str, source_id: str) -> SourceItem | None:
        with self._session_factory() as session:
            record = session.scalar(
                select(SourceItemRecord).where(
                    SourceItemRecord.source_type == source_type,
                    SourceItemRecord.source_id == source_id,
                )
            )
            if record is None:
                return None
            return self._to_source_item(record)

    def create_source_item(self, source_item: SourceItem) -> None:
        visibility_kind, visibility_id = self._split_visibility_context(source_item.visibility_context)
        record = SourceItemRecord(
            id=source_item.id,
            source_type=source_item.source_type,
            source_id=source_item.source_id,
            content_type=source_item.content_type,
            content=source_item.content,
            metadata_json=self._dumps(source_item.metadata),
            occurred_at=source_item.occurred_at,
            actor_ref=source_item.actor_ref,
            role=source_item.role,
            container_ref=source_item.container_ref,
            thread_ref=source_item.thread_ref,
            session_ref=source_item.session_ref,
            source_ref=source_item.source_ref,
            artifact_kind=source_item.artifact_kind,
            visibility_kind=visibility_kind,
            visibility_id=visibility_id,
            use_case=source_item.use_case,
            processing_status=source_item.processing_status,
            processing_attempts=source_item.processing_attempts,
            processing_claimed_by=source_item.processing_claimed_by,
            processing_claimed_at=source_item.processing_claimed_at,
            processing_lease_expires_at=source_item.processing_lease_expires_at,
            processing_completed_at=source_item.processing_completed_at,
            processing_error=source_item.processing_error,
            processing_next_attempt_at=source_item.processing_next_attempt_at,
            created_at=source_item.created_at,
        )
        with self._session_factory.begin() as session:
            session.add(record)

    def get_source_item(self, source_item_id: str) -> SourceItem:
        with self._session_factory() as session:
            record = session.get(SourceItemRecord, source_item_id)
            if record is None:
                raise KeyError(source_item_id)
            return self._to_source_item(record)

    def claim_next_source_item(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
        now: datetime | None = None,
    ) -> SourceItem | None:
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
        supersession_pairs: list[tuple[str, str]],
        thread_rebuild_scope: ThreadProcessingScope | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        finished_at = completed_at or utc_now()
        with self._session_factory.begin() as session:
            self._persist_process_result_in_session(session, result)
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

    def commit_process_result(
        self,
        *,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]],
    ) -> None:
        with self._session_factory.begin() as session:
            self._persist_process_result_in_session(session, result)
            self._apply_supersession_pairs_in_session(session, supersession_pairs)
            self._apply_source_item_metadata_updates_in_session(session, result.source_item_metadata_updates)
            self._refresh_memory_freshness_for_ids_in_session(session, [memory.id for memory in result.memory_objects])

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

    def list_source_items_for_thread(self, container_ref: str, thread_ref: str) -> list[SourceItem]:
        with self._session_factory() as session:
            records = session.scalars(
                select(SourceItemRecord)
                .where(
                    SourceItemRecord.container_ref == container_ref,
                    SourceItemRecord.thread_ref == thread_ref,
                )
                .order_by(SourceItemRecord.created_at.asc(), SourceItemRecord.id.asc())
            ).all()
        return [self._to_source_item(record) for record in records]

    def create_annotation(self, annotation: Annotation) -> None:
        record = AnnotationRecord(
            id=annotation.id,
            source_item_id=annotation.source_item_id,
            type=annotation.type,
            schema_id=annotation.schema_id,
            schema_version=annotation.schema_version,
            payload_json=self._dumps(annotation.payload) or "{}",
            created_at=annotation.created_at,
        )
        with self._session_factory.begin() as session:
            session.add(record)

    def get_annotation(self, annotation_id: str) -> Annotation:
        with self._session_factory() as session:
            record = session.get(AnnotationRecord, annotation_id)
            if record is None:
                raise KeyError(annotation_id)
            return self._to_annotation(record)

    def list_annotations_for_source_item(self, source_item_id: str) -> list[Annotation]:
        with self._session_factory() as session:
            records = session.scalars(
                select(AnnotationRecord).where(AnnotationRecord.source_item_id == source_item_id)
            ).all()
        return [self._to_annotation(record) for record in records]

    def create_memory_object(self, memory_object: MemoryObject) -> None:
        visibility_kind, visibility_id = self._split_visibility_context(memory_object.visibility_context)
        record = MemoryObjectRecord(
            id=memory_object.id,
            type=memory_object.type,
            schema_id=memory_object.schema_id,
            schema_version=memory_object.schema_version,
            payload_json=self._dumps(memory_object.payload) or "{}",
            envelope_json=self._dump_memory_envelope(memory_object.envelope),
            lifecycle=memory_object.lifecycle,
            visibility_kind=visibility_kind,
            visibility_id=visibility_id,
            freshness_at=self._normalize_datetime(memory_object.freshness_at) or memory_object.created_at,
            created_at=memory_object.created_at,
        )
        with self._session_factory.begin() as session:
            session.add(record)

    def get_memory_object(self, memory_object_id: str) -> MemoryObject:
        with self._session_factory() as session:
            record = session.get(MemoryObjectRecord, memory_object_id)
            if record is None:
                raise KeyError(memory_object_id)
            return self._to_memory_object(record)

    def update_memory_object_lifecycle(self, memory_object_id: str, lifecycle: str) -> None:
        with self._session_factory.begin() as session:
            record = session.get(MemoryObjectRecord, memory_object_id)
            if record is None:
                raise KeyError(memory_object_id)
            record.lifecycle = lifecycle

    def refresh_memory_object_freshness(self, memory_object_id: str) -> datetime | None:
        with self._session_factory.begin() as session:
            return self._refresh_memory_object_freshness_in_session(session, memory_object_id)

    def list_memory_objects(self, memory_types: list[str] | None = None, lifecycle: str | None = None) -> list[MemoryObject]:
        with self._session_factory() as session:
            statement = select(MemoryObjectRecord)
            if memory_types:
                statement = statement.where(MemoryObjectRecord.type.in_(memory_types))
            if lifecycle is not None:
                statement = statement.where(MemoryObjectRecord.lifecycle == lifecycle)
            records = session.scalars(statement).all()
        return [self._to_memory_object(record) for record in records]

    def list_memory_objects_for_source_item(self, source_item_id: str) -> list[MemoryObject]:
        with self._session_factory() as session:
            relation_records = session.scalars(
                select(RelationRecord).where(
                    RelationRecord.relation_type == "supported_by",
                    RelationRecord.to_kind == "source_item",
                    RelationRecord.to_id == source_item_id,
                    RelationRecord.from_kind == "memory_object",
                )
            ).all()
            memory_object_ids = [record.from_id for record in relation_records]
            if not memory_object_ids:
                return []
            records = session.scalars(
                select(MemoryObjectRecord).where(MemoryObjectRecord.id.in_(memory_object_ids))
            ).all()
        return [self._to_memory_object(record) for record in records]

    def create_relation(self, relation: Relation) -> None:
        record = RelationRecord(
            id=relation.id,
            from_kind=relation.from_kind,
            from_id=relation.from_id,
            relation_type=relation.relation_type,
            to_kind=relation.to_kind,
            to_id=relation.to_id,
        )
        with self._session_factory.begin() as session:
            session.add(record)
            if relation.from_kind == "memory_object":
                session.flush()
                self._refresh_memory_object_freshness_in_session(session, relation.from_id)

    def list_relations_for_source_item(self, source_item_id: str) -> list[Relation]:
        with self._session_factory() as session:
            records = session.scalars(
                select(RelationRecord).where(
                    RelationRecord.to_kind == "source_item",
                    RelationRecord.to_id == source_item_id,
                )
            ).all()
        return [self._to_relation(record) for record in records]

    def create_index_entry(self, index_entry: IndexEntry) -> None:
        record = IndexEntryRecord(
            id=index_entry.id,
            target_kind=index_entry.target_kind,
            target_id=index_entry.target_id,
            index_type=index_entry.index_type,
            text_view=index_entry.text_view,
            text_view_name=index_entry.text_view_name,
            provider_name=index_entry.provider_name,
            provider_version=index_entry.provider_version,
        )
        with self._session_factory.begin() as session:
            session.add(record)

    def list_index_entries_for_target(self, target_kind: str, target_id: str) -> list[IndexEntry]:
        with self._session_factory() as session:
            records = session.scalars(
                select(IndexEntryRecord).where(
                    IndexEntryRecord.target_kind == target_kind,
                    IndexEntryRecord.target_id == target_id,
                )
            ).all()
        return [self._to_index_entry(record) for record in records]

    def search_index_entries(
        self,
        tokens: list[str],
        limit: int,
        filters: QueryFilters | None = None,
        *,
        visibility_contexts: tuple[VisibilityContext, ...] | None = None,
        include_visibility_trace: bool = False,
    ) -> IndexSearchResult:
        with self._session_factory() as session:
            records = session.scalars(
                select(IndexEntryRecord).where(IndexEntryRecord.index_type == "lexical")
            ).all()
        hits: list[IndexSearchHit] = []
        exclusion_counts: dict[str, int] = {}
        unique_tokens = set(tokens)
        total_hits_before_visibility = 0
        total_hits_after_visibility = 0
        for record in records:
            if not self._matches_filters(record.target_kind, record.target_id, filters):
                continue
            text_tokens = set(TOKEN_PATTERN.findall(record.text_view.lower()))
            matched_tokens = tuple(sorted(unique_tokens.intersection(text_tokens)))
            score = len(matched_tokens)
            if score == 0:
                continue
            total_hits_before_visibility += 1
            visibility_context = self._target_visibility_context(record.target_kind, record.target_id)
            if not visibility_context_is_visible(visibility_context, visibility_contexts):
                if include_visibility_trace and visibility_contexts is not None:
                    reason = (
                        "candidate_visibility_context_missing"
                        if visibility_context is None
                        else "query_visibility_context_excludes_candidate"
                    )
                    exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
                continue
            total_hits_after_visibility += 1
            hits.append(
                IndexSearchHit(
                    target_kind=record.target_kind,
                    target_id=record.target_id,
                    index_entry_id=record.id,
                    index_type=record.index_type,
                    text_view_name=record.text_view_name or "default",
                    score=score,
                    matched_tokens=matched_tokens,
                    provider_name=record.provider_name,
                    provider_version=record.provider_version,
                )
            )
        hits.sort(key=lambda item: (item.score, 1 if item.target_kind == "memory_object" else 0), reverse=True)
        exclusions = tuple(
            VisibilityExclusion(reason=reason, count=count)
            for reason, count in sorted(exclusion_counts.items())
        )
        return IndexSearchResult(
            hits=hits[:limit],
            visibility_exclusions=exclusions,
            total_hits_before_visibility=total_hits_before_visibility,
            total_hits_after_visibility=total_hits_after_visibility,
        )

    def get_evidence_for_memory_object(self, memory_object_id: str) -> list[EvidenceReference]:
        with self._session_factory() as session:
            relations = session.scalars(
                select(RelationRecord).where(
                    RelationRecord.from_kind == "memory_object",
                    RelationRecord.from_id == memory_object_id,
                    RelationRecord.relation_type == "supported_by",
                    RelationRecord.to_kind == "source_item",
                )
            ).all()
            source_ids = [relation.to_id for relation in relations]
            if not source_ids:
                return []
            records = session.scalars(
                select(SourceItemRecord).where(SourceItemRecord.id.in_(source_ids))
            ).all()
        return [self._to_evidence_reference(record) for record in records]

    def run_retention_pass(
        self,
        *,
        now: datetime,
        batch_size: int,
        lease: RetentionLease | None = None,
        lease_seconds: int | None = None,
        lease_now: datetime | None = None,
    ) -> RetentionRunStats:
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
                    MemoryObjectRecord.type.in_(tuple(FRESH_WORKING_MEMORY_TYPES)),
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
                if self._source_item_is_protected(session, record.id, now=now):
                    stats = self._merge_retention_stats(stats, RetentionRunStats(skipped_protected_source_items=1))
                    if deleted_sources >= delete_limit:
                        break
                    continue
                stats = self._merge_retention_stats(stats, self._delete_source_item_cascade_in_session(session, record.id))
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
                visibility_context=self._build_visibility_context(record.visibility_kind, record.visibility_id),
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
                    MemoryObjectRecord.type.in_(tuple(FRESH_WORKING_MEMORY_TYPES)),
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

    def _source_item_is_protected(self, session: Session, source_item_id: str, *, now: datetime) -> bool:
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
            if memory_record.type in DURABLE_MEMORY_TYPES:
                return True
            freshness_at = self._resolve_memory_object_freshness_in_session(session, memory_record)
            if memory_record.type in FRESH_WORKING_MEMORY_TYPES and freshness_at is not None and freshness_at > now - WORKING_MEMORY_TTL:
                return True
        return False

    def _delete_source_item_cascade_in_session(self, session: Session, source_item_id: str) -> RetentionRunStats:
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
            stats = self._merge_retention_stats(stats, self._delete_orphan_memory_object_if_needed_in_session(session, memory_object_id))
        return stats

    def _delete_orphan_memory_object_if_needed_in_session(self, session: Session, memory_object_id: str) -> RetentionRunStats:
        memory_record = session.get(MemoryObjectRecord, memory_object_id)
        if memory_record is None:
            return RetentionRunStats()
        if memory_record.type in DURABLE_MEMORY_TYPES or memory_record.type in FRESH_WORKING_MEMORY_TYPES:
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
        if memory_record.type not in ORPHAN_DELETE_MEMORY_TYPES and memory_record.lifecycle == "active":
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
    def _persist_process_result_in_session(self, session: Session, result: ProcessResult) -> None:
        for annotation in result.annotations:
            session.add(
                AnnotationRecord(
                    id=annotation.id,
                    source_item_id=annotation.source_item_id,
                    type=annotation.type,
                    schema_id=annotation.schema_id,
                    schema_version=annotation.schema_version,
                    payload_json=self._dumps(annotation.payload) or "{}",
                    created_at=annotation.created_at,
                )
            )
        for memory_object in result.memory_objects:
            visibility_kind, visibility_id = self._split_visibility_context(memory_object.visibility_context)
            session.add(
                MemoryObjectRecord(
                    id=memory_object.id,
                    type=memory_object.type,
                    schema_id=memory_object.schema_id,
                    schema_version=memory_object.schema_version,
                    payload_json=self._dumps(memory_object.payload) or "{}",
                    envelope_json=self._dump_memory_envelope(memory_object.envelope),
                    lifecycle=memory_object.lifecycle,
                    visibility_kind=visibility_kind,
                    visibility_id=visibility_id,
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

    def _after_commit_processed_source_item_persist(
        self,
        session: Session,
        *,
        source_item_id: str,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]],
    ) -> None:
        return None

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
                    visibility_kind=self._split_visibility_context(scope.visibility_context)[0],
                    visibility_id=self._split_visibility_context(scope.visibility_context)[1],
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

    def _matches_filters(self, target_kind: str, target_id: str, filters: QueryFilters | None) -> bool:
        if target_kind == "memory_object":
            memory_object = self.get_memory_object(target_id)
            if memory_object.lifecycle != "active":
                return False
        if filters is None:
            return True
        if target_kind == "source_item":
            return self._source_item_matches_filters(self.get_source_item(target_id), filters)
        if target_kind == "memory_object":
            evidence = self.get_evidence_for_memory_object(target_id)
            return any(self._evidence_matches_filters(item, filters) for item in evidence)
        return True

    def _target_visibility_context(self, target_kind: str, target_id: str) -> VisibilityContext | None:
        if target_kind == "source_item":
            return self.get_source_item(target_id).visibility_context
        if target_kind == "memory_object":
            return self.get_memory_object(target_id).visibility_context
        return None

    def _source_item_matches_filters(self, source_item: SourceItem, filters: QueryFilters) -> bool:
        if filters.source_type is not None and source_item.source_type != filters.source_type:
            return False
        if filters.role is not None and source_item.role != filters.role:
            return False
        if filters.artifact_kind is not None and source_item.artifact_kind != filters.artifact_kind:
            return False
        if filters.container_ref is not None and source_item.container_ref != filters.container_ref:
            return False
        if filters.thread_ref is not None and source_item.thread_ref != filters.thread_ref:
            return False
        if filters.session_ref is not None and source_item.session_ref != filters.session_ref:
            return False
        return True

    def _evidence_matches_filters(self, evidence: EvidenceReference, filters: QueryFilters) -> bool:
        if filters.source_type is not None and evidence.source_type != filters.source_type:
            return False
        if filters.role is not None and evidence.role != filters.role:
            return False
        if filters.artifact_kind is not None and evidence.artifact_kind != filters.artifact_kind:
            return False
        if filters.container_ref is not None and evidence.container_ref != filters.container_ref:
            return False
        if filters.thread_ref is not None and evidence.thread_ref != filters.thread_ref:
            return False
        if filters.session_ref is not None and evidence.session_ref != filters.session_ref:
            return False
        return True

    def _ensure_source_item_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(source_items)"))
            }
            for column_name, migration_sql in self._SOURCE_ITEM_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

    def _ensure_memory_object_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(memory_objects)"))
            }
            for column_name, migration_sql in self._MEMORY_OBJECT_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

    def _ensure_index_entry_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(index_entries)"))
            }
            for column_name, migration_sql in self._INDEX_ENTRY_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

    def _ensure_maintenance_state_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(maintenance_state)"))
            }
            for column_name, migration_sql in self._MAINTENANCE_STATE_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

    @staticmethod
    def _to_source_item(record: SourceItemRecord) -> SourceItem:
        return SourceItem(
            id=record.id,
            source_type=record.source_type,
            source_id=record.source_id,
            content_type=record.content_type,
            content=record.content,
            metadata=SQLiteStorageProvider._loads(record.metadata_json),
            occurred_at=SQLiteStorageProvider._normalize_datetime(record.occurred_at),
            actor_ref=record.actor_ref,
            role=record.role,
            container_ref=record.container_ref,
            thread_ref=record.thread_ref,
            session_ref=record.session_ref,
            source_ref=record.source_ref,
            artifact_kind=record.artifact_kind,
            visibility_context=SQLiteStorageProvider._build_visibility_context(record.visibility_kind, record.visibility_id),
            use_case=record.use_case,
            processing_status=record.processing_status or "pending",
            processing_attempts=record.processing_attempts or 0,
            processing_claimed_by=record.processing_claimed_by,
            processing_claimed_at=SQLiteStorageProvider._normalize_datetime(record.processing_claimed_at),
            processing_lease_expires_at=SQLiteStorageProvider._normalize_datetime(record.processing_lease_expires_at),
            processing_completed_at=SQLiteStorageProvider._normalize_datetime(record.processing_completed_at),
            processing_error=record.processing_error,
            processing_next_attempt_at=SQLiteStorageProvider._normalize_datetime(record.processing_next_attempt_at),
            created_at=SQLiteStorageProvider._normalize_datetime(record.created_at) or utc_now(),
        )

    @staticmethod
    def _to_annotation(record: AnnotationRecord) -> Annotation:
        return Annotation(
            id=record.id,
            source_item_id=record.source_item_id,
            type=record.type,
            schema_id=record.schema_id,
            schema_version=record.schema_version,
            payload=SQLiteStorageProvider._loads(record.payload_json),
            created_at=SQLiteStorageProvider._normalize_datetime(record.created_at) or utc_now(),
        )

    @staticmethod
    def _to_memory_object(record: MemoryObjectRecord) -> MemoryObject:
        return MemoryObject(
            id=record.id,
            type=record.type,
            schema_id=record.schema_id,
            schema_version=record.schema_version,
            payload=SQLiteStorageProvider._loads(record.payload_json),
            lifecycle=record.lifecycle or "active",
            envelope=SQLiteStorageProvider._load_memory_envelope(record.envelope_json),
            visibility_context=SQLiteStorageProvider._build_visibility_context(record.visibility_kind, record.visibility_id),
            freshness_at=SQLiteStorageProvider._normalize_datetime(record.freshness_at),
            created_at=SQLiteStorageProvider._normalize_datetime(record.created_at) or utc_now(),
        )

    @staticmethod
    def _to_relation(record: RelationRecord) -> Relation:
        return Relation(
            id=record.id,
            from_kind=record.from_kind,
            from_id=record.from_id,
            relation_type=record.relation_type,
            to_kind=record.to_kind,
            to_id=record.to_id,
        )

    @staticmethod
    def _to_index_entry(record: IndexEntryRecord) -> IndexEntry:
        return IndexEntry(
            id=record.id,
            target_kind=record.target_kind,
            target_id=record.target_id,
            index_type=record.index_type,
            text_view=record.text_view,
            text_view_name=record.text_view_name or "default",
            provider_name=record.provider_name,
            provider_version=record.provider_version,
        )

    @staticmethod
    def _to_evidence_reference(record: SourceItemRecord) -> EvidenceReference:
        return EvidenceReference(
            source_item_id=record.id,
            source_type=record.source_type,
            source_id=record.source_id,
            occurred_at=SQLiteStorageProvider._normalize_datetime(record.occurred_at),
            actor_ref=record.actor_ref,
            role=record.role,
            container_ref=record.container_ref,
            thread_ref=record.thread_ref,
            session_ref=record.session_ref,
            source_ref=record.source_ref,
            artifact_kind=record.artifact_kind,
            visibility_context=SQLiteStorageProvider._build_visibility_context(record.visibility_kind, record.visibility_id),
        )

    @staticmethod
    def _to_thread_processing_lease(record: ThreadProcessingLeaseRecord) -> ThreadProcessingLease:
        requested_at = SQLiteStorageProvider._normalize_datetime(record.requested_at)
        claimed_at = SQLiteStorageProvider._normalize_datetime(record.processing_claimed_at)
        lease_expires_at = SQLiteStorageProvider._normalize_datetime(record.processing_lease_expires_at)
        if requested_at is None or claimed_at is None or lease_expires_at is None or record.processing_claimed_by is None:
            raise ValueError(f"thread processing lease is incomplete for scope {record.scope_key}")
        return ThreadProcessingLease(
            scope_key=record.scope_key,
            use_case=record.use_case,
            container_ref=record.container_ref,
            thread_ref=record.thread_ref,
            visibility_context=SQLiteStorageProvider._build_visibility_context(record.visibility_kind, record.visibility_id),
            requested_at=requested_at,
            processing_claimed_by=record.processing_claimed_by,
            processing_claimed_at=claimed_at,
            processing_lease_expires_at=lease_expires_at,
        )

    @staticmethod
    def _to_retention_lease(record: MaintenanceStateRecord) -> RetentionLease:
        claimed_at = SQLiteStorageProvider._normalize_datetime(record.claimed_at)
        lease_expires_at = SQLiteStorageProvider._normalize_datetime(record.lease_expires_at)
        if claimed_at is None or lease_expires_at is None or record.claimed_by is None:
            raise ValueError(f"retention lease is incomplete for key {record.key}")
        return RetentionLease(
            key=record.key,
            claimed_by=record.claimed_by,
            claimed_at=claimed_at,
            lease_expires_at=lease_expires_at,
        )
    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _split_visibility_context(visibility_context: VisibilityContext | None) -> tuple[str | None, str | None]:
        if visibility_context is None:
            return None, None
        return visibility_context.kind, visibility_context.id

    @staticmethod
    def _build_visibility_context(kind: str | None, visibility_id: str | None) -> VisibilityContext | None:
        if not kind:
            return None
        return VisibilityContext(kind=kind, id=visibility_id)

    @staticmethod
    def _dump_memory_envelope(envelope: MemoryEnvelope | None) -> str | None:
        if envelope is None:
            return None
        return json.dumps(asdict(envelope))

    @staticmethod
    def _load_memory_envelope(value: str | None) -> MemoryEnvelope | None:
        if not value:
            return None
        try:
            payload = json.loads(value)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        scope_payload = payload.get("scope")
        derivation_payload = payload.get("derivation")
        subjects_payload = payload.get("subjects")
        if (
            payload.get("schema_id") != MEMORY_ENVELOPE_SCHEMA_ID
            or payload.get("schema_version") != MEMORY_ENVELOPE_SCHEMA_VERSION
            or not isinstance(scope_payload, dict)
            or not isinstance(derivation_payload, dict)
            or not isinstance(subjects_payload, list)
        ):
            return None
        kind = SQLiteStorageProvider._load_envelope_enum(payload.get("kind"), allowed=MEMORY_ENVELOPE_KINDS)
        confidence = SQLiteStorageProvider._load_envelope_enum(payload.get("confidence"), allowed=MEMORY_ENVELOPE_CONFIDENCES)
        producer_kind = SQLiteStorageProvider._load_envelope_enum(
            derivation_payload.get("producer_kind"),
            allowed=MEMORY_ENVELOPE_PRODUCER_KINDS,
        )
        producer_schema_id = SQLiteStorageProvider._load_required_envelope_string(
            derivation_payload.get("producer_schema_id")
        )
        producer_schema_version = SQLiteStorageProvider._load_required_envelope_string(
            derivation_payload.get("producer_schema_version")
        )
        if kind is None or confidence is None or producer_kind is None:
            return None
        if producer_schema_id is None or producer_schema_version is None:
            return None
        subjects: list[MemorySubjectAnchor] = []
        for subject_payload in subjects_payload:
            if not isinstance(subject_payload, dict):
                return None
            subject_kind = SQLiteStorageProvider._load_envelope_enum(
                subject_payload.get("kind"),
                allowed=MEMORY_SUBJECT_ANCHOR_KINDS,
            )
            subject_value = SQLiteStorageProvider._load_required_envelope_string(subject_payload.get("value"))
            if subject_kind is None or subject_value is None:
                return None
            subjects.append(MemorySubjectAnchor(kind=subject_kind, value=subject_value))
        container_ref, container_ref_valid = SQLiteStorageProvider._load_optional_envelope_string(
            scope_payload,
            "container_ref",
        )
        thread_ref, thread_ref_valid = SQLiteStorageProvider._load_optional_envelope_string(
            scope_payload,
            "thread_ref",
        )
        session_ref, session_ref_valid = SQLiteStorageProvider._load_optional_envelope_string(
            scope_payload,
            "session_ref",
        )
        prompt_variant, prompt_variant_valid = SQLiteStorageProvider._load_optional_envelope_string(
            derivation_payload,
            "prompt_variant",
        )
        model_role, model_role_valid = SQLiteStorageProvider._load_optional_envelope_string(
            derivation_payload,
            "model_role",
        )
        kind_basis, kind_basis_valid = SQLiteStorageProvider._load_optional_envelope_string(
            derivation_payload,
            "kind_basis",
        )
        if not all(
            (
                container_ref_valid,
                thread_ref_valid,
                session_ref_valid,
                prompt_variant_valid,
                model_role_valid,
                kind_basis_valid,
            )
        ):
            return None
        return MemoryEnvelope(
            schema_id=MEMORY_ENVELOPE_SCHEMA_ID,
            schema_version=MEMORY_ENVELOPE_SCHEMA_VERSION,
            kind=kind,
            scope=MemoryEnvelopeScope(
                container_ref=container_ref,
                thread_ref=thread_ref,
                session_ref=session_ref,
            ),
            derivation=MemoryEnvelopeDerivation(
                producer_kind=producer_kind,
                producer_schema_id=producer_schema_id,
                producer_schema_version=producer_schema_version,
                prompt_variant=prompt_variant,
                model_role=model_role,
                kind_basis=kind_basis,
            ),
            subjects=subjects,
            confidence=confidence,
        )

    @staticmethod
    def _load_envelope_enum(value: object, *, allowed: set[str]) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized or normalized not in allowed:
            return None
        return normalized

    @staticmethod
    def _load_required_envelope_string(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    @staticmethod
    def _load_optional_envelope_string(payload: dict[str, object], key: str) -> tuple[str | None, bool]:
        if key not in payload or payload.get(key) is None:
            return None, True
        value = payload.get(key)
        if not isinstance(value, str):
            return None, False
        normalized = value.strip()
        return normalized or None, True

    @staticmethod
    def _dumps(value: dict | None) -> str | None:
        if value is None:
            return None
        return json.dumps(value)

    @staticmethod
    def _loads(value: str | None) -> dict:
        if not value:
            return {}
        return json.loads(value)

    @staticmethod
    def _observability_state_from_metadata(metadata_json: str | None) -> dict[str, object]:
        metadata = SQLiteStorageProvider._loads(metadata_json)
        state = metadata.get("observability_debug")
        return state if isinstance(state, dict) else {}

    @staticmethod
    def _classify_unclaimable_pending_reason(
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
        next_attempt_at = SQLiteStorageProvider._normalize_datetime(record.processing_next_attempt_at)
        if next_attempt_at is not None and next_attempt_at > now:
            return "retry_backoff_active"
        if record.use_case not in known_use_cases:
            return "unknown_use_case"
        if record.use_case in scoped_use_cases and not record.visibility_kind:
            return "missing_visibility_for_scoped_use_case"
        return None

