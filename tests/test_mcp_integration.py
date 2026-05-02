"""End-to-end integration test: MCP client → Pallium ASGI app.

Uses httpx.ASGITransport to connect the async MCP client directly to the
Pallium ASGI application, verifying the full passthrough chain without
needing a real HTTP server.
"""

from __future__ import annotations

import httpx
import pytest

pytest.importorskip("mcp", reason="mcp[cli] not installed")

from app.main import create_app
from app.config import AppConfig
from app.mcp.client import PalliumMcpClient
from app.mcp.context import PalliumContext
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


@pytest.fixture()
def pallium_asgi_app(test_db_url: str):
    from storage.vector_index import VectorIndexConfig
    app = create_app(
        AppConfig(
            storage_backend="sqlite",
            sqlite_url=test_db_url,
            default_use_case="demo_agent_memory",
            semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(enabled=False),
        )
    )
    app.state._lifespan_complete = True
    return app


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


class TestMcpEndpointReachable:
    """Verify the /mcp endpoint is actually mounted and responds to MCP protocol."""

    def test_mcp_endpoint_accepts_initialize(self, test_db_url: str) -> None:
        """The /mcp endpoint must respond to MCP initialize requests."""
        import json as json_mod
        from starlette.testclient import TestClient
        from storage.vector_index import VectorIndexConfig
        # Use TestClient which handles ASGI lifespan (startup/shutdown)
        app = create_app(AppConfig(
            storage_backend="sqlite",
            sqlite_url=test_db_url,
            default_use_case="demo_agent_memory",
            semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(enabled=False),
        ))
        with TestClient(app, headers={"host": "127.0.0.1:8000"}) as client:
            response = client.post("/mcp", json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                    "protocolVersion": "2024-11-05",
                },
                "id": 1,
            }, headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            })
            assert response.status_code == 200
            # Response is SSE format: "event: message\r\ndata: {...}\r\n\r\n"
            text = response.text
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("data: "):
                    body = json_mod.loads(line[6:])
                    assert body.get("result", {}).get("serverInfo", {}).get("name") == "pallium"
                    return
            pytest.fail(f"No data line found in SSE response: {text[:200]}")

    def test_mcp_endpoint_not_on_wrong_path(self, test_db_url: str) -> None:
        """Confirm /mcp/mcp does NOT work (regression guard for mount path bug)."""
        from starlette.testclient import TestClient
        from storage.vector_index import VectorIndexConfig
        app = create_app(AppConfig(
            storage_backend="sqlite",
            sqlite_url=test_db_url,
            default_use_case="demo_agent_memory",
            semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(enabled=False),
        ))
        with TestClient(app, headers={"host": "127.0.0.1:8000"}) as client:
            response = client.post("/mcp/mcp", json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                    "protocolVersion": "2024-11-05",
                },
                "id": 1,
            })
            assert response.status_code != 200

    @pytest.mark.asyncio
    async def test_api_routes_still_work_with_mcp_mounted(self, pallium_asgi_app) -> None:
        """API routes must not be broken by the MCP mount."""
        transport = httpx.ASGITransport(app=pallium_asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            health = await http.get("/health")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"

            query = await http.post("/query", json={"text": "test", "visibility": "public"})
            assert query.status_code == 200
            assert "results" in query.json()
