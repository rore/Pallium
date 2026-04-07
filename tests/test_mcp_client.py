"""Tests for MCP HTTP client wrapping Pallium REST API."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.client import PalliumMcpClient
from app.mcp.context import PalliumContext


@pytest.fixture()
def ctx() -> PalliumContext:
    return PalliumContext(
        base_url="http://localhost:8000",
        container_ref="test-container",
        thread_ref="test-thread",
        actor_ref="test-actor",
        visibility="container",
    )


def _mock_response(status_code: int = 200, json_data: dict | list | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = json.dumps(json_data or {})
    resp.raise_for_status = MagicMock()
    return resp


class TestQuery:
    @pytest.mark.asyncio
    async def test_query_sends_scope_from_context(self, ctx: PalliumContext) -> None:
        mock_resp = _mock_response(json_data={"results": [], "should_inject": False, "decision_reason": "no_relevant_memory", "injectable_blocks": []})
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.query("test query", limit=3)

            mock_post.assert_called_once()
            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            assert payload["text"] == "test query"
            assert payload["limit"] == 3
            assert payload["container_ref"] == "test-container"
            assert payload["thread_ref"] == "test-thread"
            assert payload["actor_ref"] == "test-actor"
            assert payload["visibility"] == "container"

    @pytest.mark.asyncio
    async def test_query_omits_none_scope_fields(self) -> None:
        ctx = PalliumContext(base_url="http://localhost:8000")
        mock_resp = _mock_response(json_data={"results": [], "should_inject": False, "decision_reason": "no_relevant_memory", "injectable_blocks": []})
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.query("test query")

            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            assert "container_ref" not in payload
            assert "thread_ref" not in payload
            assert "actor_ref" not in payload
            assert "visibility" not in payload

    @pytest.mark.asyncio
    async def test_query_returns_raw_json(self, ctx: PalliumContext) -> None:
        expected = {"results": [{"score": 0.9}], "should_inject": True, "decision_reason": "carry_forward_available", "injectable_blocks": []}
        mock_resp = _mock_response(json_data=expected)
        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            client = PalliumMcpClient(ctx)
            result = await client.query("test")
            assert result == expected


class TestQueryDebug:
    @pytest.mark.asyncio
    async def test_query_debug_hits_debug_endpoint(self, ctx: PalliumContext) -> None:
        mock_resp = _mock_response(json_data={"results": [], "should_inject": False, "decision_reason": "no_relevant_memory", "injectable_blocks": [], "trace": {}})
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.query_debug("test")

            url = mock_post.call_args.args[0] if mock_post.call_args.args else mock_post.call_args.kwargs.get("url", "")
            assert "/query/debug" in str(url)

    @pytest.mark.asyncio
    async def test_query_debug_omits_limit(self, ctx: PalliumContext) -> None:
        """query_debug intentionally omits limit — uses API default (5)."""
        mock_resp = _mock_response(json_data={"results": [], "should_inject": False, "decision_reason": "no_relevant_memory", "trace": {}})
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.query_debug("test")

            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            assert "limit" not in payload


class TestIngest:
    @pytest.mark.asyncio
    async def test_ingest_sends_single_item_array(self, ctx: PalliumContext) -> None:
        mock_resp = _mock_response(json_data=[{"source_item_id": "si-123", "processing_status": "pending", "memory_object_ids": [], "relation_ids": [], "index_entry_ids": [], "processing_attempts": 0, "processing_error": None}])
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.ingest(
                content="Remember this decision",
                source_type="agent_artifact",
                source_id="test-123",
                artifact_kind="assistant_output",
                role="assistant",
            )

            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
            assert isinstance(payload, list)
            assert len(payload) == 1
            item = payload[0]
            assert item["content"] == "Remember this decision"
            assert item["source_type"] == "agent_artifact"
            assert item["source_id"] == "test-123"
            assert item["content_type"] == "text/plain"
            assert item["artifact_kind"] == "assistant_output"
            assert item["role"] == "assistant"
            assert item["container_ref"] == "test-container"

    @pytest.mark.asyncio
    async def test_ingest_omits_none_optional_fields(self, ctx: PalliumContext) -> None:
        """artifact_kind and role should be omitted when None, not sent as null."""
        mock_resp = _mock_response(json_data=[{"source_item_id": "si-123", "processing_status": "pending", "memory_object_ids": [], "relation_ids": [], "index_entry_ids": [], "processing_attempts": 0}])
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.ingest(content="test", source_type="agent_artifact", source_id="x")

            item = mock_post.call_args.kwargs.get("json")[0]
            assert "artifact_kind" not in item
            assert "role" not in item

    @pytest.mark.asyncio
    async def test_ingest_generates_source_id_when_none(self, ctx: PalliumContext) -> None:
        """When source_id is None, client auto-generates an mcp-prefixed ID."""
        mock_resp = _mock_response(json_data=[{"source_item_id": "si-123", "processing_status": "pending", "memory_object_ids": [], "relation_ids": [], "index_entry_ids": [], "processing_attempts": 0}])
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            client = PalliumMcpClient(ctx)
            await client.ingest(content="test", source_type="agent_artifact")

            item = mock_post.call_args.kwargs.get("json")[0]
            assert item["source_id"].startswith("mcp-")
            assert len(item["source_id"]) == 16  # "mcp-" + 12 hex chars

    @pytest.mark.asyncio
    async def test_ingest_returns_first_item_response(self, ctx: PalliumContext) -> None:
        resp_data = [{"source_item_id": "si-abc", "processing_status": "pending", "memory_object_ids": [], "relation_ids": [], "index_entry_ids": [], "processing_attempts": 0}]
        mock_resp = _mock_response(json_data=resp_data)
        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            client = PalliumMcpClient(ctx)
            result = await client.ingest(content="test", source_type="agent_artifact", source_id="x")
            assert result == resp_data[0]


class TestConnectionError:
    @pytest.mark.asyncio
    async def test_connection_error_returns_error_dict(self, ctx: PalliumContext) -> None:
        with patch("httpx.AsyncClient.post", side_effect=Exception("Connection refused")):
            client = PalliumMcpClient(ctx)
            result = await client.query("test")
            assert "error" in result
            assert "Connection refused" in result["error"]
