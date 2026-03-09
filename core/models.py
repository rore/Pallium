from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


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
