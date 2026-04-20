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
    async def test_all_three_tools_registered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:8000")
        server = create_server()
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {"pallium_query", "pallium_query_debug", "pallium_ingest", "pallium_get_evidence", "pallium_flag_memory"}
