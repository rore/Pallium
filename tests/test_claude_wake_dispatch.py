"""Tests for Claude Code wake transport and dispatch."""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
from types import SimpleNamespace

import pytest

from app.claude_wake import schedule_claude_relay_wake
from app.claude_wake_transport import _windows_write, claude_wake_transport
from core.claude_wake import ClaudeWakeRegistry


PAYLOAD = {
    "runtime": "claude-code",
    "session_ref": "session-test",
    "container_ref": "git:example/repo",
    "actor_ref": "local",
    "socket_path": r"\\.\pipe\claude" if os.name == "nt" else "/tmp/claude-test.sock",
    "token": "test-token",
}



def _join(worker: threading.Thread | None) -> None:
    assert worker is not None
    worker.join(timeout=1)
    assert not worker.is_alive()


def _wake_result(session_ref: str, delivery_id: str = "delivery-1") -> dict:
    return {
        "recipient": f"claude-code:{session_ref}",
        "deliveries": [{
            "delivery_id": delivery_id,
            "state": "pending",
            "recipient_runtime": "claude-code",
            "recipient_session_ref": session_ref,
        }],
    }

class TestTransport:
    """Transport tests: typed outcomes, auth frames, and platform failures."""

    @pytest.mark.skipif(os.name == "nt", reason="Unix socket test")
    def test_posix_transport_writes_auth_and_frame(self, tmp_path: Path) -> None:
        socket_path = str(tmp_path / "test.sock")
        received: list[str] = []
        ready = threading.Event()
        done = threading.Event()

        def listener() -> None:
            try:
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(socket_path)
                server.listen(1)
                ready.set()
                conn, _ = server.accept()
                data = b""
                while chunk := conn.recv(4096):
                    data += chunk
                received.extend(data.decode("utf-8").split("\n"))
                conn.close()
                server.close()
            finally:
                done.set()

        thread = threading.Thread(target=listener, daemon=True)
        thread.start()
        assert ready.wait(timeout=1)
        assert claude_wake_transport(socket_path, "test-token") == "accepted"
        assert done.wait(timeout=2)
        thread.join(timeout=1)
        lines = [line for line in received if line.strip()]
        auth, frame = (json.loads(line) for line in lines[:2])
        assert auth == {"type": "auth", "token": "test-token"}
        assert frame["msgV"] == 1 and frame["type"] == "user"
        assert frame["message"]["role"] == "user" and frame["priority"] == "next"
        assert frame["from"] == "pallium-relay"

    @pytest.mark.skipif(os.name == "nt", reason="Unix socket test")
    def test_posix_transport_missing_path_is_terminal(self) -> None:
        assert claude_wake_transport("/nonexistent/socket.sock", "token") == "terminal"

    @pytest.mark.parametrize("error", [ConnectionRefusedError(), socket.timeout(), PermissionError()])
    def test_posix_transport_classifies_uncertainty_retryable(self, monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
        import app.claude_wake_transport as transport

        class BrokenSocket:
            def settimeout(self, _seconds):
                pass
            def connect(self, _path):
                raise error
            def close(self):
                pass

        monkeypatch.setattr(transport.socket, "AF_UNIX", 1, raising=False)
        monkeypatch.setattr(transport.socket, "socket", lambda *_: BrokenSocket())
        assert transport._posix_transport("ignored", "token") == "retryable"

    def test_windows_write_cancels_after_bounded_timeout(self) -> None:
        cancelled = []
        closed = []

        class Overlapped:
            hEvent = None

        pywintypes = SimpleNamespace(OVERLAPPED=Overlapped)
        win32event = SimpleNamespace(WAIT_OBJECT_0=0, CreateEvent=lambda *_: "event", WaitForSingleObject=lambda *_: 258)
        win32file = SimpleNamespace(WriteFile=lambda *_: (997, 0), CancelIoEx=lambda handle, overlapped: cancelled.append((handle, overlapped)), GetOverlappedResult=lambda *_: 0, CloseHandle=lambda handle: closed.append(handle))
        winerror = SimpleNamespace(ERROR_IO_PENDING=997)
        assert _windows_write("pipe", b"frame", pywintypes, win32event, win32file, winerror) is False
        assert len(cancelled) == 1 and closed == ["event"]

    def test_windows_transport_clean_write_is_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys
        import app.claude_wake_transport as transport

        writes: list[bytes] = []
        monkeypatch.setitem(sys.modules, "pywintypes", SimpleNamespace())
        monkeypatch.setitem(sys.modules, "win32event", SimpleNamespace())
        monkeypatch.setitem(sys.modules, "winerror", SimpleNamespace())
        monkeypatch.setitem(sys.modules, "win32file", SimpleNamespace(GENERIC_WRITE=1, OPEN_EXISTING=2, FILE_FLAG_OVERLAPPED=4, CreateFile=lambda *_: "pipe", CloseHandle=lambda *_: None))
        monkeypatch.setattr(transport, "_windows_write", lambda _handle, data, *_: writes.append(data) or True)
        assert transport._windows_transport(r"\\.\pipe\claude", "token") == "accepted"
        auth, frame = (json.loads(data) for data in writes)
        assert auth["type"] == "auth" and frame["type"] == "user"

    @pytest.mark.parametrize("code, expected", [(2, "terminal"), (231, "retryable"), (121, "retryable"), (5, "retryable")])
    def test_windows_transport_classifies_fake_open_errors(self, monkeypatch: pytest.MonkeyPatch, code: int, expected: str) -> None:
        import sys
        import app.claude_wake_transport as transport

        class PipeError(Exception):
            def __init__(self, winerror):
                self.winerror = winerror

        def create_file(*_args):
            raise PipeError(code)

        monkeypatch.setitem(sys.modules, "pywintypes", SimpleNamespace(error=PipeError))
        monkeypatch.setitem(sys.modules, "win32event", SimpleNamespace())
        monkeypatch.setitem(sys.modules, "winerror", SimpleNamespace(ERROR_FILE_NOT_FOUND=2))
        monkeypatch.setitem(sys.modules, "win32file", SimpleNamespace(GENERIC_WRITE=1, OPEN_EXISTING=2, FILE_FLAG_OVERLAPPED=4, CreateFile=create_file, CloseHandle=lambda *_: None))
        assert transport._windows_transport(r"\\.\pipe\claude", "token") == expected

    def test_windows_transport_import_failure_is_retryable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins
        import app.claude_wake_transport as transport

        original_import = builtins.__import__
        monkeypatch.setattr(builtins, "__import__", lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError()) if name == "pywintypes" else original_import(name, *args, **kwargs))
        assert transport._windows_transport(r"\\.\pipe\claude", "token") == "retryable"

class TestDispatch:
    """Dispatch tests: route to correct handler, malformed=no-op."""

    def test_claude_code_delivery_calls_probe(self) -> None:
        """claude-code delivery routes to schedule_claude_relay_wake."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {
            "recipient": "claude-code:session-test",
            "deliveries": [
                {
                    "delivery_id": "delivery-1",
                    "state": "pending",
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": "session-test",
                }
            ],
        }
        scope = {
            "container_ref": "git:example/repo",
            "actor_ref": "local",
        }

        _join(schedule_claude_relay_wake(result, scope, registry=registry))

        registry.probe.assert_called_once()
        call_kwargs = registry.probe.call_args[1]
        assert call_kwargs["runtime"] == "claude-code"
        assert call_kwargs["session_ref"] == "session-test"
        assert call_kwargs["container_ref"] == "git:example/repo"
        assert call_kwargs["actor_ref"] == "local"
        assert callable(call_kwargs["transport"])

    def test_malformed_delivery_no_op(self) -> None:
        """Malformed delivery (no deliveries list) calls nothing."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {"recipient": "claude-code:session-test"}
        scope = {
            "container_ref": "git:example/repo",
            "actor_ref": "local",
        }

        schedule_claude_relay_wake(result, scope, registry=registry)

        registry.probe.assert_not_called()

    def test_non_dict_result_no_op(self) -> None:
        """Non-dict result calls nothing."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        schedule_claude_relay_wake("not a dict", {}, registry=registry)
        registry.probe.assert_not_called()

    def test_missing_container_ref_no_op(self) -> None:
        """Missing container_ref in scope calls nothing."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {
            "recipient": "claude-code:session-test",
            "deliveries": [
                {
                    "delivery_id": "delivery-1",
                    "state": "pending",
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": "session-test",
                }
            ],
        }
        scope = {"actor_ref": "local"}  # Missing container_ref

        schedule_claude_relay_wake(result, scope, registry=registry)

        registry.probe.assert_not_called()

    def test_bad_session_ref_no_op(self) -> None:
        """Session ref with whitespace/non-printable calls nothing."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {
            "recipient": "claude-code:bad session",
            "deliveries": [
                {
                    "delivery_id": "delivery-1",
                    "state": "pending",
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": " bad session ",  # Not stripped in delivery
                }
            ],
        }
        scope = {
            "container_ref": "git:example/repo",
            "actor_ref": "local",
        }

        schedule_claude_relay_wake(result, scope, registry=registry)

        registry.probe.assert_not_called()

    def test_valid_selector_alias_calls_probe(self) -> None:
        """Valid @alias selector calls probe."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {
            "recipient": "claude-code:@work",
            "deliveries": [
                {
                    "delivery_id": "delivery-1",
                    "state": "pending",
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": "session-test",
                }
            ],
        }
        scope = {
            "container_ref": "git:example/repo",
            "actor_ref": "local",
        }

        _join(schedule_claude_relay_wake(result, scope, registry=registry))

        registry.probe.assert_called_once()

    def test_invalid_selector_format_no_op(self) -> None:
        """Invalid alias format (@-bad) calls nothing."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {
            "recipient": "claude-code:@-bad",
            "deliveries": [
                {
                    "delivery_id": "delivery-1",
                    "state": "pending",
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": "session-test",
                }
            ],
        }
        scope = {
            "container_ref": "git:example/repo",
            "actor_ref": "local",
        }

        schedule_claude_relay_wake(result, scope, registry=registry)

        registry.probe.assert_not_called()

    def test_empty_delivery_id_no_op(self) -> None:
        """Empty delivery_id calls nothing."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {
            "recipient": "claude-code:session-test",
            "deliveries": [
                {
                    "delivery_id": "",
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": "session-test",
                }
            ],
        }
        scope = {
            "container_ref": "git:example/repo",
            "actor_ref": "local",
        }

        schedule_claude_relay_wake(result, scope, registry=registry)

        registry.probe.assert_not_called()

    def test_multiple_deliveries_no_op(self) -> None:
        """Multiple deliveries (should be exactly 1) calls nothing."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {
            "recipient": "claude-code:session-test",
            "deliveries": [
                {
                    "delivery_id": "delivery-1",
                    "state": "pending",
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": "session-test",
                },
                {
                    "delivery_id": "delivery-2",
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": "session-test",
                },
            ],
        }
        scope = {
            "container_ref": "git:example/repo",
            "actor_ref": "local",
        }

        schedule_claude_relay_wake(result, scope, registry=registry)

        registry.probe.assert_not_called()

def test_wake_worker_returns_without_waiting_and_logs_credential_free_outcome(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    import app.claude_wake as wake

    registry = ClaudeWakeRegistry()
    secret = "token-secret"
    session_ref = "session-א"
    scope = {"container_ref": "git:é/repo", "actor_ref": "local"}
    registry.register(**{**PAYLOAD, **scope, "session_ref": session_ref, "token": secret, "idle": True})
    started = threading.Event()
    release = threading.Event()

    def transport(*_: object) -> str:
        started.set()
        assert release.wait(timeout=1)
        return "accepted"

    monkeypatch.setattr(wake, "claude_wake_transport", transport)
    caplog.set_level(logging.INFO, logger="app.claude_wake")
    worker = schedule_claude_relay_wake(
        _wake_result(session_ref, "delivery-α"), scope, registry=registry
    )
    assert started.wait(timeout=1)
    assert worker is not None and worker.is_alive()
    release.set()
    _join(worker)
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "delivery-α" in logged and session_ref in logged
    assert "category=trigger_written" in logged and "latency_ms=" in logged
    assert secret not in logged and "message-content" not in logged


def test_wake_worker_coalesces_concurrent_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.claude_wake as wake

    registry = ClaudeWakeRegistry()
    registry.register(**{**PAYLOAD, "idle": True})
    started = threading.Event()
    release = threading.Event()
    barrier = threading.Barrier(3)
    workers: list[threading.Thread | None] = []
    calls: list[bool] = []

    def transport(*_: object) -> str:
        calls.append(True)
        started.set()
        assert release.wait(timeout=1)
        return "accepted"

    monkeypatch.setattr(wake, "claude_wake_transport", transport)

    def submit() -> None:
        barrier.wait()
        workers.append(schedule_claude_relay_wake(_wake_result(PAYLOAD["session_ref"]), {
            "container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"],
        }, registry=registry))

    senders = [threading.Thread(target=submit) for _ in range(2)]
    for sender in senders:
        sender.start()
    barrier.wait()
    for sender in senders:
        sender.join(timeout=1)
        assert not sender.is_alive()
    assert started.wait(timeout=1)
    assert len([worker for worker in workers if worker is not None]) == 1
    release.set()
    _join(next(worker for worker in workers if worker is not None))
    assert calls == [True]


def test_transport_failure_rearms_only_the_same_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.claude_wake as wake

    registry = ClaudeWakeRegistry()
    registry.register(**{**PAYLOAD, "idle": True})
    calls = 0

    def transport(*_: object) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("transport failed")
        return "accepted"

    monkeypatch.setattr(wake, "claude_wake_transport", transport)
    scope = {"container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"]}
    _join(schedule_claude_relay_wake(_wake_result(PAYLOAD["session_ref"], "first"), scope, registry=registry))
    _join(schedule_claude_relay_wake(_wake_result(PAYLOAD["session_ref"], "second"), scope, registry=registry))
    assert calls == 2


def test_failed_old_generation_cannot_rearm_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.claude_wake as wake

    registry = ClaudeWakeRegistry()
    registry.register(**{**PAYLOAD, "idle": True})
    started = threading.Event()
    release = threading.Event()

    def transport(*_: object) -> str:
        started.set()
        assert release.wait(timeout=1)
        return "retryable"

    monkeypatch.setattr(wake, "claude_wake_transport", transport)
    scope = {"container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"]}
    worker = schedule_claude_relay_wake(_wake_result(PAYLOAD["session_ref"]), scope, registry=registry)
    assert started.wait(timeout=1)
    registry.register(**{**PAYLOAD, "token": "replacement", "idle": False})
    release.set()
    _join(worker)
    assert not registry.probe(
        runtime=PAYLOAD["runtime"], session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"], actor_ref=PAYLOAD["actor_ref"],
        transport=lambda *_: pytest.fail("replacement must remain busy"),
    )

def test_relay_messages_response_does_not_wait_for_claude_transport(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.dependencies import build_router

    registry = ClaudeWakeRegistry()
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
        claude_wake_registry=registry,
    ))
    http = TestClient(app, client=("127.0.0.1", 50000))
    scope = {"container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"]}
    for runtime, session_ref in (("claude-code", "target"), ("codex", "sender")):
        assert http.post("/relay/turn", json={
            "runtime": runtime, "session_ref": session_ref, **scope,
        }).status_code == 200
    assert http.post("/internal/claude-wake/register", json={
        **PAYLOAD, "session_ref": "target", "idle": True,
    }).status_code == 204
    started = threading.Event()
    release = threading.Event()
    worker_threads: list[threading.Thread] = []

    def transport(*_: object) -> str:
        worker_threads.append(threading.current_thread())
        started.set()
        assert release.wait(timeout=1)
        return "accepted"

    monkeypatch.setattr("app.claude_wake.claude_wake_transport", transport)
    response = http.post("/relay/messages", json={
        "sender_runtime": "codex",
        "sender_session_ref": "sender",
        "recipient": "claude-code:target",
        "payload": "caller-surface payload",
        **scope,
    })
    assert response.status_code == 200
    assert started.wait(timeout=1)
    assert worker_threads[0].is_alive()
    release.set()
    worker_threads[0].join(timeout=1)
    assert not worker_threads[0].is_alive()


def test_wake_outcome_categories_are_distinct_and_secret_free(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    import app.claude_wake as wake

    caplog.set_level(logging.INFO, logger="app.claude_wake")
    scope = {"container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"]}
    secret = "token-secret"
    socket_path = "socket-secret"
    result = _wake_result(PAYLOAD["session_ref"], "delivery-category")
    result["deliveries"][0]["payload"] = "payload-secret"

    failed_registry = ClaudeWakeRegistry()
    failed_registry.register(**{**PAYLOAD, "token": secret, "socket_path": socket_path, "idle": True})
    monkeypatch.setattr(wake, "claude_wake_transport", lambda *_: False)
    _join(schedule_claude_relay_wake(result, scope, registry=failed_registry))

    ineligible_registry = ClaudeWakeRegistry()
    ineligible_registry.register(**{**PAYLOAD, "idle": False})
    _join(schedule_claude_relay_wake(result, scope, registry=ineligible_registry))

    error_registry = MagicMock(spec=ClaudeWakeRegistry)
    error_registry.probe.side_effect = RuntimeError("worker failure")
    _join(schedule_claude_relay_wake(result, scope, registry=error_registry))

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "category=transport_failed" in logged
    assert "category=not_eligible" in logged
    assert "category=worker_error" in logged
    assert secret not in logged and socket_path not in logged and "payload-secret" not in logged


def test_worker_start_failure_logs_and_later_send_retries(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    import app.claude_wake as wake

    class FailingThread:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("cannot start")

    registry = ClaudeWakeRegistry()
    registry.register(**{**PAYLOAD, "idle": True})
    scope = {"container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"]}
    thread_class = threading.Thread
    caplog.set_level(logging.INFO, logger="app.claude_wake")
    monkeypatch.setattr(wake.threading, "Thread", FailingThread)
    assert schedule_claude_relay_wake(_wake_result(PAYLOAD["session_ref"], "failed-start"), scope, registry=registry) is None
    monkeypatch.setattr(wake.threading, "Thread", thread_class)
    monkeypatch.setattr(wake, "claude_wake_transport", lambda *_: True)
    _join(schedule_claude_relay_wake(_wake_result(PAYLOAD["session_ref"], "retry"), scope, registry=registry))
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "category=worker_start_failed" in logged
    assert "category=trigger_written" in logged

def test_public_turn_busy_stop_idle_lifecycle_is_fail_closed(client) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes import create_router
    from core.relay import RelayService

    registry = ClaudeWakeRegistry()
    app = FastAPI()
    app.include_router(create_router(client.app.state.pallium_service, relay_service=RelayService(client.app.state.pallium_service._storage), claude_wake_registry=registry,
        relay_turn_callback=lambda req: registry.mark_busy(
            runtime=req["runtime"], session_ref=req["session_ref"],
            container_ref=req["container_ref"], actor_ref=req["actor_ref"])))
    client = TestClient(app, client=("127.0.0.1", 50000))
    payload = {**PAYLOAD, "session_ref": "session-test", "socket_path": "/tmp/test.sock", "idle": True}
    assert client.post("/internal/claude-wake/register", json=payload).status_code == 204
    scope = {"container_ref": payload["container_ref"], "actor_ref": payload["actor_ref"]}
    assert client.post("/relay/turn", json={"runtime": "claude-code", "session_ref": payload["session_ref"], **scope}).status_code == 200
    result = {"recipient": "claude-code:session-test", "deliveries": [{"delivery_id": "d1",
                    "state": "pending", "recipient_runtime": "claude-code", "recipient_session_ref": "session-test"}]}
    transport = MagicMock(return_value=True)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.claude_wake.claude_wake_transport", transport)
        _join(schedule_claude_relay_wake(result, scope, registry=registry))
    transport.assert_not_called()
    assert client.post("/internal/claude-wake/register", json=payload).status_code == 204
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.claude_wake.claude_wake_transport", transport)
        _join(schedule_claude_relay_wake(result, scope, registry=registry))
    transport.assert_called_once()
    assert not registry.probe(runtime="claude-code", session_ref="session-test", container_ref="wrong", actor_ref=scope["actor_ref"], transport=transport)


def test_windows_write_closes_event_after_cancelled_completion() -> None:
    class Overlapped:
        hEvent = None

    class Aborted(OSError):
        winerror = 995

    waits = []
    pywintypes = SimpleNamespace(OVERLAPPED=Overlapped)
    win32event = SimpleNamespace(WAIT_OBJECT_0=0, CreateEvent=lambda *_: "event", WaitForSingleObject=lambda *_: 258)
    closed = []

    def result(_handle, _overlapped, wait: bool) -> None:
        waits.append(wait)
        raise Aborted()

    win32file = SimpleNamespace(
        WriteFile=lambda *_: (997, 0), CancelIoEx=lambda *_: None,
        GetOverlappedResult=result, CloseHandle=lambda handle: closed.append(handle),
    )
    assert _windows_write("pipe", b"frame", pywintypes, win32event, win32file, SimpleNamespace(ERROR_IO_PENDING=997)) is False
    assert waits == [False] and closed == ["event"]


@pytest.mark.parametrize("use_cancel_io_ex", (True, False))
def test_windows_write_timeout_never_blocks_when_cancellation_stays_pending(use_cancel_io_ex: bool) -> None:
    class Overlapped:
        hEvent = None

    class Incomplete(OSError):
        winerror = 996

    cancellations: list[str] = []
    waits: list[bool] = []
    closed = []

    def cancel(label: str):
        def fail(*_args: object) -> None:
            cancellations.append(label)
            raise OSError("cancel failed")
        return fail

    def still_pending(_handle, _overlapped, wait: bool) -> None:
        waits.append(wait)
        if wait:
            pytest.fail("timeout cleanup must not block for completion")
        raise Incomplete()

    win32file = SimpleNamespace(
        WriteFile=lambda *_: (997, 0),
        CancelIoEx=cancel("ex") if use_cancel_io_ex else None,
        CancelIo=cancel("io"),
        GetOverlappedResult=still_pending,
        CloseHandle=lambda handle: closed.append(handle),
    )
    assert _windows_write(
        "pipe", b"frame", SimpleNamespace(OVERLAPPED=Overlapped),
        SimpleNamespace(WAIT_OBJECT_0=0, CreateEvent=lambda *_: "event", WaitForSingleObject=lambda *_: 258),
        win32file, SimpleNamespace(ERROR_IO_PENDING=997),
    ) is False
    assert cancellations == ["ex" if use_cancel_io_ex else "io"]
    assert waits == [False] and closed == []

def test_persisted_claude_d1_d2_d3_actual_hooks(
    client, monkeypatch, tmp_path, capsys,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.dependencies import build_router
    from tests.test_claude_code_integration import _load_claude_hook

    registry = ClaudeWakeRegistry()
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
        claude_wake_registry=registry,
    ))
    http = TestClient(app, client=("127.0.0.1", 50000))
    scope = {"container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"]}
    start = _load_claude_hook("session_start", monkeypatch)
    prompt = _load_claude_hook("user_prompt_submit", monkeypatch)
    stop = _load_claude_hook("stop", monkeypatch)

    for hook in (start, prompt, stop):
        monkeypatch.setattr(
            hook, "derive_container_ref",
            lambda *_: scope["container_ref"], raising=False,
        )
        monkeypatch.setattr(
            hook, "resolve_container_ref",
            lambda *_: scope["container_ref"], raising=False,
        )
        monkeypatch.setattr(
            hook, "derive_actor_ref", lambda: scope["actor_ref"], raising=False,
        )

    def relay(method, path, body, timeout=0.75):
        response = http.request(method, path, json=body)
        return response.json() if response.content else None

    def register(session, container, actor, **kwargs):
        response = http.post("/internal/claude-wake/register", json={
            **PAYLOAD,
            "session_ref": session,
            "container_ref": container,
            "actor_ref": actor,
            "idle": kwargs.get("idle", False),
        })
        return response.status_code == 204

    def acknowledge(deliveries, **_kwargs):
        acknowledged = []
        for delivery in deliveries:
            response = http.post("/relay/deliveries/ack", json={
                "delivery_id": delivery["delivery_id"],
                "claim_token": delivery["claim_token"],
                **scope,
            })
            assert response.status_code == 200
            acknowledged.append(delivery)
        return acknowledged

    for hook in (start, prompt, stop):
        monkeypatch.setattr(hook, "relay_request", relay)
    for hook in (prompt, stop):
        monkeypatch.setattr(hook, "acknowledge_relay", acknowledge)
    for hook in (start, prompt, stop):
        monkeypatch.setattr(hook, "register_claude_wake", register)

    monkeypatch.setattr(
        start, "read_hook_input",
        lambda: {"session_id": "session-test", "cwd": str(tmp_path)},
    )
    monkeypatch.setattr(start, "_fetch_orientation", lambda *_: [])
    with pytest.raises(SystemExit):
        start.main()
    sessions = http.get("/relay/sessions", params=scope).json()
    assert any(row["session_ref"] == "session-test" for row in sessions)
    assert http.post(
        "/relay/turn",
        json={"runtime": "codex", "session_ref": "sender", **scope},
    ).status_code == 200

    def send(payload, *, message_id=None):
        body = {
            "sender_runtime": "codex",
            "sender_session_ref": "sender",
            "recipient": "claude-code:session-test",
            "payload": payload,
            **scope,
        }
        if message_id is not None:
            body["message_id"] = message_id
        response = http.post("/relay/messages", json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def state(message):
        response = http.get(f"/relay/messages/{message['message_id']}", params=scope)
        assert response.status_code == 200
        return response.json()["deliveries"][0]["state"]

    sent1 = send("D1")
    assert state(sent1) == "pending"
    prompt_payload = {
        "session_id": "session-test",
        "cwd": str(tmp_path),
        "prompt": "normal prompt",
    }
    monkeypatch.setattr(prompt, "read_hook_input", lambda: prompt_payload)
    monkeypatch.setattr(prompt, "check_dedup", lambda *_: False)
    with pytest.raises(SystemExit):
        prompt.main()
    assert state(sent1) == "delivered"
    assert "D1" in capsys.readouterr().out

    sent2 = send("D2")
    assert state(sent2) == "pending"
    monkeypatch.setattr(stop, "read_hook_input", lambda: {
        "session_id": "session-test",
        "cwd": str(tmp_path),
        "transcript_path": "",
    })
    monkeypatch.setattr(stop, "read_turn", lambda *_: None)
    with pytest.raises(SystemExit) as stopped:
        stop.main()
    assert stopped.value.code == 2
    assert state(sent2) == "delivered"
    assert "D2" in capsys.readouterr().err
    ingested = []

    def pallium(method, path, body):
        ingested.append((method, path, body))
        response = http.request(method, path, json=body)
        return response.json() if response.content else None

    monkeypatch.setattr(stop, "pallium_request", pallium)
    monkeypatch.setattr(stop, "read_hook_input", lambda: {
        "session_id": "session-test", "cwd": str(tmp_path), "stop_hook_active": True,
        "transcript_path": "continuation.jsonl",
    })
    monkeypatch.setattr(stop, "read_turn", lambda *_: SimpleNamespace(
        assistant_text="handled D2 ✓", tool_calls=[],
    ))
    monkeypatch.setattr(stop, "build_work_trace_metadata", lambda *_: None)
    with pytest.raises(SystemExit) as continuation:
        stop.main()
    assert continuation.value.code == 0
    assert any(
        method == "POST" and path == "/items" and body[0]["content"] == "handled D2 ✓"
        for method, path, body in ingested
    )

    transport = MagicMock(return_value=True)
    monkeypatch.setattr("app.claude_wake.claude_wake_transport", transport)
    sent3 = send("D3", message_id="stable-d3")
    assert state(sent3) == "pending"
    transport.assert_called_once()
    assert send("D3", message_id="stable-d3")["message_id"] == sent3["message_id"]
    transport.assert_called_once()

    monkeypatch.setattr(prompt, "resolve_container_ref", lambda *_: "git:other/repo")
    with pytest.raises(SystemExit):
        prompt.main()
    assert state(sent2) == "delivered"
    assert state(sent3) == "pending"

    monkeypatch.setattr(prompt, "resolve_container_ref", lambda *_: scope["container_ref"])
    with pytest.raises(SystemExit):
        prompt.main()
    output = capsys.readouterr().out
    assert "D2" not in output and "D3" in output
    assert state(sent2) == state(sent3) == "delivered"

def test_restart_and_claim_recovery_deliver_once_on_user_prompt(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import storage.sqlite_relay as sqlite_relay
    from app.dependencies import build_router
    from tests.test_claude_code_integration import _load_claude_hook

    clock = [datetime(2030, 9, 2, tzinfo=timezone.utc)]

    def controlled_now(value=None):
        current = value or clock[0]
        return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)

    monkeypatch.setattr(sqlite_relay, "_now", controlled_now)
    scope = {"container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"]}

    def router(registry: ClaudeWakeRegistry) -> TestClient:
        app = FastAPI()
        app.include_router(build_router(
            client.app.state.pallium_service,
            relay_storage=client.app.state.pallium_service._storage,
            claude_wake_registry=registry,
        ))
        return TestClient(app, client=("127.0.0.1", 50000))

    original_registry = ClaudeWakeRegistry()
    before_restart = router(original_registry)
    assert before_restart.post("/internal/claude-wake/register", json={
        **PAYLOAD, "session_ref": "target", "idle": True,
    }).status_code == 204
    assert before_restart.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "target", **scope,
    }).status_code == 200

    restarted_registry = ClaudeWakeRegistry()
    http = router(restarted_registry)
    assert original_registry is not restarted_registry
    assert http.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "sender", **scope,
    }).status_code == 200
    transport = MagicMock(return_value=True)
    monkeypatch.setattr("app.claude_wake.claude_wake_transport", transport)

    def send(payload: str, message_id: str) -> dict:
        response = http.post("/relay/messages", json={
            "sender_runtime": "codex", "sender_session_ref": "sender",
            "recipient": "claude-code:target", "payload": payload,
            "message_id": message_id, **scope,
        })
        assert response.status_code == 200, response.text
        return response.json()

    def delivery(message: dict) -> dict:
        response = http.get(f"/relay/messages/{message['message_id']}", params=scope)
        assert response.status_code == 200
        return response.json()["deliveries"][0]

    restart_message = send("after restart", "restart-recovery")
    assert delivery(restart_message)["state"] == "pending"
    transport.assert_not_called()

    prompt = _load_claude_hook("user_prompt_submit", monkeypatch)
    monkeypatch.setattr(prompt, "resolve_container_ref", lambda *_: scope["container_ref"])
    monkeypatch.setattr(prompt, "derive_actor_ref", lambda: scope["actor_ref"])
    monkeypatch.setattr(prompt, "check_dedup", lambda *_: False)
    monkeypatch.setattr(prompt, "pallium_request", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(prompt, "read_hook_input", lambda: {
        "session_id": "target", "cwd": str(tmp_path), "prompt": "recover relay",
    })

    def relay(method, path, body, timeout=0.75):
        response = http.request(method, path, json=body)
        return response.json() if response.content else None

    def register(session, container, actor, **kwargs):
        response = http.post("/internal/claude-wake/register", json={
            **PAYLOAD, "session_ref": session, "container_ref": container,
            "actor_ref": actor, "idle": kwargs.get("idle", False),
        })
        return response.status_code == 204

    def acknowledge(deliveries, **_kwargs):
        for item in deliveries:
            response = http.post("/relay/deliveries/ack", json={
                "delivery_id": item["delivery_id"], "claim_token": item["claim_token"], **scope,
            })
            assert response.status_code == 200

    monkeypatch.setattr(prompt, "relay_request", relay)
    monkeypatch.setattr(prompt, "register_claude_wake", register)
    monkeypatch.setattr(prompt, "acknowledge_relay", acknowledge)

    with pytest.raises(SystemExit):
        prompt.main()
    assert "after restart" in capsys.readouterr().out
    assert delivery(restart_message)["state"] == "delivered"
    with pytest.raises(SystemExit):
        prompt.main()
    assert "after restart" not in capsys.readouterr().out

    claimed_message = send("after claim", "claim-recovery")
    assert send("after claim", "claim-recovery")["message_id"] == claimed_message["message_id"]
    claimed = http.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "target", **scope,
    }).json()["deliveries"]
    assert len(claimed) == 1 and claimed[0]["delivery_id"] == delivery(claimed_message)["delivery_id"]
    assert delivery(claimed_message)["state"] == "claimed"

    clock[0] += timedelta(seconds=61)
    with pytest.raises(SystemExit):
        prompt.main()
    assert "after claim" in capsys.readouterr().out
    recovered = delivery(claimed_message)
    assert recovered["state"] == "delivered" and recovered["attempts"] == 2
    with pytest.raises(SystemExit):
        prompt.main()
    assert "after claim" not in capsys.readouterr().out


def test_empty_stop_rearms_claude_wake_after_turn_admission(client, monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.dependencies import build_router
    from tests.test_claude_code_integration import _load_claude_hook

    registry = ClaudeWakeRegistry()
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
        claude_wake_registry=registry,
    ))
    http = TestClient(app, client=("127.0.0.1", 50000))
    scope = {"container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"]}
    stop = _load_claude_hook("stop", monkeypatch)
    monkeypatch.setattr(stop, "resolve_container_ref", lambda *_: scope["container_ref"])
    monkeypatch.setattr(stop, "derive_actor_ref", lambda: scope["actor_ref"])

    def register(session, container, actor, **kwargs):
        response = http.post("/internal/claude-wake/register", json={
            **PAYLOAD, "session_ref": session, "container_ref": container,
            "actor_ref": actor, "idle": kwargs.get("idle", False),
        })
        return response.status_code == 204

    def relay(method, path, body, *, timeout):
        response = http.request(method, path, json=body)
        return response.json() if response.content else None

    monkeypatch.setattr(stop, "register_claude_wake", register)
    monkeypatch.setattr(stop, "relay_request", relay)
    monkeypatch.setattr(stop, "read_hook_input", lambda: {
        "session_id": "empty-stop", "cwd": str(tmp_path), "transcript_path": "",
    })
    stop.main()

    assert http.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "sender", **scope,
    }).status_code == 200
    triggered = threading.Event()
    monkeypatch.setattr("app.claude_wake.claude_wake_transport", lambda *_: triggered.set() or True)
    sent = http.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": "claude-code:empty-stop", "payload": "wake after empty stop", **scope,
    })
    assert sent.status_code == 200
    assert triggered.wait(timeout=1)


def test_post_start_lost_http_intent_reconciles_without_claiming_relay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.config import AppConfig
    from app.main import create_app
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES
    from tests.test_claude_code_integration import _load_claude_hook

    scope = {"container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"]}
    transport_called = threading.Event()
    transport_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.claude_wake.claude_wake_transport",
        lambda socket_path, token: transport_calls.append((socket_path, token)) or transport_called.set() or True,
    )
    app = create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))

    with TestClient(app, client=("127.0.0.1", 50000)) as http:
        assert http.post("/relay/turn", json={
            "runtime": "codex", "session_ref": "sender", **scope,
        }).status_code == 200
        assert http.post("/relay/turn", json={
            "runtime": "claude-code", "session_ref": "lost-http", **scope,
        }).status_code == 200
        common = _load_claude_hook("common", monkeypatch)
        monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", PAYLOAD["socket_path"])
        monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", PAYLOAD["token"])
        monkeypatch.setattr(
            common.urllib.request,
            "build_opener",
            lambda *_: SimpleNamespace(open=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError())),
        )
        assert not common.register_claude_wake("lost-http", scope["container_ref"], scope["actor_ref"], idle=True)

        sent = http.post("/relay/messages", json={
            "sender_runtime": "codex", "sender_session_ref": "sender",
            "recipient": "claude-code:lost-http", "payload": "recover me", **scope,
        })
        assert sent.status_code == 200
        message_id = sent.json()["message_id"]
        assert transport_called.wait(timeout=1)
        assert transport_calls == [(PAYLOAD["socket_path"], PAYLOAD["token"])]
        status = http.get(f"/relay/messages/{message_id}", params=scope)
        assert status.status_code == 200
        delivery = status.json()["deliveries"][0]
        assert delivery["state"] == "pending"
        assert delivery["claim_token"] is None and delivery["receipt"] is None
        assert delivery["claimed_at"] is None and delivery["delivered_at"] is None and delivery["attempts"] == 0

        reconciler = app.state._claude_wake_reconciler
        assert reconciler is not None
    assert reconciler._thread is not None and not reconciler._thread.is_alive()

def test_persisted_idle_wakes_once_after_real_app_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from fastapi.testclient import TestClient

    import app.main as main
    from app.config import AppConfig
    from app.main import create_app
    from core.relay import RelayService
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES
    from tests.test_claude_code_integration import _load_claude_hook

    scope = {"container_ref": PAYLOAD["container_ref"], "actor_ref": PAYLOAD["actor_ref"]}
    transport_called = threading.Event()
    transport_calls: list[tuple[str, str]] = []
    monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(tmp_path / "wake"))
    monkeypatch.setattr(
        "app.claude_wake.claude_wake_transport",
        lambda socket_path, token: transport_calls.append((socket_path, token)) or transport_called.set() or "accepted",
    )
    config = AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )
    original_start = main.start_claude_wake_reconciler
    monkeypatch.setattr(main, "start_claude_wake_reconciler", lambda *_: None)
    with TestClient(create_app(config), client=("127.0.0.1", 50000)) as http_a:
        common = _load_claude_hook("common", monkeypatch)
        monkeypatch.setattr(common, "CLAUDE_WAKE_DIR", tmp_path / "wake")
        monkeypatch.setattr(common, "CLAUDE_WAKE_INTENTS_DIR", tmp_path / "wake" / "intents")
        registration = {**PAYLOAD, "session_ref": "restart-target", "idle": True, "intent_id": "app-a"}
        assert common._write_wake_intent(registration)
        assert http_a.post("/internal/claude-wake/register", json=registration).status_code == 204
        relay = RelayService(http_a.app.state.pallium_service._storage)
        relay.turn(runtime="codex", session_ref="sender", **scope)
        relay.turn(runtime="claude-code", session_ref="restart-target", **scope)
        sent = relay.send(
            sender_runtime="codex", sender_session_ref="sender",
            recipient="claude-code:restart-target", payload="persisted wake", **scope,
        )
        delivery = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
        assert delivery["state"] == "pending" and delivery["claim_token"] is None and delivery["attempts"] == 0

    monkeypatch.setattr(main, "start_claude_wake_reconciler", original_start)
    app_b = create_app(config)
    with TestClient(app_b, client=("127.0.0.1", 50000)) as http_b:
        assert transport_called.wait(timeout=1)
        assert transport_calls == [(PAYLOAD["socket_path"], PAYLOAD["token"])]
        response = http_b.get(f"/relay/messages/{sent['message_id']}", params=scope)
        assert response.status_code == 200
        delivery = response.json()["deliveries"][0]
        assert delivery["state"] == "pending"
        assert delivery["claim_token"] is None and delivery["receipt"] is None and delivery["attempts"] == 0
        reconciler = app_b.state._claude_wake_reconciler
        assert reconciler is not None
        registry = app_b.state.claude_wake_registry
        registry.set_reconcile_signal(None)
        stop = _load_claude_hook("stop", monkeypatch)
        monkeypatch.setattr(stop, "resolve_container_ref", lambda *_: scope["container_ref"])
        monkeypatch.setattr(stop, "derive_actor_ref", lambda: scope["actor_ref"])
        monkeypatch.setattr(stop, "read_hook_input", lambda: {
            "session_id": "restart-target", "cwd": str(tmp_path), "transcript_path": "",
        })
        registrations: list[dict[str, object]] = []
        claimed_ids: list[list[str]] = []
        states_before_ack: list[str] = []
        acknowledged_ids: list[str] = []

        def register(session: object, container: object, actor: object, *, idle: bool = False) -> bool:
            registration = {
                **PAYLOAD, "session_ref": session, "container_ref": container,
                "actor_ref": actor, "idle": idle, "intent_id": f"stop-{len(registrations)}",
            }
            registrations.append(registration)
            assert common._write_wake_intent(registration)
            return http_b.post("/internal/claude-wake/register", json=registration).status_code == 204

        def relay(method: str, path: str, body: dict[str, object], *, timeout: float) -> object:
            response = http_b.request(method, path, json=body)
            assert response.status_code == 200
            result = response.json() if response.content else None
            if path == "/relay/turn":
                claimed_ids.append([item["delivery_id"] for item in result["deliveries"]])
            return result

        def acknowledge(deliveries: list[dict[str, object]], **_kwargs: object) -> list[dict[str, object]]:
            for item in deliveries:
                status = http_b.get(f"/relay/messages/{sent['message_id']}", params=scope).json()["deliveries"][0]
                states_before_ack.append(status["state"])
                response = http_b.post("/relay/deliveries/ack", json={
                    "delivery_id": item["delivery_id"], "claim_token": item["claim_token"], **scope,
                })
                assert response.status_code == 200
                acknowledged_ids.append(item["delivery_id"])
            return deliveries

        monkeypatch.setattr(stop, "register_claude_wake", register)
        monkeypatch.setattr(stop, "relay_request", relay)
        monkeypatch.setattr(stop, "acknowledge_relay", acknowledge)
        with pytest.raises(SystemExit) as exited:
            stop.main()
        assert exited.value.code == 2
        emitted = capsys.readouterr().err
        assert "persisted wake" in emitted and "codex" in emitted
        assert claimed_ids == [[delivery["delivery_id"]]]
        assert states_before_ack == ["claimed"] and acknowledged_ids == [delivery["delivery_id"]]
        delivered = http_b.get(f"/relay/messages/{sent['message_id']}", params=scope).json()["deliveries"][0]
        assert delivered["state"] == "delivered" and delivered["attempts"] == 1

        stop.main()
        assert capsys.readouterr().err == ""
        assert claimed_ids == [[delivery["delivery_id"]], []]
        assert acknowledged_ids == [delivery["delivery_id"]]
        candidates = registry.recovery_candidates()
        assert [candidate["session_ref"] for candidate in candidates] == ["restart-target"]
        assert all(registration["idle"] is True for registration in registrations)
    assert reconciler._thread is not None and not reconciler._thread.is_alive()