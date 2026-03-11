from __future__ import annotations

from core.models import QueryTrace
from dataclasses import dataclass
from datetime import datetime

from core.models import Annotation, IndexEntry, MemoryObject, QueryFilters, Relation, SourceItem


@dataclass(frozen=True)
class ProcessResult:
    annotations: list[Annotation]
    memory_objects: list[MemoryObject]
    relations: list[Relation]
    index_entries: list[IndexEntry]


@dataclass(frozen=True)
class IngestResult:
    source_item_id: str
    annotation_ids: list[str]
    memory_object_ids: list[str]
    relation_ids: list[str]
    index_entry_ids: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "source_item_id": self.source_item_id,
            "annotation_ids": self.annotation_ids,
            "memory_object_ids": self.memory_object_ids,
            "relation_ids": self.relation_ids,
            "index_entry_ids": self.index_entry_ids,
        }


@dataclass(frozen=True)
class QueryResult:
    results: list
    trace: QueryTrace | None = None


def build_source_item(
    source_type: str,
    source_id: str,
    content_type: str,
    content: str,
    metadata: dict | None,
    occurred_at: datetime | None = None,
    actor_ref: str | None = None,
    role: str | None = None,
    container_ref: str | None = None,
    thread_ref: str | None = None,
    session_ref: str | None = None,
    source_ref: str | None = None,
    artifact_kind: str | None = None,
) -> SourceItem:
    return SourceItem(
        source_type=source_type,
        source_id=source_id,
        content_type=content_type,
        content=content,
        metadata=metadata,
        occurred_at=occurred_at,
        actor_ref=actor_ref,
        role=role,
        container_ref=container_ref,
        thread_ref=thread_ref,
        session_ref=session_ref,
        source_ref=source_ref,
        artifact_kind=artifact_kind,
    )


def build_query_filters(
    source_type: str | None = None,
    role: str | None = None,
    artifact_kind: str | None = None,
    container_ref: str | None = None,
    thread_ref: str | None = None,
    session_ref: str | None = None,
) -> QueryFilters | None:
    filters = QueryFilters(
        source_type=source_type,
        role=role,
        artifact_kind=artifact_kind,
        container_ref=container_ref,
        thread_ref=thread_ref,
        session_ref=session_ref,
    )
    if not any(value is not None for value in filters.__dict__.values()):
        return None
    return filters
