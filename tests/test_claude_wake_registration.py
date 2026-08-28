from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from api.routes import create_router
from app.config import AppConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES
from core.claude_wake import (
    ClaudeWakeRegistry,
    MAX_ACTOR_CHARS,
    MAX_CONTAINER_CHARS,
    MAX_RUNTIME_CHARS,
    MAX_SESSION_CHARS,
    MAX_SOCKET_CHARS,
    MAX_TOKEN_CHARS,
    TTL_SECONDS,
)
from tests.test_claude_code_integration import _load_claude_hook


PAYLOAD = {
    "runtime": "claude-code",
    "session_ref": "session-α",
    "container_ref": "git:example/repo",
    "actor_ref": "local",
    "socket_path": r"\\.\pipe\claude",
    "token": "test-token",
}


def _client(registry: ClaudeWakeRegistry, peer: tuple[str, int] = ("127.0.0.1", 50000)) -> TestClient:
    app = FastAPI()
    app.include_router(create_router(object(), claude_wake_registry=registry))
    return TestClient(app, client=peer)


def test_loopback_registration_is_secret_free_and_scope_bound() -> None:
    registry = ClaudeWakeRegistry()
    secret = "never-in-response"
    payload = {**PAYLOAD, "token": secret}
    response = _client(registry).post("/internal/claude-wake/register", json=payload)
    assert response.status_code == 204
    assert response.content == b""

    observed: list[tuple[str, str]] = []
    assert registry.probe(
        runtime=PAYLOAD["runtime"],
        session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"],
        actor_ref=PAYLOAD["actor_ref"],
        transport=lambda socket_path, token: observed.append((socket_path, token)) or True,
    )
    assert observed == [(PAYLOAD["socket_path"], secret)]
    assert not registry.probe(
        runtime=PAYLOAD["runtime"],
        session_ref=PAYLOAD["session_ref"],
        container_ref="git:other/repo",
        actor_ref=PAYLOAD["actor_ref"],
        transport=lambda *_: pytest.fail("scope mismatch must not transport"),
    )


@pytest.mark.parametrize(
    "peer,payload,status",
    [
        (("203.0.113.10", 50000), PAYLOAD, 403),
        (("127.0.0.1", 50000), {**PAYLOAD, "session_ref": "bad\nvalue"}, 400),
        (("127.0.0.1", 50000), {**PAYLOAD, "token": "x" * 8193}, 400),
    ],
)
def test_registration_rejects_untrusted_or_invalid_input_without_echoing_secret(
    peer: tuple[str, int], payload: dict[str, str], status: int,
) -> None:
    secret = payload["token"]
    response = _client(ClaudeWakeRegistry(), peer).post("/internal/claude-wake/register", json=payload)
    assert response.status_code == status
    assert secret not in response.text


def test_registration_accepts_ipv6_loopback() -> None:
    response = _client(ClaudeWakeRegistry(), ("::1", 50000)).post(
        "/internal/claude-wake/register", json=PAYLOAD,
    )
    assert response.status_code == 204


def test_replace_expiry_and_callback_reentry_are_generation_safe() -> None:
    now = [0.0]
    registry = ClaudeWakeRegistry(clock=lambda: now[0])
    registry.register(**PAYLOAD)
    now[0] += TTL_SECONDS - 1
    registry.register(**{**PAYLOAD, "token": "replacement"})
    now[0] += 2

    completed = threading.Event()

    def transport(_socket_path: str, _token: str) -> bool:
        worker = threading.Thread(target=lambda: registry.register(**{**PAYLOAD, "token": "third"}))
        worker.start()
        worker.join(timeout=1)
        assert not worker.is_alive()
        completed.set()
        return True

    assert registry.probe(
        runtime=PAYLOAD["runtime"],
        session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"],
        actor_ref=PAYLOAD["actor_ref"],
        transport=transport,
    )
    assert completed.is_set()
    assert not registry.probe(
        runtime=PAYLOAD["runtime"],
        session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"],
        actor_ref=PAYLOAD["actor_ref"],
        transport=None,
    )
    now[0] += TTL_SECONDS + 1
    assert not registry.probe(
        runtime=PAYLOAD["runtime"],
        session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"],
        actor_ref=PAYLOAD["actor_ref"],
        transport=lambda *_: pytest.fail("expired credentials must not transport"),
    )


def test_session_start_and_stop_refresh_before_early_return(monkeypatch: pytest.MonkeyPatch) -> None:
    start = _load_claude_hook("session_start", monkeypatch)
    start_calls: list[tuple[object, object, object]] = []
    monkeypatch.setattr(start, "read_hook_input", lambda: {"cwd": ".", "session_id": "session-1"})
    monkeypatch.setattr(start, "derive_container_ref", lambda _cwd: "git:example/repo")
    monkeypatch.setattr(start, "derive_actor_ref", lambda: "local")
    monkeypatch.setattr(start, "pin_container", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(start, "register_claude_wake", lambda *args: start_calls.append(args))
    monkeypatch.setattr(start, "_fetch_orientation", lambda *_args: [])
    with pytest.raises(SystemExit) as exit_info:
        start.main()
    assert exit_info.value.code == 0
    assert start_calls == [("session-1", "git:example/repo", "local")]

    stop = _load_claude_hook("stop", monkeypatch)
    stop_calls: list[tuple[object, object, object]] = []
    monkeypatch.setattr(stop, "read_hook_input", lambda: {"cwd": ".", "session_id": "session-1", "transcript_path": ""})
    monkeypatch.setattr(stop, "resolve_container_ref", lambda *_args: "git:example/repo")
    monkeypatch.setattr(stop, "derive_actor_ref", lambda: "local")
    monkeypatch.setattr(stop, "register_claude_wake", lambda *args: stop_calls.append(args))
    stop.main()
    assert stop_calls == [("session-1", "git:example/repo", "local")]


def test_hook_registration_suppresses_credential_on_transport_failure(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    common = _load_claude_hook("common", monkeypatch)
    secret = "never-print-this"
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", r"\\.\pipe\claude")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", secret)
    monkeypatch.setattr(common.urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(secret)))
    assert not common.register_claude_wake("session", "git:example/repo", "local")
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err

def test_session_start_subprocess_registers_through_loopback_without_secret_output(tmp_path: Path) -> None:
    registry = ClaudeWakeRegistry()
    received: list[dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            if self.path == "/internal/claude-wake/register":
                registry.register(**payload)
                received.append(payload)
                self.send_response(204)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
            self.end_headers()
            if self.path == "/query":
                self.wfile.write(b'{"injectable_blocks": []}')

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    secret = "subprocess-secret"
    try:
        payload = json.dumps({"cwd": str(tmp_path), "session_id": "subprocess-session", "source": "startup"})
        env = {
            **os.environ,
            "PALLIUM_PORT": str(server.server_port),
            "CLAUDE_CODE_MESSAGING_SOCKET": r"\\.\pipe\claude",
            "CLAUDE_CODE_MESSAGING_TOKEN": secret,
        }
        result = subprocess.run(
            [sys.executable, "integrations/claude-code/hooks/session_start.py"],
            input=payload,
            text=True,
            capture_output=True,
            env=env,
            check=False,
            timeout=10,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
    assert result.returncode == 0
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert len(received) == 1
    assert registry.probe(
        runtime="claude-code",
        session_ref="subprocess-session",
        container_ref=received[0]["container_ref"],
        actor_ref=received[0]["actor_ref"],
        transport=lambda socket_path, token: socket_path == r"\\.\pipe\claude" and token == secret,
    )


def test_app_instances_have_separate_memory_only_registries(tmp_path: Path) -> None:
    def config(name: str) -> AppConfig:
        return AppConfig(
            storage_backend="sqlite",
            sqlite_url=f"sqlite:///{tmp_path / name}",
            default_use_case="demo_agent_memory",
            semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(enabled=False),
        )

    first = create_app(config("first.db"))
    second = create_app(config("second.db"))
    assert first.state.claude_wake_registry is not second.state.claude_wake_registry

def _registration_endpoint(registry: ClaudeWakeRegistry):
    app = FastAPI()
    app.include_router(create_router(object(), claude_wake_registry=registry))
    return next(route.endpoint for route in app.routes if route.path == "/internal/claude-wake/register")


def test_streaming_registration_rejects_missing_length_overflow_negative_length_and_client_none() -> None:
    endpoint = _registration_endpoint(ClaudeWakeRegistry())

    async def invoke(chunks: list[bytes], *, client, content_length: str | None = None):
        remaining = list(chunks)

        async def receive():
            body = remaining.pop(0)
            return {"type": "http.request", "body": body, "more_body": bool(remaining)}

        headers = [] if content_length is None else [(b"content-length", content_length.encode())]
        request = Request({"type": "http", "method": "POST", "path": "/internal/claude-wake/register", "headers": headers, "client": client}, receive)
        return await endpoint(request)

    with pytest.raises(HTTPException) as overflow:
        asyncio.run(invoke([b"x" * 16_000, b"x" * 1_000], client=("127.0.0.1", 1)))
    assert overflow.value.status_code == 400
    with pytest.raises(HTTPException) as negative:
        asyncio.run(invoke([b"{}"], client=("127.0.0.1", 1), content_length="-1"))
    assert negative.value.status_code == 400
    with pytest.raises(HTTPException) as absent_client:
        asyncio.run(invoke([b"{}"], client=None))
    assert absent_client.value.status_code == 403


@pytest.mark.parametrize("body", [b"{", b"[]", b'{"runtime":"claude-code"}', b'{"extra":true}'])
def test_registration_malformed_wrong_shape_missing_or_extra_is_secret_free(body: bytes) -> None:
    secret = "shape-secret"
    response = _client(ClaudeWakeRegistry()).post("/internal/claude-wake/register", content=body + secret.encode() if body == b"{" else body)
    assert response.status_code == 400
    assert secret not in response.text


@pytest.mark.parametrize(
    "field,maximum",
    [
        ("runtime", MAX_RUNTIME_CHARS),
        ("session_ref", MAX_SESSION_CHARS),
        ("container_ref", MAX_CONTAINER_CHARS),
        ("actor_ref", MAX_ACTOR_CHARS),
        ("socket_path", MAX_SOCKET_CHARS),
        ("token", MAX_TOKEN_CHARS),
    ],
)
def test_registration_validates_every_field_boundary(field: str, maximum: int) -> None:
    client = _client(ClaudeWakeRegistry())
    for value in ("", "x" * (maximum + 1), "safe\x00value"):
        response = client.post("/internal/claude-wake/register", json={**PAYLOAD, field: value})
        assert response.status_code == 400
        if value:
            assert value not in response.text


@pytest.mark.parametrize("case", ["missing", "none", "empty", "oversized"])
def test_stop_refreshes_before_every_early_return(case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    stop = _load_claude_hook("stop", monkeypatch)
    calls: list[tuple[object, object, object]] = []
    payload = {"cwd": ".", "session_id": "session-1", "transcript_path": "" if case == "missing" else "turn.jsonl"}
    monkeypatch.setattr(stop, "read_hook_input", lambda: payload)
    monkeypatch.setattr(stop, "resolve_container_ref", lambda *_args: "git:example/repo")
    monkeypatch.setattr(stop, "derive_actor_ref", lambda: "local")
    monkeypatch.setattr(stop, "register_claude_wake", lambda *args: calls.append(args))
    if case == "none":
        monkeypatch.setattr(stop, "read_turn", lambda _path: None)
    elif case == "empty":
        monkeypatch.setattr(stop, "read_turn", lambda _path: SimpleNamespace(assistant_text="", tool_calls=[]))
    elif case == "oversized":
        monkeypatch.setattr(stop, "read_turn", lambda _path: SimpleNamespace(assistant_text="x" * 20_001, tool_calls=[]))
    stop.main()
    assert calls == [("session-1", "git:example/repo", "local")]


def test_usage_audit_failure_is_generic_and_later_rows_continue(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    stop = _load_claude_hook("stop", monkeypatch)
    secret = "audit-secret"
    posts: list[str] = []
    monkeypatch.setattr(stop, "pallium_request", lambda method, path, body: {"rows": [{"id": "bad", "memory_object_id": "bad"}, {"id": "good", "memory_object_id": "good"}]} if method == "GET" else posts.append(path))
    monkeypatch.setattr(stop, "_fetch_memory_match_text", lambda memory_id: (_ for _ in ()).throw(RuntimeError(secret)) if memory_id == "bad" else "good")
    monkeypatch.setattr(stop, "classify_memory_reference", lambda **_kwargs: (False, None))
    stop._populate_usage_audit_rows("session", "assistant text")
    assert posts == ["/memory-usage-audit/good"]
    captured = capsys.readouterr()
    assert secret not in captured.err
    assert "RuntimeError" in captured.err

@pytest.mark.parametrize(
    "field,maximum",
    [
        ("session_ref", MAX_SESSION_CHARS),
        ("container_ref", MAX_CONTAINER_CHARS),
        ("actor_ref", MAX_ACTOR_CHARS),
        ("socket_path", MAX_SOCKET_CHARS),
        ("token", MAX_TOKEN_CHARS),
    ],
)
def test_registration_accepts_each_non_runtime_maximum(field: str, maximum: int) -> None:
    response = _client(ClaudeWakeRegistry()).post(
        "/internal/claude-wake/register", json={**PAYLOAD, field: "x" * maximum},
    )
    assert response.status_code == 204


@pytest.mark.parametrize("failure", [TimeoutError("timeout-secret"), OSError("http-secret")])
def test_hook_timeout_or_http_failure_is_silent(failure: Exception, monkeypatch: pytest.MonkeyPatch, caplog, capsys) -> None:
    common = _load_claude_hook("common", monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", r"\\.\pipe\claude")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "transport-secret")
    monkeypatch.setattr(common.urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(failure))
    assert not common.register_claude_wake("session", "git:example/repo", "local")
    captured = capsys.readouterr()
    assert "transport-secret" not in captured.out + captured.err
    assert not caplog.records