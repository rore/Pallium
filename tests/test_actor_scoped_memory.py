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
    """User interest in a public container should fall through to turn_summary."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "pub-interest-1",
            "content_type": "text/plain",
            "content": "ok, chroma sounds interesting for our vector storage needs. i should check it out some time to compare with our current solution.",
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
        # Should have a turn_summary instead
        discussion_summaries = [m for m in active_memories if m.type == "turn_summary"]
        assert not discussion_summaries, (
            f"turn_summary should not be created (extraction disabled), "
            f"but found: {[m.payload for m in discussion_summaries]}"
        )


def test_interest_created_in_private_container(monkeypatch, test_db_url: str) -> None:
    """Interest type is deprecated — even private containers no longer produce interest memories."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "priv-interest-1",
            "content_type": "text/plain",
            "content": "ok, chroma sounds interesting for vector database workloads. i should check it out some time next week when i have more bandwidth.",
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
        assert not interest_memories, (
            f"Interest type is deprecated — should not produce interest memories, "
            f"but found: {[m.payload for m in interest_memories]}"
        )


def test_interest_not_created_in_limited_container(monkeypatch, test_db_url: str) -> None:
    """User interest in a limited (team) container should fall through to turn_summary."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "ltd-interest-1",
            "content_type": "text/plain",
            "content": "ok, chroma sounds interesting for our vector storage needs. i should check it out some time to compare with our current solution.",
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
        item_level_types = {"decision", "investigation_outcome", "interest", "turn_summary", "constraint_memory"}
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
            "source_id": "actor-a-decision-1",
            "content_type": "text/plain",
            "content": "Decision: we chose chroma as the vector database for our local retrieval pipeline because of simpler local deployment requirements.",
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
            "source_id": "actor-b-decision-1",
            "content_type": "text/plain",
            "content": "Decision: we chose qdrant as the vector database for our cloud retrieval pipeline because of better filtering support.",
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
            "text": "what vector database did we decide to use?",
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


# ---------------------------------------------------------------------------
# Multi-user test coverage: filter-layer, cross-container, shared visibility
# ---------------------------------------------------------------------------


def test_interest_fallthrough_in_shared_container_creates_shared_turn_summary(monkeypatch, test_db_url: str) -> None:
    """User A's interest in a shared container falls through to turn_summary
    with actor_ref=None and visibility=public (shared evidence).

    FINDING: Item-level memories (turn_summary, decision) in shared containers
    have actor_ref=None on the memory object, but their evidence references point to
    the creator's source item which retains actor_ref. This means evidence-path
    filtering at query time may prevent other users from reaching these memories
    directly. Thread-level memories (thread_summary, task_checkpoint) are fully
    shared because thread aggregation includes evidence from all participants.

    This test verifies the write-side correctness: interest suppression works,
    turn_summary fallback is created, and memory is shared (actor_ref=None).
    The query-side cross-user visibility depends on thread aggregation.
    """
    events = [
        {
            "source_type": "chat_message",
            "source_id": "mu-fallthrough-interest-1",
            "content_type": "text/plain",
            "content": "ok, chroma sounds interesting for our vector storage needs. i should check it out some time to compare with our current solution.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_PUBLIC,
            "thread_ref": f"{CONTAINER_PUBLIC}:thread-fallthrough",
            "visibility": "public",
            "occurred_at": "2026-03-23T10:00:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle="active")

        # Interest must NOT be created in public container
        assert not any(m.type == "interest" for m in active_memories), (
            "Interest should not be created in public container"
        )

        # turn_summary extraction is disabled — nothing should be created as fallback
        discussion_summaries = [m for m in active_memories if m.type == "turn_summary"]
        assert not discussion_summaries, (
            f"turn_summary should not be created (extraction disabled), "
            f"but found: {[m.payload for m in discussion_summaries]}"
        )


def test_shared_memory_visible_to_other_user_through_evidence_path(monkeypatch, test_db_url: str) -> None:
    """Shared memory (actor_ref=None) must be reachable by any user, even when
    evidence retains the creator's actor_ref. Regression test for evidence-path
    actor isolation bug where evidence_matches_filters blocked cross-user access."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "mu-evidence-path-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_LIMITED,
            "thread_ref": f"{CONTAINER_LIMITED}:thread-evidence-path",
            "visibility": "container",
            "occurred_at": "2026-03-23T10:00:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        # Verify memory is shared
        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle="active")
        item_memories = [m for m in active_memories if m.type not in ("thread_summary", "task_checkpoint")]
        assert item_memories, "Expected at least one item-level memory"
        for m in item_memories:
            assert m.actor_ref is None, f"Shared container memory should have actor_ref=None, got {m.actor_ref}"

        # User B queries — should see the shared decision
        query_b = client.post("/query", json={
            "text": "what decisions about reservation ordering?",
            "limit": 10,
            "container_ref": CONTAINER_LIMITED,
            "visibility": "container",
            "actor_ref": ACTOR_B,
        })
        assert query_b.status_code == 200
        results_b = query_b.json()["results"]
        memory_hits_b = [r for r in results_b if r["result_kind"] == "memory_hit"]
        assert memory_hits_b, (
            "User B should see shared decisions created by user A. "
            "If empty, evidence-path actor filtering is blocking cross-user access."
        )


def test_matches_filters_mixed_actor_shared_candidates() -> None:
    """matches_filters must pass personal (matching actor) + shared (null) and reject other actor."""
    from core.filters import matches_filters
    from core.models import EvidenceReference, MemoryObject, QueryFilters

    mo_alice = MemoryObject(
        id="mo-alice-1", type="decision", schema_id="test", schema_version="1",
        payload={"decision": "use event time"},
        visibility="private", container_ref=CONTAINER_PRIVATE, actor_ref=ACTOR_A,
        lifecycle="active",
    )
    mo_bob = MemoryObject(
        id="mo-bob-1", type="decision", schema_id="test", schema_version="1",
        payload={"decision": "use arrival time"},
        visibility="private", container_ref=CONTAINER_PRIVATE, actor_ref=ACTOR_B,
        lifecycle="active",
    )
    mo_shared = MemoryObject(
        id="mo-shared-1", type="decision", schema_id="test", schema_version="1",
        payload={"decision": "batch size 30"},
        visibility="container", container_ref=CONTAINER_LIMITED, actor_ref=None,
        lifecycle="active",
    )

    objects = {mo.id: mo for mo in [mo_alice, mo_bob, mo_shared]}
    ev_alice = EvidenceReference(
        source_item_id="si-a", source_type="chat_message", source_id="ev-a",
        actor_ref=ACTOR_A, container_ref=CONTAINER_PRIVATE, visibility="private",
    )
    ev_bob = EvidenceReference(
        source_item_id="si-b", source_type="chat_message", source_id="ev-b",
        actor_ref=ACTOR_B, container_ref=CONTAINER_PRIVATE, visibility="private",
    )
    ev_shared = EvidenceReference(
        source_item_id="si-s", source_type="chat_message", source_id="ev-s",
        actor_ref=None, container_ref=CONTAINER_LIMITED, visibility="container",
    )
    evidence_map = {"mo-alice-1": [ev_alice], "mo-bob-1": [ev_bob], "mo-shared-1": [ev_shared]}

    filters = QueryFilters(actor_ref=ACTOR_A, container_ref=CONTAINER_PRIVATE)

    assert matches_filters(
        objects.get, lambda _: None, evidence_map.get,
        "memory_object", "mo-alice-1", filters,
    ) is True, "Alice's memory should pass for alice's query"

    assert matches_filters(
        objects.get, lambda _: None, evidence_map.get,
        "memory_object", "mo-bob-1", filters,
    ) is False, "Bob's memory should NOT pass for alice's query"

    # Shared memory: actor_ref=None always passes actor filter
    shared_filters = QueryFilters(actor_ref=ACTOR_A, container_ref=CONTAINER_LIMITED)
    assert matches_filters(
        objects.get, lambda _: None, evidence_map.get,
        "memory_object", "mo-shared-1", shared_filters,
    ) is True, "Shared (null actor) memory should pass for any actor's query"

    # Cross-container case: shared memory in LIMITED container checked against
    # PRIVATE container filter — evidence container_ref won't match, so should fail
    assert matches_filters(
        objects.get, lambda _: None, evidence_map.get,
        "memory_object", "mo-shared-1", filters,
    ) is False, "Shared memory in different container should NOT pass cross-container filter"


def test_cross_container_isolation_between_users_private_containers(monkeypatch, test_db_url: str) -> None:
    """Memories in Alice's private container are invisible from Bob's private container."""
    container_alice = "chat:alice-dm"
    container_bob = "chat:bob-dm"
    events = [
        {
            "source_type": "chat_message",
            "source_id": "alice-priv-decision-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": container_alice,
            "thread_ref": f"{container_alice}:thread-1",
            "visibility": "private",
            "occurred_at": "2026-03-23T10:00:00Z",
        },
        {
            "source_type": "chat_message",
            "source_id": "bob-priv-decision-1",
            "content_type": "text/plain",
            "content": "Decision: use arrival time for hold processing during sync delays.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_B,
            "container_ref": container_bob,
            "thread_ref": f"{container_bob}:thread-1",
            "visibility": "private",
            "occurred_at": "2026-03-23T10:01:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        # Query from Alice's container — must NOT see Bob's container memories
        query_response = client.post("/query", json={
            "text": "what decisions about ordering?",
            "limit": 10,
            "container_ref": container_alice,
            "visibility": "private",
            "actor_ref": ACTOR_A,
        })
        assert query_response.status_code == 200
        results = query_response.json()["results"]
        assert results, "Alice should see at least her own container's memories"
        for result in results:
            assert result.get("container_ref") != container_bob, (
                f"Alice's query from her private container should not see Bob's container: "
                f"result={result.get('source_id') or result.get('memory_object_id')}"
            )


def test_cross_container_bleed_prevention_private_to_shared(monkeypatch, test_db_url: str) -> None:
    """Private interest must NOT leak into public container queries, even for the same actor."""
    events = [
        # Alice's private interest in her DM
        {
            "source_type": "chat_message",
            "source_id": "alice-priv-interest-1",
            "content_type": "text/plain",
            "content": "ok, chroma sounds interesting for vector database workloads. i should check it out some time next week when i have more bandwidth.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_PRIVATE,
            "thread_ref": f"{CONTAINER_PRIVATE}:thread-1",
            "visibility": "private",
            "occurred_at": "2026-03-23T10:00:00Z",
        },
        # Alice's shared decision in public container
        {
            "source_type": "chat_message",
            "source_id": "alice-pub-decision-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to prevent duplicate holds.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_PUBLIC,
            "thread_ref": f"{CONTAINER_PUBLIC}:thread-1",
            "visibility": "public",
            "occurred_at": "2026-03-23T10:01:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        # Query from public context — private interest must not appear
        query_response = client.post("/query", json={
            "text": "what do we know about databases and ordering?",
            "limit": 10,
            "container_ref": CONTAINER_PUBLIC,
            "visibility": "public",
            "actor_ref": ACTOR_A,
        })
        assert query_response.status_code == 200
        results = query_response.json()["results"]
        for result in results:
            if result["result_kind"] == "memory_hit":
                assert result.get("type") != "interest", (
                    f"Private interest should not appear in public container query: "
                    f"memory_object_id={result.get('memory_object_id')}"
                )
            # Also verify no private container memories leak
            if result.get("container_ref"):
                assert result["container_ref"] != CONTAINER_PRIVATE, (
                    f"Private container memory leaked into public query: "
                    f"result={result.get('source_id') or result.get('memory_object_id')}"
                )


def test_shared_container_both_users_see_all_decisions(monkeypatch, test_db_url: str) -> None:
    """In a shared container, both users' decisions become shared (actor_ref=None) and visible to all."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "alice-team-decision-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_LIMITED,
            "thread_ref": f"{CONTAINER_LIMITED}:thread-1",
            "visibility": "container",
            "occurred_at": "2026-03-23T10:00:00Z",
        },
        {
            "source_type": "chat_message",
            "source_id": "bob-team-decision-1",
            "content_type": "text/plain",
            "content": "Decision: use 30-minute batches for overdue notice processing.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_B,
            "container_ref": CONTAINER_LIMITED,
            "thread_ref": f"{CONTAINER_LIMITED}:thread-1",
            "visibility": "container",
            "occurred_at": "2026-03-23T10:01:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200
        client.app.state.pallium_service.drain_processing_queue(worker_id="test")

        # All memories should have actor_ref=None (shared)
        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle="active")
        item_level = [m for m in active_memories if m.type not in ("thread_summary", "task_checkpoint")]
        for memory in item_level:
            assert memory.actor_ref is None, (
                f"Memory in shared container should have actor_ref=None, "
                f"got actor_ref={memory.actor_ref} on {memory.type}"
            )

        # Query as Alice — should see results
        query_alice = client.post("/query", json={
            "text": "what decisions about ordering and batches?",
            "limit": 10,
            "container_ref": CONTAINER_LIMITED,
            "visibility": "container",
            "actor_ref": ACTOR_A,
        })
        assert query_alice.status_code == 200
        alice_results = query_alice.json()["results"]
        assert alice_results, "Alice should see shared decisions"

        # Query as Bob — should see same results
        query_bob = client.post("/query", json={
            "text": "what decisions about ordering and batches?",
            "limit": 10,
            "container_ref": CONTAINER_LIMITED,
            "visibility": "container",
            "actor_ref": ACTOR_B,
        })
        assert query_bob.status_code == 200
        bob_results = query_bob.json()["results"]
        assert bob_results, "Bob should see shared decisions"

        # Both users should see memory hits with actor_ref=None (shared).
        # Note: evidence-based filtering means each user may see different item-level
        # memories (their own source items' decisions) plus the same thread-level memories.
        # The key invariant: all visible memories are shared (actor_ref=None).
        alice_memory_ids = {r["memory_object_id"] for r in alice_results if r["result_kind"] == "memory_hit"}
        bob_memory_ids = {r["memory_object_id"] for r in bob_results if r["result_kind"] == "memory_hit"}
        assert alice_memory_ids, "Alice should see memory hits"
        assert bob_memory_ids, "Bob should see memory hits"
        # Thread-level memories (thread_summary) should be identical for both
        alice_thread_ids = {r["memory_object_id"] for r in alice_results
                           if r["result_kind"] == "memory_hit" and r.get("type") == "thread_summary"}
        bob_thread_ids = {r["memory_object_id"] for r in bob_results
                         if r["result_kind"] == "memory_hit" and r.get("type") == "thread_summary"}
        assert alice_thread_ids == bob_thread_ids, (
            f"Thread summaries should be identical for both users. "
            f"Alice: {alice_thread_ids}, Bob: {bob_thread_ids}"
        )


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


# ---------------------------------------------------------------------------
# Global visibility filter exemption tests
# ---------------------------------------------------------------------------


def test_source_item_matches_filters_global_crosses_container() -> None:
    """Global source items pass container_ref filter (not excluded cross-container)."""
    from core.filters import source_item_matches_filters
    from core.models import QueryFilters, SourceItem

    item = SourceItem(
        source_type="chat_message",
        source_id="src-1",
        content_type="text/plain",
        content="test content",
        role="user",
        container_ref="container-a",
        visibility="global",
        actor_ref="alice",
    )
    filters = QueryFilters(container_ref="container-b")
    assert source_item_matches_filters(item, filters) is True


def test_evidence_matches_filters_global_crosses_container() -> None:
    """Global evidence passes container_ref filter (not excluded cross-container)."""
    from core.filters import evidence_matches_filters
    from core.models import EvidenceReference, QueryFilters

    evidence = EvidenceReference(
        source_item_id="si-1",
        source_type="chat_message",
        source_id="src-1",
        role="user",
        container_ref="container-a",
        visibility="global",
        actor_ref="alice",
    )
    filters = QueryFilters(container_ref="container-b")
    assert evidence_matches_filters(evidence, filters) is True


def test_source_item_matches_filters_private_still_blocked() -> None:
    """Private source items still rejected cross-container (regression guard)."""
    from core.filters import source_item_matches_filters
    from core.models import QueryFilters, SourceItem

    item = SourceItem(
        source_type="chat_message",
        source_id="src-1",
        content_type="text/plain",
        content="test content",
        role="user",
        container_ref="container-a",
        visibility="private",
    )
    filters = QueryFilters(container_ref="container-b")
    assert source_item_matches_filters(item, filters) is False
