from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.models import Annotation, EvidenceReference, IndexEntry, MemoryObject, QueryFilters, Relation, SourceItem


@dataclass(frozen=True)
class IndexSearchHit:
    target_kind: str
    target_id: str
    index_entry_id: str
    index_type: str
    text_view_name: str
    score: int
    matched_tokens: tuple[str, ...]
    provider_name: str | None = None
    provider_version: str | None = None


class StorageProvider(ABC):
    @abstractmethod
    def find_source_item(self, source_type: str, source_id: str) -> SourceItem | None:
        raise NotImplementedError

    @abstractmethod
    def create_source_item(self, source_item: SourceItem) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_source_item(self, source_item_id: str) -> SourceItem:
        raise NotImplementedError

    @abstractmethod
    def create_annotation(self, annotation: Annotation) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_source_items_for_thread(self, container_ref: str, thread_ref: str) -> list[SourceItem]:
        raise NotImplementedError

    @abstractmethod
    def get_annotation(self, annotation_id: str) -> Annotation:
        raise NotImplementedError

    @abstractmethod
    def list_annotations_for_source_item(self, source_item_id: str) -> list[Annotation]:
        raise NotImplementedError

    @abstractmethod
    def create_memory_object(self, memory_object: MemoryObject) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_memory_object(self, memory_object_id: str) -> MemoryObject:
        raise NotImplementedError

    @abstractmethod
    def update_memory_object_lifecycle(self, memory_object_id: str, lifecycle: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_memory_objects(self, memory_types: list[str] | None = None, lifecycle: str | None = None) -> list[MemoryObject]:
        raise NotImplementedError

    @abstractmethod
    def list_memory_objects_for_source_item(self, source_item_id: str) -> list[MemoryObject]:
        raise NotImplementedError

    @abstractmethod
    def create_relation(self, relation: Relation) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_relations_for_source_item(self, source_item_id: str) -> list[Relation]:
        raise NotImplementedError

    @abstractmethod
    def create_index_entry(self, index_entry: IndexEntry) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_index_entries_for_target(self, target_kind: str, target_id: str) -> list[IndexEntry]:
        raise NotImplementedError

    @abstractmethod
    def search_index_entries(self, tokens: list[str], limit: int, filters: QueryFilters | None = None) -> list[IndexSearchHit]:
        raise NotImplementedError

    @abstractmethod
    def get_evidence_for_memory_object(self, memory_object_id: str) -> list[EvidenceReference]:
        raise NotImplementedError
