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


def bind_asgi_post(monkeypatch: pytest.MonkeyPatch, asgi_post) -> None:
    async def _post(_client, path, payload, **_kwargs):
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
    async def test_receive_uses_codex_runtime_identity(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
        monkeypatch.delenv("PALLIUM_THREAD_REF", raising=False)
        monkeypatch.setenv("CODEX_THREAD_ID", "codex-runtime-session")
        with patch.object(PalliumMcpClient, "relay_receive", new_callable=AsyncMock) as receive:
            content, _ = await create_server().call_tool("pallium_relay_receive", {})
        assert "metadata" in content[0].text
        receive.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_receive_missing_scope_is_actionable_before_identity(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("PALLIUM_CONTAINER_REF", raising=False)
        monkeypatch.delenv("PALLIUM_ACTOR_REF", raising=False)
        monkeypatch.delenv("PALLIUM_THREAD_REF", raising=False)
        with patch.object(PalliumMcpClient, "relay_receive", new_callable=AsyncMock) as receive:
            content, _ = await create_server().call_tool("pallium_relay_receive", {})
        assert "both container_ref and actor_ref" in content[0].text
        assert "PALLIUM_THREAD_REF" not in content[0].text
        receive.assert_not_awaited()
    @pytest.mark.asyncio
    async def test_codex_receive_fails_without_runtime_identity(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
        monkeypatch.delenv("PALLIUM_THREAD_REF", raising=False)
        monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
        monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
        server = create_server()
        content, _ = await server.call_tool("pallium_relay_receive", {})
        assert "metadata" in content[0].text

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
        data = json.loads(ack[0].text)
        assert data["state"] == "delivered"
        assert data["already_delivered"] is False

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
        with storage._begin_relay_immediate() as db:
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

@pytest.fixture()
def asgi_get(relay_app):
    async def _get(path, params):
        transport = httpx.ASGITransport(app=relay_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as http:
            response = await http.get(path, params=params)
            response.raise_for_status()
            return response.json()
    return _get


_RELAY_SCOPE_TOOL_METHODS = {
    "pallium_relay_receive": ("relay_receive", {}),
    "pallium_relay_ack": ("relay_mcp_ack", {"delivery_id": "delivery", "receipt": "receipt"}),
    "pallium_relay_reply": ("relay_reply", {"delivery_id": "delivery", "message": "reply"}),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", _RELAY_SCOPE_TOOL_METHODS)
async def test_configured_relay_scope_accepts_matching_pair(monkeypatch, tool):
    client_method, arguments = _RELAY_SCOPE_TOOL_METHODS[tool]
    http_call = AsyncMock(return_value={})
    with patch.object(PalliumMcpClient, client_method, new=http_call):
        content, _ = await create_server().call_tool(tool, {**arguments, **_SCOPE})
    assert "Relay scope" not in content[0].text
    http_call.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", _RELAY_SCOPE_TOOL_METHODS)
@pytest.mark.parametrize(
    "scope",
    [
        {"container_ref": _SCOPE["container_ref"]},
        {"container_ref": _SCOPE["container_ref"], "actor_ref": "other-actor"},
    ],
)
async def test_partial_or_conflicting_relay_scope_never_calls_http(monkeypatch, tool, scope):
    client_method, arguments = _RELAY_SCOPE_TOOL_METHODS[tool]
    http_call = AsyncMock(return_value={})
    with patch.object(PalliumMcpClient, client_method, new=http_call):
        content, _ = await create_server().call_tool(tool, {**arguments, **scope})
    assert "Relay scope" in content[0].text
    http_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_configured_scope_cannot_be_bypassed(monkeypatch):
    monkeypatch.delenv("PALLIUM_ACTOR_REF", raising=False)
    http_call = AsyncMock(return_value={})
    with patch.object(PalliumMcpClient, "relay_receive", new=http_call):
        content, _ = await create_server().call_tool("pallium_relay_receive", _SCOPE)
    assert "Configured Relay scope" in content[0].text
    http_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_unconfigured_paired_scope_receive_to_reply_is_atomic(monkeypatch, asgi_post, asgi_get):
    scope = {"container_ref": "git:example.test/unconfigured-relay", "actor_ref": "unconfigured-actor"}
    monkeypatch.delenv("PALLIUM_CONTAINER_REF", raising=False)
    monkeypatch.delenv("PALLIUM_ACTOR_REF", raising=False)
    bind_asgi_post(monkeypatch, asgi_post)
    await asgi_post("/relay/turn", {"runtime": _RUNTIME, "session_ref": _SESSION, **scope})
    await asgi_post("/relay/turn", {"runtime": "codex", "session_ref": "paired-sender", **scope})
    sent = await asgi_post("/relay/messages", {
        "sender_runtime": "codex",
        "sender_session_ref": "paired-sender",
        "recipient": f"{_RUNTIME}:{_SESSION}",
        "payload": "paired scope",
        **scope,
    })

    received, _ = await create_server().call_tool("pallium_relay_receive", scope)
    delivery = json.loads(received[0].text)["deliveries"][0]
    replied, _ = await create_server().call_tool("pallium_relay_reply", {
        "delivery_id": delivery["delivery_id"],
        "receipt": delivery["receipt"],
        "message": "paired reply",
        **scope,
    })
    assert json.loads(replied[0].text)["in_reply_to"] == sent["message_id"]
    status = await asgi_get(f"/relay/messages/{sent['message_id']}", scope)
    assert status["deliveries"][0]["state"] == "delivered"


@pytest.mark.asyncio
async def test_redacted_send_and_reply_summaries_are_safe_and_bounded(
    monkeypatch: pytest.MonkeyPatch, asgi_post,
):
    bind_asgi_post(monkeypatch, asgi_post)
    sender = "s" * 255
    for runtime, session in ((_RUNTIME, _SESSION), ("codex", sender)):
        await asgi_post("/relay/turn", {"runtime": runtime, "session_ref": session, **_SCOPE})

    server = create_server()

    async def send(message: str, recipient: str = f"{_RUNTIME}:{_SESSION}", **extra):
        content, _ = await server.call_tool("pallium_relay_send", {
            "message": message,
            "recipient": recipient,
            "sender_runtime": "codex",
            "sender_session_ref": sender,
            **extra,
        })
        return content[0].text, json.loads(content[0].text)

    repro = "session_id: wake uses socket/pipe+token+scope after restart"
    _, repro_result = await send(repro)
    assert repro_result["redacted"] is False
    assert repro_result["payload"] == repro

    unicode_payload = "日本語 🦾 résumé"
    _, unicode_result = await send(unicode_payload)
    assert unicode_result["payload"] == unicode_payload

    secret = "ghp_" + ("A" * 36)
    secret_text, secret_result = await send(f"credential: {secret} for Relay")
    assert secret_result["redacted"] is True
    assert secret not in secret_text
    assert secret_result["payload"] != f"credential: {secret} for Relay"

    received, _ = await server.call_tool("pallium_relay_receive", {})
    deliveries = json.loads(received[0].text)["deliveries"]
    reply_delivery = next(item for item in deliveries if item["payload"] == repro)
    reply_args = {
        "delivery_id": reply_delivery["delivery_id"],
        "receipt": reply_delivery["receipt"],
        "message": f"Authorization: Bearer {secret}",
    }
    first_reply, _ = await server.call_tool("pallium_relay_reply", reply_args)
    second_reply, _ = await server.call_tool("pallium_relay_reply", reply_args)
    assert secret not in first_reply[0].text
    assert secret not in second_reply[0].text

    long_session = "w" * 255
    await asgi_post("/relay/turn", {
        "runtime": _RUNTIME, "session_ref": long_session, **_SCOPE,
    })
    oversized = "Bearer " + ("A" * 20) + " " + ("z" * 1472)
    oversized_text, oversized_result = await send(
        oversized, f"{_RUNTIME}:{long_session}", expires_in_seconds=60,
    )
    assert len(oversized_text) <= 2000
    assert oversized_result["redacted"] is True
    assert oversized_result["payload_truncated"] is True
    assert "[truncated]" in oversized_result["payload"]
    assert oversized not in oversized_text
    assert "A" * 20 not in oversized_text

@pytest.mark.asyncio
async def test_recipient_address_book_pages_selectors_filters_and_lifecycle(
    monkeypatch: pytest.MonkeyPatch, asgi_post, asgi_get,
):
    bind_asgi_post(monkeypatch, asgi_post)

    async def get_from_app(_client, path, params):
        return await asgi_get(path, params)

    monkeypatch.setattr(PalliumMcpClient, "_get_or_error", get_from_app)
    server = create_server()

    async def page(**arguments):
        content, _ = await server.call_tool("pallium_relay_recipients", arguments)
        assert len(content[0].text) <= 2000
        return json.loads(content[0].text)

    assert await page() == {
        "recipients": [], "offset": 0, "next_offset": None,
        "has_more": False, "total_count": 0,
    }

    sender = "address-book-sender"
    await asgi_post("/relay/turn", {"runtime": "codex", "session_ref": sender, **_SCOPE})
    targets = [f"target-{index:02d}" for index in range(14)]
    for index, session in enumerate(targets):
        await asgi_post("/relay/turn", {
            "runtime": "codex", "session_ref": session,
            "title": f"מפתח 日本語 {index}", **_SCOPE,
        })
    await asgi_post("/relay/turn", {
        "runtime": "claude-code", "session_ref": "claude-target", **_SCOPE,
    })
    await asgi_post("/relay/sessions/name", {
        "runtime": "codex", "session_ref": targets[0], "alias": "review", **_SCOPE,
    })
    await asgi_post("/relay/sessions/name", {
        "runtime": "codex", "session_ref": targets[1], "alias": "review",
        "replace_existing": True, **_SCOPE,
    })
    await asgi_post("/relay/sessions/close", {
        "runtime": "codex", "session_ref": targets[2], **_SCOPE,
    })

    seen: list[dict] = []
    offset = 0
    total = None
    while True:
        current = await page(runtime="codex", offset=offset)
        total = current["total_count"] if total is None else total
        assert current["total_count"] == total
        seen.extend(current["recipients"])
        if not current["has_more"]:
            assert current["next_offset"] is None
            break
        assert current["next_offset"] > offset
        offset = current["next_offset"]

    repeated: list[str] = []
    offset = 0
    while True:
        current = await page(runtime="codex", offset=offset)
        repeated.extend(item["session_ref"] for item in current["recipients"])
        if not current["has_more"]:
            break
        offset = current["next_offset"]
    refs = [item["session_ref"] for item in seen]
    assert len(refs) == len(set(refs)) == len(targets)
    assert repeated == refs
    assert targets[2] not in refs
    assert all(item["runtime"] == "codex" for item in seen)
    assert all(item["exact_selector"] == f"codex:{item['session_ref']}" for item in seen)
    holder = next(item for item in seen if item["session_ref"] == targets[1])
    released = next(item for item in seen if item["session_ref"] == targets[0])
    assert holder["alias_selector"] == "codex:@review"
    assert "alias_selector" not in released
    assert any(item["title"].startswith("מפתח 日本語") for item in seen)

    all_sessions: list[dict] = []
    offset = 0
    while True:
        current = await page(runtime="codex", include_inactive=True, offset=offset)
        all_sessions.extend(current["recipients"])
        if not current["has_more"]:
            break
        offset = current["next_offset"]
    closed = next(item for item in all_sessions if item["session_ref"] == targets[2])
    assert closed["state"] == "closed"
    assert "alias_selector" not in closed
    assert (await page(runtime="codex", offset=999))["recipients"] == []

    sent, _ = await server.call_tool("pallium_relay_send", {
        "message": "canonical alias works", "recipient": holder["alias_selector"],
        "sender_runtime": "codex", "sender_session_ref": sender,
    })
    delivery = json.loads(sent[0].text)["deliveries"][0]
    assert delivery["recipient_session_ref"] == targets[1]

    exact, _ = await server.call_tool("pallium_relay_send", {
        "message": "exact fallback works", "recipient": released["exact_selector"],
        "sender_runtime": "codex", "sender_session_ref": sender,
    })
    exact_delivery = json.loads(exact[0].text)["deliveries"][0]
    assert exact_delivery["recipient_session_ref"] == targets[0]

    conflict, _ = await server.call_tool("pallium_relay_recipients", {
        "container_ref": "git:example.test/other", "actor_ref": _SCOPE["actor_ref"],
    })
    assert json.loads(conflict[0].text)["recipients"] == []
    other_actor, _ = await server.call_tool("pallium_relay_recipients", {
        "container_ref": _SCOPE["container_ref"], "actor_ref": "other-actor",
    })
    assert json.loads(other_actor[0].text)["recipients"] == []
