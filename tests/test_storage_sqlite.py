from __future__ import annotations

import json
import multiprocessing

import pytest
from pathlib import Path

from core.models import (
    Annotation,
    IndexEntry,
    MemoryEnvelope,
    MemoryEnvelopeDerivation,
    MemoryEnvelopeScope,
    MemoryObject,
    MemorySubjectAnchor,
    QueryFilters,
    Relation,
    SourceItem,
)
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
        envelope=MemoryEnvelope(
            schema_id="core.memory_envelope",
            schema_version="v1",
            kind="finding",
            scope=MemoryEnvelopeScope(
                container_ref="slack:C123",
                thread_ref="thread-a",
                session_ref="session-a",
            ),
            subjects=[MemorySubjectAnchor(kind="component", value="reservation ordering")],
            confidence="high",
            derivation=MemoryEnvelopeDerivation(
                producer_kind="item_extraction",
                producer_schema_id="typed_memory_extraction",
                producer_schema_version="v6",
                prompt_variant="strict_typed_memory_v4_evidence_guarded",
                model_role="write_time_extraction",
                kind_basis="llm_subject_hints",
            ),
        ),
    )
    storage.create_memory_object(memory_object)

    legacy_memory_object = MemoryObject(
        type="discussion_summary",
        schema_id="demo.discussion_summary",
        schema_version="v1",
        payload={"summary": "We discussed reservation ordering."},
        visibility_context=VisibilityContext(kind="limited", id="channel-a"),
    )
    storage.create_memory_object(legacy_memory_object)

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
    loaded_memory = storage.get_memory_object(memory_object.id)
    assert loaded_memory.lifecycle == "active"
    assert loaded_memory.envelope == memory_object.envelope
    assert storage.get_memory_object(legacy_memory_object.id).envelope is None

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


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        (
            "unknown_schema_version",
            {
                "schema_id": "core.memory_envelope",
                "schema_version": "v2",
                "kind": "finding",
                "scope": {},
                "subjects": [],
                "confidence": "high",
                "derivation": {
                    "producer_kind": "item_extraction",
                    "producer_schema_id": "typed_memory_extraction",
                    "producer_schema_version": "v6",
                },
            },
        ),
        (
            "unknown_kind",
            {
                "schema_id": "core.memory_envelope",
                "schema_version": "v1",
                "kind": "unsupported_kind",
                "scope": {},
                "subjects": [],
                "confidence": "high",
                "derivation": {
                    "producer_kind": "item_extraction",
                    "producer_schema_id": "typed_memory_extraction",
                    "producer_schema_version": "v6",
                },
            },
        ),
        (
            "unknown_confidence",
            {
                "schema_id": "core.memory_envelope",
                "schema_version": "v1",
                "kind": "finding",
                "scope": {},
                "subjects": [],
                "confidence": "certain",
                "derivation": {
                    "producer_kind": "item_extraction",
                    "producer_schema_id": "typed_memory_extraction",
                    "producer_schema_version": "v6",
                },
            },
        ),
        (
            "unknown_producer_kind",
            {
                "schema_id": "core.memory_envelope",
                "schema_version": "v1",
                "kind": "finding",
                "scope": {},
                "subjects": [],
                "confidence": "high",
                "derivation": {
                    "producer_kind": "future_writer",
                    "producer_schema_id": "typed_memory_extraction",
                    "producer_schema_version": "v6",
                },
            },
        ),
        (
            "unknown_subject_kind",
            {
                "schema_id": "core.memory_envelope",
                "schema_version": "v1",
                "kind": "finding",
                "scope": {},
                "subjects": [{"kind": "topic", "value": "reservation ordering"}],
                "confidence": "high",
                "derivation": {
                    "producer_kind": "item_extraction",
                    "producer_schema_id": "typed_memory_extraction",
                    "producer_schema_version": "v6",
                },
            },
        ),
        (
            "invalid_optional_scope_type",
            {
                "schema_id": "core.memory_envelope",
                "schema_version": "v1",
                "kind": "finding",
                "scope": {"container_ref": 42},
                "subjects": [],
                "confidence": "high",
                "derivation": {
                    "producer_kind": "item_extraction",
                    "producer_schema_id": "typed_memory_extraction",
                    "producer_schema_version": "v6",
                },
            },
        ),
        (
            "invalid_optional_derivation_type",
            {
                "schema_id": "core.memory_envelope",
                "schema_version": "v1",
                "kind": "finding",
                "scope": {},
                "subjects": [],
                "confidence": "high",
                "derivation": {
                    "producer_kind": "item_extraction",
                    "producer_schema_id": "typed_memory_extraction",
                    "producer_schema_version": "v6",
                    "prompt_variant": ["wrong"],
                },
            },
        ),
    ],
)
def test_sqlite_storage_provider_rejects_invalid_memory_envelopes(label: str, payload: dict[str, object]) -> None:
    assert label
    assert SQLiteStorageProvider._load_memory_envelope(json.dumps(payload)) is None


def _initialize_sqlite_storage_process(database_url: str, result_queue) -> None:
    try:
        SQLiteStorageProvider(database_url)
    except Exception as exc:  # pragma: no cover - exercised via multiprocessing regression
        result_queue.put(f"error:{exc!r}")
        raise
    result_queue.put("ok")


def test_sqlite_storage_provider_serializes_schema_initialization(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'concurrent-startup.db'}"
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    processes = [
        context.Process(target=_initialize_sqlite_storage_process, args=(database_url, result_queue))
        for _ in range(3)
    ]

    for process in processes:
        process.start()

    results = [result_queue.get(timeout=15) for _ in processes]

    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert results == ["ok", "ok", "ok"]
    SQLiteStorageProvider(database_url)


def test_duplicate_source_type_source_id_raises_integrity_error(test_db_url: str) -> None:
    from sqlalchemy.exc import IntegrityError

    storage = SQLiteStorageProvider(test_db_url)
    item_a = SourceItem(
        source_type="chat_thread",
        source_id="dup-1",
        content_type="text/plain",
        content="First item.",
        visibility_context=VisibilityContext(kind="public"),
    )
    storage.create_source_item(item_a)

    item_b = SourceItem(
        source_type="chat_thread",
        source_id="dup-1",
        content_type="text/plain",
        content="Duplicate item.",
        visibility_context=VisibilityContext(kind="public"),
    )
    with pytest.raises(IntegrityError):
        storage.create_source_item(item_b)


def test_get_index_entry(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    index_entry = IndexEntry(
        target_kind="memory_object",
        target_id="mem-1",
        index_type="lexical",
        text_view="reservation ordering discussion",
        text_view_name="memory_object.summary",
        provider_name="builtin",
        provider_version="v1",
    )
    storage.create_index_entry(index_entry)

    loaded = storage.get_index_entry(index_entry.id)
    assert loaded.id == index_entry.id
    assert loaded.target_kind == "memory_object"
    assert loaded.target_id == "mem-1"
    assert loaded.index_type == "lexical"
    assert loaded.text_view == "reservation ordering discussion"
    assert loaded.text_view_name == "memory_object.summary"
    assert loaded.provider_name == "builtin"
    assert loaded.provider_version == "v1"


def test_get_index_entry_not_found(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    with pytest.raises(KeyError):
        storage.get_index_entry("nonexistent-id")


def test_list_index_entries_by_type(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    lexical_entry_1 = IndexEntry(
        target_kind="memory_object",
        target_id="mem-1",
        index_type="lexical",
        text_view="first lexical entry",
    )
    lexical_entry_2 = IndexEntry(
        target_kind="source_item",
        target_id="src-1",
        index_type="lexical",
        text_view="second lexical entry",
    )
    vector_entry = IndexEntry(
        target_kind="memory_object",
        target_id="mem-2",
        index_type="vector",
        text_view="a vector entry",
        provider_name="openai",
        provider_version="v3",
    )
    storage.create_index_entry(lexical_entry_1)
    storage.create_index_entry(lexical_entry_2)
    storage.create_index_entry(vector_entry)

    lexical_entries = storage.list_index_entries_by_type("lexical")
    assert len(lexical_entries) == 2
    assert {e.id for e in lexical_entries} == {lexical_entry_1.id, lexical_entry_2.id}

    vector_entries = storage.list_index_entries_by_type("vector")
    assert len(vector_entries) == 1
    assert vector_entries[0].id == vector_entry.id
    assert vector_entries[0].provider_name == "openai"

    empty_entries = storage.list_index_entries_by_type("nonexistent")
    assert empty_entries == []


def test_count_index_entries_by_type(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    for i in range(3):
        storage.create_index_entry(IndexEntry(
            target_kind="memory_object",
            target_id=f"mem-{i}",
            index_type="lexical",
            text_view=f"lexical entry {i}",
        ))
    storage.create_index_entry(IndexEntry(
        target_kind="memory_object",
        target_id="mem-v1",
        index_type="vector",
        text_view="vector entry",
    ))

    assert storage.count_index_entries_by_type("lexical") == 3
    assert storage.count_index_entries_by_type("vector") == 1
    assert storage.count_index_entries_by_type("nonexistent") == 0


def test_unique_index_migration_fails_on_existing_duplicates(tmp_path: Path) -> None:
    from sqlalchemy import create_engine, text as sql_text

    database_url = f"sqlite:///{tmp_path / 'dup-preflight.db'}"
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(sql_text(
            "CREATE TABLE source_items ("
            "id VARCHAR PRIMARY KEY, source_type VARCHAR NOT NULL, source_id VARCHAR NOT NULL, "
            "content_type VARCHAR NOT NULL, content TEXT NOT NULL, metadata_json TEXT, "
            "occurred_at DATETIME, actor_ref VARCHAR, role VARCHAR, container_ref VARCHAR, "
            "thread_ref VARCHAR, session_ref VARCHAR, source_ref VARCHAR, artifact_kind VARCHAR, "
            "visibility_kind VARCHAR, visibility_id VARCHAR, use_case VARCHAR, "
            "processing_status VARCHAR DEFAULT 'pending', processing_attempts INTEGER DEFAULT 0, "
            "processing_claimed_by VARCHAR, processing_claimed_at DATETIME, "
            "processing_lease_expires_at DATETIME, processing_completed_at DATETIME, "
            "processing_error TEXT, processing_next_attempt_at DATETIME, created_at DATETIME NOT NULL)"
        ))
        conn.execute(sql_text(
            "INSERT INTO source_items (id, source_type, source_id, content_type, content, created_at) "
            "VALUES ('id-1', 'chat', 'dup', 'text/plain', 'first', datetime('now'))"
        ))
        conn.execute(sql_text(
            "INSERT INTO source_items (id, source_type, source_id, content_type, content, created_at) "
            "VALUES ('id-2', 'chat', 'dup', 'text/plain', 'second', datetime('now'))"
        ))
    engine.dispose()

    with pytest.raises(RuntimeError, match="duplicate.*source_type.*source_id"):
        SQLiteStorageProvider(database_url)





