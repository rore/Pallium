"""Unit tests for app.supervisor._kill_tree.

Covers cross-platform process-tree kill semantics: Windows ``taskkill /T``
escalation and POSIX ``killpg`` with fallback to direct kill. These tests
intentionally avoid spawning real subprocesses — the helper is tested as a
pure function over injected primitives.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from unittest.mock import patch

import pytest

from app.supervisor import _kill_tree, _TASKKILL_SUCCESS_CODES


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, pid: int = 4242, wait_raises: Exception | None = None) -> None:
        self.pid = pid
        self._wait_raises = wait_raises
        self.kill_called = False
        self.terminate_called = False
        self.wait_called_with: float | None = None

    def kill(self) -> None:
        self.kill_called = True

    def terminate(self) -> None:
        self.terminate_called = True

    def wait(self, timeout: float | None = None) -> None:
        self.wait_called_with = timeout
        if self._wait_raises is not None:
            raise self._wait_raises


def _completed(returncode: int, stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stderr=stderr)


# ---------------------------------------------------------------------------
# Windows path
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only path")
class TestKillTreeWindows:
    def test_force_false_invokes_taskkill_t_no_f(self) -> None:
        proc = _FakeProc()
        captured = {}

        def runner(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return _completed(0)

        _kill_tree(proc, force=False, runner=runner)

        assert captured["cmd"][0] == "taskkill"
        assert "/T" in captured["cmd"]
        assert "/F" not in captured["cmd"]
        assert "/PID" in captured["cmd"]
        assert str(proc.pid) in captured["cmd"]
        assert captured["kwargs"].get("check") is False
        assert captured["kwargs"].get("capture_output") is True

    def test_force_true_adds_f_flag(self) -> None:
        proc = _FakeProc()
        captured = {}

        def runner(cmd, **kwargs):
            captured["cmd"] = cmd
            return _completed(0)

        _kill_tree(proc, force=True, runner=runner)

        assert "/F" in captured["cmd"]
        assert "/T" in captured["cmd"]

    def test_taskkill_exit_128_treated_as_success(self) -> None:
        """exit 128 = process not found — already gone counts as success."""
        proc = _FakeProc()
        log_calls = []

        def runner(cmd, **kwargs):
            return _completed(128, stderr=b"ERROR: The process \"4242\" not found.\r\n")

        _kill_tree(proc, force=True, runner=runner, log=lambda c, m: log_calls.append((c, m)))

        # No "unexpected code" log entry should fire for known-success codes
        assert not any("unexpected code" in m for _, m in log_calls)

    def test_taskkill_exit_1_treated_as_failure(self) -> None:
        """exit 1 = "could not be terminated" — this is a real failure (e.g.
        permission denied). Must NOT be treated as success, otherwise low-priv
        Scheduled Task accounts can silently fail to kill orphan trees."""
        proc = _FakeProc()
        log_calls = []

        def runner(cmd, **kwargs):
            return _completed(1, stderr=b"ERROR: The process could not be terminated.")

        _kill_tree(proc, force=False, runner=runner, log=lambda c, m: log_calls.append((c, m)))

        assert any("unexpected code 1" in m for _, m in log_calls), (
            "exit code 1 must surface as 'unexpected code' so failures aren't silently masked"
        )

    def test_taskkill_unexpected_exit_logged(self) -> None:
        proc = _FakeProc()
        log_calls = []

        def runner(cmd, **kwargs):
            return _completed(2, stderr=b"weird")

        _kill_tree(proc, force=True, runner=runner, log=lambda c, m: log_calls.append((c, m)))

        assert any("unexpected code 2" in m for _, m in log_calls)

    def test_taskkill_timeout_logged_not_raised(self) -> None:
        proc = _FakeProc()
        log_calls = []

        def runner(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 5.0))

        _kill_tree(proc, force=True, runner=runner, wait_timeout=1.0, log=lambda c, m: log_calls.append((c, m)))

        assert any("timed out" in m for _, m in log_calls)

    def test_taskkill_oserror_falls_back_to_process_kill(self) -> None:
        proc = _FakeProc()
        log_calls = []

        def runner(cmd, **kwargs):
            raise FileNotFoundError("taskkill missing")

        _kill_tree(proc, force=True, runner=runner, log=lambda c, m: log_calls.append((c, m)))

        assert proc.kill_called, "expected fallback to process.kill() when taskkill unavailable"
        assert any("falling back" in m for _, m in log_calls)

    def test_always_calls_wait_with_timeout(self) -> None:
        proc = _FakeProc()

        def runner(cmd, **kwargs):
            return _completed(0)

        _kill_tree(proc, force=False, runner=runner, wait_timeout=2.5)
        assert proc.wait_called_with == 2.5

    def test_wait_timeout_logged_not_raised(self) -> None:
        proc = _FakeProc(wait_raises=subprocess.TimeoutExpired(cmd="x", timeout=5.0))
        log_calls = []

        def runner(cmd, **kwargs):
            return _completed(0)

        _kill_tree(proc, force=True, runner=runner, log=lambda c, m: log_calls.append((c, m)))

        assert any("did not exit within" in m for _, m in log_calls)


# ---------------------------------------------------------------------------
# POSIX path
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only path")
class TestKillTreePosix:
    def test_force_false_uses_sigterm_on_killpg(self) -> None:
        proc = _FakeProc()
        captured = {}

        def fake_killpg(pgid, sig):
            captured["pgid"] = pgid
            captured["sig"] = sig

        with patch("os.getpgid", return_value=12345):
            _kill_tree(proc, force=False, killpg=fake_killpg)

        assert captured["sig"] == signal.SIGTERM
        assert captured["pgid"] == 12345

    def test_force_true_uses_sigkill_on_killpg(self) -> None:
        proc = _FakeProc()
        captured = {}

        def fake_killpg(pgid, sig):
            captured["sig"] = sig

        with patch("os.getpgid", return_value=12345):
            _kill_tree(proc, force=True, killpg=fake_killpg)

        assert captured["sig"] == signal.SIGKILL

    def test_processlookuperror_falls_back_to_process_kill(self) -> None:
        proc = _FakeProc()

        def fake_killpg(pgid, sig):
            raise ProcessLookupError("already gone")

        with patch("os.getpgid", side_effect=ProcessLookupError("already gone")):
            _kill_tree(proc, force=True, killpg=fake_killpg)

        assert proc.kill_called

    def test_force_false_processlookup_falls_back_to_terminate(self) -> None:
        proc = _FakeProc()

        with patch("os.getpgid", side_effect=ProcessLookupError):
            _kill_tree(proc, force=False, killpg=lambda *_: None)

        assert proc.terminate_called
        assert not proc.kill_called

    def test_oserror_in_killpg_falls_back(self) -> None:
        proc = _FakeProc()
        log_calls = []

        def fake_killpg(pgid, sig):
            raise OSError("EINVAL")

        with patch("os.getpgid", return_value=99):
            _kill_tree(
                proc,
                force=True,
                killpg=fake_killpg,
                log=lambda c, m: log_calls.append((c, m)),
            )

        assert proc.kill_called
        assert any("killpg failed" in m for _, m in log_calls)

    def test_always_calls_wait(self) -> None:
        proc = _FakeProc()

        with patch("os.getpgid", return_value=1):
            _kill_tree(proc, force=False, killpg=lambda *_: None, wait_timeout=3.0)

        assert proc.wait_called_with == 3.0


# ---------------------------------------------------------------------------
# Cross-platform invariants
# ---------------------------------------------------------------------------


class TestKillTreeInvariants:
    def test_none_process_is_noop(self) -> None:
        # Should not raise
        _kill_tree(None, force=True)  # type: ignore[arg-type]

    def test_known_success_codes_documented(self) -> None:
        # Sanity: 0 (killed) and 128 (process not found) are accepted as success.
        # Code 1 ("could not be terminated") is NOT a success — see
        # test_taskkill_exit_1_treated_as_failure.
        assert 0 in _TASKKILL_SUCCESS_CODES
        assert 128 in _TASKKILL_SUCCESS_CODES
        assert 1 not in _TASKKILL_SUCCESS_CODES
