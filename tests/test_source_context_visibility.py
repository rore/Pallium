"""Visibility enforcement for source-context expansion (privacy fix).

`get_source_context` (pallium_expand_source) authorizes the anchor, every
neighbor, and supported memories against the CALLER's resolved
`query_visibility`, mirroring how `/query` scopes results. Before this fix the
caller's visibility was dropped by the MCP client and never threaded into
`is_visible`, so a public-context query fell through the permissive
same-container branch and received PRIVATE same-container neighbor turns.

These E2E tests drive the HTTP boundary and assert the MCP client payload.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

CT = "chat:vis"
TH = "chat:vis:t1"


def _ingest(client: TestClient, *, source_id: str, content: str,
            container_ref: str = CT, thread_ref: str = TH,
            visibility: str = "private", actor_ref: str | None = None) -> str:
    item: dict = {
        "source_type": "chat_message",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "message",
        "role": "user",
        "container_ref": container_ref,
        "thread_ref": thread_ref,
        "visibility": visibility,
    }
    if actor_ref is not None:
        item["actor_ref"] = actor_ref
    resp = client.post("/items", json=[item])
    assert resp.status_code == 200, resp.text
    client.app.state.pallium_service.drain_processing_queue(worker_id="src-ctx-vis-test")
    return resp.json()[0]["source_item_id"]


def _context(client: TestClient, source_item_id: str, **params):
    params.setdefault("container_ref", CT)
    return client.get(f"/source/{source_item_id}/context", params=params)


def _ordered_thread(client: TestClient) -> dict[str, str]:
    """public / actor-A private / PUBLIC anchor / actor-B private / public."""
    return {
        "pub_before": _ingest(client, source_id="v-pub-before",
                               content="turn public before ordering", visibility="public"),
        "priv_a": _ingest(client, source_id="v-priv-a",
                           content="turn actor-A private ordering",
                           visibility="private", actor_ref="actor-A"),
        "anchor": _ingest(client, source_id="v-anchor",
                          content="turn public anchor ordering", visibility="public"),
        "priv_b": _ingest(client, source_id="v-priv-b",
                          content="turn actor-B private ordering",
                          visibility="private", actor_ref="actor-B"),
        "pub_after": _ingest(client, source_id="v-pub-after",
                             content="turn public after ordering", visibility="public"),
    }


# ---------------------------------------------------------------------------
# Public-context expansion never surfaces private neighbors.
# ---------------------------------------------------------------------------

def test_public_context_expansion_drops_private_neighbors(client: TestClient) -> None:
    ids = _ordered_thread(client)
    resp = _context(client, ids["anchor"], before=2, after=2, query_visibility="public")
    assert resp.status_code == 200, resp.text
    returned = {it["source_item_id"] for it in resp.json()["items"]}
    # Public anchor + public neighbors only; both private neighbors dropped.
    assert ids["anchor"] in returned
    assert ids["pub_before"] in returned
    assert ids["pub_after"] in returned
    assert ids["priv_a"] not in returned
    assert ids["priv_b"] not in returned


def test_public_context_private_anchor_denied(client: TestClient) -> None:
    anchor = _ingest(
        client,
        source_id="v-priv-anchor",
        content="private anchor ordering",
        visibility="private",
        actor_ref="actor-A",
    )
    resp = _context(client, anchor, before=1, after=1, query_visibility="public")
    # A private anchor is not visible under a public query -> 404 (no leak).
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cross-actor isolation: a container-context query never returns another
# actor's private turns. (Container context excludes ALL private turns; that
# is the mechanism that prevents actor-A from seeing actor-B's private data.)
# ---------------------------------------------------------------------------

def test_container_context_excludes_other_actor_private(client: TestClient) -> None:
    ids = _ordered_thread(client)
    resp = _context(client, ids["anchor"], before=2, after=2,
                    query_visibility="container", query_actor_ref="actor-A")
    assert resp.status_code == 200, resp.text
    returned = {it["source_item_id"] for it in resp.json()["items"]}
    assert ids["priv_b"] not in returned  # actor-B private never leaks
    assert ids["priv_a"] not in returned  # private excluded regardless of actor
    # Public neighbors still visible.
    assert ids["pub_before"] in returned
    assert ids["pub_after"] in returned


# ---------------------------------------------------------------------------
# Regression guard: private/container-context (visibility omitted / None)
# returns the same same-container private neighbors as today.
# ---------------------------------------------------------------------------

def test_private_context_default_returns_private_neighbors(client: TestClient) -> None:
    ids = _ordered_thread(client)
    # No query_visibility -> private context = current read behavior.
    resp = _context(client, ids["anchor"], before=2, after=2)
    assert resp.status_code == 200, resp.text
    returned = {it["source_item_id"] for it in resp.json()["items"]}
    # Same-container private neighbors ARE returned (unchanged behavior).
    assert ids["priv_a"] in returned
    assert ids["priv_b"] in returned
    assert ids["pub_before"] in returned
    assert ids["pub_after"] in returned


# ---------------------------------------------------------------------------
# Invalid visibility rejected at the boundary (422), never permissive.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["Public", "bogus", "PRIVATE"])
def test_invalid_visibility_rejected_at_boundary(client: TestClient, bad: str) -> None:
    ids = _ordered_thread(client)
    resp = _context(client, ids["anchor"], before=2, after=2, query_visibility=bad)
    # Typed Visibility literal -> FastAPI 422; must NOT fall through permissive.
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Window/order preserved after unauthorized neighbors are dropped.
# ---------------------------------------------------------------------------

def test_window_order_preserved_after_drops(client: TestClient) -> None:
    ids = _ordered_thread(client)
    resp = _context(client, ids["anchor"], before=2, after=2, query_visibility="public")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    returned = [it["source_item_id"] for it in items]
    # Chronological, private neighbors removed, anchor in the middle.
    assert returned == [ids["pub_before"], ids["anchor"], ids["pub_after"]]
    anchors = [it for it in items if it["is_anchor"]]
    assert len(anchors) == 1 and anchors[0]["source_item_id"] == ids["anchor"]


# ---------------------------------------------------------------------------
# MCP client threads the caller's visibility into the request params.
# (PalliumMcpClient depends only on httpx + PalliumContext, not the `mcp`
# package, so these run without the optional mcp[cli] dependency.)
from app.mcp.client import PalliumMcpClient  # noqa: E402
from app.mcp.context import PalliumContext  # noqa: E402


def _mock_get_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"items": [], "supported_memories": None, "parent_lookup_id": None}
    resp.text = json.dumps({})
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_mcp_client_sends_query_visibility_when_set() -> None:
    ctx = PalliumContext(base_url="http://localhost:8000",
                         container_ref="c", actor_ref="a", visibility="public")
    with patch("httpx.AsyncClient.get", return_value=_mock_get_response()) as mock_get:
        client = PalliumMcpClient(ctx)
        await client.get_source_context("si-1")
        params = mock_get.call_args.kwargs.get("params")
        assert params["query_visibility"] == "public"
        assert params["container_ref"] == "c"
        assert params["query_actor_ref"] == "a"


@pytest.mark.asyncio
async def test_mcp_client_omits_query_visibility_when_unset() -> None:
    ctx = PalliumContext(base_url="http://localhost:8000", container_ref="c")
    with patch("httpx.AsyncClient.get", return_value=_mock_get_response()) as mock_get:
        client = PalliumMcpClient(ctx)
        await client.get_source_context("si-1")
        params = mock_get.call_args.kwargs.get("params")
        assert "query_visibility" not in params


@pytest.mark.asyncio
async def test_mcp_client_forwards_empty_visibility_for_boundary_rejection() -> None:
    # An empty (falsy but non-None) visibility is invalid; it must be FORWARDED
    # so the route/service rejects it, not silently dropped to the permissive
    # missing-visibility private-context default.
    ctx = PalliumContext(base_url="http://localhost:8000", container_ref="c", visibility="")
    with patch("httpx.AsyncClient.get", return_value=_mock_get_response()) as mock_get:
        client = PalliumMcpClient(ctx)
        await client.get_source_context("si-1")
        params = mock_get.call_args.kwargs.get("params")
        assert params["query_visibility"] == ""


def test_public_context_filters_same_container_supported_memories(
    client: TestClient,
) -> None:
    from core.models import MemoryObject, Relation

    anchor = _ingest(
        client,
        source_id="v-supported-anchor",
        content="public anchor",
        visibility="public",
    )
    storage = client.app.state.pallium_service._storage
    ids = {}
    for name, visibility in (("private", "private"), ("public", "public")):
        memory = MemoryObject(
            type="decision",
            schema_id="test",
            schema_version="v1",
            payload={"decision": name},
            container_ref=CT,
            visibility=visibility,
        )
        storage.create_memory_object(memory)
        storage.create_relation(
            Relation(
                from_kind="memory_object",
                from_id=memory.id,
                relation_type="supported_by",
                to_kind="source_item",
                to_id=anchor,
            )
        )
        ids[name] = memory.id

    response = _context(
        client,
        anchor,
        query_visibility="public",
        include_supported_memories=True,
    )
    assert response.status_code == 200, response.text
    returned = {
        item["memory_object_id"]
        for item in response.json()["supported_memories"]
    }
    assert returned == {ids["public"]}

@pytest.mark.parametrize(
    ("occurred_at", "hide_replacement"),
    [
        (datetime(2026, 8, 20, 10, tzinfo=timezone.utc), False),
        (None, False),
        (datetime(2026, 8, 20, 10, tzinfo=timezone.utc), True),
        (None, True),
    ],
)
def test_source_context_reports_current_supersession_and_safe_unavailable_state(
    client: TestClient,
    occurred_at: datetime | None,
    hide_replacement: bool,
) -> None:
    """The public expansion surface identifies stale claims without leaking tombstones."""
    from core.models import MemoryObject, Relation, SourceItem

    created_at = datetime(2026, 8, 19, 10, tzinfo=timezone.utc)
    source = SourceItem(
        source_type="chat_message",
        source_id="history-guard-source",
        content_type="text/plain",
        content="The rollout decision was recorded here.",
        occurred_at=occurred_at,
        container_ref=CT,
        thread_ref=TH,
        role="user",
        artifact_kind="message",
        visibility="private",
        created_at=created_at,
    )
    storage = client.app.state.pallium_service._storage
    storage.create_source_item(source)

    def memory(text: str, *, memory_id: str) -> MemoryObject:
        return MemoryObject(
            id=memory_id,
            type="decision",
            schema_id="test",
            schema_version="v1",
            payload={"decision": text},
            container_ref=CT,
            visibility="private",
            created_at=created_at,
        )

    old = memory("Use the staging endpoint.", memory_id="guard-old")
    replacement = memory("Use the production endpoint.", memory_id="guard-current")
    unrelated = memory("Keep retries bounded.", memory_id="guard-unrelated")
    for item in (old, replacement, unrelated):
        storage.create_memory_object(item)
    storage.create_relation(Relation(
        from_kind="memory_object", from_id=old.id, relation_type="supported_by",
        to_kind="source_item", to_id=source.id,
    ))
    storage.create_relation(Relation(
        from_kind="memory_object", from_id=unrelated.id, relation_type="supported_by",
        to_kind="source_item", to_id=source.id,
    ))
    storage.link_supersession(old.id, replacement.id, correction_reason="new decision")
    current = memory("Use the production endpoint with retries.", memory_id="guard-head")
    storage.create_memory_object(current)
    storage.link_supersession(replacement.id, current.id, correction_reason="clarified")
    if hide_replacement:
        storage.soft_delete_memory(current.id, reason="test tombstone")

    response = _context(client, source.id, include_supported_memories=True)
    assert response.status_code == 200, response.text
    item = next(entry for entry in response.json()["items"] if entry["is_anchor"])
    assert item["recorded_at_source"] == ("event" if occurred_at else "ingest")
    assert item["recorded_at"] == (occurred_at or created_at).isoformat().replace("+00:00", "Z")

    updates = item["historical_updates"]
    assert len(updates) == 1
    assert updates[0]["outdated_memory_object_id"] == old.id
    assert updates[0]["status"] == "outdated"
    assert unrelated.id not in {update["outdated_memory_object_id"] for update in updates}
    if hide_replacement:
        assert updates[0]["replacement_status"] == "unavailable"
        assert updates[0].get("current_memory_object_id") is None
        assert updates[0].get("current_text") is None
    else:
        assert updates[0]["replacement_status"] == "current"
        assert updates[0]["current_memory_object_id"] == current.id
        assert updates[0]["current_text"] == "Decision: Use the production endpoint with retries."
@pytest.mark.parametrize("mode", ["conflict", "cycle"])
def test_source_context_marks_ambiguous_supersession_unavailable(
    client: TestClient,
    mode: str,
) -> None:
    from core.models import MemoryObject, Relation, SourceItem

    storage = client.app.state.pallium_service._storage
    source = SourceItem(
        id=f"guard-{mode}-source",
        source_type="chat_message",
        source_id=f"guard-{mode}-source",
        content_type="text/plain",
        content="An earlier decision.",
        container_ref=CT,
        thread_ref=TH,
        artifact_kind="message",
        visibility="private",
    )
    old = MemoryObject(
        id=f"guard-{mode}-old",
        type="decision",
        schema_id="test",
        schema_version="v1",
        payload={"decision": "Earlier"},
        lifecycle="superseded",
        container_ref=CT,
        visibility="private",
    )
    first = dataclasses.replace(
        old,
        id=f"guard-{mode}-first",
        payload={"decision": "First replacement"},
        lifecycle="superseded" if mode == "cycle" else "active",
    )
    memories = [old, first]
    if mode == "conflict":
        memories.append(dataclasses.replace(
            first,
            id="guard-conflict-second",
            payload={"decision": "Second replacement"},
        ))
    storage.create_source_item(source)
    for memory in memories:
        storage.create_memory_object(memory)
    storage.create_relation(Relation(
        from_kind="memory_object",
        from_id=old.id,
        relation_type="supported_by",
        to_kind="source_item",
        to_id=source.id,
    ))
    storage.create_relation(Relation(
        from_kind="memory_object",
        from_id=first.id,
        relation_type="supersedes",
        to_kind="memory_object",
        to_id=old.id,
    ))
    if mode == "conflict":
        storage.create_relation(Relation(
            from_kind="memory_object",
            from_id=memories[2].id,
            relation_type="supersedes",
            to_kind="memory_object",
            to_id=old.id,
        ))
    else:
        storage.create_relation(Relation(
            from_kind="memory_object",
            from_id=old.id,
            relation_type="supersedes",
            to_kind="memory_object",
            to_id=first.id,
        ))

    response = _context(client, source.id)
    assert response.status_code == 200, response.text
    update = response.json()["items"][0]["historical_updates"][0]
    assert update["status"] == "outdated"
    assert update["replacement_status"] == mode
    assert update["current_memory_object_id"] is None
    assert update["current_text"] is None
