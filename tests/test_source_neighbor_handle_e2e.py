"""Public MCP navigation to a following source beyond the expansion budget."""
from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import bindparam, text

pytest.importorskip("mcp", reason="mcp[cli] not installed")

from app.mcp.server import create_server

CONTAINER = "chat:neighbor-handle"
THREAD = "chat:neighbor-handle:thread"
ACTOR = "reader"


def _ingest(
    client, source_id: str, content: str, *, thread_ref: str = THREAD,
    actor_ref: str = ACTOR, visibility: str = "private",
) -> str:
    response = client.post("/items", json=[{
        "source_type": "chat_message",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "artifact_kind": "message",
        "role": "user",
        "actor_ref": actor_ref,
        "container_ref": CONTAINER,
        "thread_ref": thread_ref,
        "visibility": visibility,
    }])
    assert response.status_code == 200, response.text
    client.app.state.pallium_service.drain_processing_queue(
        worker_id="neighbor-handle-e2e",
    )
    return response.json()[0]["source_item_id"]


def _mcp_server(client, monkeypatch: pytest.MonkeyPatch):
    real_async_client = httpx.AsyncClient

    def asgi_client(*args, **kwargs):
        kwargs["transport"] = httpx.ASGITransport(app=client.app)
        kwargs["base_url"] = "http://testserver"
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("app.mcp.client.httpx.AsyncClient", asgi_client)
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://testserver")
    return create_server()


@pytest.mark.asyncio
async def test_public_mcp_returns_oversized_following_handle_without_receipt(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor_content = "anchor marker " + "界" * (2362 - len("anchor marker "))
    anchor_id = _ingest(client, "neighbor-anchor", anchor_content)
    middle_id = _ingest(client, "neighbor-middle", "middle " * 14 + "界" * 2)
    following_id = _ingest(
        client, "neighbor-following", "password=hunter2 " + "😀" * 2770,
    )
    last_id = _ingest(client, "neighbor-last", "last 漢字 " * 350)
    server = _mcp_server(client, monkeypatch)
    search_content, _ = await server.call_tool("pallium_search_history", {
        "query": "anchor marker",
        "container_ref": CONTAINER,
        "thread_ref": THREAD,
        "actor_ref": ACTOR,
        "visibility": "private",
    })
    search = json.loads(search_content[0].text)
    assert any(item["source_item_id"] == anchor_id for item in search["results"])
    content, _ = await server.call_tool("pallium_expand_source", {
        "source_item_id": anchor_id,
        "before": 0,
        "after": 3,
        "max_chars": 4000,
        "container_ref": CONTAINER,
        "thread_ref": THREAD,
        "actor_ref": ACTOR,
        "visibility": "private",
        "parent_lookup_id": search["lookup_event_id"],
    })

    payload = json.loads(content[0].text)
    assert len(content[0].text) <= 4000
    assert payload.get("next_source_item_id") == following_id
    assert [item["source_item_id"] for item in payload["items"]] == [anchor_id, middle_id]
    assert all(item["content"] != "😀" * 2787 for item in payload["items"])

    following_content, _ = await server.call_tool("pallium_expand_source", {
        "source_item_id": following_id,
        "before": 0,
        "after": 1,
        "max_chars": 4000,
        "container_ref": CONTAINER,
        "thread_ref": THREAD,
        "actor_ref": ACTOR,
        "visibility": "private",
        "parent_lookup_id": search["lookup_event_id"],
    })
    following = json.loads(following_content[0].text)
    assert len(following_content[0].text) <= 4000
    assert following["items"][0]["source_item_id"] == following_id
    assert "hunter2" not in following["items"][0]["content"]
    assert "[REDACTED]" in following["items"][0]["content"]
    assert following["next_source_item_id"] == last_id
    assert following["parent_lookup_id"] == search["lookup_event_id"]

    last_content, _ = await server.call_tool("pallium_expand_source", {
        "source_item_id": last_id,
        "before": 0,
        "after": 1,
        "max_chars": 4000,
        "container_ref": CONTAINER,
        "thread_ref": THREAD,
        "actor_ref": ACTOR,
        "visibility": "private",
        "parent_lookup_id": search["lookup_event_id"],
    })
    last = json.loads(last_content[0].text)
    assert len(last_content[0].text) <= 4000
    assert last["items"][0]["source_item_id"] == last_id
    assert last.get("next_source_item_id") is None
    assert last["parent_lookup_id"] == search["lookup_event_id"]

    storage = client.app.state.pallium_service._storage
    with storage._engine.connect() as connection:
        expansions = connection.execute(text(
            "SELECT exposed_json FROM historical_lookup_reuse_event "
            "WHERE event_type = 'expansion' AND parent_lookup_id = :parent "
            "ORDER BY created_at"
        ), {"parent": search["lookup_event_id"]}).mappings().all()
    assert len(expansions) == 3
    delivered = [json.loads(row["exposed_json"]) for row in expansions]
    assert following_id not in {item["source_item_id"] for item in delivered[0]}
    assert any(item["source_item_id"] == following_id for item in delivered[1])
    assert any(item["source_item_id"] == last_id for item in delivered[2])


@pytest.mark.asyncio
async def test_neighbor_handle_refetch_rechecks_scope_and_forgetting(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor_id = _ingest(client, "scope-anchor", "scope marker " + "a" * 90)
    target_id = _ingest(client, "scope-target", "t" * 5000)
    server = _mcp_server(client, monkeypatch)
    search_content, _ = await server.call_tool("pallium_search_history", {
        "query": "scope marker", "container_ref": CONTAINER,
        "thread_ref": THREAD, "actor_ref": ACTOR, "visibility": "private",
    })
    lookup_id = json.loads(search_content[0].text)["lookup_event_id"]
    base = {
        "before": 0, "after": 1, "max_chars": 4000,
        "container_ref": CONTAINER, "thread_ref": THREAD,
        "actor_ref": ACTOR, "visibility": "private",
        "parent_lookup_id": lookup_id,
    }
    initial_content, _ = await server.call_tool("pallium_expand_source", {
        **base, "source_item_id": anchor_id,
    })
    assert json.loads(initial_content[0].text)["next_source_item_id"] == target_id

    for changed_scope in (
        {"actor_ref": "other-reader"},
        {"visibility": "public"},
        {"container_ref": "chat:other"},
    ):
        denied_content, _ = await server.call_tool("pallium_expand_source", {
            **base, **changed_scope, "source_item_id": target_id,
        })
        denied = json.loads(denied_content[0].text)
        assert denied.get("error")
        assert "items" not in denied

    forgotten = client.post("/source/forget", json={
        "source_item_id": target_id, "reason": "test lifecycle",
        "actor_ref": ACTOR,
    })
    assert forgotten.status_code == 200, forgotten.text
    for source_item_id in (target_id, "missing-neighbor-handle"):
        denied_content, _ = await server.call_tool("pallium_expand_source", {
            **base, "source_item_id": source_item_id,
        })
        denied = json.loads(denied_content[0].text)
        assert denied.get("error")
        assert "items" not in denied


@pytest.mark.asyncio
async def test_anchor_continuation_preserves_following_handle(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread = "chat:neighbor-handle:continuation"
    anchor_id = _ingest(
        client, "continuation-anchor", "continuation marker " + "界" * 4980,
        thread_ref=thread,
    )
    following_id = _ingest(
        client, "continuation-following", "😀" * 5000, thread_ref=thread,
    )
    server = _mcp_server(client, monkeypatch)
    search_content, _ = await server.call_tool("pallium_search_history", {
        "query": "continuation marker", "container_ref": CONTAINER,
        "thread_ref": thread, "actor_ref": ACTOR, "visibility": "private",
    })
    lookup_id = json.loads(search_content[0].text)["lookup_event_id"]
    arguments = {
        "source_item_id": anchor_id, "before": 0, "after": 1,
        "max_chars": 4000, "container_ref": CONTAINER,
        "thread_ref": thread, "actor_ref": ACTOR,
        "visibility": "private", "parent_lookup_id": lookup_id,
    }
    first_content, _ = await server.call_tool("pallium_expand_source", arguments)
    first = json.loads(first_content[0].text)
    assert first["next_source_item_id"] == following_id
    assert first["has_more"] is True
    continuation_content, _ = await server.call_tool("pallium_expand_source", {
        **arguments,
        "content_offset": first["next_offset"],
        "content_revision": first["content_revision"],
    })
    continuation = json.loads(continuation_content[0].text)
    assert len(continuation_content[0].text) <= 4000
    assert continuation["next_source_item_id"] == following_id
    assert continuation["parent_lookup_id"] == lookup_id


@pytest.mark.asyncio
async def test_public_mcp_preserves_handle_when_serialized_metadata_drops_a_turn(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread = "chat:neighbor-handle:metadata"
    ids = [
        _ingest(client, f"metadata-{i}", f"metadata message {i}", thread_ref=thread)
        for i in range(5)
    ]
    raw = client.get(f"/source/{ids[0]}/context", params={
        "container_ref": CONTAINER, "query_visibility": "private",
        "before": 0, "after": 4, "max_chars": 800,
    }).json()
    assert [item["source_item_id"] for item in raw["items"]] == ids
    assert raw["next_source_item_id"] is None
    server = _mcp_server(client, monkeypatch)
    search_content, _ = await server.call_tool("pallium_search_history", {
        "query": "metadata message", "container_ref": CONTAINER,
        "thread_ref": thread, "visibility": "private",
    })
    arguments = {
        "before": 0, "after": 4, "max_chars": 800,
        "container_ref": CONTAINER, "thread_ref": thread, "visibility": "private",
        "parent_lookup_id": json.loads(search_content[0].text)["lookup_event_id"],
    }
    content, _ = await server.call_tool("pallium_expand_source", {
        **arguments, "source_item_id": ids[0],
    })
    result = json.loads(content[0].text)
    assert len(content[0].text) <= 800
    assert "items" in result, result
    delivered = {item["source_item_id"] for item in result["items"]}
    first_omitted = next(source_id for source_id in ids[1:] if source_id not in delivered)
    assert result["next_source_item_id"] == first_omitted
    opened, _ = await server.call_tool("pallium_expand_source", {
        **arguments, "source_item_id": result["next_source_item_id"], "after": 0,
    })
    assert json.loads(opened[0].text)["items"][0]["source_item_id"] == first_omitted
    assert len(opened[0].text) <= 800


def test_http_handle_requires_an_eligible_following_neighbor(client) -> None:
    thread = "chat:neighbor-handle:boundaries"
    cases = (
        ("fit", "anchor-" + "a" * 92, "b" * 100, 200, True),
        ("exact", "a" * 100, "b" * 3900, 4000, True),
        ("over", "a" * 100, "b" * 3901, 4000, False),
        ("empty", "anchor-empty", "", 200, True),
    )
    for name, anchor_text, following_text, budget, should_fit in cases:
        case_thread = f"{thread}:{name}"
        anchor_id = _ingest(
            client, f"{name}-anchor", anchor_text, thread_ref=case_thread,
        )
        following_id = _ingest(
            client, f"{name}-following", following_text or "placeholder",
            thread_ref=case_thread,
        )
        if not following_text:
            with client.app.state.pallium_service._storage._engine.begin() as connection:
                connection.execute(text(
                    "UPDATE source_items SET content = '' WHERE id = :source_item_id"
                ), {"source_item_id": following_id})
        response = client.get(f"/source/{anchor_id}/context", params={
            "container_ref": CONTAINER, "query_visibility": "private",
            "query_actor_ref": ACTOR, "before": 0, "after": 1,
            "max_chars": budget,
        })
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload.get("next_source_item_id") == (None if should_fit else following_id)
        if should_fit:
            assert [item["source_item_id"] for item in payload["items"]] == [
                anchor_id, following_id,
            ]

    end_id = _ingest(client, "end-anchor", "end", thread_ref=f"{thread}:end")
    end = client.get(f"/source/{end_id}/context", params={
        "container_ref": CONTAINER, "after": 1, "max_chars": 4000,
    })
    assert end.status_code == 200
    assert end.json().get("next_source_item_id") is None

    no_sides_id = _ingest(client, "zero-sides-anchor", "anchor", thread_ref=f"{thread}:zero")
    _ingest(client, "zero-sides-following", "z" * 5000, thread_ref=f"{thread}:zero")
    no_sides = client.get(f"/source/{no_sides_id}/context", params={
        "container_ref": CONTAINER, "before": 0, "after": 0,
    })
    assert no_sides.status_code == 200
    assert no_sides.json().get("next_source_item_id") is None

    public_thread = f"{thread}:visibility"
    public_anchor = _ingest(
        client, "public-anchor", "public", thread_ref=public_thread,
        actor_ref=None, visibility="public",
    )
    private_neighbor = _ingest(
        client, "private-neighbor", "private" * 1000,
        thread_ref=public_thread, actor_ref=None, visibility="private",
    )
    forgotten_neighbor = _ingest(
        client, "forgotten-neighbor", "forgotten" * 1000,
        thread_ref=public_thread, actor_ref=None, visibility="public",
    )
    eligible_neighbor = _ingest(
        client, "eligible-public-neighbor", "eligible" * 1000,
        thread_ref=public_thread, actor_ref=None, visibility="public",
    )
    forgotten = client.post("/source/forget", json={
        "source_item_id": forgotten_neighbor, "reason": "test eligibility",
        "actor_ref": ACTOR,
    })
    assert forgotten.status_code == 200, forgotten.text
    public_context = client.get(f"/source/{public_anchor}/context", params={
        "container_ref": CONTAINER, "query_visibility": "public",
        "before": 0, "after": 3,
        "max_chars": 4000,
    })
    assert public_context.status_code == 200, public_context.text
    public_payload = public_context.json()
    returned_ids = {item["source_item_id"] for item in public_payload["items"]}
    assert private_neighbor not in returned_ids
    assert forgotten_neighbor not in returned_ids
    assert private_neighbor != public_payload.get("next_source_item_id")
    assert forgotten_neighbor != public_payload.get("next_source_item_id")
    assert public_payload.get("next_source_item_id") == eligible_neighbor


def test_http_handle_skips_ineligible_neighbors_and_keeps_the_side_limit(client) -> None:
    thread = "chat:neighbor-handle:privacy"
    anchor_id = _ingest(
        client, "privacy-anchor", "a" * 100, thread_ref=thread,
    )
    hidden_id = _ingest(
        client, "privacy-hidden", "h" * 5000, thread_ref=thread,
        actor_ref="other-reader",
    )
    eligible_id = _ingest(
        client, "privacy-eligible", "e" * 5000, thread_ref=thread,
    )
    response = client.get(f"/source/{anchor_id}/context", params={
        "container_ref": CONTAINER, "query_visibility": "private",
        "query_actor_ref": ACTOR, "before": 0, "after": 2,
        "max_chars": 4000,
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert hidden_id not in {item["source_item_id"] for item in payload["items"]}
    assert payload.get("next_source_item_id") == eligible_id

    bounded_thread = f"{thread}:bounded"
    rows = [{
        "source_type": "chat_message", "source_id": f"bounded-{index:02d}",
        "content_type": "text/plain", "content": "x",
        "artifact_kind": "message", "role": "user", "actor_ref": ACTOR,
        "container_ref": CONTAINER, "thread_ref": bounded_thread,
        "visibility": "private",
    } for index in range(27)]
    ingested = client.post("/items", json=rows)
    assert ingested.status_code == 200, ingested.text
    bounded_ids = [item["source_item_id"] for item in ingested.json()]
    client.app.state.pallium_service.drain_processing_queue(
        worker_id="neighbor-handle-e2e-boundary",
    )
    with client.app.state.pallium_service._storage._engine.begin() as connection:
        connection.execute(text(
            "UPDATE source_items SET content = '' WHERE id IN :source_item_ids"
        ).bindparams(bindparam("source_item_ids", expanding=True)), {
            "source_item_ids": bounded_ids[1:],
        })
    bounded = client.get(f"/source/{bounded_ids[0]}/context", params={
        "container_ref": CONTAINER, "query_visibility": "private",
        "query_actor_ref": ACTOR, "before": 0, "after": 100,
        "max_chars": 4000,
    })
    assert bounded.status_code == 200, bounded.text
    bounded_payload = bounded.json()
    assert len(bounded_payload["items"]) == 26
    assert bounded_ids[-1] not in {
        item["source_item_id"] for item in bounded_payload["items"]
    }
    assert bounded_payload.get("next_source_item_id") is None

