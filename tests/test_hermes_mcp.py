"""Caller-surface tests for the profile-scoped Hermes stdio MCP adapter."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("mcp", reason="mcp[cli] is required for real stdio coverage")

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from app.mcp.context import (
    PalliumContext,
    current_hermes_request,
)
from app.mcp.hermes import HERMES_RELAY_TOOLS, _read_identity, create_hermes_server, make_tool_adapter
from app.mcp.server import create_server


class _RelayHandler(BaseHTTPRequestHandler):
    client = None
    calls: list[tuple[str, dict]] = []
    lock = threading.Lock()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        with self.lock:
            self.calls.append((parsed.path, query))
        response = self.client.get(parsed.path, params=query)
        self._write_response(response)

    def do_POST(self) -> None:  # noqa: N802
        size = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(size) or b"{}")
        with self.lock:
            self.calls.append((self.path, payload))
        response = self.client.post(self.path, json=payload)
        self._write_response(response)

    def _write_response(self, response) -> None:
        raw = response.content
        self.send_response(response.status_code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args) -> None:
        return


def _identity(session_id: str, turn_id: str = "turn-1", **extra: object) -> dict:
    return {"pallium_hermes": {"session_id": session_id, "turn_id": turn_id, **extra}}


async def _exercise_stdio(base_url: str, *, peer_endpoint: str, reply_delivery: dict) -> dict:
    repo = str(Path(__file__).resolve().parents[1])
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": os.pathsep.join(filter(None, (repo, env.get("PYTHONPATH")))),
        # These hostile ambient values must not become this entry's fixed profile scope.
        "PALLIUM_BASE_URL": "http://127.0.0.1:1",
        "PALLIUM_AGENT_REF": "codex",
        "PALLIUM_THREAD_REF": "wrong-static-session",
        "PALLIUM_CONTAINER_REF": "git:test/wrong-container",
    })
    params = StdioServerParameters(
        command=os.sys.executable,
        args=[
            "-m", "app.mcp.hermes",
            "--base-url", base_url,
            "--container-ref", "git:test/hermes",
            "--actor-ref", "hermes-test-actor",
            "--visibility", "private",
        ],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            assert names == set(HERMES_RELAY_TOOLS)

            before = len(_RelayHandler.calls)
            missing = await session.call_tool("pallium_relay_address", {})
            malformed = await session.call_tool(
                "pallium_relay_address", {}, meta=_identity(" ", "turn-1")
            )
            conflicting = await session.call_tool(
                "pallium_relay_address",
                {},
                meta={**_identity("session-a", "turn-a"), "turn_id": "turn-b"},
            )
            bad_scope = await session.call_tool(
                "pallium_relay_address",
                {"container_ref": "git:test/other"},
                meta=_identity("session-a", "turn-a"),
            )
            assert missing.isError and malformed.isError and conflicting.isError and bad_scope.isError
            assert len(_RelayHandler.calls) == before

            valid = await session.call_tool(
                "pallium_relay_address", {}, meta=_identity("session-a", "turn-a")
            )
            assert not valid.isError, [item.text for item in valid.content if hasattr(item, "text")]
            address = json.loads(valid.content[0].text)
            assert address["runtime"] == "hermes"
            assert address["session_ref"] == "session-a"

            max_unicode_session = "ü" * 255
            maximum = await session.call_tool(
                "pallium_relay_address", {}, meta=_identity(max_unicode_session, "turn-max")
            )
            assert not maximum.isError
            before_over_max = len(_RelayHandler.calls)
            over_max = await session.call_tool(
                "pallium_relay_address", {}, meta=_identity("x" * 256, "turn-over")
            )
            assert over_max.isError
            assert len(_RelayHandler.calls) == before_over_max

            # Concurrent requests on one stdio session must keep their own trusted identity.
            await asyncio.gather(*[
                session.call_tool(
                    "pallium_relay_address", {}, meta=_identity(session_id, f"turn-{session_id}")
                )
                for session_id in ("session-concurrent-a", "session-concurrent-b")
            ])

            target_filter = await session.call_tool(
                "pallium_relay_recipients",
                {"runtime": "codex", "session_ref": "other-task"},
                meta=_identity("session-a", "turn-target"),
            )
            assert not target_filter.isError

            before_send = len(_RelayHandler.calls)
            wrong_sender = await session.call_tool(
                "pallium_relay_send",
                {
                    "message": "should not send", "recipient": "@peer",
                    "sender_runtime": "hermes", "sender_session_ref": "session-other",
                },
                meta=_identity("session-a", "turn-send"),
            )
            assert wrong_sender.isError
            assert not any(path == "/relay/messages" for path, _ in _RelayHandler.calls[before_send:])
            wrong_container = await session.call_tool(
                "pallium_relay_send",
                {
                    "message": "should not send", "recipient": "@peer",
                    "sender_runtime": "hermes", "sender_session_ref": "session-a",
                    "container_ref": "git:test/other",
                },
                meta=_identity("session-a", "turn-send"),
            )
            assert wrong_container.isError
            assert not any(path == "/relay/messages" for path, _ in _RelayHandler.calls[before_send:])

            sent = await session.call_tool(
                "pallium_relay_send",
                {
                    "message": "héllo 任务", "recipient": peer_endpoint,
                    "sender_runtime": "hermes", "sender_session_ref": "session-a",
                    "container_ref": "git:test/hermes",
                },
                meta=_identity("session-a", "turn-send"),
            )
            assert not sent.isError
            sent_result = json.loads(sent.content[0].text)

            before_reply = len(_RelayHandler.calls)
            wrong_reply = await session.call_tool(
                "pallium_relay_reply",
                {"delivery_id": "delivery-other", "message": "reply"},
                meta=_identity("session-a", "turn-reply", reply={
                    "delivery_id": reply_delivery["delivery_id"], "receipt": reply_delivery["receipt"],
                }),
            )
            assert wrong_reply.isError
            assert not any(path == "/relay/replies" for path, _ in _RelayHandler.calls[before_reply:])
            wrong_receipt = await session.call_tool(
                "pallium_relay_reply",
                {"delivery_id": reply_delivery["delivery_id"], "message": "reply", "receipt": "forged"},
                meta=_identity("session-a", "turn-reply", reply={
                    "delivery_id": reply_delivery["delivery_id"], "receipt": reply_delivery["receipt"],
                }),
            )
            assert wrong_receipt.isError
            assert not any(path == "/relay/replies" for path, _ in _RelayHandler.calls[before_reply:])

            replied = await session.call_tool(
                "pallium_relay_reply",
                {"delivery_id": reply_delivery["delivery_id"], "message": "réponse"},
                meta=_identity("session-a", "turn-reply", reply={
                    "delivery_id": reply_delivery["delivery_id"], "receipt": reply_delivery["receipt"],
                }),
            )
            assert not replied.isError
            return {"tools": names, "sent": sent_result}


def test_dedicated_hermes_stdio_binds_identity_and_reuses_relay_tools(client) -> None:
    _RelayHandler.client = client
    _RelayHandler.calls = []
    scope = {"container_ref": "git:test/hermes"}

    def register(runtime: str, session_ref: str) -> dict:
        response = client.post("/relay/turn", json={
            "runtime": runtime, "session_ref": session_ref, **scope,
        })
        assert response.status_code == 200, response.text
        return response.json()["session"]

    hermes_endpoints = {
        name: register("hermes", name)
        for name in ("session-a", "ü" * 255, "session-concurrent-a", "session-concurrent-b")
    }
    codex_peer = register("codex", "other-task")
    register("codex", "reply-sender")
    incoming = client.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "reply-sender",
        "recipient": hermes_endpoints["session-a"]["endpoint_id"],
        "payload": "question", **scope,
    })
    assert incoming.status_code == 200, incoming.text
    delivered = client.post("/relay/turn", json={
        "runtime": "hermes", "session_ref": "session-a",
        "max_chars": 2400, "max_messages": 1, **scope,
    })
    assert delivered.status_code == 200, delivered.text
    reply_delivery = delivered.json()["deliveries"][0]

    server = ThreadingHTTPServer(("127.0.0.1", 0), _RelayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = asyncio.run(_exercise_stdio(
            f"http://127.0.0.1:{server.server_port}",
            peer_endpoint=codex_peer["endpoint_id"],
            reply_delivery=reply_delivery,
        ))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    recipient_calls = [payload for path, payload in _RelayHandler.calls if path == "/relay/sessions"]
    address_calls = [query for query in recipient_calls if query["runtime"] == ["hermes"]]
    assert {query["session_ref"][0] for query in address_calls} == {
        "session-a", "ü" * 255, "session-concurrent-a", "session-concurrent-b",
    }
    assert all(query["runtime"] == ["hermes"] for query in address_calls)
    assert all(query["container_ref"] == ["git:test/hermes"] for query in address_calls)
    assert any(
        query["runtime"] == ["codex"] and query["session_ref"] == ["other-task"]
        for query in recipient_calls
    )

    sends = [payload for path, payload in _RelayHandler.calls if path == "/relay/messages"]
    assert len(sends) == 1
    assert sends[0]["payload"] == "héllo 任务"
    assert sends[0]["sender_runtime"] == "hermes"
    assert sends[0]["sender_session_ref"] == "session-a"
    assert sends[0]["container_ref"] == "git:test/hermes"

    replies = [payload for path, payload in _RelayHandler.calls if path == "/relay/replies"]
    assert len(replies) == 1
    assert replies[0]["delivery_id"] == reply_delivery["delivery_id"]
    assert replies[0]["receipt"] == reply_delivery["receipt"]
    assert replies[0]["payload"] == "réponse"
    assert replies[0]["container_ref"] == "git:test/hermes"

    sent_message_id = result["sent"]["message_id"]
    sent_status = client.get(f"/relay/messages/{sent_message_id}", params=scope)
    assert sent_status.status_code == 200, sent_status.text
    assert sent_status.json()["payload"] == "héllo 任务"
    assert sent_status.json()["deliveries"][0]["state"] == "pending"
    replied_status = client.get(f"/relay/messages/{incoming.json()['message_id']}", params=scope)
    assert replied_status.status_code == 200, replied_status.text
    assert replied_status.json()["deliveries"][0]["state"] == "delivered"
    peer_inbox = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "reply-sender", "max_chars": 2400, **scope,
    })
    assert peer_inbox.status_code == 200, peer_inbox.text
    assert any(item["payload"] == "réponse" for item in peer_inbox.json()["deliveries"])


def test_default_server_registration_is_unchanged() -> None:
    names = {tool.name for tool in asyncio.run(create_server().list_tools())}
    assert "pallium_query" in names
    assert "pallium_relay_receive" in names


@pytest.mark.parametrize("base_url", [
    "https://127.0.0.1:19836",
    "http://example.com:19836",
    "http://127.0.0.2:19836",
    "http://user:secret@127.0.0.1:19836",
    "http://127.0.0.1:19836/path",
    "http://127.0.0.1:19836/?token=x",
    " http://127.0.0.1:19836",
    "http://127.0.0.1:70000",
])
def test_hermes_server_rejects_non_private_loopback_topology(base_url: str) -> None:
    with pytest.raises(ValueError):
        create_hermes_server(
            base_url=base_url,
            container_ref="git:test/hermes",
            actor_ref="hermes-test-actor",
            visibility="private",
        )


@pytest.mark.parametrize(("actor_ref", "visibility"), [
    (" actor ", "private"),
    ("hermes", "shared"),
    ("x" * 256, "private"),
])
def test_hermes_server_rejects_invalid_fixed_scope(actor_ref: str, visibility: str) -> None:
    with pytest.raises(ValueError):
        create_hermes_server(
            base_url="http://127.0.0.1:19836",
            container_ref="git:test/hermes",
            actor_ref=actor_ref,
            visibility=visibility,
        )


def test_reply_admission_delivery_id_has_api_bound() -> None:
    with pytest.raises(ValueError, match="invalid admitted reply metadata"):
        _read_identity(_identity("session", reply={
            "delivery_id": "d" * 65,
            "receipt": "r" * 64,
        }), "pallium_relay_reply")


def test_bound_hermes_context_resets_after_handler_exception() -> None:
    context = PalliumContext(
        base_url="http://127.0.0.1:19836",
        container_ref="git:test/hermes",
        actor_ref="hermes-test-actor",
        agent_ref="hermes",
        visibility="private",
    )

    def failing_handler():
        assert current_hermes_request() is not None
        raise RuntimeError("handler failed")

    adapter = make_tool_adapter(context)
    guarded = adapter("pallium_relay_address", failing_handler, lambda: type(
        "RequestContext", (), {"request_context": type("Meta", (), {"meta": _identity("session")})()}
    )())
    assert guarded is not None
    assert current_hermes_request() is None

    async def invoke() -> None:
        with pytest.raises(RuntimeError, match="handler failed"):
            await guarded()
        assert current_hermes_request() is None

    asyncio.run(invoke())
