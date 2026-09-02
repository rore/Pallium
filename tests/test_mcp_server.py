"""Tests for MCP server tool registration and self-gating."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("mcp", reason="mcp[cli] not installed")

from app.mcp import server as mcp_server
from app.mcp.server import _bounded_expansion, _compact_history, _json_text, _trim_update_details, create_server


class TestSelfGating:
    @pytest.mark.asyncio
    async def test_query_returns_not_configured_when_no_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PALLIUM_BASE_URL", raising=False)
        server = create_server()
        tools = await server.list_tools()
        tool_names = [t.name for t in tools]
        assert "pallium_query" in tool_names

        content_list, _ = await server.call_tool("pallium_query", {"query": "test"})
        text = content_list[0].text
        assert "not configured" in text.lower()

    @pytest.mark.asyncio
    async def test_ingest_returns_not_configured_when_no_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PALLIUM_BASE_URL", raising=False)
        server = create_server()
        content_list, _ = await server.call_tool("pallium_ingest", {"content": "test"})
        text = content_list[0].text
        assert "not configured" in text.lower()

    @pytest.mark.asyncio
    async def test_query_debug_returns_not_configured_when_no_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PALLIUM_BASE_URL", raising=False)
        server = create_server()
        content_list, _ = await server.call_tool("pallium_query_debug", {"query": "test"})
        text = content_list[0].text
        assert "not configured" in text.lower()


    @pytest.mark.asyncio
    async def test_status_returns_not_configured_when_no_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PALLIUM_BASE_URL", raising=False)
        server = create_server()
        content_list, _ = await server.call_tool("pallium_status", {})
        text = content_list[0].text
        assert "not configured" in text.lower()


class TestToolsWithMockedClient:
    @pytest.mark.asyncio
    async def test_query_passes_through_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        expected = {"results": [{"score": 0.9}], "should_inject": True, "decision_reason": "carry_forward_available"}

        with patch("app.mcp.client.PalliumMcpClient.query", new_callable=AsyncMock, return_value=expected):
            server = create_server()
            content_list, _ = await server.call_tool("pallium_query", {"query": "test decision"})
            text = content_list[0].text
            parsed = json.loads(text)
            assert parsed == expected

    @pytest.mark.asyncio
    async def test_query_debug_passes_through_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        expected = {"results": [], "trace": {"stages": []}, "should_inject": False, "decision_reason": "no_relevant_memory"}

        with patch("app.mcp.client.PalliumMcpClient.query_debug", new_callable=AsyncMock, return_value=expected):
            server = create_server()
            content_list, _ = await server.call_tool("pallium_query_debug", {"query": "test"})
            text = content_list[0].text
            parsed = json.loads(text)
            assert parsed == expected

    @pytest.mark.asyncio
    async def test_ingest_passes_through_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        expected = {"source_item_id": "si-123", "processing_status": "pending"}

        with patch("app.mcp.client.PalliumMcpClient.ingest", new_callable=AsyncMock, return_value=expected):
            server = create_server()
            content_list, _ = await server.call_tool("pallium_ingest", {"content": "remember this"})
            text = content_list[0].text
            parsed = json.loads(text)
            assert parsed == expected

    @pytest.mark.asyncio
    async def test_status_passes_through_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        expected = {"pending_items": 0, "query": {"total_queries": 5}}

        with patch("app.mcp.client.PalliumMcpClient.get_status", new_callable=AsyncMock, return_value=expected):
            server = create_server()
            content_list, _ = await server.call_tool("pallium_status", {})
            text = content_list[0].text
            parsed = json.loads(text)
            assert parsed == expected

    @pytest.mark.asyncio
    async def test_query_scope_override_resolved_in_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Scope overrides are resolved by the server into context, not passed to client."""
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        monkeypatch.setenv("PALLIUM_CONTAINER_REF", "env-container")

        with patch("app.mcp.client.PalliumMcpClient.__init__", return_value=None) as mock_init, \
             patch("app.mcp.client.PalliumMcpClient.query", new_callable=AsyncMock, return_value={"results": []}):
            server = create_server()
            await server.call_tool("pallium_query", {
                "query": "test",
                "container_ref": "override-container",
            })
            # The client should receive a context with the override applied
            ctx_arg = mock_init.call_args.args[0]
            assert ctx_arg.container_ref == "override-container"


class TestBoundedErrorSurface:
    """Verify that oversized error responses are bounded through the full MCP tools/call path."""

    @pytest.mark.asyncio
    async def test_relay_send_422_bounded_with_status_code_and_sibling_fields_preserved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """tools/call pallium_relay_send with oversized 422: bounded output, status_code kept, input stripped, sibling metadata preserved."""
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")

        oversized_422 = {
            "error": "Client error '422 Unprocessable Content'",
            "status_code": 422,
            "detail": {
                "detail": [
                    {
                        "type": "string_too_long",
                        "loc": ["body", "payload"],
                        "msg": "String should have at most 1500 characters",
                        "input": "x" * 2000,
                        "url": "https://example.com",
                    }
                ],
                "metadata": {"request_id": "abc123"},
            },
        }

        server = create_server()
        with patch("app.mcp.client.PalliumMcpClient.relay_send", new_callable=AsyncMock, return_value=oversized_422):
            content_list, _ = await server.call_tool(
                "pallium_relay_send",
                {
                    "message": "test",
                    "recipient": "codex:@relayarch",
                    "sender_runtime": "claude-code",
                    "sender_session_ref": "test-session",
                    "container_ref": "git:example.com/test/repo",
                    "actor_ref": "test-actor",
                },
            )

        out = json.loads(content_list[0].text)
        assert len(content_list[0].text) <= 2000
        assert out["status_code"] == 422
        assert "input" not in out["detail"]["detail"][0]
        assert "url" not in out["detail"]["detail"][0]
        assert out["detail"]["metadata"] == {"request_id": "abc123"}
        assert out["detail"]["detail"][0]["msg"] == "String should have at most 1500 characters"


class TestToolDescriptions:
    @pytest.mark.asyncio
    async def test_expected_tools_are_registered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        server = create_server()
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}
        # Subset assertion (not exact-set): future tool additions must not
        # re-break this. Includes the P1 historical-lookup tools.
        expected = {
            "pallium_query",
            "pallium_query_debug",
            "pallium_ingest",
            "pallium_expand",
            "pallium_flag_memory",
            "pallium_status",
            "pallium_rate_memory",
            "pallium_search_history",
            "pallium_expand_source",
        }
        assert expected <= tool_names


@pytest.mark.asyncio
async def test_forget_source_tool_forwards_identity_free_single_and_bulk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    calls: list[dict] = []

    async def fake_forget_source(**kwargs):
        calls.append(kwargs)
        return {"forgotten": True, "count": 1}

    with patch(
        "app.mcp.client.PalliumMcpClient.forget_source",
        new=AsyncMock(side_effect=fake_forget_source),
    ):
        server = create_server()
        await server.call_tool(
            "pallium_forget_source",
            {"source_item_id": "s-1", "reason": "r"},
        )
        await server.call_tool(
            "pallium_forget_source",
            {"thread_ref": "t-1", "reason": "r"},
        )

    assert calls == [
        {"source_item_id": "s-1", "thread_ref": None, "reason": "r"},
        {"source_item_id": None, "thread_ref": "t-1", "reason": "r"},
    ]


@pytest.mark.asyncio
async def test_expand_source_tool_forwards_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    captured: dict[str, str] = {}

    async def fake_get_source_context(source_item_id: str, **kwargs):
        captured["source_item_id"] = source_item_id
        return {"items": []}

    with (
        patch("app.mcp.client.PalliumMcpClient.__init__", return_value=None) as init,
        patch(
            "app.mcp.client.PalliumMcpClient.get_source_context",
            new=AsyncMock(side_effect=fake_get_source_context),
        ),
    ):
        server = create_server()
        await server.call_tool(
            "pallium_expand_source",
            {"source_item_id": "s-1", "visibility": "public"},
        )

    assert init.call_args.args[0].visibility == "public"
    assert captured == {"source_item_id": "s-1"}

@pytest.mark.asyncio
async def test_historical_search_empty_echoes_exact_requested_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    raw = {
        "results": [],
        "lookup_event_id": "lookup-empty",
        "decision_reason": "source_only_search",
    }
    search_mock = AsyncMock(return_value=raw)
    with patch(
        "app.mcp.client.PalliumMcpClient.search_history",
        new=search_mock,
    ):
        server = create_server()
        content, _ = await server.call_tool("pallium_search_history", {
            "query": "missing",
            "container_ref": "git:example.com/example/repository",
            "thread_ref": "任务:1",
            "visibility": "private",
            "request_source_item_id": "请求:42",
        })

    assert search_mock.await_args.kwargs["request_source_item_id"] == "请求:42"
    payload = json.loads(content[0].text)
    assert payload["requested_container_ref"] == "git:example.com/example/repository"
    assert "exact" in payload["empty_result_hint"]
    assert len(content[0].text) <= 300


@pytest.mark.asyncio
async def test_historical_search_keeps_request_link_validation_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    detail = "request_source_item_id must reference a live user request in the same scope"
    with patch(
        "app.mcp.client.PalliumMcpClient.search_history",
        new=AsyncMock(return_value={
            "error": "Client error '422 Unprocessable Entity'",
            "detail": {"detail": detail},
        }),
    ):
        server = create_server()
        content, _ = await server.call_tool("pallium_search_history", {
            "query": "prior work",
            "container_ref": "git:example/repo",
            "thread_ref": "task:1",
            "actor_ref": "actor:1",
            "visibility": "private",
            "request_source_item_id": "missing",
        })

    payload = json.loads(content[0].text)
    assert payload["detail"] == {"detail": detail}


@pytest.mark.asyncio
async def test_historical_tools_project_bounded_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    raw = {"results": [{"result_kind": "source_hit", "source_item_id": "s1", "excerpt": "prefix match middle suffix", "role": None, "occurred_at": None, "score": 99}], "lookup_event_id": "lookup-1"}
    expansion = {"items": [{"source_item_id": "s1", "is_anchor": True, "content": "anchor content"}], "supported_memories": None, "parent_lookup_id": "lookup-1"}
    with patch("app.mcp.client.PalliumMcpClient.search_history", new=AsyncMock(return_value=raw)), patch("app.mcp.client.PalliumMcpClient.get_source_context", new=AsyncMock(return_value=expansion)):
        server = create_server()
        search, _ = await server.call_tool("pallium_search_history", {"query": "match"})
        expanded, _ = await server.call_tool("pallium_expand_source", {"source_item_id": "s1", "parent_lookup_id": "lookup-1"})
    search_text, expand_text = search[0].text, expanded[0].text
    assert len(search_text) <= 2000
    assert "score" not in search_text and "role" not in search_text and "occurred_at" not in search_text
    assert len(expand_text) <= 4000
    assert "s1" in expand_text and "lookup-1" in expand_text
@pytest.mark.asyncio
async def test_historical_search_compacts_unicode_and_omits_null_optionals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    raw = {
        "results": [
            {
                "result_kind": "source_hit",
                "source_item_id": "unicode-1",
                "excerpt": "quoted \\\"line\\\" \\ path\nעברית 中文 😀 match middle",
                "role": None,
                "occurred_at": None,
                "score": 9,
            }
        ],
        "lookup_event_id": "lookup-unicode",
    }
    with patch(
        "app.mcp.client.PalliumMcpClient.search_history",
        new=AsyncMock(return_value=raw),
    ):
        server = create_server()
        content, _ = await server.call_tool(
            "pallium_search_history", {"query": "match"}
        )

    payload = json.loads(content[0].text)
    assert len(content[0].text) <= 2000
    assert payload["results"][0]["source_item_id"] == "unicode-1"
    assert "role" not in payload["results"][0]
    assert "occurred_at" not in payload["results"][0]
    assert "\\\"" in payload["results"][0]["excerpt"]
    assert "😀" in payload["results"][0]["excerpt"]


@pytest.mark.asyncio
async def test_historical_expansion_reports_small_budget_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    expansion = {
        "items": [
            {
                "source_item_id": "anchor-1",
                "is_anchor": True,
                "content": "anchor content",
            }
        ],
        "supported_memories": None,
        "parent_lookup_id": "lookup-1",
    }
    with patch(
        "app.mcp.client.PalliumMcpClient.get_source_context",
        new=AsyncMock(return_value=expansion),
    ):
        server = create_server()
        content, _ = await server.call_tool(
            "pallium_expand_source",
            {"source_item_id": "anchor-1", "max_chars": 1},
        )

    payload = json.loads(content[0].text)
    assert len(content[0].text) <= 4000
    assert payload["error"] == "max_chars is too small for the expansion anchor"
    assert payload["min_max_chars"] == 256

def test_compact_history_defaults_to_three_hits_and_bounds_escaped_json() -> None:
    result = _compact_history({
        "results": [
            {"source_item_id": f"s-{i}", "excerpt": ('\\"' * 1500) + "needle"}
            for i in range(8)
        ],
        "lookup_event_id": "lookup-1",
    }, "needle")
    assert len(result["results"]) <= 3
    assert len(_json_text(result)) <= 2000
    assert result["lookup_event_id"] == "lookup-1"
    assert "empty_result_hint" not in result


def test_compact_history_preserves_decision_reason_on_empty_fail_closed() -> None:
    # search_history routes through _compact_history; an empty fail-closed
    # result must still tell the caller WHY (not a silent []).
    result = _compact_history({
        "results": [],
        "lookup_event_id": None,
        "decision_reason": "visibility_context_required",
    }, "needle")
    assert result["results"] == []
    assert result["decision_reason"] == "visibility_context_required"


def test_compact_history_preserves_recorded_date_and_replacement_status() -> None:
    result = _compact_history({
        "results": [{
            "source_item_id": "source-1",
            "excerpt": "The old rollout used the staging endpoint.",
            "recorded_at": "2026-08-20T10:00:00+00:00",
            "recorded_at_source": "event",
            "historical_updates": [{
                "outdated_memory_object_id": "old-memory",
                "memory_type": "decision",
                "status": "outdated",
                "replacement_status": "current",
                "current_memory_object_id": "new-memory",
                "current_text": "Use the production endpoint.",
                "current_recorded_at": "2026-08-21T10:00:00+00:00",
            }],
        }],
        "lookup_event_id": "lookup-1",
    }, "endpoint")

    hit = result["results"][0]
    assert hit["recorded_at"] == "2026-08-20T10:00:00+00:00"
    assert hit["recorded_at_source"] == "event"
    assert hit["historical_updates"][0]["replacement_status"] == "current"
    assert hit["historical_updates"][0]["current_memory_object_id"] == "new-memory"
    assert hit["historical_updates"][0]["current_text"] == "Use the production endpoint."
    assert len(_json_text(result)) <= 2000


def test_budget_trimming_keeps_current_replacement_before_unavailable() -> None:
    current = {"status": "outdated", "replacement_status": "current", "current_memory_object_id": "new"}
    unavailable = {"status": "outdated", "replacement_status": "unavailable"}
    item = {"historical_updates": [current, unavailable]}
    payload = {"results": [item]}
    expected = {"results": [{"historical_updates": [current], "historical_updates_omitted": 1}]}
    budget = len(_json_text(expected))

    _trim_update_details(payload, [item], budget)

    assert item["historical_updates"] == [current]
    assert item["historical_updates_omitted"] == 1
    assert len(_json_text(payload)) <= budget


def test_bounded_expansion_preserves_historical_updates_within_budget() -> None:
    result = _bounded_expansion({
        "items": [{
            "source_item_id": "anchor",
            "is_anchor": True,
            "content": "The old rollout used the staging endpoint.",
            "recorded_at": "2026-08-20T10:00:00+00:00",
            "recorded_at_source": "ingest",
            "historical_updates": [{
                "outdated_memory_object_id": "old-memory",
                "memory_type": "decision",
                "status": "outdated",
                "replacement_status": "unavailable",
            }],
        }],
        "supported_memories": None,
        "parent_lookup_id": "lookup-1",
    }, 700)

    assert len(_json_text(result)) <= 700
    item = result["items"][0]
    assert item["recorded_at_source"] == "ingest"
    assert item["historical_updates"][0]["status"] == "outdated"


def test_compact_history_trims_unicode_without_dropping_stale_status() -> None:
    result = _compact_history({
        "results": [{
            "source_item_id": "unicode-source",
            "excerpt": "界" * 5000,
            "recorded_at": "2026-08-20T10:00:00+00:00",
            "historical_updates": [{
                "memory_type": "decision",
                "status": "outdated",
                "replacement_status": "current",
                "current_text": "更新" * 5000,
            }],
        }],
        "lookup_event_id": "lookup-unicode",
    }, "界")

    assert len(_json_text(result)) <= 2000
    assert len(result["results"]) == 1
    assert result["results"][0]["historical_updates"][0]["status"] == "outdated"
    assert result["results"][0]["historical_updates"][0]["current_text_truncated"] is True

def test_compact_history_explains_empty_requested_scope_within_budget() -> None:
    result = _compact_history({
        "results": [],
        "lookup_event_id": "lookup-1",
        "decision_reason": "source_only_search",
    }, "needle", container_ref="git:github.com/rore/pallium")

    assert result["requested_container_ref"] == "git:github.com/rore/pallium"
    assert "exact" in result["empty_result_hint"]
    assert len(_json_text(result)) <= 300


def test_compact_history_truncates_oversized_requested_scope_within_budget() -> None:
    result = _compact_history({
        "results": [],
        "lookup_event_id": None,
        "decision_reason": "source_only_search",
    }, "needle", container_ref="x" * 1000)

    assert result["requested_container_ref"] == "x" * 64
    assert result["container_ref_truncated"] is True
    assert len(_json_text(result)) <= 300


def test_bounded_expansion_clips_anchor_and_flags_every_clipped_item() -> None:
    result = _bounded_expansion({
        "items": [
            {"source_item_id": "a", "is_anchor": True, "content": "A" * 10000},
            {"source_item_id": "b", "is_anchor": False, "content": "B" * 10000},
            {"source_item_id": "c", "is_anchor": False, "content": "C" * 10000},
        ],
        "supported_memories": None,
        "parent_lookup_id": "lookup-1",
    }, 800)
    assert len(_json_text(result)) <= 800
    assert result["items"][0]["is_anchor"] is True
    assert all(item.get("content_truncated") is True for item in result["items"])


def test_bounded_expansion_drops_farthest_preserves_order_and_omits_supports_first() -> None:
    result = _bounded_expansion({
        "items": [
            {"source_item_id": "n0", "is_anchor": False, "content": "before"},
            {"source_item_id": "anchor", "is_anchor": True, "content": "anchor"},
            {"source_item_id": "n2", "is_anchor": False, "content": "after"},
        ],
        "supported_memories": [{"memory_object_id": "m" * 1000}],
        "parent_lookup_id": "parent",
    }, 256)
    assert len(_json_text(result)) <= 256
    assert result["supported_memories"] is None
    ids = [item["source_item_id"] for item in result["items"]]
    assert ids == sorted(ids, key={"n0": 0, "anchor": 1, "n2": 2}.get)
    assert "anchor" in ids


def test_bounded_expansion_overmax_clamps_to_four_thousand_and_errors_are_bounded() -> None:
    result = _bounded_expansion({"items": [{"source_item_id": "a", "is_anchor": True, "content": "x" * 10000}]}, 50000)
    assert len(_json_text(result)) <= 4000
    assert len(_json_text(_compact_history({"error": "e" * 5000, "detail": "d" * 5000}, "q"))) <= 2000
    assert len(_json_text(_bounded_expansion({"error": "e" * 5000, "detail": "d" * 5000}, 4000))) <= 4000

@pytest.mark.asyncio
async def test_expand_source_bounds_structured_validation_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    result = {
        "error": "validation failed",
        "detail": {
            "loc": ["query", "max_chars"],
            "msg": "must be at least 256",
            "type": "greater_than_equal",
        },
    }
    with patch(
        "app.mcp.client.PalliumMcpClient.get_source_context",
        new=AsyncMock(return_value=result),
    ):
        server = create_server()
        content, _ = await server.call_tool(
            "pallium_expand_source",
            {"source_item_id": "missing", "max_chars": 256},
        )

    payload = json.loads(content[0].text)
    assert len(content[0].text) <= 256
    assert payload["detail"]["loc"] == ["query", "max_chars"]


@pytest.mark.asyncio
async def test_expand_source_bounds_empty_oversized_metadata_at_default_and_requested_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    result = {
        "items": [],
        "supported_memories": [{"memory_object_id": "m" * 10000}],
        "parent_lookup_id": "p" * 10000,
    }
    with patch(
        "app.mcp.client.PalliumMcpClient.get_source_context",
        new=AsyncMock(return_value=result),
    ):
        server = create_server()
        default_content, _ = await server.call_tool(
            "pallium_expand_source", {"source_item_id": "empty"},
        )
        capped_content, _ = await server.call_tool(
            "pallium_expand_source",
            {"source_item_id": "empty", "max_chars": 256},
        )

    assert len(default_content[0].text) <= 4000
    assert len(capped_content[0].text) <= 256
    assert json.loads(default_content[0].text)["error"] == "expansion exceeds the response budget"
    assert json.loads(capped_content[0].text)["error"] == "expansion exceeds the response budget"


def test_bounded_expansion_counts_dropped_neighbors_inside_budget() -> None:
    result = _bounded_expansion({
        "items": [
            {"source_item_id": "n0", "is_anchor": False, "content": "before"},
            {"source_item_id": "anchor", "is_anchor": True, "content": "anchor"},
            {"source_item_id": "n2", "is_anchor": False, "content": "after"},
        ],
        "supported_memories": None,
        "parent_lookup_id": "parent",
    }, 256)
    assert len(_json_text(result)) <= 256
    assert result["items_omitted"] > 0
    assert result["items_omitted"] == 3 - len(result["items"])


def test_compact_history_preserves_unicode_casefold_match_offset() -> None:
    result = _compact_history({
        "results": [{"source_item_id": "s", "excerpt": ("prefix " * 30) + "Straße " + ("suffix " * 30)}],
        "lookup_event_id": "lookup",
    }, "STRASSE")
    assert "Straße" in result["results"][0]["excerpt"]
    assert len(_json_text(result)) <= 2000

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments", "client_method"),
    [
        (
            "pallium_remember",
            {"text": "fact", "type": "decision"},
            "remember_memory",
        ),
        (
            "pallium_supersede",
            {"new_text": "replacement", "supersedes_id": "old-id"},
            "supersede_memory",
        ),
        (
            "pallium_record_outcome",
            {"procedure_id": "procedure-id", "outcome": "success"},
            "record_outcome",
        ),
    ],
)
async def test_explicit_creation_tools_resolve_complete_provenance_context(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    arguments: dict,
    client_method: str,
) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    scope = {
        "container_ref": "git:github.com/example/project",
        "thread_ref": "session-123",
        "actor_ref": "local-user",
        "agent_ref": "codex",
        "visibility": "private",
    }
    with patch("app.mcp.client.PalliumMcpClient.__init__", return_value=None) as init, patch(
        f"app.mcp.client.PalliumMcpClient.{client_method}",
        new=AsyncMock(return_value={"ok": True}),
    ):
        server = create_server()
        await server.call_tool(tool_name, {**arguments, **scope})

    context = init.call_args.args[0]
    assert {
        "container_ref": context.container_ref,
        "thread_ref": context.thread_ref,
        "actor_ref": context.actor_ref,
        "agent_ref": context.agent_ref,
        "visibility": context.visibility,
    } == scope

@pytest.mark.asyncio
async def test_relay_tools_are_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    server = create_server()
    names = {tool.name for tool in await server.list_tools()}
    assert {
        "pallium_relay_recipients",
        "pallium_relay_name",
        "pallium_relay_send",
        "pallium_relay_reply",
        "pallium_relay_status",
    } <= names

    tools = {tool.name: tool for tool in await server.list_tools()}
    assert "replace_existing=true" in tools["pallium_relay_name"].description
    assert "codex:@review" in tools["pallium_relay_send"].description
    assert "1,500" in tools["pallium_relay_send"].description
    assert "1,500" in tools["pallium_relay_reply"].description
    assert "multipart continuations" in tools["pallium_relay_reply"].description
    assert "one idempotent reply" in tools["pallium_relay_reply"].description


@pytest.mark.asyncio
async def test_relay_send_uses_exact_scope_and_preserves_unicode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    calls: list[dict] = []

    async def fake_send(**kwargs):
        calls.append(kwargs)
        return {"message_id": "m-1", "state": "pending"}

    with patch("app.mcp.client.PalliumMcpClient.relay_send", new=AsyncMock(side_effect=fake_send)):
        server = create_server()
        content, _ = await server.call_tool("pallium_relay_send", {
            "message": "הודעה → 你好",
            "recipient": "codex:@review",
            "sender_runtime": "codex",
            "sender_session_ref": "session-1",
            "container_ref": "git:example/repo",
            "actor_ref": "actor-1",
        })
    assert calls == [{
        "message": "הודעה → 你好",
        "recipient": "codex:@review",
        "sender_runtime": "codex",
        "sender_session_ref": "session-1",
        "expires_in_seconds": None,
    }]
    assert json.loads(content[0].text)["state"] == "pending"

@pytest.mark.asyncio
async def test_relay_reply_uses_delivery_without_model_supplied_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    reply = AsyncMock(return_value={"message_id": "reply-1"})
    with patch("app.mcp.client.PalliumMcpClient.relay_reply", new=reply):
        server = create_server()
        content, _ = await server.call_tool("pallium_relay_reply", {
            "delivery_id": "delivery-1",
            "message": "ack ✓",
            "container_ref": "git:example/repo",
            "actor_ref": "actor-1",
        })
    reply.assert_awaited_once_with(
        delivery_id="delivery-1", receipt=None, message="ack ✓", expires_in_seconds=None
    )
    assert json.loads(content[0].text)["message_id"] == "reply-1"


@pytest.mark.asyncio
async def test_relay_status_keeps_errors_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    error = {"error": "conflict", "status_code": 409, "detail": {"reason": "already delivered"}}
    with patch("app.mcp.client.PalliumMcpClient.relay_status", new=AsyncMock(return_value=error)):
        server = create_server()
        content, _ = await server.call_tool("pallium_relay_status", {"message_id": "m-1"})
    assert json.loads(content[0].text) == error


@pytest.mark.asyncio
async def test_relay_broadcast_response_keeps_success_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    result = {
        "message_id": "m-broadcast", "recipient": "codex", "redacted": False,
        "deliveries": [
            {"delivery_id": f"delivery-{index}", "state": "pending", "payload": "x" * 1500}
            for index in range(25)
        ],
    }
    with patch("app.mcp.client.PalliumMcpClient.relay_send", new=AsyncMock(return_value=result)):
        server = create_server()
        content, _ = await server.call_tool("pallium_relay_send", {
            "message": "handoff", "recipient": "codex", "sender_runtime": "claude-code",
            "sender_session_ref": "sender",
        })
    summary = json.loads(content[0].text)
    assert len(content[0].text) <= 2000
    assert summary == {
        "message_id": "m-broadcast", "recipient": "codex", "redacted": False,
        "delivery_count": 25, "delivery_states": {"pending": 25},
    }

@pytest.mark.asyncio
async def test_relay_response_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
    huge = {"message_id": "m-1", "payload": "x" * 5000}
    with patch("app.mcp.client.PalliumMcpClient.relay_status", new=AsyncMock(return_value=huge)):
        server = create_server()
        content, _ = await server.call_tool("pallium_relay_status", {"message_id": "m-1"})
    assert len(content[0].text) <= 2000
    assert json.loads(content[0].text)["error"] == "relay response exceeds the response budget"

def test_main_reads_stdio_transport_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = MagicMock()
    monkeypatch.setenv("PALLIUM_MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("FASTMCP_HOST", "127.0.0.1")
    monkeypatch.setenv("FASTMCP_PORT", "19837")
    monkeypatch.setattr(mcp_server, "create_server", lambda **_: runner)

    mcp_server.main()

    runner.run.assert_called_once_with(transport="stdio")
