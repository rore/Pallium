"""Owned unpacked Desktop adapter. Native execution belongs on a disposable OS only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time


RUNNER_MARKERS = {
    "GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
    "RUNNER_OS": "Windows", "RUNNER_ARCH": "X64",
    "HERMES_NATIVE_CI_ISOLATION": "github-hosted-ephemeral-windows",
}


def contained_path(root: Path, target: Path) -> Path:
    """Reject aliases before resolution, then require a strict descendant of a known root."""
    assert root.is_absolute() and target.is_absolute(), "qualification paths must be absolute"
    for path in (root, target):
        for parent in (path, *path.parents):
            assert not parent.is_symlink() and not parent.is_junction(), "reparse qualification path refused"
    root, target = root.resolve(), target.resolve()
    assert target != root and target.is_relative_to(root), "qualification path escaped disposable root"
    return target


def require_runner_gate(env: dict[str, str], *writable: Path) -> Path:
    # Markers prevent accidental host execution; the approved CI job supplies the actual OS boundary.
    assert all(env.get(key) == value for key, value in RUNNER_MARKERS.items()), "disposable Windows runner required"
    runner = Path(env.get("RUNNER_TEMP", ""))
    assert runner.is_absolute() and runner.is_dir(), "existing independent runner temp required"
    assert runner.resolve() != Path(env.get("USERPROFILE", "")).resolve(), "runner temp cannot be the profile root"
    for path in writable:
        contained_path(runner, path)
    return runner.resolve()


def desktop_env(env: dict[str, str], source: Path, python: Path, home: Path) -> dict[str, str]:
    result = dict(env)
    # Electron does not use the terminal's Node preload; Python backend guards remain installed.
    for key in ("NODE_OPTIONS", "HERMES_TUI", "HERMES_DESKTOP_HERMES", "HERMES_DESKTOP_TEST_MODE"):
        result.pop(key, None)
    result.update({
        "HERMES_DESKTOP_USER_DATA_DIR": str(home / "desktop-user-data"),
        "HERMES_DESKTOP_CWD": str(home / "scratch"),
        "HERMES_DESKTOP_PYTHON": str(python),
        "HERMES_DESKTOP_HERMES_ROOT": str(source),
        "HERMES_DESKTOP_ISOLATED_BACKEND": "1",
    })
    return result


def validate_user_data_reuse(home: Path, source: Path, python: Path, previous_spec: Path) -> None:
    prior = json.loads(previous_spec.read_text(encoding="utf-8"))
    assert Path(prior["home"]).resolve() == home.resolve(), "prior close profile mismatch"
    assert Path(prior["source"]).resolve() == source.resolve(), "prior close source mismatch"
    assert Path(prior["python"]).resolve() == python.resolve(), "prior close runtime mismatch"
    python_base = Path(sys._base_executable).resolve()
    assert Path(prior["python_base"]).resolve() == python_base, "prior close base runtime mismatch"
    assert prior["python_base_sha256"] == hashlib.sha256(python_base.read_bytes()).hexdigest(), (
        "prior close base runtime hash mismatch")
    prior_artifacts = previous_spec.parent
    cleanup = json.loads((prior_artifacts / "cleanup.json").read_text(encoding="utf-8"))
    assert cleanup.get("driver_returncode") == 0 and cleanup.get("forced") is False \
        and cleanup.get("recovered") == [] and cleanup.get("alive") == [], "prior Desktop close was not clean"
    ledger = json.loads((prior_artifacts / "owned-processes-ledger.json").read_text(encoding="utf-8"))
    assert isinstance(ledger, list) and ledger, "prior owned identity ledger is missing"
    import psutil
    for row in ledger:
        try:
            proc = psutil.Process(row["pid"])
            assert not (proc.create_time() == row["birthtime"]
                        and Path(proc.exe()).resolve() == Path(row["exe"]).resolve()), (
                "prior owned Desktop identity is still alive")
        except psutil.NoSuchProcess:
            pass


class DesktopConsole:
    """Drive only the owned renderer's ordinary composer and New session command."""

    def __init__(self, python, source, home, env, artifacts, stopped, tree, *, reuse_user_data=False,
                 previous_spec=None, scope_mode="fixed"):
        self.tree, self.stopped, self.artifacts = tree, stopped, artifacts
        self.replies = queue.Queue()
        self.cdp = None
        self.logs = []
        self.proc = None
        self.paths_checked = False
        require_runner_gate(env, home, artifacts, source)
        assert type(scope_mode) is str and scope_mode in {"fixed", "cwd"}, "unknown Desktop scope mode"
        if scope_mode == "cwd":
            scratch = contained_path(home, home / "scratch")
            assert scratch.is_dir(), "existing Desktop workspace required"
        self.paths_checked = True
        executable = source / "apps" / "desktop" / "release" / "win-unpacked" / "Hermes.exe"
        contained_path(source, executable)
        expected = env.get("HERMES_DESKTOP_EXE_SHA256", "")
        assert re.fullmatch(r"[0-9a-fA-F]{64}", expected), "explicit Desktop binary hash required"
        assert hashlib.sha256(executable.read_bytes()).hexdigest() == expected.lower(), "Desktop binary drift"
        assert isinstance(reuse_user_data, bool), "userData reuse must be a boolean"
        user_data = home / "desktop-user-data"
        contained_path(home, user_data)
        if reuse_user_data:
            assert previous_spec is not None, "same-profile reuse requires a prior close spec"
            contained_path(Path(env["RUNNER_TEMP"]), Path(previous_spec))
            validate_user_data_reuse(home, source, python, Path(previous_spec))
            assert user_data.is_dir(), "same-profile reuse requires existing Desktop userData"
        else:
            assert not user_data.exists(), "Desktop userData must be fresh"
        self.child_env = desktop_env(env, source, python, home)
        self.proc = subprocess.Popen([
            str(executable), "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
        ], cwd=home / "scratch", env=self.child_env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW)
        tree.record(tree.psutil.Process(self.proc.pid))
        self.output = queue.Queue()

        def pump(stream, kind):
            for line in stream:
                self.output.put((kind, line))

        self.readers = [threading.Thread(target=pump, args=(stream, kind), daemon=True)
                        for stream, kind in ((self.proc.stdout, "stdout"), (self.proc.stderr, "stderr"))]
        for reader in self.readers:
            reader.start()
        endpoint = None
        deadline = time.monotonic() + 90
        while endpoint is None:
            self._alive(deadline)
            try:
                kind, line = self.output.get(timeout=.1)
                self.logs.append({"stream": kind, "text": line})
                if kind == "stderr" and (match := re.search(r"DevTools listening on (ws://\S+)", line)):
                    endpoint = match[1]
            except queue.Empty:
                pass
        helper = Path(__file__).with_name("hermes_desktop_cdp_driver.cjs")
        self.cdp_log = (artifacts / "desktop-cdp-errors.txt").open("x", encoding="utf-8")
        self.cdp = subprocess.Popen([env["HERMES_NODE"], str(helper), endpoint, str(source),
                                     scope_mode, str(home / "scratch")],
                                    cwd=home / "scratch", env=self.child_env, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=self.cdp_log, text=True, encoding="utf-8",
                                    creationflags=subprocess.CREATE_NO_WINDOW)
        tree.record(tree.psutil.Process(self.cdp.pid))

        def replies():
            for line in self.cdp.stdout:
                self.replies.put(line)

        self.reply_reader = threading.Thread(target=replies, daemon=True)
        self.reply_reader.start()

    def _alive(self, deadline):
        assert not self.stopped.is_set(), "Desktop driver shutdown requested"
        assert self.tree.error is None, self.tree.error
        assert self.proc.poll() is None, "owned Desktop exited before readiness"
        if time.monotonic() >= deadline:
            raise TimeoutError("owned Desktop/CDP readiness timed out")

    def _command(self, op, **fields):
        self.cdp.stdin.write(json.dumps({"id": op, "op": op, **fields}, ensure_ascii=True) + "\n")
        self.cdp.stdin.flush()
        deadline = time.monotonic() + 100
        while True:
            self._alive(deadline)
            try:
                reply = json.loads(self.replies.get(timeout=.1))
            except queue.Empty:
                assert self.cdp.poll() is None, "Desktop CDP adapter exited"
                continue
            assert reply.get("id") == op and reply.get("ok") is True, reply
            return reply["result"]

    def ready(self):
        self._command("ready")

    def submit(self, prompt, *, marker):
        assert marker and marker in prompt
        prompt.encode("utf-8", errors="strict")
        self._command("submit", text=prompt)

    def wait(self, expected, *, timeout=90):
        self._command("wait", text=expected)

    def new_session(self):
        self._command("new")

    def close(self):
        # The shared dispatcher closes the exact owned tree first, including partial constructors.
        for attribute in ("reply_reader",):
            if reader := getattr(self, attribute, None):
                reader.join(2)
        for reader in getattr(self, "readers", []):
            reader.join(2)
        while hasattr(self, "output"):
            try:
                kind, line = self.output.get_nowait()
                self.logs.append({"stream": kind, "text": line})
            except queue.Empty:
                break
        if self.paths_checked and self.artifacts.is_dir():
            (self.artifacts / "desktop-output.json").write_text(json.dumps(self.logs), encoding="utf-8")
        if log := getattr(self, "cdp_log", None):
            log.close()
