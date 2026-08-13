"""Source-centric context expansion (vNext P1).

Given a raw source_item_id, `GET /source/{id}/context` returns a BOUNDED
neighborhood of surrounding raw turns in the same thread — visibility-enforced
per neighbor, redaction-aware, forgotten-excluded, with the anchor always
included and flagged. Supported memories are opt-in and separate. Mirrors the
governance guarantees of get_memory_expand.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from core.models import MemoryObject, Relation, SourceItem

CT = "chat:ctx"
TH = "chat:ctx:t1"


def _ingest(client: TestClient, *, source_id: str, content: str,
            container_ref: str = CT, thread_ref: str = TH, visibility: str = "private") -> str:
    resp = client.post("/items", json=[{
        "source_type": "chat_message",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "message",
        "role": "user",
        "container_ref": container_ref,
        "thread_ref": thread_ref,
        "visibility": visibility,
    }])
    assert resp.status_code == 200, resp.text
    client.app.state.pallium_service.drain_processing_queue(worker_id="src-ctx-test")
    return resp.json()[0]["source_item_id"]


def _context(client: TestClient, source_item_id: str, **params):
    params.setdefault("container_ref", CT)
    resp = client.get(f"/source/{source_item_id}/context", params=params)
    return resp


# ---------------------------------------------------------------------------
# A. Bounded window + anchor flagged + chronological
# ---------------------------------------------------------------------------

def test_bounded_window_anchor_flagged_chronological(client: TestClient) -> None:
    ids = [_ingest(client, source_id=f"t{i}", content=f"turn {i} about ordering") for i in range(7)]
    anchor = ids[3]

    resp = _context(client, anchor, before=2, after=2)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    returned = [it["source_item_id"] for it in items]
    # 2 before + anchor + 2 after, chronological
    assert returned == ids[1:6]
    anchors = [it for it in items if it["is_anchor"]]
    assert len(anchors) == 1 and anchors[0]["source_item_id"] == anchor


def test_before_after_zero_returns_anchor_only(client: TestClient) -> None:
    ids = [_ingest(client, source_id=f"z{i}", content=f"turn {i} ordering") for i in range(5)]
    resp = _context(client, ids[2], before=0, after=0)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["source_item_id"] == ids[2] and items[0]["is_anchor"] is True


def test_size_cap_keeps_anchor_drops_farthest(client: TestClient) -> None:
    big = "x" * 500
    ids = [_ingest(client, source_id=f"b{i}", content=f"turn {i} ordering {big}") for i in range(7)]
    anchor = ids[3]
    # Budget only comfortably covers the anchor + ~1 neighbor.
    resp = _context(client, anchor, before=3, after=3, max_chars=700)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    ret = {it["source_item_id"] for it in items}
    assert anchor in ret  # anchor always included, exempt from cap
    assert len(items) < 7  # farthest neighbors dropped


# ---------------------------------------------------------------------------
# B. Forgotten gate (anchor + neighbor)
# ---------------------------------------------------------------------------

def test_forgotten_neighbor_omitted(client: TestClient) -> None:
    ids = [_ingest(client, source_id=f"f{i}", content=f"turn {i} ordering") for i in range(5)]
    # forget a neighbor of the anchor ids[2]
    assert client.post("/source/forget", json={"source_item_id": ids[1], "reason": "user"}).status_code == 200

    items = _context(client, ids[2], before=2, after=2).json()["items"]
    ret = {it["source_item_id"] for it in items}
    assert ids[1] not in ret
    assert ids[2] in ret


def test_forgotten_anchor_yields_404(client: TestClient) -> None:
    ids = [_ingest(client, source_id=f"fa{i}", content=f"turn {i} ordering") for i in range(3)]
    assert client.post("/source/forget", json={"source_item_id": ids[1], "reason": "user"}).status_code == 200
    resp = _context(client, ids[1], before=2, after=2)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# C. Cross-container anchor gate (adversarial — 0-violations invariant)
# ---------------------------------------------------------------------------

def test_cross_container_anchor_gate_404(client: TestClient) -> None:
    anchor = _ingest(client, source_id="priv", content="secret plan ordering",
                     container_ref="chat:room-a", thread_ref="chat:room-a:t1", visibility="private")
    # Caller in a different container must not reach a private anchor.
    resp = client.get(f"/source/{anchor}/context", params={"container_ref": "chat:room-b", "before": 2, "after": 2})
    assert resp.status_code == 404


def test_unknown_anchor_404(client: TestClient) -> None:
    resp = _context(client, "does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# D. parent_lookup_id echoed
# ---------------------------------------------------------------------------

def test_parent_lookup_id_echoed(client: TestClient) -> None:
    anchor = _ingest(client, source_id="pl", content="turn ordering")
    resp = _context(client, anchor, parent_lookup_id="lookup-123")
    assert resp.status_code == 200, resp.text
    assert resp.json()["parent_lookup_id"] == "lookup-123"


# ---------------------------------------------------------------------------
# E. Supported memories: opt-in, separate field, visibility-filtered
# ---------------------------------------------------------------------------

def _link_memory(storage, *, source_item_id: str, container_ref: str, visibility: str, mtype: str = "decision") -> str:
    mem = MemoryObject(type=mtype, schema_id="test", schema_version="v1",
                       payload={"decision": "x"}, container_ref=container_ref, visibility=visibility)
    storage.create_memory_object(mem)
    storage.create_relation(Relation(
        from_kind="memory_object", from_id=mem.id,
        relation_type="supported_by", to_kind="source_item", to_id=source_item_id,
    ))
    return mem.id


def test_supported_memories_opt_in_and_separate(client: TestClient) -> None:
    service = client.app.state.pallium_service
    storage = service._storage
    anchor = _ingest(client, source_id="sm-anchor", content="turn ordering")
    mem_id = _link_memory(storage, source_item_id=anchor, container_ref=CT, visibility="private")

    # Without opt-in: no supported memories.
    resp_off = _context(client, anchor)
    assert resp_off.status_code == 200
    assert resp_off.json()["supported_memories"] is None

    # With opt-in: present, in a separate field, never mixed into items.
    resp_on = _context(client, anchor, include_supported_memories=True)
    assert resp_on.status_code == 200, resp_on.text
    body = resp_on.json()
    sm_ids = {m["memory_object_id"] for m in body["supported_memories"]}
    assert mem_id in sm_ids
    assert all(it["source_item_id"] != mem_id for it in body["items"])


def test_supported_memory_visibility_filtered(client: TestClient) -> None:
    service = client.app.state.pallium_service
    storage = service._storage
    anchor = _ingest(client, source_id="smv-anchor", content="turn ordering")
    # A private memory in a DIFFERENT container must be dropped for a CT caller.
    other = _link_memory(storage, source_item_id=anchor, container_ref="chat:other", visibility="private")
    # A public memory is visible cross-container.
    pub = _link_memory(storage, source_item_id=anchor, container_ref="chat:other", visibility="public")

    body = _context(client, anchor, include_supported_memories=True).json()
    sm_ids = {m["memory_object_id"] for m in body["supported_memories"]}
    assert other not in sm_ids
    assert pub in sm_ids
