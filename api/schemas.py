from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.visibility import Visibility


ArtifactKind = Literal["message", "assistant_output", "tool_use_summary", "todo_snapshot", "notification"]
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


class InjectableBlockResponse(BaseModel):
    result_id: str
    block_type: str
    title: str
    text: str
    memory_type: str | None = None
    memory_object_id: str | None = None
    evidence: list[EvidenceResponse] = Field(default_factory=list)


class QueryResponse(BaseModel):
    results: list[QueryResultResponse]
    should_inject: bool
    decision_reason: str
    injectable_blocks: list[InjectableBlockResponse] = Field(default_factory=list)


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


class MemoryEvidenceResponse(BaseModel):
    memory_object_id: str
    items: list[MemoryEvidenceItemResponse]


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
    trace: QueryTraceResponse


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


class ItemAndQueryDebugResponse(BaseModel):
    source_item_id: str
    results: list[QueryResultResponse]
    should_inject: bool
    decision_reason: str
    injectable_blocks: list[InjectableBlockResponse] = Field(default_factory=list)
    trace: QueryTraceResponse


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
