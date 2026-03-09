from __future__ import annotations

from dataclasses import dataclass

from core.models import Annotation, IndexEntry, MemoryObject, Relation, SourceItem


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


def build_source_item(
    source_type: str,
    source_id: str,
    content_type: str,
    content: str,
    metadata: dict | None,
) -> SourceItem:
    return SourceItem(
        source_type=source_type,
        source_id=source_id,
        content_type=content_type,
        content=content,
        metadata=metadata,
    )
