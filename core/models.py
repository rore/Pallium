from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from core.visibility import QueryVisibilityTrace, VisibilityContext


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


@dataclass(frozen=True)
class SourceItem:
    source_type: str
    source_id: str
    content_type: str
    content: str
    metadata: dict[str, Any] | None = None
    occurred_at: datetime | None = None
    actor_ref: str | None = None
    role: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    session_ref: str | None = None
    source_ref: str | None = None
    artifact_kind: str | None = None
    visibility_context: VisibilityContext | None = None
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


@dataclass(frozen=True)
class Annotation:
    source_item_id: str
    type: str
    schema_id: str
    schema_version: str
    payload: dict[str, Any]
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class MemoryObject:
    type: str
    schema_id: str
    schema_version: str
    payload: dict[str, Any]
    lifecycle: str = "active"
    visibility_context: VisibilityContext | None = None
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
    role: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    session_ref: str | None = None
    source_ref: str | None = None
    artifact_kind: str | None = None
    visibility_context: VisibilityContext | None = None


@dataclass(frozen=True)
class QueryFilters:
    source_type: str | None = None
    role: str | None = None
    artifact_kind: str | None = None
    container_ref: str | None = None
    thread_ref: str | None = None
    session_ref: str | None = None


@dataclass(frozen=True)
class QueryResultItem:
    result_kind: str
    score: int
    evidence: list[EvidenceReference]
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
    artifact_kind: str | None = None
    visibility_context: VisibilityContext | None = None


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


@dataclass(frozen=True)
class RetrievalStageTrace:
    stage_name: str
    candidate_hits_considered: int
    candidate_hits: tuple[RetrievalTraceHit, ...]
    selected_hits: tuple[RetrievalTraceHit, ...]


@dataclass(frozen=True)
class QueryTrace:
    query_text: str
    query_tokens: tuple[str, ...]
    limit: int
    filters: QueryFilters | None
    stages: tuple[RetrievalStageTrace, ...]
    routing: dict[str, Any] | None = None
    visibility: QueryVisibilityTrace | None = None
