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
            "actor_ref": "actor-1",
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
            },
        )

    payload = json.loads(content[0].text)
    assert payload["search_mode"] == "exact_work_ref"
    assert payload["requested_work_ref"] == "proj-42"
    assert payload["lookup_event_id"] == "finalized"
    assert search.await_args.args[:2] == ("proj-42", None)
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


def test_exact_compaction_drops_cues_before_result_identity() -> None:
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
    rendered = _json_text(compact)

    assert len(rendered) <= 2000
    assert compact["requested_work_ref"] == "proj-1"
    assert [item["source_item_id"] for item in compact["results"]] == [
        "source-0",
        "source-1",
        "source-2",
    ]
    assert any("work_refs" not in item for item in compact["results"])



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
