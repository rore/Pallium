"""Focused tests for the qualification-only native gateway guards."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import base64
import socket
import socketserver
import subprocess
import threading
import types
import sys
import shutil
import tempfile

import pytest

from tests.fixtures.hermes_gateway_driver import (
    OwnedGateway,
    gateway_guard_witness,
    gateway_target,
    install_copied_runtime_guard,
)
from tests.fixtures.hermes_tui_driver import node_preload_source, python_guard_source


@pytest.mark.parametrize("value, expected", [
    ("ws://127.0.0.1:1/api/ws", ("127.0.0.1", 1)),
    ("ws://127.0.0.1:65535/api/ws", ("127.0.0.1", 65535)),
])
def test_gateway_target_accepts_only_literal_native_endpoint(value, expected):
    assert gateway_target(value) == expected


@pytest.mark.parametrize("value", [
    None, "", "ws://localhost:1234/api/ws", "ws://127.0.0.2:1234/api/ws",
    "http://127.0.0.1:1234/api/ws", "wss://127.0.0.1:1234/api/ws",
    "ws://user@127.0.0.1:1234/api/ws", "ws://127.0.0.1:1234/api/ws?x=1",
    "ws://127.0.0.1:1234/api/ws#fragment", "ws://127.0.0.1:1234/other",
    "ws://127.0.0.1:0/api/ws", "ws://127.0.0.1:65536/api/ws",
    "ws://127.0.0.1:01234/api/ws", "ws://[::1]:1234/api/ws",
])
def test_gateway_target_rejects_aliases_and_url_variants(value):
    with pytest.raises(AssertionError, match="unexpected native gateway endpoint"):
        gateway_target(value)


def _mock_installer_environment(tmp_path, monkeypatch, *, prefix_outside=False, base_same=False, active=False):
    import tests.fixtures.hermes_gateway_driver as gateway

    allowed_root = tmp_path / "qualification"
    allowed_root.mkdir()
    source = allowed_root / "source"
    (source / "ui-tui" / "scripts").mkdir(parents=True)
    prefix = (tmp_path / "outside-venv") if prefix_outside else (allowed_root / "venv")
    prefix.mkdir()
    python = prefix / "bin" / "python"
    python.parent.mkdir()
    python.write_text("synthetic executable marker", encoding="utf-8")
    (prefix / "pyvenv.cfg").write_text("synthetic venv marker", encoding="utf-8")
    site = prefix / "lib" / "python3.14" / "site-packages"
    site.mkdir(parents=True)
    base = prefix if base_same else (allowed_root / "base-python")
    base.mkdir(exist_ok=True)
    metadata = {"version": [3, 14], "prefix": str(prefix), "base": str(base), "site": str(site)}
    monkeypatch.setattr(gateway.subprocess, "run", lambda *args, **kwargs: types.SimpleNamespace(
        stdout=json.dumps(metadata)))
    consumers = [types.SimpleNamespace(info={"exe": str(python)})] if active else []
    monkeypatch.setitem(sys.modules, "psutil", types.SimpleNamespace(process_iter=lambda *_args: consumers))
    return allowed_root, source, prefix, python, site


@pytest.mark.parametrize("case", ["base-is-prefix", "prefix-outside-root", "active-consumer"])
def test_installer_refusals_do_not_create_sitecustomize(tmp_path, monkeypatch, case):
    paths = _mock_installer_environment(
        tmp_path, monkeypatch,
        base_same=case == "base-is-prefix",
        prefix_outside=case == "prefix-outside-root",
        active=case == "active-consumer",
    )
    allowed_root, source, _prefix, python, site = paths
    target = site / "sitecustomize.py"
    with pytest.raises(AssertionError):
        install_copied_runtime_guard(python, source, "synthetic guard bytes", allowed_root=allowed_root)
    assert not target.exists()


def test_installer_refuses_conflicting_existing_sitecustomize_without_changing_it(tmp_path, monkeypatch):
    allowed_root, source, _prefix, python, site = _mock_installer_environment(tmp_path, monkeypatch)
    target = site / "sitecustomize.py"
    original = b"preexisting owner content\n"
    target.write_bytes(original)
    with pytest.raises(AssertionError):
        install_copied_runtime_guard(python, source, "different guard content", allowed_root=allowed_root)
    assert target.read_bytes() == original


def test_installer_accepts_identical_existing_guard_without_rewriting(tmp_path, monkeypatch):
    allowed_root, source, _prefix, python, site = _mock_installer_environment(tmp_path, monkeypatch)
    target = site / "sitecustomize.py"
    payload = "synthetic guard bytes"
    target.write_text(payload, encoding="utf-8")
    before = target.stat().st_mtime_ns
    result = install_copied_runtime_guard(python, source, payload, allowed_root=allowed_root)
    assert result["action"] == "verified-identical"
    assert target.read_text(encoding="utf-8") == payload
    assert target.stat().st_mtime_ns == before


def test_gateway_guard_witness_matches_current_process_birth_and_installed_guard(tmp_path):
    path = tmp_path / "witness.jsonl"
    receipt = {"pid": 418, "owner_birthtime": 1234.5}
    guard = {"path": "/qualification/python/site-packages/sitecustomize.py", "sha256": "a" * 64}
    old = {"pid": 418, "birthtime": 1234.4, "path": guard["path"],
           "sha256": guard["sha256"], "socket_guard_active": True}
    current = {"pid": 418, "birthtime": 1234.5, "path": guard["path"],
               "sha256": guard["sha256"], "socket_guard_active": True}
    path.write_text(json.dumps(old) + "\n" + json.dumps(current) + "\n", encoding="utf-8")
    assert gateway_guard_witness(path, receipt, guard) == [current]


@pytest.mark.parametrize("change", [
    {"path": "/qualification/other/sitecustomize.py"},
    {"sha256": "b" * 64},
    {"socket_guard_active": False},
])
def test_gateway_guard_witness_rejects_bad_current_process_evidence(tmp_path, change):
    path = tmp_path / "witness.jsonl"
    receipt = {"pid": 418, "owner_birthtime": 1234.5}
    guard = {"path": "/qualification/python/site-packages/sitecustomize.py", "sha256": "a" * 64}
    current = {"pid": 418, "birthtime": 1234.5, "path": guard["path"],
               "sha256": guard["sha256"], "socket_guard_active": True}
    current.update(change)
    path.write_text(json.dumps(current) + "\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        gateway_guard_witness(path, receipt, guard)


def test_gateway_guard_witness_ignores_only_old_pid_birth_record(tmp_path):
    path = tmp_path / "witness.jsonl"
    receipt = {"pid": 418, "owner_birthtime": 1234.5}
    guard = {"path": "/qualification/python/site-packages/sitecustomize.py", "sha256": "a" * 64}
    old = {"pid": 418, "birthtime": 1234.4, "path": "/wrong", "sha256": "bad",
           "socket_guard_active": False}
    path.write_text(json.dumps(old) + "\n", encoding="utf-8")
    assert gateway_guard_witness(path, receipt, guard) == []


def test_native_peer_emits_exact_guard_witness_and_keeps_hook_audit_minimal(tmp_path, monkeypatch):
    from tests.fixtures import hermes_native_peer_plugin as peer

    peer_file = tmp_path / "peer_plugin.py"
    peer_file.write_text("# synthetic module identity\n", encoding="utf-8")
    guard_path = tmp_path / "sitecustomize.py"
    guard_path.write_text("# private synthetic guard bytes\n", encoding="utf-8")
    witness_path = tmp_path / "guard-witness.jsonl"
    monkeypatch.setattr(peer, "__file__", str(peer_file))
    monkeypatch.setenv("PALLIUM_TUI_GUARD_WITNESS", str(witness_path))
    guard = types.SimpleNamespace(__file__=str(guard_path), _connect=socket.socket.connect)
    monkeypatch.setitem(sys.modules, "sitecustomize", guard)

    class FakeProcess:
        def create_time(self):
            return 1234.5

    monkeypatch.setitem(sys.modules, "psutil", types.SimpleNamespace(Process=lambda: FakeProcess()))
    hooks = {}
    peer.register(types.SimpleNamespace(register_hook=lambda name, callback: hooks.setdefault(name, callback)))
    rows = [json.loads(line) for line in witness_path.read_text(encoding="utf-8").splitlines()]
    assert rows == [{"pid": os.getpid(), "birthtime": 1234.5, "path": str(guard_path.resolve()),
                     "sha256": hashlib.sha256(guard_path.read_bytes()).hexdigest(),
                     "socket_guard_active": True}]
    assert set(rows[0]) == {"pid", "birthtime", "path", "sha256", "socket_guard_active"}
    assert set(hooks) == {"post_llm_call"}
    hooks["post_llm_call"](session_id="session-x", turn_id="turn-y", content="private")
    audit = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8"))
    assert audit == {"session_id": "session-x", "turn_id": "turn-y"}


@pytest.mark.parametrize("shared_gateway", [0, 1, "true", None, {}])
def test_driver_rejects_non_boolean_shared_gateway_before_runtime_import(tmp_path, monkeypatch, shared_gateway):
    from tests.fixtures import hermes_tui_driver as driver

    spec = tmp_path / "driver-spec.json"
    spec.write_text(json.dumps({"home": str(tmp_path / "home"), "source": str(tmp_path / "source"),
                                "python": str(tmp_path / "python"), "shared_gateway": shared_gateway}),
                    encoding="utf-8")
    imported = []
    original_import = __import__

    def guard_import(name, *args, **kwargs):
        if name == "hermes_desktop_driver":
            imported.append(name)
            raise RuntimeError("runtime import must follow spec validation")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guard_import)
    with pytest.raises(AssertionError, match="shared_gateway must be a strict boolean"):
        driver.driver_main(spec)
    assert imported == []


def test_driver_rejects_unknown_surface_before_runtime_import(tmp_path, monkeypatch):
    from tests.fixtures import hermes_tui_driver as driver

    spec = tmp_path / "driver-spec.json"
    spec.write_text(json.dumps({"home": str(tmp_path / "home"), "source": str(tmp_path / "source"),
                                "python": str(tmp_path / "python"), "surface": "other"}),
                    encoding="utf-8")
    imported = []
    original_import = __import__

    def guard_import(name, *args, **kwargs):
        if name == "hermes_desktop_driver":
            imported.append(name)
            raise RuntimeError("runtime import must follow spec validation")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guard_import)
    with pytest.raises(AssertionError, match="unknown native UI surface"):
        driver.driver_main(spec)
    assert imported == []


@pytest.mark.parametrize("owner_variant", ["launcher", "base", "pythonw"])
def test_owned_gateway_records_only_live_child_identity_and_redacts_protocols(tmp_path, monkeypatch, owner_variant):
    import tests.fixtures.hermes_gateway_driver as gateway

    python = tmp_path / "python.exe"
    base = tmp_path / "base-python.exe"
    base.write_bytes(b"pinned python base")
    base_sha256 = hashlib.sha256(base.read_bytes()).hexdigest()
    home = tmp_path / "hermes-home"
    artifacts = tmp_path / "artifacts"
    home.mkdir()
    artifacts.mkdir()
    helper = _FakeProcess(51, 100.0, python)
    owner_exe = {"launcher": python, "base": base, "pythonw": python.with_name("pythonw.exe")}[owner_variant]
    owner = _FakeProcess(52, 101.0, owner_exe, parents=[helper])
    processes = {51: helper, 52: owner}

    class FakeTree:
        def __init__(self):
            self.psutil = types.SimpleNamespace(Process=lambda pid: processes[pid])
            self.recorded = []

        def record(self, process):
            self.recorded.append(process)

    receipt = {"url": "ws://127.0.0.1:48123/api/ws", "profile_id": "profile-a",
               "instance_id": "instance-b", "pid": 52, "start_time": 101,
               "hermes_home": str(home.resolve()), "code_sha": "c" * 40}
    fake_state = {}

    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.pid = 51
            self.stdout = _LineReader(json.dumps(receipt) + "\n", fake_state)
            self.stdin = _InputWriter(fake_state, receipt)

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(gateway.subprocess, "Popen", FakePopen)
    tree = FakeTree()
    instance = OwnedGateway(python, tmp_path, {"HERMES_HOME": str(home)}, artifacts, tree, "c" * 40,
                            python_base=base, python_base_sha256=base_sha256)
    fake_state["gateway"] = instance
    saved = json.loads((artifacts / "gateway-before.json").read_text(encoding="utf-8"))
    assert tree.recorded == [helper, owner]
    assert instance.owner_identity == (52, 101.0, str(owner_exe.resolve()))
    assert set(saved) == set(receipt) | {"owner_birthtime", "owner_exe", "helper_identity"}
    assert "protocols" not in saved and "ticket" not in saved
    instance.verify_and_release()
    after = json.loads((artifacts / "gateway-after.json").read_text(encoding="utf-8"))
    assert set(after) == set(saved)
    assert after["pid"] == receipt["pid"] and after["owner_birthtime"] == 101.0


@pytest.mark.parametrize("bad_owner", ["unrelated-parent", "reused-helper-birth", "wrong-executable"])
def test_owned_gateway_rejects_unproven_or_unexpected_owner_before_receipt_save(tmp_path, monkeypatch, bad_owner):
    import tests.fixtures.hermes_gateway_driver as gateway

    python = tmp_path / "python.exe"
    base = tmp_path / "base-python.exe"
    base.write_bytes(b"pinned python base")
    wrong = tmp_path / "other.exe"
    home = tmp_path / "hermes-home"
    artifacts = tmp_path / "artifacts"
    home.mkdir()
    artifacts.mkdir()
    helper = _FakeProcess(61, 200.0, python)
    if bad_owner == "wrong-executable":
        parent = helper
    elif bad_owner == "reused-helper-birth":
        parent = _FakeProcess(61, 201.0, python)
    else:
        parent = _FakeProcess(60, 199.0, wrong)
    owner_exe = wrong if bad_owner == "wrong-executable" else python
    owner = _FakeProcess(62, 201.0, owner_exe, parents=[parent])
    processes = {61: helper, 62: owner}

    class FakeTree:
        def __init__(self):
            self.psutil = types.SimpleNamespace(Process=lambda pid: processes[pid])
            self.recorded = []

        def record(self, process):
            self.recorded.append(process)

    receipt = {"url": "ws://127.0.0.1:48124/api/ws", "profile_id": "profile-a",
               "instance_id": "instance-b", "pid": 62, "start_time": 201,
               "hermes_home": str(home.resolve()), "code_sha": "d" * 40}

    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.pid = 61
            self.stdout = _LineReader(json.dumps(receipt) + "\n")
            self.stdin = _InputWriter()

    monkeypatch.setattr(gateway.subprocess, "Popen", FakePopen)
    tree = FakeTree()
    with pytest.raises(AssertionError):
        OwnedGateway(python, tmp_path, {"HERMES_HOME": str(home)}, artifacts, tree, "d" * 40,
                     python_base=base, python_base_sha256=hashlib.sha256(base.read_bytes()).hexdigest())
    assert tree.recorded == ([helper, owner] if bad_owner == "wrong-executable" else [helper])
    assert not (artifacts / "gateway-before.json").exists()


@pytest.mark.parametrize("case", ["wrong-path", "wrong-hash", "malformed-hash", "nonstr-hash", "directory", "missing",
                                  "relative", "parent-traversal", "file-alias", "ancestor-alias", "ancestor-junction"])
def test_owned_gateway_rejects_unpinned_base_before_spawn(tmp_path, monkeypatch, case):
    import tests.fixtures.hermes_gateway_driver as gateway

    base = tmp_path / "base-python.exe"
    base.write_bytes(b"pinned python base")
    digest = hashlib.sha256(base.read_bytes()).hexdigest()
    supplied, supplied_digest = base, digest
    if case == "wrong-path":
        supplied = tmp_path / "other-python.exe"
        supplied.write_bytes(b"different python base")
    elif case == "wrong-hash":
        supplied_digest = "0" * 64
    elif case == "malformed-hash":
        supplied_digest = "bad"
    elif case == "nonstr-hash":
        supplied_digest = None
    elif case == "directory":
        supplied = tmp_path / "python-dir"
        supplied.mkdir()
    elif case == "missing":
        supplied = tmp_path / "missing-python.exe"
    elif case == "relative":
        monkeypatch.chdir(tmp_path)
        supplied = Path("base-python.exe")
    elif case == "parent-traversal":
        (tmp_path / "nested").mkdir()
        supplied = tmp_path / "nested" / ".." / base.name

    if case in {"file-alias", "ancestor-alias"}:
        target = base if case == "file-alias" else tmp_path
        original_is_symlink = Path.is_symlink

        def report_alias(path):
            return path == target or original_is_symlink(path)

        monkeypatch.setattr(Path, "is_symlink", report_alias)

    if case == "ancestor-junction":
        original_is_junction = getattr(Path, "is_junction", lambda _path: False)
        monkeypatch.setattr(Path, "is_junction",
                            lambda path: path == tmp_path or original_is_junction(path), raising=False)

    def unexpected_spawn(*_args, **_kwargs):
        pytest.fail("gateway helper spawned before base Python validation")

    monkeypatch.setattr(gateway.subprocess, "Popen", unexpected_spawn)
    with pytest.raises(AssertionError):
        OwnedGateway(tmp_path / "venv-python.exe", tmp_path, {}, tmp_path, object(), "f" * 40,
                     python_base=supplied, python_base_sha256=supplied_digest)


def test_owned_gateway_rejects_helper_error_receipt_after_recording_helper(tmp_path, monkeypatch):
    import tests.fixtures.hermes_gateway_driver as gateway

    python = tmp_path / "python.exe"
    base = tmp_path / "base-python.exe"
    base.write_bytes(b"pinned python base")
    helper = _FakeProcess(71, 300.0, python)

    class FakeTree:
        def __init__(self):
            self.psutil = types.SimpleNamespace(Process=lambda _pid: helper)
            self.recorded = []

        def record(self, process):
            self.recorded.append(process)

    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.pid = 71
            self.stdout = _LineReader(json.dumps({"error": "native gateway qualification failed"}) + "\n")
            self.stdin = _InputWriter()

    monkeypatch.setattr(gateway.subprocess, "Popen", FakePopen)
    tree = FakeTree()
    with pytest.raises(AssertionError, match="native gateway qualification helper failed"):
        OwnedGateway(python, tmp_path, {"HERMES_HOME": str(tmp_path)}, tmp_path, tree, "e" * 40,
                     python_base=base, python_base_sha256=hashlib.sha256(base.read_bytes()).hexdigest())
    assert tree.recorded == [helper]


@pytest.mark.parametrize("phase,status,calls,returns,state,reason,should_wait,interrupt_wait", [
    ("bootstrap", "returned", 1, 1, "draining", None, True, True),
    ("bootstrap", "returned", 1, 1, "draining", None, True, False),
    ("imports", "returned", 1, 1, "draining", None, False, False),
    ("bootstrap", "none_or_unwind", 1, 0, "draining", None, False, False),
    ("bootstrap", "returned", 1, 1, "ready", None, False, False),
    ("bootstrap", "returned", 1, 1, "draining", "authorization", False, False),
    ("bootstrap", "returned", 2, 2, "draining", None, False, False),
])
def test_owned_gateway_error_waits_only_for_exact_draining_receipt(
        tmp_path, monkeypatch, phase, status, calls, returns, state, reason, should_wait, interrupt_wait):
    import queue
    import tests.fixtures.hermes_gateway_driver as gateway

    diagnostic = {
        "error": "native gateway qualification failed", "phase": phase, "exception_type": "RuntimeError",
        "frames": [{"file": "ui-tui/scripts/gateway_bootstrap.py", "function": "bootstrap", "line": 79}],
        "ensure": {"status": status, "calls": calls, "returns": returns,
                   "state": state, "reason_code": reason},
    }
    receiver = object.__new__(OwnedGateway)
    receiver.replies = queue.Queue()
    receiver.replies.put(diagnostic)
    receiver.artifacts = tmp_path
    waits = []
    persisted_at_wait = []

    def passive_wait(seconds):
        waits.append(seconds)
        receipt = tmp_path / "gateway-error.json"
        persisted_at_wait.append(receipt.exists() and json.loads(receipt.read_text(encoding="utf-8")) == diagnostic)
        if interrupt_wait:
            raise InterruptedError("passive wait interruption must not replace the fatal helper failure")

    monkeypatch.setattr(gateway.time, "sleep", passive_wait)
    with pytest.raises(AssertionError, match="native gateway qualification helper failed"):
        receiver.receive()
    assert waits == ([30] if should_wait else [])
    assert persisted_at_wait == ([True] if should_wait else [])
    assert json.loads((tmp_path / "gateway-error.json").read_text(encoding="utf-8")) == diagnostic


def test_owned_gateway_success_receipt_does_not_wait(tmp_path, monkeypatch):
    import queue
    import tests.fixtures.hermes_gateway_driver as gateway

    receipt = {
        "url": "ws://127.0.0.1:19341/api/ws", "profile_id": "profile",
        "instance_id": "instance", "pid": 41, "start_time": 1,
        "hermes_home": str(tmp_path), "code_sha": "e" * 40,
    }
    receiver = object.__new__(OwnedGateway)
    receiver.replies = queue.Queue()
    receiver.replies.put(receipt)
    receiver.artifacts = tmp_path
    waits = []
    monkeypatch.setattr(gateway.time, "sleep", lambda seconds: waits.append(seconds))

    assert receiver.receive() == receipt
    assert waits == []
    assert not (tmp_path / "gateway-error.json").exists()


class _FakeProcess:
    def __init__(self, pid, birth, exe, parents=()):
        self.pid, self.birth, self.executable, self._parents = pid, birth, exe, parents

    def create_time(self):
        return self.birth

    def exe(self):
        return str(self.executable)

    def parents(self):
        return self._parents


class _LineReader:
    def __init__(self, line, state=None):
        self.lines = [line]
        self.state = state if state is not None else {}
        self.block_after_first = state is not None
        self.release = threading.Event()
        self.finished = False

    def readline(self, _limit=-1):
        if self.lines:
            return self.lines.pop(0)
        if not self.block_after_first:
            return ""
        self.release.wait(timeout=5)
        self.finished = True
        return ""

    def close(self):
        self.release.set()


class _InputWriter:
    def __init__(self, state=None, receipt=None):
        self.state, self.receipt = state if state is not None else {}, receipt
        self.commands = []

    def write(self, _value):
        self.commands.append(_value)
        if _value == "verify\n":
            self.state["gateway"].replies.put(self.receipt)
            self.state["gateway"].proc.stdout.release.set()
        return None

    def flush(self):
        return None

    def close(self):
        return None


def _runtime_paths(*extra_paths: Path):
    node = os.environ.get("HERMES_NODE")
    python = os.environ.get("HERMES_E2E_PYTHON")
    if not node or not python:
        pytest.skip("explicit HERMES_NODE and HERMES_E2E_PYTHON qualification runtimes are required")
    node_path, python_path = Path(node), Path(python)
    assert node_path.is_absolute() and python_path.is_absolute(), "qualification runtime paths must be absolute"
    assert node_path.is_file() and python_path.is_file(), "explicit qualification runtime is unavailable"
    if os.name == "nt":
        from tests.fixtures.hermes_desktop_driver import require_runner_gate

        require_runner_gate(dict(os.environ), node_path, python_path, *extra_paths)
    elif os.name == "posix":
        from tests.fixtures.hermes_linux_guard import require_contained_paths, require_linux_qualification

        require_linux_qualification(dict(os.environ))
        require_contained_paths(node_path, python_path, *extra_paths)
    else:
        pytest.skip("unsupported qualification host")
    return node_path, python_path


def _private_env(tmp_path: Path, node: Path, python: Path, gateway_port: int = 19341) -> dict[str, str]:
    env = {
        "PATH": os.pathsep.join((str(node.parent), str(python.parent),
                                  str(Path(os.environ["SYSTEMROOT"]) / "System32") if os.name == "nt" else "/usr/bin")),
        "HOME": str(tmp_path), "TMPDIR": str(tmp_path), "TEMP": str(tmp_path),
        "HERMES_NODE": str(node), "HERMES_E2E_PYTHON": str(python),
        "PALLIUM_TUI_ALLOWED_ENDPOINTS": json.dumps([["127.0.0.1", gateway_port]]),
        "PALLIUM_TUI_GATEWAY_WS": f"ws://127.0.0.1:{gateway_port}/api/ws",
        "NO_COLOR": "1", "LANG": "C.UTF-8",
    }
    if os.name == "nt":
        env.update({"USERPROFILE": str(tmp_path), "HOMEDRIVE": tmp_path.drive,
                    "HOMEPATH": str(tmp_path)[len(tmp_path.drive):],
                    "APPDATA": str(tmp_path / "AppData" / "Roaming"),
                    "LOCALAPPDATA": str(tmp_path / "AppData" / "Local"),
                    "XDG_CONFIG_HOME": str(tmp_path / ".config"),
                    "XDG_DATA_HOME": str(tmp_path / ".local" / "share"),
                    "XDG_CACHE_HOME": str(tmp_path / ".cache"),
                    "XDG_STATE_HOME": str(tmp_path / ".local" / "state")})
        for key in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "OS"):
            if key in os.environ:
                env[key] = os.environ[key]
    else:
        for key in ("PALLIUM_LINUX_QUALIFICATION_ROOT", "PALLIUM_LINUX_QUALIFICATION_MANIFEST"):
            env[key] = os.environ[key]
    return env


def test_python_guard_allows_only_numeric_loopback_ephemeral_resolution(tmp_path):
    node, python = _runtime_paths(tmp_path)
    env = _private_env(tmp_path, node, python, gateway_port=1)
    script = python_guard_source() + r'''
import json, socket

resolved = socket.getaddrinfo("127.0.0.1", 0, type=socket.SOCK_STREAM)
assert resolved and all(row[4][1] == 0 for row in resolved)
family, kind, proto, _, address = resolved[0]
listener = socket.socket(family, kind, proto)
listener.bind(address)
listener.listen(1)
port = listener.getsockname()[1]
assert type(port) is int and port not in (0, 1)

class Host(str): pass
class Port(int): pass

for host, requested_port in (
        ("192.0.2.1", 0), ("example.invalid", 0), ("例.invalid", 0), ("localhost", 0), ("127.0.0.1", "0"),
        ("127.0.0.1", False), ("127.0.0.1", 2), (Host("127.0.0.1"), 0),
        ("127.0.0.1", Port(0))):
    try:
        socket.getaddrinfo(host, requested_port, type=socket.SOCK_STREAM)
    except PermissionError:
        pass
    else:
        raise AssertionError("nonliteral ephemeral resolver request was allowed")

for method in ("connect", "connect_ex"):
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        getattr(client, method)(("127.0.0.1", port))
    except PermissionError:
        pass
    else:
        raise AssertionError("unallowlisted ephemeral connect was allowed")
    finally:
        client.close()
listener.close()
print(json.dumps({"ephemeral_port": port, "resolver_denials": 9, "connect_denials": 2}))
'''
    result = subprocess.run([str(python), "-I", "-S", "-c", script], env=env, cwd=tmp_path,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["ephemeral_port"] != 1
    assert observed["resolver_denials"] == 9 and observed["connect_denials"] == 2


def test_node_preload_allows_one_native_websocket_and_blocks_url_protocol_and_other_network(tmp_path):
    node, python = _runtime_paths(tmp_path)
    preload = tmp_path / "preload.cjs"
    preload.write_text(node_preload_source(), encoding="utf-8")
    observed = {}

    class Handshake(socketserver.StreamRequestHandler):
        def handle(self):
            request = self.rfile.readline().decode("ascii").strip()
            headers = {}
            while line := self.rfile.readline():
                text = line.decode("ascii").strip()
                if not text:
                    break
                name, value = text.split(":", 1)
                headers[name.lower()] = value.strip()
            observed["path"] = request.split(" ")[1]
            protocols = headers.get("sec-websocket-protocol", "").split(", ")
            observed["native_protocols"] = (len(protocols) == 2 and protocols[0] == "hermes-gateway-v1"
                                            and protocols[1].startswith("hermes-gateway-ticket."))
            key = headers["sec-websocket-key"]
            accept = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
            self.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                              "Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept +
                              "\r\nSec-WebSocket-Protocol: hermes-gateway-v1\r\n\r\n").encode("ascii"))
            # Read the client's masked close frame and return a normal server close frame.
            header = self.rfile.read(2)
            if len(header) == 2:
                length = header[1] & 0x7f
                if header[1] & 0x80:
                    mask = self.rfile.read(4)
                    payload = self.rfile.read(length)
                    if len(mask) == 4 and len(payload) == length:
                        self.wfile.write(b"\x88\x02\x03\xe8")

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = False
        daemon_threads = True

    server = Server(("127.0.0.1", 0), Handshake)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        port = server.server_address[1]
        script = r'''const net = require("node:net");
const guardedConnect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function(...args) {
 const normalized = Array.isArray(args[0]) ? args[0] : args;
 const first = normalized[0];
 const fields = {};
 if (first && typeof first === "object") {
  for (const key of ["host","hostname","port","family","localAddress","localPort","path","socketPath","autoSelectFamily"])
   if (first[key] === null || ["string","number","boolean"].includes(typeof first[key])) fields[key] = first[key];
 }
 console.error(JSON.stringify({kind:"connect",types:normalized.map(value=>typeof value),
  fields,lookup_type:typeof first?.lookup}));
 return guardedConnect.apply(this,args);
};
const protocols = ["hermes-gateway-v1", "hermes-gateway-ticket.syntheticQualificationToken"];
const ws = new WebSocket(process.env.PALLIUM_TUI_GATEWAY_WS, protocols);
ws.addEventListener("open", () => { ws.close(); console.log("opened"); });
ws.addEventListener("error", event => {
 console.error(JSON.stringify({kind:"websocket-error",name:event.error?.name,code:event.error?.code,
  cause_name:event.error?.cause?.name,cause_code:event.error?.cause?.code}));
 process.exitCode = 2;
});
'''
        env = _private_env(tmp_path, node, python, port)
        env["NODE_OPTIONS"] = f'--require="{preload.as_posix()}"'
        result = subprocess.run([str(node), "-e", script], env=env, cwd=tmp_path,
                                capture_output=True, text=True, timeout=15)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
    (tmp_path / "websocket-control.json").write_text(json.dumps({
        "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
        "server_observation": observed}, indent=2), encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "opened"
    assert observed == {"path": "/api/ws", "native_protocols": True}
    assert "syntheticQualificationToken" not in result.stdout + result.stderr

    negative = r'''const check = (fn) => { try { fn(); return false; } catch (_) { return true; } };
const port = Number(new URL(process.env.PALLIUM_TUI_GATEWAY_WS).port);
const urls = [`ws://127.0.0.1:${port + 1}/api/ws`, `ws://127.0.0.1:${port}/other`,
 `wss://127.0.0.1:${port}/api/ws`, `ws://localhost:${port}/api/ws`,
 `ws://127.0.0.1:${port}/api/ws?x=1`, `ws://127.0.0.1:${port}/api/ws#x`,
 `ws://user@127.0.0.1:${port}/api/ws`];
const urlDenied = urls.every(url => check(() => new WebSocket(url,
 ["hermes-gateway-v1", "hermes-gateway-ticket.syntheticQualificationToken"])));
const protocolDenied = [[], ["hermes-gateway-v1"], ["bad", "hermes-gateway-ticket.syntheticQualificationToken"],
 ["hermes-gateway-v1", "bad"]].every(protocols => check(() => new WebSocket(process.env.PALLIUM_TUI_GATEWAY_WS, protocols)));
const socketDenied = check(() => require("node:net").connect({host:"127.0.0.1", port:port + 1}))
 && check(() => require("node:net").connect({host:"127.0.0.1", port:port + 1,localAddress:null}));
const sourceBindingDenied = ["127.0.0.1","0.0.0.0","::1","",0,false,{},[]].every(localAddress =>
 check(() => require("node:net").connect({host:"127.0.0.1",port,localAddress})));
const staticDenied = [() => require("node:net").createServer().listen(0),
 () => require("node:tls").connect(1), () => require("node:dgram").createSocket("udp4").bind(0),
 () => require("node:http").get(`http://127.0.0.1:${port}/`),
 () => require("node:dns").lookup("example.test")].every(check);
const websocketStatic = globalThis.WebSocket.CONNECTING === 0 && globalThis.WebSocket.OPEN === 1
 && globalThis.WebSocket.CLOSING === 2 && globalThis.WebSocket.CLOSED === 3;
globalThis.fetch(`http://127.0.0.1:${port}/`).then(() => process.exit(5), () => {
 if (!(urlDenied && protocolDenied && socketDenied && sourceBindingDenied && staticDenied && websocketStatic)) process.exit(4);
 console.log("denied");
});
'''
    denied = subprocess.run([str(node), "-e", negative], env=env, cwd=tmp_path,
                            capture_output=True, text=True, timeout=15)
    assert denied.returncode == 0, denied.stderr
    assert denied.stdout.strip() == "denied"
    assert "syntheticQualificationToken" not in denied.stderr

    default_deny_env = dict(env)
    default_deny_env.pop("PALLIUM_TUI_GATEWAY_WS")
    default_deny = subprocess.run([str(node), "-e", 'try { new WebSocket("ws://127.0.0.1:1/api/ws", ["hermes-gateway-v1", "hermes-gateway-ticket.synthetic"]); process.exit(5); } catch (_) { console.log("blocked"); }'],
                                  env=default_deny_env, cwd=tmp_path, capture_output=True,
                                  text=True, timeout=10)
    assert default_deny.returncode == 0 and default_deny.stdout.strip() == "blocked"
    malformed_env = dict(env)
    malformed_env["PALLIUM_TUI_GATEWAY_WS"] = "ws://localhost:19341/api/ws"
    malformed = subprocess.run([str(node), "-e", "console.log('must-not-start')"], env=malformed_env,
                               cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert malformed.returncode == 78
    assert "must-not-start" not in malformed.stdout


def test_python_control_socket_guard_requires_exact_private_unix_path(tmp_path):
    _node, python = _runtime_paths()
    if os.name == "nt":
        pytest.skip("AF_UNIX control path qualification is Linux-only")
    from tests.fixtures.hermes_linux_guard import require_contained_paths

    require_contained_paths(tmp_path)
    qualification_tmp = Path(os.environ["PALLIUM_LINUX_QUALIFICATION_ROOT"]) / "tmp"
    control_root = Path(tempfile.mkdtemp(prefix="uds-", dir=qualification_tmp))
    try:
        require_contained_paths(control_root)
    except BaseException:
        assert control_root.parent.resolve() == qualification_tmp.resolve()
        assert control_root.name.startswith("uds-")
        shutil.rmtree(control_root)
        raise
    parent = control_root / "p"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    exact = parent / "control.sock"
    wrong = parent / "wrong.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(exact))
    exact.chmod(0o600)
    listener.listen(1)
    accepted = []

    def accept_one():
        connection, _ = listener.accept()
        accepted.append(True)
        connection.close()

    thread = threading.Thread(target=accept_one, daemon=True)
    thread.start()
    script = python_guard_source() + r'''
import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(sys.argv[1])
s.close()
try:
    socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).connect(sys.argv[2])
except PermissionError:
    print("denied")
else:
    raise SystemExit(9)
'''
    env = _private_env(tmp_path, Path(os.environ["HERMES_NODE"]), python)
    env["PALLIUM_TUI_ALLOWED_CONTROL_PATHS"] = json.dumps([str(exact)])
    try:
        result = subprocess.run([str(python), "-I", "-S", "-c", script, str(exact), str(wrong)],
                                env=env, cwd=tmp_path, capture_output=True, text=True, timeout=10)
    except BaseException:
        listener.close()
        thread.join(timeout=2)
        assert control_root.parent.resolve() == qualification_tmp.resolve()
        assert control_root.name.startswith("uds-")
        shutil.rmtree(control_root)
        raise
    try:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "denied"
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert accepted == [True]

        unsafe_script = python_guard_source() + r'''
import socket, sys
try:
    socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).connect(sys.argv[1])
except PermissionError:
    print("mode-denied")
else:
    raise SystemExit(8)
'''
        parent.chmod(0o750)
        unsafe = subprocess.run([str(python), "-I", "-S", "-c", unsafe_script, str(exact)],
                                env=env, cwd=tmp_path, capture_output=True, text=True, timeout=10)
        assert unsafe.returncode == 0 and unsafe.stdout.strip() == "mode-denied"

        parent.chmod(0o700)
        exact.chmod(0o660)
        unsafe_socket = subprocess.run([str(python), "-I", "-S", "-c", unsafe_script, str(exact)],
                                       env=env, cwd=tmp_path, capture_output=True, text=True, timeout=10)
        assert unsafe_socket.returncode == 0 and unsafe_socket.stdout.strip() == "mode-denied"

        exact.chmod(0o600)
        link = parent / "control-alias.sock"
        link.symlink_to(exact)
        alias_script = python_guard_source() + r'''
import socket, sys
try:
    socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).connect(sys.argv[1])
except PermissionError:
    print("alias-denied")
else:
    raise SystemExit(7)
'''
        alias = subprocess.run([str(python), "-I", "-S", "-c", alias_script, str(link)],
                               env=env, cwd=tmp_path, capture_output=True, text=True, timeout=10)
        assert alias.returncode == 0 and alias.stdout.strip() == "alias-denied"

        symlink_env = dict(env)
        symlink_env["PALLIUM_TUI_ALLOWED_CONTROL_PATHS"] = json.dumps([str(link)])
        refused = subprocess.run([str(python), "-I", "-S", "-c", python_guard_source()],
                                 env=symlink_env, cwd=tmp_path, capture_output=True, timeout=10)
        assert refused.returncode == 78
    finally:
        listener.close()
        assert control_root.parent.resolve() == qualification_tmp.resolve()
        assert control_root.name.startswith("uds-")
        shutil.rmtree(control_root)


@pytest.mark.parametrize("spoofed_exception,draining", [(False, False), (True, False), (False, True)])
def test_real_helper_retains_partial_bootstrap_child_for_final_tree_cleanup(
        tmp_path, monkeypatch, spoofed_exception, draining):
    import queue
    import uuid
    from tests.fixtures.hermes_gateway_driver import HELPER
    from tests.fixtures.hermes_tui_driver import OwnedTree

    node, python = _runtime_paths(tmp_path)
    import psutil

    source = tmp_path / "synthetic-source"
    scripts = source / "ui-tui" / "scripts"
    scripts.mkdir(parents=True)
    native_package = source / "hermes_cli"
    native_package.mkdir()
    (native_package / "__init__.py").write_text("", encoding="utf-8")
    witness = tmp_path / "spawned-child.json"
    drain_marker = tmp_path / "draining-child-alive.marker"
    child_code = (
        "import time; from pathlib import Path; time.sleep(.2); "
        f"Path({str(drain_marker)!r}).write_text('started'); time.sleep(120)"
        if draining else "import time; time.sleep(120)"
    )
    native_state = "draining" if draining else "ready"
    native_reason = "None" if draining else repr("authorization")
    marker = "qualification-partial-" + uuid.uuid4().hex
    secrets = (
        "synthetic-bootstrap-stdout-must-never-escape",
        "synthetic-bootstrap-stderr-must-never-escape",
        "synthetic-exception-message-must-never-escape",
        "SyntheticPrivateExceptionName",
        "decoy-private-state",
        "decoy-private-reason",
    )
    native_runtime = (
        "import json,os,subprocess,sys,psutil\nfrom pathlib import Path\n"
        "class GatewayDiscovery:\n"
        "    def __init__(self,state,reason_code): self.state=state; self.reason_code=reason_code\n"
        "def ensure_gateway_runtime(*args,**kwargs):\n"
        "    options={'start_new_session':True} if os.name!='nt' else {}\n"
        f"    child_code={child_code!r}\n"
        f"    child=subprocess.Popen([sys.executable,'-c',child_code,{marker!r}],**options)\n"
        "    process=psutil.Process(child.pid)\n"
        f"    Path({str(witness)!r}).write_text(json.dumps({{'pid':child.pid,'birthtime':process.create_time(),'exe':process.exe()}}))\n"
        f"    return GatewayDiscovery({native_state!r},{native_reason})\n"
    )
    (native_package / "gateway_runtime.py").write_text(native_runtime, encoding="utf-8")
    (native_package / "decoy.py").write_text(
        "class GatewayDiscovery:\n"
        "    state='decoy-private-state'\n"
        "    reason_code='decoy-private-reason'\n"
        "def ensure_gateway_runtime(): return GatewayDiscovery()\n", encoding="utf-8")
    bootstrap = (
        "import json,os,subprocess,sys,psutil\nfrom pathlib import Path\n"
        f"sys.path.insert(0,{str(source)!r})\n"
        "from hermes_cli.gateway_runtime import ensure_gateway_runtime\n"
        "from hermes_cli.decoy import ensure_gateway_runtime as decoy_ensure\n"
        f"Error = type({secrets[3]!r}, (RuntimeError,), {{'__module__': 'builtins'}}) if {spoofed_exception!r} else RuntimeError\n"
        "def bootstrap(start):\n"
        "    assert start is True\n"
        "    assert ensure_gateway_runtime().state == 'ready'\n"
        "    decoy_ensure()\n"
        f"    print({secrets[0]!r})\n"
        f"    print({secrets[1]!r},file=sys.stderr)\n"
        f"    raise Error({secrets[2]!r})\n"
    )
    (scripts / "gateway_bootstrap.py").write_text(bootstrap, encoding="utf-8")
    env = _private_env(tmp_path, node, python)
    env["HERMES_HOME"] = str(tmp_path / "hermes-profile")
    Path(env["HERMES_HOME"]).mkdir()
    # The test must prove final refresh, without help from periodic ancestry polling.
    monkeypatch.setattr(OwnedTree, "_monitor", lambda self: self.stopped.wait())
    proc = subprocess.Popen([str(python), "-c", HELPER, str(source), "f" * 40], env=env,
                            cwd=tmp_path, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8")
    tree = None
    line = ""
    replies = queue.Queue()
    reader = threading.Thread(target=lambda: replies.put(proc.stdout.readline()), daemon=True)
    reader.start()
    try:
        tree = OwnedTree(proc.pid, python, ledger=tmp_path / "owned-ledger.json")
        line = replies.get(timeout=10)
        diagnostic = json.loads(line)
        receiver = object.__new__(OwnedGateway)
        receiver.replies = queue.Queue()
        receiver.replies.put(diagnostic)
        receiver.artifacts = tmp_path
        with pytest.raises(AssertionError, match="native gateway qualification helper failed"):
            receiver.receive()
        saved_diagnostic = json.loads((tmp_path / "gateway-error.json").read_text(encoding="utf-8"))
        assert saved_diagnostic == diagnostic
        assert diagnostic["error"] == "native gateway qualification failed"
        assert diagnostic["phase"] == "bootstrap"
        assert diagnostic["exception_type"] == ("Exception" if spoofed_exception else "AssertionError" if draining else "RuntimeError")
        assert diagnostic["ensure"] == {
            "status": "returned", "calls": 1, "returns": 1,
            "state": "draining" if draining else "ready",
            "reason_code": None if draining else "authorization",
        }
        assert any(frame["file"] == "ui-tui/scripts/gateway_bootstrap.py"
                   for frame in diagnostic["frames"])
        rendered = line + json.dumps(saved_diagnostic)
        assert all(secret not in rendered for secret in secrets)
        assert proc.poll() is None, "failed helper exited before final ownership refresh"
        child = json.loads(witness.read_text(encoding="utf-8"))
        process = psutil.Process(child["pid"])
        assert process.create_time() == child["birthtime"]
        assert Path(process.exe()).resolve() == Path(child["exe"]).resolve()
        assert any(parent.pid == proc.pid for parent in process.parents())
        if draining:
            assert drain_marker.read_text(encoding="utf-8") == "started"
            assert process.is_running() and proc.poll() is None
        if os.name != "nt":
            assert os.getsid(process.pid) == process.pid
        assert process.pid not in tree.identities, "periodic polling masked the final-refresh contract"
        tree.close()
        assert process.pid in tree.identities, "final cleanup never recorded the partial-start child"
        saved = json.loads((tmp_path / "owned-ledger.json").read_text(encoding="utf-8"))
        assert any(row["pid"] == child["pid"] and row["birthtime"] == child["birthtime"] for row in saved)
        for pid, (birth, executable) in tree.identities.items():
            try:
                current = psutil.Process(pid)
                assert current.create_time() != birth or current.status() == psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                pass
    finally:
        if tree is not None:
            # A regressed helper may exit early; retain the synthetic child's own creation witness for cleanup.
            if witness.exists():
                child = json.loads(witness.read_text(encoding="utf-8"))
                try:
                    current = psutil.Process(child["pid"])
                    if (current.create_time() == child["birthtime"]
                            and Path(current.exe()).resolve() == Path(child["exe"]).resolve()
                            and current.cmdline()[-1] == marker):
                        tree.record(current)
                except psutil.NoSuchProcess:
                    pass
            tree.close()
        elif proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
        reader.join(timeout=2)
        assert not reader.is_alive()
        remaining_out = proc.stdout.read()
        stderr = proc.stderr.read()
        proc.stdin.close()
        proc.stdout.close()
        proc.stderr.close()
        assert not remaining_out and not stderr


@pytest.mark.parametrize("value_case", [
    "unknown_state", "subclass_state", "unknown_reason", "subclass_reason",
])
def test_real_helper_normalizes_unrecognized_gateway_state_and_reason(tmp_path, value_case):
    from tests.fixtures.hermes_gateway_driver import HELPER

    node, python = _runtime_paths(tmp_path)
    source = tmp_path / "synthetic-source"
    scripts = source / "ui-tui" / "scripts"
    scripts.mkdir(parents=True)
    native_package = source / "hermes_cli"
    native_package.mkdir()
    (native_package / "__init__.py").write_text("", encoding="utf-8")
    state = "'ready'"
    reason = "'authorization'"
    if value_case == "unknown_state":
        state = "'private-state-value'"
    elif value_case == "subclass_state":
        state = "PrivateValue('ready')"
    elif value_case == "unknown_reason":
        reason = "'private-reason-value'"
    else:
        reason = "PrivateValue('authorization')"
    native_runtime = (
        "class PrivateValue(str): pass\n"
        "class GatewayDiscovery:\n"
        "    def __init__(self,state,reason_code): self.state=state; self.reason_code=reason_code\n"
        "def ensure_gateway_runtime(*args,**kwargs):\n"
        f"    return GatewayDiscovery({state},{reason})\n"
    )
    (native_package / "gateway_runtime.py").write_text(native_runtime, encoding="utf-8")
    (native_package / "decoy.py").write_text(
        "class GatewayDiscovery:\n"
        "    state='decoy-private-state'\n"
        "    reason_code='decoy-private-reason'\n"
        "def ensure_gateway_runtime(): return GatewayDiscovery()\n", encoding="utf-8")
    (scripts / "gateway_bootstrap.py").write_text(
        f"import sys\nsys.path.insert(0,{str(source)!r})\n"
        "from hermes_cli.gateway_runtime import ensure_gateway_runtime\n"
        "from hermes_cli.decoy import ensure_gateway_runtime as decoy_ensure\n"
        "def bootstrap(start):\n"
        "    assert start is True\n"
        "    ensure_gateway_runtime()\n"
        "    decoy_ensure()\n"
        "    raise RuntimeError('private-exception-message')\n", encoding="utf-8")
    env = _private_env(tmp_path, node, python)
    env["HERMES_HOME"] = str(tmp_path / "hermes-profile")
    Path(env["HERMES_HOME"]).mkdir()
    proc = subprocess.Popen([str(python), "-c", HELPER, str(source), "f" * 40], env=env,
                            cwd=tmp_path, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        line, stderr = proc.communicate("close\n", timeout=10)
        diagnostic = json.loads(line)
        assert diagnostic["ensure"] == {
            "status": "returned", "calls": 1, "returns": 1,
            "state": "unrecognized" if "state" in value_case else "ready",
            "reason_code": "unrecognized" if "reason" in value_case else "authorization",
        }
        assert all(secret not in line for secret in (
            "private-state-value", "private-reason-value", "decoy-private-state",
            "decoy-private-reason", "private-exception-message"))
        assert proc.returncode == 78 and stderr == ""
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)


@pytest.mark.parametrize("scenario", [
    "return", "raise", "preexisting_profiler", "none_return", "two_call",
])
def test_gateway_helper_profiler_lifecycle_uses_only_extracted_functions(tmp_path, scenario):
    import ast
    from tests.fixtures.hermes_gateway_driver import HELPER

    parsed = ast.parse(HELPER)
    selected = []
    found_functions = set()
    found_assignments = set()
    function_names = {"observe_ensure", "ensure_gateway_bootstrap"}
    assignment_names = {"ensure_observation", "ensure_filename"}
    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in function_names:
            selected.append(node)
            found_functions.add(node.name)
        elif isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            selected_names = names & assignment_names
            if selected_names:
                selected.append(node)
                found_assignments.update(selected_names)
    assert found_functions == function_names
    assert found_assignments == assignment_names

    source = (tmp_path / "synthetic-source").resolve()
    target = source / "hermes_cli" / "gateway_runtime.py"
    module_name = f"_gateway_profiler_lifecycle_{id(tmp_path)}"
    previous_module = sys.modules.get(module_name)
    native = types.ModuleType(module_name)
    native.behavior = scenario
    native.calls = []
    native_source = (
        "class GatewayDiscovery:\n"
        "    def __init__(self,state,reason_code): self.state=state; self.reason_code=reason_code\n"
        "def ensure_gateway_runtime():\n"
        "    calls.append(True)\n"
        "    if behavior == 'raise': raise RuntimeError('private')\n"
        "    if behavior == 'none_return': return None\n"
        "    return GatewayDiscovery('ready','authorization')\n"
    )
    exec(compile(native_source, str(target), "exec"), native.__dict__)
    namespace = {"sys": sys, "types": types, "Path": Path, "source": source}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "<selected-helper-functions>", "exec"), namespace)
    bootstrap_calls = []

    def bootstrap(start):
        bootstrap_calls.append(start)
        assert start is True
        result = native.ensure_gateway_runtime()
        if scenario == "two_call":
            result = native.ensure_gateway_runtime()
        return result

    original_profiler = sys.getprofile()
    existing_profiler = lambda frame, event, arg: None
    try:
        sys.setprofile(None)
        sys.modules[module_name] = native
        if scenario == "preexisting_profiler":
            sys.setprofile(existing_profiler)
            with pytest.raises(AssertionError, match="already has a profiler"):
                namespace["ensure_gateway_bootstrap"]({"bootstrap": bootstrap})
            assert sys.getprofile() is existing_profiler
            assert bootstrap_calls == [] and native.calls == []
            assert namespace["ensure_observation"]["status"] == "not_reached"
        elif scenario == "raise":
            with pytest.raises(RuntimeError, match="private"):
                namespace["ensure_gateway_bootstrap"]({"bootstrap": bootstrap})
            assert sys.getprofile() is None
            assert namespace["ensure_observation"] == {
                "status": "none_or_unwind", "calls": 1, "returns": 1,
                "state": None, "reason_code": None,
            }
        else:
            result = namespace["ensure_gateway_bootstrap"]({"bootstrap": bootstrap})
            assert sys.getprofile() is None
            if scenario == "none_return":
                assert result is None
                assert namespace["ensure_observation"] == {
                    "status": "none_or_unwind", "calls": 1, "returns": 1,
                    "state": None, "reason_code": None,
                }
            elif scenario == "two_call":
                assert namespace["ensure_observation"] == {
                    "status": "multiple_calls", "calls": 2, "returns": 2,
                    "state": "ready", "reason_code": "authorization",
                }
            else:
                assert namespace["ensure_observation"] == {
                    "status": "returned", "calls": 1, "returns": 1,
                    "state": "ready", "reason_code": "authorization",
                }
        if scenario != "preexisting_profiler":
            assert bootstrap_calls == [True]
        assert len(native.calls) == (2 if scenario == "two_call" else int(scenario != "preexisting_profiler"))
    finally:
        sys.setprofile(original_profiler)
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module


@pytest.mark.parametrize("malformation", [
    "unknown_field", "absolute_path", "traversal", "custom_type", "invalid_line", "too_many_frames",
    "unknown_ensure_field", "invalid_ensure_count", "invalid_ensure_state", "invalid_ensure_status",
])
def test_gateway_helper_error_diagnostic_rejects_malformed_payload_without_persistence(tmp_path, monkeypatch, malformation):
    import queue
    import tests.fixtures.hermes_gateway_driver as gateway

    diagnostic = {
        "error": "native gateway qualification failed",
        "phase": "bootstrap",
        "exception_type": "RuntimeError",
        "frames": [{"file": "ui-tui/scripts/gateway_bootstrap.py", "function": "bootstrap", "line": 12}],
        "ensure": {"status": "returned", "calls": 1, "returns": 1,
                   "state": "draining", "reason_code": None},
    }
    if malformation == "unknown_field":
        diagnostic["ticket"] = "must-not-persist"
    elif malformation == "absolute_path":
        diagnostic["frames"][0]["file"] = "/private/source/bootstrap.py"
    elif malformation == "traversal":
        diagnostic["frames"][0]["file"] = "../private/bootstrap.py"
    elif malformation == "custom_type":
        diagnostic["exception_type"] = "SecretCustomError"
    elif malformation == "invalid_line":
        diagnostic["frames"][0]["line"] = True
    elif malformation == "too_many_frames":
        diagnostic["frames"] *= 9
    elif malformation == "unknown_ensure_field":
        diagnostic["ensure"]["ticket"] = "must-not-persist"
    elif malformation == "invalid_ensure_count":
        diagnostic["ensure"]["calls"] = True
    elif malformation == "invalid_ensure_state":
        diagnostic["ensure"]["state"] = "private-state-value"
    elif malformation == "invalid_ensure_status":
        diagnostic["ensure"]["status"] = "private-status-value"

    receiver = object.__new__(OwnedGateway)
    receiver.replies = queue.Queue()
    receiver.replies.put(diagnostic)
    receiver.artifacts = tmp_path
    waits = []
    monkeypatch.setattr(gateway.time, "sleep", lambda seconds: waits.append(seconds))
    with pytest.raises(AssertionError, match="native gateway qualification helper failed"):
        receiver.receive()
    assert waits == []
    assert not (tmp_path / "gateway-error.json").exists()


def test_installed_sdk2_guard_survives_source_pythonpath_and_fails_closed(tmp_path):
    node, python = _runtime_paths(tmp_path)
    guard_raw, expected_sha = os.environ.get("PALLIUM_TUI_GUARD_PATH"), os.environ.get("PALLIUM_TUI_GUARD_SHA256")
    if not guard_raw or not expected_sha:
        pytest.skip("the dedicated copied SDK2 runtime guard must be installed by the qualification owner")
    guard_path = Path(guard_raw)
    assert guard_path.is_absolute() and guard_path.is_file(), "installed qualification guard path is unavailable"
    source_raw = os.environ.get("HERMES_E2E_SOURCE")
    if not source_raw:
        pytest.skip("explicit released Hermes source fixture is required")
    source = Path(source_raw)
    assert source.is_dir(), "explicit released Hermes source fixture is unavailable"
    if os.name == "nt":
        from tests.fixtures.hermes_desktop_driver import require_runner_gate

        require_runner_gate(dict(os.environ), guard_path, source, tmp_path)
    else:
        from tests.fixtures.hermes_linux_guard import require_contained_paths

        require_contained_paths(guard_path, source, tmp_path)
    assert hashlib.sha256(guard_path.read_bytes()).hexdigest() == expected_sha

    env = _private_env(tmp_path, node, python)
    env.update({
        "PYTHONPATH": str(source),  # Mirrors the native TUI's source-root overwrite.
        "PALLIUM_TUI_GUARD_PATH": str(guard_path),
        "PALLIUM_TUI_GUARD_SHA256": expected_sha,
    })
    probe = "import json,sitecustomize,socket; print(json.dumps({'file':sitecustomize.__file__,'active':socket.socket.connect is sitecustomize._connect}))"
    result = subprocess.run([str(python), "-c", probe], env=env, cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    proof = json.loads(result.stdout)
    assert Path(proof["file"]).resolve() == guard_path.resolve()
    assert proof["active"] is True

    for malformed in (None, "not-json", "[]"):
        bad_env = dict(env)
        if malformed is None:
            bad_env.pop("PALLIUM_TUI_ALLOWED_ENDPOINTS", None)
        else:
            bad_env["PALLIUM_TUI_ALLOWED_ENDPOINTS"] = malformed
        failed = subprocess.run([str(python), "-c", "print('must-not-start')"], env=bad_env,
                                cwd=tmp_path, capture_output=True, text=True, timeout=10)
        assert failed.returncode == 78
        assert "must-not-start" not in failed.stdout

