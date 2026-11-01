"""A rejected exact claim may retry once; uncertain requests never replay."""
from __future__ import annotations

from email.message import Message
import importlib.util
import io
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import urllib.error

import pytest


@pytest.fixture(params=["codex", "claude-code"])
def common(request, monkeypatch):
    path = Path(__file__).resolve().parents[1]/"integrations"/request.param/"hooks/common.py"
    spec = importlib.util.spec_from_file_location("claim_busy_"+request.param, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_HOOK_DEADLINE", None)
    return module


BUSY = b'{"detail":{"code":"relay_busy","retryable":true}}'
DELIVERY_ID = "relay-delivery-"+"a"*32


def busy_error(raw=BUSY, *, retry="1", length=None, extra_headers=()):
    headers = Message()
    if retry is not None:
        headers["Retry-After"] = retry
    headers["Content-Length"] = str(len(raw)) if length is None else length
    for key, value in extra_headers:
        headers[key] = value
    stream = io.BytesIO(raw)
    return urllib.error.HTTPError("http://localhost/relay/turn", 503, "busy", headers, stream), stream


def exercise(common, monkeypatch, *, first=None, first_elapsed=.45, persistent=False,
             timeout=2., expiry=102000, payload_updates=None, method="POST", path="/relay/turn",
             oversleep=0., wall_jump=0., with_deadline=True, deadline_seconds=2., wrong_origin=False, redirected=False):
    now, wall_offset = [0.], [0.]
    calls, sleeps = [], []
    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds+oversleep
        wall_offset[0] += wall_jump
    monkeypatch.setattr(common, "time", SimpleNamespace(monotonic=lambda: now[0],
        time=lambda: 100+now[0]+wall_offset[0], sleep=sleep))
    monkeypatch.setattr(common, "_run_before_deadline", lambda operation, deadline: operation())
    payload = {"runtime":"codex", "wake_delivery_id":DELIVERY_ID, "claim_expires_at_ms":expiry}
    payload.update(payload_updates or {})
    before = dict(payload)
    first, stream = first if first is not None else busy_error()
    if isinstance(first, urllib.error.HTTPError):
        first.url = common.PALLIUM_BASE_URL+("/other" if wrong_origin else path)
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return b'{"ok":true}'
    def open_request(request, timeout):
        calls.append((request.data, timeout))
        if redirected:
            request.redirect_dict = {request.full_url: 1}
        if len(calls) == 1:
            now[0] += first_elapsed
            raise first
        if persistent:
            now[0] += .45
            error, _ = busy_error()
            error.url = common.PALLIUM_BASE_URL+path
            raise error
        return Response()
    monkeypatch.setattr(common, "_urlopen", open_request)
    result = common.relay_request(method, path, payload, timeout=timeout,
        deadline=common.HookDeadline(deadline_seconds, clock=lambda: now[0]) if with_deadline else None)
    assert payload == before
    return result, calls, sleeps, stream


def test_confirmed_busy_retries_same_bytes_once_inside_original_budget(common, monkeypatch):
    result, calls, sleeps, stream = exercise(common, monkeypatch)
    assert result == {"ok": True} and sleeps == [1]
    assert len(calls) == 2 and calls[0][0] is calls[1][0]
    assert json.loads(calls[1][0])["claim_expires_at_ms"] == 102000
    assert calls[0][1] == 2 and calls[1][1] == pytest.approx(.55)
    assert stream.closed


@pytest.mark.parametrize("case", ["missing-retry", "retry-zero", "retry-two", "retry-date", "duplicate-retry",
    "missing-length", "bad-length", "duplicate-length", "too-large", "truncated", "chunked",
    "bad-json", "wrong-code", "false-retry", "numeric-retry", "extra-key", "duplicate-key", "other-status"])
def test_ambiguous_or_other_busy_errors_never_retry(common, monkeypatch, case):
    raw, retry, length, headers = BUSY, "1", None, []
    if case == "missing-retry": retry = None
    if case == "retry-zero": retry = "0"
    if case == "retry-two": retry = "2"
    if case == "retry-date": retry = "Sat, 31 Oct 2026 16:00:00 GMT"
    if case == "duplicate-retry": headers.append(("Retry-After", "1"))
    if case == "bad-length": length = "unknown"
    if case == "duplicate-length": headers.append(("Content-Length", str(len(raw))))
    if case == "too-large": raw = BUSY+b" "*1025
    if case == "truncated": length = str(len(raw)+1)
    if case == "chunked": headers.append(("Transfer-Encoding", "chunked"))
    if case == "bad-json": raw = b"{"
    if case == "wrong-code": raw = BUSY.replace(b"relay_busy", b"unavailable")
    if case == "false-retry": raw = BUSY.replace(b"true", b"false")
    if case == "numeric-retry": raw = BUSY.replace(b"true", b"1")
    if case == "extra-key": raw = b'{"detail":{"code":"relay_busy","retryable":true,"admitted":true}}'
    if case == "duplicate-key": raw = b'{"detail":{"code":"other","code":"relay_busy","retryable":true}}'
    error, stream = busy_error(raw, retry=retry, length=length, extra_headers=headers)
    if case == "missing-length": del error.headers["Content-Length"]
    if case == "other-status": error.code = 500
    result, calls, sleeps, _ = exercise(common, monkeypatch, first=(error, stream))
    assert result is None and len(calls) == 1 and sleeps == [] and stream.closed


@pytest.mark.parametrize("options", [
    {"payload_updates":{"runtime":"claude-code"}}, {"payload_updates":{"wake_delivery_id":"invalid"}},
    {"payload_updates":{"wake_delivery_id":None}}, {"payload_updates":{"claim_expires_at_ms":True}},
    {"payload_updates":{"claim_expires_at_ms":0}}, {"method":"GET"}, {"path":"/relay/messages"},
    {"with_deadline":False}, {"timeout":3., "deadline_seconds":3.},
    {"wrong_origin":True}, {"redirected":True},
])
def test_only_explicit_bounded_exact_codex_claim_can_retry(common, monkeypatch, options):
    result, calls, sleeps, _ = exercise(common, monkeypatch, **options)
    assert result is None and len(calls) == 1 and sleeps == []


@pytest.mark.parametrize("options,expected_calls,expected_sleeps", [
    ({"persistent":True}, 2, [1]), ({"first_elapsed":1.1}, 1, []),
    ({"expiry":100900}, 1, []), ({"oversleep":.8}, 1, [1]), ({"wall_jump":10.}, 1, [1]),
])
def test_persistent_busy_and_expired_budgets_stop_without_later_retry(common, monkeypatch, options, expected_calls, expected_sleeps):
    result, calls, sleeps, _ = exercise(common, monkeypatch, **options)
    assert result is None and len(calls) == expected_calls and sleeps == expected_sleeps


@pytest.mark.parametrize("error", [TimeoutError("uncertain"), OSError("connection lost")])
def test_uncertain_transport_never_replays(common, monkeypatch, error):
    result, calls, sleeps, _ = exercise(common, monkeypatch, first=(error, None))
    assert result is None and len(calls) == 1 and sleeps == []


@pytest.mark.parametrize("raw", [b' { "detail" : { "retryable": true, "code": "relay_busy" } } ',
                                BUSY+b" "*(1024-len(BUSY))])
def test_complete_equivalent_json_and_maximum_body_are_accepted(common, monkeypatch, raw):
    result, calls, sleeps, stream = exercise(common, monkeypatch, first=busy_error(raw))
    assert result == {"ok": True} and len(calls) == 2 and sleeps == [1] and stream.closed


def test_error_body_read_failure_never_retries(common, monkeypatch):
    error, stream = busy_error()
    def incomplete(_size):
        raise TimeoutError("body incomplete")
    error.read = incomplete
    result, calls, sleeps, _ = exercise(common, monkeypatch, first=(error, stream))
    assert result is None and len(calls) == 1 and not sleeps and stream.closed


def test_timed_out_worker_cannot_later_retry_after_delayed_error_body(common, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    calls, errors = [], []
    body_finished = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def do_POST(self):
            calls.append(self.rfile.read(int(self.headers["Content-Length"])))
            time.sleep(.8)
            self.send_response(503)
            self.send_header("Content-Length", str(len(BUSY)))
            self.send_header("Retry-After", "1")
            self.end_headers()
            self.wfile.flush()
            time.sleep(1.4)  # Per-read timeout allows this; the original absolute budget expires.
            try:
                self.wfile.write(BUSY)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except BaseException as exc:
                errors.append(exc)
            finally:
                body_finished.set()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    original_opener = common._build_opener
    monkeypatch.setattr(common, "_build_opener", lambda *handlers: original_opener(common.urllib.request.ProxyHandler({}), *handlers))
    monkeypatch.setattr(common, "PALLIUM_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        worker.start()
        started = time.monotonic()
        payload = {"runtime":"codex", "wake_delivery_id":DELIVERY_ID,
                   "claim_expires_at_ms":int((time.time()+2)*1000)}
        assert common.relay_request("POST", "/relay/turn", payload, timeout=2,
            deadline=common.HookDeadline(started+2)) is None
        assert time.monotonic()-started < 2.15
        assert body_finished.wait(2)
        time.sleep(1.1)  # Covers the would-be late Retry-After interval.
        assert len(calls) == 1 and not errors
    finally:
        server.shutdown(); server.server_close(); worker.join(3)
        assert not worker.is_alive()


@pytest.mark.parametrize("mode", ["busy-recovery", "post-admission-error"])
def test_exact_claim_real_http_recovers_only_known_busy_and_emits_acks_once(tmp_path, monkeypatch, mode):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from fastapi.testclient import TestClient
    from app import dependencies
    from app.config import AppConfig
    from app.main import create_app
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES
    from tests.test_hook_common_parity import codex_common as hook

    monkeypatch.setattr(dependencies, "schedule_codex_relay_wake", lambda *a, **k: None)
    monkeypatch.setattr("app.mcp.server.create_server", lambda **_: (_ for _ in ()).throw(ImportError()))
    admitted = []
    if mode == "post-admission-error":
        original_router = dependencies.create_router
        def router(service, **kwargs):
            original_callback = kwargs.get("relay_turn_admission_callback")
            def callback(request, result, captured):
                if original_callback is not None:
                    original_callback(request, result, captured)
                if request.get("wake_delivery_id"):
                    admitted.append(request["wake_delivery_id"])
                    raise RuntimeError("controlled post-admission callback failure")
            kwargs["relay_turn_admission_callback"] = callback
            return original_router(service, **kwargs)
        monkeypatch.setattr(dependencies, "create_router", router)
    app = create_app(AppConfig(storage_backend="sqlite", sqlite_url=f"sqlite:///{tmp_path/'main.db'}",
        relay_sqlite_url=f"sqlite:///{tmp_path/'relay.db'}", default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES, vector_index=VectorIndexConfig(enabled=False)))
    backend = TestClient(app)
    storage = app.state.pallium_service._storage
    assert app.state.codex_wake_registry.initialize(old_owner_drained=True)
    scope = {"container_ref":"git:example.test/rejected-claim"}
    for session in ("sender-session", "target-session"):
        response = backend.post("/relay/turn", json={"runtime":"codex", "session_ref":session, **scope})
        assert response.status_code == 200, response.text
    sent = backend.post("/relay/messages", json={"sender_runtime":"codex", "sender_session_ref":"sender-session",
        "recipient":"codex:target-session", "payload":"Continue the review — 東京", **scope})
    assert sent.status_code == 200, sent.text
    message = sent.json()
    delivery = message["deliveries"][0]["delivery_id"]
    held, rejected = threading.Event(), threading.Event()
    def hold_gate():
        with storage._relay_writer_lock:
            held.set()
            assert rejected.wait(5), "test must settle the controlled rejection"
    statuses, wire, preclaim = [], [], []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            response = backend.post(self.path, json=json.loads(raw))
            if self.path == "/relay/turn":
                statuses.append(response.status_code)
                wire.append(raw)
            if response.status_code == 503:
                assert response.json() == {"detail":{"code":"relay_busy", "retryable":True}}
                preclaim.append(backend.get("/relay/messages/"+message["message_id"], params=scope).json()["deliveries"][0])
                rejected.set()
            self.send_response(response.status_code)
            self.send_header("Content-Length", str(len(response.content)))
            if "retry-after" in response.headers:
                self.send_header("Retry-After", response.headers["retry-after"])
            self.end_headers()
            self.wfile.write(response.content)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    holding = threading.Thread(target=hold_gate, daemon=True)
    monkeypatch.setattr(hook, "SESSIONS_DIR", tmp_path/"sessions")
    monkeypatch.setattr(hook, "STATE_DIR", tmp_path/"state")
    monkeypatch.setattr(hook, "PALLIUM_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(hook, "_HOOK_DEADLINE", hook.HookDeadline(time.monotonic()+8))
    original_opener = hook._build_opener
    monkeypatch.setattr(hook, "_build_opener", lambda *handlers: original_opener(hook.urllib.request.ProxyHandler({}), *handlers))
    try:
        serving.start()
        if mode == "busy-recovery":
            holding.start()
            assert held.wait(3)
        started = time.monotonic()
        result = hook.relay_turn("codex", "target-session", scope["container_ref"], wake_delivery_id=delivery,
                                 timeout=2, deadline=hook.HookDeadline(started+2))
        elapsed = time.monotonic()-started
        assert result is not None and elapsed < 2
        assert statuses == ([503, 200] if mode == "busy-recovery" else [200])
        if mode == "busy-recovery":
            assert wire[0] == wire[1]
            assert preclaim[0]["state"] == "pending" and preclaim[0]["attempts"] == 0
        else:
            assert admitted == [delivery]
        text, rendered = hook.format_relay(result["deliveries"])
        assert "Continue the review" in text and len(rendered) == 1 and rendered[0]["attempts"] == 1
        assert hook.acknowledge_relay(rendered, container_ref=scope["container_ref"]) == rendered
        final = backend.get("/relay/messages/"+message["message_id"], params=scope).json()["deliveries"][0]
        assert final["state"] == "delivered" and final["attempts"] == 1
    finally:
        rejected.set()
        if holding.ident:
            holding.join(3)
        server.shutdown(); server.server_close(); serving.join(3)
        assert not holding.is_alive() and not serving.is_alive()
        backend.close()
        app.state._close_constructed()
