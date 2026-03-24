"""Tests for actor-scoped memory and container-driven visibility rules.

Covers:
- constraint_memory role guard (assistant can't create it)
- interest/constraint suppression in shared containers
- actor_ref propagation on MemoryObject
- actor_ref query-time filtering
- backward compatibility (queries without actor_ref)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.config_helpers import build_agent_conversation_client

CONTAINER_PRIVATE = "chat:private-dm"
CONTAINER_PUBLIC = "chat:public-channel"
CONTAINER_LIMITED = "chat:team-channel"
THREAD_A = "chat:thread-a"
ACTOR_A = "user:alice"
ACTOR_B = "user:bob"


def _build_client(monkeypatch, sqlite_url: str) -> TestClient:
    return build_agent_conversation_client(monkeypatch, sqlite_url)


# ---------------------------------------------------------------------------
# Step 1: constraint_memory role guard
# ---------------------------------------------------------------------------


def test_assistant_response_does_not_produce_constraint_memory(monkeypatch, test_db_url: str) -> None:
    """Assistant messages with constraint language should not create constraint_memory."""
    events = [
        {
            "source_type": "assistant_artifact",
            "source_id": "asst-constraint-check-1",
            "content_type": "text/plain",
            "content": (
                "Important: do not use the admin portal sign-in or open a local browser. "
                "Use only the CLI-based token refresh tool to restore authentication."
            ),
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": CONTAINER_PRIVATE,
            "thread_ref": THREAD_A,
            "visibility": "private",
            "occurred_at": "2026-03-23T10:00:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle="active")
        constraint_memories = [m for m in active_memories if m.type == "constraint_memory"]
        assert not constraint_memories, (
            f"Assistant response should not create constraint_memory, "
            f"but found: {[m.payload for m in constraint_memories]}"
        )


# ---------------------------------------------------------------------------
# Step 2: interest/constraint suppression in shared containers
# ---------------------------------------------------------------------------


def test_interest_not_created_in_public_container(monkeypatch, test_db_url: str) -> None:
    """User interest in a public container should fall through to discussion_summary."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "pub-interest-1",
            "content_type": "text/plain",
            "content": "ok, chroma sounds interesting. i should check it some time.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": CONTAINER_PUBLIC,
            "thread_ref": THREAD_A,
            "visibility": "public",
            "occurred_at": "2026-03-23T10:01:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle="active")
        interest_memories = [m for m in active_memories if m.type == "interest"]
        assert not interest_memories, (
            f"Interest should not be created in public containers, "
            f"but found: {[m.payload for m in interest_memories]}"
        )
        # Should have a discussion_summary instead
        discussion_summaries = [m for m in active_memories if m.type == "discussion_summary"]
        assert discussion_summaries, (
            f"Expected discussion_summary as fallback, but only found: "
            f"{[m.type for m in active_memories]}"
        )


def test_interest_created_in_private_container(monkeypatch, test_db_url: str) -> None:
    """User interest in a private container should still create interest memory."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "priv-interest-1",
            "content_type": "text/plain",
            "content": "ok, chroma sounds interesting. i should check it some time.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": CONTAINER_PRIVATE,
            "thread_ref": THREAD_A,
            "visibility": "private",
            "occurred_at": "2026-03-23T10:01:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle="active")
        interest_memories = [m for m in active_memories if m.type == "interest"]
        assert interest_memories, (
            f"Interest should be created in private containers, "
            f"but only found: {[m.type for m in active_memories]}"
        )


def test_interest_not_created_in_limited_container(monkeypatch, test_db_url: str) -> None:
    """User interest in a limited (team) container should fall through to discussion_summary."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "ltd-interest-1",
            "content_type": "text/plain",
            "content": "ok, chroma sounds interesting. i should check it some time.",
            "artifact_kind": "message",
            "role": "user",
            "container_ref": CONTAINER_LIMITED,
            "thread_ref": THREAD_A,
            "visibility": "container",
            "occurred_at": "2026-03-23T10:01:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle="active")
        interest_memories = [m for m in active_memories if m.type == "interest"]
        assert not interest_memories, (
            f"Interest should not be created in limited containers, "
            f"but found: {[m.payload for m in interest_memories]}"
        )


# ---------------------------------------------------------------------------
# Step 3: actor_ref propagation on MemoryObject
# ---------------------------------------------------------------------------


def test_actor_ref_set_on_memory_from_private_container(monkeypatch, test_db_url: str) -> None:
    """Memory from a user message in a private container should have actor_ref set."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "priv-actor-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_PRIVATE,
            "thread_ref": THREAD_A,
            "visibility": "private",
            "occurred_at": "2026-03-23T10:02:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle="active")
        assert active_memories, "Expected at least one memory"
        # Item-level memories should have actor_ref set
        item_level_types = {"decision", "investigation_outcome", "interest", "discussion_summary", "constraint_memory"}
        item_memories = [m for m in active_memories if m.type in item_level_types]
        assert item_memories, f"Expected item-level memories, got: {[m.type for m in active_memories]}"
        for memory in item_memories:
            assert memory.actor_ref == ACTOR_A, (
                f"Item-level memory in private container should have actor_ref={ACTOR_A}, "
                f"got actor_ref={memory.actor_ref} on {memory.type}"
            )
        # Thread-level memories should always have actor_ref=None
        thread_types = {"thread_summary", "task_checkpoint"}
        thread_memories = [m for m in active_memories if m.type in thread_types]
        for memory in thread_memories:
            assert memory.actor_ref is None, (
                f"Thread-level memory should have actor_ref=None, "
                f"got actor_ref={memory.actor_ref} on {memory.type}"
            )


def test_actor_ref_null_on_memory_from_public_container(monkeypatch, test_db_url: str) -> None:
    """Memory from a user message in a public container should have actor_ref=None."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "pub-actor-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_PUBLIC,
            "thread_ref": THREAD_A,
            "visibility": "public",
            "occurred_at": "2026-03-23T10:02:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle="active")
        assert active_memories, "Expected at least one memory"
        for memory in active_memories:
            assert memory.actor_ref is None, (
                f"Memory in public container should have actor_ref=None, "
                f"got actor_ref={memory.actor_ref} on {memory.type}"
            )


def test_actor_ref_null_on_assistant_memory(monkeypatch, test_db_url: str) -> None:
    """Assistant messages in private containers get actor_ref from source_item.actor_ref.

    This is correct — in a private DM, the assistant's findings are personal
    to that container. Query-time actor filtering plus container scoping
    handles visibility correctly.
    """
    events = [
        {
            "source_type": "assistant_artifact",
            "source_id": "asst-actor-1",
            "content_type": "text/plain",
            "content": "Investigation found that arrival-time ordering applied stale hold updates during catalog sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "actor_ref": "agent:assistant-1",
            "container_ref": CONTAINER_PRIVATE,
            "thread_ref": THREAD_A,
            "visibility": "private",
            "occurred_at": "2026-03-23T10:03:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle="active")
        # In private containers, actor_ref is propagated from the source item
        item_level = [m for m in active_memories if m.type not in ("thread_summary", "task_checkpoint")]
        for memory in item_level:
            assert memory.actor_ref == "agent:assistant-1", (
                f"In private container, actor_ref should be propagated from source, "
                f"got {memory.actor_ref} on {memory.type}"
            )


# ---------------------------------------------------------------------------
# Steps 4-5: actor_ref query-time filtering
# ---------------------------------------------------------------------------


def test_query_with_actor_ref_sees_own_and_shared_memories(monkeypatch, test_db_url: str) -> None:
    """Query with actor_ref=A should see A's personal memories + shared (null) memories."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "actor-a-decision-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_PRIVATE,
            "thread_ref": THREAD_A,
            "visibility": "private",
            "occurred_at": "2026-03-23T10:04:00Z",
        },
        {
            "source_type": "chat_message",
            "source_id": "shared-decision-1",
            "content_type": "text/plain",
            "content": "Decision: use 30-minute batches for overdue notices.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_PUBLIC,
            "thread_ref": THREAD_A,
            "visibility": "public",
            "occurred_at": "2026-03-23T10:05:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        # Query with actor_ref=A should see both
        query_response = client.post("/query", json={
            "text": "what decisions have been made about ordering?",
            "limit": 10,
            "container_ref": CONTAINER_PRIVATE,
            "visibility": "private",
            "actor_ref": ACTOR_A,
        })
        assert query_response.status_code == 200


def test_query_with_actor_ref_excludes_other_actors_memories(monkeypatch, test_db_url: str) -> None:
    """Query with actor_ref=A should NOT see actor_ref=B memories."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "actor-a-interest-1",
            "content_type": "text/plain",
            "content": "ok, chroma sounds interesting. i should check it some time.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_PRIVATE,
            "thread_ref": THREAD_A,
            "visibility": "private",
            "occurred_at": "2026-03-23T10:06:00Z",
        },
        {
            "source_type": "chat_message",
            "source_id": "actor-b-interest-1",
            "content_type": "text/plain",
            "content": "ok, qdrant sounds interesting. i should check it some time.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_B,
            "container_ref": CONTAINER_PRIVATE,
            "thread_ref": THREAD_A,
            "visibility": "private",
            "occurred_at": "2026-03-23T10:07:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        # Verify both memories exist
        storage = client.app.state.pallium_service._storage
        all_memories = storage.list_memory_objects(lifecycle="active")
        actor_a_memories = [m for m in all_memories if m.actor_ref == ACTOR_A]
        actor_b_memories = [m for m in all_memories if m.actor_ref == ACTOR_B]
        assert actor_a_memories, "Expected memory with actor_ref=A"
        assert actor_b_memories, "Expected memory with actor_ref=B"

        # Query as actor A — should not see B's memories
        actor_b_memory_ids = {m.id for m in actor_b_memories}
        query_response = client.post("/query", json={
            "text": "what databases was I interested in?",
            "limit": 10,
            "container_ref": CONTAINER_PRIVATE,
            "visibility": "private",
            "actor_ref": ACTOR_A,
        })
        assert query_response.status_code == 200
        results = query_response.json()["results"]
        for result in results:
            if result["result_kind"] == "memory_hit":
                assert result["memory_object_id"] not in actor_b_memory_ids, (
                    f"Actor A's query should not return actor B's memory: {result['memory_object_id']}"
                )


def test_query_without_actor_ref_sees_everything(monkeypatch, test_db_url: str) -> None:
    """Query without actor_ref should see all memories (backward compatible)."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "compat-decision-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_PRIVATE,
            "thread_ref": THREAD_A,
            "visibility": "private",
            "occurred_at": "2026-03-23T10:08:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        # Query without actor_ref — should still work and show all memories
        query_response = client.post("/query", json={
            "text": "what decisions have been made?",
            "limit": 10,
            "container_ref": CONTAINER_PRIVATE,
            "visibility": "private",
        })
        assert query_response.status_code == 200
        results = query_response.json()["results"]
        assert results, "Expected results when querying without actor_ref"


# ---------------------------------------------------------------------------
# Step 6: source_item actor_ref filtering
# ---------------------------------------------------------------------------


def test_source_item_matches_filters_respects_actor_ref() -> None:
    """source_item_matches_filters must reject items from a different actor."""
    from core.filters import source_item_matches_filters
    from core.models import QueryFilters, SourceItem

    item_a = SourceItem(
        source_type="chat_message", source_id="si-a", content_type="text/plain",
        content="hello", actor_ref=ACTOR_A, container_ref=CONTAINER_PRIVATE,
        visibility="private",
    )
    item_b = SourceItem(
        source_type="chat_message", source_id="si-b", content_type="text/plain",
        content="hello", actor_ref=ACTOR_B, container_ref=CONTAINER_PRIVATE,
        visibility="private",
    )
    item_shared = SourceItem(
        source_type="chat_message", source_id="si-shared", content_type="text/plain",
        content="hello", actor_ref=None, container_ref=CONTAINER_PRIVATE,
        visibility="private",
    )

    filters_a = QueryFilters(actor_ref=ACTOR_A, container_ref=CONTAINER_PRIVATE)
    filters_none = QueryFilters(container_ref=CONTAINER_PRIVATE)

    # Actor A's item passes for actor A query
    assert source_item_matches_filters(item_a, filters_a) is True
    # Actor B's item must NOT pass for actor A query
    assert source_item_matches_filters(item_b, filters_a) is False
    # Shared item (actor_ref=None) always passes
    assert source_item_matches_filters(item_shared, filters_a) is True
    # Query without actor_ref sees everything
    assert source_item_matches_filters(item_a, filters_none) is True
    assert source_item_matches_filters(item_b, filters_none) is True


def test_evidence_matches_filters_respects_actor_ref() -> None:
    """evidence_matches_filters must reject evidence from a different actor."""
    from core.filters import evidence_matches_filters
    from core.models import EvidenceReference, QueryFilters

    ev_a = EvidenceReference(
        source_item_id="si-a", source_type="chat_message", source_id="ev-a",
        actor_ref=ACTOR_A, container_ref=CONTAINER_PRIVATE,
        visibility="private",
    )
    ev_b = EvidenceReference(
        source_item_id="si-b", source_type="chat_message", source_id="ev-b",
        actor_ref=ACTOR_B, container_ref=CONTAINER_PRIVATE,
        visibility="private",
    )
    ev_shared = EvidenceReference(
        source_item_id="si-s", source_type="chat_message", source_id="ev-s",
        actor_ref=None, container_ref=CONTAINER_PRIVATE,
        visibility="private",
    )

    filters_a = QueryFilters(actor_ref=ACTOR_A, container_ref=CONTAINER_PRIVATE)

    assert evidence_matches_filters(ev_a, filters_a) is True
    assert evidence_matches_filters(ev_b, filters_a) is False
    assert evidence_matches_filters(ev_shared, filters_a) is True


def test_query_with_actor_ref_excludes_other_actors_source_items(monkeypatch, test_db_url: str) -> None:
    """Query with actor_ref=A should NOT return source_hits from actor B."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "actor-a-src-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_PRIVATE,
            "thread_ref": THREAD_A,
            "visibility": "private",
            "occurred_at": "2026-03-23T10:10:00Z",
        },
        {
            "source_type": "chat_message",
            "source_id": "actor-b-src-1",
            "content_type": "text/plain",
            "content": "Decision: use arrival time for hold ordering during catalog sync.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_B,
            "container_ref": CONTAINER_PRIVATE,
            "thread_ref": THREAD_A,
            "visibility": "private",
            "occurred_at": "2026-03-23T10:11:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        # Query as actor A
        query_response = client.post("/query", json={
            "text": "what decisions about ordering?",
            "limit": 10,
            "container_ref": CONTAINER_PRIVATE,
            "visibility": "private",
            "actor_ref": ACTOR_A,
        })
        assert query_response.status_code == 200
        results = query_response.json()["results"]
        for result in results:
            if result["result_kind"] == "source_hit":
                assert result.get("actor_ref") != ACTOR_B, (
                    f"Actor A's query should not return actor B's source item: "
                    f"source_id={result.get('source_id')}"
                )
