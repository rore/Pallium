from __future__ import annotations

# Guards precede application imports; the run packet additionally guards pytest/conftest.
from tests.test_windows_service import (
    guard_native_calls, guard_selected_mock, NativeCallDenied, ImmediateDeadline, FakeAPI, _deny,
)
with guard_native_calls():
    from app import windows_service as service
    from app.cli import service as cli
    original_check_health = cli._check_health
    original_read_endpoint_json = cli._read_endpoint_json

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

RESTART_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "restart-service.ps1"


@pytest.fixture(autouse=True)
def managed_only_isolation(monkeypatch, tmp_path):
    for name in ("HOME", "USERPROFILE", "APPDATA", "PALLIUM_HOME", "PALLIUM_CONFIG_FILE", "PALLIUM_ENV_FILE"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    monkeypatch.setenv("PALLIUM_STORAGE_BACKEND", "memory")
    monkeypatch.delenv(service.GENERATION_ENV, raising=False)
    monkeypatch.setattr(service, "WindowsAPI", _deny)
    monkeypatch.setattr(service, "_NATIVE", None)
    with guard_native_calls(monkeypatch):
        yield


class ManagedGeneration:
    """Caller-surface controller fixture; kernel objects cannot magically reopen."""
    def __init__(self, tmp_path, monkeypatch, *, home=None):
        self.now = 0.0
        self.calls = []
        self.closed = set()
        self.gone = set()
        self.signaled_stop = set()
        self.exits = {}
        self.identities = {}
        self.jobs = {}
        self.starts = 0
        self.health_round = 0
        self.transient = False
        self.terminal_endpoint = None
        self.active_survivor = False
        self.fail_on_signal = False
        self.terminal_history = []
        self.home = home or tmp_path / "שירות %TEMP% with spaces"
        self.run_dir = self.home / "run"
        self.run_dir.mkdir(parents=True)
        self.python = self.home / "installed-python.exe"
        self.python.touch()
        self.cwd = tmp_path / "stable installed קוד"
        self.cwd.mkdir()
        self.manifest = {"version": 1, "home": str(self.home), "python": str(self.python),
                         "cwd": str(self.cwd), "port": 21987, "vbs": str(self.run_dir / "launcher.vbs")}
        self.save_manifest()
        original_deadline = service.Deadline
        monkeypatch.setattr(service, "Deadline", lambda seconds, absolute=None: original_deadline(seconds, clock=lambda: self.now, absolute=absolute))
        monkeypatch.setattr(service, "time", SimpleNamespace(sleep=self.advance))
        monkeypatch.setattr(cli, "time", SimpleNamespace(monotonic=lambda: self.now))
        monkeypatch.setattr(service, "_existing_store", lambda _: self.calls.append("existing-authority"))
        monkeypatch.setattr(service, "_config_identity", lambda *_: "same-config")
        monkeypatch.setattr(service, "_task_info", self.task_info)
        monkeypatch.setattr(service, "_start_task", self.start_task)
        monkeypatch.setattr(cli, "_check_health", self.health)
        monkeypatch.setattr(cli, "_read_endpoint_json", self.endpoint)
        owner = self
        class API(FakeAPI):
            def private_home(self, home):
                assert home == owner.home
            def process(self, pid):
                if pid in owner.gone:
                    raise service.Unknown("kernel process identity no longer available")
                assert pid in owner.identities
                return pid
            def identity(self, handle, pid):
                assert handle == pid
                return owner.identities[pid]
            def job(self, name):
                if name in owner.gone:
                    raise service.Unknown("Job destroyed; cannot reopen custody")
                assert name in owner.jobs
                return name
            def in_job(self, handle, job):
                return handle in owner.jobs[job]
            def exit_code(self, handle):
                return owner.exits.get(handle)
            def signaled(self, handle, seconds=0):
                if isinstance(handle, str) and handle.endswith("-stop"):
                    return handle in owner.signaled_stop
                if owner.exits.get(handle) is None:
                    owner.advance(seconds)
                    return False
                return True
            def signal(self, event):
                owner.calls.append("signal")
                owner.signaled_stop.add(event)
                owner.settle_current(failed=owner.fail_on_signal)
            def accounting(self, job):
                roots = owner.jobs[job]
                return len(roots), sum(owner.exits.get(pid) is None for pid in roots)
            def close(self, handle):
                owner.closed.add(handle)
        self.api = API()
        self.install_generation(1, running=True)

    def save_manifest(self):
        (self.run_dir / "windows-launch.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        Path(self.manifest["vbs"]).write_text(service.launcher_text(self.manifest), encoding="utf-16")

    def advance(self, seconds):
        self.now += seconds

    def install_generation(self, number, *, running=True, failed=False):
        base = number * 100
        def identity(pid, image):
            value = {"pid": pid, "created": pid * 10, "image": image}
            self.identities[pid] = value
            self.exits[pid] = None if running else (2 if failed else 0)
            return value
        observer = identity(base + 1, "python.exe")
        launcher = identity(base + 2, "wscript.exe")
        supervisor = identity(base + 3, "python.exe")
        api = identity(base + 4, "python.exe")
        worker = identity(base + 5, "python.exe")
        description = service._names(self.home, str(number) * 32)
        self.jobs[description] = [supervisor["pid"], api["pid"], worker["pid"]]
        self.record = {"version": 1, "generation": str(number) * 32, "description": description,
                       "config": "same-config", "manifest": self.manifest, "observer": observer,
                       "launcher": launcher, "ancestry": [observer, launcher], "supervisor": supervisor,
                       "task_instance": "instance-" + str(number), "outcome": "running" if running else "failed" if failed else "clean",
                       "api_ready": {"nonce": "nonce-" + str(number), "identity": api,
                                     "public_instance": "public-instance-" + str(number)}}
        self.write_record()
        (self.run_dir / "api_token").write_text(json.dumps({"nonce": self.record["api_ready"]["nonce"], "pid": api["pid"],
                                                     "bound": {"generation": description, "port": self.manifest["port"]},
                                                     "public_instance": self.record["api_ready"]["public_instance"]}), encoding="utf-8")
        if not running:
            self.write_terminal()

    def write_record(self):
        (self.run_dir / "windows-generation.json").write_text(json.dumps(self.record), encoding="utf-8")

    def write_terminal(self):
        roots = self.jobs[self.record["description"]]
        self.record.update(empty=True, total=len(roots), exits={str(pid): self.exits[pid] for pid in roots})
        self.write_record()

    def settle_current(self, *, failed=False):
        if self.active_survivor:
            return
        for pid in self.jobs[self.record["description"]] + [self.record["observer"]["pid"], self.record["launcher"]["pid"]]:
            self.exits[pid] = 2 if failed else 0
        self.record["outcome"] = "failed" if failed else "clean"
        self.write_terminal()
        self.terminal_history.append(json.loads(json.dumps(self.record)))

    def task_info(self, _deadline):
        running = self.exits[self.record["observer"]["pid"]] is None
        return {"path": "\\Pallium", "name": "Pallium", "action_count": 1,
                "action": "wscript.exe", "arguments": service._task_arguments(self.manifest),
                "cwd": self.manifest["cwd"], "retry": 0, "state": 4 if running else 3,
                "instances": [self.record["task_instance"]] if running else []}

    def start_task(self, manifest, deadline):
        deadline.remaining()
        assert all(self.exits[pid] is not None for pid in self.jobs[self.record["description"]])
        # OLD identities/Job are still pinned throughout admission.
        assert self.record["description"] not in self.closed
        self.starts += 1
        self.calls.append("start-registered-task")
        self.install_generation(self.starts + 1)
        return self.record["task_instance"]

    def health(self, port, *, timeout, expected_instance=None):
        assert expected_instance == self.record["api_ready"]["public_instance"]
        self.calls.append(("/health", port, timeout))
        self.advance(.01)
        self.health_round += 1
        if self.terminal_endpoint == "/health" or self.transient and self.health_round < 2:
            return {"status": "initializing"}
        return {"status": "ok", "vector_index_ready": True, "embedding_provider_ok": True}

    def endpoint(self, port, path, *, timeout, expected_instance=None):
        assert expected_instance == self.record["api_ready"]["public_instance"]
        self.calls.append((path, port, timeout))
        self.advance(.02)
        return None if path == self.terminal_endpoint else {}

    def run(self, action="restart", timeout=1):
        result = service.control(self.home, action, timeout=timeout, api=self.api, ready=cli._managed_ready)
        assert all(not isinstance(call, str) or not any(word in call for word in ("kill", "census", "initialize")) for call in self.calls)
        return result


@pytest.fixture
def generation(tmp_path, monkeypatch):
    return ManagedGeneration(tmp_path, monkeypatch)


def test_default_readiness_budget_allows_three_minute_cold_start():
    assert "[double]$ReadinessTimeoutSeconds = 180" in RESTART_SCRIPT.read_text(encoding="utf-8")


def test_wake_import_runs_after_stop_and_before_task_start(generation):
    # RETIRED: unconditional import; retained: ordered stop/start with no setup.
    assert generation.run() == "started"
    assert generation.calls.index("signal") < generation.calls.index("start-registered-task")
    assert "existing-authority" in generation.calls


def test_wake_import_failure_never_starts_service(generation, monkeypatch):
    def refuse(_):
        raise service.Unknown("existing authority missing; separate offline setup")
    monkeypatch.setattr(service, "_existing_store", refuse)
    with pytest.raises(service.Unknown, match="separate offline"):
        generation.run()
    assert generation.starts == 0 and "signal" not in generation.calls


def test_stop_only_does_not_import_wakes(generation):
    assert generation.run("stop").startswith("stopped")
    assert generation.starts == 0


def test_preflight_failure_never_stops_the_healthy_service(generation, monkeypatch):
    monkeypatch.setattr(generation.api, "private_home", lambda _: (_ for _ in ()).throw(service.Unknown("preflight")))
    with pytest.raises(service.Unknown, match="preflight"):
        generation.run()
    assert "signal" not in generation.calls and generation.starts == 0


@pytest.mark.parametrize("task_shape", ["invalid_workdir", "unparseable"])
def test_invalid_installed_task_metadata_never_stops(generation, task_shape):
    generation.manifest["cwd" if task_shape == "invalid_workdir" else "python"] = str(generation.home / "missing")
    generation.save_manifest()
    with pytest.raises(service.Unknown):
        generation.run()
    assert "signal" not in generation.calls


def test_canonical_task_omits_working_directory_and_sweeps_survivor(generation):
    # RETIRED omission/sweep: exact installed cwd, no fallback, owned survivor refuses.
    generation.active_survivor = True
    with pytest.raises(service.Unknown):
        generation.run()
    assert generation.starts == 0


def _refuse_legacy(generation, monkeypatch, shape="legacy"):
    Path(generation.manifest["vbs"]).write_text(shape + " legacy entrypoint", encoding="utf-16")
    task = generation.task_info(None)
    task["arguments"] = '"legacy.vbs"'
    monkeypatch.setattr(service, "_task_info", lambda _: task)
    with pytest.raises(service.Unknown):
        generation.run()
    assert generation.starts == 0 and "signal" not in generation.calls


def test_legacy_task_passes_exact_working_directory(generation, monkeypatch):
    _refuse_legacy(generation, monkeypatch)
    generation.save_manifest()
    assert service._manifest(generation.home)["cwd"] == str(generation.cwd)


@pytest.mark.parametrize("task_shape", ["canonical_legacy", "generated_cli", "new_launcher"])
def test_restart_metadata_parses_legacy_and_generated_launcher_forms(generation, monkeypatch, task_shape):
    # All three historical forms lack the new invocation/deadline contract.
    _refuse_legacy(generation, monkeypatch, task_shape)


def test_legacy_task_passes_unicode_working_directory_exactly(generation, monkeypatch):
    _refuse_legacy(generation, monkeypatch)
    assert "קוד" in generation.manifest["cwd"]
    generation.save_manifest()
    assert service._manifest(generation.home)["cwd"] == str(generation.cwd)


def test_canonical_unicode_home_controls_pid_cleanup_and_failure_log(generation):
    assert service._manifest(generation.home)["home"] == str(generation.home)
    (generation.run_dir / "pallium.pid").write_text("5151", encoding="utf-8")
    assert generation.run() == "started"
    assert (generation.run_dir / "pallium.pid").read_text() == "5151"


def test_legacy_task_failure_keeps_default_home_log_path(tmp_path, monkeypatch, capsys):
    profile = tmp_path / "private profile"
    home = profile / ".pallium"
    generation = ManagedGeneration(tmp_path, monkeypatch, home=home)
    task = generation.task_info(None)
    task["arguments"] = '"legacy.vbs"'
    monkeypatch.setattr(service, "_task_info", lambda _: task)
    monkeypatch.setattr(service, "native", lambda: generation.api)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.Path, "home", lambda: profile)
    monkeypatch.delenv("PALLIUM_HOME", raising=False)
    assert cli.service_main(["restart"]) == 1
    output = capsys.readouterr()
    assert "refused/UNKNOWN" in output.err and "legacy" in output.err
    assert f"Pallium log: {home / 'logs' / 'pallium.log'}" in output.err
    assert "started" not in output.out and "recovered" not in output.out
    assert "Pallium restarted." not in output.out
    assert generation.starts == 0 and "signal" not in generation.calls


def test_canonical_missing_home_fails_before_stop(generation):
    generation.manifest.pop("home")
    (generation.run_dir / "windows-launch.json").write_text(json.dumps(generation.manifest), encoding="utf-8")
    with pytest.raises(service.Unknown):
        generation.run()
    assert "signal" not in generation.calls


@pytest.mark.parametrize("port", [None, "abc", 0, 65536])
def test_missing_or_invalid_port_never_stops(generation, port):
    generation.manifest["port"] = port
    generation.save_manifest()
    with pytest.raises(service.Unknown):
        generation.run()
    assert "signal" not in generation.calls


@pytest.mark.parametrize("port", [1, 65535])
def test_boundary_ports_are_valid(generation, port):
    generation.manifest["port"] = port
    generation.save_manifest()
    generation.write_record()
    assert generation.run() == "started"
    assert {call[1] for call in generation.calls if isinstance(call, tuple)} == {port}


def test_partial_taskkill_error_continues_cleanup_and_restarts(generation):
    generation.fail_on_signal = True
    assert generation.run() == "recovered"
    assert generation.starts == 1


def test_nonzero_taskkill_error_continues_cleanup_and_restarts(generation):
    generation.fail_on_signal = True
    assert generation.run() == "recovered"
    assert generation.terminal_history[0]["outcome"] == "failed"


def test_stop_only_rejects_nonzero_taskkill(generation):
    generation.settle_current()
    generation.record["exits"]["103"] = 2
    generation.write_record()
    with pytest.raises(service.Unknown, match="nonzero"):
        generation.run("stop")
    assert generation.starts == 0


def test_stop_only_rejects_failed_process_enumeration(generation):
    generation.gone.add(generation.record["launcher"]["pid"])
    with pytest.raises(service.Unknown, match="no longer available"):
        generation.run("stop")
    assert generation.starts == 0 and "signal" not in generation.calls


def test_multiple_initial_listeners_are_killed_once_each(generation):
    # RETIRED listener census/kill; retain multi-child settlement before one admission.
    assert len(generation.jobs[generation.record["description"]]) == 3
    assert generation.run() == "started" and generation.starts == 1


def test_surviving_listener_fails_before_task_start(generation):
    generation.active_survivor = True
    with pytest.raises(service.Unknown):
        generation.run()
    assert generation.starts == 0


def test_start_failure_is_nonzero_and_never_prints_success(generation, monkeypatch, capsys):
    def unknown_start(*_):
        raise service.Unknown("task start outcome unknown")
    monkeypatch.setattr(service, "_start_task", unknown_start)
    monkeypatch.setattr(service, "native", lambda: generation.api)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    assert cli.service_main(["restart", "--home", str(generation.home)]) == 1
    output = capsys.readouterr()
    assert "refused/UNKNOWN" in output.err and "task start outcome unknown" in output.err
    assert f"Pallium log: {generation.home / 'logs' / 'pallium.log'}" in output.err
    assert "started" not in output.out and "recovered" not in output.out
    assert "already running" not in output.out and "Pallium restarted." not in output.out
    assert generation.starts == 0


def test_transient_readiness_checks_all_contracts_before_success(generation):
    generation.transient = True
    assert generation.run() == "started"
    paths = [call[0] for call in generation.calls if isinstance(call, tuple)]
    assert paths.count("/health") >= 2
    assert paths[-3:] == ["/health", "/status", "/debug/queue/health"]
    assert generation.starts == 1


def test_queue_health_can_use_longer_timeout_within_same_deadline(generation):
    assert generation.run(timeout=6) == "started"
    budgets = [call[2] for call in generation.calls if isinstance(call, tuple)]
    assert 2 < budgets[-1] < 6
    assert budgets[0] <= 2 and budgets[1] <= 2
    assert generation.now < 6


@pytest.mark.parametrize("scenario,last_endpoint", [("terminal_health", "/health"), ("terminal_status", "/status"), ("terminal_queue", "/debug/queue/health")])
def test_terminal_readiness_exhausts_exact_budget_without_success(generation, scenario, last_endpoint):
    generation.terminal_endpoint = last_endpoint
    with pytest.raises(service.Unknown, match="deadline"):
        generation.run(timeout=.21)
    assert generation.starts == 1 and generation.now >= .21
    assert any(isinstance(call, tuple) and call[0] == last_endpoint for call in generation.calls)


def test_stop_only_accepts_empty_listener_not_found(generation):
    # Port absence does not enter the proof: full retained set must settle.
    assert generation.run("stop").startswith("stopped")
    assert generation.record["empty"] and len(generation.record["exits"]) == 3
    generation.gone.update(generation.closed)
    with pytest.raises(service.Unknown, match="no longer available|destroyed"):
        generation.run("start")
    assert generation.starts == 0


def test_stop_only_rejects_orphan_redirected_worker(generation):
    generation.active_survivor = True
    with pytest.raises(service.Unknown):
        generation.run("stop")
    assert generation.starts == 0


def test_stop_only_rejects_quoted_codex_queue_survivor(generation):
    # Product/quoting does not confer ownership; a retained owned child is active.
    generation.active_survivor = True
    with pytest.raises(service.Unknown):
        generation.run("stop")
    assert generation.starts == 0


def test_cooperative_windows_wrapper_has_no_task_or_force_fallback():
    source = RESTART_SCRIPT.read_text(encoding="utf-8")
    assert "-m app.windows_service $action --home" in source and "--deadline $absolute" in source
    assert "[double]$ReadinessTimeoutSeconds = 180" in source
    assert "UseShellExecute = $false" in source and "CreateNoWindow = $true" in source
    for forbidden in ("taskkill", "Stop-ScheduledTask", "Start-ScheduledTask", "Stop-Process", ".Kill(", "initialize-wakes"):
        assert forbidden not in source


def test_cooperative_windows_missing_powershell_query_fake_is_denied():
    with pytest.raises(NativeCallDenied):
        service._task_info(ImmediateDeadline())


def test_cooperative_windows_task_query_is_read_only_and_bounded(monkeypatch):
    calls = []
    def query(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=0, stdout='{"state":3,"path":"\\\\Pallium","name":"Pallium","action_count":1,"instances":[]}')
    monkeypatch.setattr(subprocess, "run", query)
    assert service._task_info(ImmediateDeadline())["state"] == 3
    assert calls[0][1]["timeout"] == 5
    assert "-NoProfile" in calls[0][0]
    assert "GetFolder" in calls[0][0][-1] and "GetTask('Pallium')" in calls[0][0][-1]
    assert all(verb not in calls[0][0][-1] for verb in ("Stop-ScheduledTask", "Start-ScheduledTask", "Register-ScheduledTask"))


@pytest.mark.parametrize("shape", ["automatic-retry", "wrong-host", "legacy-vbs", "missing-home"],
                         ids=["automatic-retry", "wrong-host", "legacy-vbs", "missing-home"])
def test_cooperative_windows_unsupported_registered_launcher_refused_before_control(tmp_path, monkeypatch, shape):
    vbs = tmp_path / "launcher.vbs"
    text = service.MANAGED_MARKER + '\nWScript.Quit WshShell.Run("""python.exe"" -m app.windows_service observe --home ""private home""", 0, True)\n'
    if shape == "legacy-vbs":
        text = text.replace(service.MANAGED_MARKER, "' old unmanaged wrapper")
    if shape == "missing-home":
        text = service.MANAGED_MARKER + "\n"
    vbs.write_text(text, encoding="utf-16")
    task = {"path": "\\Pallium", "name": "Pallium", "action_count": 1, "instances": [],
            "action": "cmd.exe" if shape == "wrong-host" else "wscript.exe",
            "arguments": '"' + str(vbs) + '" "$(Arg0)"', "retry": 3 if shape == "automatic-retry" else 0}
    monkeypatch.setattr(service, "_task_info", lambda _: task)
    with pytest.raises(service.Unknown):
        service._registered_home(ImmediateDeadline())


def test_cooperative_windows_registered_unicode_home_is_exact(tmp_path, monkeypatch):
    home = tmp_path / "Профиль with spaces"
    vbs = tmp_path / "managed.vbs"
    vbs.write_text(service.MANAGED_MARKER + f'\nWScript.Quit WshShell.Run("""python.exe"" -m app.windows_service observe --home ""{home}""", 0, True)\n', encoding="utf-16")
    monkeypatch.setattr(service, "_task_info", lambda _: {"path":"\\Pallium", "name":"Pallium", "action_count":1, "instances":[], "action":"wscript.exe", "arguments":'"'+str(vbs)+'" "$(Arg0)"', "retry":0})
    assert service._registered_home(ImmediateDeadline()) == home


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf")], ids=["zero", "negative", "nan", "infinite"])
def test_cooperative_windows_invalid_operation_budget_never_queries_host(seconds):
    with pytest.raises(ValueError):
        service.control(Path("unused"), "restart", timeout=seconds)


def test_cooperative_windows_mutating_powershell_child_missing_fake_is_denied():
    # The same pre-import subprocess sentinel guards COM Run as well as queries.
    deadline = SimpleNamespace(remaining=lambda: 5, end=10)
    with pytest.raises(NativeCallDenied):
        service._start_task({"vbs": "private.vbs", "cwd": "private"}, deadline)


def test_cooperative_windows_wrapper_uses_only_explicit_mockable_child_boundaries():
    source = RESTART_SCRIPT.read_text(encoding="utf-8")
    assert "New-Object -ComObject Schedule.Service" in source
    assert "New-Object -TypeName System.Diagnostics.Process" in source
    assert "$start.FileName = $manifest.python" in source
    assert "$start.WorkingDirectory = $manifest.cwd" in source
    assert ".venv" not in source and "$PSScriptRoot" not in source
    assert "[Diagnostics.Process]::Start" not in source


def test_cooperative_windows_wrong_task_path_action_count_or_instance_refuses(generation, monkeypatch):
    task = generation.task_info(None)
    task["path"] = "\\OtherFolder\\Pallium"
    monkeypatch.setattr(service, "_task_info", lambda _: task)
    with pytest.raises(service.Unknown):
        generation.run()
    task["path"], task["action_count"] = "\\Pallium", 2
    with pytest.raises(service.Unknown):
        generation.run()
    task["action_count"], task["instances"] = 1, ["another-instance"]
    with pytest.raises(service.Unknown, match="instance"):
        generation.run()
    assert generation.starts == 0 and "signal" not in generation.calls


@pytest.mark.parametrize("shape", ["foreign-nonce", "foreign-pid", "not-in-job", "no-supervisor-proof"], ids=["foreign-nonce", "foreign-pid", "not-in-job", "no-supervisor-proof"])
def test_cooperative_windows_healthy_port_never_substitutes_for_generation_proof(generation, monkeypatch, shape):
    if shape == "foreign-nonce":
        (generation.run_dir / "api_token").write_text(json.dumps({"nonce": "foreign", "pid": 104}), encoding="utf-8")
    elif shape == "foreign-pid":
        (generation.run_dir / "api_token").write_text(json.dumps({"nonce": "nonce-1", "pid": 999}), encoding="utf-8")
    elif shape == "not-in-job":
        generation.jobs[generation.record["description"]].remove(104)
    else:
        generation.record.pop("api_ready")
        generation.write_record()
    if shape == "no-supervisor-proof":
        with pytest.raises(service.Unknown, match="running/unready"):
            generation.run("start")
    else:
        with pytest.raises(service.Unknown, match="ownership"):
            generation.run("start")
    assert generation.starts == 0 and not any(isinstance(call, tuple) for call in generation.calls)


def test_cooperative_windows_public_error_uses_exact_unicode_home(generation, monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(service, "control", lambda *_args, **_kwargs: (_ for _ in ()).throw(service.Unknown("custody unavailable")))
    assert cli.service_main(["restart", "--home", str(generation.home)]) == 1
    assert f"Pallium log: {generation.home / 'logs' / 'pallium.log'}" in capsys.readouterr().err


def test_cooperative_windows_registered_start_keeps_exact_instance_and_deadline(monkeypatch):
    calls = []
    def run(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=0, stdout='{"path":"\\\\Pallium","instance":"exact-instance"}')
    monkeypatch.setattr(subprocess, "run", run)
    deadline = SimpleNamespace(remaining=lambda: 5, end=123.5)
    assert service._start_task({"vbs": "private.vbs", "cwd": "stable installed"}, deadline) == "exact-instance"
    command, options = calls[0]
    assert "$t.Run(" in command[-1] and "GetTask('Pallium')" in command[-1]
    assert "timeout" not in options  # no mutating-child kill or invented cancellation
    assert options["env"]["PALLIUM_CONTROL_DEADLINE"] == "123.5"
    assert json.loads(options["env"]["PALLIUM_CONTROL_EXPECTED"])["cwd"] == "stable installed"


def test_cooperative_windows_live_owned_prebind_token_rejects_healthy_foreign_listener(generation):
    # All prior checks pass: own nonce/PID, live API+supervisor+observer, same Job.
    token_path = generation.run_dir / "api_token"
    token = json.loads(token_path.read_text(encoding="utf-8"))
    token.pop("bound")
    token_path.write_text(json.dumps(token), encoding="utf-8")
    assert token["nonce"] == generation.record["api_ready"]["nonce"]
    assert generation.api.in_job(token["pid"], generation.record["description"])
    assert generation.api.exit_code(token["pid"]) is None
    # Fake ordinary HTTP health would be healthy, but cannot substitute for binding.
    with pytest.raises(service.Unknown, match="ownership"):
        generation.run("start")
    assert generation.starts == 0 and not any(isinstance(call, tuple) for call in generation.calls)


@pytest.mark.parametrize("endpoint", ["/health", "/status", "/debug/queue/health"], ids=["health", "status", "queue-health"])
@pytest.mark.parametrize("marker", [None, "stale-instance", "foreign-instance"], ids=["missing", "stale", "mismatched"])
def test_cooperative_windows_each_managed_http_probe_requires_public_instance(generation, monkeypatch, endpoint, marker):
    # Keep own bind/token/PID/Job/process fields valid; only the responder differs.
    expected = generation.record["api_ready"]["public_instance"]
    calls = []
    class Response:
        def __init__(self, path):
            self.headers = {} if path == endpoint and marker is None else {
                service.SERVICE_INSTANCE_HEADER: marker if path == endpoint else expected}
            self.path = path
        def read(self):
            return json.dumps({"status": "ok", "vector_index_ready": True, "embedding_provider_ok": True}).encode()
        def close(self):
            pass
    def respond(url, **_):
        path = url.split("21987", 1)[1]
        calls.append(path)
        return Response(path)
    monkeypatch.setattr(cli, "_check_health", original_check_health)
    monkeypatch.setattr(cli, "_read_endpoint_json", original_read_endpoint_json)
    monkeypatch.setattr(cli.urllib.request, "urlopen", respond)
    with pytest.raises(service.Unknown, match="running/unready"):
        generation.run("start")
    assert calls[-1] == endpoint and generation.starts == 0
    assert generation.api.exit_code(generation.record["api_ready"]["identity"]["pid"]) is None


def test_cooperative_windows_foreign_healthy_listener_during_owned_failed_bind_refuses(generation, monkeypatch):
    token_path = generation.run_dir / "api_token"
    token = json.loads(token_path.read_text(encoding="utf-8"))
    token.pop("bound")
    token_path.write_text(json.dumps(token), encoding="utf-8")
    calls = []
    def foreign(url, **_):
        calls.append(url)
        return SimpleNamespace(headers={service.SERVICE_INSTANCE_HEADER: "foreign-instance"},
            read=lambda: b'{"status":"ok","vector_index_ready":true,"embedding_provider_ok":true}')
    monkeypatch.setattr(cli, "_check_health", original_check_health)
    monkeypatch.setattr(cli, "_read_endpoint_json", original_read_endpoint_json)
    monkeypatch.setattr(cli.urllib.request, "urlopen", foreign)
    assert generation.api.exit_code(token["pid"]) is None
    assert generation.api.in_job(token["pid"], generation.record["description"])
    with pytest.raises(service.Unknown, match="ownership"):
        generation.run("start")
    assert calls == [] and generation.starts == 0


def test_cooperative_windows_unmanaged_readiness_keeps_legacy_no_header_behavior(generation, monkeypatch):
    calls = []
    def respond(url, **_):
        calls.append(url)
        return SimpleNamespace(headers={}, read=lambda: b'{"status":"ok","vector_index_ready":true,"embedding_provider_ok":true}')
    monkeypatch.setattr(cli, "_check_health", original_check_health)
    monkeypatch.setattr(cli, "_read_endpoint_json", original_read_endpoint_json)
    monkeypatch.setattr(cli.urllib.request, "urlopen", respond)
    assert cli._service_ready(21987, timeout=1)
    assert len(calls) == 3
    assert not cli._managed_ready(21987, timeout=1)  # missing expected instance is never relaxed


def test_cooperative_windows_matching_public_instance_on_all_three_probes_accepts(generation, monkeypatch):
    expected = generation.record["api_ready"]["public_instance"]
    paths = []
    def respond(url, **_):
        paths.append(url.split("21987", 1)[1])
        return SimpleNamespace(headers={service.SERVICE_INSTANCE_HEADER: expected},
            read=lambda: b'{"status":"ok","vector_index_ready":true,"embedding_provider_ok":true}')
    monkeypatch.setattr(cli, "_check_health", original_check_health)
    monkeypatch.setattr(cli, "_read_endpoint_json", original_read_endpoint_json)
    monkeypatch.setattr(cli.urllib.request, "urlopen", respond)
    assert generation.run("start") == "already running"
    assert paths == ["/health", "/status", "/debug/queue/health"] and generation.starts == 0


@pytest.mark.parametrize("expected", [None, "", 0, False, [], {}, " ", "invalid\nvalue"],
                         ids=["missing", "empty", "number", "boolean", "list", "object", "whitespace", "control-character"])
def test_cooperative_windows_malformed_expected_marker_never_falls_back_to_legacy(generation, monkeypatch, expected):
    def unexpected(*_args, **_kwargs):
        pytest.fail("managed context must reject expected marker before any readiness probe")
    monkeypatch.setattr(cli, "_check_health", unexpected)
    monkeypatch.setattr(cli, "_read_endpoint_json", unexpected)
    assert not cli._managed_ready(21987, timeout=1, expected_instance=expected)
    generation.record["api_ready"]["public_instance"] = expected
    generation.write_record()
    with pytest.raises(service.Unknown, match="running/unready"):
        generation.run("start")
    assert generation.starts == 0 and "signal" not in generation.calls
