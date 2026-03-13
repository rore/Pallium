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


class QueryDebugResponse(BaseModel):
    results: list[QueryResultResponse]
    trace: QueryTraceResponse
