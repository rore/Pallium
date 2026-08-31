"""FastMCP tool-layer tests for pallium_relay_receive and pallium_relay_ack.

Tests the FastMCP tool wrapper behaviors that HTTP-layer tests cannot reach:
- Identity guard (PALLIUM_AGENT_REF / PALLIUM_THREAD_REF env var checks)
- claim_token secrecy (stripped before the model sees the result)
- RF-008 drain-all (no max_chars cap at tool invocation)
- Stale receipt rejection at tool level
- hook/MCP race (delivery claimed by hook is not reclaimed by MCP receive)
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

pytest.importorskip("mcp", reason="mcp[cli] not installed")

from mcp.shared.memory import create_connected_server_and_client_session

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


@pytest.fixture()
def asgi_get(relay_app):
    async def _get(path, params):
        transport = httpx.ASGITransport(app=relay_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as http:
            response = await http.get(path, params=params)
            response.raise_for_status()
            return response.json()
    return _get

def bind_asgi_post(monkeypatch: pytest.MonkeyPatch, asgi_post) -> None:
    async def _post(_client, path, payload):
        try:
            return await asgi_post(path, payload)
        except httpx.HTTPStatusError as exc:
            return {
                "error": str(exc),
                "status_code": exc.response.status_code,
                "detail": exc.response.json(),
            }

    monkeypatch.setattr(PalliumMcpClient, "_post_or_error", _post)

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
        bind_asgi_post(monkeypatch, asgi_post)

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
        assert "deliveries" in data, data
        assert len(data["deliveries"]) == 1
        d = data["deliveries"][0]
        assert "claim_token" not in d
        assert d["receipt"] is not None
        assert d["delivery_id"]


class TestDrainAll:
    @pytest.mark.asyncio
    async def test_rf008_returns_all_deliveries_beyond_legacy_limit(self, monkeypatch: pytest.MonkeyPatch, asgi_post):
        """RF-008: all pending deliveries returned in one tool call, no 2400-char cap."""
        bind_asgi_post(monkeypatch, asgi_post)

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
        bind_asgi_post(monkeypatch, asgi_post)

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
        bind_asgi_post(monkeypatch, asgi_post)

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


class TestFullLifecycle:
    @pytest.mark.asyncio
    async def test_two_session_isolation_unicode_and_atomic_redacted_reply(
        self, monkeypatch: pytest.MonkeyPatch, asgi_post
    ):
        bind_asgi_post(monkeypatch, asgi_post)
        session_a = "tool-session-a"
        session_b = "tool-session-b"
        sender = "tool-isolation-sender"
        for runtime, session in (
            (_RUNTIME, session_a),
            (_RUNTIME, session_b),
            ("codex", sender),
        ):
            await asgi_post("/relay/turn", {"runtime": runtime, "session_ref": session, **_SCOPE})
        await asgi_post("/relay/messages", {
            "sender_runtime": "codex",
            "sender_session_ref": sender,
            "recipient": f"{_RUNTIME}:{session_a}",
            "payload": "日本語 🦾 résumé",
            **_SCOPE,
        })

        monkeypatch.setenv("PALLIUM_THREAD_REF", session_b)
        content, _ = await create_server().call_tool("pallium_relay_receive", {})
        assert json.loads(content[0].text)["deliveries"] == []

        monkeypatch.setenv("PALLIUM_THREAD_REF", session_a)
        content, _ = await create_server().call_tool("pallium_relay_receive", {})
        delivery = json.loads(content[0].text)["deliveries"][0]
        assert delivery["payload"] == "日本語 🦾 résumé"

        reply, _ = await create_server().call_tool("pallium_relay_reply", {
            "delivery_id": delivery["delivery_id"],
            "receipt": delivery["receipt"],
            "message": "Authorization: Bearer secret-tool-reply",
        })
        result = json.loads(reply[0].text)
        assert result["redacted"] is True
        assert "secret-tool-reply" not in result["payload"]

    @pytest.mark.asyncio
    async def test_restart_lease_redelivery_idempotent_ack_and_hook_race(
        self, monkeypatch: pytest.MonkeyPatch, asgi_post, relay_app
    ):
        bind_asgi_post(monkeypatch, asgi_post)
        await asgi_post("/relay/turn", {"runtime": _RUNTIME, "session_ref": _SESSION, **_SCOPE})
        await asgi_post("/relay/turn", {"runtime": "codex", "session_ref": "lifecycle-sender", **_SCOPE})
        await asgi_post("/relay/messages", {
            "sender_runtime": "codex",
            "sender_session_ref": "lifecycle-sender",
            "recipient": f"{_RUNTIME}:{_SESSION}",
            "payload": "redeliver me",
            **_SCOPE,
        })

        first_server = create_server()
        first, _ = await first_server.call_tool("pallium_relay_receive", {})
        first_delivery = json.loads(first[0].text)["deliveries"][0]
        second, _ = await create_server().call_tool("pallium_relay_receive", {})
        assert json.loads(second[0].text)["deliveries"] == []

        from datetime import datetime, timedelta, timezone
        from storage.sqlite_schema import RelayDeliveryRecord

        storage = relay_app.state.pallium_service._storage
        with storage._begin_immediate() as db:
            record = db.get(RelayDeliveryRecord, first_delivery["delivery_id"])
            record.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

        redelivered, _ = await create_server().call_tool("pallium_relay_receive", {})
        current = json.loads(redelivered[0].text)["deliveries"][0]
        assert current["receipt"] != first_delivery["receipt"]

        stale, _ = await create_server().call_tool("pallium_relay_ack", {
            "delivery_id": current["delivery_id"],
            "receipt": first_delivery["receipt"],
        })
        assert json.loads(stale[0].text)["status_code"] == 409
        for _ in range(2):
            ack, _ = await create_server().call_tool("pallium_relay_ack", {
                "delivery_id": current["delivery_id"],
                "receipt": current["receipt"],
            })
            assert json.loads(ack[0].text)["state"] == "delivered"

        await asgi_post("/relay/messages", {
            "sender_runtime": "codex",
            "sender_session_ref": "lifecycle-sender",
            "recipient": f"{_RUNTIME}:{_SESSION}",
            "payload": "hook wins",
            **_SCOPE,
        })
        hook_claim = await asgi_post("/relay/turn", {
            "runtime": _RUNTIME,
            "session_ref": _SESSION,
            **_SCOPE,
        })
        assert len(hook_claim["deliveries"]) == 1
        mcp_after_hook, _ = await create_server().call_tool("pallium_relay_receive", {})
        assert json.loads(mcp_after_hook[0].text)["deliveries"] == []
@pytest.mark.asyncio
async def test_trusted_codex_request_metadata_receives_per_session_and_acks(monkeypatch, asgi_post, asgi_get):
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.delenv("PALLIUM_THREAD_REF", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    bind_asgi_post(monkeypatch, asgi_post)
    for session in ("meta-a", "meta-b", "sender"):
        await asgi_post("/relay/turn", {"runtime": "codex", "session_ref": session, **_SCOPE})
    messages = {}
    for session, payload in (("meta-a", "only-a"), ("meta-b", "only-b")):
        messages[session] = await asgi_post("/relay/messages", {
            "sender_runtime": "codex", "sender_session_ref": "sender", "recipient": f"codex:{session}",
            "payload": payload, **_SCOPE,
        })
    async with create_connected_server_and_client_session(create_server(trust_codex_request_metadata=True)) as client:
        a, b = await asyncio.gather(
            client.call_tool("pallium_relay_receive", meta={"x-codex-turn-metadata": json.dumps({"thread_id": "meta-a", "session_id": "meta-a", "turn_id": "turn-a"})}),
            client.call_tool("pallium_relay_receive", meta={"x-codex-turn-metadata": json.dumps({"thread_id": "meta-b", "session_id": "meta-b", "turn_id": "turn-b"})}),
        )
        delivery_a = json.loads(a.content[0].text)["deliveries"][0]
        delivery_b = json.loads(b.content[0].text)["deliveries"][0]
        await client.call_tool("pallium_relay_ack", {"delivery_id": delivery_a["delivery_id"], "receipt": delivery_a["receipt"]})
        await client.call_tool("pallium_relay_reply", {"delivery_id": delivery_b["delivery_id"], "receipt": delivery_b["receipt"], "message": "reply-b"})
    status_a, status_b = await asyncio.gather(
        asgi_get(f"/relay/messages/{messages['meta-a']['message_id']}", _SCOPE),
        asgi_get(f"/relay/messages/{messages['meta-b']['message_id']}", _SCOPE),
    )
    assert [d["payload"] for d in json.loads(a.content[0].text)["deliveries"]] == ["only-a"]
    assert [d["payload"] for d in json.loads(b.content[0].text)["deliveries"]] == ["only-b"]
    assert status_a["deliveries"][0]["state"] == "delivered"
    assert status_b["deliveries"][0]["state"] == "delivered"


@pytest.mark.asyncio
async def test_trusted_codex_absent_metadata_preserves_runtime_fallback(monkeypatch, asgi_post):
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("PALLIUM_THREAD_REF", "fallback")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    bind_asgi_post(monkeypatch, asgi_post)
    for session in ("fallback", "sender"):
        await asgi_post("/relay/turn", {"runtime": "codex", "session_ref": session, **_SCOPE})
    await asgi_post("/relay/messages", {
        "sender_runtime": "codex", "sender_session_ref": "sender", "recipient": "codex:fallback",
        "payload": "legacy", **_SCOPE,
    })
    async with create_connected_server_and_client_session(create_server(trust_codex_request_metadata=True)) as client:
        result = await client.call_tool("pallium_relay_receive")
    assert [d["payload"] for d in json.loads(result.content[0].text)["deliveries"]] == ["legacy"]


@pytest.mark.asyncio
async def test_default_server_denies_forged_request_metadata_even_with_stdio_env(monkeypatch):
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("PALLIUM_MCP_TRANSPORT", "stdio")
    monkeypatch.delenv("PALLIUM_THREAD_REF", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    receive = AsyncMock()
    with patch.object(PalliumMcpClient, "relay_receive", new=receive):
        async with create_connected_server_and_client_session(create_server()) as client:
            result = await client.call_tool("pallium_relay_receive", meta={"x-codex-turn-metadata": json.dumps({"thread_id": "forged", "session_id": "forged", "turn_id": "turn"})})
    assert "PALLIUM_THREAD_REF" in result.content[0].text
    receive.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("request_meta", "expected_error"), [
    ({"x-codex-turn-metadata": None}, "PALLIUM_THREAD_REF"),
    ({"x-codex-turn-metadata": "["}, "Codex request identity"),
    ({"x-codex-turn-metadata": json.dumps({"thread_id": "only-thread", "turn_id": "turn"})}, "Codex request identity"),
    ({"x-codex-turn-metadata": json.dumps({"thread_id": None, "session_id": "s", "turn_id": "turn"})}, "Codex request identity"),
    ({"x-codex-turn-metadata": json.dumps({"thread_id": "safe\x00", "session_id": "safe\x00", "turn_id": "turn"})}, "Codex request identity"),
    ({"x-codex-turn-metadata": json.dumps({"thread_id": "x" * 4096})}, "Codex request identity"),
    ({"x-codex-turn-metadata": "[" * 1000}, "Codex request identity"),
])
async def test_trusted_codex_metadata_failures_do_not_call_receive(monkeypatch, request_meta, expected_error):
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.delenv("PALLIUM_THREAD_REF", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    receive = AsyncMock()
    with patch.object(PalliumMcpClient, "relay_receive", new=receive):
        async with create_connected_server_and_client_session(create_server(trust_codex_request_metadata=True)) as client:
            result = await client.call_tool("pallium_relay_receive", meta=request_meta)
    assert expected_error in result.content[0].text
    receive.assert_not_awaited()

@pytest.mark.asyncio
@pytest.mark.parametrize("env_key", ["PALLIUM_THREAD_REF", "CODEX_THREAD_ID", "CODEX_SESSION_ID"])
async def test_trusted_codex_metadata_environment_conflicts_do_not_call_receive(monkeypatch, env_key):
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.delenv("PALLIUM_THREAD_REF", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    monkeypatch.setenv(env_key, "other")
    receive = AsyncMock()
    with patch.object(PalliumMcpClient, "relay_receive", new=receive):
        async with create_connected_server_and_client_session(create_server(trust_codex_request_metadata=True)) as client:
            result = await client.call_tool("pallium_relay_receive", meta={"x-codex-turn-metadata": json.dumps({"thread_id": "safe", "session_id": "safe", "turn_id": "turn"})})
    assert "Codex request identity" in result.content[0].text
    receive.assert_not_awaited()


@pytest.mark.asyncio
async def test_trusted_codex_metadata_rejects_forged_model_context(monkeypatch):
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.delenv("PALLIUM_THREAD_REF", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    receive = AsyncMock()
    with patch.object(PalliumMcpClient, "relay_receive", new=receive):
        async with create_connected_server_and_client_session(create_server(trust_codex_request_metadata=True)) as client:
            result = await client.call_tool("pallium_relay_receive", {"context": {"thread_id": "forged"}})
    assert "PALLIUM_THREAD_REF" in result.content[0].text
    receive.assert_not_awaited()
