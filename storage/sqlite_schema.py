from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint, text
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
    thread_position = Column(Integer, nullable=True)
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
    # W3 explicit memory-write columns (see docs/specs/2026-07-01-milestone-shaped-memory-contract.md §W3).
    # `origin` distinguishes agent-explicit writes from automatic extraction and
    # from user-requested notes. Defaults to 'agent_inferred' so all pre-W3 rows
    # are tagged correctly by the migration, and so fresh-DB rows inserted
    # without an explicit origin also classify correctly. Server-side default
    # matches the ALTER TABLE ADD COLUMN default in _MEMORY_OBJECT_MIGRATIONS.
    origin = Column(String, nullable=True, server_default="agent_inferred")
    origin_session_id = Column(String, nullable=True)
    origin_agent_id = Column(String, nullable=True)
    # `correction_reason` is written when a memory is corrected, superseded, or
    # forgotten via the explicit tools. Provides audit context.
    correction_reason = Column(Text, nullable=True)
    # Explicit supersession chain — populated by pallium_supersede / pallium_correct.
    # If set, this memory has been superseded by the referenced memory_object id.
    # Lifecycle-column supersession already exists; this column adds the pointer
    # so the chain is walkable without a Relation lookup. Both paths coexist.
    superseded_by_id = Column(String, nullable=True)
    # Soft-delete tombstone. `is_soft_deleted=1` hides the row from default
    # retrieval; audit / retrospective queries can opt in. Server-side default
    # of 0 matches the ALTER TABLE default so fresh-DB rows are visible by default.
    is_soft_deleted = Column(Integer, nullable=False, default=0, server_default="0")
    soft_deleted_at = Column(DateTime(timezone=True), nullable=True)
    soft_delete_reason = Column(Text, nullable=True)
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
    thread_ref = Column(String, nullable=True)
    visibility = Column(String, nullable=True, default="private")
    requested_at = Column(DateTime(timezone=True), nullable=True)
    processing_claimed_by = Column(String, nullable=True)
    processing_claimed_at = Column(DateTime(timezone=True), nullable=True)
    processing_lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    processing_completed_at = Column(DateTime(timezone=True), nullable=True)
    collection_watermark_at = Column(DateTime(timezone=True), nullable=True)
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
    source_item_created_at = Column(DateTime(timezone=True), nullable=True)
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
    candidate_scores_json = Column(Text, nullable=True)
    injection_method = Column(String, nullable=True)
    query_workstream_id = Column(String, nullable=True)
    # Phase 4 (2026-06-27): opaque label identifying which deterministic
    # trigger fired this query. Validated server-side as an enum-like
    # token; values include "session_start_orientation",
    # "session_start_checkpoint", "post_tool_failure",
    # "retry_threshold", "user_explicit", "pre_compact", or NULL for
    # legacy / proactive queries. See
    # docs/specs/2026-06-27-injection-policy-abstention.md.
    trigger_origin = Column(String, nullable=True)


class MemoryFlagRecord(Base):
    __tablename__ = "memory_flags"

    id = Column(String, primary_key=True)
    memory_object_id = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    source_ref = Column(String, nullable=False)
    flagged_at = Column(DateTime(timezone=True), nullable=False)


class MemoryFeedbackRecord(Base):
    __tablename__ = "memory_feedback"

    id = Column(String, primary_key=True)
    memory_object_id = Column(String, nullable=False)  # no FK — survives deletion
    rating = Column(String, nullable=False)             # "relevant" | "not_relevant"
    reason = Column(Text, nullable=True)
    query_context = Column(Text, nullable=True)
    query_audit_log_id = Column(String, nullable=True)  # join to audit log for context
    rater_ref = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    memory_type = Column(String, nullable=True)
    memory_text = Column(Text, nullable=True)
    thread_ref = Column(String, nullable=True)
    container_ref = Column(String, nullable=True)


# Phase 5 (2026-06-27): per-injected-block usage telemetry.
# Distinct from memory_feedback — feedback is a *human rating* of whether
# a memory was on-topic; usage_audit is *did the agent actually use the
# memory in its next response* (an integration-side heuristic match).
# See docs/specs/2026-06-27-injection-policy-abstention.md.
class MemoryUsageAuditRecord(Base):
    __tablename__ = "memory_usage_audit"

    id = Column(String, primary_key=True)
    query_audit_log_id = Column(String, nullable=False)
    memory_object_id = Column(String, nullable=False)
    memory_type = Column(String, nullable=True)       # denorm for per-type rollups
    container_ref = Column(String, nullable=True)     # denorm
    thread_ref = Column(String, nullable=True)        # denorm
    # Denorm of query_audit_log.trigger_origin so the Phase 6 metric
    # "proactive-only useful-injection rate" can filter cheaply.
    trigger_origin = Column(String, nullable=True)
    # NULL = not yet populated; 0/1 once the populator hook resolves it.
    referenced_in_next_turn = Column(Integer, nullable=True)
    reference_kind = Column(String, nullable=True)    # id_quote | verbatim_snippet | entity_match | NULL
    observation_window_turns = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    populated_at = Column(DateTime(timezone=True), nullable=True)


class MetricRecord(Base):
    __tablename__ = "metrics"

    id = Column(String, primary_key=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    category = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    container_ref = Column(String, nullable=True)
    thread_ref = Column(String, nullable=True)
    actor_ref = Column(String, nullable=True)
    value = Column(Float, nullable=True)
    payload_json = Column(Text, nullable=True)


class WorkstreamRecord(Base):
    """Workstream registry — see docs/designs/014-workstream-consolidation-rekey.md."""

    __tablename__ = "workstreams"

    id = Column(String, primary_key=True)
    container_ref = Column(String, nullable=False)
    visibility = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    signature_blob = Column(Text, nullable=False)
    opened_at = Column(DateTime(timezone=True), nullable=False)
    last_touched_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_reason = Column(String, nullable=True)
    canonical_id = Column(String, nullable=True)
    created_by = Column(String, nullable=False, default="thread_rebuild")


class MemoryWorkstreamRecord(Base):
    __tablename__ = "memory_workstreams"

    memory_object_id = Column(String, primary_key=True)
    workstream_id = Column(String, primary_key=True)
    assigned_at = Column(DateTime(timezone=True), nullable=False)


class SourceItemWorkstreamRecord(Base):
    __tablename__ = "source_item_workstreams"

    source_item_id = Column(String, primary_key=True)
    workstream_id = Column(String, primary_key=True)
    watermark = Column(String, primary_key=True)
    assigned_at = Column(DateTime(timezone=True), nullable=False)
    # Cascade stage that produced this assignment (work_refs / file_path /
    # symbol / title / anchor / recency / open_new / self_ref_attach /
    # unknown). Nullable for legacy rows written before this column landed.
    # Diagnostic-only; nothing reads it for behavior decisions.
    stage = Column(String, nullable=True)


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
        "thread_position": "ALTER TABLE source_items ADD COLUMN thread_position INTEGER",
    }
    _MEMORY_OBJECT_MIGRATIONS = {
        "lifecycle": "ALTER TABLE memory_objects ADD COLUMN lifecycle VARCHAR DEFAULT 'active'",
        "visibility": "ALTER TABLE memory_objects ADD COLUMN visibility VARCHAR DEFAULT 'private'",
        "freshness_at": "ALTER TABLE memory_objects ADD COLUMN freshness_at DATETIME",
        "envelope_json": "ALTER TABLE memory_objects ADD COLUMN envelope_json TEXT",
        "container_ref": "ALTER TABLE memory_objects ADD COLUMN container_ref VARCHAR",
        "actor_ref": "ALTER TABLE memory_objects ADD COLUMN actor_ref VARCHAR",
        "subject": "ALTER TABLE memory_objects ADD COLUMN subject VARCHAR",
        # W3 explicit-write columns. All nullable / default-safe so pre-W3 rows
        # remain valid without a data backfill. `origin` defaults to
        # 'agent_inferred' so existing extraction writes classify correctly.
        "origin": "ALTER TABLE memory_objects ADD COLUMN origin VARCHAR DEFAULT 'agent_inferred'",
        "origin_session_id": "ALTER TABLE memory_objects ADD COLUMN origin_session_id VARCHAR",
        "origin_agent_id": "ALTER TABLE memory_objects ADD COLUMN origin_agent_id VARCHAR",
        "correction_reason": "ALTER TABLE memory_objects ADD COLUMN correction_reason TEXT",
        "superseded_by_id": "ALTER TABLE memory_objects ADD COLUMN superseded_by_id VARCHAR",
        "is_soft_deleted": "ALTER TABLE memory_objects ADD COLUMN is_soft_deleted INTEGER DEFAULT 0",
        "soft_deleted_at": "ALTER TABLE memory_objects ADD COLUMN soft_deleted_at DATETIME",
        "soft_delete_reason": "ALTER TABLE memory_objects ADD COLUMN soft_delete_reason TEXT",
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
    _PACKAGE_PROCESSING_MIGRATIONS = {
        "source_item_created_at": (
            "ALTER TABLE package_processing_status ADD COLUMN source_item_created_at DATETIME"
        ),
    }
    _THREAD_PROCESSING_LEASE_MIGRATIONS = {
        "collection_watermark_at": "ALTER TABLE thread_processing_leases ADD COLUMN collection_watermark_at DATETIME",
    }
    _SOURCE_ITEM_WORKSTREAM_MIGRATIONS = {
        "stage": "ALTER TABLE source_item_workstreams ADD COLUMN stage VARCHAR",
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
        # W3 explicit-write indexes. `origin` is queried by the dashboard to
        # distinguish explicit writes from inferred extraction. `superseded_by_id`
        # supports fast supersession-chain traversal without a Relation lookup.
        # `is_soft_deleted` partial index keeps default-retrieval queries cheap
        # (they filter on `is_soft_deleted = 0`, so we only index the small
        # tombstone set).
        "idx_memory_objects_origin": (
            "CREATE INDEX IF NOT EXISTS idx_memory_objects_origin "
            "ON memory_objects(origin, container_ref, created_at) "
            "WHERE origin IS NOT NULL"
        ),
        "idx_memory_objects_superseded_by": (
            "CREATE INDEX IF NOT EXISTS idx_memory_objects_superseded_by "
            "ON memory_objects(superseded_by_id) "
            "WHERE superseded_by_id IS NOT NULL"
        ),
        "idx_memory_objects_soft_deleted": (
            "CREATE INDEX IF NOT EXISTS idx_memory_objects_soft_deleted "
            "ON memory_objects(container_ref, created_at) "
            "WHERE is_soft_deleted = 1"
        ),
        "idx_source_items_thread_lookup": (
            "CREATE INDEX IF NOT EXISTS idx_source_items_thread_lookup "
            "ON source_items(container_ref, thread_ref, created_at, id)"
        ),
        "idx_source_items_thread_stats": (
            "CREATE INDEX IF NOT EXISTS idx_source_items_thread_stats "
            "ON source_items(thread_ref, created_at DESC, id)"
        ),
        "idx_source_items_claim_queue": (
            "CREATE INDEX IF NOT EXISTS idx_source_items_claim_queue "
            "ON source_items(processing_status, processing_next_attempt_at, processing_lease_expires_at, created_at, id) "
            "WHERE use_case IS NOT NULL"
        ),
        "idx_relations_to_target_lookup": (
            "CREATE INDEX IF NOT EXISTS idx_relations_to_target_lookup "
            "ON relations(to_kind, to_id, relation_type, from_kind, from_id)"
        ),
        "idx_relations_from_target_lookup": (
            "CREATE INDEX IF NOT EXISTS idx_relations_from_target_lookup "
            "ON relations(from_kind, from_id, relation_type, to_kind, to_id)"
        ),
        "idx_index_entries_target_lookup": (
            "CREATE INDEX IF NOT EXISTS idx_index_entries_target_lookup "
            "ON index_entries(target_kind, target_id, index_type, id)"
        ),
        "idx_index_entries_type_lookup": (
            "CREATE INDEX IF NOT EXISTS idx_index_entries_type_lookup "
            "ON index_entries(index_type, id)"
        ),
        "idx_thread_processing_leases_claim_lookup": (
            "CREATE INDEX IF NOT EXISTS idx_thread_processing_leases_claim_lookup "
            "ON thread_processing_leases(requested_at, processing_lease_expires_at, created_at, scope_key)"
        ),
        "idx_package_processing_claim_lookup": (
            "CREATE INDEX IF NOT EXISTS idx_package_processing_claim_lookup "
            "ON package_processing_status(status, source_item_created_at, source_item_id, package_name, next_attempt_at, lease_expires_at)"
        ),
        "idx_source_items_container_top_level": (
            "CREATE INDEX IF NOT EXISTS idx_source_items_container_top_level "
            "ON source_items(container_ref, thread_position, created_at)"
        ),
        "idx_metrics_cat_ts": (
            "CREATE INDEX IF NOT EXISTS idx_metrics_cat_ts "
            "ON metrics(category, timestamp)"
        ),
        "idx_metrics_cat_evt_ts": (
            "CREATE INDEX IF NOT EXISTS idx_metrics_cat_evt_ts "
            "ON metrics(category, event_type, timestamp)"
        ),
        "idx_metrics_container_ts": (
            "CREATE INDEX IF NOT EXISTS idx_metrics_container_ts "
            "ON metrics(container_ref, timestamp)"
        ),
        "idx_workstreams_container_visibility": (
            "CREATE INDEX IF NOT EXISTS idx_workstreams_container_visibility "
            "ON workstreams(container_ref, visibility)"
        ),
        "idx_workstreams_last_touched": (
            "CREATE INDEX IF NOT EXISTS idx_workstreams_last_touched "
            "ON workstreams(last_touched_at)"
        ),
        "idx_memory_workstreams_ws": (
            "CREATE INDEX IF NOT EXISTS idx_memory_workstreams_ws "
            "ON memory_workstreams(workstream_id)"
        ),
        "idx_memory_workstreams_mid": (
            "CREATE INDEX IF NOT EXISTS idx_memory_workstreams_mid "
            "ON memory_workstreams(memory_object_id)"
        ),
        "idx_source_item_workstreams_si": (
            "CREATE INDEX IF NOT EXISTS idx_source_item_workstreams_si "
            "ON source_item_workstreams(source_item_id)"
        ),
        "idx_source_item_workstreams_ws": (
            "CREATE INDEX IF NOT EXISTS idx_source_item_workstreams_ws "
            "ON source_item_workstreams(workstream_id)"
        ),
        "idx_source_item_workstreams_wm": (
            "CREATE INDEX IF NOT EXISTS idx_source_item_workstreams_wm "
            "ON source_item_workstreams(watermark)"
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
    _MEMORY_FLAG_INDEX_MIGRATIONS = {
        "idx_memory_flags_memory_id": (
            "CREATE INDEX IF NOT EXISTS idx_memory_flags_memory_id "
            "ON memory_flags(memory_object_id)"
        ),
    }
    _MEMORY_FEEDBACK_INDEX_MIGRATIONS = {
        "idx_memory_feedback_memory_object_id": (
            "CREATE INDEX IF NOT EXISTS idx_memory_feedback_memory_object_id "
            "ON memory_feedback (memory_object_id)"
        ),
        "idx_memory_feedback_created_at": (
            "CREATE INDEX IF NOT EXISTS idx_memory_feedback_created_at "
            "ON memory_feedback (created_at)"
        ),
    }
    # Phase 5: memory_usage_audit indexes.
    _MEMORY_USAGE_AUDIT_INDEX_MIGRATIONS = {
        "idx_memory_usage_audit_query_audit_log_id": (
            "CREATE INDEX IF NOT EXISTS idx_memory_usage_audit_query_audit_log_id "
            "ON memory_usage_audit (query_audit_log_id)"
        ),
        "idx_memory_usage_audit_memory_object_id": (
            "CREATE INDEX IF NOT EXISTS idx_memory_usage_audit_memory_object_id "
            "ON memory_usage_audit (memory_object_id, created_at DESC)"
        ),
        "idx_memory_usage_audit_type_trigger": (
            "CREATE INDEX IF NOT EXISTS idx_memory_usage_audit_type_trigger "
            "ON memory_usage_audit (memory_type, trigger_origin, created_at)"
        ),
        "idx_memory_usage_audit_container": (
            "CREATE INDEX IF NOT EXISTS idx_memory_usage_audit_container "
            "ON memory_usage_audit (container_ref, created_at)"
        ),
        "idx_memory_usage_audit_pending": (
            "CREATE INDEX IF NOT EXISTS idx_memory_usage_audit_pending "
            "ON memory_usage_audit (populated_at) "
            "WHERE populated_at IS NULL"
        ),
    }
    _MEMORY_FEEDBACK_COLUMN_MIGRATIONS = {
        "memory_type": "ALTER TABLE memory_feedback ADD COLUMN memory_type VARCHAR",
        "memory_text": "ALTER TABLE memory_feedback ADD COLUMN memory_text TEXT",
        "thread_ref": "ALTER TABLE memory_feedback ADD COLUMN thread_ref VARCHAR",
        "container_ref": "ALTER TABLE memory_feedback ADD COLUMN container_ref VARCHAR",
    }
    _QUERY_AUDIT_LOG_MIGRATIONS = {
        "candidate_scores_json": "ALTER TABLE query_audit_log ADD COLUMN candidate_scores_json TEXT",
        "injection_method": "ALTER TABLE query_audit_log ADD COLUMN injection_method VARCHAR",
        "query_workstream_id": "ALTER TABLE query_audit_log ADD COLUMN query_workstream_id VARCHAR",
        "trigger_origin": "ALTER TABLE query_audit_log ADD COLUMN trigger_origin VARCHAR",
    }

    def _initialize_schema(self) -> None:
        with self._schema_initialization_lock():
            Base.metadata.create_all(self._engine)
            self._ensure_thread_processing_lease_nullable_thread_ref()
            self._ensure_thread_processing_lease_columns()
            self._ensure_source_item_columns()
            self._ensure_source_item_workstream_columns()
            self._ensure_memory_object_columns()
            self._ensure_index_entry_columns()
            self._ensure_maintenance_state_columns()
            self._ensure_package_processing_columns()
            self._ensure_unique_indexes()
            self._ensure_indexes()
            self._ensure_query_audit_log_indexes()
            self._ensure_query_audit_log_columns()
            self._ensure_memory_flag_indexes()
            self._ensure_memory_feedback_columns()
            self._ensure_memory_feedback_indexes()
            # Phase 5: memory_usage_audit indexes (table is created
            # declaratively by Base.metadata.create_all above).
            self._ensure_memory_usage_audit_indexes()
            self._ensure_fts5_table()
            self._backfill_legacy_memory_freshness()
            self._backfill_thread_position()

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

    def _ensure_thread_processing_lease_nullable_thread_ref(self) -> None:
        """Migrate thread_processing_leases.thread_ref from NOT NULL to nullable."""
        with self._engine.begin() as connection:
            columns = connection.execute(text("PRAGMA table_info(thread_processing_leases)")).fetchall()
            thread_ref_col = next((col for col in columns if col[1] == "thread_ref"), None)
            if thread_ref_col is None:
                return
            notnull = thread_ref_col[3]
            if not notnull:
                return
            connection.execute(text(
                "CREATE TABLE thread_processing_leases_new ("
                "  scope_key VARCHAR PRIMARY KEY,"
                "  use_case VARCHAR NOT NULL,"
                "  container_ref VARCHAR NOT NULL,"
                "  thread_ref VARCHAR,"
                "  visibility VARCHAR DEFAULT 'private',"
                "  requested_at DATETIME,"
                "  processing_claimed_by VARCHAR,"
                "  processing_claimed_at DATETIME,"
                "  processing_lease_expires_at DATETIME,"
                "  processing_completed_at DATETIME,"
                "  collection_watermark_at DATETIME,"
                "  created_at DATETIME NOT NULL,"
                "  updated_at DATETIME NOT NULL"
                ")"
            ))
            connection.execute(text(
                "INSERT INTO thread_processing_leases_new "
                "(scope_key, use_case, container_ref, thread_ref, visibility, "
                " requested_at, processing_claimed_by, processing_claimed_at, "
                " processing_lease_expires_at, processing_completed_at, "
                " created_at, updated_at) "
                "SELECT scope_key, use_case, container_ref, thread_ref, visibility, "
                "  requested_at, processing_claimed_by, processing_claimed_at, "
                "  processing_lease_expires_at, processing_completed_at, "
                "  created_at, updated_at "
                "FROM thread_processing_leases"
            ))
            connection.execute(text("DROP TABLE thread_processing_leases"))
            connection.execute(text(
                "ALTER TABLE thread_processing_leases_new RENAME TO thread_processing_leases"
            ))

    def _ensure_thread_processing_lease_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(thread_processing_leases)"))}
            for column_name, migration_sql in self._THREAD_PROCESSING_LEASE_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

    def _ensure_source_item_workstream_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(source_item_workstreams)"))}
            for column_name, migration_sql in self._SOURCE_ITEM_WORKSTREAM_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

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

    def _ensure_package_processing_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(package_processing_status)"))
            }
            for column_name, migration_sql in self._PACKAGE_PROCESSING_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))
            connection.execute(
                text(
                    "UPDATE package_processing_status "
                    "SET source_item_created_at = ("
                    "  SELECT created_at FROM source_items WHERE source_items.id = package_processing_status.source_item_id"
                    ") "
                    "WHERE source_item_created_at IS NULL"
                )
            )

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

    def _ensure_query_audit_log_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(query_audit_log)"))}
            for column_name, migration_sql in self._QUERY_AUDIT_LOG_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

    def _ensure_memory_flag_indexes(self) -> None:
        with self._engine.begin() as connection:
            for _index_name, create_sql in self._MEMORY_FLAG_INDEX_MIGRATIONS.items():
                connection.execute(text(create_sql))

    def _ensure_memory_feedback_columns(self) -> None:
        with self._engine.begin() as connection:
            existing_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(memory_feedback)"))}
            for column_name, migration_sql in self._MEMORY_FEEDBACK_COLUMN_MIGRATIONS.items():
                if column_name not in existing_columns:
                    connection.execute(text(migration_sql))

    def _ensure_memory_feedback_indexes(self) -> None:
        with self._engine.begin() as connection:
            for _index_name, create_sql in self._MEMORY_FEEDBACK_INDEX_MIGRATIONS.items():
                connection.execute(text(create_sql))

    def _ensure_memory_usage_audit_indexes(self) -> None:
        with self._engine.begin() as connection:
            for _index_name, create_sql in self._MEMORY_USAGE_AUDIT_INDEX_MIGRATIONS.items():
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

    def _backfill_thread_position(self) -> None:
        """Set thread_position for existing source items that don't have it."""
        with self._engine.begin() as connection:
            needs_backfill = connection.execute(text(
                "SELECT COUNT(*) FROM source_items WHERE thread_position IS NULL LIMIT 1"
            )).scalar()
            if not needs_backfill:
                return
            connection.execute(text(
                "UPDATE source_items SET thread_position = ("
                "  SELECT COUNT(*) FROM source_items s2"
                "  WHERE s2.container_ref = source_items.container_ref"
                "    AND s2.thread_ref = source_items.thread_ref"
                "    AND (s2.created_at < source_items.created_at"
                "         OR (s2.created_at = source_items.created_at AND s2.id <= source_items.id))"
                ") WHERE thread_ref IS NOT NULL AND thread_position IS NULL"
            ))
            connection.execute(text(
                "UPDATE source_items SET thread_position = 1 "
                "WHERE thread_ref IS NULL AND thread_position IS NULL"
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
