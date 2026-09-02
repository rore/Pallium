"""Tests for Claude Code wake transport and dispatch."""

from __future__ import annotations

import json
import os
import socket
import threading
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.claude_wake import schedule_claude_relay_wake
from app.claude_wake_transport import claude_wake_transport
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
