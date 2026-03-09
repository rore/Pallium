from __future__ import annotations

import re

from core.contracts import IngestResult, QueryResult, build_source_item
from core.models import IndexEntry
from retrieval.base import RetrievalProvider
from semantic.base import SemanticPlugin
from storage.base import StorageProvider


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _normalize_for_index(text: str) -> str:
    return " ".join(TOKEN_PATTERN.findall(text.lower()))


class PalliumService:
    def __init__(
        self,
        storage: StorageProvider,
        retrieval: RetrievalProvider,
        semantic_plugins: dict[str, SemanticPlugin],
        default_use_case: str,
    ) -> None:
        self._storage = storage
        self._retrieval = retrieval
        self._semantic_plugins = semantic_plugins
        self._default_use_case = default_use_case

    def ingest_item(
        self,
        source_type: str,
        source_id: str,
        content_type: str,
        content: str,
        metadata: dict | None,
        use_case: str | None,
    ) -> IngestResult:
        existing_source_item = self._storage.find_source_item(source_type=source_type, source_id=source_id)
        if existing_source_item is not None:
            annotations = self._storage.list_annotations_for_source_item(existing_source_item.id)
            memory_objects = self._storage.list_memory_objects_for_source_item(existing_source_item.id)
            relations = self._storage.list_relations_for_source_item(existing_source_item.id)
            index_entries = self._storage.list_index_entries_for_target(
                target_kind="source_item",
                target_id=existing_source_item.id,
            )
            for memory_object in memory_objects:
                index_entries.extend(
                    self._storage.list_index_entries_for_target(
                        target_kind="memory_object",
                        target_id=memory_object.id,
                    )
                )
            return IngestResult(
                source_item_id=existing_source_item.id,
                annotation_ids=[item.id for item in annotations],
                memory_object_ids=[item.id for item in memory_objects],
                relation_ids=[item.id for item in relations],
                index_entry_ids=[item.id for item in index_entries],
            )

        plugin_name = use_case or self._default_use_case
        plugin = self._semantic_plugins[plugin_name]

        source_item = build_source_item(
            source_type=source_type,
            source_id=source_id,
            content_type=content_type,
            content=content,
            metadata=metadata,
        )
        self._storage.create_source_item(source_item)

        source_index_entry = IndexEntry(
            target_kind="source_item",
            target_id=source_item.id,
            index_type="lexical",
            text_view=_normalize_for_index(source_item.content),
        )
        self._storage.create_index_entry(source_index_entry)

        derived = plugin.process_item(source_item)
        for annotation in derived.annotations:
            self._storage.create_annotation(annotation)
        for memory_object in derived.memory_objects:
            self._storage.create_memory_object(memory_object)
        for relation in derived.relations:
            self._storage.create_relation(relation)
        for index_entry in derived.index_entries:
            self._storage.create_index_entry(index_entry)

        return IngestResult(
            source_item_id=source_item.id,
            annotation_ids=[item.id for item in derived.annotations],
            memory_object_ids=[item.id for item in derived.memory_objects],
            relation_ids=[item.id for item in derived.relations],
            index_entry_ids=[source_index_entry.id, *[item.id for item in derived.index_entries]],
        )

    def query(self, text: str, limit: int) -> QueryResult:
        return QueryResult(results=self._retrieval.query(text=text, limit=limit))
