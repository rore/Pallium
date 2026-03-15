from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ArtifactKind = Literal["message", "assistant_output", "tool_use_summary", "todo_snapshot", "notification"]
VisibilityKind = Literal["public", "limited", "user"]
ProcessingStatus = Literal["pending", "processing", "completed", "skipped", "failed"]


class VisibilityContextModel(BaseModel):
    kind: VisibilityKind
    id: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "VisibilityContextModel":
        if self.kind == "public":
            if self.id is not None:
                raise ValueError("public visibility_context must use id=null")
            return self
        if not self.id:
            raise ValueError(f"{self.kind} visibility_context requires a non-empty id")
        return self


class ItemCreateRequest(BaseModel):
    source_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None
    use_case: str | None = None
    occurred_at: datetime | None = None
    actor_ref: str | None = None
    role: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    session_ref: str | None = None
    source_ref: str | None = None
    artifact_kind: ArtifactKind | None = None
    visibility_context: VisibilityContextModel | None = None


class ItemCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_item_id: str
    annotation_ids: list[str]
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
    annotation_ids: list[str]
    memory_object_ids: list[str]
    relation_ids: list[str]
    index_entry_ids: list[str]
    failure_category: str | None = None
    annotation_count: int = 0
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
    session_ref: str | None = None
    visibility_context: VisibilityContextModel | None = None


class EvidenceResponse(BaseModel):
    source_item_id: str
    source_type: str
    source_id: str
    occurred_at: datetime | None = None
    actor_ref: str | None = None
    role: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    session_ref: str | None = None
    source_ref: str | None = None
    artifact_kind: ArtifactKind | None = None
    visibility_context: VisibilityContextModel | None = None


class QueryResultResponse(BaseModel):
    result_kind: str
    score: int
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
    role: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    session_ref: str | None = None
    source_ref: str | None = None
    artifact_kind: ArtifactKind | None = None
    visibility_context: VisibilityContextModel | None = None


class QueryResponse(BaseModel):
    results: list[QueryResultResponse]


class QueryTraceFiltersResponse(BaseModel):
    source_type: str | None = None
    role: str | None = None
    artifact_kind: ArtifactKind | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    session_ref: str | None = None


class RetrievalTraceHitResponse(BaseModel):
    target_kind: str
    target_id: str
    index_entry_id: str
    index_type: str
    text_view_name: str
    score: int
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
    query_visibility_context: VisibilityContextModel | None = None
    expanded_visibility_contexts: list[VisibilityContextModel] = Field(default_factory=list)
    excluded_candidates: list[QueryTraceVisibilityExclusionResponse] = Field(default_factory=list)
    fail_closed_reason: str | None = None


class QueryTraceResponse(BaseModel):
    query_text: str
    query_tokens: list[str]
    limit: int
    filters: QueryTraceFiltersResponse | None = None
    stages: list[RetrievalStageTraceResponse]
    routing: dict[str, Any] | None = None
    visibility: QueryTraceVisibilityResponse | None = None
    result_summary: dict[str, Any] | None = None


class QueryDebugResponse(BaseModel):
    results: list[QueryResultResponse]
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
    thread_ref: str
    visibility_context: VisibilityContextModel | None = None
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


class QueueHealthResponse(BaseModel):
    status_counts: dict[str, int]
    oldest_pending_age_seconds: int | None = None
    pending_without_use_case_count: int
    unclaimable_pending_counts: list[QueueHealthReasonCountResponse] = Field(default_factory=list)
    leased_source_items: list[LeasedSourceItemResponse] = Field(default_factory=list)
    leased_thread_scopes: list[LeasedThreadScopeResponse] = Field(default_factory=list)
    recent_failures: list[RecentFailureResponse] = Field(default_factory=list)
