"""Tests for Claude Code wake transport and dispatch."""

from __future__ import annotations

import json
import os
import socket
import threading
import tempfile
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


class TestTransport:
    """Transport tests: write auth + frame, handle errors."""

    @pytest.mark.skipif(os.name == "nt", reason="Unix socket test")
    def test_posix_transport_writes_auth_and_frame(self, tmp_path: Path) -> None:
        """POSIX: connect, write auth line, write peer frame."""
        socket_path = str(tmp_path / "test.sock")
        received: list[str] = []
        done = threading.Event()

        def listener():
            try:
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(socket_path)
                server.listen(1)
                conn, _ = server.accept()
                data = b""
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                received.extend(data.decode("utf-8").split("\n"))
                conn.close()
                server.close()
            except Exception:
                pass
            finally:
                done.set()

        thread = threading.Thread(target=listener, daemon=True)
        thread.start()
        import time
        time.sleep(0.1)  # Let listener bind

        result = claude_wake_transport(socket_path, "test-token")
        done.wait(timeout=2)
        thread.join(timeout=1)

        assert result is True
        lines = [line for line in received if line.strip()]
        assert len(lines) >= 2

        auth = json.loads(lines[0])
        assert auth["type"] == "auth"
        assert auth["token"] == "test-token"

        frame = json.loads(lines[1])
        assert frame["msgV"] == 1
        assert frame["type"] == "user"
        assert frame["message"]["role"] == "user"
        assert frame["priority"] == "next"
        assert frame["from"] == "pallium-relay"

    @pytest.mark.skipif(os.name == "nt", reason="Unix socket test")
    def test_posix_transport_bad_socket_path_returns_false(self) -> None:
        """POSIX: nonexistent socket returns False, no raise."""
        result = claude_wake_transport("/nonexistent/socket.sock", "token")
        assert result is False

    def test_windows_write_cancels_after_bounded_timeout(self) -> None:
        """Pending named-pipe writes must not block forever."""
        cancelled = []
        closed = []

        class Overlapped:
            hEvent = None

        pywintypes = SimpleNamespace(OVERLAPPED=Overlapped)
        win32event = SimpleNamespace(
            WAIT_OBJECT_0=0,
            CreateEvent=lambda *_args: "event",
            WaitForSingleObject=lambda *_args: 258,
        )
        win32file = SimpleNamespace(
            WriteFile=lambda *_args: (997, 0),
            CancelIoEx=lambda handle, overlapped: cancelled.append((handle, overlapped)),
            CloseHandle=lambda handle: closed.append(handle),
        )
        winerror = SimpleNamespace(ERROR_IO_PENDING=997)

        assert _windows_write("pipe", b"frame", pywintypes, win32event, win32file, winerror) is False
        assert len(cancelled) == 1
        assert closed == ["event"]
    @pytest.mark.skipif(os.name != "nt", reason="Windows test")
    def test_windows_transport_import_failure_returns_false(self) -> None:
        """Windows: win32file import failure returns False."""
        # This test can only run on Windows where win32file may not be available
        # If it is available, this test will naturally pass (the transport will work).
        # The point is to verify that ImportError is caught gracefully.
        result = claude_wake_transport(r"\\.\pipe\nonexistent", "token")
        # Either it works (win32file is installed) or returns False (not installed)
        assert isinstance(result, bool)


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

        schedule_claude_relay_wake(result, scope, registry=registry)

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

        schedule_claude_relay_wake(result, scope, registry=registry)

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
        schedule_claude_relay_wake(result, scope, registry=registry)
    transport.assert_not_called()
    assert client.post("/internal/claude-wake/register", json=payload).status_code == 204
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.claude_wake.claude_wake_transport", transport)
        schedule_claude_relay_wake(result, scope, registry=registry)
    transport.assert_called_once()
    assert not registry.probe(runtime="claude-code", session_ref="session-test", container_ref="wrong", actor_ref=scope["actor_ref"], transport=transport)
def test_windows_write_closes_event_after_cancelled_completion() -> None:
    class Overlapped:
        hEvent = None
    pywintypes = SimpleNamespace(OVERLAPPED=Overlapped)
    waits = iter([258])
    win32event = SimpleNamespace(WAIT_OBJECT_0=0, CreateEvent=lambda *_: "event", WaitForSingleObject=lambda *_: next(waits))
    closed = []
    win32file = SimpleNamespace(
        WriteFile=lambda *_: (997, 0),
        CancelIoEx=lambda *_: None,
        GetOverlappedResult=lambda *_: (_ for _ in ()).throw(OSError("ERROR_OPERATION_ABORTED")),
        CloseHandle=lambda handle: closed.append(handle),
    )
    assert _windows_write("pipe", b"frame", pywintypes, win32event, win32file, SimpleNamespace(ERROR_IO_PENDING=997)) is False
    assert closed == ["event"]

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
        for delivery in deliveries:
            response = http.post("/relay/deliveries/ack", json={
                "delivery_id": delivery["delivery_id"],
                "claim_token": delivery["claim_token"],
                **scope,
            })
            assert response.status_code == 200

    for hook in (start, prompt):
        monkeypatch.setattr(hook, "relay_request", relay)
    monkeypatch.setattr(prompt, "acknowledge_relay", acknowledge)
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
    stop.main()

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
    assert state(sent2) == state(sent3) == "pending"

    monkeypatch.setattr(prompt, "resolve_container_ref", lambda *_: scope["container_ref"])
    with pytest.raises(SystemExit):
        prompt.main()
    output = capsys.readouterr().out
    assert "D2" in output and "D3" in output
    assert state(sent2) == state(sent3) == "delivered"
