from __future__ import annotations

import asyncio
from contextlib import nullcontext
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
    MAX_REGISTRATIONS,
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
    "idle": True,
}


def _client(registry: ClaudeWakeRegistry, peer: tuple[str, int] = ("127.0.0.1", 50000)) -> TestClient:
    app = FastAPI()
    app.include_router(create_router(object(), claude_wake_registry=registry))
    return TestClient(app, client=peer)


def test_registration_keeps_intent_when_store_unusable_marker_cannot_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hashlib import sha256

    state_dir = tmp_path / "wake"
    marker = state_dir / "store-unusable"
    marker.parent.mkdir()
    marker.write_text('{"unusable":true}', encoding="utf-8")
    payload = {**PAYLOAD, "intent_id": "marker-recovery"}
    intent = state_dir / "intents" / (sha256(PAYLOAD["session_ref"].encode("utf-8")).hexdigest() + ".json")
    intent.parent.mkdir()
    intent.write_text(json.dumps(payload), encoding="utf-8")
    registry = ClaudeWakeRegistry(state_dir=state_dir)
    original_unlink = Path.unlink

    def fail_marker_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == marker:
            raise OSError("marker remains")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_marker_unlink)
    response = _client(registry).post("/internal/claude-wake/register", json=payload)
    assert response.status_code == 409
    assert json.loads(intent.read_text(encoding="utf-8")) == payload
    assert registry.recovery_candidates() == []
    assert (state_dir / "capabilities.json").exists()
    assert ClaudeWakeRegistry(state_dir=state_dir).recovery_candidates() == []

    monkeypatch.setattr(Path, "unlink", original_unlink)
    registry.recover_intents()
    assert not marker.exists() and not intent.exists()
    assert [candidate["state"] for candidate in registry.recovery_candidates()] == ["idle"]
    assert [candidate["state"] for candidate in ClaudeWakeRegistry(state_dir=state_dir).recovery_candidates()] == ["idle"]

@pytest.mark.parametrize("replace_closed_intent", (False, True))
def test_close_endpoint_write_failure_preserves_exact_intent_for_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replace_closed_intent: bool,
) -> None:
    from hashlib import sha256

    state_dir = tmp_path / "wake"
    intent = state_dir / "intents" / (sha256(PAYLOAD["session_ref"].encode("utf-8")).hexdigest() + ".json")

    def write_intent(payload: dict[str, object]) -> None:
        intent.parent.mkdir(parents=True, exist_ok=True)
        intent.write_text(json.dumps(payload), encoding="utf-8")

    registry = ClaudeWakeRegistry(state_dir=state_dir)
    opened = {**PAYLOAD, "intent_id": "open"}
    write_intent(opened)
    client = _client(registry)
    assert client.post("/internal/claude-wake/register", json=opened).status_code == 204
    closed = {key: PAYLOAD[key] for key in ("runtime", "session_ref", "container_ref", "actor_ref")}
    closed.update(intent_id="closed", closed=True)
    write_intent(closed)
    original_write = registry._write_canonical_locked
    monkeypatch.setattr(registry, "_write_canonical_locked", lambda *_: False)

    assert client.post("/internal/claude-wake/close", json=closed).status_code == 400
    assert json.loads(intent.read_text(encoding="utf-8")) == closed
    assert [candidate["state"] for candidate in registry.recovery_candidates()] == ["idle"]
    assert [candidate["state"] for candidate in ClaudeWakeRegistry(state_dir=state_dir).recovery_candidates()] == ["idle"]

    monkeypatch.setattr(registry, "_write_canonical_locked", original_write)
    if replace_closed_intent:
        newer = {**PAYLOAD, "token": "new-token", "intent_id": "new"}
        write_intent(newer)
    registry.recover_intents()
    restarted = ClaudeWakeRegistry(state_dir=state_dir)
    if not replace_closed_intent:
        assert not intent.exists() and restarted.recovery_candidates() == []
        return
    observed: list[str] = []
    assert restarted.probe(
        runtime=PAYLOAD["runtime"], session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"],
        transport=lambda _socket_path, token: observed.append(token) or "accepted",
    )
    assert observed == ["new-token"]

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

    def transport(_socket_path: str, _token: str) -> str:
        worker = threading.Thread(target=lambda: registry.register(**{**PAYLOAD, "token": "third"}))
        worker.start()
        worker.join(timeout=1)
        assert not worker.is_alive()
        completed.set()
        return "accepted"

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
    start_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(start, "read_hook_input", lambda: {"cwd": ".", "session_id": "session-1"})
    monkeypatch.setattr(start, "derive_container_ref", lambda _cwd: "git:example/repo")
    monkeypatch.setattr(start, "derive_actor_ref", lambda: "local")
    monkeypatch.setattr(start, "pin_container", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(start, "register_claude_wake", lambda *args, **kwargs: start_calls.append((args, kwargs)))
    monkeypatch.setattr(start, "relay_request", lambda *_args, **_kwargs: {"deliveries": []})
    monkeypatch.setattr(start, "_fetch_orientation", lambda *_args: [])
    with pytest.raises(SystemExit) as exit_info:
        start.main()
    assert exit_info.value.code == 0
    assert start_calls == [(('session-1', 'git:example/repo', 'local'), {'idle': False})]

    stop = _load_claude_hook("stop", monkeypatch)
    stop_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(stop, "read_hook_input", lambda: {"cwd": ".", "session_id": "session-1", "transcript_path": ""})
    monkeypatch.setattr(stop, "resolve_container_ref", lambda *_args: "git:example/repo")
    monkeypatch.setattr(stop, "derive_actor_ref", lambda: "local")
    monkeypatch.setattr(stop, "register_claude_wake", lambda *args, **kwargs: stop_calls.append((args, kwargs)))
    stop.main()
    assert stop_calls == [(('session-1', 'git:example/repo', 'local'), {'idle': True})] * 2


def test_hook_registration_suppresses_credential_on_transport_failure(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    common = _load_claude_hook("common", monkeypatch)
    secret = "never-print-this"
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", r"\\.\pipe\claude")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", secret)
    monkeypatch.setattr(common.urllib.request, "build_opener", lambda *_args: SimpleNamespace(open=lambda *_a, **_k: (_ for _ in ()).throw(OSError(secret))))
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
    assert not registry.probe(
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
    router = create_router(object(), claude_wake_registry=registry)
    return next(route.endpoint for route in router.routes if route.path == "/internal/claude-wake/register")


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


@pytest.mark.parametrize("value", [None, 1, [], {}])
def test_registration_rejects_wrong_typed_secret_fields(value: object) -> None:
    response = _client(ClaudeWakeRegistry()).post(
        "/internal/claude-wake/register", json={**PAYLOAD, "token": value},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid registration"}


def test_concurrent_expiry_is_safe() -> None:
    now = [0.0]
    registry = ClaudeWakeRegistry(clock=lambda: now[0])
    registry.register(**PAYLOAD)
    now[0] = TTL_SECONDS + 1
    barrier = threading.Barrier(3)
    results: list[bool] = []

    def probe() -> None:
        barrier.wait()
        results.append(registry.probe(
            runtime=PAYLOAD["runtime"],
            session_ref=PAYLOAD["session_ref"],
            container_ref=PAYLOAD["container_ref"],
            actor_ref=PAYLOAD["actor_ref"],
            transport=lambda *_: pytest.fail("expired credentials must not transport"),
        ))

    workers = [threading.Thread(target=probe) for _ in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=1)
        assert not worker.is_alive()
    assert results == [False, False]


def test_registry_capacity_prunes_expired_and_preserves_existing_updates() -> None:
    now = [0.0]
    registry = ClaudeWakeRegistry(clock=lambda: now[0])
    for index in range(MAX_REGISTRATIONS):
        registry.register(**{**PAYLOAD, "session_ref": f"session-{index}"})
    registry.register(**{**PAYLOAD, "session_ref": "session-0", "token": "replacement"})
    with pytest.raises(ValueError, match="capacity"):
        registry.register(**{**PAYLOAD, "session_ref": "overflow"})
    now[0] = TTL_SECONDS + 1
    registry.register(**{**PAYLOAD, "session_ref": "after-expiry"})
    assert registry.probe(
        runtime=PAYLOAD["runtime"],
        session_ref="after-expiry",
        container_ref=PAYLOAD["container_ref"],
        actor_ref=PAYLOAD["actor_ref"],
        transport=lambda *_: True,
    )


def test_hook_enforces_encoded_body_limit_before_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    common = _load_claude_hook("common", monkeypatch)
    wake_dir = tmp_path / "wake"
    monkeypatch.setattr(common, "CLAUDE_WAKE_DIR", wake_dir)
    monkeypatch.setattr(common, "CLAUDE_WAKE_INTENTS_DIR", wake_dir / "intents")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", "socket")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "é" * MAX_TOKEN_CHARS)
    opener_calls: list[bool] = []
    monkeypatch.setattr(
        common.urllib.request,
        "build_opener",
        lambda *_args: opener_calls.append(True) or pytest.fail("oversized encoded body must not open"),
    )
    assert not common.register_claude_wake("session", "git:example/repo", "local")
    assert opener_calls == [] and not common._wake_intent_path("session").exists()
    assert list((wake_dir / "intents").glob("*.tmp")) == []
    restarted = ClaudeWakeRegistry(state_dir=wake_dir)
    restarted.recover_intents()
    assert restarted.recovery_candidates() == []

    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", "socket-✓")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "token-✓")

    def open_request(request, **_kwargs):
        body = json.loads(request.data.decode("utf-8"))
        assert common._wake_intent_path("session-✓").exists()
        assert body["session_ref"] == "session-✓" and body["container_ref"] == "git:é/repo"
        return nullcontext()

    monkeypatch.setattr(common.urllib.request, "build_opener", lambda *_args: SimpleNamespace(open=open_request))
    assert common.register_claude_wake("session-✓", "git:é/repo", "actor-α")

def test_hook_disables_proxies_and_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    common = _load_claude_hook("common", monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", r"\\.\pipe\claude")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "token")
    handlers: list[object] = []

    def build_opener(*configured: object):
        handlers.extend(configured)
        return SimpleNamespace(open=lambda *_args, **_kwargs: nullcontext())

    monkeypatch.setattr(common.urllib.request, "build_opener", build_opener)
    assert common.register_claude_wake("session", "git:example/repo", "local")
    assert any(isinstance(handler, common.urllib.request.ProxyHandler) and handler.proxies == {} for handler in handlers)
    redirect_handler = next(handler for handler in handlers if isinstance(handler, common._RejectCredentialRedirects))
    assert redirect_handler.redirect_request(None, None, 307, None, {}, "https://example.invalid") is None


@pytest.mark.parametrize("case", ["missing", "none", "empty", "oversized"])
def test_stop_refreshes_before_every_early_return(case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    stop = _load_claude_hook("stop", monkeypatch)
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    payload = {"cwd": ".", "session_id": "session-1", "transcript_path": "" if case == "missing" else "turn.jsonl"}
    monkeypatch.setattr(stop, "read_hook_input", lambda: payload)
    monkeypatch.setattr(stop, "resolve_container_ref", lambda *_args: "git:example/repo")
    monkeypatch.setattr(stop, "derive_actor_ref", lambda: "local")
    monkeypatch.setattr(stop, "register_claude_wake", lambda *args, **kwargs: calls.append((args, kwargs)))
    if case == "none":
        monkeypatch.setattr(stop, "read_turn", lambda _path: None)
    elif case == "empty":
        monkeypatch.setattr(stop, "read_turn", lambda _path: SimpleNamespace(assistant_text="", tool_calls=[]))
    elif case == "oversized":
        monkeypatch.setattr(stop, "read_turn", lambda _path: SimpleNamespace(assistant_text="x" * 20_001, tool_calls=[]))
    stop.main()
    assert calls == [(('session-1', 'git:example/repo', 'local'), {'idle': True})] * 2


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
    monkeypatch.setattr(common.urllib.request, "build_opener", lambda *_args: SimpleNamespace(open=lambda *_a, **_k: (_ for _ in ()).throw(failure)))
    assert not common.register_claude_wake("session", "git:example/repo", "local")
    captured = capsys.readouterr()
    assert "transport-secret" not in captured.out + captured.err
    assert not caplog.records
def test_claude_hook_lifecycle_surfaces_registration_turn_and_stop(monkeypatch) -> None:
    calls = []
    start = _load_claude_hook("session_start", monkeypatch)
    prompt = _load_claude_hook("user_prompt_submit", monkeypatch)
    stop = _load_claude_hook("stop", monkeypatch)
    payload = {"session_id": "session-test", "cwd": ".", "prompt": "a sufficiently long prompt for relay"}
    monkeypatch.setattr(start, "read_hook_input", lambda: {"session_id": "session-test", "cwd": ".", "source": "startup"})
    monkeypatch.setattr(start, "register_claude_wake", lambda *args, **kwargs: calls.append(("start", args)) or True)
    monkeypatch.setattr(start, "_fetch_orientation", lambda *_: [])
    with pytest.raises(SystemExit):
        start.main()
    monkeypatch.setattr(prompt, "read_hook_input", lambda: payload)
    monkeypatch.setattr(prompt, "check_dedup", lambda *_: False)
    monkeypatch.setattr(prompt, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(prompt, "relay_request", lambda method, path, body, timeout: calls.append(("prompt", method, path)) or {"deliveries": []})
    monkeypatch.setattr(prompt, "pallium_request", lambda *args, **kwargs: None)
    with pytest.raises(SystemExit):
        prompt.main()
    monkeypatch.setattr(stop, "read_hook_input", lambda: {"session_id": "session-test", "cwd": "."})
    monkeypatch.setattr(stop, "resolve_container_ref", lambda *_: "git:example/repo")
    monkeypatch.setattr(stop, "register_claude_wake", lambda *args, **kwargs: calls.append(("stop", args)) or True)
    monkeypatch.setattr(stop, "read_turn", lambda *_: None)
    stop.main()
    assert [entry[0] for entry in calls] == ["start", "prompt", "stop", "stop"]
    assert calls[1][2] == "/relay/turn"
def test_explicit_idle_state_is_one_shot_and_scope_bound() -> None:
    registry = ClaudeWakeRegistry()
    registry.register(**{**PAYLOAD, "idle": False})

    def transport(*_: object) -> str:
        return "accepted"

    assert not registry.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"], transport=transport)
    registry.register(**{**PAYLOAD, "idle": True})
    assert registry.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"], transport=transport)
    assert not registry.probe(runtime="claude-code", session_ref=PAYLOAD["session_ref"], container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"], transport=transport)

@pytest.mark.parametrize("idle, expected", [(None, 204), ("false", 400), (1, 400)])
def test_registration_idle_boundary_is_fail_closed(idle, expected) -> None:
    registry = ClaudeWakeRegistry()
    payload = {key: value for key, value in PAYLOAD.items() if key != "idle"}
    if idle is not None:
        payload["idle"] = idle
    response = _client(registry).post("/internal/claude-wake/register", json=payload)
    assert response.status_code == expected
    if idle is None:
        assert not registry.probe(
            runtime=PAYLOAD["runtime"], session_ref=PAYLOAD["session_ref"],
            container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"],
            transport=lambda *_: True,
        )


def test_session_start_delivers_and_acks_relay_before_orientation(
    monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    start = _load_claude_hook("session_start", monkeypatch)
    delivery = {
        "delivery_id": "delivery-start",
        "claim_token": "claim-start",
        "message_id": "message-start",
        "sender_runtime": "codex",
        "sender_session_ref": "sender",
        "recipient": "claude-code:session-1",
        "payload": "startup work",
        "redacted": False,
        "in_reply_to": None,
        "created_at": "2026-09-02T10:00:00+00:00",
        "expires_at": "2026-09-03T10:00:00+00:00",
    }
    acknowledgements = []
    monkeypatch.setattr(
        start, "read_hook_input",
        lambda: {"cwd": ".", "session_id": "session-1", "source": "startup"},
    )
    monkeypatch.setattr(start, "derive_container_ref", lambda _cwd: "git:example/repo")
    monkeypatch.setattr(start, "derive_actor_ref", lambda: "local")
    monkeypatch.setattr(start, "pin_container", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(start, "register_claude_wake", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        start, "relay_request",
        lambda *_args, **_kwargs: {"deliveries": [delivery]},
    )
    monkeypatch.setattr(
        start, "acknowledge_relay",
        lambda deliveries, **scope: acknowledgements.append((deliveries, scope)),
    )
    monkeypatch.setattr(
        start, "_fetch_orientation",
        lambda *_args: pytest.fail("Relay delivery must skip orientation memory"),
    )

    with pytest.raises(SystemExit):
        start.main()

    assert "startup work" in capsys.readouterr().out
    assert acknowledgements == [([delivery], {
        "container_ref": "git:example/repo",
        "actor_ref": "local",
    })]


def test_claude_reconciler_is_lifespan_owned_and_stops_on_repeated_apps(tmp_path: Path) -> None:
    def config(name: str) -> AppConfig:
        return AppConfig(storage_backend="sqlite", sqlite_url=f"sqlite:///{tmp_path / name}", default_use_case="demo_agent_memory", semantic_packages=DEMO_SEMANTIC_PACKAGES, vector_index=VectorIndexConfig(enabled=False))

    for name in ("first.db", "second.db"):
        app = create_app(config(name))
        with TestClient(app):
            reconciler = app.state._claude_wake_reconciler
            assert reconciler is not None and reconciler._thread is not None and reconciler._thread.is_alive()
        assert not reconciler._thread.is_alive()