from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.visibility import Visibility


ArtifactKind = Literal["message", "assistant_output", "tool_use_summary", "todo_snapshot", "notification", "note"]
ProcessingStatus = Literal["pending", "processing", "completed", "skipped", "failed"]
TurnKind = Literal["new_thread", "same_thread", "same_thread_continuation", "resumed_session", "new_session"]


class VisibilityContextModel(BaseModel):
    kind: Visibility
    id: str | None = None

    @model_validator(mode="after")
    def normalize_scope_id(self) -> VisibilityContextModel:
        if self.kind != "container":
            self.id = None
        return self


class RuntimeContextModel(BaseModel):
    turn_kind: TurnKind | None = None
    session_has_sufficient_local_context: bool | None = None
    evidence_request: bool | None = None


class ItemCreateRequest(BaseModel):
    source_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None
    use_case: str | None = None
    occurred_at: datetime | None = None
    actor_ref: str | None = None
    agent_ref: str | None = None
    role: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    source_ref: str | None = None
    artifact_kind: ArtifactKind | None = None
    visibility: Visibility | VisibilityContextModel | None = None

    def visibility_kind(self) -> str | None:
        if isinstance(self.visibility, VisibilityContextModel):
            return self.visibility.kind
        return self.visibility


class ItemCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_item_id: str
    memory_object_ids: list[str]
    relation_ids: list[str]
    index_entry_ids: list[str]
    processing_status: ProcessingStatus
    processing_attempts: int
    processing_error: str | None = None


class MemoryProvenanceResponse(BaseModel):
    memory_object_id: str
    memory_kind: str
    source_item_ids: list[str] = Field(default_factory=list)
    superseded_memory_ids: list[str] = Field(default_factory=list)


class ProcessingStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_item_id: str
    use_case: str | None = None
    processing_status: ProcessingStatus
    processing_attempts: int
    processing_claimed_at: datetime | None = None
    processing_completed_at: datetime | None = None
    processing_error: str | None = None
    memory_object_ids: list[str]
    relation_ids: list[str]
    index_entry_ids: list[str]
    failure_category: str | None = None
    memory_object_types: list[str] = Field(default_factory=list)
    thread_rebuild_requested: bool = False
    thread_rebuild_completed: bool = False
    produced_memory_provenance: list[MemoryProvenanceResponse] = Field(default_factory=list)


class QueryRequest(BaseModel):
    text: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=50)
    source_type: str | None = None
    role: str | None = None
    artifact_kind: ArtifactKind | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    actor_ref: str | None = None
    work_refs: list[str] | None = None
    visibility: Visibility | VisibilityContextModel | None = None
    runtime_context: RuntimeContextModel | None = None
    # Phase 4 (2026-06-27): opaque label identifying which deterministic
    # trigger fired this query. Validated server-side against a known
    # token set; None means "legacy / proactive default." See
    # docs/specs/2026-06-27-injection-policy-abstention.md.
    trigger_origin: str | None = None
    # Source-only history search (vNext P1): when true, rank raw source turns
    # (source_hit) on their own — memory objects never occupy result slots —
    # and skip the memory injection/abstention path (should_inject=False,
    # empty injectable_blocks). Default false = normal proactive query.
    source_only: bool = False

    def visibility_kind(self) -> str | None:
        if isinstance(self.visibility, VisibilityContextModel):
            return self.visibility.kind
        return self.visibility


class EvidenceResponse(BaseModel):
    source_item_id: str
    source_type: str
    source_id: str
    occurred_at: datetime | None = None
    actor_ref: str | None = None
    agent_ref: str | None = None
    role: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    source_ref: str | None = None
    artifact_kind: ArtifactKind | None = None
    visibility: str = "private"


class QueryResultResponse(BaseModel):
    result_id: str | None = None
    result_kind: str
    score: float
    evidence: list[EvidenceResponse]
    memory_object_id: str | None = None
    type: str | None = None
    payload: dict[str, Any] | None = None
    source_item_id: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    excerpt: str | None = None
    occurred_at: datetime | None = None
    actor_ref: str | None = None
    agent_ref: str | None = None
    role: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    source_ref: str | None = None
    artifact_kind: ArtifactKind | None = None
    visibility: str = "private"
    retrieval_source: str | None = None
    # Source-only search: 1-based rank within the source-only page; None otherwise.
    raw_rank: int | None = None


class InjectableBlockResponse(BaseModel):
    result_id: str
    block_type: str
    title: str
    text: str
    memory_type: str | None = None
    memory_object_id: str | None = None
    expand_available: bool = False
    evidence: list[EvidenceResponse] = Field(default_factory=list)


class QueryResponse(BaseModel):
    results: list[QueryResultResponse]
    should_inject: bool
    decision_reason: str
    injectable_blocks: list[InjectableBlockResponse] = Field(default_factory=list)
    # vNext P0 (design 015): stable id for this lookup, linking the call to
    # its recorded exposures and follow-up in the measurement event chain.
    # Equals the persisted query_audit_log row id when a row was written for
    # this call; None otherwise (e.g. query-audit logging disabled, or an
    # endpoint that does not persist a row). Additive and non-breaking.
    lookup_event_id: str | None = None


class MemoryEvidenceItemResponse(BaseModel):
    source_item_id: str
    source_type: str
    source_id: str
    content: str
    role: str | None = None
    actor_ref: str | None = None
    occurred_at: datetime | None = None
    thread_ref: str | None = None
    artifact_kind: ArtifactKind | None = None


class MemoryExpandResponse(BaseModel):
    memory_object_id: str
    payload: dict | None = None
    items: list[MemoryEvidenceItemResponse]
    # Phase 5b (2026-06-28): per-type text view the usage-audit populator
    # should compare against the assistant's response. Uses the same per-
    # type field map as the embedding text view (single source of truth for
    # "what counts as memory content"). None when the memory type has no
    # per-type text view or no fields are populated.
    match_text: str | None = None


class QueryTraceFiltersResponse(BaseModel):
    source_type: str | None = None
    role: str | None = None
    artifact_kind: ArtifactKind | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    actor_ref: str | None = None
    work_refs: list[str] = Field(default_factory=list)


class RetrievalTraceHitResponse(BaseModel):
    target_kind: str
    target_id: str
    index_entry_id: str
    index_type: str
    text_view_name: str
    score: float
    matched_tokens: list[str]
    provider_name: str | None = None
    provider_version: str | None = None


class RetrievalStageTraceResponse(BaseModel):
    stage_name: str
    candidate_hits_considered: int
    candidate_hits: list[RetrievalTraceHitResponse]
    selected_hits: list[RetrievalTraceHitResponse]
    candidate_hits_before_visibility: int | None = None
    candidate_hits_after_visibility: int | None = None


class QueryTraceVisibilityExclusionResponse(BaseModel):
    reason: str
    count: int


class QueryTraceVisibilityResponse(BaseModel):
    query_visibility: str | None = None
    query_container_ref: str | None = None
    excluded_candidates: list[QueryTraceVisibilityExclusionResponse] = Field(default_factory=list)
    fail_closed_reason: str | None = None


class FusionTraceHitResponse(BaseModel):
    result_id: str
    rrf_score: float
    rrf_rank: int
    fused_score: int
    lexical_rank: int | None = None
    vector_rank: int | None = None
    retrieval_source: str


class FusionStageTraceResponse(BaseModel):
    stage_name: str
    k: int
    rrf_score_scale: int
    lexical_candidate_count: int
    vector_candidate_count: int
    fused_candidate_count: int
    both_sources_count: int
    selected_count: int
    lexical_weight: float = 1.0
    vector_weight: float = 1.0
    hits: list[FusionTraceHitResponse]


class QueryTraceResponse(BaseModel):
    query_text: str
    query_tokens: list[str]
    limit: int
    filters: QueryTraceFiltersResponse | None = None
    requested_filters: QueryTraceFiltersResponse | None = None
    filter_scope_relaxed: bool = False
    filter_scope_reason: str | None = None
    stages: list[RetrievalStageTraceResponse]
    routing: dict[str, Any] | None = None
    visibility: QueryTraceVisibilityResponse | None = None
    result_summary: dict[str, Any] | None = None
    fusion_trace: FusionStageTraceResponse | None = None


class QueryDebugResponse(QueryResponse):
    # vNext P0 (design 015): /query/debug does not persist an audit row, so the
    # inherited `lookup_event_id` is always None here.
    trace: QueryTraceResponse
    # Phase 4A (design 014): workstream id of the query item, if assigned.
    # Per-candidate workstream ids are surfaced via the audit log; this field
    # is the row-level diagnostic equivalent for /query/debug.
    query_workstream_id: str | None = None
    # Per-candidate workstream ids, keyed by memory_object_id. Populated on a
    # best-effort basis from the ``memory_workstreams`` table.
    candidate_workstream_ids: dict[str, str] = Field(default_factory=dict)


class ItemAndQueryRequest(BaseModel):
    source_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None
    use_case: str | None = None
    occurred_at: datetime | None = None
    actor_ref: str | None = None
    agent_ref: str | None = None
    role: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    source_ref: str | None = None
    artifact_kind: ArtifactKind | None = None
    visibility: Visibility | VisibilityContextModel | None = None
    query_text: str | None = None
    query_limit: int = Field(default=5, ge=1, le=50)
    query_actor_ref: str | None = None
    work_refs: list[str] | None = None
    runtime_context: RuntimeContextModel | None = None
    # Phase 4 (2026-06-27): opaque trigger label for the query side of
    # the combined ingest-and-query call. Same semantics as
    # QueryRequest.trigger_origin.
    query_trigger_origin: str | None = None

    def visibility_kind(self) -> str | None:
        if isinstance(self.visibility, VisibilityContextModel):
            return self.visibility.kind
        return self.visibility


class ItemAndQueryResponse(BaseModel):
    source_item_id: str
    results: list[QueryResultResponse]
    should_inject: bool
    decision_reason: str
    injectable_blocks: list[InjectableBlockResponse] = Field(default_factory=list)
    # vNext P0 (design 015): see QueryResponse.lookup_event_id.
    lookup_event_id: str | None = None


class ItemAndQueryDebugResponse(BaseModel):
    source_item_id: str
    results: list[QueryResultResponse]
    should_inject: bool
    decision_reason: str
    injectable_blocks: list[InjectableBlockResponse] = Field(default_factory=list)
    trace: QueryTraceResponse
    # vNext P0 (design 015): see QueryResponse.lookup_event_id. This endpoint
    # persists an audit row when query-audit logging is enabled, so the id is
    # non-null in that case (None otherwise).
    lookup_event_id: str | None = None


class QueueHealthReasonCountResponse(BaseModel):
    reason: str
    count: int


class LeasedSourceItemResponse(BaseModel):
    source_item_id: str
    use_case: str | None = None
    processing_claimed_by: str | None = None
    processing_claimed_at: datetime | None = None
    processing_lease_expires_at: datetime | None = None


class LeasedThreadScopeResponse(BaseModel):
    scope_key: str
    use_case: str
    container_ref: str
    thread_ref: str | None = None
    visibility: str = "private"
    processing_claimed_by: str | None = None
    processing_claimed_at: datetime | None = None
    processing_lease_expires_at: datetime | None = None


class RecentFailureResponse(BaseModel):
    source_item_id: str
    use_case: str | None = None
    failure_category: str | None = None
    processing_error: str | None = None
    processing_attempts: int
    processing_completed_at: datetime | None = None


class RetentionHealthResponse(BaseModel):
    enabled: bool
    last_run_started_at: datetime | None = None
    last_run_completed_at: datetime | None = None
    last_deleted_source_items: int = 0
    last_deleted_memory_objects: int = 0
    last_deleted_relations: int = 0
    last_deleted_index_entries: int = 0
    last_stripped_debug_metadata: int = 0
    last_skipped_protected_source_items: int = 0


class QueueHealthResponse(BaseModel):
    status_counts: dict[str, int]
    status_counts_24h: dict[str, int] = Field(default_factory=dict)
    oldest_pending_age_seconds: int | None = None
    pending_without_use_case_count: int
    unclaimable_pending_counts: list[QueueHealthReasonCountResponse] = Field(default_factory=list)
    leased_source_items: list[LeasedSourceItemResponse] = Field(default_factory=list)
    leased_thread_scopes: list[LeasedThreadScopeResponse] = Field(default_factory=list)
    recent_failures: list[RecentFailureResponse] = Field(default_factory=list)
    retention: RetentionHealthResponse


class FlagMemoryRequest(BaseModel):
    reason: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    immediate: bool = False


class FlagMemoryResponse(BaseModel):
    memory_object_id: str
    flag_count: int
    unique_sources: int
    suppressed: bool


class MemoryFeedbackRequest(BaseModel):
    rating: Literal["relevant", "not_relevant"]
    reason: str | None = None
    query_context: str | None = None
    query_audit_log_id: str | None = None
    rater_ref: str | None = None
    thread_ref: str | None = None
    container_ref: str | None = None


class MemoryFeedbackResponse(BaseModel):
    memory_object_id: str
    rating: str
    recorded: bool


# Phase 5 (2026-06-27): per-injected-block usage telemetry.
# See docs/specs/2026-06-27-injection-policy-abstention.md.

class MemoryUsageAuditRowResponse(BaseModel):
    id: str
    query_audit_log_id: str
    memory_object_id: str
    memory_type: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    trigger_origin: str | None = None
    referenced_in_next_turn: bool | None = None
    reference_kind: str | None = None
    observation_window_turns: int | None = None
    created_at: datetime | None = None
    populated_at: datetime | None = None


class MemoryUsageAuditListResponse(BaseModel):
    rows: list[MemoryUsageAuditRowResponse]


_REFERENCE_KIND_VALUES: tuple[str, ...] = (
    "id_quote",
    "verbatim_snippet",
    "entity_match",
)


class MemoryUsageAuditUpdateRequest(BaseModel):
    referenced_in_next_turn: bool
    # reference_kind is required when referenced_in_next_turn is True;
    # validated server-side. When False (no reference), kind is None.
    reference_kind: str | None = None
    observation_window_turns: int | None = None


class MemoryUsageAuditUpdateResponse(BaseModel):
    audit_row_id: str
    updated: bool   # False if already populated (no-op) or row not found


# ── W3 explicit memory-write tools ─────────────────────────────────
# See docs/specs/2026-07-01-milestone-shaped-memory-contract.md §W3.
# These schemas back the pallium_remember / pallium_correct /
# pallium_supersede / pallium_forget / pallium_record_outcome MCP tools.
# Validation happens here at the API boundary (Invariant 1 discipline).

# Enum of memory origins recorded by the explicit-write path.
_ORIGIN_LITERALS = Literal["agent_explicit", "agent_inferred", "user_requested"]

# Bounded text lengths to prevent unbounded prompt-injection / storage bloat.
_MAX_MEMORY_TEXT_CHARS = 10_000
_MAX_REASON_CHARS = 500


class RememberMemoryRequest(BaseModel):
    """pallium_remember(text, type, ...): durable fact write.

    `type` names a registered memory type (decision, investigation_outcome,
    constraint_memory, operational_fact, etc). The service validates the
    type is registered before writing.

    `confidence` is stored for audit only. Invariant 1: it is NEVER used
    for retrieval ranking. Values >1.0 are rejected as they suggest the
    caller misunderstands the field.
    """
    text: str = Field(min_length=1, max_length=_MAX_MEMORY_TEXT_CHARS)
    type: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[str] | None = Field(default=None, max_length=5)
    container_ref: str | None = None
    actor_ref: str | None = None
    thread_ref: str | None = None
    origin_session_id: str | None = None
    origin_agent_id: str | None = None


class RememberMemoryResponse(BaseModel):
    memory_object_id: str
    origin: _ORIGIN_LITERALS
    created_at: datetime


class CorrectMemoryRequest(BaseModel):
    """pallium_correct: in-place fix of a wrong memory.

    Use when the memory is partially wrong (extraction was incomplete or
    mislabeled). For fully-obsolete memories, use pallium_supersede
    instead — that keeps the old memory in the audit chain and creates a
    new one.
    """
    corrected_text: str = Field(min_length=1, max_length=_MAX_MEMORY_TEXT_CHARS)
    reason: str = Field(
        min_length=1,
        max_length=_MAX_REASON_CHARS,
        description="Why the correction is needed. Include a note about the prior evidence.",
    )


class CorrectMemoryResponse(BaseModel):
    memory_object_id: str
    corrected: bool  # True on success; false if the memory is not active


class SupersedeMemoryRequest(BaseModel):
    """pallium_supersede: explicit supersession — new memory replaces old.

    Both memories persist. The old one is marked lifecycle='superseded'
    and gets a pointer to the new one via superseded_by_id. Retrieval
    hides superseded rows by default; retrospective queries opt in.
    """
    new_text: str = Field(min_length=1, max_length=_MAX_MEMORY_TEXT_CHARS)
    supersedes_id: str = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=_MAX_REASON_CHARS)
    # The new memory takes the old memory's type/container by default; overrides here.
    type: str | None = None
    container_ref: str | None = None
    actor_ref: str | None = None
    thread_ref: str | None = None
    origin_session_id: str | None = None
    origin_agent_id: str | None = None


class SupersedeMemoryResponse(BaseModel):
    old_memory_object_id: str
    new_memory_object_id: str
    superseded: bool  # True on success; false only if a concurrent supersession lost


class ForgetMemoryRequest(BaseModel):
    """pallium_forget: soft-delete with tombstone.

    The memory row remains in the database for audit. It's marked
    is_soft_deleted=1 and excluded from default retrieval. Retrospective
    audit queries can still surface it.

    Idempotent: forgetting an already-forgotten memory returns
    forgotten=False without modifying anything.
    """
    reason: str = Field(min_length=1, max_length=_MAX_REASON_CHARS)


class ForgetMemoryResponse(BaseModel):
    memory_object_id: str
    forgotten: bool  # False on second call (idempotent)


class ForgetSourceRequest(BaseModel):
    """User-requested forgetting of raw source turns (soft + auditable).

    Distinct from ForgetMemoryRequest (memory objects) and from the TTL
    retention hard-delete. Supply EITHER ``source_item_id`` (forget one turn)
    OR ``container_ref`` (optional ``thread_ref``) for a point-in-time bulk
    forget of that bounded scope. The row + index entries persist; the turn is
    excluded from query ``source_hit``s and expansion. ``actor_ref`` records
    the "who" for audit.

    Idempotent per item: re-forgetting an already-forgotten turn does not
    modify it.
    """
    source_item_id: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    reason: str = Field(min_length=1, max_length=_MAX_REASON_CHARS)
    actor_ref: str | None = None


class ForgetSourceResponse(BaseModel):
    count: int  # number of turns newly forgotten (0 if already forgotten)
    source_item_id: str | None = None
    forgotten: bool | None = None  # single-item mode only; False if idempotent no-op
    container_ref: str | None = None
    thread_ref: str | None = None


class RecordOutcomeRequest(BaseModel):
    """pallium_record_outcome: link outcome to a procedure / operational memory.

    Feeds W4 operational-fact memory success/failure counters. Stored
    for audit; NOT used to update retrieval ranking until W4 integration
    testing verifies the contract end-to-end.
    """
    procedure_id: str = Field(min_length=1)
    outcome: Literal["success", "failure", "inconclusive"]
    evidence: list[str] | None = Field(default=None, max_length=5)
    note: str | None = Field(default=None, max_length=_MAX_REASON_CHARS)


class RecordOutcomeResponse(BaseModel):
    procedure_id: str
    outcome: Literal["success", "failure", "inconclusive"]
    recorded: bool
