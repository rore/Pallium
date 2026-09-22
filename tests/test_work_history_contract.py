from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from api.schemas import QueryRequest
from app.mcp.client import PalliumMcpClient
from app.mcp.context import PalliumContext
from app.mcp.server import _compact_history, _json_text, create_server


def _create_server():
    pytest.importorskip("mcp", reason="mcp[cli] not installed")
    return create_server()


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "", "source_only": True, "trigger_origin": "agent_pull"},
        {"text": "   ", "source_only": False},
    ],
)
def test_broad_blank_stays_rejected(payload: dict) -> None:
    with pytest.raises(ValidationError):
        QueryRequest(**payload)


def test_exact_blank_and_public_result_limit_boundaries() -> None:
    QueryRequest(
        text="  ",
        source_only=True,
        trigger_origin="agent_pull_work",
        work_refs=["Proj 42"],
        limit=50,
    )
    with pytest.raises(ValidationError):
        QueryRequest(
            text="",
            source_only=True,
            trigger_origin="agent_pull_work",
            work_refs=["proj-42"],
            limit=51,
        )


@pytest.mark.asyncio
async def test_exact_client_uses_existing_source_only_query_funnel() -> None:
    client = PalliumMcpClient(
        PalliumContext(
            base_url="http://testserver",
            container_ref="git:example/repo",
            thread_ref="session-1",
            actor_ref="actor-1",
            visibility="private",
        )
    )
    captured: dict = {}

    async def capture(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"results": []}

    client._post = capture
    await client.search_history_by_work_ref(
        "proj-42",
        "任务",
        limit=7,
        request_source_item_id="request-1",
        defer_delivery=True,
    )

    assert captured == {
        "path": "/query",
        "payload": {
            "text": "任务",
            "limit": 7,
            "source_only": True,
            "trigger_origin": "agent_pull_work",
            "defer_delivery": True,
            "work_refs": ["proj-42"],
            "container_ref": "git:example/repo",
            "thread_ref": "session-1",
            "visibility": "private",
            "request_source_item_id": "request-1",
        },
    }


@pytest.mark.asyncio
async def test_tool_schema_and_descriptions_distinguish_exact_from_broad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    tools = await _create_server().list_tools()
    exact = next(t for t in tools if t.name == "pallium_search_history_by_work_ref")
    broad = next(t for t in tools if t.name == "pallium_search_history")

    assert "work_ref" in exact.inputSchema["required"]
    assert exact.inputSchema["properties"]["query"].get("default") is None
    assert "narrow exact-reference search" in exact.description
    assert "can miss related work" in exact.description
    assert "broad topic-level search" in exact.description
    assert "compatibility-only" in broad.description
    assert "cannot prove messages were received or sent" in broad.description
    assert "work_refs" in broad.inputSchema["properties"]
    assert "actor_ref" not in exact.inputSchema.get("required", [])
    assert "actor_ref" not in broad.inputSchema.get("required", [])
    for tool in (exact, broad):
        properties = tool.inputSchema["properties"]
        assert properties["limit"]["minimum"] == 1
        assert properties["limit"]["maximum"] == 50
        assert properties["result_offset"]["minimum"] == 0
        assert "result_revision" in properties
        assert "next_offset" in tool.description
        assert "result_revision" in tool.description
    assert "exact metadata filter" in exact.description
    assert "exact metadata filter" in broad.description


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "work_ref",
    [
        {"value": "secret-bearing-wrong-type"},
        ["ghp_" + "secret-bearing-wrong-type", {"nested": "secret"}],
    ],
)
async def test_exact_tool_rejects_secret_bearing_wrong_types_without_echo(
    monkeypatch: pytest.MonkeyPatch, work_ref
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    try:
        content, _ = await _create_server().call_tool(
            "pallium_search_history_by_work_ref",
            {"work_ref": work_ref, "container_ref": "c", "visibility": "private"},
        )
        rendered = content[0].text
    except Exception as exc:  # FastMCP may reject tool args before invocation.
        rendered = str(exc)
    assert "secret-bearing-wrong-type" not in rendered
    assert "nested" not in rendered

@pytest.mark.asyncio
async def test_exact_tool_finalizes_only_compacted_hits_and_normalizes_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    raw = {
        "results": [
            {"source_item_id": "kept", "excerpt": "x"},
            {"source_item_id": "dropped", "excerpt": "y"},
        ],
        "delivery_attempt_id": "attempt",
    }
    receipt = AsyncMock(return_value={"lookup_event_id": "finalized"})
    with (
        patch(
            "app.mcp.client.PalliumMcpClient.search_history_by_work_ref",
            new=AsyncMock(return_value=raw),
        ) as search,
        patch(
            "app.mcp.client.PalliumMcpClient.finalize_historical_delivery",
            new=receipt,
        ),
    ):
        content, _ = await _create_server().call_tool(
            "pallium_search_history_by_work_ref",
            {
                "work_ref": "PROJ 42",
                "limit": 1,
                "container_ref": "c",
                "visibility": "private",
                "actor_ref": "工具乙",
            },
        )

    payload = json.loads(content[0].text)
    assert payload["search_mode"] == "exact_work_ref"
    assert payload["requested_work_ref"] == "proj-42"
    assert payload["lookup_event_id"] == "finalized"
    assert search.await_args.args[:2] == ("proj-42", None)
    assert search.await_args.kwargs["actor_ref"] == "工具乙"
    assert receipt.await_args.kwargs["items"] == [
        {"source_item_id": "kept", "role": "search_match"}
    ]


@pytest.mark.asyncio
async def test_exact_tool_errors_are_visible_bounded_and_do_not_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    finalize = AsyncMock()
    with patch(
        "app.mcp.client.PalliumMcpClient.finalize_historical_delivery",
        new=finalize,
    ):
        for bad_ref in ("---", "x" * 129, "bad\x00secret"):
            content, _ = await _create_server().call_tool(
                "pallium_search_history_by_work_ref",
                {
                    "work_ref": bad_ref,
                    "container_ref": "c",
                    "visibility": "private",
                },
            )
            assert bad_ref not in content[0].text
            assert len(content[0].text) <= 300
            assert json.loads(content[0].text)["error"] == (
                "work_ref must be one valid identifier"
            )
    finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_exact_tool_surfaces_request_and_finalize_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    request_error = {
        "error": "Client error",
        "detail": {"detail": "request_source_item_id must reference a live request"},
    }
    with patch(
        "app.mcp.client.PalliumMcpClient.search_history_by_work_ref",
        new=AsyncMock(return_value=request_error),
    ):
        content, _ = await _create_server().call_tool(
            "pallium_search_history_by_work_ref",
            {
                "work_ref": "proj-1",
                "request_source_item_id": "missing",
                "container_ref": "c",
                "visibility": "private",
            },
        )
    assert json.loads(content[0].text)["detail"] == request_error["detail"]

    with (
        patch(
            "app.mcp.client.PalliumMcpClient.search_history_by_work_ref",
            new=AsyncMock(
                return_value={
                    "results": [],
                    "delivery_attempt_id": "attempt",
                    "decision_reason": "source_only_search",
                }
            ),
        ),
        patch(
            "app.mcp.client.PalliumMcpClient.finalize_historical_delivery",
            new=AsyncMock(return_value={"error": "finalization failed"}),
        ),
    ):
        content, _ = await _create_server().call_tool(
            "pallium_search_history_by_work_ref",
            {
                "work_ref": "proj-1",
                "container_ref": "c",
                "visibility": "private",
            },
        )
    assert json.loads(content[0].text) == {"error": "finalization failed"}


def test_exact_compaction_preserves_result_identity_across_pages() -> None:
    refs = [f"work-{i}-" + ("x" * 120) for i in range(5)]
    result = {
        "results": [
            {
                "source_item_id": f"source-{i}",
                "excerpt": "界" * 2000,
                "thread_ref": f"thread-{i}",
                "work_refs": refs,
            }
            for i in range(3)
        ],
        "lookup_event_id": "lookup-1",
    }
    compact = _compact_history(
        result,
        "界",
        limit=3,
        thread_ref="active-thread",
        search_mode="exact_work_ref",
        requested_work_ref="proj-1",
    )
    seen = []
    while True:
        rendered = _json_text(compact)
        assert len(rendered) <= 2000
        assert compact["requested_work_ref"] == "proj-1"
        seen.extend(item["source_item_id"] for item in compact["results"])
        if compact["next_offset"] is None:
            break
        compact = _compact_history(
            result,
            "界",
            limit=3,
            thread_ref="active-thread",
            search_mode="exact_work_ref",
            requested_work_ref="proj-1",
            result_offset=compact["next_offset"],
            result_revision=compact["result_revision"],
        )

    assert seen == ["source-0", "source-1", "source-2"]



@pytest.mark.asyncio
async def test_exact_empty_deferred_result_reserves_final_lookup_uuid_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    final_id = "12345678-1234-1234-1234-123456789012"
    with (
        patch(
            "app.mcp.client.PalliumMcpClient.search_history_by_work_ref",
            new=AsyncMock(return_value={
                "results": [],
                "delivery_attempt_id": "attempt",
                "decision_reason": "source_only_search",
            }),
        ),
        patch(
            "app.mcp.client.PalliumMcpClient.finalize_historical_delivery",
            new=AsyncMock(return_value={"lookup_event_id": final_id}),
        ),
    ):
        content, _ = await _create_server().call_tool(
            "pallium_search_history_by_work_ref",
            {
                "work_ref": "x" * 128,
                "container_ref": "c" * 1000,
                "visibility": "private",
            },
        )

    payload = json.loads(content[0].text)
    assert "requested_work_ref" not in payload
    assert payload["lookup_event_id"] == final_id
    assert "use broad search" in payload["empty_result_hint"]
    assert "never guess" in payload["empty_result_hint"]
    assert len(content[0].text) <= 300


@pytest.mark.asyncio
async def test_exact_client_omits_context_actor_for_blank_query() -> None:
    client = PalliumMcpClient(PalliumContext(
        base_url="http://testserver",
        container_ref="git:example/repo",
        thread_ref="session-1",
        actor_ref="工具甲",
        visibility="private",
    ))
    captured: dict = {}

    async def capture(path, payload):
        captured["payload"] = payload
        return {"results": []}

    client._post = capture
    await client.search_history_by_work_ref("proj-42")
    assert captured["payload"]["text"] == ""
    assert "actor_ref" not in captured["payload"]


@pytest.mark.asyncio
async def test_exact_client_sends_explicit_unicode_actor_for_nonblank_query() -> None:
    client = PalliumMcpClient(PalliumContext(
        base_url="http://testserver",
        container_ref="git:example/repo",
        thread_ref="session-1",
        actor_ref="ambient-actor",
        visibility="private",
    ))
    captured: dict = {}

    async def capture(path, payload):
        captured["payload"] = payload
        return {"results": []}

    client._post = capture
    await client.search_history_by_work_ref("proj-42", "任务", actor_ref="工具乙")
    assert captured["payload"]["actor_ref"] == "工具乙"

@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name, search_method, tool_args", [
    ("pallium_search_history", "search_history", {"query": "evidence"}),
    ("pallium_search_history_by_work_ref", "search_history_by_work_ref", {"work_ref": "proj-1", "query": "evidence"}),
])
@pytest.mark.parametrize("paging_args, error_kind", [
    ({"limit": 0}, "greater than or equal to 1"),
    ({"limit": 51}, "less than or equal to 50"),
    ({"limit": True}, "valid integer"),
    ({"limit": 1.5}, "valid integer"),
    ({"result_offset": -1}, "greater than or equal to 0"),
    ({"result_offset": True}, "valid integer"),
    ({"result_offset": 1}, "result_revision_required"),
    ({"result_revision": "A" * 64}, "invalid_result_revision"),
    ({"result_revision": "0" * 63}, "invalid_result_revision"),
])
async def test_history_paging_validation_happens_before_http(
    monkeypatch: pytest.MonkeyPatch, tool_name: str, search_method: str,
    tool_args: dict, paging_args: dict, error_kind: str,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    search = AsyncMock()
    try:
        with patch.object(PalliumMcpClient, search_method, new=search):
            content, _ = await _create_server().call_tool(
                tool_name,
                {**tool_args, **paging_args, "container_ref": "c", "visibility": "private"},
            )
        rendered = content[0].text
    except Exception as exc:
        rendered = str(exc)
    assert error_kind in rendered
    search.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name, search_method, tool_args", [
    ("pallium_search_history", "search_history", {"query": "evidence"}),
    ("pallium_search_history_by_work_ref", "search_history_by_work_ref", {"work_ref": "proj-1", "query": "evidence"}),
])
async def test_stale_history_revision_does_not_finalize(
    monkeypatch: pytest.MonkeyPatch, tool_name: str, search_method: str, tool_args: dict,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    search = AsyncMock(return_value={
        "results": [{"source_item_id": "a", "excerpt": "evidence"}],
        "delivery_attempt_id": "attempt",
    })
    finalize = AsyncMock()
    with (
        patch.object(PalliumMcpClient, search_method, new=search),
        patch.object(PalliumMcpClient, "finalize_historical_delivery", new=finalize),
    ):
        content, _ = await _create_server().call_tool(
            tool_name,
            {**tool_args, "result_offset": 1, "result_revision": "0" * 64,
             "container_ref": "c", "visibility": "private"},
        )
    assert json.loads(content[0].text)["error"] == "history_result_revision_stale"
    finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_history_page_finalizes_only_subset_and_terminal_page_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    result = {
        "results": [
            {"source_item_id": f"item-{index}", "excerpt": "evidence " * 80}
            for index in range(50)
        ],
        "delivery_attempt_id": "attempt",
    }
    search = AsyncMock(return_value=result)
    finalize = AsyncMock(side_effect=[
        {"lookup_event_id": "lookup-first"}, {"lookup_event_id": "lookup-terminal"},
    ])
    with (
        patch.object(PalliumMcpClient, "search_history", new=search),
        patch.object(PalliumMcpClient, "finalize_historical_delivery", new=finalize),
    ):
        server = _create_server()
        first_content, _ = await server.call_tool(
            "pallium_search_history",
            {"query": "evidence", "limit": 50, "container_ref": "c", "visibility": "private"},
        )
        first = json.loads(first_content[0].text)
        assert first["has_more"] is True
        terminal_content, _ = await server.call_tool(
            "pallium_search_history",
            {"query": "evidence", "limit": 50, "result_offset": first["total_count"],
             "result_revision": first["result_revision"], "container_ref": "c", "visibility": "private"},
        )
    terminal = json.loads(terminal_content[0].text)
    assert terminal["results"] == []
    assert terminal["next_offset"] is None
    assert finalize.await_count == 2
    assert finalize.await_args_list[0].kwargs["items"] == [
        {"source_item_id": item["source_item_id"], "role": "search_match"}
        for item in first["results"]
    ]
    assert finalize.await_args_list[1].kwargs["items"] == []


@pytest.mark.asyncio
async def test_history_retry_mints_fresh_lookup_id_without_changing_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    search = AsyncMock(return_value={
        "results": [{"source_item_id": "item-1", "excerpt": "evidence"}],
        "delivery_attempt_id": "attempt",
    })
    finalize = AsyncMock(side_effect=[
        {"lookup_event_id": "lookup-first"}, {"lookup_event_id": "lookup-retry"},
    ])
    with (
        patch.object(PalliumMcpClient, "search_history", new=search),
        patch.object(PalliumMcpClient, "finalize_historical_delivery", new=finalize),
    ):
        server = _create_server()
        first_content, _ = await server.call_tool(
            "pallium_search_history",
            {"query": "evidence", "container_ref": "c", "visibility": "private"},
        )
        retry_content, _ = await server.call_tool(
            "pallium_search_history",
            {"query": "evidence", "container_ref": "c", "visibility": "private"},
        )
    first = json.loads(first_content[0].text)
    retry = json.loads(retry_content[0].text)
    assert first["lookup_event_id"] != retry["lookup_event_id"]
    first.pop("lookup_event_id")
    retry.pop("lookup_event_id")
    assert first == retry
    assert finalize.await_count == 2
@pytest.mark.asyncio
async def test_history_request_change_stales_at_offset_zero_without_finalizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    search = AsyncMock(return_value={
        "results": [{"source_item_id": "item-1", "excerpt": "evidence"}],
        "delivery_attempt_id": "attempt",
    })
    finalize = AsyncMock(return_value={"lookup_event_id": "lookup-first"})
    with (
        patch.object(PalliumMcpClient, "search_history", new=search),
        patch.object(PalliumMcpClient, "finalize_historical_delivery", new=finalize),
    ):
        server = _create_server()
        first_content, _ = await server.call_tool(
            "pallium_search_history",
            {"query": "first", "container_ref": "c", "visibility": "private"},
        )
        first = json.loads(first_content[0].text)
        stale_content, _ = await server.call_tool(
            "pallium_search_history",
            {
                "query": "second",
                "result_revision": first["result_revision"],
                "container_ref": "c",
                "visibility": "private",
            },
        )

    assert json.loads(stale_content[0].text)["error_kind"] == "stale_result_revision"
    assert finalize.await_count == 1


@pytest.mark.asyncio
async def test_history_later_page_retry_is_stable_with_fresh_lookup_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    search = AsyncMock(return_value={
        "results": [
            {"source_item_id": f"item-{index}", "excerpt": "evidence " * 80}
            for index in range(10)
        ],
        "delivery_attempt_id": "attempt",
    })
    finalize = AsyncMock(side_effect=[
        {"lookup_event_id": "lookup-first"},
        {"lookup_event_id": "lookup-later"},
        {"lookup_event_id": "lookup-later-retry"},
    ])
    with (
        patch.object(PalliumMcpClient, "search_history", new=search),
        patch.object(PalliumMcpClient, "finalize_historical_delivery", new=finalize),
    ):
        server = _create_server()
        first_content, _ = await server.call_tool(
            "pallium_search_history",
            {
                "query": "evidence",
                "limit": 10,
                "container_ref": "c",
                "visibility": "private",
            },
        )
        first = json.loads(first_content[0].text)
        continuation = {
            "query": "evidence",
            "limit": 10,
            "result_offset": first["next_offset"],
            "result_revision": first["result_revision"],
            "container_ref": "c",
            "visibility": "private",
        }
        later_content, _ = await server.call_tool("pallium_search_history", continuation)
        retry_content, _ = await server.call_tool("pallium_search_history", continuation)

    later = json.loads(later_content[0].text)
    retry = json.loads(retry_content[0].text)
    assert later["lookup_event_id"] != retry["lookup_event_id"]
    later.pop("lookup_event_id")
    retry.pop("lookup_event_id")
    assert later == retry
    assert finalize.await_args_list[1].kwargs["items"] == finalize.await_args_list[2].kwargs["items"]


@pytest.mark.asyncio
async def test_equal_length_visible_change_stales_without_finalizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    search = AsyncMock(side_effect=[
        {
            "results": [{"source_item_id": "same", "excerpt": "alpha"}],
            "delivery_attempt_id": "attempt-first",
        },
        {
            "results": [{"source_item_id": "same", "excerpt": "bravo"}],
            "delivery_attempt_id": "attempt-changed",
        },
    ])
    finalize = AsyncMock(return_value={"lookup_event_id": "lookup-first"})
    with (
        patch.object(PalliumMcpClient, "search_history", new=search),
        patch.object(PalliumMcpClient, "finalize_historical_delivery", new=finalize),
    ):
        server = _create_server()
        first_content, _ = await server.call_tool(
            "pallium_search_history",
            {"query": "evidence", "container_ref": "c", "visibility": "private"},
        )
        first = json.loads(first_content[0].text)
        stale_content, _ = await server.call_tool(
            "pallium_search_history",
            {
                "query": "evidence",
                "result_revision": first["result_revision"],
                "container_ref": "c",
                "visibility": "private",
            },
        )

    assert json.loads(stale_content[0].text)["error_kind"] == "stale_result_revision"
    assert finalize.await_count == 1
