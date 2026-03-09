from __future__ import annotations

from core.models import Annotation, IndexEntry, MemoryObject, Relation, SourceItem
from storage.sqlite import SQLiteStorageProvider


def test_sqlite_storage_provider_contract(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    source_item = SourceItem(
        source_type="chat_thread",
        source_id="thread-1",
        content_type="text/plain",
        content="Event timestamp watermarking avoids skipped records.",
        metadata={"topic": "exports"},
    )
    storage.create_source_item(source_item)

    annotation = Annotation(
        source_item_id=source_item.id,
        type="summary",
        schema_id="core.summary",
        schema_version="v1",
        payload={"text": "Event timestamp watermarking avoids skipped records."},
    )
    storage.create_annotation(annotation)

    memory_object = MemoryObject(
        type="discussion_summary",
        schema_id="demo.discussion_summary",
        schema_version="v1",
        payload={"summary": "Event timestamp watermarking avoids skipped records."},
    )
    storage.create_memory_object(memory_object)

    relation = Relation(
        from_kind="memory_object",
        from_id=memory_object.id,
        relation_type="supported_by",
        to_kind="source_item",
        to_id=source_item.id,
    )
    storage.create_relation(relation)

    index_entry = IndexEntry(
        target_kind="memory_object",
        target_id=memory_object.id,
        index_type="lexical",
        text_view="event timestamp watermarking avoids skipped records",
    )
    storage.create_index_entry(index_entry)

    assert storage.get_source_item(source_item.id).id == source_item.id
    assert storage.get_annotation(annotation.id).id == annotation.id
    assert storage.get_memory_object(memory_object.id).id == memory_object.id

    hits = storage.search_index_entries(["event", "watermarking"], limit=5)
    assert hits
    assert hits[0].target_id == memory_object.id
    evidence = storage.get_evidence_for_memory_object(memory_object.id)
    assert len(evidence) == 1
    assert evidence[0].source_item_id == source_item.id
