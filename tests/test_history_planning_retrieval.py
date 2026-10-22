from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.config import AppConfig, ObservabilityConfig
from app.main import create_app
from core.models import IndexEntry, QueryFilters, SourceItem
from storage.sqlite import SQLiteStorageProvider
from storage.vector_index import VectorIndexConfig


def test_source_filter_refills_after_ineligible_lexical_candidates(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    for rank in range(12):
        item = SourceItem(
            source_type="chat",
            source_id=f"automated-noise-{rank}",
            content_type="text/plain",
            content="planning selection priorities cleanup",
            role="user",
            container_ref="container-a",
            thread_ref="session-a",
            visibility="private",
        )
        storage.create_source_item(item)
        storage.create_index_entry(IndexEntry(
            target_kind="source_item",
            target_id=item.id,
            index_type="lexical",
            text_view="planning selection priorities cleanup",
        ))

    target = SourceItem(
        source_type="chat",
        source_id="assistant-plan",
        content_type="text/plain",
        content="planning selection priorities cleanup",
        role="assistant",
        container_ref="container-a",
        thread_ref="session-a",
        visibility="private",
    )
    storage.create_source_item(target)
    storage.create_index_entry(IndexEntry(
        target_kind="source_item",
        target_id=target.id,
        index_type="lexical",
        text_view="planning selection priorities cleanup",
    ))

    hits = storage.search_index_entries(
        ["planning", "selection", "priorities", "cleanup"],
        limit=1,
        filters=QueryFilters(role="assistant"),
        query_container_ref="container-a",
        query_visibility="private",
        target_kind="source_item",
    ).hits

    assert [hit.target_id for hit in hits] == [target.id]


@pytest.mark.parametrize(
    ("filters", "noise_scope"),
    [
        (QueryFilters(role="assistant"), {"role": "user"}),
        (QueryFilters(thread_ref="session-a"), {"thread_ref": "session-b"}),
        (QueryFilters(container_ref="container-a"), {"container_ref": "container-b"}),
    ],
)
def test_source_filters_refill_across_candidate_pages(
    test_db_url: str, filters: QueryFilters, noise_scope: dict[str, str],
) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    for rank in range(3):
        values = {"role": "user", "thread_ref": "session-a", "container_ref": "container-a"}
        values.update(noise_scope)
        item = SourceItem(
            source_type="chat", source_id=f"filtered-noise-{rank}",
            content_type="text/plain", content="scope candidate filler",
            role=values["role"], thread_ref=values["thread_ref"],
            container_ref=values["container_ref"], visibility="private",
        )
        storage.create_source_item(item)
        storage.create_index_entry(IndexEntry(
            target_kind="source_item", target_id=item.id, index_type="lexical",
            text_view="scope candidate filler",
        ))
    eligible = SourceItem(
        source_type="chat", source_id="eligible", content_type="text/plain",
        content="scope candidate filler", role="assistant",
        container_ref="container-a", thread_ref="session-a", visibility="private",
    )
    storage.create_source_item(eligible)
    storage.create_index_entry(IndexEntry(
        target_kind="source_item", target_id=eligible.id, index_type="lexical",
        text_view="scope candidate filler",
    ))

    hits = storage.search_index_entries(
        ["scope", "candidate", "filler"], limit=1, filters=filters,
        query_container_ref="container-a", query_visibility="private",
        target_kind="source_item",
    ).hits
    assert [hit.target_id for hit in hits] == [eligible.id]


def test_source_candidates_exhaust_and_preserve_shared_visibility(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    for rank in range(3):
        item = SourceItem(
            source_type="chat", source_id=f"wrong-role-{rank}",
            content_type="text/plain", content="exhaustion probe",
            role="user", container_ref="container-a", visibility="private",
        )
        storage.create_source_item(item)
        storage.create_index_entry(IndexEntry(
            target_kind="source_item", target_id=item.id, index_type="lexical",
            text_view="exhaustion probe",
        ))
    exhausted = storage.search_index_entries(
        ["exhaustion", "probe"], limit=1,
        filters=QueryFilters(role="assistant"), target_kind="source_item",
    )
    assert exhausted.hits == []

    shared = SourceItem(
        source_type="chat", source_id="shared-public", content_type="text/plain",
        content="shared scope candidate", role="user", container_ref="container-b",
        visibility="public",
    )
    storage.create_source_item(shared)
    storage.create_index_entry(IndexEntry(
        target_kind="source_item", target_id=shared.id, index_type="lexical",
        text_view="shared scope candidate",
    ))
    shared_hits = storage.search_index_entries(
        ["shared", "scope", "candidate"], limit=1,
        filters=QueryFilters(container_ref="container-a"),
        query_container_ref="container-a", query_visibility="private",
        target_kind="source_item",
    ).hits
    assert [hit.target_id for hit in shared_hits] == [shared.id]


def test_source_candidates_refill_after_forgotten_and_invisible_rows(test_db_url: str) -> None:
    from datetime import datetime, timezone

    storage = SQLiteStorageProvider(test_db_url)
    for rank in range(2):
        item = SourceItem(
            source_type="chat", source_id=f"excluded-{rank}",
            content_type="text/plain", content="lifecycle visibility probe",
            role="assistant", container_ref="container-b", visibility="private",
            forgotten_at=datetime.now(timezone.utc) if rank == 0 else None,
        )
        storage.create_source_item(item)
        storage.create_index_entry(IndexEntry(
            target_kind="source_item", target_id=item.id, index_type="lexical",
            text_view="lifecycle visibility probe",
        ))
    eligible = SourceItem(
        source_type="chat", source_id="visible-live", content_type="text/plain",
        content="lifecycle visibility probe", role="assistant",
        container_ref="container-a", visibility="private",
    )
    storage.create_source_item(eligible)
    storage.create_index_entry(IndexEntry(
        target_kind="source_item", target_id=eligible.id, index_type="lexical",
        text_view="lifecycle visibility probe",
    ))

    hits = storage.search_index_entries(
        ["lifecycle", "visibility", "probe"], limit=1,
        query_container_ref="container-a", query_visibility="private",
        target_kind="source_item",
    ).hits
    assert [hit.target_id for hit in hits] == [eligible.id]


@pytest.mark.parametrize(("field", "excluded", "wanted"), [
    ("role", "user", "assistant"),
    ("thread_ref", "session-b", "session-a"),
    ("container_ref", "container-b", "container-a"),
    ("actor_ref", "other", "owner"),
    ("source_type", "external", "chat"),
    ("artifact_kind", "assistant_output", "message"),
])
def test_http_query_refills_past_bounded_lexical_candidate_window(
    test_db_url: str, field: str, excluded: str, wanted: str,
) -> None:
    app = create_app(AppConfig(
        storage_backend="sqlite", sqlite_url=test_db_url,
        default_use_case="demo_agent_memory", semantic_packages={},
        vector_index=VectorIndexConfig(enabled=False),
    ))
    app.state._lifespan_complete = True
    corpus = [
        {
            "source_type": "chat", "source_id": f"window-noise-{rank}",
            "content_type": "text/plain", "content": "bounded candidate query",
            "artifact_kind": "message", "role": "assistant", "actor_ref": "owner",
            "container_ref": "container-a", "thread_ref": "session-a",
            "visibility": "private", field: excluded,
        }
        for rank in range(60)
    ]
    corpus.append({
        "source_type": "chat", "source_id": "window-assistant-target",
        "content_type": "text/plain", "content": "bounded candidate query " + "background context " * 30,
        "artifact_kind": "message", "role": "assistant", "actor_ref": "owner",
        "container_ref": "container-a", "thread_ref": "session-a",
        "visibility": "private",
    })
    with TestClient(app) as client:
        for start in range(0, len(corpus), 50):
            response = client.post("/items", json=corpus[start:start + 50])
            assert response.status_code == 200, response.text
            if start + 50 >= len(corpus):
                target_source_id = response.json()[-1]["source_item_id"]
        query = {
            "text": "bounded candidate query", "limit": 1,
            "source_only": True, "container_ref": "container-a",
            "thread_ref": "session-a", "visibility": "private",
            field: wanted,
        }
        response = client.post("/query", json=query)
        assert response.status_code == 200, response.text
        assert [item["source_item_id"] for item in response.json()["results"]] == [target_source_id]
        assert response.json()["should_inject"] is False
        assert response.json()["injectable_blocks"] == []
        assert client.post("/source/forget", json={"source_item_id": target_source_id, "reason": "test lifecycle"}).status_code == 200
        assert client.post("/query", json=query).json()["results"] == []


def test_source_cursor_deduplicates_views_and_stabilizes_ties(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    ids = []
    for index in range(3):
        item = SourceItem(source_type="chat", source_id=f"tie-{index}", content_type="text/plain",
                          content="stable search", role="assistant", container_ref="container-a", visibility="private")
        storage.create_source_item(item)
        ids.append(item.id)
        for view in range(3):
            storage.create_index_entry(IndexEntry(
                id=f"index-{index}-{view}", target_kind="source_item", target_id=item.id,
                index_type="lexical", text_view="stable search", text_view_name=f"view-{view}",
            ))
    for _ in range(2):
        hits = storage.search_index_entries(["stable", "search"], limit=3,
                                            target_kind="source_item", query_container_ref="container-a", query_visibility="private").hits
        assert [hit.target_id for hit in hits] == ids
        assert [hit.index_entry_id for hit in hits] == [f"index-{index}-0" for index in range(3)]


@pytest.mark.asyncio
async def test_mcp_history_finds_planning_and_expands_qualifying_user_turn(
    test_db_url: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mcp.server import create_server

    app = create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=test_db_url,
        default_use_case="demo_agent_memory",
        semantic_packages={},
        vector_index=VectorIndexConfig(enabled=False),
        observability=ObservabilityConfig(query_audit_log=False),
    ))
    app.state._lifespan_complete = True

    transport = httpx.ASGITransport(app=app)
    real_client = httpx.AsyncClient
    turns = [
        ("user", "Which initial archive rollout priorities can we advance?"),
        ("assistant", "Archive rollout priorities: repair indexing first, validate recovery second, then improve selection UX."),
        ("user", "Agreed, but keep the existing selection visible during editing. 界"),
    ]
    turns.extend(("user", f"<heartbeat>Scheduled reminder {i}: keep driving archive rollout work.</heartbeat>") for i in range(14))
    async with real_client(transport=transport, base_url="http://testserver") as http:
        response = await http.post("/items", json=[{
            "source_type": "chat", "source_id": f"planning-turn-{index}",
            "content_type": "text/plain", "content": content, "artifact_kind": "message",
            "role": role, "container_ref": "container-a", "thread_ref": "past-session",
            "visibility": "private",
        } for index, (role, content) in enumerate(turns)])
        assert response.status_code == 200, response.text
        plan_id = response.json()[1]["source_item_id"]
        acceptance_id = response.json()[2]["source_item_id"]
    app.state.pallium_service.drain_processing_queue(worker_id="planning-history-test")

    def asgi_client(*args, **kwargs):
        kwargs.update(transport=transport, base_url="http://testserver")
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.mcp.client.httpx.AsyncClient", asgi_client)
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://testserver")
    server = create_server()

    async def tool(name, arguments):
        blocks, _ = await server.call_tool(name, arguments)
        return json.loads(blocks[0].text)

    scope = {"container_ref": "container-a", "thread_ref": "reader", "visibility": "private"}
    # Only request-supplied topic anchors, not the answer's ordered item names.
    args = {**scope, "query": "archive rollout priorities", "source_thread_ref": "past-session", "limit": 5}
    result = await tool("pallium_search_history", args)
    delivered = []
    plan_page = None
    while True:
        delivered.extend(result["results"])
        if any(hit["source_item_id"] == plan_id for hit in result["results"]):
            plan_page = result
        if result["next_offset"] is None:
            break
        result = await tool("pallium_search_history", {**args, "result_offset": result["next_offset"], "result_revision": result["result_revision"]})
    assert plan_page is not None
    assert any(hit["source_item_id"] == plan_id for hit in delivered)
    context = await tool("pallium_expand_source", {
        **scope, "source_item_id": plan_id, "before": 1, "after": 1,
        "parent_lookup_id": plan_page["lookup_event_id"],
    })
    assert context["parent_lookup_id"] == plan_page["lookup_event_id"]
    contents = {item["source_item_id"]: item["content"] for item in context["items"]}
    assert contents[plan_id] == turns[1][1]
    assert contents[acceptance_id] == turns[2][1]
    user_only = await tool("pallium_search_history", {**args, "role": "user"})
    assert user_only["results"]
    assert all(hit["source_item_id"] != plan_id for hit in user_only["results"])
    assert all(hit["role"] == "user" for hit in user_only["results"])
