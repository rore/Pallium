"""Tests for MCP server tool registration and self-gating."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("mcp", reason="mcp[cli] not installed")

from app.mcp.server import create_server


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
