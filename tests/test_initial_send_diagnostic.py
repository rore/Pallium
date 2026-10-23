"""Owned-handle cleanup boundaries; these tests never launch a process."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest


@pytest.mark.parametrize("outcome", ["exited", "terminate", "kill", "stuck"])
def test_initial_send_cleanup_uses_only_owned_handle_and_bounded_waits(monkeypatch, outcome):
    path = Path(__file__).parents[1] / "scripts/diagnostics/initial_send/run.py"
    spec = importlib.util.spec_from_file_location("initial_send_runner", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    calls = []
    clock = iter((0, 7.5, 15))
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    monkeypatch.setattr(runner.signal, "signal", lambda *_: None)
    child = SimpleNamespace(returncode=0 if outcome == "exited" else None)
    child.poll = lambda: child.returncode

    def terminate():
        calls.append("terminate")

    def kill():
        calls.append("kill")
        if outcome != "stuck":
            child.returncode = -9

    def wait(*, timeout):
        calls.append(timeout)
        if outcome == "terminate":
            child.returncode = 0
        if child.returncode is None:
            raise subprocess.TimeoutExpired("owned", timeout)
        return child.returncode

    child.terminate, child.kill, child.wait = terminate, kill, wait
    receipt = {}
    runner.drain(child, receipt)
    assert receipt["owned_root_exited"] is (outcome != "stuck")
    assert all(0 <= value <= 7.5 for value in calls if isinstance(value, float))
    assert calls == {
        "exited": [], "terminate": ["terminate", 7.5],
        "kill": ["terminate", 7.5, "kill", 7.5],
        "stuck": ["terminate", 7.5, "kill", 7.5],
    }[outcome]
    assert ("cleanup_error" in receipt) is (outcome == "stuck")
