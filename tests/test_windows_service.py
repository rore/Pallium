"""Mocked safety regressions for the managed Windows lifecycle."""
import ctypes
import importlib
import os
import socket
import subprocess
from contextlib import contextmanager
from unittest.mock import patch

import pytest


class NativeCallDenied(AssertionError):
    pass


native_calls = []


def _deny(*args, **kwargs):
    native_calls.append("denied")
    raise NativeCallDenied("unexpected native or host operation")


@contextmanager
def guard_native_calls():
    with patch.object(ctypes, "WinDLL", _deny, create=True), \
            patch.object(subprocess, "Popen", _deny), \
            patch.object(subprocess, "run", _deny), \
            patch.object(socket, "create_connection", _deny), \
            patch.object(socket.socket, "connect", _deny), \
            patch.object(socket.socket, "connect_ex", _deny):
        yield


# Guard before importing any application module or constructing a backend.
with guard_native_calls():
    service = importlib.import_module("app.windows_service")
assert not native_calls
_WindowsAPI = service.WindowsAPI


@pytest.fixture(autouse=True)
def deny_unconfigured_backends(monkeypatch):
    native_calls.clear()
    monkeypatch.setattr(service, "_NATIVE", None)
    monkeypatch.setattr(service, "WindowsAPI", _deny)
    monkeypatch.setattr(service.ctypes, "WinDLL", _deny, raising=False)
    monkeypatch.setattr(service.subprocess, "Popen", _deny)
    monkeypatch.setattr(service.subprocess, "run", _deny)
    monkeypatch.setattr(service.socket if hasattr(service, "socket") else socket,
                        "create_connection", _deny)
    monkeypatch.setattr(socket.socket, "connect", _deny)
    monkeypatch.setattr(socket.socket, "connect_ex", _deny)


@pytest.fixture(autouse=True)
def guard_selected_mock(request, tmp_path):
    """Imported by other selected test modules; existing nonselected tests stay intact."""
    if not request.node.name.startswith("test_cooperative_windows_"):
        yield
        return
    environment = {
        "HOME": str(tmp_path / "profile"), "USERPROFILE": str(tmp_path / "profile"),
        "APPDATA": str(tmp_path / "profile" / "AppData"),
        "PALLIUM_HOME": str(tmp_path / "private-home"),
        "PALLIUM_CONFIG_FILE": str(tmp_path / "config.toml"),
        "PALLIUM_ENV_FILE": str(tmp_path / "private.env"),
        "PALLIUM_STORAGE_BACKEND": "memory", service.GENERATION_ENV: "",
    }
    with guard_native_calls(), patch.object(service, "WindowsAPI", _deny), \
            patch.object(service, "_NATIVE", None), patch.dict(os.environ, environment):
        yield


class FakeAPI:
    """Only explicitly configured native behaviors are allowed."""
    def __init__(self):
        self.calls = []
        self.processes = {}
        self.identities = {}
        self.locked = False
        self.active = 0
        self.total = 0

    def __getattr__(self, name):
        return _deny

    @contextmanager
    def mutex(self, name, seconds):
        self.calls.append(("mutex-enter", name))
        assert not self.locked
        self.locked = True
        try:
            yield
        finally:
            self.locked = False
            self.calls.append(("mutex-exit", name))

    def event(self, name, *, create=False):
        self.calls.append(("event", name, create))
        return name

    def signal(self, event):
        self.calls.append(("signal", event))

    def spawn(self, command, **kwargs):
        self.calls.append(("spawn", command))
        return "process"

    def resume(self, process):
        self.calls.append(("resume", process))

    def close(self, handle):
        self.calls.append(("close", handle))

    def process(self, pid):
        self.calls.append(("process", pid))
        return self.processes[pid]

    def identity(self, handle, pid):
        self.calls.append(("identity", pid))
        return self.identities[pid]

    def job(self, description):
        self.calls.append(("job", description))
        return "job"

    def signaled(self, handle, seconds=0):
        self.calls.append(("signaled", handle))
        return True

    def exit_code(self, handle):
        return 0

    def accounting(self, job):
        self.calls.append(("accounting", job, self.locked))
        return self.total, self.active


class ImmediateDeadline:
    def remaining(self):
        return 5

    def read(self, operation):
        return operation()


def test_cooperative_windows_deadline_remaining_is_bounded_by_monotonic_budget():
    now = [10.0]
    deadline = service.Deadline(2.5, clock=lambda: now[0])
    assert deadline.remaining() == 2.5
    now[0] = 11.25
    assert deadline.remaining() == 1.25
    now[0] = 12.5
    with pytest.raises(service.Unknown, match="deadline"):
        deadline.remaining()


def test_cooperative_windows_stop_channel_spawn_closes_admission_before_launch():
    api = FakeAPI()
    channel = service.StopChannel("generation", api=api)
    attempts = []
    with pytest.raises(service.Unknown, match="admission"):
        channel.spawn(["child"], attempts=attempts, stop=lambda: True)
    assert attempts == []
    assert not any(call[0] == "spawn" for call in api.calls)


def test_cooperative_windows_stop_channel_retains_raced_attempt_without_resuming():
    api = FakeAPI()
    channel = service.StopChannel("generation", api=api)
    attempts = []
    states = iter((False, True))
    with pytest.raises(service.Unknown, match="retained"):
        channel.spawn(["child"], attempts=attempts, stop=lambda: next(states))
    assert attempts == ["process"]
    assert not any(call[0] == "resume" for call in api.calls)


def test_cooperative_windows_stop_request_signals_inside_spawn_mutex():
    api = FakeAPI()
    channel = service.StopChannel("generation", api=api)
    channel.request()
    assert [call[0] for call in api.calls[-3:]] == ["mutex-enter", "signal", "mutex-exit"]


def test_cooperative_windows_pin_checks_observer_launcher_identity_and_job(tmp_path):
    api = FakeAPI()
    manifest = {"home": str(tmp_path)}
    generation = "a" * 32
    description = service._names(tmp_path, generation)
    record = {
        "version": 1, "generation": generation, "description": description,
        "manifest": manifest,
        "observer": {"pid": 11, "created": 1, "image": "observer.exe"},
        "launcher": {"pid": 12, "created": 2, "image": "wscript.exe"},
    }
    api.processes = {11: "observer-handle", 12: "launcher-handle"}
    api.identities = {11: record["observer"], 12: record["launcher"]}
    record["ancestry"] = [record["observer"], record["launcher"]]
    handles = service._pin(tmp_path, record, manifest, ImmediateDeadline(), api)
    assert handles == ["observer-handle", "launcher-handle", "job"]
    assert [call[1] for call in api.calls if call[0] == "identity"] == [11, 12]


def test_cooperative_windows_pin_rejects_reused_process_identity(tmp_path):
    api = FakeAPI()
    manifest = {"home": str(tmp_path)}
    generation = "a" * 32
    record = {
        "version": 1, "generation": generation,
        "description": service._names(tmp_path, generation), "manifest": manifest,
        "observer": {"pid": 11, "created": 1, "image": "observer.exe"},
        "launcher": {"pid": 12, "created": 2, "image": "wscript.exe"},
    }
    api.processes = {11: "observer-handle", 12: "launcher-handle"}
    api.identities = {11: record["observer"], 12: {**record["launcher"], "created": 99}}
    record["ancestry"] = [record["observer"], record["launcher"]]
    with pytest.raises(service.Unknown, match="identity changed"):
        service._pin(tmp_path, record, manifest, ImmediateDeadline(), api)
    assert ("close", "observer-handle") in api.calls
    assert ("close", "launcher-handle") in api.calls


def _settlement_fixture(tmp_path, outcome="clean", exits=None, total=1, active=0):
    api = FakeAPI()
    api.total, api.active = total, active
    manifest = {"home": str(tmp_path)}
    record = {
        "version": 1, "generation": "b" * 32,
        "description": service._names(tmp_path, "b" * 32),
        "config": "config", "manifest": manifest,
        "observer": {"pid": 21, "created": 1, "image": "observer.exe"},
        "launcher": {"pid": 22, "created": 2, "image": "wscript.exe"},
        "outcome": outcome,
    }
    api.processes = {21: "observer-handle", 22: "launcher-handle"}
    api.identities = {21: record["observer"], 22: record["launcher"]}
    record["ancestry"] = [record["observer"], record["launcher"]]
    terminal = {**record, "empty": True, "total": total,
                "outcome": outcome, "exits": exits if exits is not None else {"31": 0}}
    (tmp_path / "run").mkdir(exist_ok=True)
    (tmp_path / "run" / "windows-generation.json").write_text(
        __import__("json").dumps(terminal), encoding="utf-8")
    return api, manifest, record, terminal


def test_cooperative_windows_missing_native_fake_fails_before_host_calls():
    # native() must stop at the sentinel WindowsAPI constructor.
    with pytest.raises(NativeCallDenied):
        service.native()
    assert native_calls == ["denied"]


@pytest.mark.parametrize(("outcome", "exits"), [
    ("clean", {"31": 0}),
    ("failed", {"31": 2}),
], ids=["clean-zero-exit", "failed-nonzero-exit"])
def test_cooperative_windows_settle_accepts_only_reported_terminal_outcomes(tmp_path, monkeypatch, outcome, exits):
    api, manifest, record, terminal = _settlement_fixture(tmp_path, outcome, exits)
    monkeypatch.setattr(service, "_task_state", lambda *_: "Ready")
    pinned = ["observer-handle", "launcher-handle", "job"]
    assert service._settle(tmp_path, record, manifest, ImmediateDeadline(), api, pinned=pinned) == terminal
    assert all(not call[-1] for call in api.calls if call[0] == "accounting")


@pytest.mark.parametrize(("outcome", "exits", "total", "active"), [
    ("unknown", {"31": 0}, 1, 0),
    ("clean", {}, 0, 0),
    ("clean", {"31": 0}, 2, 0),
    ("clean", {"31": 0}, 1, 1),
    ("clean", {"31": 5}, 1, 0),
], ids=["unknown", "empty-results", "total-mismatch", "active-process", "clean-nonzero-exit"])
def test_cooperative_windows_settle_refuses_unknown_incomplete_or_inconsistent_receipts(
        tmp_path, monkeypatch, outcome, exits, total, active):
    api, manifest, record, _ = _settlement_fixture(tmp_path, outcome, exits, total, active)
    monkeypatch.setattr(service, "_task_state", lambda *_: "Ready")
    with pytest.raises(service.Unknown):
        service._settle(tmp_path, record, manifest, ImmediateDeadline(), api,
                        pinned=["observer-handle", "launcher-handle", "job"])


def test_cooperative_windows_settle_running_generation_releases_spawn_mutex_before_drain(tmp_path, monkeypatch):
    api, manifest, record, terminal = _settlement_fixture(tmp_path, "clean")
    record["outcome"] = "running"
    monkeypatch.setattr(service, "_task_state", lambda *_: "Ready")
    result = service._settle(tmp_path, record, manifest, ImmediateDeadline(), api,
                             pinned=["observer-handle", "launcher-handle", "job"])
    assert result == terminal
    assert [call[0] for call in api.calls].index("mutex-exit") < [call[0] for call in api.calls].index("signaled")


def test_cooperative_windows_control_retries_one_failed_before_launch(tmp_path, monkeypatch):
    class Launched:
        handle = "created-launcher-handle"

        def poll(self):
            return None

    class RetryAPI(FakeAPI):
        def spawn(self, command, **kwargs):
            self.calls.append(("spawn", command))
            if sum(call[0] == "spawn" for call in self.calls) == 1:
                raise service.FailedBeforeLaunch("no process created")
            return Launched()

    api = RetryAPI()
    home = tmp_path
    run = home / "run"
    run.mkdir()
    path = run / "windows-generation.json"
    path.write_text("{}", encoding="utf-8")
    manifest = {"cwd": str(home), "vbs": str(home / "launcher.vbs"), "port": 21987}
    old = {"outcome": "clean", "config": "config"}
    current = {"outcome": "running", "config": "config"}
    reads = iter((old, current))
    monkeypatch.setattr(service, "Deadline", lambda _: ImmediateDeadline())
    monkeypatch.setattr(service, "_manifest", lambda _: manifest)
    monkeypatch.setattr(service, "_existing_store", lambda _: None)
    monkeypatch.setattr(service, "_config_identity", lambda *_: "config")
    monkeypatch.setattr(service, "_task_state", lambda *_: "Ready")
    monkeypatch.setattr(service, "_json", lambda _: next(reads))
    monkeypatch.setattr(service, "_settle", lambda *_args, **_kwargs: old)
    monkeypatch.setattr(service, "_pin", lambda *_args: ["observer", "launcher", "job"])
    monkeypatch.setattr(api, "private_home", lambda _: None)
    monkeypatch.setattr(api, "exit_code", lambda _: None, raising=False)
    assert service.control(home, "start", api=api, ready=lambda *_: True) == "recovered"
    assert sum(call[0] == "spawn" for call in api.calls) == 2
    assert sum(call[0] == "resume" for call in api.calls) == 1


@pytest.mark.parametrize("shape", ["direct", "redirector", "reused", "foreign", "non-python", "cycle", "depth", "query-error"],
                         ids=["direct", "redirector", "reused", "foreign", "non-python", "cycle", "depth", "query-error"])
def test_cooperative_windows_exact_own_ancestry_is_bounded_and_retained(monkeypatch, shape):
    from types import SimpleNamespace
    parents = {100: 99, 99: 98, 98: 0}
    images = {100: "C:/Python/python.exe", 99: "C:/private/python.exe", 98: "C:/Windows/wscript.exe"}
    times = {100: 30, 99: 20, 98: 10}
    if shape == "direct":
        parents[100] = 98
    elif shape == "reused":
        times[99] = 40
    elif shape == "non-python":
        images[99] = "C:/Windows/cmd.exe"
    elif shape == "cycle":
        parents[99] = 100
    elif shape == "depth":
        parents = {pid: pid + 1 for pid in range(100, 118)}
        images = {pid: "C:/Python/python.exe" for pid in parents}
        times = {pid: 200 - pid for pid in parents}
    opened, closed, dlls = [], [], []
    def open_process(rights, inherit, pid):
        assert rights == 0x100400 and inherit is False
        opened.append(pid)
        return pid
    def query(handle, information, basic, size, returned):
        assert information == 0
        basic[4], basic[5] = handle, parents[handle]
        return -1 if shape == "query-error" else 0
    def dll(name):
        assert name == "ntdll"
        dlls.append(name)
        return SimpleNamespace(NtQueryInformationProcess=query)
    receiver = SimpleNamespace(
        k=SimpleNamespace(OpenProcess=open_process), check=lambda value: value,
        identity=lambda handle, pid: {"pid": pid, "created": times[pid], "image": images[pid]},
        sid="same-user", user_sid=lambda handle: "other-user" if shape == "foreign" and handle == 99 else "same-user",
        exit_code=lambda handle: None, close=closed.append,
    )
    monkeypatch.setattr(service.os, "getpid", lambda: 100)
    monkeypatch.setattr(service.ctypes, "WinDLL", dll)
    if shape in {"direct", "redirector"}:
        handle, identity, retained, ancestry = _WindowsAPI.launcher(receiver)
        assert handle == 98 and identity["image"].endswith("wscript.exe")
        assert retained == opened and closed == []
        assert [item["pid"] for item in ancestry] == opened
    else:
        with pytest.raises(service.Unknown):
            _WindowsAPI.launcher(receiver)
        assert closed == opened
    assert len(opened) <= 16 and dlls == ["ntdll"]
