from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.models import Annotation, IndexEntry, MemoryObject, QueryFilters, QueryTrace, Relation, SourceItem
from core.visibility import VisibilityContext


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
    processing_status: str
    processing_attempts: int
    processing_error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "source_item_id": self.source_item_id,
            "annotation_ids": self.annotation_ids,
            "memory_object_ids": self.memory_object_ids,
            "relation_ids": self.relation_ids,
            "index_entry_ids": self.index_entry_ids,
            "processing_status": self.processing_status,
            "processing_attempts": self.processing_attempts,
            "processing_error": self.processing_error,
        }


@dataclass(frozen=True)
class ItemProcessingResult:
    source_item_id: str
    use_case: str | None
    processing_status: str
    processing_attempts: int
    processing_claimed_at: datetime | None
    processing_completed_at: datetime | None
    processing_error: str | None
    annotation_ids: list[str]
    memory_object_ids: list[str]
    relation_ids: list[str]
    index_entry_ids: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "source_item_id": self.source_item_id,
            "use_case": self.use_case,
            "processing_status": self.processing_status,
            "processing_attempts": self.processing_attempts,
            "processing_claimed_at": self.processing_claimed_at,
            "processing_completed_at": self.processing_completed_at,
            "processing_error": self.processing_error,
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
    visibility_context: VisibilityContext | None = None,
    use_case: str | None = None,
    processing_status: str = "pending",
    processing_attempts: int = 0,
    processing_claimed_by: str | None = None,
    processing_claimed_at: datetime | None = None,
    processing_lease_expires_at: datetime | None = None,
    processing_completed_at: datetime | None = None,
    processing_error: str | None = None,
    processing_next_attempt_at: datetime | None = None,
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
        visibility_context=visibility_context,
        use_case=use_case,
        processing_status=processing_status,
        processing_attempts=processing_attempts,
        processing_claimed_by=processing_claimed_by,
        processing_claimed_at=processing_claimed_at,
        processing_lease_expires_at=processing_lease_expires_at,
        processing_completed_at=processing_completed_at,
        processing_error=processing_error,
        processing_next_attempt_at=processing_next_attempt_at,
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
