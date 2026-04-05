from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from core.visibility import QueryVisibilityTrace


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


def build_result_id(
    *,
    result_kind: str,
    memory_object_id: str | None = None,
    source_item_id: str | None = None,
) -> str | None:
    if result_kind == "memory_hit" and memory_object_id:
        return f"memory_object:{memory_object_id}"
    if result_kind == "source_hit" and source_item_id:
        return f"source_item:{source_item_id}"
    return None


@dataclass(frozen=True)
class SourceItem:
    source_type: str
    source_id: str
    content_type: str
    content: str
    metadata: dict[str, Any] | None = None
    occurred_at: datetime | None = None
    actor_ref: str | None = None
    agent_ref: str | None = None
    role: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    source_ref: str | None = None
    artifact_kind: str | None = None
    visibility: str = "private"
    use_case: str | None = None
    processing_status: str = "pending"
    processing_attempts: int = 0
    processing_claimed_by: str | None = None
    processing_claimed_at: datetime | None = None
    processing_lease_expires_at: datetime | None = None
    processing_completed_at: datetime | None = None
    processing_error: str | None = None
    processing_next_attempt_at: datetime | None = None
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)


MemoryEnvelopeKind = Literal["constraint", "finding", "episode", "next_step", "summary", "unknown"]
MemorySubjectAnchorKind = Literal["workstream", "component", "surface"]
MemoryEnvelopeConfidence = Literal["high", "medium", "low", "unknown"]
MemoryEnvelopeProducerKind = Literal["item_extraction", "thread_aggregation", "consolidation"]


@dataclass(frozen=True)
class MemorySubjectAnchor:
    kind: MemorySubjectAnchorKind
    value: str


@dataclass(frozen=True)
class MemoryEnvelopeScope:
    container_ref: str | None = None
    thread_ref: str | None = None


@dataclass(frozen=True)
class MemoryEnvelopeDerivation:
    producer_kind: MemoryEnvelopeProducerKind
    producer_schema_id: str
    producer_schema_version: str
    prompt_variant: str | None = None
    model_role: str | None = None
    kind_basis: str | None = None


@dataclass(frozen=True)
class MemoryEnvelope:
    schema_id: str
    schema_version: str
    kind: MemoryEnvelopeKind
    scope: MemoryEnvelopeScope
    derivation: MemoryEnvelopeDerivation
    subjects: list[MemorySubjectAnchor] = field(default_factory=list)
    confidence: MemoryEnvelopeConfidence = "unknown"


@dataclass(frozen=True)
class MemoryObject:
    type: str
    schema_id: str
    schema_version: str
    payload: dict[str, Any]
    lifecycle: str = "active"
    visibility: str = "private"
    container_ref: str | None = None
    actor_ref: str | None = None
    freshness_at: datetime | None = None
    envelope: MemoryEnvelope | None = None
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class Relation:
    from_kind: str
    from_id: str
    relation_type: str
    to_kind: str
    to_id: str
    id: str = field(default_factory=new_id)


@dataclass(frozen=True)
class IndexEntry:
    target_kind: str
    target_id: str
    index_type: str
    text_view: str
    text_view_name: str = "default"
    provider_name: str | None = None
    provider_version: str | None = None
    id: str = field(default_factory=new_id)


@dataclass(frozen=True)
class EvidenceReference:
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
    artifact_kind: str | None = None
    visibility: str = "private"


@dataclass(frozen=True)
class QueryFilters:
    source_type: str | None = None
    role: str | None = None
    artifact_kind: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    actor_ref: str | None = None


TurnKind = Literal["new_thread", "same_thread", "same_thread_continuation", "resumed_session", "new_session"]


@dataclass(frozen=True)
class QueryRuntimeContext:
    turn_kind: TurnKind | None = None
    session_has_sufficient_local_context: bool | None = None


@dataclass(frozen=True)
class QueryResultItem:
    result_kind: str
    score: int
    evidence: list[EvidenceReference]
    result_id: str | None = None
    memory_object_id: str | None = None
    type: str | None = None
    payload: dict[str, Any] | None = None
    freshness_at: datetime | None = None
    envelope: MemoryEnvelope | None = None
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
    artifact_kind: str | None = None
    visibility: str = "private"
    retrieval_source: str | None = None
    lexical_score: int | None = None
    vector_score: int | None = None

    def __post_init__(self) -> None:
        if self.result_id is None:
            object.__setattr__(
                self,
                "result_id",
                build_result_id(
                    result_kind=self.result_kind,
                    memory_object_id=self.memory_object_id,
                    source_item_id=self.source_item_id,
                ),
            )


@dataclass(frozen=True)
class InjectableBlock:
    result_id: str
    block_type: str
    title: str
    text: str
    evidence: list[EvidenceReference]
    memory_type: str | None = None


@dataclass(frozen=True)
class RetrievalTraceHit:
    target_kind: str
    target_id: str
    index_entry_id: str
    index_type: str
    text_view_name: str
    score: int
    matched_tokens: tuple[str, ...]
    provider_name: str | None = None
    provider_version: str | None = None
    cosine_similarity: float | None = None


@dataclass(frozen=True)
class RetrievalStageTrace:
    stage_name: str
    candidate_hits_considered: int
    candidate_hits: tuple[RetrievalTraceHit, ...]
    selected_hits: tuple[RetrievalTraceHit, ...]
    candidate_hits_before_visibility: int | None = None
    candidate_hits_after_visibility: int | None = None


@dataclass(frozen=True)
class FusionTraceHit:
    result_id: str
    rrf_score: float
    rrf_rank: int
    fused_score: int
    lexical_rank: int | None = None
    vector_rank: int | None = None
    retrieval_source: str = "lexical"


@dataclass(frozen=True)
class FusionStageTrace:
    stage_name: str = "rrf_fusion"
    k: int = 60
    rrf_score_scale: int = 600
    lexical_candidate_count: int = 0
    vector_candidate_count: int = 0
    fused_candidate_count: int = 0
    both_sources_count: int = 0
    selected_count: int = 0
    hits: tuple[FusionTraceHit, ...] = ()


@dataclass(frozen=True)
class QueryTrace:
    query_text: str
    query_tokens: tuple[str, ...]
    limit: int
    filters: QueryFilters | None
    stages: tuple[RetrievalStageTrace, ...]
    requested_filters: QueryFilters | None = None
    filter_scope_relaxed: bool = False
    filter_scope_reason: str | None = None
    routing: dict[str, Any] | None = None
    visibility: QueryVisibilityTrace | None = None
    result_summary: dict[str, Any] | None = None
    fusion_trace: FusionStageTrace | None = None
