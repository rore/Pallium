"""pallium_search_history — agent-facing source-only history lookup (vNext P1).

Exercises the MCP client's `search_history` method against the Pallium ASGI app
via ASGITransport. The method carries the load-bearing behavior (source_only +
agent_pull attribution + scope + optional filters); the FastMCP `@server.tool()`
wrapper is a thin passthrough. Kept OUT of test_mcp_integration.py so it runs
even where `mcp[cli]` is not installed (that file is import-skipped).
"""
from __future__ import annotations

import httpx
import pytest

from app.config import AppConfig, ObservabilityConfig
from app.main import create_app
from app.mcp.client import PalliumMcpClient
from app.mcp.context import PalliumContext
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


@pytest.fixture()
def asgi_app(test_db_url: str):
    from storage.vector_index import VectorIndexConfig
    app = create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=test_db_url,
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
        observability=ObservabilityConfig(query_audit_log=True),  # populate lookup_event_id
    ))
    app.state._lifespan_complete = True
    return app


@pytest.fixture()
def client(asgi_app) -> PalliumMcpClient:
    c = PalliumMcpClient(PalliumContext(base_url="http://testserver", visibility="public"))

    async def _asgi_post(path, payload):
        transport = httpx.ASGITransport(app=asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as http:
            response = await http.post(path, json=payload)
            response.raise_for_status()
            return response.json()

    c._post = _asgi_post
    return c


@pytest.mark.asyncio
async def test_search_history_sends_source_only_and_agent_pull(client: PalliumMcpClient) -> None:
    captured: dict = {}
    orig = client._post

    async def capture(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return await orig(path, payload)

    client._post = capture
    await client.search_history("reservation ordering", limit=3, source_type="chat_message")

    assert captured["path"] == "/query"
    p = captured["payload"]
    assert p["source_only"] is True
    assert p["trigger_origin"] == "agent_pull"
    assert p["source_type"] == "chat_message"
    assert p["visibility"] == "public"  # scope from context
    # optional filters not supplied are omitted
    assert "role" not in p and "work_refs" not in p


@pytest.mark.asyncio
async def test_search_history_returns_source_hits_with_stable_ids(asgi_app, client: PalliumMcpClient) -> None:
    await client.ingest(
        content="reservation ordering duplicate holds decision",
        source_type="chat_message",
        source_id="hist-e2e-1",
        artifact_kind="message",
        role="user",
    )
    asgi_app.state.pallium_service.drain_processing_queue(worker_id="mcp-hist-test")

    result = await client.search_history("reservation ordering duplicate holds", limit=5)

    assert result["decision_reason"] == "source_only_search"
    assert result["should_inject"] is False
    # Audit logging is enabled on the fixture, so the measurement event chain's
    # anchor is populated (not just present in the schema).
    assert result["lookup_event_id"] is not None
    source_hits = [r for r in result["results"] if r["result_kind"] == "source_hit"]
    assert source_hits, result
    top = source_hits[0]
    assert top["source_item_id"]  # stable handle for expansion / forget
    assert top["raw_rank"] == 1


@pytest.mark.asyncio
async def test_search_history_omits_unset_optional_filters(client: PalliumMcpClient) -> None:
    captured: dict = {}
    orig = client._post

    async def capture(path, payload):
        captured["payload"] = payload
        return await orig(path, payload)

    client._post = capture
    await client.search_history("anything")
    p = captured["payload"]
    assert p["source_only"] is True
    assert p["trigger_origin"] == "agent_pull"
    for k in ("source_type", "role", "artifact_kind", "work_refs"):
        assert k not in p
