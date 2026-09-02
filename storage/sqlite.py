from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, TypeVar

from sqlalchemy import and_, create_engine, event, func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError

from core.errors import SupersessionConflictError, is_transient_error
from core.contracts import ProcessResult
from core.models import EvidenceReference, IndexEntry, MemoryFeedback, MemoryFlag, MemoryObject, Relation, SourceItem, utc_now
from core.turn_inference import ThreadStats
from storage.base import StorageProvider
from storage.sqlite_codec import SQLiteCodecMixin
from storage.sqlite_codec import extract_memory_subject
from storage.sqlite_queue import SQLiteQueueMixin
from storage.sqlite_retention import SQLiteRetentionMixin
from storage.sqlite_relay import SQLiteRelayMixin
from storage.sqlite_schema import (
    Base,
    IndexEntryRecord,
    HistoricalLookupReuseEventRecord,
    HistoricalLookupReuseLabelRecord,
    MaintenanceStateRecord,
    MemoryFeedbackRecord,
    MemoryFlagRecord,
    MemoryObjectRecord,
    MemoryObjectShadowRecord,
    MemoryUsageAuditRecord,
    PackageProcessingStatusRecord,
    QueryAuditLogRecord,
    RelayDeliveryRecord,
    RelayMessageRecord,
    RelayMigrationMetadataRecord,
    RelaySessionRecord,
    RelationRecord,
    SQLiteSchemaMixin,
    SourceItemRecord,
    SubtaskSelectorShadowRecord,
    ThreadProcessingLeaseRecord,
    insert_lexical_fts_row,
)
from storage.sqlite_search import SQLiteSearchMixin

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

_DISPLAY_TEXT_KEYS = ("summary", "statement", "decision", "investigation_outcome", "interest_text", "constraint_text", "carry_forward_answer", "outcome", "content", "title", "investigation_subject", "subject")


# PR 3 of operational_fact redesign: lifecycles that are visible to
# operator surfaces by default when the caller passes no explicit
# ``lifecycle=...`` filter. Non-allowlist values (``candidate`` and any
# future hidden lifecycles like ``quarantined``) require either an
# explicit ``lifecycle=<value>`` filter OR ``include_candidates=True``
# to appear. New lifecycle values default to invisible — adding one
# here is a deliberate review step.
_DEFAULT_VISIBLE_LIFECYCLES: tuple[str, ...] = ("active", "superseded", "suppressed")


def _extract_display_text(payload: dict) -> str:
    for key in _DISPLAY_TEXT_KEYS:
        val = payload.get(key)
        if val:
            return str(val)
    return ""


class SQLiteStorageProvider(
    SQLiteRelayMixin,
    SQLiteSearchMixin,
    SQLiteQueueMixin,
    SQLiteRetentionMixin,
    SQLiteSchemaMixin,
    SQLiteCodecMixin,
    StorageProvider,
):
    _RELAY_MIGRATION_KEY = "relay_split_v1"
    _RELAY_IMMEDIATE_ATTEMPTS = 3
    _RELAY_IMMEDIATE_BUSY_TIMEOUT_MS = 100

    def __init__(self, database_url: str, relay_database_url: str | None = None) -> None:
        separate_relay = relay_database_url is not None and not self._same_sqlite_file(database_url, relay_database_url)
        self._engine = self._create_engine(database_url)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False, class_=Session)
        self._initialize_schema(include_relay=not separate_relay)
        self._relay_engine = self._engine
        self._relay_session_factory = self._session_factory
        if separate_relay:
            self._relay_engine = self._create_engine(relay_database_url)
            self._relay_session_factory = sessionmaker(
                self._relay_engine, expire_on_commit=False, class_=Session
            )
            self._initialize_relay_schema(self._relay_engine)
            self._migrate_legacy_relay()

    @classmethod
    def _create_engine(cls, database_url: str):
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        engine = create_engine(database_url, future=True, connect_args=connect_args)
        cls._register_sqlite_connect_hooks(engine)
        return engine

    @staticmethod
    def _same_sqlite_file(database_url: str, relay_database_url: str) -> bool:
        if database_url == relay_database_url:
            return True
        if not (database_url.startswith("sqlite") and relay_database_url.startswith("sqlite")):
            return False
        source = database_url.removeprefix("sqlite:///")
        target = relay_database_url.removeprefix("sqlite:///")
        return (source == target == ":memory:") or (source != ":memory:" and target != ":memory:" and Path(source).resolve() == Path(target).resolve())

    @staticmethod
    def _sqlite_identity(engine) -> str:
        database = engine.url.database
        if not database or database == ":memory:":
            return str(engine.url)
        return str(Path(database).resolve())

    def relay_database_status(self) -> dict[str, object]:
        """Read-only Relay database routing state for operational callers."""
        return {
            "isolated": self._relay_engine is not self._engine,
            "database_url": str(self._relay_engine.url),
            "migration_ready": True,
        }

    def close(self) -> None:
        """Release both SQLite engine pools owned by this provider."""
        self._engine.dispose()
        if self._relay_engine is not self._engine:
            self._relay_engine.dispose()

    def _migrate_legacy_relay(self) -> None:
        """Copy legacy Relay rows once while source writes are held out."""
        source_identity = self._sqlite_identity(self._engine)
        target_identity = self._sqlite_identity(self._relay_engine)
        with self._schema_initialization_lock(self._engine):
            with self._schema_initialization_lock(self._relay_engine):
                with self._begin_immediate_for(self._session_factory) as source:
                    marker = source.get(RelayMigrationMetadataRecord, self._RELAY_MIGRATION_KEY)
                    if marker is not None:
                        if (marker.source_identity, marker.target_identity) != (source_identity, target_identity):
                            raise RuntimeError("Relay split marker does not match the configured source and target databases")
                        with self._relay_session_factory() as target:
                            target_marker = target.get(RelayMigrationMetadataRecord, self._RELAY_MIGRATION_KEY)
                            if target_marker is None or (target_marker.source_identity, target_marker.target_identity) != (source_identity, target_identity):
                                raise RuntimeError("Relay split target marker is missing or does not match the configured databases")
                            self._verify_relay_ids(source, target, require_exact=False)
                        return
                    with self._begin_relay_immediate() as target:
                        target_marker = target.get(RelayMigrationMetadataRecord, self._RELAY_MIGRATION_KEY)
                        if target_marker is not None and (
                            target_marker.source_identity,
                            target_marker.target_identity,
                        ) != (source_identity, target_identity):
                            raise RuntimeError("Relay database was initialized from a different source database")
                        self._copy_relay_rows(source, target)
                        self._verify_relay_ids(source, target, require_exact=True)
                        if target_marker is None:
                            target.add(RelayMigrationMetadataRecord(
                                key=self._RELAY_MIGRATION_KEY,
                                source_identity=source_identity,
                                target_identity=target_identity,
                                completed_at=utc_now(),
                            ))
                    source.add(RelayMigrationMetadataRecord(
                        key=self._RELAY_MIGRATION_KEY,
                        source_identity=source_identity,
                        target_identity=target_identity,
                        completed_at=utc_now(),
                    ))

    @staticmethod
    def _relay_tables_present(session: Session) -> bool:
        names = {
            row[0] for row in session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('relay_sessions', 'relay_messages', 'relay_deliveries')")
            )
        }
        expected = {"relay_sessions", "relay_messages", "relay_deliveries"}
        if names and names != expected:
            raise RuntimeError("legacy Relay schema is incomplete; refusing split migration")
        return bool(names)

    def _copy_relay_rows(self, source: Session, target: Session) -> None:
        if not self._relay_tables_present(source):
            return
        for model in (RelaySessionRecord, RelayMessageRecord, RelayDeliveryRecord):
            rows = source.execute(select(model)).scalars().all()
            if rows:
                target.execute(
                    model.__table__.insert().prefix_with("OR IGNORE"),
                    [{column.name: getattr(row, column.name) for column in model.__table__.columns} for row in rows],
                )

    def _verify_relay_ids(self, source: Session, target: Session, *, require_exact: bool) -> None:
        if not self._relay_tables_present(source):
            return
        for model in (RelaySessionRecord, RelayMessageRecord, RelayDeliveryRecord):
            source_rows = {row.id: row for row in source.execute(select(model)).scalars()}
            target_rows = {row.id: row for row in target.execute(select(model)).scalars()}
            if not set(source_rows).issubset(target_rows) or (require_exact and set(source_rows) != set(target_rows)):
                raise RuntimeError(f"Relay split migration verification failed for {model.__tablename__}")
            # Full-column equality only makes sense right after the one-time copy. On the
            # resumed path mutable columns (e.g. last_seen_at) legitimately diverge: relay
            # writes advance the relay-DB copy while the main-DB copy stays frozen. Verify
            # id-subset parity only there.
            if not require_exact:
                continue
            for row_id, source_row in source_rows.items():
                target_row = target_rows[row_id]
                if any(
                    getattr(source_row, column.name) != getattr(target_row, column.name)
                    for column in model.__table__.columns
                ):
                    raise RuntimeError(f"Relay split migration found conflicting {model.__tablename__} row {row_id}")

    @staticmethod
    def _register_sqlite_connect_hooks(engine) -> None:
        """Register connection-level hooks for SQLite engines.

        Sets auto-vacuum mode, WAL journal mode and busy timeout on every new
        connection so concurrent readers and writers (API server, processors,
        cleaners) can operate without blocking each other.  The busy timeout lets
        writers wait briefly instead of failing immediately when another writer
        holds the lock.
        """
        if engine.url.get_backend_name() != "sqlite":
            return

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            # auto_vacuum MUST be set before journal_mode=WAL: on a brand-new DB
            # the first journal_mode=WAL write commits the header and locks in the
            # current auto_vacuum value, so setting it afterward is silently
            # ignored. Setting it first makes new DBs adopt INCREMENTAL before any
            # table page is written. On an EXISTING DB this is a harmless no-op —
            # the persisted mode only changes via a one-time VACUUM.
            cursor.execute("PRAGMA auto_vacuum=INCREMENTAL")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()

    _LOCKED_MAX_RETRIES = 3
    _LOCKED_BACKOFF_BASE = 0.2

    def _with_retry(self, fn: Callable[[Session], _T]) -> _T:
        """Execute fn(session) in a transaction, retrying on transient SQLite errors."""
        for attempt in range(self._LOCKED_MAX_RETRIES):
            try:
                with self._session_factory.begin() as session:
                    return fn(session)
            except Exception as exc:
                if not is_transient_error(exc):
                    raise
                if attempt == self._LOCKED_MAX_RETRIES - 1:
                    raise
                logger.warning(
                    "Transient SQLite error (attempt %d/%d), retrying: %s",
                    attempt + 1, self._LOCKED_MAX_RETRIES, exc,
                )
                time.sleep(self._LOCKED_BACKOFF_BASE * (2 ** attempt))
        raise AssertionError("unreachable: loop must return or raise")

    def _reclaim_engine_free_pages(self, engine) -> dict[str, int]:
        if engine.url.get_backend_name() != "sqlite":
            return {"freelist_before": 0, "freelist_after": 0, "reclaimed_pages": 0, "checkpoint_busy": 0}
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            before = int(conn.exec_driver_sql("PRAGMA freelist_count").scalar() or 0)
            conn.exec_driver_sql("PRAGMA incremental_vacuum")
            after = int(conn.exec_driver_sql("PRAGMA freelist_count").scalar() or 0)
            row = conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            checkpoint_busy = int(row[0]) if row is not None else 0
        return {"freelist_before": before, "freelist_after": after, "reclaimed_pages": max(0, before - after), "checkpoint_busy": checkpoint_busy}

    def reclaim_free_pages(self) -> dict[str, int]:
        """Return free pages to the OS via incremental auto-vacuum.

        Runs ``PRAGMA incremental_vacuum`` in AUTOCOMMIT — a VACUUM-family pragma
        must not run inside a transaction, so this deliberately does NOT go
        through ``_with_retry`` (which wraps everything in a ``begin()``).

        ``incremental_vacuum`` removes pages from the freelist (that reduction is
        what ``reclaimed_pages`` reports). In WAL mode the *physical* file shrink
        only happens when the WAL is truncated at a checkpoint, so a
        ``wal_checkpoint(TRUNCATE)`` follows. That checkpoint can return **busy**
        (without raising) when another connection holds a WAL read snapshot — the
        common case when the API server is live — in which case the WAL is NOT
        truncated yet and the ``.db`` file has not physically shrunk. That is not
        an error: SQLite's automatic checkpointing and the next reclaim pass
        complete the truncation. ``checkpoint_busy`` surfaces that state.

        No-op on DBs created with ``auto_vacuum=NONE`` (legacy installs, whose
        freelist is not reclaimable this way) and on non-SQLite backends; reports
        ``reclaimed_pages=0`` there. Idempotent and safe to call every cleaner
        cycle (cheap when the freelist is empty).
        """
        result = self._reclaim_engine_free_pages(self._engine)
        if self._relay_engine is not self._engine:
            relay = self._reclaim_engine_free_pages(self._relay_engine)
            result["relay_reclaimed_pages"] = relay["reclaimed_pages"]
            result["relay_checkpoint_busy"] = relay["checkpoint_busy"]
        return result

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
        record = SourceItemRecord(
            id=source_item.id,
            source_type=source_item.source_type,
            source_id=source_item.source_id,
            content_type=source_item.content_type,
            content=source_item.content,
            metadata_json=self._dumps(source_item.metadata),
            occurred_at=source_item.occurred_at,
            actor_ref=source_item.actor_ref,
            agent_ref=source_item.agent_ref,
            role=source_item.role,
            container_ref=source_item.container_ref,
            thread_ref=source_item.thread_ref,
            source_ref=source_item.source_ref,
            artifact_kind=source_item.artifact_kind,
            visibility=source_item.visibility,
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
        with self._begin_immediate() as session:
            if source_item.thread_ref is not None and source_item.container_ref is not None:
                count = session.execute(
                    text(
                        "SELECT COUNT(*) FROM source_items "
                        "WHERE container_ref = :container_ref AND thread_ref = :thread_ref"
                    ),
                    {"container_ref": source_item.container_ref, "thread_ref": source_item.thread_ref},
                ).scalar()
                record.thread_position = count + 1
            else:
                record.thread_position = 1
            session.add(record)
            session.flush()

    def create_source_item_with_packages(
        self,
        source_item: SourceItem,
        package_names: list[str],
        *,
        skip_packages: list[str] | None = None,
    ) -> None:
        skip_set = set(skip_packages or [])
        now = utc_now()
        record = SourceItemRecord(
            id=source_item.id,
            source_type=source_item.source_type,
            source_id=source_item.source_id,
            content_type=source_item.content_type,
            content=source_item.content,
            metadata_json=self._dumps(source_item.metadata),
            occurred_at=source_item.occurred_at,
            actor_ref=source_item.actor_ref,
            agent_ref=source_item.agent_ref,
            role=source_item.role,
            container_ref=source_item.container_ref,
            thread_ref=source_item.thread_ref,
            source_ref=source_item.source_ref,
            artifact_kind=source_item.artifact_kind,
            visibility=source_item.visibility,
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
        with self._begin_immediate() as session:
            if source_item.thread_ref is not None and source_item.container_ref is not None:
                count = session.execute(
                    text(
                        "SELECT COUNT(*) FROM source_items "
                        "WHERE container_ref = :container_ref AND thread_ref = :thread_ref"
                    ),
                    {"container_ref": source_item.container_ref, "thread_ref": source_item.thread_ref},
                ).scalar()
                record.thread_position = count + 1
            else:
                record.thread_position = 1
            session.add(record)
            session.flush()
            source_item_created_at = self._normalize_datetime(record.created_at) or record.created_at
            for pkg in package_names:
                status = "skipped" if pkg in skip_set else "pending"
                session.add(
                    PackageProcessingStatusRecord(
                        source_item_id=source_item.id,
                        package_name=pkg,
                        status=status,
                        attempts=0,
                        source_item_created_at=source_item_created_at,
                        created_at=now,
                    )
                )

    def get_source_item(self, source_item_id: str) -> SourceItem:
        with self._session_factory() as session:
            record = session.get(SourceItemRecord, source_item_id)
            if record is None:
                raise KeyError(source_item_id)
            return self._to_source_item(record)

    def get_source_items(self, ids) -> dict[str, SourceItem]:
        # Batched counterpart to get_source_item: one `WHERE id IN (...)` for the
        # whole set, so the shared retrieval path stops re-reading each candidate
        # per gate. Missing ids are simply absent from the returned map.
        id_list = list(dict.fromkeys(ids))  # dedupe, preserve order
        if not id_list:
            return {}
        with self._session_factory() as session:
            records = session.scalars(
                select(SourceItemRecord).where(SourceItemRecord.id.in_(id_list))
            ).all()
            return {record.id: self._to_source_item(record) for record in records}

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

    def list_source_item_neighbors(
        self,
        container_ref: str,
        thread_ref: str,
        *,
        anchor_created_at: datetime,
        anchor_id: str,
        before: int,
        after: int,
    ) -> tuple[list[SourceItem], list[SourceItem]]:
        """Return (preceding, following) raw turns adjacent to an anchor in a thread.

        Bounded two-sided window ordered by ``(created_at, id)`` — NOT by
        ``thread_position``, which is not contiguous or unique (retention
        hard-deletes rows and positions are ``COUNT(*)+1`` with no unique
        constraint, so gaps and duplicate positions occur). The LIMIT is pushed
        into SQL on each side so this never walks the whole transcript. Both
        lists are returned in ascending ``(created_at, id)`` order.
        """
        preceding: list[SourceItem] = []
        following: list[SourceItem] = []
        with self._session_factory() as session:
            if before > 0:
                rows = session.scalars(
                    select(SourceItemRecord)
                    .where(
                        SourceItemRecord.container_ref == container_ref,
                        SourceItemRecord.thread_ref == thread_ref,
                        or_(
                            SourceItemRecord.created_at < anchor_created_at,
                            and_(
                                SourceItemRecord.created_at == anchor_created_at,
                                SourceItemRecord.id < anchor_id,
                            ),
                        ),
                    )
                    .order_by(SourceItemRecord.created_at.desc(), SourceItemRecord.id.desc())
                    .limit(before)
                ).all()
                preceding = [self._to_source_item(r) for r in reversed(rows)]
            if after > 0:
                rows = session.scalars(
                    select(SourceItemRecord)
                    .where(
                        SourceItemRecord.container_ref == container_ref,
                        SourceItemRecord.thread_ref == thread_ref,
                        or_(
                            SourceItemRecord.created_at > anchor_created_at,
                            and_(
                                SourceItemRecord.created_at == anchor_created_at,
                                SourceItemRecord.id > anchor_id,
                            ),
                        ),
                    )
                    .order_by(SourceItemRecord.created_at.asc(), SourceItemRecord.id.asc())
                    .limit(after)
                ).all()
                following = [self._to_source_item(r) for r in rows]
        return preceding, following

    def list_top_level_messages_for_container(
        self,
        container_ref: str,
        after_created_at: datetime | None = None,
        max_items: int | None = None,
    ) -> list[SourceItem]:
        with self._session_factory() as session:
            query = (
                select(SourceItemRecord)
                .where(
                    SourceItemRecord.container_ref == container_ref,
                    SourceItemRecord.thread_position == 1,
                )
            )
            if after_created_at is not None:
                query = query.where(SourceItemRecord.created_at > after_created_at)
            if max_items is not None:
                query = query.order_by(
                    SourceItemRecord.created_at.desc(),
                    SourceItemRecord.id.desc(),
                ).limit(max_items)
                records = list(session.scalars(query).all())
                records.sort(key=lambda r: (r.created_at, r.id))
            else:
                query = query.order_by(
                    SourceItemRecord.created_at.asc(),
                    SourceItemRecord.id.asc(),
                )
                records = list(session.scalars(query).all())
        return [self._to_source_item(record) for record in records]

    def get_thread_stats(self, thread_ref: str, *, exclude_item_id: str | None = None) -> ThreadStats:
        with self._session_factory() as session:
            query = select(
                func.count(SourceItemRecord.id),
                func.max(SourceItemRecord.created_at),
            ).where(SourceItemRecord.thread_ref == thread_ref)
            if exclude_item_id is not None:
                query = query.where(SourceItemRecord.id != exclude_item_id)
            row = session.execute(query).one()
            return ThreadStats(item_count=row[0], latest_created_at=row[1])

    def create_memory_object(self, memory_object: MemoryObject) -> None:
        record = MemoryObjectRecord(
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
        self._with_retry(lambda session: session.add(record))

    def insert_shadow_extraction(
        self,
        *,
        rows: list[MemoryObjectShadowRecord],
    ) -> None:
        """Bulk-insert shadow-extraction rows for one source item.

        W5 PR 1 helper. Persistence path is intentionally disjoint from
        the live memory-object writer — this helper touches ONLY
        ``memory_objects_shadow`` and never any live table. Concurrency
        goes through ``_with_retry`` (same serialization guarantee as
        ``create_memory_object``); the shadow row set for one LLM call
        is committed atomically as one transaction.

        Callers must guarantee every row shares the same
        ``shadow_run_id``. Empty ``rows`` is a no-op.
        """
        if not rows:
            return

        def _do(session):
            for row in rows:
                session.add(row)

        self._with_retry(_do)

    def get_memory_object(self, memory_object_id: str) -> MemoryObject:
        with self._session_factory() as session:
            record = session.get(MemoryObjectRecord, memory_object_id)
            if record is None:
                raise KeyError(memory_object_id)
            return self._to_memory_object(record)

    def list_supersession_successor_ids(self, memory_object_id: str) -> tuple[str, ...]:
        with self._session_factory() as session:
            record = session.get(MemoryObjectRecord, memory_object_id)
            if record is None:
                raise KeyError(memory_object_id)
            successor_ids = set()
            if record.superseded_by_id:
                successor_ids.add(record.superseded_by_id)
            successor_ids.update(session.scalars(select(RelationRecord.from_id).where(
                RelationRecord.from_kind == "memory_object",
                RelationRecord.to_id == memory_object_id,
                RelationRecord.relation_type == "supersedes",
                RelationRecord.to_kind == "memory_object",
            )).all())
        return tuple(sorted(successor_ids))

    def update_memory_object_lifecycle(self, memory_object_id: str, lifecycle: str) -> None:
        def _do(session):
            record = session.get(MemoryObjectRecord, memory_object_id)
            if record is None:
                raise KeyError(memory_object_id)
            record.lifecycle = lifecycle
        self._with_retry(_do)

    def store_memory_flag(self, flag: MemoryFlag) -> None:
        def _do(session):
            record = session.get(MemoryObjectRecord, flag.memory_object_id)
            if record is None:
                raise KeyError(flag.memory_object_id)
            session.add(MemoryFlagRecord(
                id=flag.id,
                memory_object_id=flag.memory_object_id,
                reason=flag.reason,
                source_ref=flag.source_ref,
                flagged_at=flag.flagged_at,
            ))
        self._with_retry(_do)

    # ── W3 explicit memory-write methods ─────────────────────────────
    #
    # These four methods back the pallium_remember / pallium_correct /
    # pallium_supersede / pallium_forget MCP tools. Each is atomic (wrapped
    # in _with_retry which uses session.begin()). They only manipulate the
    # W3 columns added in the W3 storage-schema PR; they do NOT create or
    # delete rows in memory_objects — that path goes through
    # create_memory_object.
    #
    # Invariant 1 (see docs/context/lessons.md): none of these methods
    # update retrieval ranking or accessibility state. `origin` is stored
    # for audit and dashboard filtering; `superseded_by_id` and
    # `is_soft_deleted` gate visibility via retrieval filters but do not
    # boost any ranking. `correction_reason` is audit-only.

    def mark_memory_origin(
        self,
        memory_object_id: str,
        *,
        origin: str,
        origin_session_id: str | None = None,
        origin_agent_id: str | None = None,
    ) -> None:
        """Set W3 origin fields on an existing memory.

        Called by the explicit-write path AFTER create_memory_object so the
        agent's session / agent_ref are audit-recorded. `origin` must be
        one of the enum values: 'agent_explicit', 'agent_inferred',
        'user_requested'. Validation happens at the MCP tool boundary; this
        method trusts its inputs.

        Idempotent: calling twice with the same values is a no-op.

        Raises KeyError if the memory_object does not exist.
        """
        allowed = {"agent_explicit", "agent_inferred", "user_requested"}
        if origin not in allowed:
            raise ValueError(f"origin must be one of {sorted(allowed)}, got {origin!r}")

        def _do(session):
            record = session.get(MemoryObjectRecord, memory_object_id)
            if record is None:
                raise KeyError(memory_object_id)
            record.origin = origin
            if origin_session_id is not None:
                record.origin_session_id = origin_session_id
            if origin_agent_id is not None:
                record.origin_agent_id = origin_agent_id
        self._with_retry(_do)

    def link_supersession(
        self,
        old_memory_object_id: str,
        new_memory_object_id: str,
        *,
        correction_reason: str | None = None,
    ) -> None:
        """Mark old memory as superseded by new memory. Atomic.

        Sets on the old memory:
        - lifecycle='superseded'
        - superseded_by_id=new_memory_object_id
        - correction_reason (if provided)

        Conflict handling: if the old memory is already superseded
        (lifecycle != 'active' OR superseded_by_id set), raises
        SupersessionConflictError. This lets the MCP tool return 409
        Conflict to the caller — first writer wins.

        The new memory must already exist (create_memory_object first),
        otherwise raises KeyError for new_memory_object_id.
        """
        def _do(session):
            old = session.get(MemoryObjectRecord, old_memory_object_id)
            if old is None:
                raise KeyError(old_memory_object_id)
            new = session.get(MemoryObjectRecord, new_memory_object_id)
            if new is None:
                raise KeyError(new_memory_object_id)
            if old.lifecycle != "active" or old.superseded_by_id is not None:
                raise SupersessionConflictError(
                    f"memory {old_memory_object_id!r} is not active "
                    f"(lifecycle={old.lifecycle!r}, "
                    f"superseded_by_id={old.superseded_by_id!r})"
                )
            old.lifecycle = "superseded"
            old.superseded_by_id = new_memory_object_id
            if correction_reason is not None:
                old.correction_reason = correction_reason
        self._with_retry(_do)

    def soft_delete_memory(
        self,
        memory_object_id: str,
        *,
        reason: str,
        deleted_at: datetime | None = None,
    ) -> bool:
        """Soft-delete a memory (pallium_forget).

        Sets is_soft_deleted=1, soft_deleted_at, soft_delete_reason.
        Does NOT change lifecycle — a soft-deleted memory may still be
        'active' or 'superseded'; the tombstone is orthogonal.

        Idempotent: calling on an already-soft-deleted memory returns
        False without modifying anything. First soft-delete returns True.

        Raises KeyError if the memory_object does not exist.
        """
        def _do(session):
            record = session.get(MemoryObjectRecord, memory_object_id)
            if record is None:
                raise KeyError(memory_object_id)
            if record.is_soft_deleted == 1:
                return False
            record.is_soft_deleted = 1
            record.soft_deleted_at = deleted_at or utc_now()
            record.soft_delete_reason = reason
            return True
        return self._with_retry(_do)

    def forget_source_item(
        self,
        source_item_id: str,
        *,
        reason: str,
        actor_ref: str | None = None,
        forgotten_at: datetime | None = None,
    ) -> bool:
        """User-requested forget of a single raw source turn.

        Soft + auditable: sets forgotten_at / forgotten_by / forgotten_reason;
        the row and its index entries persist (retrieval filters it out at
        candidate time). Distinct from ``soft_delete_memory`` (memory objects).

        Idempotent: returns False without modifying an already-forgotten row;
        first forget returns True. Raises KeyError if the item does not exist.
        """
        def _do(session):
            record = session.get(SourceItemRecord, source_item_id)
            if record is None:
                raise KeyError(source_item_id)
            if record.forgotten_at is not None:
                return False
            record.forgotten_at = forgotten_at or utc_now()
            record.forgotten_by = actor_ref
            record.forgotten_reason = reason
            return True
        return self._with_retry(_do)

    def forget_source_scope(
        self,
        *,
        container_ref: str,
        thread_ref: str | None = None,
        reason: str,
        actor_ref: str | None = None,
        forgotten_at: datetime | None = None,
    ) -> int:
        """Point-in-time bulk forget of raw turns within a bounded scope.

        Marks every currently-present, not-yet-forgotten source item in the
        (container_ref[, thread_ref]) scope as forgotten. This is point-in-time:
        turns ingested AFTER the call are unaffected (no standing rule).
        Returns the number of rows newly forgotten. ``container_ref`` is
        required so the scope is always bounded to one container.
        """
        def _do(session):
            stmt = select(SourceItemRecord).where(
                SourceItemRecord.container_ref == container_ref,
                SourceItemRecord.forgotten_at.is_(None),
            )
            if thread_ref is not None:
                stmt = stmt.where(SourceItemRecord.thread_ref == thread_ref)
            records = session.scalars(stmt).all()
            ts = forgotten_at or utc_now()
            for record in records:
                record.forgotten_at = ts
                record.forgotten_by = actor_ref
                record.forgotten_reason = reason
            return len(records)
        return self._with_retry(_do)

    def correct_memory_payload(
        self,
        memory_object_id: str,
        *,
        new_payload: dict,
        correction_reason: str,
    ) -> None:
        """In-place correction of a memory (pallium_correct).

        Updates payload_json + correction_reason atomically. Does NOT
        change lifecycle — this is "the extraction was incomplete or
        mislabeled" semantics, not "obsolete, replace with a new memory."
        For the latter, callers should use link_supersession instead.

        Raises SupersessionConflictError if the memory is already
        superseded — a superseded memory should not be modified in place;
        the caller should supersede the current active memory in the
        chain instead.

        Raises KeyError if the memory_object does not exist.
        """
        def _do(session):
            record = session.get(MemoryObjectRecord, memory_object_id)
            if record is None:
                raise KeyError(memory_object_id)
            if record.lifecycle != "active" or record.superseded_by_id is not None:
                raise SupersessionConflictError(
                    f"cannot correct non-active memory {memory_object_id!r} "
                    f"(lifecycle={record.lifecycle!r}, "
                    f"superseded_by_id={record.superseded_by_id!r})"
                )
            record.payload_json = self._dumps(new_payload) or "{}"
            record.correction_reason = correction_reason
        self._with_retry(_do)

    # ── /W3 explicit memory-write methods ────────────────────────────

    def record_memory_feedback(
        self,
        memory_object_id: str,
        rating: str,
        reason: str | None,
        query_context: str | None,
        query_audit_log_id: str | None,
        rater_ref: str | None,
        thread_ref: str | None = None,
        container_ref: str | None = None,
    ) -> str:
        """Record a relevance feedback judgment for an injected memory.

        Unlike store_memory_flag, this does NOT check for memory existence —
        feedback is an analytics record and should succeed even for deleted memories.
        Returns the feedback record id.
        """
        from core.models import new_id
        feedback_id = new_id()
        def _do(session):
            memory_type = None
            memory_text = None
            mem_record = session.get(MemoryObjectRecord, memory_object_id)
            if mem_record:
                memory_type = mem_record.type
                payload = json.loads(mem_record.payload_json) if mem_record.payload_json else {}
                memory_text = _extract_display_text(payload)

            resolved_audit_id = query_audit_log_id
            if resolved_audit_id is None and (thread_ref or container_ref):
                one_hour_ago = utc_now() - timedelta(hours=1)
                stmt = (
                    select(QueryAuditLogRecord.id)
                    .where(
                        QueryAuditLogRecord.injected_blocks_json.contains(memory_object_id),
                        QueryAuditLogRecord.should_inject == 1,
                        QueryAuditLogRecord.created_at >= one_hour_ago,
                    )
                )
                if thread_ref:
                    stmt = stmt.where(QueryAuditLogRecord.thread_ref == thread_ref)
                if container_ref:
                    stmt = stmt.where(QueryAuditLogRecord.container_ref == container_ref)
                stmt = stmt.order_by(QueryAuditLogRecord.created_at.desc()).limit(1)
                resolved_audit_id = session.execute(stmt).scalar_one_or_none()

            session.add(MemoryFeedbackRecord(
                id=feedback_id,
                memory_object_id=memory_object_id,
                rating=rating,
                reason=reason,
                query_context=query_context,
                query_audit_log_id=resolved_audit_id,
                rater_ref=rater_ref,
                created_at=utc_now(),
                memory_type=memory_type,
                memory_text=memory_text,
                thread_ref=thread_ref,
                container_ref=container_ref,
            ))
        self._with_retry(_do)
        return feedback_id

    def count_unique_flag_sources(self, memory_object_id: str, window_days: int) -> int:
        cutoff = utc_now() - timedelta(days=window_days)
        with self._session_factory() as session:
            count = session.scalar(
                select(func.count(func.distinct(MemoryFlagRecord.source_ref))).where(
                    MemoryFlagRecord.memory_object_id == memory_object_id,
                    MemoryFlagRecord.flagged_at >= cutoff,
                )
            )
            return count or 0

    def count_total_flags(self, memory_object_id: str) -> int:
        with self._session_factory() as session:
            count = session.scalar(
                select(func.count(MemoryFlagRecord.id)).where(
                    MemoryFlagRecord.memory_object_id == memory_object_id,
                )
            )
            return count or 0

    def list_memory_flags(self, memory_object_id: str) -> list[MemoryFlag]:
        with self._session_factory() as session:
            records = session.scalars(
                select(MemoryFlagRecord)
                .where(MemoryFlagRecord.memory_object_id == memory_object_id)
                .order_by(MemoryFlagRecord.flagged_at.asc())
            ).all()
            return [
                MemoryFlag(
                    id=r.id,
                    memory_object_id=r.memory_object_id,
                    reason=r.reason,
                    source_ref=r.source_ref,
                    flagged_at=self._normalize_datetime(r.flagged_at) or r.flagged_at,
                )
                for r in records
            ]

    def refresh_memory_object_freshness(self, memory_object_id: str):
        def _do(session):
            return self._refresh_memory_object_freshness_in_session(session, memory_object_id)
        return self._with_retry(_do)

    def list_memory_objects(
        self,
        memory_types: list[str] | None = None,
        lifecycle: str | None = None,
        container_ref: str | None = None,
        subject_in: list[str] | None = None,
        *,
        include_soft_deleted: bool = False,
        include_candidates: bool = False,
    ) -> list[MemoryObject]:
        with self._session_factory() as session:
            statement = select(MemoryObjectRecord)
            if memory_types:
                statement = statement.where(MemoryObjectRecord.type.in_(memory_types))
            if lifecycle is not None:
                statement = statement.where(MemoryObjectRecord.lifecycle == lifecycle)
            elif not include_candidates:
                # PR 3 of operational_fact redesign: default filter —
                # non-allowlist lifecycles (``candidate`` and any future
                # hidden values) are invisible unless explicitly opted
                # into via ``include_candidates=True`` or an exact
                # ``lifecycle=...`` filter. Preserves existing behavior
                # for ``active`` / ``superseded`` / ``suppressed``.
                statement = statement.where(
                    MemoryObjectRecord.lifecycle.in_(_DEFAULT_VISIBLE_LIFECYCLES)
                )
            if container_ref is not None:
                statement = statement.where(MemoryObjectRecord.container_ref == container_ref)
            if subject_in is not None:
                statement = statement.where(MemoryObjectRecord.subject.in_(subject_in))
            if not include_soft_deleted:
                # PR 1: default filter — tombstoned rows must not be
                # returned unless the caller explicitly opts in
                # (audit tools, undo replays).
                statement = statement.where(MemoryObjectRecord.is_soft_deleted == 0)
            records = session.scalars(statement).all()
        return [self._to_memory_object(record) for record in records]

    def list_memory_objects_for_source_item(
        self, source_item_id: str, *,
        include_soft_deleted: bool = False,
        include_candidates: bool = False,
    ) -> list[MemoryObject]:
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
            statement = select(MemoryObjectRecord).where(
                MemoryObjectRecord.id.in_(memory_object_ids)
            )
            if not include_soft_deleted:
                statement = statement.where(MemoryObjectRecord.is_soft_deleted == 0)
            if not include_candidates:
                statement = statement.where(
                    MemoryObjectRecord.lifecycle.in_(_DEFAULT_VISIBLE_LIFECYCLES)
                )
            records = session.scalars(statement).all()
        return [self._to_memory_object(record) for record in records]

    def list_memory_objects_for_source_items(
        self, source_item_ids: list[str], *,
        include_soft_deleted: bool = False,
        include_candidates: bool = False,
    ) -> dict[str, list[MemoryObject]]:
        if not source_item_ids:
            return {}
        with self._session_factory() as session:
            relation_records = session.scalars(
                select(RelationRecord).where(
                    RelationRecord.relation_type == "supported_by",
                    RelationRecord.to_kind == "source_item",
                    RelationRecord.to_id.in_(source_item_ids),
                    RelationRecord.from_kind == "memory_object",
                )
            ).all()
            source_to_memory_ids: dict[str, list[str]] = {}
            all_memory_ids: set[str] = set()
            for rel in relation_records:
                source_to_memory_ids.setdefault(rel.to_id, []).append(rel.from_id)
                all_memory_ids.add(rel.from_id)
            if not all_memory_ids:
                return {sid: [] for sid in source_item_ids}
            memory_stmt = select(MemoryObjectRecord).where(
                MemoryObjectRecord.id.in_(list(all_memory_ids))
            )
            if not include_soft_deleted:
                memory_stmt = memory_stmt.where(MemoryObjectRecord.is_soft_deleted == 0)
            if not include_candidates:
                memory_stmt = memory_stmt.where(
                    MemoryObjectRecord.lifecycle.in_(_DEFAULT_VISIBLE_LIFECYCLES)
                )
            memory_records = session.scalars(memory_stmt).all()
            memory_by_id = {record.id: self._to_memory_object(record) for record in memory_records}
        result: dict[str, list[MemoryObject]] = {}
        for sid in source_item_ids:
            result[sid] = [memory_by_id[mid] for mid in source_to_memory_ids.get(sid, []) if mid in memory_by_id]
        return result

    def count_distinct_threads_for_conflict_slot(
        self,
        *,
        container_ref: str,
        command_family: str,
        artifact_role: str,
        scope_kind: str,
        scope_ref: str,
        artifact_normalized: str,
        visibility: str = "private",
    ) -> int:
        """See :meth:`StorageProvider.count_distinct_threads_for_conflict_slot`.

        PR 4 of operational_fact redesign. Uses ``json_extract`` on the
        payload_json column to match the slot key without requiring a
        payload-column split. Filters both candidate and active rows
        (so a slot with one active + one candidate row already counts
        the two threads) and excludes soft-deleted rows.

        Scope isolation: filters on ``visibility`` so a private
        candidate can't accidentally count as evidence for a global
        slot in the same container (or vice versa). Same defense-in-
        depth as the container_ref filter — the plan's §Invariants
        section calls this out explicitly.
        """
        from semantic.operational_fact import OPERATIONAL_FACT_TYPE

        with self._session_factory() as session:
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

    def create_relation(self, relation: Relation) -> None:
        record = RelationRecord(
            id=relation.id,
            from_kind=relation.from_kind,
            from_id=relation.from_id,
            relation_type=relation.relation_type,
            to_kind=relation.to_kind,
            to_id=relation.to_id,
        )
        def _do(session):
            session.add(record)
            if relation.from_kind == "memory_object":
                session.flush()
                self._refresh_memory_object_freshness_in_session(session, relation.from_id)
        self._with_retry(_do)

    def list_relations_for_source_item(self, source_item_id: str) -> list[Relation]:
        with self._session_factory() as session:
            records = session.scalars(
                select(RelationRecord).where(
                    RelationRecord.to_kind == "source_item",
                    RelationRecord.to_id == source_item_id,
                )
            ).all()
        return [self._to_relation(record) for record in records]

    def _resolve_container_ref_in_session(
        self, session, target_kind: str, target_id: str,
    ) -> str | None:
        """Resolve container_ref for an index target within an existing session."""
        if target_kind == "source_item":
            record = session.get(SourceItemRecord, target_id)
            return record.container_ref if record else None
        if target_kind == "memory_object":
            record = session.get(MemoryObjectRecord, target_id)
            if record is None:
                return None
            if record.container_ref is not None:
                return record.container_ref
            # Fallback: envelope_json → scope.container_ref
            if record.envelope_json:
                try:
                    envelope = json.loads(record.envelope_json)
                    return envelope.get("scope", {}).get("container_ref")
                except (json.JSONDecodeError, TypeError):
                    return None
            return None
        return None

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
        def _do(session):
            session.add(record)
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
        self._with_retry(_do)

    def list_index_entries_for_target(self, target_kind: str, target_id: str) -> list[IndexEntry]:
        with self._session_factory() as session:
            records = session.scalars(
                select(IndexEntryRecord).where(
                    IndexEntryRecord.target_kind == target_kind,
                    IndexEntryRecord.target_id == target_id,
                )
            ).all()
        return [self._to_index_entry(record) for record in records]

    def get_index_entry(self, index_entry_id: str) -> IndexEntry:
        with self._session_factory() as session:
            record = session.get(IndexEntryRecord, index_entry_id)
            if record is None:
                raise KeyError(index_entry_id)
            return self._to_index_entry(record)

    def get_index_entries(self, index_entry_ids: list[str]) -> dict[str, IndexEntry]:
        if not index_entry_ids:
            return {}
        with self._session_factory() as session:
            records = session.scalars(
                select(IndexEntryRecord).where(IndexEntryRecord.id.in_(index_entry_ids))
            ).all()
        return {record.id: self._to_index_entry(record) for record in records}

    def find_index_entry(self, target_kind, target_id, index_type, text_view_name):
        with self._session_factory() as session:
            row = session.scalars(
                select(IndexEntryRecord).where(
                    IndexEntryRecord.target_kind == target_kind,
                    IndexEntryRecord.target_id == target_id,
                    IndexEntryRecord.index_type == index_type,
                    IndexEntryRecord.text_view_name == text_view_name,
                )
            ).first()
            return self._to_index_entry(row) if row else None

    def list_index_entries_by_type(self, index_type: str) -> list[IndexEntry]:
        with self._session_factory() as session:
            records = session.scalars(
                select(IndexEntryRecord).where(IndexEntryRecord.index_type == index_type)
            ).all()
        return [self._to_index_entry(record) for record in records]

    def list_index_entries_by_type_page(
        self,
        index_type: str,
        *,
        after_id: str | None = None,
        limit: int | None = None,
    ) -> list[IndexEntry]:
        with self._session_factory() as session:
            statement = (
                select(IndexEntryRecord)
                .where(IndexEntryRecord.index_type == index_type)
                .order_by(IndexEntryRecord.id.asc())
            )
            if after_id is not None:
                statement = statement.where(IndexEntryRecord.id > after_id)
            if limit is not None:
                statement = statement.limit(limit)
            records = session.scalars(statement).all()
        return [self._to_index_entry(record) for record in records]

    def count_index_entries_by_type(self, index_type: str) -> int:
        with self._session_factory() as session:
            count = session.scalar(
                select(func.count()).select_from(IndexEntryRecord).where(
                    IndexEntryRecord.index_type == index_type
                )
            )
        return count or 0

    def update_index_entry_provider(self, index_entry_id: str, provider_name: str, provider_version: str) -> None:
        def _do(session):
            record = session.get(IndexEntryRecord, index_entry_id)
            if record is None:
                raise KeyError(index_entry_id)
            record.provider_name = provider_name
            record.provider_version = provider_version
        self._with_retry(_do)

    def update_index_entry_text_view(self, index_entry_id: str, text_view: str) -> None:
        def _do(session):
            record = session.get(IndexEntryRecord, index_entry_id)
            if record is None:
                raise KeyError(index_entry_id)
            record.text_view = text_view
        self._with_retry(_do)

    def redact_index_entry_text_view(
        self, index_entry_id: str, new_text_view: str,
    ) -> None:
        """Rewrite ``index_entries.text_view`` AND its ``lexical_fts``
        row (FTS5 cannot be UPDATEd on columns — DELETE + INSERT is
        the required pattern).

        This exists specifically for the PR-0 secrets-purge path: the
        pre-existing :meth:`update_index_entry_text_view` at
        :meth:`SqliteStorage.update_index_entry_text_view` above touches
        only the ``index_entries`` table, which leaves the FTS index
        holding the pre-redaction ``text_view`` — retrievable by
        lexical search. That is unsafe for secret redaction.

        Mirror of :meth:`_retarget_index_entries_in_session`
        (lines below) for a single entry ID, changing text_view
        instead of target_id.

        Vector rows (``index_type != 'lexical'``) are unaffected —
        their text_view lives on the record itself.

        Raises ``KeyError`` if the entry does not exist.
        """
        def _do(session):
            record = session.get(IndexEntryRecord, index_entry_id)
            if record is None:
                raise KeyError(index_entry_id)
            record.text_view = new_text_view
            if record.index_type != "lexical":
                return
            container_ref = self._resolve_container_ref_in_session(
                session, record.target_kind, record.target_id,
            )
            session.execute(
                text("DELETE FROM lexical_fts WHERE index_entry_id = :id"),
                {"id": index_entry_id},
            )
            insert_lexical_fts_row(
                session,
                index_entry_id=index_entry_id,
                target_kind=record.target_kind,
                target_id=record.target_id,
                text_view=new_text_view,
                text_view_name=record.text_view_name,
                container_ref=container_ref,
            )
        self._with_retry(_do)

    def retarget_index_entries_for_target(
        self, target_kind: str, old_target_id: str, new_target_id: str,
    ) -> int:
        def _do(session):
            return self._retarget_index_entries_in_session(
                session, target_kind, old_target_id, new_target_id,
            )
        return self._with_retry(_do)

    def _retarget_index_entries_in_session(
        self,
        session: Session,
        target_kind: str,
        old_target_id: str,
        new_target_id: str,
    ) -> int:
        """Move all index entries from old_target_id to new_target_id within an open session.

        Updates the index_entries table and rebuilds lexical_fts rows (FTS5
        does not support UPDATE on columns, so we DELETE + INSERT).
        The vector index is unaffected — it is keyed by entry_id, and the
        target_id is resolved at query time via get_index_entry().
        """
        records = session.scalars(
            select(IndexEntryRecord).where(
                IndexEntryRecord.target_kind == target_kind,
                IndexEntryRecord.target_id == old_target_id,
            )
        ).all()
        if not records:
            return 0

        new_container_ref = self._resolve_container_ref_in_session(
            session, target_kind, new_target_id,
        )

        for record in records:
            record.target_id = new_target_id
            if record.index_type == "lexical":
                # FTS5 cannot UPDATE columns; delete old row and insert new.
                session.execute(
                    text("DELETE FROM lexical_fts WHERE index_entry_id = :id"),
                    {"id": record.id},
                )
                insert_lexical_fts_row(
                    session,
                    index_entry_id=record.id,
                    target_kind=target_kind,
                    target_id=new_target_id,
                    text_view=record.text_view,
                    text_view_name=record.text_view_name,
                    container_ref=new_container_ref,
                )
        return len(records)

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

    def find_latest_checkpoint_for_thread(self, container_ref: str, thread_ref: str) -> MemoryObject | None:
        with self._session_factory() as session:
            record = session.execute(
                select(MemoryObjectRecord)
                .join(
                    RelationRecord,
                    (RelationRecord.from_id == MemoryObjectRecord.id)
                    & (RelationRecord.from_kind == "memory_object")
                    & (RelationRecord.relation_type == "supported_by")
                    & (RelationRecord.to_kind == "source_item"),
                )
                .join(
                    SourceItemRecord,
                    SourceItemRecord.id == RelationRecord.to_id,
                )
                .where(
                    MemoryObjectRecord.type == "task_checkpoint",
                    MemoryObjectRecord.container_ref == container_ref,
                    MemoryObjectRecord.lifecycle == "active",
                    SourceItemRecord.thread_ref == thread_ref,
                )
                .order_by(MemoryObjectRecord.freshness_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if record is None:
                return None
            return self._to_memory_object(record)

    def write_query_audit_row(self, row: dict[str, Any]) -> None:
        record = QueryAuditLogRecord(**row)
        self._with_retry(lambda session: session.add(record))

    def write_subtask_selector_shadow_row(self, row: dict[str, Any]) -> None:
        """Persist one shadow sub-task-selector observation.

        Write-only side table for the REPORT6 shadow experiment; never
        read by the injection pipeline. See SubtaskSelectorShadowRecord.
        """
        record = SubtaskSelectorShadowRecord(**row)
        self._with_retry(lambda session: session.add(record))

    def write_historical_lookup_event_row(self, row: dict[str, Any]) -> None:
        """Persist one historical-lookup reuse funnel event (write-only).

        Unconditional telemetry — NOT gated on query_audit_log. Never mutated
        after write and never read by the injection pipeline. See
        HistoricalLookupReuseEventRecord.
        """
        record = HistoricalLookupReuseEventRecord(**row)
        self._with_retry(lambda session: session.add(record))

    def get_historical_lookup_event_row(self, event_id: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            record = session.get(HistoricalLookupReuseEventRecord, event_id)
            if record is None:
                return None
            return {
                "id": record.id,
                "event_type": record.event_type,
                "session_id": record.session_id,
                "container_ref": record.container_ref,
                "actor_ref": record.actor_ref,
                "visibility": record.visibility,
                "trigger_origin": record.trigger_origin,
                "source_session_ref": record.source_session_ref,
                "query_text": record.query_text,
                "request_source_item_id": record.request_source_item_id,
                "parent_lookup_id": record.parent_lookup_id,
                "exposed_json": record.exposed_json,
            }

    def finalize_historical_lookup_delivery(self, attempt_id: str, payload: dict[str, Any]) -> str:
        final_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "pallium:historical-delivery:" + attempt_id))

        def commit(session: Session) -> str:
            attempt = session.get(HistoricalLookupReuseEventRecord, attempt_id)
            if attempt is None:
                raise KeyError(attempt_id)
            event_type = {
                "lookup_attempt": "lookup",
                "expansion_attempt": "expansion",
            }.get(attempt.event_type)
            if event_type is None:
                raise ValueError("delivery attempt is not finalizable")
            parent = attempt.parent_lookup_id
            if event_type == "expansion":
                parent_row = session.get(HistoricalLookupReuseEventRecord, parent) if parent else None
                if parent_row is None or parent_row.event_type != "lookup":
                    raise ValueError("expansion attempt has no finalized parent lookup")
                scope = ("container_ref", "session_id", "actor_ref", "visibility")
                if any(getattr(parent_row, key) != getattr(attempt, key) for key in scope):
                    raise ValueError("parent lookup is out of scope")
            exposed_json = payload["exposed_json"]
            existing = session.get(HistoricalLookupReuseEventRecord, final_id)
            if existing is not None:
                same = (
                    existing.event_type == event_type
                    and existing.parent_lookup_id == parent
                    and existing.container_ref == attempt.container_ref
                    and existing.session_id == attempt.session_id
                    and existing.actor_ref == attempt.actor_ref
                    and existing.visibility == attempt.visibility
                    and existing.exposed_json == exposed_json
                )
                if not same:
                    raise RuntimeError("conflicting delivery retry")
                return final_id
            session.add(HistoricalLookupReuseEventRecord(
                id=final_id,
                created_at=attempt.created_at,
                event_type=event_type,
                session_id=attempt.session_id,
                container_ref=attempt.container_ref,
                actor_ref=attempt.actor_ref,
                trigger_origin=attempt.trigger_origin,
                parent_lookup_id=parent,
                exposed_json=exposed_json,
                visibility=attempt.visibility,
                source_session_ref=attempt.source_session_ref,
                query_text=attempt.query_text,
                request_source_item_id=attempt.request_source_item_id,
            ))
            return final_id

        try:
            return self._with_retry(commit)
        except IntegrityError:
            return self._with_retry(commit)

    def write_historical_lookup_label_row(self, row: dict[str, Any]) -> None:
        """Append one per-rater rung label (append-only).

        A re-label is a new row; existing rows are never mutated. See
        HistoricalLookupReuseLabelRecord.
        """
        record = HistoricalLookupReuseLabelRecord(**row)
        self._with_retry(lambda session: session.add(record))

    # ── Phase 5: memory_usage_audit ──────────────────────────────────
    #
    # See docs/specs/2026-06-27-injection-policy-abstention.md.
    # Distinct from memory_feedback (human ratings); this table records
    # whether the agent actually USED an injected memory, populated
    # asynchronously by an integration-side heuristic (Phase 5b).

    def write_memory_usage_audit_rows(
        self,
        *,
        query_audit_log_id: str,
        injected_blocks: list[dict[str, Any]],
        container_ref: str | None,
        thread_ref: str | None,
        trigger_origin: str | None,
    ) -> list[str]:
        """Write one usage-audit row per injected block.

        Called from `write_query_audit` after the query_audit_log row is
        persisted, so we already have a stable audit id. Rows are
        written with `referenced_in_next_turn=NULL` / `populated_at=NULL`
        — the Phase 5b populator fills those in later via the
        update endpoint.

        Returns the list of inserted row ids in the same order as the
        input blocks.
        """
        from core.models import new_id
        if not injected_blocks:
            return []
        ids: list[str] = []
        records: list[MemoryUsageAuditRecord] = []
        created_at = utc_now()
        for block in injected_blocks:
            memory_object_id = (block or {}).get("memory_object_id")
            if not memory_object_id:
                continue
            row_id = new_id()
            ids.append(row_id)
            records.append(MemoryUsageAuditRecord(
                id=row_id,
                query_audit_log_id=query_audit_log_id,
                memory_object_id=memory_object_id,
                memory_type=(block or {}).get("memory_type"),
                container_ref=container_ref,
                thread_ref=thread_ref,
                trigger_origin=trigger_origin,
                referenced_in_next_turn=None,
                reference_kind=None,
                observation_window_turns=None,
                created_at=created_at,
                populated_at=None,
            ))
        if records:
            self._with_retry(lambda session: session.add_all(records))
        return ids

    def list_memory_usage_audit_rows(
        self,
        query_audit_log_id: str,
    ) -> list[dict[str, Any]]:
        """List all usage-audit rows for a given query, oldest first."""
        def _do(session: Session) -> list[dict[str, Any]]:
            stmt = (
                select(MemoryUsageAuditRecord)
                .where(MemoryUsageAuditRecord.query_audit_log_id == query_audit_log_id)
                .order_by(MemoryUsageAuditRecord.created_at.asc())
            )
            out: list[dict[str, Any]] = []
            for r in session.execute(stmt).scalars().all():
                out.append({
                    "id": r.id,
                    "query_audit_log_id": r.query_audit_log_id,
                    "memory_object_id": r.memory_object_id,
                    "memory_type": r.memory_type,
                    "container_ref": r.container_ref,
                    "thread_ref": r.thread_ref,
                    "trigger_origin": r.trigger_origin,
                    "referenced_in_next_turn": (
                        bool(r.referenced_in_next_turn)
                        if r.referenced_in_next_turn is not None
                        else None
                    ),
                    "reference_kind": r.reference_kind,
                    "observation_window_turns": r.observation_window_turns,
                    "created_at": r.created_at,
                    "populated_at": r.populated_at,
                })
            return out
        return self._with_retry(_do)

    def list_pending_memory_usage_audit_rows_by_thread(
        self,
        thread_ref: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List usage-audit rows for a thread that are still pending
        (`populated_at IS NULL`), newest first.

        Phase 5b populator path: the Stop hook calls this to find which
        rows from recent injections still need a usage verdict. The
        hard cap protects against a runaway thread with thousands of
        unresolved rows.
        """
        # Hard cap to bound matcher cost in the hook.
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
        def _do(session: Session) -> list[dict[str, Any]]:
            stmt = (
                select(MemoryUsageAuditRecord)
                .where(MemoryUsageAuditRecord.thread_ref == thread_ref)
                .where(MemoryUsageAuditRecord.populated_at.is_(None))
                .order_by(MemoryUsageAuditRecord.created_at.desc())
                .limit(limit)
            )
            out: list[dict[str, Any]] = []
            for r in session.execute(stmt).scalars().all():
                out.append({
                    "id": r.id,
                    "query_audit_log_id": r.query_audit_log_id,
                    "memory_object_id": r.memory_object_id,
                    "memory_type": r.memory_type,
                    "container_ref": r.container_ref,
                    "thread_ref": r.thread_ref,
                    "trigger_origin": r.trigger_origin,
                    "referenced_in_next_turn": None,
                    "reference_kind": None,
                    "observation_window_turns": None,
                    "created_at": r.created_at,
                    "populated_at": None,
                })
            return out
        return self._with_retry(_do)

    def update_memory_usage_audit_row(
        self,
        *,
        audit_row_id: str,
        referenced_in_next_turn: bool,
        reference_kind: str | None,
        observation_window_turns: int | None,
    ) -> bool:
        """Update a single usage-audit row.

        Idempotent: if the row is already populated (populated_at IS NOT
        NULL), this is a no-op and returns False. Otherwise updates and
        returns True. Phase 5b populator depends on this idempotence.
        """
        def _do(session: Session) -> bool:
            r = session.get(MemoryUsageAuditRecord, audit_row_id)
            if r is None:
                return False
            if r.populated_at is not None:
                return False  # already populated; no-op for idempotence
            r.referenced_in_next_turn = 1 if referenced_in_next_turn else 0
            r.reference_kind = reference_kind
            r.observation_window_turns = observation_window_turns
            r.populated_at = utc_now()
            return True
        return self._with_retry(_do)

    def _after_commit_processed_source_item_persist(
        self,
        session: Session,
        *,
        source_item_id: str,
        result: ProcessResult,
        supersession_pairs: list[tuple[str, str]],
    ) -> None:
        return None
