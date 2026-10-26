"""Tests for Claude Code wake transport and dispatch."""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
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
from core.relay_activation import ActivationAttemptResult


PAYLOAD = {
    "runtime": "claude-code",
    "session_ref": "session-test",
    "container_ref": "git:example/repo",
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
            "recipient_endpoint_id": "relay-session-" + "a" * 32,
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
        result = claude_wake_transport(socket_path, "test-token")
        assert result.outcome == "accepted"
        assert result.evidence == ("submission_attempted", "transport_accepted")
        assert done.wait(timeout=2)
        thread.join(timeout=1)
        lines = [line for line in received if line.strip()]
        auth, frame = (json.loads(line) for line in lines[:2])
        assert auth == {"type": "auth", "token": "test-token"}
        assert frame["msgV"] == 1 and frame["type"] == "user"
        assert frame["message"]["role"] == "user" and frame["priority"] == "next"
        assert frame["from"] == "pallium-relay"

    @pytest.mark.skipif(os.name == "nt", reason="Unix socket test")
    def test_posix_transport_missing_path_is_unreachable(self) -> None:
        result = claude_wake_transport("/nonexistent/socket.sock", "token")
        assert result.outcome == "failed"
        assert result.destination_health_update == "unreachable"

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
        result = transport._posix_transport("ignored", "token")
        assert result.outcome == "deferred" and result.native_retry_safe

    def test_windows_write_cancels_after_bounded_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.claude_wake_transport as transport

        pending: list[tuple[object, object]] = []
        monkeypatch.setattr(transport, "_pending_windows_writes", pending)
        cancelled = []
        closed = []

        class Overlapped:
            hEvent = None

        pywintypes = SimpleNamespace(OVERLAPPED=Overlapped)
        win32event = SimpleNamespace(WAIT_OBJECT_0=0, CreateEvent=lambda *_: "event", WaitForSingleObject=lambda *_: 258)
        win32file = SimpleNamespace(WriteFile=lambda *_: (997, 0), CancelIoEx=lambda handle, overlapped: cancelled.append((handle, overlapped)), GetOverlappedResult=lambda *_: 0, CloseHandle=lambda handle: closed.append(handle))
        winerror = SimpleNamespace(ERROR_IO_PENDING=997)
        assert _windows_write("pipe", b"frame", pywintypes, win32event, win32file, winerror) is False
        assert len(cancelled) == 1 and closed == ["event"] and pending == []

    def test_windows_transport_clean_write_is_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys
        import app.claude_wake_transport as transport

        writes: list[bytes] = []
        monkeypatch.setitem(sys.modules, "pywintypes", SimpleNamespace())
        monkeypatch.setitem(sys.modules, "win32event", SimpleNamespace())
        monkeypatch.setitem(sys.modules, "winerror", SimpleNamespace())
        monkeypatch.setitem(sys.modules, "win32file", SimpleNamespace(GENERIC_WRITE=1, OPEN_EXISTING=2, FILE_FLAG_OVERLAPPED=4, CreateFile=lambda *_: "pipe", CloseHandle=lambda *_: None))
        monkeypatch.setattr(transport, "_windows_write", lambda _handle, data, *_: writes.append(data) or True)
        result = transport._windows_transport(r"\\.\pipe\claude", "token")
        assert result.outcome == "accepted"
        auth, frame = (json.loads(data) for data in writes)
        assert auth["type"] == "auth" and frame["type"] == "user"

    @pytest.mark.parametrize("code, expected", [(2, "failed"), (231, "deferred"), (121, "deferred"), (5, "deferred")])
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
        assert transport._windows_transport(r"\\.\pipe\claude", "token").outcome == expected

    def test_windows_transport_import_failure_is_retryable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins
        import app.claude_wake_transport as transport

        original_import = builtins.__import__
        monkeypatch.setattr(builtins, "__import__", lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError()) if name == "pywintypes" else original_import(name, *args, **kwargs))
        result = transport._windows_transport(r"\\.\pipe\claude", "token")
        assert result.outcome == "deferred" and result.native_retry_safe

class TestDispatch:
    """Dispatch tests: route to correct handler, malformed=no-op."""

    def test_claude_code_delivery_calls_attempt(self) -> None:
        """claude-code delivery routes to schedule_claude_relay_wake."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {
            "recipient": "claude-code:session-test",
            "deliveries": [
                {
                    "delivery_id": "delivery-1",
                    "recipient_endpoint_id": "relay-session-" + "a" * 32,
                    "state": "pending",
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": "session-test",
                }
            ],
        }
        scope = {
            "container_ref": "git:example/repo",
        }

        _join(schedule_claude_relay_wake(result, scope, registry=registry))

        registry.attempt.assert_called_once()
        call_kwargs = registry.attempt.call_args[1]
        assert call_kwargs["runtime"] == "claude-code"
        assert call_kwargs["session_ref"] == "session-test"
        assert call_kwargs["container_ref"] == "git:example/repo"
        assert callable(call_kwargs["transport"])

    def test_malformed_delivery_no_op(self) -> None:
        """Malformed delivery (no deliveries list) calls nothing."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {"recipient": "claude-code:session-test"}
        scope = {
            "container_ref": "git:example/repo",
        }

        schedule_claude_relay_wake(result, scope, registry=registry)

        registry.attempt.assert_not_called()

    def test_non_dict_result_no_op(self) -> None:
        """Non-dict result calls nothing."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        schedule_claude_relay_wake("not a dict", {}, registry=registry)
        registry.attempt.assert_not_called()

    def test_missing_container_ref_no_op(self) -> None:
        """Missing container_ref in scope calls nothing."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {
            "recipient": "claude-code:session-test",
            "deliveries": [
                {
                    "delivery_id": "delivery-1",
                    "recipient_endpoint_id": "relay-session-" + "a" * 32,
                    "state": "pending",
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": "session-test",
                }
            ],
        }
        scope = {"actor_ref": "local"}  # Missing container_ref

        schedule_claude_relay_wake(result, scope, registry=registry)

        registry.attempt.assert_not_called()

    def test_bad_session_ref_no_op(self) -> None:
        """Session ref with whitespace/non-printable calls nothing."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {
            "recipient": "claude-code:bad session",
            "deliveries": [
                {
                    "delivery_id": "delivery-1",
                    "recipient_endpoint_id": "relay-session-" + "a" * 32,
                    "state": "pending",
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": " bad session ",  # Not stripped in delivery
                }
            ],
        }
        scope = {
            "container_ref": "git:example/repo",
        }

        schedule_claude_relay_wake(result, scope, registry=registry)

        registry.attempt.assert_not_called()

    def test_valid_selector_alias_calls_attempt(self) -> None:
        """Valid @alias selector calls probe."""

        native_thread = threading.Thread
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {
            "recipient": "claude-code:@work",
            "deliveries": [
                {
                    "delivery_id": "delivery-1",
                    "recipient_endpoint_id": "relay-session-" + "a" * 32,
                    "state": "pending",
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": "session-test",
                }
            ],
        }
        scope = {
            "container_ref": "git:example/repo",
        }

        worker = schedule_claude_relay_wake(result, scope, registry=registry)
        assert isinstance(worker, threading.Thread)
        _join(worker)

        registry.attempt.assert_called_once()
        args = registry.attempt.call_args.kwargs
        assert args["runtime"] == "claude-code" and args["session_ref"] == "session-test"
        assert args["container_ref"] == scope["container_ref"]
        assert args["delivery_id"] == "delivery-1"
        assert args["recipient_endpoint_id"] == "relay-session-" + "a" * 32
        assert callable(args["transport"]) and callable(args["still_pending"])
        assert threading.Thread is native_thread

    def test_invalid_selector_format_no_op(self) -> None:
        """Invalid alias format (@-bad) calls nothing."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {
            "recipient": "claude-code:@-bad",
            "deliveries": [
                {
                    "delivery_id": "delivery-1",
                    "recipient_endpoint_id": "relay-session-" + "a" * 32,
                    "state": "pending",
                    "recipient_runtime": "claude-code",
                    "recipient_session_ref": "session-test",
                }
            ],
        }
        scope = {
            "container_ref": "git:example/repo",
        }

        schedule_claude_relay_wake(result, scope, registry=registry)

        registry.attempt.assert_not_called()

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
        }

        schedule_claude_relay_wake(result, scope, registry=registry)

        registry.attempt.assert_not_called()

    def test_multiple_deliveries_no_op(self) -> None:
        """Multiple deliveries (should be exactly 1) calls nothing."""
        registry = MagicMock(spec=ClaudeWakeRegistry)
        result = {
            "recipient": "claude-code:session-test",
            "deliveries": [
                {
                    "delivery_id": "delivery-1",
                    "recipient_endpoint_id": "relay-session-" + "a" * 32,
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
        }

        schedule_claude_relay_wake(result, scope, registry=registry)

        registry.attempt.assert_not_called()

def test_wake_worker_returns_without_waiting_and_logs_credential_free_outcome(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    import app.claude_wake as wake

    registry = ClaudeWakeRegistry()
    secret = "token-secret"
    session_ref = "session-א"
    scope = {"container_ref": "git:é/repo"}
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
    assert "category=accepted" in logged and "latency_ms=" in logged
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
            "container_ref": PAYLOAD["container_ref"],
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


def test_drain_joins_target_registry_through_final_trace_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.claude_wake as wake

    target_registry = ClaudeWakeRegistry()
    other_registry = ClaudeWakeRegistry()
    target_registry.register(**{**PAYLOAD, "token": "target-token", "idle": True})
    other_registry.register(**{**PAYLOAD, "token": "other-token", "idle": True})
    target_entered = threading.Event()
    other_entered = threading.Event()
    release_target = threading.Event()
    release_other = threading.Event()
    trace_entered = threading.Event()
    release_trace = threading.Event()
    drain_started = threading.Event()
    drain_finished = threading.Event()
    failures: list[BaseException] = []

    def transport(_socket_path: str, token: str) -> str:
        if token == "target-token":
            target_entered.set()
            assert release_target.wait(timeout=5)
            return "accepted"
        other_entered.set()
        assert release_other.wait(timeout=5)
        return "accepted"

    def target_trace(event: dict[str, object]) -> None:
        if event["stage"] == "completed":
            trace_entered.set()
            assert release_trace.wait(timeout=5)

    def drain() -> None:
        drain_started.set()
        try:
            wake.drain_claude_relay_wakes(target_registry)
        except BaseException as exc:
            failures.append(exc)
        finally:
            drain_finished.set()

    monkeypatch.setattr(wake, "claude_wake_transport", transport)
    target_worker = other_worker = None
    drain_thread = threading.Thread(target=drain, daemon=True)
    try:
        target_worker = schedule_claude_relay_wake(
            _wake_result(PAYLOAD["session_ref"], "target-delivery"),
            {"container_ref": PAYLOAD["container_ref"]},
            registry=target_registry,
            trace_callback=target_trace,
        )
        other_worker = schedule_claude_relay_wake(
            _wake_result(PAYLOAD["session_ref"], "other-delivery"),
            {"container_ref": PAYLOAD["container_ref"]},
            registry=other_registry,
        )
        assert target_worker is not None and other_worker is not None
        assert target_entered.wait(timeout=1)
        assert other_entered.wait(timeout=1)

        drain_thread.start()
        assert drain_started.wait(timeout=1)
        release_target.set()
        assert trace_entered.wait(timeout=1)
        assert not drain_finished.wait(timeout=0.05)

        release_trace.set()
        assert drain_finished.wait(timeout=1)
        assert not failures
        assert not target_worker.is_alive()
        assert other_worker.is_alive()
    finally:
        release_target.set()
        release_trace.set()
        release_other.set()
        for worker in (target_worker, other_worker):
            if worker is not None:
                worker.join(timeout=1)
        if drain_thread.ident is not None:
            drain_thread.join(timeout=1)
        assert all(worker is None or not worker.is_alive() for worker in (target_worker, other_worker))
        assert not drain_thread.is_alive()


def test_drain_keeps_completed_predecessor_and_eligible_successor_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.claude_wake as wake

    registry = ClaudeWakeRegistry()
    registry.register(**{**PAYLOAD, "idle": True})
    first_transport_entered = threading.Event()
    release_first_trace = threading.Event()
    first_trace_entered = threading.Event()
    second_transport_entered = threading.Event()
    release_second_transport = threading.Event()
    drain_started = threading.Event()
    drain_finished = threading.Event()
    calls: list[int] = []
    trace_events: list[dict[str, object]] = []
    errors: list[BaseException] = []

    def transport(*_args: object) -> str:
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            first_transport_entered.set()
            return "accepted"
        second_transport_entered.set()
        assert release_second_transport.wait(timeout=5)
        return "accepted"

    def trace(event: dict[str, object]) -> None:
        trace_events.append(event)
        if event["stage"] == "completed" and event["delivery_id"] == "first-delivery":
            first_trace_entered.set()
            assert release_first_trace.wait(timeout=5)

    def drain() -> None:
        drain_started.set()
        try:
            wake.drain_claude_relay_wakes(registry)
        except BaseException as exc:
            errors.append(exc)
        finally:
            drain_finished.set()

    monkeypatch.setattr(wake, "claude_wake_transport", transport)
    first_worker = second_worker = None
    drain_thread = threading.Thread(target=drain, daemon=True)
    try:
        first_worker = schedule_claude_relay_wake(
            _wake_result(PAYLOAD["session_ref"], "first-delivery"),
            {"container_ref": PAYLOAD["container_ref"]},
            registry=registry,
            trace_callback=trace,
        )
        assert first_worker is not None
        assert first_transport_entered.wait(timeout=1)
        assert first_trace_entered.wait(timeout=1)
        assert registry.release_delivery("first-delivery")
        assert registry.register(**{**PAYLOAD, "idle": True})

        second_worker = schedule_claude_relay_wake(
            _wake_result(PAYLOAD["session_ref"], "second-delivery"),
            {"container_ref": PAYLOAD["container_ref"]},
            registry=registry,
            trace_callback=trace,
        )
        assert second_worker is not None and second_worker is not first_worker
        assert second_transport_entered.wait(timeout=1)
        with wake._workers_lock:
            owned = {
                worker for owner_id, worker in wake._workers
                if owner_id == id(registry)
            }
        assert first_worker in owned and second_worker in owned
        assert not any(event["stage"] == "associated" for event in trace_events)

        wake.stop_claude_relay_wake_admission(registry)
        drain_thread.start()
        assert drain_started.wait(timeout=1)
        release_first_trace.set()
        assert not drain_finished.wait(timeout=0.05)
        release_second_transport.set()
        assert drain_finished.wait(timeout=1)
        assert not errors
        assert not first_worker.is_alive() and not second_worker.is_alive()
    finally:
        release_first_trace.set()
        release_second_transport.set()
        for worker in (first_worker, second_worker):
            if worker is not None:
                worker.join(timeout=1)
        if drain_thread.ident is not None:
            drain_thread.join(timeout=1)
        assert all(worker is None or not worker.is_alive() for worker in (first_worker, second_worker))
        assert not drain_thread.is_alive()


def test_shutdown_racing_prepared_trace_prevents_native_worker_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.claude_wake as wake

    registry = ClaudeWakeRegistry()
    registry.register(**{**PAYLOAD, "idle": True})
    prepared = threading.Event()
    release_prepared = threading.Event()
    admission_stopped = threading.Event()
    schedule_done = threading.Event()
    trace_events: list[dict[str, object]] = []
    transport_calls: list[bool] = []
    scheduled: list[threading.Thread | None] = []
    errors: list[BaseException] = []

    def trace(event: dict[str, object]) -> None:
        trace_events.append(event)
        if event["stage"] == "prepared":
            prepared.set()
            assert release_prepared.wait(timeout=5)

    def schedule() -> None:
        try:
            scheduled.append(schedule_claude_relay_wake(
                _wake_result(PAYLOAD["session_ref"], "shutdown-race"),
                {"container_ref": PAYLOAD["container_ref"]},
                registry=registry,
                trace_callback=trace,
            ))
        except BaseException as exc:
            errors.append(exc)
        finally:
            schedule_done.set()

    def stop_admission() -> None:
        try:
            wake.stop_claude_relay_wake_admission(registry)
        except BaseException as exc:
            errors.append(exc)
        finally:
            admission_stopped.set()

    monkeypatch.setattr(wake, "claude_wake_transport", lambda *_: transport_calls.append(True) or "accepted")
    schedule_thread = threading.Thread(target=schedule, daemon=True)
    stop_thread = threading.Thread(target=stop_admission, daemon=True)
    try:
        schedule_thread.start()
        assert prepared.wait(timeout=1)
        stop_thread.start()
        assert admission_stopped.wait(timeout=1)
        release_prepared.set()
        assert schedule_done.wait(timeout=1)
        assert scheduled == [None]
        assert not errors
        assert not transport_calls
        completed = [event for event in trace_events if event["stage"] == "completed"]
        assert len(completed) == 1
        assert completed[0]["outcome"] == "deferred"
        wake.drain_claude_relay_wakes(registry)
    finally:
        release_prepared.set()
        for worker in (schedule_thread, stop_thread):
            if worker.ident is not None:
                worker.join(timeout=1)
            assert not worker.is_alive()


def test_transport_exception_retains_exact_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
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
    scope = {"container_ref": PAYLOAD["container_ref"]}
    _join(schedule_claude_relay_wake(_wake_result(PAYLOAD["session_ref"], "first"), scope, registry=registry))
    _join(schedule_claude_relay_wake(_wake_result(PAYLOAD["session_ref"], "second"), scope, registry=registry))
    assert calls == 1


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
    scope = {"container_ref": PAYLOAD["container_ref"]}
    worker = schedule_claude_relay_wake(_wake_result(PAYLOAD["session_ref"]), scope, registry=registry)
    assert started.wait(timeout=1)
    registry.register(**{**PAYLOAD, "token": "replacement", "idle": False})
    release.set()
    _join(worker)
    result = registry.attempt(
        runtime=PAYLOAD["runtime"], session_ref=PAYLOAD["session_ref"],
        container_ref=PAYLOAD["container_ref"],
        transport=lambda *_: pytest.fail("replacement must remain busy"),
    )
    assert result.outcome == "deferred"

def test_relay_messages_response_does_not_wait_for_claude_transport(
    client, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    from contextlib import contextmanager
    import time
    import traceback

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    import app.dependencies as dependencies
    from app.dependencies import build_router
    from core.errors import ImmediateTransactionBusyError
    from storage.sqlite_schema import (
        RelayDeliveryRecord, RelayEndpointGenerationRecord, RelayMessageRecord, RelaySessionRecord,
    )

    registry = ClaudeWakeRegistry()
    app = FastAPI()
    service = client.app.state.pallium_service
    storage = service._storage
    app.include_router(build_router(service, relay_storage=storage, claude_wake_registry=registry))
    http = TestClient(app, client=("127.0.0.1", 50000))
    scope = {"container_ref": PAYLOAD["container_ref"]}

    def relay_state():
        with storage._relay_session_factory() as db:
            def rows(model):
                ordering = tuple(model.__table__.primary_key.columns)
                return tuple(tuple(row) for row in db.execute(
                    select(*model.__table__.columns).order_by(*ordering)
                ).all())
            return {
                "sessions": rows(RelaySessionRecord),
                "endpoint_generations": rows(RelayEndpointGenerationRecord),
                "messages": rows(RelayMessageRecord),
                "deliveries": rows(RelayDeliveryRecord),
            }

    native_relay_turn = storage.relay_turn
    native_begin = storage._begin_relay_immediate
    turn_scope = threading.local()
    enrollment_attempts: list[dict[str, object]] = []

    def observed_relay_turn(*args, **kwargs):
        identity = (kwargs.get("runtime"), kwargs.get("session_ref"), kwargs.get("container_ref"))
        if identity not in {
            ("claude-code", "target", scope["container_ref"]),
            ("codex", "sender", scope["container_ref"]),
        }:
            return native_relay_turn(*args, **kwargs)
        observation: dict[str, object] = {
            "identity": identity, "acquired": False, "committed": False,
            "error": None, "result_present": False, "result_identity_matches": False,
        }
        enrollment_attempts.append(observation)
        turn_scope.observation = observation
        try:
            result = native_relay_turn(*args, **kwargs)
            observation["result_present"] = result is not None
            session = result.get("session") if isinstance(result, dict) else None
            observation["result_identity_matches"] = (
                isinstance(session, dict)
                and (session.get("runtime"), session.get("session_ref"), session.get("container_ref")) == identity
                and isinstance(session.get("endpoint_id"), str)
                and type(session.get("scope_generation")) is int
            )
            return result
        except BaseException as exc:
            observation["error"] = exc
            raise
        finally:
            turn_scope.observation = None

    @contextmanager
    def observed_begin(*args, **kwargs):
        observation = getattr(turn_scope, "observation", None)
        if observation is None:
            with native_begin(*args, **kwargs) as db:
                yield db
            return
        try:
            with native_begin(*args, **kwargs) as db:
                observation["acquired"] = True
                yield db
            observation["committed"] = True
        except BaseException as exc:
            observation["error"] = exc
            raise

    @contextmanager
    def initial_enrollment_observers():
        try:
            with monkeypatch.context() as admission:
                yield admission
        except BaseException:
            http.close()
            raise

    with initial_enrollment_observers() as admission:
        admission.setattr(storage, "relay_turn", observed_relay_turn)
        admission.setattr(storage, "_begin_relay_immediate", observed_begin)
        for runtime, session_ref in (("claude-code", "target"), ("codex", "sender")):
            assert not registry._registrations
            before = relay_state()
            assert before["messages"] == () and before["deliveries"] == ()
            request_body = {"runtime": runtime, "session_ref": session_ref, **scope}
            deadline = time.monotonic() + 5
            enrollment_attempts.clear()
            expected_attempts = 1
            response = http.post("/relay/turn", json=request_body)
            if response.status_code == 503:
                assert len(enrollment_attempts) == 1
                refusal = enrollment_attempts[0]
                assert not registry._registrations
                assert refusal["identity"] == (runtime, session_ref, scope["container_ref"])
                assert type(refusal["error"]) is ImmediateTransactionBusyError
                assert refusal["error"].acquisition_stage == "setup_deadline"
                assert refusal["acquired"] is False and refusal["committed"] is False, (
                    "setup_deadline refusal is retryable only before acquisition with no result"
                )
                assert refusal["result_present"] is False
                assert response.json() == {"detail": {"code": "relay_busy", "retryable": True}}
                assert response.headers.get("Retry-After") == "1"
                assert relay_state() == before
                delay = int(response.headers["Retry-After"])
                assert 0 < delay < deadline - time.monotonic()
                time.sleep(delay)
                assert time.monotonic() < deadline
                assert relay_state() == before
                assert not registry._registrations
                response = http.post("/relay/turn", json=request_body)
                expected_attempts = 2
            assert response.status_code == 200, (
                "initial empty-session enrollment must return 200 after at most one bounded retry"
            )
            assert len(enrollment_attempts) == expected_attempts
            success = enrollment_attempts[-1]
            assert success["identity"] == (runtime, session_ref, scope["container_ref"])
            assert success["acquired"] is True and success["committed"] is True
            assert success["error"] is None and success["result_present"] is True
            assert success["result_identity_matches"] is True
            current = relay_state()
            assert current["messages"] == () and current["deliveries"] == ()

    assert http.post("/internal/claude-wake/register", json={
        **PAYLOAD, "session_ref": "target", "idle": True,
    }).status_code == 204
    started = threading.Event()
    release = threading.Event()
    worker_threads: list[threading.Thread] = []
    scheduled: list[threading.Thread] = []
    attempts, errors, phases = [], [], []
    original_attempt = registry.attempt
    original_schedule = dependencies.schedule_claude_relay_wake

    def attempt(*args, **kwargs):
        phases.append(("attempt_entered", time.monotonic()))
        try:
            result = original_attempt(*args, **kwargs)
        except BaseException:
            errors.append(traceback.format_exc(limit=12))
            raise
        attempts.append((result.outcome, result.reason))
        return result

    def schedule(*args, **kwargs):
        phases.append(("schedule_entered", time.monotonic()))
        try:
            worker = original_schedule(*args, **kwargs)
        except BaseException:
            errors.append(traceback.format_exc(limit=12))
            raise
        if worker is not None:
            scheduled.append(worker)
        phases.append(("schedule_returned", time.monotonic()))
        return worker

    def transport(*_: object) -> str:
        worker_threads.append(threading.current_thread())
        phases.append(("transport_entered", time.monotonic()))
        started.set()
        try:
            assert release.wait(timeout=5)
        except BaseException:
            errors.append(traceback.format_exc(limit=12))
            raise
        return "accepted"

    monkeypatch.setattr(registry, "attempt", attempt)
    monkeypatch.setattr(dependencies, "schedule_claude_relay_wake", schedule)
    monkeypatch.setattr("app.claude_wake.claude_wake_transport", transport)
    caplog.set_level(logging.INFO, logger="app.claude_wake")
    try:
        phases.append(("request_started", time.monotonic()))
        response = http.post("/relay/messages", json={
            "sender_runtime": "codex",
            "sender_session_ref": "sender",
            "recipient": "claude-code:target",
            "payload": "caller-surface payload",
            **scope,
        })
        phases.append(("response_returned", time.monotonic()))
        assert response.status_code == 200, response.text
        arrived = started.wait(timeout=1)
        diagnostics = None
        if not arrived:
            frames = sys._current_frames()
            diagnostics = {
                "response": response.text[:2048], "phases": list(phases),
                "attempts": list(attempts), "errors": list(errors),
                "workers": [(worker.name, worker.ident, worker.is_alive()) for worker in scheduled[:4]],
                "stacks": {
                    str(worker.ident): "".join(traceback.format_stack(frames[worker.ident], limit=12))[-4096:]
                    for worker in scheduled[:4] if worker.ident in frames
                },
            }
            try:
                print("claude_transport_arrival=" + json.dumps(diagnostics), file=sys.stderr)
            except Exception:
                pass
        assert arrived, diagnostics
        assert worker_threads[0].is_alive()
    finally:
        release.set()
        for worker in dict.fromkeys([*scheduled, *worker_threads]):
            worker.join(timeout=1)
        http.close()
    assert not errors, errors
    assert not worker_threads[0].is_alive()
    assert all(not worker.is_alive() for worker in scheduled)


def test_wake_outcome_categories_are_distinct_and_secret_free(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    import app.claude_wake as wake

    caplog.set_level(logging.INFO, logger="app.claude_wake")
    scope = {"container_ref": PAYLOAD["container_ref"]}
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
    error_registry.attempt.side_effect = RuntimeError("worker failure")
    _join(schedule_claude_relay_wake(result, scope, registry=error_registry))

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "category=uncertain" in logged
    assert "category=deferred" in logged
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
    scope = {"container_ref": PAYLOAD["container_ref"]}
    thread_class = threading.Thread
    caplog.set_level(logging.INFO, logger="app.claude_wake")
    monkeypatch.setattr(wake.threading, "Thread", FailingThread)
    try:
        assert schedule_claude_relay_wake(_wake_result(PAYLOAD["session_ref"], "failed-start"), scope, registry=registry) is None
        wake.drain_claude_relay_wakes(registry)
    finally:
        monkeypatch.setattr(wake.threading, "Thread", thread_class)
    monkeypatch.setattr(wake, "claude_wake_transport", lambda *_: True)
    worker = schedule_claude_relay_wake(_wake_result(PAYLOAD["session_ref"], "retry"), scope, registry=registry)
    try:
        _join(worker)
        wake.drain_claude_relay_wakes(registry)
        wake.drain_claude_relay_wakes(registry)
    finally:
        if worker is not None:
            worker.join(timeout=1)
            assert not worker.is_alive()
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "category=worker_start_failed" in logged
    assert "category=accepted" in logged


def test_drain_is_idempotent_when_completed_trace_callback_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.claude_wake as wake

    registry = ClaudeWakeRegistry()
    registry.register(**{**PAYLOAD, "idle": True})
    completed = threading.Event()

    def trace(event: dict[str, object]) -> None:
        if event["stage"] == "completed":
            completed.set()
            raise RuntimeError("trace callback failed")

    monkeypatch.setattr(wake, "claude_wake_transport", lambda *_: "accepted")
    worker = schedule_claude_relay_wake(
        _wake_result(PAYLOAD["session_ref"]),
        {"container_ref": PAYLOAD["container_ref"]},
        registry=registry,
        trace_callback=trace,
    )
    try:
        assert completed.wait(timeout=1)
        _join(worker)
        wake.drain_claude_relay_wakes(registry)
        wake.drain_claude_relay_wakes(registry)
    finally:
        if worker is not None:
            worker.join(timeout=1)
            assert not worker.is_alive()


def test_public_turn_busy_stop_idle_lifecycle_is_fail_closed(client) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes import create_router
    from core.relay import RelayService

    registry = ClaudeWakeRegistry()
    relay = RelayService(client.app.state.pallium_service._storage)
    app = FastAPI()
    app.include_router(create_router(client.app.state.pallium_service, relay_service=relay, claude_wake_registry=registry,
        relay_turn_callback=lambda req, _result: registry.mark_busy(
            runtime=req["runtime"], session_ref=req["session_ref"],
            container_ref=req["container_ref"])))
    client = TestClient(app, client=("127.0.0.1", 50000))
    payload = {**PAYLOAD, "session_ref": "session-test", "socket_path": "/tmp/test.sock", "idle": True}
    scope = {"container_ref": payload["container_ref"]}
    relay.turn(runtime="claude-code", session_ref=payload["session_ref"], **scope)
    relay.close_session(runtime="claude-code", session_ref=payload["session_ref"], **scope)
    assert relay.list_sessions(runtime="claude-code", include_inactive=True, **scope)[0]["state"] == "closed"
    assert client.post("/internal/claude-wake/register", json=payload).status_code == 204
    assert relay.list_sessions(runtime="claude-code", include_inactive=True, **scope)[0]["destination_health"] == "active"
    assert client.post("/relay/turn", json={"runtime": "claude-code", "session_ref": payload["session_ref"], **scope}).status_code == 200
    result = {"recipient": "claude-code:session-test", "deliveries": [{"delivery_id": "d1",
                    "recipient_endpoint_id": "relay-session-" + "a" * 32,
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
    assert registry.attempt(runtime="claude-code", session_ref="session-test", container_ref="wrong", transport=transport).outcome == "deferred"


def test_windows_write_closes_event_after_cancelled_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.claude_wake_transport as transport

    pending: list[tuple[object, object]] = []
    monkeypatch.setattr(transport, "_pending_windows_writes", pending)
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
    assert waits == [False] and closed == ["event"] and pending == []


@pytest.mark.parametrize("use_cancel_io_ex", (True, False))
def test_windows_write_timeout_never_blocks_when_cancellation_stays_pending(use_cancel_io_ex: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.claude_wake_transport as transport

    pending: list[tuple[object, object]] = []
    monkeypatch.setattr(transport, "_pending_windows_writes", pending)
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
    assert len(pending) == 1 and pending[0][1] == "event"

def test_windows_write_reaps_signaled_timeout_state(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.claude_wake_transport as transport

    class Overlapped:
        hEvent = None

    class Incomplete(OSError):
        winerror = 996

    pending: list[tuple[object, object]] = []
    monkeypatch.setattr(transport, "_pending_windows_writes", pending)
    events = iter(["pending", "next"])
    closed = []

    def wait(event: str, timeout: int) -> int:
        return 0 if event == "pending" and timeout == 0 else 258

    def incomplete(_handle, _overlapped, wait_for_completion: bool) -> None:
        assert not wait_for_completion
        raise Incomplete()

    win32event = SimpleNamespace(WAIT_OBJECT_0=0, CreateEvent=lambda *_: next(events), WaitForSingleObject=wait)
    win32file = SimpleNamespace(WriteFile=lambda *_: (997, 0), CancelIoEx=lambda *_: None, GetOverlappedResult=incomplete, CloseHandle=lambda event: closed.append(event))
    assert not _windows_write("pipe", b"frame", SimpleNamespace(OVERLAPPED=Overlapped), win32event, win32file, SimpleNamespace(ERROR_IO_PENDING=997))
    win32file.WriteFile = lambda *_: (0, 0)
    assert _windows_write("pipe", b"frame", SimpleNamespace(OVERLAPPED=Overlapped), win32event, win32file, SimpleNamespace(ERROR_IO_PENDING=997))
    assert pending == [] and closed == ["pending", "next"]


def test_windows_write_retains_pending_overlapped_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.claude_wake_transport as transport

    class Overlapped:
        hEvent = None

    class Incomplete(OSError):
        winerror = 996

    pending: list[tuple[object, object]] = []
    monkeypatch.setattr(transport, "_pending_windows_writes", pending)
    barrier = threading.Barrier(3)
    events: list[object] = []
    event_lock = threading.Lock()

    def create_event(*_args: object) -> object:
        event = object()
        with event_lock:
            events.append(event)
        return event

    def write() -> None:
        barrier.wait()
        assert not _windows_write(
            "pipe", b"frame", SimpleNamespace(OVERLAPPED=Overlapped),
            SimpleNamespace(WAIT_OBJECT_0=0, CreateEvent=create_event, WaitForSingleObject=lambda *_: 258),
            SimpleNamespace(WriteFile=lambda *_: (997, 0), CancelIoEx=lambda *_: None, GetOverlappedResult=lambda *_: (_ for _ in ()).throw(Incomplete()), CloseHandle=lambda *_: None),
            SimpleNamespace(ERROR_IO_PENDING=997),
        )

    workers = [threading.Thread(target=write) for _ in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=1)
        assert not worker.is_alive()
    assert {event for _overlapped, event in pending} == set(events)

def test_persisted_claude_d1_d2_d3_actual_hooks(
    client, monkeypatch, tmp_path, capsys,
) -> None:
    from itertools import count
    import time

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.dependencies import build_router
    from storage import sqlite_queue
    from tests.test_claude_code_integration import _load_claude_hook

    registry = ClaudeWakeRegistry()
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
        claude_wake_registry=registry,
    ))
    http = TestClient(app, client=("127.0.0.1", 50000))
    scope = {"container_ref": PAYLOAD["container_ref"]}
    start = _load_claude_hook("session_start", monkeypatch)
    prompt = _load_claude_hook("user_prompt_submit", monkeypatch)
    stop = _load_claude_hook("stop", monkeypatch)
    hook_sessions = tmp_path / "hook-sessions"
    real_time = start.relay_turn.__globals__["time"]
    real_monotonic = real_time.monotonic
    for hook in (start, prompt, stop):
        common_globals = hook.relay_turn.__globals__
        monkeypatch.setitem(common_globals, "SESSIONS_DIR", hook_sessions)
        # Disk setup latency is not this delivery contract; native locks and hook budgets stay real.
        local_time = SimpleNamespace(**vars(common_globals["time"]))
        local_time.monotonic = count(step=.001).__next__
        monkeypatch.setitem(common_globals, "time", local_time)
    relay_calls, registration_statuses = [], []

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
            hook, "derive_actor_ref", lambda *_: "local", raising=False,
        )

    storage = client.app.state.pallium_service._storage
    native_queue_time, native_monotonic = sqlite_queue.time, time.monotonic

    def relay(method, path, body, timeout=0.75):
        if method == "POST" and path == "/relay/turn":
            original_turn = storage.relay_turn
            qualified = []

            def provider_turn(**kwargs):
                if qualified or any(kwargs.get(field) != body.get(field) for field in (
                    "runtime", "session_ref", "container_ref",
                )):
                    return original_turn(**kwargs)
                qualified.append(True)
                owner = threading.get_ident()
                ticks = count(step=.001).__next__
                turn_time = SimpleNamespace(**vars(native_queue_time))
                turn_time.monotonic = lambda: ticks() if threading.get_ident() == owner else native_monotonic()
                try:
                    with monkeypatch.context() as admission:
                        admission.setattr(sqlite_queue, "time", turn_time)
                        return original_turn(**kwargs)
                finally:
                    assert sqlite_queue.time is native_queue_time
                    assert time.monotonic is native_monotonic

            with monkeypatch.context() as provider:
                provider.setattr(storage, "relay_turn", provider_turn)
                response = http.request(method, path, json=body)
            assert qualified == [True]
        else:
            response = http.request(method, path, json=body)
        assert sqlite_queue.time is native_queue_time
        relay_calls.append((method, path, response.status_code))
        return response.json() if response.content else None
    def register(session, container, **kwargs):
        response = http.post("/internal/claude-wake/register", json={
            **PAYLOAD,
            "session_ref": session,
            "container_ref": container,
            "idle": kwargs.get("idle", False),
        })
        registration_statuses.append(response.status_code)
        return response.status_code == 204

    def acknowledge(deliveries, **kwargs):
        acknowledged = []
        ack_container = kwargs.get("container_ref", scope["container_ref"])
        for delivery in deliveries:
            response = http.post("/relay/deliveries/ack", json={
                "delivery_id": delivery["delivery_id"],
                "claim_token": delivery["claim_token"],
                "container_ref": ack_container,
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
    session_response = http.get("/relay/sessions", params=scope)
    assert session_response.status_code == 200
    sessions = session_response.json()
    state_path = hook_sessions / "session-test.json"
    retained_state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None
    diagnostics = {
        "relay_calls": relay_calls,
        "registration_statuses": registration_statuses, "retained_state": retained_state,
        "start_output": capsys.readouterr().out,
    }
    assert relay_calls == [("POST", "/relay/turn", 200)], diagnostics
    assert registration_statuses == [204], diagnostics
    admitted = [row for row in sessions if row["session_ref"] == "session-test"]
    assert len(admitted) == 1 and retained_state is not None, diagnostics
    assert retained_state["last_confirmed_endpoint_id"] == admitted[0]["endpoint_id"]
    assert retained_state["last_confirmed_container_ref"] == scope["container_ref"]
    assert retained_state["last_confirmed_scope_generation"] == admitted[0]["scope_generation"]
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

    def injected_scope(output):
        scope_line = next(
            line for line in output.splitlines()
            if line.startswith("[Pallium scope — ")
        )
        return json.loads(
            scope_line.removeprefix("[Pallium scope — ").removesuffix("]")
        )

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
    prompt_output = capsys.readouterr().out
    assert "D1" in prompt_output
    prompt_scope = injected_scope(prompt_output)
    assert prompt_scope == {
        **scope,
        "thread_ref": "session-test",
        "agent_ref": "claude-code",
        "visibility": "private",
        "actor_ref": "local",
    }
    assert http.post("/relay/replies", json={
        "delivery_id": sent1["deliveries"][0]["delivery_id"],
        "payload": "handled D1",
        "container_ref": prompt_scope["container_ref"],
    }).status_code == 200

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
    stop_output = capsys.readouterr().err
    assert "D2" in stop_output
    stop_scope = injected_scope(stop_output)
    assert stop_scope == prompt_scope
    assert http.post("/relay/replies", json={
        "delivery_id": sent2["deliveries"][0]["delivery_id"],
        "payload": "handled D2",
        "container_ref": stop_scope["container_ref"],
    }).status_code == 200
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

    transport_called = threading.Event()
    transport = MagicMock(side_effect=lambda *_args, **_kwargs: transport_called.set() or True)
    monkeypatch.setattr("app.claude_wake.claude_wake_transport", transport)
    sent3 = send("D3", message_id="stable-d3")
    assert state(sent3) == "pending"
    assert transport_called.wait(2)  # Sending schedules a worker; it does not join it.
    transport.assert_called_once()
    assert send("D3", message_id="stable-d3")["message_id"] == sent3["message_id"]
    transport.assert_called_once()

    monkeypatch.setattr(prompt, "resolve_container_ref", lambda *_: "git:other/repo")
    with pytest.raises(SystemExit):
        prompt.main()
    assert state(sent2) == "delivered"
    assert state(sent2) == state(sent3) == "delivered"

    monkeypatch.setattr(prompt, "resolve_container_ref", lambda *_: scope["container_ref"])
    with pytest.raises(SystemExit):
        prompt.main()
    output = capsys.readouterr().out
    assert "D2" not in output and "D3" in output
    assert state(sent2) == state(sent3) == "delivered"
    assert all(status == 200 for _, _, status in relay_calls), relay_calls
    assert all(status == 204 for status in registration_statuses), registration_statuses
    assert real_time.monotonic is real_monotonic
    assert all(
        hook.relay_turn.__globals__["hook_deadline"]().clock is real_monotonic
        for hook in (start, prompt, stop)
    )

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
    scope = {"container_ref": PAYLOAD["container_ref"]}

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
    from itertools import count
    import time as native_time
    from storage import sqlite_queue

    native_storage_time = sqlite_queue.time
    native_monotonic = native_time.monotonic
    # These establish the restart fixture; native admission deadlines have separate coverage.
    with monkeypatch.context() as registration:
        registration_time = SimpleNamespace(**vars(native_storage_time))
        registration_time.monotonic = count(step=0.001).__next__
        registration.setattr(sqlite_queue, "time", registration_time)
        assert before_restart.post("/internal/claude-wake/register", json={
            **PAYLOAD, "session_ref": "target", "idle": True,
        }).status_code == 204
        assert before_restart.post("/relay/turn", json={
            "runtime": "claude-code", "session_ref": "target", **scope,
        }).status_code == 200
    assert sqlite_queue.time is native_storage_time
    assert sqlite_queue.time.monotonic is native_monotonic
    assert native_time.monotonic is native_monotonic

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
    session_dir = tmp_path / "hook-sessions"
    session_dir.mkdir()
    (session_dir / "target.lock").write_bytes(b"0")
    assert not (session_dir / "target.json").exists()
    monkeypatch.setitem(prompt.relay_turn.__globals__, "SESSIONS_DIR", session_dir)
    monkeypatch.setattr(prompt, "resolve_container_ref", lambda *_: scope["container_ref"])
    monkeypatch.setattr(prompt, "derive_actor_ref", lambda *_: "local")
    monkeypatch.setattr(prompt, "check_dedup", lambda *_: False)
    monkeypatch.setattr(prompt, "pallium_request", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(prompt, "read_hook_input", lambda: {
        "session_id": "target", "cwd": str(tmp_path), "prompt": "recover relay",
    })

    def relay(method, path, body, timeout=0.75):
        response = http.request(method, path, json=body)
        return response.json() if response.content else None
    def register(session, container, **kwargs):
        response = http.post("/internal/claude-wake/register", json={
            **PAYLOAD, "session_ref": session, "container_ref": container, "idle": kwargs.get("idle", False),
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
    import app.claude_wake as wake
    from tests.test_claude_code_integration import _load_claude_hook

    registry = ClaudeWakeRegistry()
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
        claude_wake_registry=registry,
    ))
    http = TestClient(app, client=("127.0.0.1", 50000))
    scope = {"container_ref": PAYLOAD["container_ref"]}
    stop = _load_claude_hook("stop", monkeypatch)
    common = sys.modules["common"]
    assert stop.relay_turn.__globals__ is common.__dict__
    native_time = common.time
    native_monotonic = native_time.monotonic
    native_acquire = common._acquire_session_lock
    native_release = common._release_session_lock
    lock_events = []
    acquired_handles = []
    from itertools import count

    def scoped_acquire(session_id):
        if session_id != "empty-stop":
            return native_acquire(session_id)
        logical_time = SimpleNamespace(**vars(native_time))
        # Qualify functional rearm after real lock setup; native elapsed-budget behavior has separate coverage.
        logical_time.monotonic = count(step=.001).__next__
        common.time = logical_time
        try:
            handle = native_acquire(session_id)
            lock_events.append(("acquire", handle is not None))
            if handle is not None:
                acquired_handles.append(handle)
            return handle
        finally:
            common.time = native_time

    def observe_release(handle):
        result = native_release(handle)
        if acquired_handles and handle is acquired_handles[0]:
            lock_events.append(("release", True))
        return result

    monkeypatch.setattr(common, "_acquire_session_lock", scoped_acquire)
    monkeypatch.setattr(common, "_release_session_lock", observe_release)
    monkeypatch.setitem(stop.relay_turn.__globals__, "SESSIONS_DIR", tmp_path / "hook-sessions")
    monkeypatch.setattr(stop, "resolve_container_ref", lambda *_: scope["container_ref"])
    monkeypatch.setattr(stop, "derive_actor_ref", lambda *_: "local")
    registration_events = []
    turn_events = []

    def register(session, container, **kwargs):
        response = http.post("/internal/claude-wake/register", json={
            **PAYLOAD, "session_ref": session, "container_ref": container, "idle": kwargs.get("idle", False),
        })
        registration_events.append({"session": session, "idle": kwargs.get("idle", False), "status": response.status_code})
        turn_events.append("register")
        return response.status_code == 204

    def relay(method, path, body, *, timeout):
        response = http.request(method, path, json=body)
        if method == "POST" and path == "/relay/turn" and body.get("session_ref") == "empty-stop":
            payload = response.json() if response.content else {}
            session_payload = payload.get("session", {}) if isinstance(payload, dict) else {}
            turn_events.append("target_turn")
            turn_events.append({"status": response.status_code, "runtime": session_payload.get("runtime"),
                                "session_ref": session_payload.get("session_ref"), "container_ref": session_payload.get("container_ref"),
                                "endpoint_id": session_payload.get("endpoint_id"), "scope_generation": session_payload.get("scope_generation")})
        return response.json() if response.content else None

    monkeypatch.setattr(stop, "register_claude_wake", register)
    monkeypatch.setattr(stop, "relay_request", relay)
    monkeypatch.setattr(stop, "read_hook_input", lambda: {
        "session_id": "empty-stop", "cwd": str(tmp_path), "transcript_path": "",
    })
    try:
        try:
            stop.main()
        finally:
            common.time = native_time
            monkeypatch.setattr(common, "_acquire_session_lock", native_acquire)
            monkeypatch.setattr(common, "_release_session_lock", native_release)

        assert common.time is native_time
        assert common.time.monotonic is native_monotonic
        assert common._acquire_session_lock is native_acquire
        assert common._release_session_lock is native_release
        assert lock_events == [("acquire", True), ("release", True)], "empty-stop native lock acquisition must succeed"
        assert any(isinstance(event, dict) for event in turn_events), "target canonical turn admission witness must exist"
        assert [event for event in turn_events if isinstance(event, str)] == ["register", "target_turn", "register"]
        target_turn = next(event for event in turn_events if isinstance(event, dict))
        assert target_turn["status"] == 200 and target_turn["runtime"] == "claude-code"
        assert target_turn["session_ref"] == "empty-stop" and target_turn["container_ref"] == scope["container_ref"]
        assert isinstance(target_turn["endpoint_id"], str) and target_turn["endpoint_id"].startswith("relay-session-")
        assert type(target_turn["scope_generation"]) is int and target_turn["scope_generation"] >= 0
        assert len(registration_events) == 2
        assert registration_events[0]["session"] == registration_events[1]["session"] == "empty-stop"
        assert registration_events[0]["idle"] is True and registration_events[1]["idle"] is True
        assert registration_events[1]["status"] == 204, "post-turn idle rearm registration must be accepted"
        assert registration_events[0]["status"] == 204
        assert registry.state_for(recipient_endpoint_id=target_turn["endpoint_id"], session_ref="empty-stop",
                                  container_ref=scope["container_ref"]) == "idle"
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
    finally:
        try:
            wake.stop_claude_relay_wake_admission(registry)
        finally:
            try:
                wake.drain_claude_relay_wakes(registry)
            finally:
                http.close()


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

    scope = {"container_ref": PAYLOAD["container_ref"]}
    transport_called = threading.Event()
    http_opened = threading.Event()
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
        def lose_http_response(*_args, **_kwargs):
            http_opened.set()
            raise OSError()

        monkeypatch.setattr(
            common.urllib.request,
            "build_opener",
            lambda *_: SimpleNamespace(open=lose_http_response),
        )
        accepted = common.register_claude_wake("lost-http", scope["container_ref"], idle=True)
        assert not accepted
        assert http_opened.is_set(), "registration false must follow the intended HTTP opener failure"

        sent = http.post("/relay/messages", json={
            "sender_runtime": "codex", "sender_session_ref": "sender",
            "recipient": "claude-code:lost-http", "payload": "recover me", **scope,
        })
        assert sent.status_code == 200
        message_id = sent.json()["message_id"]
        # Functional allowance for the one-second poll plus actual admission and dispatch work; this is not an SLA.
        assert transport_called.wait(timeout=5), "natural intent reconciliation must reach transport within the harness allowance"
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


@pytest.mark.parametrize("old_state,new_state", [
    ("busy", "idle"), ("idle", "busy"), ("idle", "closed"), ("closed", "idle"),
])
@pytest.mark.parametrize("lost_http", [False, True], ids=["http", "recovery"])
def test_create_app_preserves_new_intent_during_old_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    old_state: str, new_state: str, lost_http: bool, *, before_cleanup=None,
) -> None:
    from itertools import count
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import ExitStack, nullcontext

    from fastapi.testclient import TestClient

    import app.claude_wake as wake
    import core.claude_wake as wake_registry_module
    from app.config import AppConfig
    from app.main import create_app
    import storage.sqlite_queue as sqlite_queue
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES
    from tests.test_claude_code_integration import _load_claude_hook
    import sys
    import time

    wake_dir = tmp_path / "wake"
    monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(wake_dir))
    recovery_ready = threading.Event()
    recovered = threading.Event()
    recovery_entered = threading.Event()
    original_recover = wake.recover_claude_relay_wakes
    original_stop = wake.ClaudeWakeReconciler.stop

    def stop_reconciler(reconciler):
        recovery_ready.set()
        return original_stop(reconciler)

    monkeypatch.setattr(wake.ClaudeWakeReconciler, "stop", stop_reconciler)

    def controlled_recover(*args, **kwargs):
        recovery_entered.set()
        recovery_ready.wait()
        original_recover(*args, **kwargs)
        recovered.set()

    monkeypatch.setattr(wake, "recover_claude_relay_wakes", controlled_recover)
    calls: list[tuple[str, str]] = []
    wake_called = threading.Event()
    monkeypatch.setattr(
        "app.claude_wake.claude_wake_transport",
        lambda path, token: calls.append((path, token)) or wake_called.set() or True,
    )
    app = create_app(AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{tmp_path / 'relay.db'}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    ))
    scope = {"container_ref": PAYLOAD["container_ref"]}

    with TestClient(app, client=("127.0.0.1", 50000)) as http, ExitStack() as release_gates:
        release_gates.callback(recovery_ready.set)
        assert recovery_entered.wait(timeout=5)
        common = _load_claude_hook("common", monkeypatch)
        real_time = wake_registry_module.time
        native_monotonic = real_time.monotonic
        registry_time = SimpleNamespace(**vars(real_time))
        registry_time.monotonic = count(step=.001).__next__
        monkeypatch.setattr(wake_registry_module, "time", registry_time)
        hook_time = SimpleNamespace(**vars(common.time))
        hook_time.monotonic = count(step=.001).__next__
        monkeypatch.setattr(common, "time", hook_time)
        common.CLAUDE_WAKE_DIR = wake_dir
        common.CLAUDE_WAKE_INTENTS_DIR = wake_dir / "intents"
        stages: list[dict[str, object]] = []

        def capture(stage, delegate, metadata, *args, **kwargs):
            row = {"stage": stage, "thread": threading.get_ident(),
                   "entered": time.perf_counter(), **metadata}
            stages.append(row)
            try:
                result = delegate(*args, **kwargs)
                row["return_type"] = type(result).__name__
                if isinstance(result, bool):
                    row["returned"] = result
                elif stage == "intent_lock":
                    row["acquired"] = result is not None
                return result
            except BaseException as exc:
                row.update(error_type=type(exc).__name__, errno=getattr(exc, "errno", None),
                           winerror=getattr(exc, "winerror", None))
                raise
            finally:
                row["finished"] = time.perf_counter()

        original_acquire = common._acquire_file_lock
        original_publish = common._write_wake_intent
        original_intent_path = common._wake_intent_path
        original_replace = common.os.replace

        class IntentPath(type(tmp_path)):
            def write_text(self, *args, **kwargs):
                return capture("temporary_write", super().write_text,
                               {"path_length": len(str(self))}, *args, **kwargs)

        def publish(payload):
            try:
                return capture("publication", original_publish, {}, payload)
            finally:
                metadata = json.dumps({"stages": stages[:128], "truncated": max(0, len(stages) - 128)})
                (tmp_path / "old-cleanup-publication.json").write_text(metadata, encoding="utf-8")
                print("old cleanup publication: " + metadata, file=sys.stderr)

        monkeypatch.setattr(common, "_acquire_file_lock", lambda path, budget:
                            capture("intent_lock", original_acquire, {"budget": budget}, path, budget))
        monkeypatch.setattr(common, "_wake_intent_path", lambda *args: IntentPath(original_intent_path(*args)))
        monkeypatch.setattr(common, "os", SimpleNamespace(**vars(common.os)))
        monkeypatch.setattr(common.os, "replace", lambda source, destination:
                            capture("atomic_replace", original_replace,
                                    {"source_length": len(str(source)), "destination_length": len(str(destination))},
                                    source, destination))
        monkeypatch.setattr(common, "_write_wake_intent", publish)

        session = "overlap-\u2713"

        def turn(session: str) -> None:
            assert http.post("/relay/turn", json={
                "runtime": "claude-code", "session_ref": session, **scope,
            }).status_code == 200

        def intent(state: str, intent_id: str) -> dict[str, object]:
            payload = {
                **PAYLOAD, "session_ref": session, "idle": state == "idle",
                "intent_id": intent_id,
            }
            if state == "closed":
                payload = {key: payload[key] for key in (
                    "runtime", "session_ref", "container_ref", "intent_id",
                )}
                payload["closed"] = True
            return payload

        def apply(payload: dict[str, object]):
            if payload.get("intent_id") == "old" and before_cleanup is not None:
                before_cleanup()
            path = "/internal/claude-wake/register"
            if payload.get("closed"):
                path = "/internal/claude-wake/close"
                payload = {key: payload[key] for key in (
                    "runtime", "session_ref", "container_ref", "intent_id",
                )}
            return http.post(path, json=payload)

        assert http.post("/relay/turn", json={
            "runtime": "codex", "session_ref": "sender", **scope,
        }).status_code == 200

        turn(session)
        bootstrap = intent("busy", "bootstrap")
        assert common._write_wake_intent(bootstrap)
        assert apply(bootstrap).status_code == 204
        old = intent(old_state, "old")
        assert common._write_wake_intent(old)
        target = common._wake_intent_path("claude-code", session, scope["container_ref"])
        cleanup_held = threading.Event()
        native_contention = threading.Event()
        published = threading.Event()
        send_http = threading.Event()
        publisher_thread: list[int] = []
        original_unlink = Path.unlink

        def paused_unlink(path, *args, **kwargs):
            if path == target and not cleanup_held.is_set():
                assert json.loads(path.read_text(encoding="utf-8"))["intent_id"] == "old"
                cleanup_held.set()
                # The publisher releases this barrier only after a real native failure.
                assert native_contention.wait(timeout=1)
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", paused_unlink)
        if os.name == "nt":
            import msvcrt as native
            lock_name, nonblocking = "locking", native.LK_NBLCK
        else:
            import fcntl as native
            lock_name, nonblocking = "flock", native.LOCK_EX | native.LOCK_NB
        original_native_lock = getattr(native, lock_name)

        def witnessed_lock(fd, operation, *args):
            try:
                return original_native_lock(fd, operation, *args)
            except OSError:
                if operation == nonblocking and publisher_thread == [threading.get_ident()]:
                    native_contention.set()
                raise

        monkeypatch.setattr(native, lock_name, witnessed_lock)
        monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", PAYLOAD["socket_path"])
        monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", PAYLOAD["token"])

        def open_request(request, **kwargs):
            published.set()
            assert send_http.wait(timeout=3)
            if lost_http:
                raise OSError("loopback request unavailable after durable publication")
            response = http.post(
                common.urllib.parse.urlparse(request.full_url).path,
                json=json.loads(request.data),
            )
            assert response.status_code == 204, response.text
            return nullcontext(response)

        monkeypatch.setattr(common.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=open_request))

        def publish_new():
            publisher_thread.append(threading.get_ident())
            if new_state == "closed":
                return common.close_claude_wake(session, scope["container_ref"])
            return common.register_claude_wake(session, scope["container_ref"], idle=new_state == "idle")

        try:
            with ThreadPoolExecutor(max_workers=2) as workers:
                try:
                    cleanup = workers.submit(apply, old)
                    # Arrival precedes the competing publisher; contention stays native.
                    assert cleanup_held.wait(timeout=5)
                    publication = workers.submit(publish_new)
                    # Arrival is fixture orchestration; native lock budgets stay unchanged.
                    assert published.wait(timeout=5)
                    assert native_contention.is_set()
                    assert cleanup.result(timeout=1).status_code == 204
                    newer = json.loads(target.read_text(encoding="utf-8"))
                    assert newer["intent_id"] != "old"
                    assert newer.get("closed", False) == (new_state == "closed")
                    if new_state != "closed":
                        assert newer["idle"] == (new_state == "idle")
                    send_http.set()
                    assert publication.result(timeout=1) is (not lost_http)
                finally:
                    native_contention.set()
                    send_http.set()
            recovery_ready.set()
            assert recovered.wait(timeout=1)
            assert not target.exists()
        finally:
            send_http.set()
            recovery_ready.set()

        from contextlib import contextmanager
        from sqlalchemy import select
        from core.errors import ImmediateTransactionBusyError
        from storage.sqlite_schema import RelayMessageRecord, RelayDeliveryRecord

        storage = app.state.pallium_service._storage
        begin = storage._begin_relay_immediate
        send = storage.relay_send
        local = threading.local()
        attempts = []

        def observe_send(*args, **kwargs):
            local.active = True
            try:
                return send(*args, **kwargs)
            finally:
                local.active = False

        @contextmanager
        def observe_begin():
            if not getattr(local, "active", False):
                with begin() as db:
                    yield db
                return
            attempt = {"acquired": False}
            attempts.append(attempt)
            try:
                with begin() as db:
                    attempt["acquired"] = True
                    yield db
            except BaseException as error:
                attempt["error"] = error
                raise

        body = {
            "sender_runtime": "codex", "sender_session_ref": "sender",
            "recipient": "claude-code:" + session, "payload": "preserved transition \u2713", **scope,
        }
        calls_before = list(calls)
        with storage._relay_engine.connect() as db:
            assert db.execute(select(RelayMessageRecord.id)).all() == []
            assert db.execute(select(RelayDeliveryRecord.id)).all() == []
        with monkeypatch.context() as admission:
            admission.setattr(storage, "relay_send", observe_send)
            admission.setattr(storage, "_begin_relay_immediate", observe_begin)
            deadline = time.monotonic() + 5
            sent = http.post("/relay/messages", json=body)
            if sent.status_code == 503:
                assert len(attempts) == 1 and attempts[0]["acquired"] is False
                assert type(attempts[0].get("error")) is ImmediateTransactionBusyError
                assert sent.json() == {"detail": {"code": "relay_busy", "retryable": True}}
                with storage._relay_engine.connect() as db:
                    assert db.execute(select(RelayMessageRecord.id)).all() == []
                    assert db.execute(select(RelayDeliveryRecord.id)).all() == []
                assert calls == calls_before
                delay = sent.headers.get("Retry-After", "")
                assert delay.isascii() and delay.isdecimal()
                assert 0 < int(delay) < deadline - time.monotonic()
                time.sleep(int(delay))
                assert time.monotonic() < deadline
                sent = http.post("/relay/messages", json=body)
            assert len(attempts) in (1, 2)
            assert attempts[-1]["acquired"] is True and "error" not in attempts[-1]
        assert sent.status_code == 200
        if new_state == "idle":
            assert wake_called.wait(timeout=1)
        recovered.clear()
        app.state._claude_wake_reconciler.signal()
        assert recovered.wait(timeout=1)
        assert calls == ([(PAYLOAD["socket_path"], PAYLOAD["token"])] if new_state == "idle" else [])
        status = http.get(f"/relay/messages/{sent.json()['message_id']}", params=scope)
        assert status.status_code == 200
        delivery = status.json()["deliveries"][0]
        assert delivery["state"] == "pending"
        assert delivery["claim_token"] is None and delivery["receipt"] is None
        assert delivery["attempts"] == 0
        assert real_time.monotonic is native_monotonic
        assert time.monotonic is native_monotonic
        assert registry_time.sleep is real_time.sleep
        assert hook_time.sleep is real_time.sleep
        assert app.state.claude_wake_registry._clock is native_monotonic
        assert app.state._claude_wake_reconciler._clock is native_monotonic
        assert common.HookDeadline(0).clock is native_monotonic
        assert sqlite_queue.time.monotonic is native_monotonic

def test_expired_claim_rewakes_once_after_real_app_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    *, force_first_registration_refusal=False,
) -> None:
    from itertools import count

    from fastapi.testclient import TestClient

    import app.main as main
    import storage.sqlite_relay as sqlite_relay
    import core.claude_wake as wake_registry_module
    from app.config import AppConfig
    from app.main import create_app
    from core.relay import RelayService
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES
    from tests.test_claude_code_integration import _load_claude_hook

    real_time = wake_registry_module.time
    real_monotonic = real_time.monotonic
    # Lock admission is not this restart contract; retain native locks and real recovery clocks.
    registry_time = SimpleNamespace(**vars(real_time))
    registry_time.monotonic = count(step=.001).__next__
    monkeypatch.setattr(wake_registry_module, "time", registry_time)
    clock = [datetime(2030, 9, 5, tzinfo=timezone.utc)]

    def controlled_now(value=None):
        current = value or clock[0]
        return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)

    monkeypatch.setattr(sqlite_relay, "_now", controlled_now)
    scope = {"container_ref": PAYLOAD["container_ref"]}
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
    monkeypatch.setattr(main, "start_claude_wake_reconciler", lambda *_args, **_kwargs: None)
    with TestClient(create_app(config), client=("127.0.0.1", 50000)) as http_a:
        common = _load_claude_hook("common", monkeypatch)
        hook_time = SimpleNamespace(**vars(common.time))
        hook_time.monotonic = count(step=.001).__next__
        monkeypatch.setattr(common, "time", hook_time)
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
        claimed = relay.turn(
            runtime="claude-code", session_ref="restart-target", **scope,
        )["deliveries"][0]
        delivery = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
        assert claimed["delivery_id"] == delivery["delivery_id"]
        assert delivery["state"] == "claimed" and delivery["attempts"] == 1

    clock[0] += timedelta(seconds=61)
    initial_recovery = threading.Event()

    def start_with_recovery_readiness(*args, claim_recovery, **kwargs):
        def observed_recovery():
            try:
                return claim_recovery()
            finally:
                initial_recovery.set()

        return original_start(*args, claim_recovery=observed_recovery, **kwargs)

    monkeypatch.setattr(main, "start_claude_wake_reconciler", start_with_recovery_readiness)
    app_b = create_app(config)
    with TestClient(app_b, client=("127.0.0.1", 50000)) as http_b:
        assert initial_recovery.wait(timeout=5), "initial appB claim recovery did not complete"
        assert transport_called.wait(timeout=1)
        assert transport_calls == [(PAYLOAD["socket_path"], PAYLOAD["token"])]
        response = http_b.get(f"/relay/messages/{sent['message_id']}", params=scope)
        assert response.status_code == 200
        delivery = response.json()["deliveries"][0]
        assert delivery["state"] == "claimed"
        assert delivery["claim_token"] is not None and delivery["attempts"] == 1
        reconciler = app_b.state._claude_wake_reconciler
        assert reconciler is not None
        registry = app_b.state.claude_wake_registry
        registry.set_reconcile_signal(None)
        stop = _load_claude_hook("stop", monkeypatch)
        monkeypatch.setitem(stop.relay_turn.__globals__, "SESSIONS_DIR", tmp_path / "hook-sessions")
        monkeypatch.setattr(stop, "resolve_container_ref", lambda *_: scope["container_ref"])
        monkeypatch.setattr(stop, "derive_actor_ref", lambda *_: "local")
        monkeypatch.setattr(stop, "read_hook_input", lambda: {
            "session_id": "restart-target", "cwd": str(tmp_path), "transcript_path": "",
        })
        registrations: list[dict[str, object]] = []
        publication_results: list[tuple[str, bool]] = []
        registration_responses: list[tuple[str, int]] = []
        registration_failures: list[tuple[str, object, str | None]] = []
        forced_refusals = []
        claimed_ids: list[list[str]] = []
        states_before_ack: list[str] = []
        acknowledged_ids: list[str] = []

        def register(session: object, container: object, *, idle: bool = False) -> bool:
            registration = {
                **PAYLOAD, "session_ref": session, "container_ref": container,
 "idle": idle, "intent_id": f"stop-{len(registrations)}",
            }
            registrations.append(registration)
            published = common._write_wake_intent(registration)
            publication_results.append((registration["intent_id"], published))
            assert published
            storage = app_b.state.pallium_service._storage
            native_mark_active = storage.relay_mark_active
            with monkeypatch.context() as refusal:
                if force_first_registration_refusal and registration["intent_id"] == "stop-0":
                    from core.errors import ImmediateTransactionBusyError

                    def refused_mark_active(**kwargs):
                        assert kwargs["runtime"] == "claude-code"
                        assert kwargs["session_ref"] == "restart-target"
                        assert kwargs["container_ref"] == scope["container_ref"]
                        forced_refusals.append(registration["intent_id"])
                        raise ImmediateTransactionBusyError(
                            "controlled mark-active acquisition refusal", acquisition_stage="setup_deadline",
                        )

                    refusal.setattr(storage, "relay_mark_active", refused_mark_active)
                response = http_b.post("/internal/claude-wake/register", json=registration)
            assert storage.relay_mark_active == native_mark_active
            registration_responses.append((registration["intent_id"], response.status_code))
            if response.status_code != 204:
                registration_failures.append((
                    registration["intent_id"], response.json(), response.headers.get("Retry-After"),
                ))
            return response.status_code == 204

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
        assert delivered["state"] == "delivered" and delivered["attempts"] == 2

        stop.main()
        assert capsys.readouterr().err == ""
        assert claimed_ids == [[delivery["delivery_id"]], []]
        assert acknowledged_ids == [delivery["delivery_id"]]
        candidates = registry.recovery_candidates()
        diagnostics = {
            "publication_results": publication_results,
            "registration_responses": registration_responses,
            "registration_failures": registration_failures,
        }
        assert publication_results == [(f"stop-{index}", True) for index in range(3)], diagnostics
        assert registration_responses[1:] == [(f"stop-{index}", 204) for index in (1, 2)], diagnostics
        if registration_responses[0] == ("stop-0", 503):
            assert registration_failures == [(
                "stop-0", {"detail": {"code": "relay_busy", "retryable": True}}, "1",
            )], diagnostics
        else:
            assert registration_responses[0] == ("stop-0", 204), diagnostics
            assert registration_failures == [], diagnostics
        assert [candidate["session_ref"] for candidate in candidates] == ["restart-target"], diagnostics
        assert transport_calls == [(PAYLOAD["socket_path"], PAYLOAD["token"])], diagnostics
        assert all(registration["idle"] is True for registration in registrations)
        assert forced_refusals == (["stop-0"] if force_first_registration_refusal else [])
        assert registry._clock is real_monotonic and reconciler._clock is real_monotonic
        assert real_time.monotonic is real_monotonic
    assert reconciler._thread is not None and not reconciler._thread.is_alive()


def test_unreachable_callback_is_aware_and_exception_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.claude_wake as wake

    registry = ClaudeWakeRegistry()
    registry.register(**{**PAYLOAD, "idle": True})
    observed: list[datetime] = []
    monkeypatch.setattr(wake, "claude_wake_transport", lambda *_: "unreachable")

    def callback(attempt_started_at: datetime) -> None:
        observed.append(attempt_started_at)
        raise RuntimeError("callback failure")

    _join(schedule_claude_relay_wake(
        _wake_result(PAYLOAD["session_ref"]),
        {"container_ref": PAYLOAD["container_ref"]},
        registry=registry, on_unreachable=callback,
    ))
    assert len(observed) == 1 and observed[0].tzinfo is not None
    assert registry._registrations[(PAYLOAD["runtime"], PAYLOAD["session_ref"], PAYLOAD["container_ref"])].state == "unreachable"
    assert registry.recovery_candidates() == []

    retried: list[datetime] = []
    _join(schedule_claude_relay_wake(
        _wake_result(PAYLOAD["session_ref"], "delivery-2"),
        {"container_ref": PAYLOAD["container_ref"]},
        registry=registry, on_unreachable=retried.append,
    ))
    assert retried == []
    assert registry._registrations[(PAYLOAD["runtime"], PAYLOAD["session_ref"], PAYLOAD["container_ref"])].state == "unreachable"



def test_real_router_unreachable_feedback_and_registration_self_heal(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.dependencies import build_router
    from core.relay import RelayService

    registry = ClaudeWakeRegistry()
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
        claude_wake_registry=registry,
    ))
    http = TestClient(app, client=("127.0.0.1", 50000))
    scope = {"container_ref": PAYLOAD["container_ref"]}
    for runtime, session_ref in (("claude-code", "health-target"), ("codex", "sender")):
        assert http.post("/relay/turn", json={
            "runtime": runtime, "session_ref": session_ref, **scope,
        }).status_code == 200

    registration = {**PAYLOAD, "session_ref": "health-target", "idle": True}
    assert http.post("/internal/claude-wake/register", json=registration).status_code == 204

    probe_finished = threading.Event()
    original_probe = registry.attempt

    def probe_and_signal(**kwargs: object) -> ActivationAttemptResult:
        result = original_probe(**kwargs)
        probe_finished.set()
        return result

    monkeypatch.setattr(registry, "attempt", probe_and_signal)
    monkeypatch.setattr("app.claude_wake.claude_wake_transport", lambda *_: ActivationAttemptResult("deferred", "pre_frame", native_retry_safe=True))
    retryable = http.post("/relay/messages", json={
        "sender_runtime": "codex",
        "sender_session_ref": "sender",
        "recipient": "claude-code:health-target",
        "payload": "retryable feedback",
        **scope,
    })
    assert retryable.status_code == 200
    assert probe_finished.wait(timeout=1)
    retryable_status = http.get(
        f"/relay/messages/{retryable.json()['message_id']}", params=scope
    ).json()
    assert retryable_status["deliveries"][0]["destination_health"] == "active"
    assert registry._registrations[("claude-code", "health-target", scope["container_ref"])].state == "idle"
    monkeypatch.setattr(registry, "attempt", original_probe)

    persisted = threading.Event()
    original_mark = RelayService.mark_unreachable

    def mark_and_signal(service: RelayService, **kwargs: object) -> bool:
        changed = original_mark(service, **kwargs)
        persisted.set()
        return changed

    monkeypatch.setattr(RelayService, "mark_unreachable", mark_and_signal)
    monkeypatch.setattr("app.claude_wake.claude_wake_transport", lambda *_: "unreachable")
    sent = http.post("/relay/messages", json={
        "sender_runtime": "codex",
        "sender_session_ref": "sender",
        "recipient": "claude-code:health-target",
        "payload": "health feedback",
        **scope,
    })
    assert sent.status_code == 200
    assert persisted.wait(timeout=1)
    status = http.get(f"/relay/messages/{sent.json()['message_id']}", params=scope).json()
    assert status["deliveries"][0]["state"] == "pending"
    assert status["deliveries"][0]["destination_health"] == "unreachable"
    assert registry._registrations[("claude-code", "health-target", scope["container_ref"])].state == "unreachable"

    assert http.post("/internal/claude-wake/register", json=registration).status_code == 204
    sessions = http.get(
        "/relay/sessions", params={**scope, "include_inactive": True}
    ).json()
    target = next(row for row in sessions if row["session_ref"] == "health-target")
    assert target["destination_health"] == "active"
    assert registry._registrations[("claude-code", "health-target", scope["container_ref"])].state == "idle"

def test_rw007_stop_batches_recursive_stop_and_deterministic_recovery(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.claude_wake import recover_claude_relay_wakes
    from app.dependencies import build_router
    from core.relay import RelayService
    from tests.test_claude_code_integration import _load_claude_hook

    scope = {
        "container_ref": PAYLOAD["container_ref"],
    }
    registry = ClaudeWakeRegistry()
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
        claude_wake_registry=registry,
    ))
    http = TestClient(app, client=("127.0.0.1", 50000))
    relay = RelayService(client.app.state.pallium_service._storage)
    stop = _load_claude_hook("stop", monkeypatch)
    monkeypatch.setitem(stop.relay_turn.__globals__, "SESSIONS_DIR", tmp_path / "hook-sessions")
    def register(session, container, **kwargs):
        response = http.post("/internal/claude-wake/register", json={
            **PAYLOAD,
            "session_ref": session,
            "container_ref": container,
            "idle": kwargs.get("idle", False),
        })
        return response.status_code == 204

    def request(method, path, body, **_kwargs):
        response = http.request(method, path, json=body)
        assert response.status_code == 200, response.text
        return response.json() if response.content else None

    def acknowledge(deliveries, **_kwargs):
        import time
        from contextlib import contextmanager
        from sqlalchemy import select
        from core.errors import ImmediateTransactionBusyError
        from storage.sqlite_schema import RelayDeliveryRecord

        storage = client.app.state.pallium_service._storage
        begin, ack = storage._begin_relay_immediate, storage.relay_ack
        local = threading.local()
        attempts = []

        def observe_ack(*args, **kwargs):
            local.active = True
            try:
                return ack(*args, **kwargs)
            finally:
                local.active = False

        @contextmanager
        def observe_begin():
            if not getattr(local, "active", False):
                with begin() as db:
                    yield db
                return
            attempt = {"acquired": False}
            attempts.append(attempt)
            try:
                with begin() as db:
                    attempt["acquired"] = True
                    yield db
            except BaseException as error:
                attempt["error"] = error
                raise

        def authority():
            columns = [column for column in RelayDeliveryRecord.__table__.columns
                       if column.name not in {"trace_version", "trace_truncated", "trace_pruned"}]
            with storage._relay_engine.connect() as db:
                return db.execute(select(*columns).order_by(RelayDeliveryRecord.id)).all()

        for item in deliveries:
            attempts.clear()
            body = {
                "delivery_id": item["delivery_id"],
                "claim_token": item["claim_token"],
                **scope,
            }
            before = authority()
            with monkeypatch.context() as admission:
                admission.setattr(storage, "relay_ack", observe_ack)
                admission.setattr(storage, "_begin_relay_immediate", observe_begin)
                deadline = time.monotonic() + 5
                response = http.post("/relay/deliveries/ack", json=body)
                if response.status_code == 503:
                    assert len(attempts) == 1 and attempts[0]["acquired"] is False
                    assert type(attempts[0].get("error")) is ImmediateTransactionBusyError
                    assert response.json() == {"detail": {"code": "relay_busy", "retryable": True}}
                    assert authority() == before
                    current = next(row for row in before if row.id == item["delivery_id"])
                    assert (current.state, current.claim_token, current.attempts) == ("claimed", item["claim_token"], 1)
                    lease = current.lease_expires_at
                    assert lease is not None
                    delay = response.headers.get("Retry-After", "")
                    assert delay.isascii() and delay.isdecimal()
                    assert 0 < int(delay) < deadline - time.monotonic()
                    time.sleep(int(delay))
                    assert time.monotonic() < deadline
                    assert authority() == before
                    assert lease.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
                    response = http.post("/relay/deliveries/ack", json=body)
                assert len(attempts) in (1, 2)
                assert attempts[-1]["acquired"] is True and "error" not in attempts[-1]
            assert response.status_code == 200
        return deliveries

    monkeypatch.setattr(stop, "resolve_container_ref", lambda *_: scope["container_ref"])
    monkeypatch.setattr(stop, "derive_actor_ref", lambda *_: "local")
    monkeypatch.setattr(stop, "register_claude_wake", register)
    monkeypatch.setattr(stop, "relay_request", request)
    monkeypatch.setattr(stop, "acknowledge_relay", acknowledge)
    normal = {
        "session_id": "rw007",
        "cwd": str(tmp_path),
        "transcript_path": "",
    }
    monkeypatch.setattr(stop, "read_hook_input", lambda: normal)

    relay.turn(runtime="codex", session_ref="sender", **scope)
    relay.turn(runtime="claude-code", session_ref="rw007", **scope)
    sent = [
        relay.send(
            sender_runtime="codex",
            sender_session_ref="sender",
            recipient="claude-code:rw007",
            payload=payload,
            **scope,
        )
        for payload in ("one", "two", "three", "four")
    ]

    with pytest.raises(SystemExit) as first:
        stop.main()
    assert first.value.code == 2
    first_output = capsys.readouterr().err
    first_relay, first_scope = first_output.rstrip().rsplit("\n\n", 1)
    assert all(word in first_relay for word in ("one", "two", "three"))
    assert "four" not in first_relay
    assert first_relay.endswith("[Relay: 1 more; Pallium continues.]")
    assert first_scope.startswith("[Pallium scope — ")
    assert [
        http.get(f"/relay/messages/{item['message_id']}", params=scope)
        .json()["deliveries"][0]["state"]
        for item in sent
    ] == ["delivered", "delivered", "delivered", "pending"]

    recursive = {**normal, "stop_hook_active": True}
    monkeypatch.setattr(stop, "read_hook_input", lambda: recursive)
    stop.main()
    assert capsys.readouterr().err == ""
    assert http.get(
        f"/relay/messages/{sent[3]['message_id']}", params=scope
    ).json()["deliveries"][0]["state"] == "pending"

    sent.append(relay.send(
        sender_runtime="codex",
        sender_session_ref="sender",
        recipient="claude-code:rw007",
        payload="five",
        **scope,
    ))
    transport_called = threading.Event()
    transport_calls: list[tuple[str, str]] = []

    def transport(socket: str, token: str) -> str:
        transport_calls.append((socket, token))
        transport_called.set()
        return "accepted"

    monkeypatch.setattr("app.claude_wake.claude_wake_transport", transport)
    recover_claude_relay_wakes(registry, relay)
    assert transport_called.wait(timeout=1)
    assert len(transport_calls) == 1

    monkeypatch.setattr(stop, "read_hook_input", lambda: normal)
    with pytest.raises(SystemExit) as final:
        stop.main()
    assert final.value.code == 2
    final_output = capsys.readouterr().err
    assert "four" in final_output and "five" in final_output
    assert "[Relay:" not in final_output

    monkeypatch.setattr(stop, "read_hook_input", lambda: recursive)
    stop.main()
    transport_calls.clear()
    recover_claude_relay_wakes(registry, relay)
    assert transport_calls == []
    assert [
        http.get(f"/relay/messages/{item['message_id']}", params=scope)
        .json()["deliveries"][0]["state"]
        for item in sent
    ] == ["delivered"] * 5
    combined = first_output + final_output
    assert all(combined.count(payload) == 1 for payload in ("one", "two", "three", "four", "five"))
    registration = registry._registrations[("claude-code", "rw007", scope["container_ref"])]
    assert registration.state == "idle" and registration.delivery_id is None


@pytest.mark.parametrize("force_claim_refusals", [False, True])
@pytest.mark.parametrize("with_prompt_id", [False, True])
def test_crash_after_claim_idle_stop_rewakes_actual_claude_hook_once(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys, force_claim_refusals, with_prompt_id,
) -> None:
    import time
    from core.errors import ImmediateTransactionBusyError
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import storage.sqlite_relay as sqlite_relay
    from app.dependencies import build_router, recover_expired_relay_wakes
    from core.relay import RelayService
    from tests.test_claude_code_integration import _load_claude_hook

    clock = [datetime(2030, 9, 5, tzinfo=timezone.utc)]

    def controlled_now(value=None):
        current = value or clock[0]
        return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)

    monkeypatch.setattr(sqlite_relay, "_now", controlled_now)
    scope = {"container_ref": PAYLOAD["container_ref"]}
    registry = ClaudeWakeRegistry()
    assert registry.register(**PAYLOAD, idle=False)
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
        claude_wake_registry=registry,
    ))
    http = TestClient(app, client=("127.0.0.1", 50000))
    relay = RelayService(client.app.state.pallium_service._storage)
    relay.turn(runtime="codex", session_ref="sender", **scope)
    relay.turn(runtime="claude-code", session_ref=PAYLOAD["session_ref"], **scope)
    sent = relay.send(
        sender_runtime="codex",
        sender_session_ref="sender",
        recipient="claude-code:" + PAYLOAD["session_ref"],
        payload="wake after crash ✓",
        **scope,
    )
    claimed = relay.turn(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"], **scope
    )["deliveries"][0]
    assert claimed["delivery_id"] == sent["deliveries"][0]["delivery_id"]
    def register(session, container, **kwargs):
        response = http.post("/internal/claude-wake/register", json={
            **PAYLOAD,
            "session_ref": session,
            "container_ref": container,
            "idle": kwargs.get("idle", False),
        })
        return response.status_code == 204

    phase, hook_requests, refusals, acknowledged_ids = ["initial-stop"], [], [], []

    def relay_request(method, path, body, *, timeout=0.75):
        hook_requests.append((phase[0], method, path))
        response = http.request(method, path, json=body)
        if response.status_code == 503:
            assert path == "/relay/turn"
            assert response.json() == {"detail": {"code": "relay_busy", "retryable": True}}
            assert response.json()["detail"]["retryable"] is True
            assert response.headers["Retry-After"] == "1"
            refusals.append((phase[0], dict(body)))
            return None
        assert response.status_code == 200, response.text
        return response.json() if response.content else None

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
            acknowledged_ids.append(delivery["delivery_id"])
        return acknowledged

    stop = _load_claude_hook("stop", monkeypatch)
    monkeypatch.setattr(sys.modules[stop.relay_turn.__module__], "SESSIONS_DIR", tmp_path / "hook-sessions")
    monkeypatch.setattr(sys.modules[stop.relay_turn.__module__], "STATE_DIR", tmp_path / "hook-state")
    monkeypatch.setattr(stop, "resolve_container_ref", lambda *_: scope["container_ref"])
    monkeypatch.setattr(stop, "derive_actor_ref", lambda *_: "local")
    monkeypatch.setattr(stop, "register_claude_wake", register)
    monkeypatch.setattr(stop, "relay_request", relay_request)
    monkeypatch.setattr(stop, "acknowledge_relay", acknowledge)
    monkeypatch.setattr(stop, "read_hook_input", lambda: {
        "session_id": PAYLOAD["session_ref"],
        "cwd": str(tmp_path),
        "transcript_path": "",
    })
    stop.main()
    assert registry.recovery_candidates()[0]["state"] == "idle"

    transported = threading.Event()
    transport_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.claude_wake.claude_wake_transport",
        lambda path, token: transport_calls.append((path, token)) or transported.set() or True,
    )
    clock[0] += timedelta(seconds=61)
    recover_expired_relay_wakes(relay, registry)
    assert transported.wait(timeout=0.5)
    assert transport_calls == [(PAYLOAD["socket_path"], PAYLOAD["token"])]

    forced, turn = [], relay._store.relay_turn

    def refuse_claim(**kwargs):
        if (force_claim_refusals and phase[0] in {"prompt", "stop"}
                and phase[0] not in forced and kwargs.get("max_chars", 0) > 0):
            assert kwargs["runtime"] == "claude-code" and kwargs["session_ref"] == PAYLOAD["session_ref"]
            forced.append(phase[0])
            raise ImmediateTransactionBusyError("controlled lifecycle refusal", acquisition_stage="late_begin")
        return turn(**kwargs)

    monkeypatch.setattr(relay._store, "relay_turn", refuse_claim)
    prompt = _load_claude_hook("user_prompt_submit", monkeypatch)
    monkeypatch.setattr(sys.modules[prompt.relay_turn.__module__], "SESSIONS_DIR", tmp_path / "hook-sessions")
    monkeypatch.setattr(sys.modules[prompt.relay_turn.__module__], "STATE_DIR", tmp_path / "hook-state")
    monkeypatch.setattr(prompt, "resolve_container_ref", lambda *_: scope["container_ref"])
    monkeypatch.setattr(prompt, "derive_actor_ref", lambda *_: "local")
    monkeypatch.setattr(prompt, "register_claude_wake", register)
    monkeypatch.setattr(prompt, "relay_request", relay_request)
    monkeypatch.setattr(prompt, "acknowledge_relay", acknowledge)
    monkeypatch.setattr(
        prompt,
        "pallium_request",
        lambda *_args, **_kwargs: pytest.fail("Relay recovery must not ingest synthetic memory"),
    )
    prompt_id = "00000000-0000-4000-8000-000000000001" if with_prompt_id else None
    monkeypatch.setattr(prompt, "read_hook_input", lambda: {
        "session_id": PAYLOAD["session_ref"],
        "cwd": str(tmp_path),
        "prompt": "Pallium Relay wake notice: new messages available.",
        "prompt_id": prompt_id,
    })

    common = sys.modules[prompt.relay_turn.__module__]
    if with_prompt_id:
        assert common.source_turn_key(prompt_id) == prompt_id
    notice = "Pallium Relay wake notice: new messages available."
    assert common.check_dedup(notice, PAYLOAD["session_ref"]) is False
    assert common.check_dedup(notice, PAYLOAD["session_ref"]) is True
    expected_fence, = registry.recovery_candidates()
    assert expected_fence["state"] == "wake_inflight"
    assert (expected_fence["runtime"], expected_fence["session_ref"], expected_fence["container_ref"],
            expected_fence["delivery_id"]) == ("claude-code", PAYLOAD["session_ref"], scope["container_ref"], claimed["delivery_id"])
    output, deadline = "", time.monotonic() + 5

    def assert_fenced():
        pending = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
        assert (pending["delivery_id"], pending["state"], pending["attempts"]) == (
            claimed["delivery_id"], claimed["state"], claimed["attempts"],
        )
        assert relay.pending_candidate(runtime="claude-code", session_ref=PAYLOAD["session_ref"],
                                       delivery_id=claimed["delivery_id"], **scope) == {
            "delivery_id": claimed["delivery_id"], "recipient_endpoint_id": claimed["recipient_endpoint_id"],
            "state": "pending",
        }
        assert pending["recipient_endpoint_id"] == claimed["recipient_endpoint_id"]
        assert acknowledged_ids == [] and "wake after crash ✓" not in output
        assert registry.recovery_candidates() == [expected_fence]
        before_transport = tuple(transport_calls)
        recover_expired_relay_wakes(relay, registry)
        assert tuple(transport_calls) == before_transport
        return pending

    phase[0], before_requests, before_refusals = "prompt", len(hook_requests), len(refusals)
    try:
        prompt.main()
    except SystemExit as prompted:
        assert prompted.code == 0
    captured = capsys.readouterr()
    output += captured.out + captured.err
    assert len(hook_requests) == before_requests + 1
    delivered = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
    if delivered["state"] != "delivered":
        assert len(refusals) == before_refusals + 1
        assert_fenced()
        # These Stops are explicit later host events; reconciliation cannot create them.
        for _ in range(8):
            assert time.monotonic() < deadline, "Claude recovery exceeded wall-time bound"
            phase[0], before_requests, before_refusals = "stop", len(hook_requests), len(refusals)
            try:
                stop.main()
            except SystemExit as stopped:
                assert stopped.code == 2
            captured = capsys.readouterr()
            output += captured.out + captured.err
            assert len(hook_requests) == before_requests + 1
            delivered = relay.message_status(message_id=sent["message_id"], **scope)["deliveries"][0]
            if delivered["state"] == "delivered":
                break
            assert len(refusals) == before_refusals + 1
            assert_fenced()
        else:
            pytest.fail("Claude recovery exceeded eight explicit natural Stop events")
    assert time.monotonic() < deadline, "Claude recovery exceeded wall-time bound"
    assert len(transport_calls) == 1  # An accepted wake remains fenced until its exact ACK.
    assert forced == (["prompt", "stop"] if force_claim_refusals else [])
    assert output.count("wake after crash ✓") == 1
    assert acknowledged_ids == [claimed["delivery_id"]]
    assert registry.recovery_candidates() == []
    assert delivered["state"] == "delivered" and delivered["attempts"] == 2
    (tmp_path / "claude-recovery-boundary.json").write_text(json.dumps({
        "forced": forced, "http_refusals": refusals, "hook_requests": hook_requests,
        "native_wakes": len(transport_calls), "delivered": delivered["delivery_id"],
    }), encoding="utf-8")
    transport_calls.clear()
    recover_expired_relay_wakes(relay, registry)
    assert transport_calls == []
    assert relay.turn(
        runtime="claude-code", session_ref=PAYLOAD["session_ref"], **scope
    )["deliveries"] == []

    # An overtaken notice is still coordination, even with no remaining delivery.
    phase[0], before_requests = "overtaken-notice", len(hook_requests)
    prompt.main()
    captured = capsys.readouterr()
    assert "wake after crash ✓" not in captured.out + captured.err
    assert len(hook_requests) == before_requests + 1
    assert acknowledged_ids == [claimed["delivery_id"]]


@pytest.mark.parametrize("decoration", ["exact", "prefix", "suffix"])
def test_claude_empty_wake_notice_and_near_match_memory_boundaries(client, monkeypatch, tmp_path, decoration):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.dependencies import build_router
    from tests.test_claude_code_integration import _load_claude_hook

    notice = "Pallium Relay wake notice: new messages available."
    text = {"exact": notice, "prefix": "Please explain: " + notice, "suffix": notice + " user note"}[decoration]
    scope = {"container_ref": PAYLOAD["container_ref"]}
    app = FastAPI()
    app.include_router(build_router(client.app.state.pallium_service,
                                   relay_storage=client.app.state.pallium_service._storage,
                                   claude_wake_registry=ClaudeWakeRegistry()))
    with TestClient(app, client=("127.0.0.1", 50000)) as http:
        hook = _load_claude_hook("user_prompt_submit", monkeypatch)
        common = sys.modules[hook.relay_turn.__module__]
        monkeypatch.setattr(common, "STATE_DIR", tmp_path / "hook-state")
        monkeypatch.setattr(common, "SESSIONS_DIR", tmp_path / "hook-sessions")
        monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: scope["container_ref"])
        monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "local")
        monkeypatch.setattr(hook, "read_hook_input", lambda: {
            "session_id": PAYLOAD["session_ref"], "cwd": str(tmp_path), "prompt": text,
        })
        relay_calls, memory_calls = [], []

        def register(session, container, **kwargs):
            response = http.post("/internal/claude-wake/register", json={
                **PAYLOAD, "session_ref": session, "container_ref": container, "idle": kwargs.get("idle", False),
            })
            assert response.status_code == 204
            return True

        def relay_request(method, path, body, **kwargs):
            response = http.request(method, path, json=body)
            assert response.status_code == 200, response.text
            assert response.json()["deliveries"] == []
            relay_calls.append((method, path))
            return response.json()

        def memory_request(method, path, body):
            memory_calls.append((method, path, body))
            return {"injectable_blocks": []}

        monkeypatch.setattr(hook, "register_claude_wake", register)
        monkeypatch.setattr(hook, "relay_request", relay_request)
        monkeypatch.setattr(hook, "pallium_request", memory_request)
        monkeypatch.setattr(hook, "acknowledge_relay", lambda *_a, **_k: pytest.fail("Empty notice must not ACK"))
        for invocation in (1, 2):
            try:
                hook.main()
            except SystemExit as exited:
                assert exited.code == 0
            assert len(relay_calls) == (invocation if decoration == "exact" else 1)
            assert len(memory_calls) == (0 if decoration == "exact" else 1)
        if decoration != "exact":
            method, path, body = memory_calls[0]
            assert (method, path, body["content"], body["query_text"]) == ("POST", "/item-and-query", text, text)


def test_cross_container_duplicate_native_claude_endpoints_wake_independently(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.dependencies import build_router

    actor = "shared-wake-actor"
    source = "git:example.test/wake-source"
    target = "git:example.test/wake-target"
    registry = ClaudeWakeRegistry()
    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
        claude_wake_registry=registry,
    ))
    http = TestClient(app, client=("127.0.0.1", 50000))

    def turn(runtime: str, session_ref: str, container_ref: str) -> dict:
        response = http.post("/relay/turn", json={
            "runtime": runtime,
            "session_ref": session_ref,
            "container_ref": container_ref,
        })
        assert response.status_code == 200, response.text
        return response.json()

    turn("codex", "sender", source)
    first = turn("claude-code", "duplicate", source)["session"]
    second = turn("claude-code", "duplicate", target)["session"]
    for container_ref, socket_path, token in (
        (source, "socket-a", "token-a"),
        (target, "socket-b", "token-b"),
    ):
        response = http.post("/internal/claude-wake/register", json={
            "runtime": "claude-code",
            "session_ref": "duplicate",
            "container_ref": container_ref,
            "socket_path": socket_path,
            "token": token,
            "idle": True,
        })
        assert response.status_code == 204, response.text

    observed: list[tuple[str, str]] = []
    complete = threading.Event()

    def transport(socket_path: str, token: str) -> str:
        observed.append((socket_path, token))
        if len(observed) == 2:
            complete.set()
        return "accepted"

    monkeypatch.setattr("app.claude_wake.claude_wake_transport", transport)
    for endpoint, payload in ((first["endpoint_id"], "left"), (second["endpoint_id"], "right")):
        response = http.post("/relay/messages", json={
            "sender_runtime": "codex",
            "sender_session_ref": "sender",
            "recipient": endpoint,
            "payload": payload,
            "container_ref": source,
        })
        assert response.status_code == 200, response.text

    assert complete.wait(timeout=1)
    assert sorted(observed) == [("socket-a", "token-a"), ("socket-b", "token-b")]
    assert [item["payload"] for item in turn("claude-code", "duplicate", source)["deliveries"]] == ["left"]
    assert [item["payload"] for item in turn("claude-code", "duplicate", target)["deliveries"]] == ["right"]

def test_posix_transport_post_frame_failure_is_uncertain(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.claude_wake_transport as transport

    writes = []

    class BrokenAfterAuth:
        def settimeout(self, _seconds):
            pass
        def connect(self, _path):
            pass
        def sendall(self, value):
            writes.append(value)
            if len(writes) == 2:
                raise socket.timeout()
        def close(self):
            pass

    monkeypatch.setattr(transport.socket, "AF_UNIX", 1, raising=False)
    monkeypatch.setattr(transport.socket, "socket", lambda *_: BrokenAfterAuth())
    result = transport._posix_transport("ignored", "token")
    assert len(writes) == 2
    assert result.outcome == "uncertain"
    assert result.reason == "peer_frame_uncertain"
    assert result.evidence == ("submission_attempted",)
    assert result.native_retry_safe is False

def test_router_codex_wake_registry_uses_isolated_sqlite_authority(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import codex_wake
    from app.dependencies import build_router
    from core.relay import RelayService

    expected_dir = Path(os.environ["PALLIUM_CODEX_WAKE_DIR"])
    assert expected_dir.parent == tmp_path
    default = codex_wake.get_codex_wake_registry()
    assert default._path is None and not default.usable
    storage = client.app.state.pallium_service._storage
    registry = codex_wake.get_codex_wake_registry_for_relay_database(
        str(storage._relay_engine.url), relay_service=RelayService(storage),
    )
    assert registry.initialize(old_owner_drained=True)
    assert registry._path == expected_dir / "reservations.json"
    monkeypatch.setattr(
        "app.dependencies.schedule_codex_relay_wake",
        codex_wake.schedule_codex_relay_wake,
    )
    monkeypatch.setattr(codex_wake, "_wake_after_debounce", lambda *_: None)

    app = FastAPI()
    app.include_router(build_router(
        client.app.state.pallium_service,
        relay_storage=client.app.state.pallium_service._storage,
        codex_wake_registry=registry,
    ))
    http = TestClient(app, client=("127.0.0.1", 50000))
    scope = {"container_ref": "git:example.test/codex-test-state"}
    for runtime, session in (("codex", "target"), ("claude-code", "sender")):
        assert http.post(
            "/relay/turn",
            json={"runtime": runtime, "session_ref": session, **scope},
        ).status_code == 200
    sent = http.post(
        "/relay/messages",
        json={
            "sender_runtime": "claude-code",
            "sender_session_ref": "sender",
            "recipient": "codex:target",
            "payload": "isolated state",
            **scope,
        },
    )
    assert sent.status_code == 200, sent.text
    delivery = sent.json()["deliveries"][0]
    assert registry.snapshot(delivery["recipient_endpoint_id"]).delivery_id == (
        delivery["delivery_id"]
    )
    assert not registry._path.exists()
    assert registry._path.is_relative_to(tmp_path)
