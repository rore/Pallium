"""End-to-end integration test: MCP client → Pallium ASGI app.

Uses httpx.ASGITransport to connect the async MCP client directly to the
Pallium ASGI application, verifying the full passthrough chain without
needing a real HTTP server.
"""

from __future__ import annotations

import httpx
import pytest

from app.main import create_app
from app.config import AppConfig
from app.mcp.client import PalliumMcpClient
from app.mcp.context import PalliumContext


@pytest.fixture()
def pallium_asgi_app(test_db_url: str):
    from storage.vector_index import VectorIndexConfig
    return create_app(
        AppConfig(
            storage_backend="sqlite",
            sqlite_url=test_db_url,
            default_use_case="demo_agent_memory",
            vector_index=VectorIndexConfig(enabled=False),
        )
    )


@pytest.fixture()
def mcp_client(pallium_asgi_app) -> PalliumMcpClient:
    """MCP client wired to the ASGI app via ASGITransport."""
    ctx = PalliumContext(
        base_url="http://testserver",
        visibility="public",
    )
    client = PalliumMcpClient(ctx)

    # Monkey-patch _post to use ASGITransport instead of real HTTP
    async def _asgi_post(path, payload):
        transport = httpx.ASGITransport(app=pallium_asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as http:
            response = await http.post(path, json=payload)
            response.raise_for_status()
            return response.json()

    client._post = _asgi_post
    return client


class TestMcpClientPassthrough:
    """Verify MCP client responses match what the HTTP API returns."""

    @pytest.mark.asyncio
    async def test_query_returns_valid_response(self, mcp_client: PalliumMcpClient) -> None:
        result = await mcp_client.query("test query", limit=5)
        assert "results" in result
        assert "should_inject" in result
        assert "decision_reason" in result
        assert "injectable_blocks" in result

    @pytest.mark.asyncio
    async def test_query_debug_returns_trace(self, mcp_client: PalliumMcpClient) -> None:
        result = await mcp_client.query_debug("test query")
        assert "results" in result
        assert "trace" in result
        assert "should_inject" in result

    @pytest.mark.asyncio
    async def test_ingest_returns_processing_status(self, mcp_client: PalliumMcpClient) -> None:
        result = await mcp_client.ingest(
            content="Remember this decision about caching",
            source_type="agent_artifact",
            source_id="mcp-integration-test-001",
        )
        assert "source_item_id" in result
        assert "processing_status" in result
        assert result["processing_status"] in ("pending", "completed", "skipped")

    @pytest.mark.asyncio
    async def test_query_response_matches_direct_http(self, pallium_asgi_app, mcp_client: PalliumMcpClient) -> None:
        """MCP client response must be identical to direct HTTP API response."""
        query_payload = {"text": "test match", "limit": 3, "visibility": "public"}

        # Direct HTTP response
        transport = httpx.ASGITransport(app=pallium_asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            direct_response = await http.post("/query", json=query_payload)
            direct_result = direct_response.json()

        # MCP client response
        mcp_result = await mcp_client.query("test match", limit=3)

        # Must match exactly — no transformation layer
        assert mcp_result == direct_result
