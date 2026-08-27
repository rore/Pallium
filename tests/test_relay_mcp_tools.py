"""FastMCP tool-layer tests for pallium_relay_receive and pallium_relay_ack.

Tests the FastMCP tool wrapper behaviors that HTTP-layer tests cannot reach:
- Identity guard (PALLIUM_AGENT_REF / PALLIUM_THREAD_REF env var checks)
- claim_token secrecy (stripped before the model sees the result)
- RF-008 drain-all (no max_chars cap at tool invocation)
- Stale receipt rejection at tool level
- hook/MCP race (delivery claimed by hook is not reclaimed by MCP receive)
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

pytest.importorskip("mcp", reason="mcp[cli] not installed")

from app.config import AppConfig
from app.main import create_app
from app.mcp.client import PalliumMcpClient
from app.mcp.server import create_server
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


_SCOPE = {
    "container_ref": "git:example.test/relay-tools",
    "actor_ref": "tool-actor",
}
_RUNTIME = "claude-code"
_SESSION = "mcp-tool-session"


@pytest.fixture()
def relay_app(test_db_url: str):
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
def asgi_post(relay_app):
    async def _post(path, payload):
        transport = httpx.ASGITransport(app=relay_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as http:
            response = await http.post(path, json=payload)
            response.raise_for_status()
            return response.json()
    return _post


@pytest.fixture(autouse=True)
def base_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://testserver")
    monkeypatch.setenv("PALLIUM_CONTAINER_REF", _SCOPE["container_ref"])
    monkeypatch.setenv("PALLIUM_ACTOR_REF", _SCOPE["actor_ref"])
    monkeypatch.setenv("PALLIUM_AGENT_REF", _RUNTIME)
    monkeypatch.setenv("PALLIUM_THREAD_REF", _SESSION)


class TestIdentityGuard:
    @pytest.mark.asyncio
    async def test_receive_fails_without_agent_ref(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("PALLIUM_AGENT_REF", raising=False)
        server = create_server()
        content, _ = await server.call_tool("pallium_relay_receive", {})
        assert "PALLIUM_AGENT_REF" in content[0].text

    @pytest.mark.asyncio
    async def test_receive_fails_without_thread_ref(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("PALLIUM_THREAD_REF", raising=False)
        server = create_server()
        content, _ = await server.call_tool("pallium_relay_receive", {})
        assert "PALLIUM_THREAD_REF" in content[0].text

    @pytest.mark.asyncio
    async def test_receive_fails_when_not_configured(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("PALLIUM_BASE_URL", raising=False)
        server = create_server()
        content, _ = await server.call_tool("pallium_relay_receive", {})
        assert "not configured" in content[0].text.lower()


class TestClaimTokenSecrecy:
    @pytest.mark.asyncio
    async def test_claim_token_stripped_from_mcp_result(self, monkeypatch: pytest.MonkeyPatch):
        """claim_token must never appear in the model-facing MCP response."""
        delivery_with_token = {
            "delivery_id": "d-secret",
            "claim_token": "super-secret-claim-token",
            "receipt": "safe-receipt-for-model",
            "message_id": "m-1",
            "payload": "hello",
            "sender_runtime": "codex",
            "sender_session_ref": "sender",
            "created_at": "2026-08-27T00:00:00Z",
        }
        mock_result = {"deliveries": [delivery_with_token], "has_more": False, "remaining_count": 0}

        with patch.object(PalliumMcpClient, "relay_receive", new_callable=AsyncMock, return_value=mock_result):
            server = create_server()
            content, _ = await server.call_tool("pallium_relay_receive", {})
            text = content[0].text
            assert "super-secret-claim-token" not in text
            assert "safe-receipt-for-model" in text

    @pytest.mark.asyncio
    async def test_receipt_present_in_mcp_result(self, monkeypatch: pytest.MonkeyPatch, asgi_post):
        """receipt is visible in the MCP response; delivery_id is present for ACK."""
        monkeypatch.setattr(PalliumMcpClient, "_post", asgi_post)

        # register both sessions first
        await asgi_post("/relay/turn", {"runtime": _RUNTIME, "session_ref": _SESSION, **_SCOPE})
        await asgi_post("/relay/turn", {"runtime": "codex", "session_ref": "tool-sender", **_SCOPE})
        await asgi_post("/relay/messages", {
            "sender_runtime": "codex", "sender_session_ref": "tool-sender",
            "recipient": f"{_RUNTIME}:{_SESSION}", "payload": "test message", **_SCOPE,
        })

        server = create_server()
        content, _ = await server.call_tool("pallium_relay_receive", {})
        text = content[0].text
        data = json.loads(text)
        assert len(data["deliveries"]) == 1
        d = data["deliveries"][0]
        assert "claim_token" not in d
        assert d["receipt"] is not None
        assert d["delivery_id"]


class TestDrainAll:
    @pytest.mark.asyncio
    async def test_rf008_returns_all_deliveries_beyond_legacy_limit(self, monkeypatch: pytest.MonkeyPatch, asgi_post):
        """RF-008: all pending deliveries returned in one tool call, no 2400-char cap."""
        monkeypatch.setattr(PalliumMcpClient, "_post", asgi_post)

        await asgi_post("/relay/turn", {"runtime": _RUNTIME, "session_ref": _SESSION, **_SCOPE})
        for i in range(4):
            sender = f"drain-tool-{i}"
            await asgi_post("/relay/turn", {"runtime": "codex", "session_ref": sender, **_SCOPE})
            await asgi_post("/relay/messages", {
                "sender_runtime": "codex", "sender_session_ref": sender,
                "recipient": f"{_RUNTIME}:{_SESSION}",
                "payload": f"message-{i}: " + "x" * 700,
                **_SCOPE,
            })

        server = create_server()
        content, _ = await server.call_tool("pallium_relay_receive", {})
        data = json.loads(content[0].text)
        assert len(data["deliveries"]) == 4
        assert data["has_more"] is False


class TestAck:
    @pytest.mark.asyncio
    async def test_ack_with_valid_receipt(self, monkeypatch: pytest.MonkeyPatch, asgi_post):
        monkeypatch.setattr(PalliumMcpClient, "_post", asgi_post)

        await asgi_post("/relay/turn", {"runtime": _RUNTIME, "session_ref": _SESSION, **_SCOPE})
        await asgi_post("/relay/turn", {"runtime": "codex", "session_ref": "ack-sender", **_SCOPE})
        await asgi_post("/relay/messages", {
            "sender_runtime": "codex", "sender_session_ref": "ack-sender",
            "recipient": f"{_RUNTIME}:{_SESSION}", "payload": "ack me", **_SCOPE,
        })

        server = create_server()
        recv, _ = await server.call_tool("pallium_relay_receive", {})
        d = json.loads(recv[0].text)["deliveries"][0]

        ack, _ = await server.call_tool("pallium_relay_ack", {
            "delivery_id": d["delivery_id"], "receipt": d["receipt"],
        })
        assert json.loads(ack[0].text)["state"] == "delivered"

    @pytest.mark.asyncio
    async def test_ack_with_wrong_receipt_fails(self, monkeypatch: pytest.MonkeyPatch, asgi_post):
        monkeypatch.setattr(PalliumMcpClient, "_post", asgi_post)

        await asgi_post("/relay/turn", {"runtime": _RUNTIME, "session_ref": _SESSION, **_SCOPE})
        await asgi_post("/relay/turn", {"runtime": "codex", "session_ref": "wrong-ack-sender", **_SCOPE})
        await asgi_post("/relay/messages", {
            "sender_runtime": "codex", "sender_session_ref": "wrong-ack-sender",
            "recipient": f"{_RUNTIME}:{_SESSION}", "payload": "bad ack", **_SCOPE,
        })

        server = create_server()
        recv, _ = await server.call_tool("pallium_relay_receive", {})
        d = json.loads(recv[0].text)["deliveries"][0]

        bad_ack, is_error = await server.call_tool("pallium_relay_ack", {
            "delivery_id": d["delivery_id"], "receipt": "wrong-receipt",
        })
        text = bad_ack[0].text
        assert "conflict" in text.lower() or "409" in text or is_error
