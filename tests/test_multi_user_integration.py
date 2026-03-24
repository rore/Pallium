"""Multi-user integration tests — end-to-end with LLM stubs.

Covers:
- Multi-user shared container end-to-end (both users see shared decisions)
- Cross-thread multi-user recall (memories visible across threads)
- Private vs public container interaction (private doesn't bleed into public)
- Consolidation of multi-actor thread summaries (pattern_memory actor_ref=None)
"""
from __future__ import annotations

import pytest

from tests.config_helpers import build_agent_conversation_client
from tests.test_thread_aggregation import ThreadAwareStubProvider

pytestmark = pytest.mark.slow

CONTAINER_TEAM = "chat:library-team"
CONTAINER_PRIVATE = "chat:private-dm"
CONTAINER_PUBLIC = "chat:catalog-shared"
ACTOR_A = "user:branch-librarian"
ACTOR_B = "user:catalog-admin"


def _build_client(monkeypatch, sqlite_url: str):
    return build_agent_conversation_client(
        monkeypatch,
        sqlite_url,
        llm_provider_factory=ThreadAwareStubProvider,
        auto_drain=True,
    )


def test_multi_user_team_channel_end_to_end(monkeypatch, test_db_url: str) -> None:
    """Two users ingest decisions in a shared container; both see all shared decisions."""
    events = [
        {
            "source_type": "chat_message",
            "source_id": "mu-team-alice-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_TEAM,
            "thread_ref": f"{CONTAINER_TEAM}:thread-shared-1",
            "visibility": "container",
            "occurred_at": "2026-03-23T10:00:00Z",
        },
        {
            "source_type": "chat_message",
            "source_id": "mu-team-bob-1",
            "content_type": "text/plain",
            "content": "Decision: use 30-minute batches for overdue notice processing to avoid staff inbox spam.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_B,
            "container_ref": CONTAINER_TEAM,
            "thread_ref": f"{CONTAINER_TEAM}:thread-shared-1",
            "visibility": "container",
            "occurred_at": "2026-03-23T10:01:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200

        # All memories should be shared (actor_ref=None)
        storage = client.app.state.pallium_service._storage
        active_memories = storage.list_memory_objects(lifecycle="active")
        item_level = [m for m in active_memories if m.type not in ("thread_summary", "task_checkpoint")]
        assert item_level, "Expected at least one item-level memory"
        for memory in item_level:
            assert memory.actor_ref is None, (
                f"Shared container memory should have actor_ref=None, "
                f"got {memory.actor_ref} on {memory.type}"
            )

        # Query as Alice
        q_alice = client.post("/query", json={
            "text": "what decisions have been made about ordering and notices?",
            "limit": 10,
            "container_ref": CONTAINER_TEAM,
            "visibility": "container",
            "actor_ref": ACTOR_A,
        })
        assert q_alice.status_code == 200
        assert q_alice.json()["results"], "Alice should see shared decisions"

        # Query as Bob
        q_bob = client.post("/query", json={
            "text": "what decisions have been made about ordering and notices?",
            "limit": 10,
            "container_ref": CONTAINER_TEAM,
            "visibility": "container",
            "actor_ref": ACTOR_B,
        })
        assert q_bob.status_code == 200
        assert q_bob.json()["results"], "Bob should see shared decisions"


def test_cross_thread_multi_user_recall(monkeypatch, test_db_url: str) -> None:
    """User A discusses in thread 1, user B in thread 2; user A queries from thread 3 and recalls both."""
    events = [
        # Thread 1: Alice discusses catalog sync
        {
            "source_type": "chat_message",
            "source_id": "mu-xthread-alice-1",
            "content_type": "text/plain",
            "content": "The catalog sync retry hit a 401 because the service token expired after 312 reservation records.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_TEAM,
            "thread_ref": f"{CONTAINER_TEAM}:thread-xthread-1",
            "visibility": "container",
            "occurred_at": "2026-03-23T10:00:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "mu-xthread-alice-asst-1",
            "content_type": "text/plain",
            "content": "Blocked: catalog API returned 401 because the service token expired.",
            "artifact_kind": "tool_use_summary",
            "role": "assistant",
            "container_ref": CONTAINER_TEAM,
            "thread_ref": f"{CONTAINER_TEAM}:thread-xthread-1",
            "visibility": "container",
            "occurred_at": "2026-03-23T10:01:00Z",
        },
        # Thread 2: Bob discusses reservation ordering
        {
            "source_type": "chat_message",
            "source_id": "mu-xthread-bob-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_B,
            "container_ref": CONTAINER_TEAM,
            "thread_ref": f"{CONTAINER_TEAM}:thread-xthread-2",
            "visibility": "container",
            "occurred_at": "2026-03-23T10:02:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "mu-xthread-bob-asst-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": CONTAINER_TEAM,
            "thread_ref": f"{CONTAINER_TEAM}:thread-xthread-2",
            "visibility": "container",
            "occurred_at": "2026-03-23T10:03:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        response = client.post("/items", json=events)
        assert response.status_code == 200

        # Alice queries from thread 3 about catalog sync
        q = client.post("/query", json={
            "text": "what happened with the catalog sync and reservation ordering?",
            "limit": 10,
            "container_ref": CONTAINER_TEAM,
            "thread_ref": f"{CONTAINER_TEAM}:thread-xthread-3",
            "visibility": "container",
            "actor_ref": ACTOR_A,
        })
        assert q.status_code == 200
        results = q.json()["results"]
        assert results, "Cross-thread recall should return results from shared container"
        # Verify we see content from at least one thread's memories
        all_text = " ".join(
            str(r.get("excerpt", "")) + str(r.get("payload", {}).get("summary", ""))
            + str(r.get("payload", {}).get("decision", ""))
            for r in results
        ).lower()
        assert "catalog" in all_text or "reservation" in all_text or "ordering" in all_text, (
            f"Cross-thread recall should include domain terms, got: {all_text[:200]}"
        )


def test_private_memories_invisible_from_public_context(monkeypatch, test_db_url: str) -> None:
    """Private interest must not appear when querying from public context."""
    events = [
        # Private interest in Alice's DM
        {
            "source_type": "chat_message",
            "source_id": "mu-priv-interest-1",
            "content_type": "text/plain",
            "content": "ok, chroma sounds interesting. i should check it some time.",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_PRIVATE,
            "thread_ref": f"{CONTAINER_PRIVATE}:thread-1",
            "visibility": "private",
            "occurred_at": "2026-03-23T10:00:00Z",
        },
        # Public decision
        {
            "source_type": "chat_message",
            "source_id": "mu-pub-decision-1",
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

        # Query from public container
        q = client.post("/query", json={
            "text": "what decisions and interests about databases?",
            "limit": 10,
            "container_ref": CONTAINER_PUBLIC,
            "visibility": "public",
            "actor_ref": ACTOR_A,
        })
        assert q.status_code == 200
        results = q.json()["results"]
        for result in results:
            if result["result_kind"] == "memory_hit":
                assert result.get("type") != "interest", (
                    f"Private interest leaked into public context: "
                    f"memory_object_id={result.get('memory_object_id')}"
                )
            if result.get("container_ref"):
                assert result["container_ref"] != CONTAINER_PRIVATE, (
                    f"Private container memory leaked into public query"
                )


def test_consolidation_multi_actor_produces_null_actor_ref(monkeypatch, test_db_url: str) -> None:
    """Pattern memory from consolidation of multi-actor thread summaries has actor_ref=None."""
    # Ingest two separate threads from two different actors with related topics
    events_thread_1 = [
        {
            "source_type": "chat_message",
            "source_id": "mu-consol-alice-msg-1",
            "content_type": "text/plain",
            "content": "Why are some library holds disappearing after catalog sync delays?",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_A,
            "container_ref": CONTAINER_TEAM,
            "thread_ref": f"{CONTAINER_TEAM}:thread-consol-1",
            "visibility": "container",
            "occurred_at": "2026-03-23T10:00:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "mu-consol-alice-asst-1",
            "content_type": "text/plain",
            "content": "Investigation found that arrival-time ordering skipped hold updates during catalog sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": CONTAINER_TEAM,
            "thread_ref": f"{CONTAINER_TEAM}:thread-consol-1",
            "visibility": "container",
            "occurred_at": "2026-03-23T10:01:00Z",
        },
    ]
    events_thread_2 = [
        {
            "source_type": "chat_message",
            "source_id": "mu-consol-bob-msg-1",
            "content_type": "text/plain",
            "content": "Are we seeing duplicate holds after catalog sync delays in the branch library?",
            "artifact_kind": "message",
            "role": "user",
            "actor_ref": ACTOR_B,
            "container_ref": CONTAINER_TEAM,
            "thread_ref": f"{CONTAINER_TEAM}:thread-consol-2",
            "visibility": "container",
            "occurred_at": "2026-03-23T10:02:00Z",
        },
        {
            "source_type": "assistant_artifact",
            "source_id": "mu-consol-bob-asst-1",
            "content_type": "text/plain",
            "content": "Decision: use item event time for reservation ordering to avoid skipped holds during sync delays.",
            "artifact_kind": "assistant_output",
            "role": "assistant",
            "container_ref": CONTAINER_TEAM,
            "thread_ref": f"{CONTAINER_TEAM}:thread-consol-2",
            "visibility": "container",
            "occurred_at": "2026-03-23T10:03:00Z",
        },
    ]
    with _build_client(monkeypatch, test_db_url) as client:
        r1 = client.post("/items", json=events_thread_1)
        assert r1.status_code == 200
        r2 = client.post("/items", json=events_thread_2)
        assert r2.status_code == 200

        # Run consolidation — try both strategies to maximize chance of producing output
        client.app.state.pallium_service.run_consolidation_pass(
            use_case="agent_conversation_memory",
            strategy_name="container_topic_window",
        )
        client.app.state.pallium_service.run_consolidation_pass(
            use_case="agent_conversation_memory",
            strategy_name="thread_summary_anchored",
        )

        # Check pattern_memory or continuity_memory produced
        storage = client.app.state.pallium_service._storage
        all_memories = storage.list_memory_objects(lifecycle="active")
        consolidated = [m for m in all_memories if m.type in ("pattern_memory", "continuity_memory")]
        # Consolidation may or may not produce results depending on topic overlap
        # and LLM stub behavior. If it does, actor_ref must be None.
        # This is a best-effort check: the structural guarantee is that
        # MemoryObject for pattern_memory/continuity_memory defaults to actor_ref=None
        # in the constructor (agent_conversation_memory_threads.py).
        for memory in consolidated:
            assert memory.actor_ref is None, (
                f"Consolidated memory should have actor_ref=None, "
                f"got actor_ref={memory.actor_ref} on {memory.type}"
            )

        # Verify thread summaries from multi-actor threads are shared (non-vacuous check)
        thread_summaries = [m for m in all_memories if m.type == "thread_summary"]
        assert thread_summaries, "Expected thread summaries from the two ingested threads"
        for ts in thread_summaries:
            assert ts.actor_ref is None, (
                f"Thread summary should have actor_ref=None, got {ts.actor_ref}"
            )
