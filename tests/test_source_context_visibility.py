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

import json
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
    anchor = _ingest(client, source_id="v-priv-anchor",
                     content="private anchor ordering", visibility="private", actor_ref="actor-A")
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
