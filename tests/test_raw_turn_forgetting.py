"""Raw-turn user-requested forgetting (soft + auditable).

Covers the fail-closed retrieval gate (including the ``filters is None`` path),
storage-level soft-forget semantics (idempotent, auditable, point-in-time
scope), the ``/source/forget`` API, source-expansion exclusion, and mutual
independence from ``pallium_forget`` (memory-object soft-delete).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from core.filters import matches_filters
from core.models import MemoryObject, Relation, SourceItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _source_item(**overrides) -> SourceItem:
    base = dict(
        source_type="chat_message",
        source_id="s-1",
        content_type="text/plain",
        content="Decision: use item event time for reservation ordering to avoid duplicate holds.",
        container_ref="chat:room-a",
        thread_ref="chat:room-a:thread-1",
        artifact_kind="message",
        role="user",
        visibility="private",
    )
    base.update(overrides)
    return SourceItem(**base)


def _accessors(item: SourceItem):
    """Return the three storage-accessor callables matches_filters expects."""
    def get_source_item(_id: str) -> SourceItem:
        return item
    def get_memory_object(_id: str):  # pragma: no cover - unused on source path
        raise AssertionError("memory accessor should not be called for source_item")
    def get_evidence(_id: str):  # pragma: no cover - unused on source path
        raise AssertionError("evidence accessor should not be called for source_item")
    return get_memory_object, get_source_item, get_evidence


# ---------------------------------------------------------------------------
# A. matches_filters gate — the single chokepoint for lexical AND vector paths
# ---------------------------------------------------------------------------

def test_gate_excludes_forgotten_source_item_with_filters() -> None:
    item = _source_item(forgotten_at=datetime.now(timezone.utc), forgotten_reason="user asked")
    get_mo, get_si, get_ev = _accessors(item)
    from core.models import QueryFilters
    assert matches_filters(get_mo, get_si, get_ev, "source_item", item.id, QueryFilters()) is False


def test_gate_excludes_forgotten_source_item_when_filters_none() -> None:
    """Regression for the fail-closed hole: the gate must run BEFORE the
    ``filters is None`` early return, or a filter-less caller leaks the turn."""
    item = _source_item(forgotten_at=datetime.now(timezone.utc))
    get_mo, get_si, get_ev = _accessors(item)
    assert matches_filters(get_mo, get_si, get_ev, "source_item", item.id, None) is False


def test_gate_allows_active_source_item() -> None:
    item = _source_item()  # forgotten_at is None
    get_mo, get_si, get_ev = _accessors(item)
    assert matches_filters(get_mo, get_si, get_ev, "source_item", item.id, None) is True
    assert item.forgotten is False


# ---------------------------------------------------------------------------
# B. Storage-level soft-forget semantics
# ---------------------------------------------------------------------------

def _storage(client: TestClient):
    return client.app.state.pallium_service._storage


def test_forget_source_item_is_soft_idempotent_and_auditable(client: TestClient) -> None:
    storage = _storage(client)
    item = _source_item(source_id="audit-1")
    storage.create_source_item(item)

    ts = datetime.now(timezone.utc)
    assert storage.forget_source_item(item.id, reason="user request", actor_ref="user:alice", forgotten_at=ts) is True
    # Idempotent: a second forget does not modify the row.
    assert storage.forget_source_item(item.id, reason="again", actor_ref="user:bob") is False

    reloaded = storage.get_source_item(item.id)
    assert reloaded.forgotten is True
    assert reloaded.forgotten_at == ts  # first write preserved, not overwritten
    assert reloaded.forgotten_by == "user:alice"
    assert reloaded.forgotten_reason == "user request"
    # Soft, not hard: the row still exists (get_source_item did not raise).


def test_forget_source_scope_is_point_in_time(client: TestClient) -> None:
    storage = _storage(client)
    storage.create_source_item(_source_item(source_id="scope-a", thread_ref="chat:room-a:thread-1"))
    storage.create_source_item(_source_item(source_id="scope-b", thread_ref="chat:room-a:thread-1"))
    storage.create_source_item(_source_item(source_id="other-thread", thread_ref="chat:room-a:thread-2"))

    count = storage.forget_source_scope(
        container_ref="chat:room-a", thread_ref="chat:room-a:thread-1",
        reason="clear thread", actor_ref="user:alice",
    )
    assert count == 2

    # A turn ingested AFTER the scope forget is unaffected (point-in-time).
    storage.create_source_item(_source_item(source_id="scope-later", thread_ref="chat:room-a:thread-1"))
    forgotten = {
        i.source_id
        for i in storage.list_source_items_for_thread("chat:room-a", "chat:room-a:thread-1")
        if i.forgotten
    }
    assert forgotten == {"scope-a", "scope-b"}
    # Other thread untouched.
    other = storage.list_source_items_for_thread("chat:room-a", "chat:room-a:thread-2")
    assert all(not i.forgotten for i in other)


# ---------------------------------------------------------------------------
# C. Independence from pallium_forget (memory-object soft-delete)
# ---------------------------------------------------------------------------

def test_source_forget_does_not_soft_delete_memory(client: TestClient) -> None:
    storage = _storage(client)
    item = _source_item(source_id="indep-src")
    storage.create_source_item(item)
    memory = MemoryObject(
        type="decision", schema_id="test", schema_version="v1",
        payload={"decision": "x"}, container_ref="chat:room-a",
    )
    storage.create_memory_object(memory)

    storage.forget_source_item(item.id, reason="user request")

    # Forgetting the source does NOT tombstone the memory.
    assert storage.get_memory_object(memory.id).is_soft_deleted is False
    # And forgetting the memory does NOT forget the source.
    storage.soft_delete_memory(memory.id, reason="unrelated")
    assert storage.get_source_item(item.id).forgotten is True  # still from the source forget above


# ---------------------------------------------------------------------------
# D. Source-expansion exclusion
# ---------------------------------------------------------------------------

def test_get_memory_expand_omits_forgotten_source(client: TestClient) -> None:
    service = client.app.state.pallium_service
    storage = service._storage
    item = _source_item(source_id="expand-src")
    storage.create_source_item(item)
    memory = MemoryObject(
        type="decision", schema_id="test", schema_version="v1",
        payload={"decision": "x", "decision_evidence_text": "quote"},
        container_ref="chat:room-a",
    )
    storage.create_memory_object(memory)
    storage.create_relation(Relation(
        from_kind="memory_object", from_id=memory.id,
        relation_type="supported_by", to_kind="source_item", to_id=item.id,
    ))

    # Before forget: the source appears in expansion.
    _payload, items, _mt = service.get_memory_expand(memory.id, container_ref="chat:room-a")
    assert item.id in {i.id for i in items}

    storage.forget_source_item(item.id, reason="user request")

    # After forget: expansion omits it.
    _payload, items, _mt = service.get_memory_expand(memory.id, container_ref="chat:room-a")
    assert item.id not in {i.id for i in items}


# ---------------------------------------------------------------------------
# E. End-to-end via the API: /query source_hit disappears after /source/forget
# ---------------------------------------------------------------------------

def _ingest(client: TestClient, *, source_id: str, container_ref: str = "chat:room-a") -> str:
    resp = client.post("/items", json=[{
        "source_type": "chat_message",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": "Decision: use item event time for reservation ordering to avoid duplicate holds.",
        "artifact_kind": "message",
        "role": "user",
        "container_ref": container_ref,
        "thread_ref": f"{container_ref}:thread-1",
        "visibility": "private",
    }])
    assert resp.status_code == 200, resp.text
    client.app.state.pallium_service.drain_processing_queue(worker_id="forget-test")
    return resp.json()[0]["source_item_id"]


def _query_source_ids(client: TestClient, *, container_ref: str = "chat:room-a") -> set[str]:
    resp = client.post("/query", json={
        "text": "reservation ordering duplicate holds",
        "container_ref": container_ref,
        "thread_ref": f"{container_ref}:thread-1",
        "visibility": "private",
        "limit": 20,
    })
    assert resp.status_code == 200, resp.text
    return {
        r.get("source_id")
        for r in resp.json()["results"]
        if r["result_kind"] == "source_hit"
    }


def test_query_source_hit_gone_after_forget_by_id(client: TestClient) -> None:
    source_item_id = _ingest(client, source_id="e2e-1")
    assert "e2e-1" in _query_source_ids(client)

    resp = client.post("/source/forget", json={"source_item_id": source_item_id, "reason": "user request"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["forgotten"] is True
    assert body["count"] == 1

    assert "e2e-1" not in _query_source_ids(client)

    # Soft, not hard: the row still exists with an auditable marker.
    reloaded = _storage(client).get_source_item(source_item_id)
    assert reloaded.forgotten is True
    assert reloaded.forgotten_reason == "user request"


def test_source_forget_api_requires_a_target(client: TestClient) -> None:
    resp = client.post("/source/forget", json={"reason": "user request"})
    assert resp.status_code == 422


def test_source_forget_api_rejects_both_targets(client: TestClient) -> None:
    """Combining a single-item target with a scope target is ambiguous and
    could silently leave the scope unforgotten — reject it (422)."""
    resp = client.post("/source/forget", json={
        "source_item_id": "s-x",
        "container_ref": "chat:room-a",
        "reason": "user request",
    })
    assert resp.status_code == 422


def test_service_forget_source_rejects_both_targets(client: TestClient) -> None:
    import pytest
    service = client.app.state.pallium_service
    with pytest.raises(ValueError):
        service.forget_source(source_item_id="s-x", container_ref="chat:room-a", reason="r")
