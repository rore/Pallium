from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Session, declarative_base


Base = declarative_base()

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
    source_ref = Column(String, nullable=True)
    artifact_kind = Column(String, nullable=True)
    visibility = Column(String, nullable=True, default="private")
    agent_ref = Column(String, nullable=True)
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


class MemoryObjectRecord(Base):
    __tablename__ = "memory_objects"

    id = Column(String, primary_key=True)
    type = Column(String, nullable=False)
    schema_id = Column(String, nullable=False)
    schema_version = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False)
    envelope_json = Column(Text, nullable=True)
    lifecycle = Column(String, nullable=False, default="active")
    visibility = Column(String, nullable=True, default="private")
    container_ref = Column(String, nullable=True)
    actor_ref = Column(String, nullable=True)
    freshness_at = Column(DateTime(timezone=True), nullable=True)
    subject = Column(String, nullable=True)
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
    visibility = Column(String, nullable=True, default="private")
    requested_at = Column(DateTime(timezone=True), nullable=True)
    processing_claimed_by = Column(String, nullable=True)
    processing_claimed_at = Column(DateTime(timezone=True), nullable=True)
    processing_lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    processing_completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class PackageProcessingStatusRecord(Base):
    __tablename__ = "package_processing_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_item_id = Column(String, nullable=False)
    package_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    claimed_by = Column(String, nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("source_item_id", "package_name", name="uq_package_processing_source_package"),
    )


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


class QueryAuditLogRecord(Base):
    __tablename__ = "query_audit_log"

    id = Column(String, primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    source_item_id = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    thread_ref = Column(String, nullable=True)
    container_ref = Column(String, nullable=True)
    actor_ref = Column(String, nullable=True)
    visibility = Column(String, nullable=True)
    query_text = Column(Text, nullable=False)
    should_inject = Column(Integer, nullable=False, default=0)
    decision_reason = Column(String, nullable=False)
    injected_blocks_json = Column(Text, nullable=False, default="[]")


class SQLiteSchemaMixin:
    _SOURCE_ITEM_MIGRATIONS = {
        "occurred_at": "ALTER TABLE source_items ADD COLUMN occurred_at DATETIME",
        "actor_ref": "ALTER TABLE source_items ADD COLUMN actor_ref VARCHAR",
        "role": "ALTER TABLE source_items ADD COLUMN role VARCHAR",
        "container_ref": "ALTER TABLE source_items ADD COLUMN container_ref VARCHAR",
        "thread_ref": "ALTER TABLE source_items ADD COLUMN thread_ref VARCHAR",
        "source_ref": "ALTER TABLE source_items ADD COLUMN source_ref VARCHAR",
        "artifact_kind": "ALTER TABLE source_items ADD COLUMN artifact_kind VARCHAR",
        "visibility": "ALTER TABLE source_items ADD COLUMN visibility VARCHAR DEFAULT 'private'",
        "agent_ref": "ALTER TABLE source_items ADD COLUMN agent_ref VARCHAR",
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
        "visibility": "ALTER TABLE memory_objects ADD COLUMN visibility VARCHAR DEFAULT 'private'",
        "freshness_at": "ALTER TABLE memory_objects ADD COLUMN freshness_at DATETIME",
        "envelope_json": "ALTER TABLE memory_objects ADD COLUMN envelope_json TEXT",
        "container_ref": "ALTER TABLE memory_objects ADD COLUMN container_ref VARCHAR",
        "actor_ref": "ALTER TABLE memory_objects ADD COLUMN actor_ref VARCHAR",
        "subject": "ALTER TABLE memory_objects ADD COLUMN subject VARCHAR",
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
    _UNIQUE_INDEX_MIGRATIONS = {
        "uq_source_items_source_type_source_id": (
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_source_items_source_type_source_id "
            "ON source_items(source_type, source_id)"
        ),
    }
    _INDEX_MIGRATIONS = {
        "idx_memory_objects_subject_lookup": (
            "CREATE INDEX IF NOT EXISTS idx_memory_objects_subject_lookup "
            "ON memory_objects(container_ref, subject, type) "
            "WHERE lifecycle = 'active' AND subject IS NOT NULL"
        ),
    }
    _QUERY_AUDIT_LOG_INDEX_MIGRATIONS = {
        "idx_query_audit_log_thread": (
            "CREATE INDEX IF NOT EXISTS idx_query_audit_log_thread "
            "ON query_audit_log(thread_ref, created_at)"
        ),
        "idx_query_audit_log_actor": (
            "CREATE INDEX IF NOT EXISTS idx_query_audit_log_actor "
            "ON query_audit_log(actor_ref, created_at)"
        ),
        "idx_query_audit_log_container": (
            "CREATE INDEX IF NOT EXISTS idx_query_audit_log_container "
            "ON query_audit_log(container_ref, created_at)"
        ),
    }

    def _initialize_schema(self) -> None:
        with self._schema_initialization_lock():
            Base.metadata.create_all(self._engine)
            self._ensure_source_item_columns()
            self._ensure_memory_object_columns()
            self._ensure_index_entry_columns()
            self._ensure_maintenance_state_columns()
            self._ensure_unique_indexes()
            self._ensure_indexes()
            self._ensure_query_audit_log_indexes()
            self._ensure_fts5_table()
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

    def _ensure_source_item_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(source_items)"))}
            for column_name, migration_sql in self._SOURCE_ITEM_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

    def _ensure_memory_object_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(memory_objects)"))}
            for column_name, migration_sql in self._MEMORY_OBJECT_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

    def _ensure_index_entry_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(index_entries)"))}
            for column_name, migration_sql in self._INDEX_ENTRY_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

    def _ensure_maintenance_state_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(maintenance_state)"))}
            for column_name, migration_sql in self._MAINTENANCE_STATE_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

    def _ensure_unique_indexes(self) -> None:
        with self._engine.begin() as connection:
            existing_indexes = {
                row[1]
                for row in connection.execute(text("PRAGMA index_list(source_items)"))
            }
            for index_name, create_sql in self._UNIQUE_INDEX_MIGRATIONS.items():
                if index_name in existing_indexes:
                    continue
                duplicates = connection.execute(
                    text(
                        "SELECT source_type, source_id, COUNT(*) AS cnt "
                        "FROM source_items "
                        "GROUP BY source_type, source_id "
                        "HAVING cnt > 1"
                    )
                ).fetchall()
                if duplicates:
                    detail = "; ".join(
                        f"({row[0]}, {row[1]}): {row[2]} rows"
                        for row in duplicates[:10]
                    )
                    raise RuntimeError(
                        f"Cannot create unique index {index_name}: "
                        f"duplicate (source_type, source_id) rows exist. "
                        f"Resolve duplicates before restarting. Duplicates: {detail}"
                    )
                connection.execute(text(create_sql))

    def _ensure_indexes(self) -> None:
        with self._engine.begin() as connection:
            for _index_name, create_sql in self._INDEX_MIGRATIONS.items():
                connection.execute(text(create_sql))

    def _ensure_query_audit_log_indexes(self) -> None:
        with self._engine.begin() as connection:
            for _index_name, create_sql in self._QUERY_AUDIT_LOG_INDEX_MIGRATIONS.items():
                connection.execute(text(create_sql))

    def _ensure_fts5_available(self, connection) -> None:
        """Verify FTS5 extension is available. Fail fast with clear message."""
        try:
            connection.execute(text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_check USING fts5(x)"
            ))
            connection.execute(text("DROP TABLE IF EXISTS _fts5_check"))
        except Exception as exc:
            raise RuntimeError(
                "SQLite FTS5 extension is not available. "
                "Pallium requires FTS5 for lexical search. "
                "Python 3.9+ bundles SQLite with FTS5 enabled by default."
            ) from exc

    def _ensure_fts5_table(self) -> None:
        with self._engine.begin() as connection:
            self._ensure_fts5_available(connection)
            connection.execute(text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS lexical_fts USING fts5("
                "text_view, "
                "index_entry_id UNINDEXED, "
                "target_kind UNINDEXED, "
                "target_id UNINDEXED, "
                "text_view_name UNINDEXED, "
                "container_ref UNINDEXED, "
                "tokenize='unicode61 remove_diacritics 2'"
                ")"
            ))


def insert_lexical_fts_row(
    session: Session,
    *,
    index_entry_id: str,
    target_kind: str,
    target_id: str,
    text_view: str,
    text_view_name: str | None,
    container_ref: str | None,
) -> None:
    """Insert a single row into the lexical_fts FTS5 virtual table."""
    session.execute(
        text(
            "INSERT INTO lexical_fts"
            "(text_view, index_entry_id, target_kind, target_id, text_view_name, container_ref) "
            "VALUES (:text_view, :index_entry_id, :target_kind, :target_id, :text_view_name, :container_ref)"
        ),
        {
            "text_view": text_view,
            "index_entry_id": index_entry_id,
            "target_kind": target_kind,
            "target_id": target_id,
            "text_view_name": text_view_name,
            "container_ref": container_ref,
        },
    )
