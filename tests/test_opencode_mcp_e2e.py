"""OpenCode request identity through real MCP transports and the SQLite HTTP API."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("mcp")
from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from pydantic import model_serializer

pytestmark = pytest.mark.slow  # Bounded readiness polling for the real TCP listener.

CONTAINER = "git:example.test/team/mcp-identity"
WORK = {"scope_ref": "tracker:v1:example.test#queue", "local_ref": "item:任务-α"}
SELF_TOOLS = {
    "pallium_relay_address": {},
    "pallium_relay_work_refs": {},
    "pallium_relay_attach_work_ref": WORK,
    "pallium_relay_detach_work_ref": WORK,
    "pallium_relay_receive": {},
}


def _meta(session_id):
    return {"ai.opencode/sessionID": session_id}


def _environment(base_url, **overrides):
    # Do not inherit credentials, native hooks, runtime identity or bridge capabilities.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PALLIUM_", "CODEX_", "CLAUDE_", "OPENCODE_"))
           and not key.endswith("API_KEY")}
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[1]),
               PALLIUM_BASE_URL=base_url, PALLIUM_CONTAINER_REF=CONTAINER)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


@pytest.fixture
def relay_http(client):
    """Reuse the real app/temporary SQLite fixture, with a child-accessible HTTP port."""
    calls = []
    lock = threading.Lock()

    class Forward(BaseHTTPRequestHandler):
        barrier = None

        def forward(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            parsed = urlparse(self.path)
            value = json.loads(raw) if raw else parse_qs(parsed.query)
            with lock:
                calls.append((self.command, parsed.path, value))
            if self.barrier is not None and parsed.path == "/relay/sessions":
                self.barrier.wait(timeout=10)
            response = client.request(self.command, self.path, content=raw or None,
                                      headers={"Content-Type": "application/json"})
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = do_POST = forward

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Forward)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls, Forward
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def _remote_mcp(monkeypatch, env, requests=None):
    """A real loopback Streamable HTTP listener serving production create_server."""
    import uvicorn
    from app.mcp.server import create_server

    with monkeypatch.context() as patch:
        for key in set(os.environ) | set(env):
            if key.startswith(("PALLIUM_", "CODEX_", "CLAUDE_", "OPENCODE_")):
                patch.delenv(key, raising=False)
        for key, value in env.items():
            if key.startswith(("PALLIUM_", "CODEX_", "CLAUDE_", "OPENCODE_")):
                patch.setenv(key, value)
        before = dict(os.environ)
        mcp = create_server(host="127.0.0.1")
        mcp.settings.json_response = True
        production = mcp.streamable_http_app()

        async def observed(scope, receive, send):
            raw = bytearray()

            async def read():
                message = await receive()
                if requests is not None and message["type"] == "http.request":
                    # Observation only: forward the identical ASGI message to production.
                    raw.extend(message.get("body", b""))
                    if raw and not message.get("more_body"):
                        requests.append(json.loads(raw))
                return message
            await production(scope, read, send)

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(observed, log_level="error", lifespan="on"))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 15
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(.01)
                assert server.started, "isolated MCP HTTP listener did not start"
                yield f"http://127.0.0.1:{port}/mcp"
                assert dict(os.environ) == before, "request identity must not mutate process environment"
            finally:
                server.should_exit = True
                thread.join(timeout=15)
                assert not thread.is_alive(), "isolated MCP HTTP listener did not stop"


@asynccontextmanager
async def _session(transport, monkeypatch, env):
    if transport == "stdio":
        # main returns on EOF; check the child's environment, not just the parent's.
        program = ("import os,sys; from app.mcp.server import main; "
                   "before=dict(os.environ); main(); assert dict(os.environ)==before; "
                   "print('MCP_ENVIRONMENT_UNCHANGED',file=sys.stderr,flush=True)")
        params = StdioServerParameters(command=os.sys.executable, args=["-c", program],
                                       env={**env, "PALLIUM_MCP_TRANSPORT": "stdio"})
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
            async with stdio_client(params, errlog=log) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
            log.seek(0)
            assert "MCP_ENVIRONMENT_UNCHANGED" in log.read(), "child did not confirm unchanged environment on EOF"
    else:
        with _remote_mcp(monkeypatch, env) as url:
            async with streamable_http_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session


def _register(client, session_id, runtime="opencode"):
    response = client.post("/relay/turn", json={"runtime": runtime,
        "session_ref": session_id, "container_ref": CONTAINER})
    assert response.status_code == 200, response.text
    return response.json()["session"]


def _read_refs(client, session_id):
    response = client.get("/relay/sessions/work-refs", params={"runtime": "opencode",
        "session_ref": session_id, "container_ref": CONTAINER})
    assert response.status_code == 200, response.text
    return response.json()["work_refs"]


async def _call(session, tool, args=None, meta=None):
    result = await session.call_tool(tool, args or {}, meta=meta)
    assert not result.isError, result.content
    body = json.loads(result.content[0].text)
    assert "error" not in body, body
    return body


async def _exact_metadata_call(session, tool, args, meta):
    # call_tool/send_request normally serialize exclude_none=True, which erases
    # a present null namespace and would test fallback, not the invalid wire field.
    class ExactMetadataRequest(types.ClientRequest):
        @model_serializer(mode="wrap")
        def serialize(self, handler):
            request = handler(self)
            if meta is not None:
                request["params"]["_meta"] = meta
            return request

    request = ExactMetadataRequest(types.CallToolRequest(
        params=types.CallToolRequestParams(name=tool, arguments=args)))
    return await session.send_request(request, types.CallToolResult)


@pytest.mark.parametrize("transport", ["stdio", "http"])
@pytest.mark.parametrize("configured", ["unset", "opencode", "unset-stale-thread"])
def test_request_identity_concurrency_work_refs_and_recovery(
    client, relay_http, monkeypatch, transport, configured,
):
    base, calls, forward = relay_http
    ids = ("session-a", "session-b", "任务-α")
    endpoints = {value: _register(client, value)["endpoint_id"] for value in (*ids, "x", "ü" * 255)}
    _register(client, "sender", runtime="codex")
    messages = {}
    for value in ids:
        response = client.post("/relay/messages", json={"sender_runtime": "codex",
            "sender_session_ref": "sender", "recipient": endpoints[value],
            "payload": f"only {value}", "container_ref": CONTAINER})
        assert response.status_code == 200, response.text
        messages[value] = response.json()["message_id"]
    options = {} if configured == "unset" else {"PALLIUM_THREAD_REF": "stale-thread"}
    if configured == "opencode":
        options["PALLIUM_AGENT_REF"] = "opencode"
    env = _environment(base, **options)

    async def exercise():
        async with _session(transport, monkeypatch, env) as session:
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            for name in SELF_TOOLS:
                assert not {"request_ctx", "session_ref", "thread_ref", "runtime"} & set(
                    tools[name].inputSchema.get("properties", {}))

            for _ in range(2):
                forward.barrier = threading.Barrier(3)
                try:
                    results = await asyncio.gather(*[
                        _call(session, "pallium_relay_address", meta=_meta(value)) for value in ids])
                finally:
                    forward.barrier = None
                for value, result in zip(ids, results):
                    assert result == {"runtime": "opencode", "session_ref": value,
                        "exact_selector": endpoints[value], "relay_name_state": "unnamed"}
            # Sequential reuse must not retain the preceding concurrent request.
            for value in (*reversed(ids), "x", "ü" * 255):
                result = await _call(session, "pallium_relay_address", meta={**_meta(value), "unrelated": "ignored"})
                assert result["exact_selector"] == endpoints[value]

            attached = await asyncio.gather(*[
                _call(session, "pallium_relay_attach_work_ref", WORK, _meta(value)) for value in ids])
            for value, result in zip(ids, attached):
                duplicate = await _call(session, "pallium_relay_attach_work_ref", WORK, _meta(value))
                assert duplicate["attached"]["work_ref"] == result["attached"]["work_ref"]
                rows = (await _call(session, "pallium_relay_work_refs", meta=_meta(value)))["work_refs"]
                assert len(rows) == 1
                assert rows == _read_refs(client, value)
                assert rows[0]["local_ref"] == WORK["local_ref"]
            assert _read_refs(client, "ü" * 255) == []

            received = await asyncio.gather(*[
                _call(session, "pallium_relay_receive", meta=_meta(value)) for value in ids])
            for value, result in zip(ids, received):
                assert len(result["deliveries"]) == 1
                delivery = result["deliveries"][0]
                assert delivery["payload"] == f"only {value}"
                assert delivery["message_id"] == messages[value]
                assert delivery["receipt"] and "claim_token" not in delivery
                wrong = await session.call_tool("pallium_relay_ack", {
                    "delivery_id": delivery["delivery_id"], "receipt": "wrong-receipt"})
                assert wrong.isError
                status = client.get(f"/relay/messages/{messages[value]}", params={"container_ref": CONTAINER})
                assert status.json()["deliveries"][0]["state"] != "delivered"
                args = {key: delivery[key] for key in ("delivery_id", "receipt")}
                assert (await _call(session, "pallium_relay_ack", args))["already_delivered"] is False
                assert (await _call(session, "pallium_relay_ack", args))["already_delivered"] is True
                status = await _call(session, "pallium_relay_status", {"message_id": messages[value]})
                assert status["deliveries"][0]["state"] == "delivered"
                persisted = client.get(f"/relay/messages/{messages[value]}", params={"container_ref": CONTAINER})
                assert persisted.json()["deliveries"][0]["state"] == "delivered"
                assert (await _call(session, "pallium_relay_receive", meta=_meta(value)))["deliveries"] == []

            for value in ids:
                assert (await _call(session, "pallium_relay_detach_work_ref", WORK, _meta(value)))["detached"] is True
                assert (await _call(session, "pallium_relay_detach_work_ref", WORK, _meta(value)))["detached"] is False
                assert (await _call(session, "pallium_relay_work_refs", meta=_meta(value)))["work_refs"] == []
                assert _read_refs(client, value) == []
                closed = client.post("/relay/sessions/close", json={"runtime": "opencode",
                    "session_ref": value, "container_ref": CONTAINER})
                assert closed.status_code == 200, closed.text
                assert (await _call(session, "pallium_relay_address", meta=_meta(value)))["exact_selector"] == endpoints[value]
                readback = client.get("/relay/sessions", params={"runtime": "opencode",
                    "session_ref": value, "container_ref": CONTAINER, "include_inactive": True})
                assert readback.json()[0]["state"] == "closed"

    asyncio.run(exercise())
    identity_calls = [payload for _, path, payload in calls if path in {
        "/relay/turn", "/relay/sessions/work-refs/attach", "/relay/sessions/work-refs/detach"}]
    assert identity_calls and all(payload["runtime"] == "opencode" for payload in identity_calls)
    assert {payload["session_ref"] for payload in identity_calls} == set(ids)
    assert env.get("PALLIUM_THREAD_REF") == options.get("PALLIUM_THREAD_REF")


@pytest.mark.parametrize("transport", ["stdio", "http"])
@pytest.mark.parametrize("configured", [False, True])
def test_invalid_metadata_rejects_all_self_tools_before_backend_and_recovers(
    client, relay_http, monkeypatch, transport, configured,
):
    base, calls, _ = relay_http
    endpoint = _register(client, "valid")["endpoint_id"]
    options = {"PALLIUM_AGENT_REF": "opencode", "PALLIUM_THREAD_REF": "valid"} if configured else {}
    invalid = [_meta(value) for value in (
        None, "", " ", " leading", "trailing ", "line\nbreak", "tab\tvalue", "null\0value",
        "control\x7f", "zero\u200bwidth", "x" * 256, "ü" * 256, 7, True, [], {},
    )]
    invalid += [{**_meta("valid"), **codex} for codex in (
        {"threadId": "valid"}, {"threadId": "other"}, {"turnId": "turn"},
        {"x-codex-turn-metadata": {"session_id": "valid"}},
        {"x-codex-turn-metadata": None},
        {"pallium_hermes": {"session_id": "valid", "turn_id": "turn"}},
    )]
    if not configured:
        invalid += [None, {}, {"unknown": "ignored"}, {"sessionID": "valid"}]

    async def exercise():
        async with _session(transport, monkeypatch, _environment(base, **options)) as session:
            before = len(calls)
            for meta in invalid:
                for tool, args in SELF_TOOLS.items():
                    result = await _exact_metadata_call(session, tool, args, meta)
                    assert result.isError, (tool, meta, result.content)
                    assert len(calls) == before, (tool, meta, calls[before:])
            good = await _call(session, "pallium_relay_address", meta=_meta("valid"))
            assert good["exact_selector"] == endpoint
            missing = await session.call_tool("pallium_relay_address", {}, meta=_meta("not-registered"))
            assert missing.isError
            assert "current Relay endpoint is not registered" in missing.content[0].text
            assert client.get("/relay/sessions", params={"runtime": "opencode",
                "session_ref": "not-registered", "container_ref": CONTAINER}).json() == []
            assert _read_refs(client, "valid") == []
            assert (await _call(session, "pallium_relay_address", meta=_meta("valid")))["exact_selector"] == endpoint

    asyncio.run(exercise())


@pytest.mark.parametrize("transport", ["stdio", "http"])
@pytest.mark.parametrize("runtime", ["claude-code", "codex", "hermes", "opencode"])
def test_runtime_conflicts_and_metadata_absent_legacy_compatibility(
    client, relay_http, monkeypatch, transport, runtime,
):
    base, calls, _ = relay_http
    expected = _register(client, "legacy", runtime=runtime)["endpoint_id"]
    env = _environment(base, PALLIUM_AGENT_REF=runtime, PALLIUM_THREAD_REF="legacy",
                       CODEX_THREAD_ID="hostile-ambient-codex")

    async def exercise():
        async with _session(transport, monkeypatch, env) as session:
            before = len(calls)
            if runtime != "opencode":
                for tool, args in SELF_TOOLS.items():
                    refused = await session.call_tool(tool, args, meta=_meta("other"))
                    assert refused.isError
                assert len(calls) == before
            # Codex still requires its own per-request metadata, not stale env values.
            meta = {"threadId": "legacy"} if runtime == "codex" else None
            address = await _call(session, "pallium_relay_address", meta=meta)
            assert address["runtime"] == runtime and address["exact_selector"] == expected

    asyncio.run(exercise())


@pytest.mark.parametrize("transport", ["stdio", "http"])
def test_expired_receive_claim_recovers_without_any_plugin_hook(client, relay_http, monkeypatch, transport):
    from storage import sqlite_relay

    base, _, _ = relay_http
    endpoint = _register(client, "recovery")["endpoint_id"]
    _register(client, "sender", runtime="codex")
    sent = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": endpoint, "payload": "recover once ✓", "container_ref": CONTAINER})
    assert sent.status_code == 200, sent.text
    message_id = sent.json()["message_id"]

    async def exercise():
        async with _session(transport, monkeypatch, _environment(base)) as session:
            initial = (await _call(session, "pallium_relay_receive", meta=_meta("recovery")))["deliveries"][0]
            assert initial["claim_attempt"] == 1 and initial["possible_redelivery"] is False
            assert (await _call(session, "pallium_relay_receive", meta=_meta("recovery")))["deliveries"] == []
            native_now = sqlite_relay._now
            monkeypatch.setattr(sqlite_relay, "_now", lambda value=None:
                native_now(value) if value else native_now() + timedelta(seconds=61))
            recovered = (await _call(session, "pallium_relay_receive", meta=_meta("recovery")))["deliveries"][0]
            assert recovered["delivery_id"] == initial["delivery_id"]
            assert recovered["message_id"] == message_id and recovered["payload"] == "recover once ✓"
            assert recovered["claim_attempt"] == 2 and recovered["possible_redelivery"] is True
            assert "claim_token" not in recovered and recovered["receipt"]
            args = {key: recovered[key] for key in ("delivery_id", "receipt")}
            assert (await _call(session, "pallium_relay_ack", args))["already_delivered"] is False
            assert (await _call(session, "pallium_relay_status", {"message_id": message_id}))["deliveries"][0]["state"] == "delivered"
            persisted = client.get(f"/relay/messages/{message_id}", params={"container_ref": CONTAINER})
            assert persisted.json()["deliveries"][0]["state"] == "delivered"

    asyncio.run(exercise())


def test_hermes_bound_stdio_identity_keeps_precedence(client, relay_http):
    base, calls, _ = relay_http
    endpoint = _register(client, "hermes-session", runtime="hermes")["endpoint_id"]
    params = StdioServerParameters(command=os.sys.executable, args=["-m", "app.mcp.hermes",
        "--base-url", base, "--container-ref", CONTAINER, "--actor-ref", "fixture-actor",
        "--visibility", "private"], env=_environment(base, PALLIUM_AGENT_REF="opencode",
        PALLIUM_THREAD_REF="stale-thread"))

    async def exercise():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for value in ("other-opencode-session", None, "invalid\nvalue"):
                    result = await _call(session, "pallium_relay_address", meta={**_meta(value),
                        "pallium_hermes": {"session_id": "hermes-session", "turn_id": "turn-1"}})
                    assert result["runtime"] == "hermes" and result["exact_selector"] == endpoint

    asyncio.run(exercise())
    assert len(calls) == 3 and all(value["runtime"] == ["hermes"] for _, _, value in calls)


@pytest.mark.parametrize("transport", ["stdio", "http"])
@pytest.mark.parametrize("problem", ["conflict", "missing", "invalid-config", "unconfigured"])
def test_scope_and_unconfigured_fail_before_backend(client, relay_http, monkeypatch, transport, problem):
    base, calls, _ = relay_http
    options = {}
    if problem == "missing":
        options["PALLIUM_CONTAINER_REF"] = None
    elif problem == "invalid-config":
        options["PALLIUM_CONTAINER_REF"] = " "
    elif problem == "unconfigured":
        options["PALLIUM_BASE_URL"] = None

    async def exercise():
        async with _session(transport, monkeypatch, _environment(base, **options)) as session:
            before = len(calls)
            for tool, args in SELF_TOOLS.items():
                supplied = {**args, **({"container_ref": "git:example.test/other"} if problem == "conflict" else {})}
                meta = {**_meta("valid"), "container_ref": CONTAINER} if problem == "missing" else _meta("valid")
                result = await session.call_tool(tool, supplied, meta=meta)
                assert result.isError
            assert len(calls) == before
            if problem == "missing":
                _register(client, "valid")
                result = await _call(session, "pallium_relay_address", {"container_ref": CONTAINER}, _meta("valid"))
                assert result["session_ref"] == "valid"

    asyncio.run(exercise())
