"""Pre-launch checks only: these tests never start Hermes or Electron."""
from pathlib import Path
import hashlib
import io
import json
import threading
from types import SimpleNamespace

import pytest

from tests.fixtures.hermes_desktop_driver import (
    DesktopConsole, RUNNER_MARKERS, contained_path, desktop_env, require_runner_gate,
)


def test_disposable_runner_gate_and_strict_containment(tmp_path):
    child = tmp_path / "job" / "profile"
    env = {**RUNNER_MARKERS, "RUNNER_TEMP": str(tmp_path), "USERPROFILE": str(tmp_path.parent)}
    assert require_runner_gate(env, child) == tmp_path.resolve()
    for name in RUNNER_MARKERS:
        with pytest.raises(AssertionError, match="disposable Windows"):
            require_runner_gate({**env, name: "wrong"}, child)
    for escaped in (tmp_path, tmp_path.parent / "outside", Path("relative")):
        with pytest.raises(AssertionError):
            require_runner_gate(env, escaped)
    with pytest.raises(AssertionError, match="profile root"):
        require_runner_gate({**env, "USERPROFILE": str(tmp_path)}, child)


def test_containment_rejects_reparse_ancestor_before_resolution(tmp_path, monkeypatch):
    alias = tmp_path / "alias"
    monkeypatch.setattr(Path, "is_junction", lambda self: self == alias)
    with pytest.raises(AssertionError, match="reparse"):
        contained_path(tmp_path, alias / "profile")


def test_partial_desktop_constructor_close_preserves_gate_error_and_target(tmp_path):
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("unchanged", encoding="utf-8")
    console = DesktopConsole.__new__(DesktopConsole)
    with pytest.raises(AssertionError, match="disposable Windows"):
        try:
            console.__init__(tmp_path / "python.exe", tmp_path / "source", tmp_path / "home", {},
                             tmp_path, threading.Event(), None)
        finally:
            console.close()
    assert sentinel.read_text(encoding="utf-8") == "unchanged"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["sentinel"]


def test_desktop_environment_uses_public_isolated_backend_and_keeps_python_guard(tmp_path):
    source, python, home = (tmp_path / name for name in ("source", "python.exe", "home"))
    original = {"NODE_OPTIONS": "deny-terminal-network", "PYTHONPATH": "backend-guard",
                "HERMES_TUI": "1", "HERMES_HOME": str(home / ".hermes"),
                "HERMES_DESKTOP_HERMES": "ambient-launcher", "HERMES_DESKTOP_TEST_MODE": "1"}
    env = desktop_env(original, source, python, home)
    assert not {"NODE_OPTIONS", "HERMES_TUI", "HERMES_DESKTOP_HERMES", "HERMES_DESKTOP_TEST_MODE"} & env.keys()
    assert env["PYTHONPATH"] == "backend-guard"
    assert env["HERMES_DESKTOP_ISOLATED_BACKEND"] == "1"
    assert env["HERMES_DESKTOP_PYTHON"] == str(python)
    assert env["HERMES_DESKTOP_HERMES_ROOT"] == str(source)
    assert env["HERMES_DESKTOP_USER_DATA_DIR"] == str(home / "desktop-user-data")
    assert env["HERMES_DESKTOP_CWD"] == str(home / "scratch")
    assert original["NODE_OPTIONS"] == "deny-terminal-network"


@pytest.mark.parametrize("expected", ["", "x" * 64, "0" * 64])
def test_desktop_bad_binary_provenance_never_launches(tmp_path, monkeypatch, expected):
    source, home, artifacts = (tmp_path / name for name in ("source", "home", "artifacts"))
    binary = source / "apps" / "desktop" / "release" / "win-unpacked" / "Hermes.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"synthetic non-executable")
    env = {**RUNNER_MARKERS, "RUNNER_TEMP": str(tmp_path), "HERMES_DESKTOP_EXE_SHA256": expected}
    calls = []
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(AssertionError, match="hash required|binary drift"):
        DesktopConsole(tmp_path / "python.exe", source, home, env, artifacts, threading.Event(), None)
    assert calls == []
    assert not home.exists() and not artifacts.exists()


def test_desktop_owned_startup_and_ui_protocol_without_native_process(tmp_path, monkeypatch):
    source, home, artifacts = (tmp_path / name for name in ("source", "home", "artifacts"))
    binary = source / "apps" / "desktop" / "release" / "win-unpacked" / "Hermes.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"synthetic non-executable")
    artifacts.mkdir()
    env = {**RUNNER_MARKERS, "RUNNER_TEMP": str(tmp_path), "HERMES_NODE": str(tmp_path / "node.exe"),
           "HERMES_DESKTOP_EXE_SHA256": hashlib.sha256(binary.read_bytes()).hexdigest(), "NODE_OPTIONS": "terminal-only"}
    app = SimpleNamespace(pid=123, stdout=io.StringIO(), poll=lambda: None,
                          stderr=io.StringIO("DevTools listening on ws://127.0.0.1:43123/devtools/browser/synthetic\n"))
    wire = "".join(json.dumps({"id": op, "ok": True, "result": {}}) + "\n"
                   for op in ("ready", "submit", "wait", "new"))
    cdp = SimpleNamespace(pid=456, stdin=io.StringIO(), stdout=io.StringIO(wire), poll=lambda: None)
    calls, identities = [], []

    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return app if len(calls) == 1 else cdp

    monkeypatch.setattr("subprocess.Popen", popen)
    # The mocked Windows launch also runs on Linux, which does not define this native flag.
    monkeypatch.setattr("subprocess.CREATE_NO_WINDOW", 0, raising=False)
    tree = SimpleNamespace(error=None, psutil=SimpleNamespace(Process=lambda pid: pid), record=identities.append)
    console = DesktopConsole(tmp_path / "python.exe", source, home, env, artifacts, threading.Event(), tree)
    try:
        console.ready()
        console.submit("hello 漢字 🌍", marker="hello")
        console.wait("rendered answer")
        console.new_session()
    finally:
        console.close()
    assert identities == [123, 456]
    assert calls[0][0] == [str(binary), "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0"]
    assert calls[1][0][2:] == ["ws://127.0.0.1:43123/devtools/browser/synthetic", str(source)]
    assert all("NODE_OPTIONS" not in kwargs["env"] for _, kwargs in calls)
    assert json.loads(cdp.stdin.getvalue().splitlines()[1])["text"] == "hello 漢字 🌍"
    assert (artifacts / "desktop-output.json").is_file()
