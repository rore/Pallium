"""Caller-visible Derived Memory obligations, selected from documented product behavior."""

from __future__ import annotations

import pytest

from tests.config_helpers import build_agent_conversation_client


CONTAINER = "git:example.test/behavior-memory"
PROVENANCE = {
    "container_ref": CONTAINER,
    "thread_ref": "thread:memory",
    "actor_ref": "user:alpha",
    "agent_ref": "agent:test",
    "visibility": "private",
}


@pytest.fixture
def memory_client(monkeypatch, tmp_path):
    return build_agent_conversation_client(
        monkeypatch,
        f"sqlite:///{tmp_path / 'memory-contracts.db'}",
        auto_drain=True,
    )


def _note(source_id: str, content: str, *, actor: str = "user:alpha") -> dict:
    return {
        "source_type": "agent_artifact",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "note",
        "role": "user",
        "container_ref": CONTAINER,
        "thread_ref": "thread:memory",
        "actor_ref": actor,
        "visibility": "private",
    }


def _notes(client, text: str, *, actor: str = "user:alpha") -> list[dict]:
    response = client.post("/query", json={
        "text": text,
        "limit": 10,
        "container_ref": CONTAINER,
        "actor_ref": actor,
        "visibility": "private",
    })
    assert response.status_code == 200, response.text
    return [row for row in response.json()["results"] if row.get("type") == "note"]


def _remember(client, text: str) -> str:
    response = client.post("/memory/remember", json={
        **PROVENANCE,
        "text": text,
        "type": "decision",
    })
    assert response.status_code == 200, response.text
    return response.json()["memory_object_id"]


def _expand(client, memory_id: str) -> dict:
    response = client.get(
        f"/memory/{memory_id}/expand",
        params={"container_ref": CONTAINER},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_explicit_note_is_recalled_verbatim(memory_client):
    """docs/derived-memory.md §Notes: a note remains verbatim; fault: extraction paraphrases or drops it."""
    content = "Archive rotation: prepare → verify Δ → publish. Keep line two\nexactly as entered."
    response = memory_client.post("/items", json=[_note("note-verbatim", content)])
    assert response.status_code == 200, response.text

    hits = _notes(memory_client, "archive rotation verify publish")
    assert len(hits) == 1
    assert hits[0]["payload"]["content"] == content


def test_private_note_is_not_recalled_for_another_actor(memory_client):
    """docs/derived-memory.md §Memory Scoping: private recall is actor-scoped; fault: another actor sees the note."""
    response = memory_client.post(
        "/items", json=[_note("note-private", "The amber ledger belongs to alpha.")]
    )
    assert response.status_code == 200, response.text

    assert len(_notes(memory_client, "amber ledger", actor="user:alpha")) == 1
    assert _notes(memory_client, "amber ledger", actor="user:beta") == []


def test_reingesting_same_note_does_not_duplicate_recall(memory_client):
    """docs/http-api.md §Items: stable source IDs are idempotent; fault: retries yield duplicate memory cards."""
    item = _note("note-retry", "The cobalt checklist closes every seventh cycle.")
    for _ in range(2):
        response = memory_client.post("/items", json=[item])
        assert response.status_code == 200, response.text

    hits = _notes(memory_client, "cobalt checklist seventh cycle")
    assert len(hits) == 1
    assert hits[0]["payload"]["content"] == item["content"]


def test_explicit_correction_changes_public_expansion(memory_client):
    """docs/http-api.md §Explicit Memory Writes: correction replaces wrong text; fault: public expansion stays stale."""
    memory_id = _remember(memory_client, "The first ledger is canonical.")
    assert _expand(memory_client, memory_id)["payload"]["statement"] == "The first ledger is canonical."

    response = memory_client.post(
        f"/memory/{memory_id}/correct",
        json={"corrected_text": "The second ledger is canonical.", "reason": "source correction"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["corrected"] is True
    assert _expand(memory_client, memory_id)["payload"]["statement"] == "The second ledger is canonical."


def test_superseded_memory_rejects_stale_correction(memory_client):
    """docs/http-api.md §Explicit Memory Writes: a superseded ID conflicts; fault: stale correction is accepted."""
    old_id = _remember(memory_client, "Use the amber index.")
    response = memory_client.post("/memory/supersede", json={
        **PROVENANCE,
        "new_text": "Use the cobalt index.",
        "supersedes_id": old_id,
    })
    assert response.status_code == 200, response.text
    new_id = response.json()["new_memory_object_id"]
    assert _expand(memory_client, new_id)["payload"]["statement"] == "Use the cobalt index."

    stale = memory_client.post(
        f"/memory/{old_id}/correct",
        json={"corrected_text": "Use the wrong index.", "reason": "stale agent"},
    )
    assert stale.status_code == 409
    assert _expand(memory_client, new_id)["payload"]["statement"] == "Use the cobalt index."
