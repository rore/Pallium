"""End-to-end test for note memory: ingest → processing → query → injection."""
from __future__ import annotations

import pytest
from tests.config_helpers import build_agent_conversation_client


@pytest.fixture()
def client(monkeypatch, tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'test.db'}"
    return build_agent_conversation_client(
        monkeypatch,
        sqlite_url,
        auto_drain=True,
    )


NOTE_CONTENT = (
    "API key rotation procedure:\n"
    "1. Generate new key in admin console\n"
    "2. Update key in vault: vault kv put secret/api-keys/catalog-sync key=NEW_KEY\n"
    "3. Restart catalog-sync service\n"
    "4. Verify connectivity with curl\n"
    "5. Revoke old key in admin console"
)


def test_note_ingest_and_query_returns_note(client):
    """Full path: ingest note → process → query → get note back."""
    resp = client.post("/items", json=[{
        "source_type": "agent_artifact",
        "source_id": "note-e2e-001",
        "content_type": "text/plain",
        "content": NOTE_CONTENT,
        "artifact_kind": "note",
        "role": "user",
        "container_ref": "git:test/repo",
        "thread_ref": "thread-e2e-1",
        "actor_ref": "user:tester",
        "visibility": "private",
    }])
    assert resp.status_code == 200

    # Query for the note
    query_resp = client.post("/query", json={
        "text": "how to rotate API keys",
        "limit": 5,
        "container_ref": "git:test/repo",
        "actor_ref": "user:tester",
        "visibility": "private",
    })
    assert query_resp.status_code == 200
    results = query_resp.json()["results"]

    # Should find the note as a memory hit
    note_hits = [r for r in results if r.get("type") == "note"]
    assert len(note_hits) >= 1, f"Expected note in results, got: {[r.get('type') for r in results]}"

    # Verify note payload
    note = note_hits[0]
    assert note["payload"]["content"] == NOTE_CONTENT
    assert note["payload"]["title"]  # should have a title


def test_note_ingest_preserves_full_content(client):
    """Even long content is preserved verbatim in the memory object."""
    long_content = "Step " + " ".join([f"{i}. Do thing {i}." for i in range(100)])

    resp = client.post("/items", json=[{
        "source_type": "agent_artifact",
        "source_id": "note-e2e-002",
        "content_type": "text/plain",
        "content": long_content,
        "artifact_kind": "note",
        "role": "user",
        "container_ref": "git:test/repo",
        "thread_ref": "thread-e2e-2",
        "actor_ref": "user:tester",
        "visibility": "private",
    }])
    assert resp.status_code == 200

    query_resp = client.post("/query", json={
        "text": "step do thing",
        "limit": 5,
        "container_ref": "git:test/repo",
        "actor_ref": "user:tester",
        "visibility": "private",
    })
    assert query_resp.status_code == 200
    results = query_resp.json()["results"]

    note_hits = [r for r in results if r.get("type") == "note"]
    assert len(note_hits) >= 1
    assert note_hits[0]["payload"]["content"] == long_content


def test_note_not_returned_to_wrong_actor(client):
    """Private notes should not leak to other actors."""
    resp = client.post("/items", json=[{
        "source_type": "agent_artifact",
        "source_id": "note-e2e-003",
        "content_type": "text/plain",
        "content": "Secret: the deployment password is hunter2",
        "artifact_kind": "note",
        "role": "user",
        "container_ref": "git:test/repo",
        "thread_ref": "thread-e2e-3",
        "actor_ref": "user:alice",
        "visibility": "private",
    }])
    assert resp.status_code == 200

    # Query as a different actor
    query_resp = client.post("/query", json={
        "text": "deployment password",
        "limit": 5,
        "container_ref": "git:test/repo",
        "actor_ref": "user:bob",
        "visibility": "private",
    })
    assert query_resp.status_code == 200
    results = query_resp.json()["results"]

    # Bob should NOT see Alice's private note
    note_hits = [r for r in results if r.get("type") == "note"]
    assert len(note_hits) == 0, f"Private note leaked to wrong actor: {note_hits}"


def test_note_idempotent_ingest(client):
    """Ingesting same source_id twice should not create duplicates."""
    item = {
        "source_type": "agent_artifact",
        "source_id": "note-e2e-004",
        "content_type": "text/plain",
        "content": "Remember: staging resets every Sunday at 03:00 UTC",
        "artifact_kind": "note",
        "role": "user",
        "container_ref": "git:test/repo",
        "thread_ref": "thread-e2e-4",
        "actor_ref": "user:tester",
        "visibility": "private",
    }
    client.post("/items", json=[item])
    client.post("/items", json=[item])

    query_resp = client.post("/query", json={
        "text": "staging resets Sunday",
        "limit": 10,
        "container_ref": "git:test/repo",
        "actor_ref": "user:tester",
        "visibility": "private",
    })
    assert query_resp.status_code == 200
    results = query_resp.json()["results"]

    note_hits = [r for r in results if r.get("type") == "note"]
    assert len(note_hits) == 1, f"Expected exactly 1 note (idempotent), got {len(note_hits)}"


def test_note_source_evidence_available(client):
    """The source item should be accessible as evidence for the note."""
    resp = client.post("/items", json=[{
        "source_type": "agent_artifact",
        "source_id": "note-e2e-005",
        "content_type": "text/plain",
        "content": "On-call: L1 first 15 min, L2 after 15 min, L3 after 30 min",
        "artifact_kind": "note",
        "role": "user",
        "container_ref": "git:test/repo",
        "thread_ref": "thread-e2e-5",
        "actor_ref": "user:tester",
        "visibility": "private",
    }])
    assert resp.status_code == 200

    query_resp = client.post("/query", json={
        "text": "on-call escalation",
        "limit": 5,
        "container_ref": "git:test/repo",
        "actor_ref": "user:tester",
        "visibility": "private",
    })
    results = query_resp.json()["results"]
    note_hits = [r for r in results if r.get("type") == "note"]
    assert len(note_hits) >= 1

    # The note should have evidence linking back to the source
    note = note_hits[0]
    assert note.get("evidence") or note.get("memory_object_id")
