from __future__ import annotations

from core.models import Annotation, IndexEntry, MemoryObject, QueryFilters, Relation, SourceItem
from core.visibility import VisibilityContext
from storage.sqlite import SQLiteStorageProvider


def test_sqlite_storage_provider_contract(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    source_item = SourceItem(
        source_type="chat_thread",
        source_id="thread-1",
        content_type="text/plain",
        content="Item event time reservation ordering avoids missed hold updates.",
        metadata={"topic": "reservation ordering"},
        artifact_kind="message",
        role="user",
        container_ref="slack:C123",
        thread_ref="thread-a",
        session_ref="session-a",
        actor_ref="slack:U123",
        source_ref="https://example.test/thread-1",
        visibility_context=VisibilityContext(kind="limited", id="channel-a"),
    )
    storage.create_source_item(source_item)

    annotation = Annotation(
        source_item_id=source_item.id,
        type="summary",
        schema_id="core.summary",
        schema_version="v1",
        payload={"text": "Item event time reservation ordering avoids missed hold updates."},
    )
    storage.create_annotation(annotation)

    memory_object = MemoryObject(
        type="investigation_outcome",
        schema_id="demo.investigation_outcome",
        schema_version="v1",
        payload={"investigation_outcome": "arrival-time ordering missed hold updates during sync delays"},
        visibility_context=VisibilityContext(kind="limited", id="channel-a"),
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
        text_view="arrival time progress tracking missed hold updates during sync delays",
        text_view_name="memory_object.investigation_context",
        provider_name="builtin",
        provider_version="v1",
    )
    storage.create_index_entry(index_entry)

    source_index_entry = IndexEntry(
        target_kind="source_item",
        target_id=source_item.id,
        index_type="lexical",
        text_view="item event time reservation ordering avoids missed hold updates",
        text_view_name="source_item.content",
        provider_name="builtin",
        provider_version="v1",
    )
    storage.create_index_entry(source_index_entry)

    loaded_source = storage.get_source_item(source_item.id)
    assert loaded_source.id == source_item.id
    assert loaded_source.thread_ref == "thread-a"
    assert loaded_source.session_ref == "session-a"
    assert loaded_source.artifact_kind == "message"
    assert loaded_source.visibility_context == VisibilityContext(kind="limited", id="channel-a")
    assert storage.get_annotation(annotation.id).id == annotation.id
    assert storage.get_memory_object(memory_object.id).lifecycle == "active"

    loaded_index_entries = storage.list_index_entries_for_target("memory_object", memory_object.id)
    assert len(loaded_index_entries) == 1
    assert loaded_index_entries[0].text_view_name == "memory_object.investigation_context"
    assert loaded_index_entries[0].provider_name == "builtin"
    assert loaded_index_entries[0].provider_version == "v1"

    hits = storage.search_index_entries(["missed", "delays"], limit=5).hits
    assert hits
    assert hits[0].target_id == memory_object.id
    assert hits[0].text_view_name == "memory_object.investigation_context"
    assert set(hits[0].matched_tokens) == {"delays", "missed"}

    limited_hits = storage.search_index_entries(
        ["missed", "delays"],
        limit=5,
        visibility_contexts=(VisibilityContext(kind="public", id=None), VisibilityContext(kind="limited", id="channel-a")),
        include_visibility_trace=True,
    )
    assert limited_hits.hits
    assert limited_hits.visibility_exclusions == ()

    public_hits = storage.search_index_entries(
        ["missed", "delays"],
        limit=5,
        visibility_contexts=(VisibilityContext(kind="public", id=None),),
        include_visibility_trace=True,
    )
    assert public_hits.hits == []
    assert public_hits.visibility_exclusions
    assert public_hits.visibility_exclusions[0].reason == "query_visibility_context_excludes_candidate"

    storage.update_memory_object_lifecycle(memory_object.id, "superseded")
    assert storage.get_memory_object(memory_object.id).lifecycle == "superseded"
    hits_after_supersede = storage.search_index_entries(["missed", "delays"], limit=5).hits
    assert all(hit.target_id != memory_object.id for hit in hits_after_supersede)

    filtered_hits = storage.search_index_entries(
        ["item", "reservation", "ordering"],
        limit=5,
        filters=QueryFilters(thread_ref="thread-a", role="user", artifact_kind="message"),
    ).hits
    assert filtered_hits

    no_hits = storage.search_index_entries(
        ["item", "reservation", "ordering"],
        limit=5,
        filters=QueryFilters(thread_ref="thread-b"),
    ).hits
    assert no_hits == []

    evidence = storage.get_evidence_for_memory_object(memory_object.id)
    assert len(evidence) == 1
    assert evidence[0].source_item_id == source_item.id
    assert evidence[0].thread_ref == "thread-a"
    assert evidence[0].source_ref == "https://example.test/thread-1"
    assert evidence[0].visibility_context == VisibilityContext(kind="limited", id="channel-a")
