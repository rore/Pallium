from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows scheduled-task restart wrapper",
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RESTART_SCRIPT = REPO_ROOT / "scripts" / "restart-service.ps1"


def test_default_readiness_budget_allows_three_minute_cold_start() -> None:
    script = RESTART_SCRIPT.read_text(encoding="utf-8")

    assert "[double]$ReadinessTimeoutSeconds = 180" in script


HARNESS = r'''
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
function Log-Call {
    param([string]$Value)
    [IO.File]::AppendAllText($env:RW010_CALL_LOG, $Value + [Environment]::NewLine)
}

function Get-ScheduledTask {
    param($TaskName, $ErrorAction)
    $workingDirectory = if ($env:RW010_TASK_SHAPE -in @("canonical", "unparseable")) {
        ""
    } else {
        $env:RW010_WORKDIR
    }
    [pscustomobject]@{
        State = "Ready"
        Actions = @([pscustomobject]@{
            Execute = "wscript.exe"
            Arguments = '"' + $env:RW010_VBS + '"'
            WorkingDirectory = $workingDirectory
        })
    }
}

$script:PreparationMilliseconds = 0.0
$script:OwnedChildCount = 0
function Advance-PreparationTestClock([double]$Milliseconds) {
    if ($env:RW010_PREPARATION_CLOCK -eq '1') { $script:PreparationMilliseconds += $Milliseconds }
}
function New-PreparationTestTimer {
    $timer = [pscustomobject]@{}
    $timer | Add-Member ScriptProperty Elapsed { [TimeSpan]::FromMilliseconds($script:PreparationMilliseconds) }
    return $timer
}

function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$Wait, [switch]$PassThru)
    if ($Wait -or -not $PassThru -or $WindowStyle -ne 'Hidden') { throw 'owned child start must be hidden, retained and nonblocking' }
    Log-Call "Start-Process:$FilePath"
    $role = if ($FilePath -eq 'taskkill.exe') { 'taskkill' } elseif ($ArgumentList -match 'service initialize-wakes') { 'init' } else { 'preflight' }
    if ($role -eq 'init') { Log-Call 'Initialize-Wakes' }
    if ($role -eq 'taskkill') {
        $script:TaskkillCalls++
        Log-Call ('taskkill ' + ($ArgumentList -join ' '))
    } elseif ($PSBoundParameters.ContainsKey('WorkingDirectory')) {
        Log-Call "PreflightWorkingDirectory:$WorkingDirectory"
    } else {
        Log-Call 'PreflightWorkingDirectory:<omitted>'
    }
    if ($env:RW010_PROCESS_FAULT -eq "${role}:spawn") { throw 'simulated spawn failure' }
    if ($env:RW010_PROCESS_FAULT -eq "${role}:null") { return $null }
    $exitCode = if (($role -eq 'preflight' -and $env:RW010_SCENARIO -eq 'preflight_failure') -or ($role -eq 'init' -and $env:RW010_SCENARIO -eq 'wake_import_failure')) { 7 } else { 0 }
    if ($role -eq 'taskkill' -and $script:TaskkillCalls -eq 1 -and $env:RW010_SCENARIO -in @('partial_taskkill', 'nonzero_taskkill')) { $exitCode = 1 }
    $script:OwnedChildCount++
    $process = [pscustomobject]@{ Id = (9300 + $script:OwnedChildCount); Role = $role; HasExited = $false; Code = $exitCode; Killed = $false }
    $process | Add-Member ScriptProperty ExitCode {
        Log-Call "ExitCode:$($this.Role)"
        if (-not $this.HasExited) { throw 'exit code read before confirmed exit' }
        return $this.Code
    }
    $process | Add-Member ScriptMethod WaitForExit {
        param([int]$Milliseconds)
        Log-Call "Wait:$($this.Role):$Milliseconds"
        if ($this.Killed) {
            if ($env:RW010_PROCESS_FAULT -eq "$($this.Role):cleanup_wait_error") { throw 'simulated cleanup wait failure' }
            if ($env:RW010_PROCESS_FAULT -eq "$($this.Role):cleanup_timeout") {
                Advance-PreparationTestClock $Milliseconds
                return $false
            }
            $this.HasExited = $true
            return $true
        }
        if ($env:RW010_PROCESS_FAULT -eq "$($this.Role):wait_error") {
            Advance-PreparationTestClock 100
            throw 'simulated wait failure'
        }
        if ($env:RW010_PROCESS_FAULT -in @("$($this.Role):timeout", "$($this.Role):kill_error", "$($this.Role):cleanup_timeout", "$($this.Role):cleanup_wait_error", "$($this.Role):refresh_error", "$($this.Role):exited_on_refresh")) {
            Advance-PreparationTestClock $Milliseconds
            return $false
        }
        if ($env:RW010_SCENARIO -eq 'prep_cumulative' -and $this.Role -in @('preflight', 'taskkill')) { Advance-PreparationTestClock 600 }
        if ($env:RW010_SCENARIO -eq 'prep_near_limit_ready' -and $this.Role -eq 'preflight') { Advance-PreparationTestClock 175000 }
        $this.HasExited = $true
        return $true
    }
    $process | Add-Member ScriptMethod Refresh {
        Log-Call "Refresh:$($this.Role)"
        if ($env:RW010_PROCESS_FAULT -eq "$($this.Role):refresh_error") { throw 'simulated refresh failure' }
        if ($env:RW010_PROCESS_FAULT -eq "$($this.Role):exited_on_refresh") { $this.HasExited = $true }
    }
    $process | Add-Member ScriptMethod Kill {
        Log-Call "Kill:$($this.Role):$($this.Id)"
        if ($env:RW010_PROCESS_FAULT -eq "$($this.Role):kill_error") { throw 'simulated root kill failure' }
        $this.Killed = $true
    }
    $process | Add-Member ScriptMethod Dispose {
        Log-Call "Dispose:$($this.Role)"
        if ($env:RW010_SCENARIO -eq 'prep_expired_before_stop' -and $this.Role -eq 'preflight') { Advance-PreparationTestClock 3000 }
        if ($env:RW010_SCENARIO -eq 'prep_sleep_exact_boundary' -and $this.Role -eq 'preflight') { Advance-PreparationTestClock 1000 }
        if ($env:RW010_SCENARIO -eq 'prep_sleep_just_fits' -and $this.Role -eq 'preflight') { Advance-PreparationTestClock 998 }
        if ($env:RW010_SCENARIO -eq 'prep_expired_before_start' -and $this.Role -eq 'init') { Advance-PreparationTestClock 1000 }
        if ($env:RW010_PROCESS_FAULT -eq "$($this.Role):dispose_error") { throw 'simulated disposal failure' }
    }
    return $process
}

function Stop-ScheduledTask {
    param($TaskName, $ErrorAction)
    Log-Call "Stop-ScheduledTask"
}

function Start-ScheduledTask {
    param($TaskName, $ErrorAction)
    Log-Call "Start-ScheduledTask"
    if ($env:RW010_SCENARIO -eq "start_failure") { throw "mock start failure" }
}

function Stop-Process {
    param([Parameter(ValueFromRemainingArguments = $true)]$Arguments)
    Log-Call "Stop-Process"
}

$script:TaskkillCalls = 0
$script:NetTcpCalls = 0
function Get-NetTCPConnection {
    param($LocalPort, $State, $ErrorAction)
    $script:NetTcpCalls++
    Log-Call "Get-NetTCPConnection:$LocalPort"
    if ($env:RW010_SCENARIO -eq "empty_listener_notfound") {
        Write-Error "No matching objects" -ErrorId "CmdletizationQuery_NotFound" -Category ObjectNotFound -ErrorAction $ErrorAction
        return
    }
    if ($env:RW010_SCENARIO -eq "multiple_initial_listeners" -and $script:NetTcpCalls -eq 1) {
        return @(
            [pscustomobject]@{ OwningProcess = 6161 },
            [pscustomobject]@{ OwningProcess = 6161 },
            [pscustomobject]@{ OwningProcess = 6262 }
        )
    }
    if ($env:RW010_SCENARIO -eq "surviving_listener" -and $script:NetTcpCalls -gt 1) {
        return @(
            [pscustomobject]@{ OwningProcess = 6161 },
            [pscustomobject]@{ OwningProcess = 6262 }
        )
    }
    return $null
}

function Get-Process {
    param($Id, $ErrorAction)
    if ($env:RW016_PID -and $Id -eq [int]$env:RW016_PID) {
        if ($env:RW010_SCENARIO -eq 'prep_expired_before_taskkill') { Advance-PreparationTestClock 3000 }
        return [pscustomobject]@{ Id = $Id }
    }
    return $null
}

function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    Log-Call "Get-CimInstance:$Filter"
    if ($env:RW010_SCENARIO -eq 'prep_expired_before_init' -and -not $Filter) { Advance-PreparationTestClock 1000 }
    if ($env:RW010_SCENARIO -eq 'prep_expired_before_sleep' -and $Filter -like '*app.run service run*') { Advance-PreparationTestClock 1000 }
    if ($env:RW010_SCENARIO -eq "enumeration_failure" -and -not $Filter) {
        throw "simulated process enumeration failure"
    }
    if ($env:RW010_SCENARIO -eq "quoted_codex_survivor" -and -not $Filter) {
        return [pscustomobject]@{ ProcessId = 7373; ParentProcessId = 1; Name = "codex.exe"; ExecutablePath = "C:\Program Files\Codex\codex.exe"; CommandLine = '"C:\Program Files\Codex\codex.exe" queue --profile pallium-relay --thread x' }
    }
    if ($env:RW010_SCENARIO -eq "redirected_worker_survivor" -and (-not $Filter -or $Filter -like "*app.processor*")) {
        return [pscustomobject]@{ ProcessId = 8484; ParentProcessId = 1; Name = "python.exe"; ExecutablePath = $env:RW010_NATIVE_PYTHON; CommandLine = ('"' + $env:RW010_PYTHON + '" -m app.processor --processor-id orphan') }
    }
    if ($env:RW010_SCENARIO -eq "canonical_survivor" -and $Filter -like "*app.run service run*") {
        return @(
            [pscustomobject]@{
                ProcessId = 4242
                Name = "python.exe"
                ExecutablePath = $env:RW010_PYTHON
                CommandLine = "python -m app.run service run --port 2198 --home `"`"$env:RW010_SERVICE_HOME`"`""
            },
            [pscustomobject]@{
                ProcessId = 4343
                Name = "python.exe"
                ExecutablePath = $env:RW010_PYTHON
                CommandLine = "python -m app.run service run --port 21987 --home `"`"$env:RW010_SERVICE_HOME`"`""
            }
        )
    }
    if ($env:RW010_SCENARIO -eq "canonical_survivor" -and $Filter -like "*app.run mcp*") {
        return [pscustomobject]@{ ProcessId = 9999; Name = "python.exe" }
    }
    return @()
}

function Start-Sleep {
    param($Seconds, $Milliseconds)
    if ($Seconds -eq 2) { Advance-PreparationTestClock 2000 }
    if ($null -ne $Milliseconds) { Log-Call "Sleep:$Milliseconds" }
    else { Log-Call "Sleep:$($Seconds * 1000)" }
}

$script:HealthCalls = 0
$script:StatusCalls = 0
$script:QueueCalls = 0

function Invoke-RestMethod {
    param($Uri, $TimeoutSec)
    $path = ([uri]$Uri).AbsolutePath
    Log-Call "URI:$Uri"
    Log-Call "GET $path"
    Log-Call "Timeout:${path}:$TimeoutSec"
    if ($path -eq "/health") {
        $script:HealthCalls++
        if ($env:RW010_SCENARIO -eq "terminal_health" -or
            ($env:RW010_SCENARIO -eq "transient" -and $script:HealthCalls -eq 1)) {
            return [pscustomobject]@{ status = "initializing" }
        }
        return [pscustomobject]@{ status = "ok" }
    }

    $script:StatusCalls++
    if ($env:RW010_SCENARIO -eq "terminal_status") {
        return [pscustomobject]@{}
    }
    if ($env:RW010_SCENARIO -eq "transient" -and $script:StatusCalls -eq 1) {
        return [pscustomobject]@{
            embedding_provider_ok = $false
            ingestion = [pscustomobject]@{ status = "ok" }
        }
    }
    if ($env:RW010_SCENARIO -eq "transient" -and $script:StatusCalls -eq 2) {
        return [pscustomobject]@{
            embedding_provider_ok = $true
            ingestion = [pscustomobject]@{ status = "degraded" }
        }
    }
    [pscustomobject]@{
        embedding_provider_ok = $true
        ingestion = [pscustomobject]@{ status = "ok" }
    }
}

function Invoke-WebRequest {
    param($Uri, [switch]$UseBasicParsing, $TimeoutSec)
    $path = ([uri]$Uri).AbsolutePath
    Log-Call "URI:$Uri"
    Log-Call "GET $path"
    Log-Call "Timeout:${path}:$TimeoutSec"
    $script:QueueCalls++
    if ($env:RW010_SCENARIO -eq "slow_queue") {
        if ($TimeoutSec -lt 3) { throw "simulated queue timeout" }
        [Threading.Thread]::Sleep(3000)
    }
    if ($env:RW010_SCENARIO -eq "terminal_queue" -or
        ($env:RW010_SCENARIO -eq "transient" -and $script:QueueCalls -le 21)) {
        return [pscustomobject]@{ StatusCode = 503 }
    }
    [pscustomobject]@{ StatusCode = 204 }
}

$env:USERPROFILE = $env:RW010_HOME
if ($env:RW010_STOP_ONLY -eq "1") {
    & $env:RW010_SCRIPT -ReadinessTimeoutSeconds ([double]$env:RW010_READINESS_TIMEOUT_SECONDS) -StopOnly
} else {
    & $env:RW010_SCRIPT -ReadinessTimeoutSeconds ([double]$env:RW010_READINESS_TIMEOUT_SECONDS)
}
exit $LASTEXITCODE
'''


def _run_restart(
    tmp_path: Path,
    scenario: str,
    *,
    task_shape: str = "canonical",
    port: int | str | None = 21987,
    working_directory: Path | None = None,
    service_home: Path | None = None,
    pid_file_value: int | None = None,
    readiness_timeout_seconds: float | str = 4.0,
    stop_only: bool = False,
    process_fault: str = "",
    preparation_clock: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None, "PowerShell is required on Windows"

    call_log = tmp_path / "calls.log"
    harness = tmp_path / "harness.ps1"
    service_home = service_home or tmp_path / "service-home"
    vbs = tmp_path / "launcher.vbs"
    harness.write_text(HARNESS, encoding="utf-8")
    script = RESTART_SCRIPT
    if preparation_clock:
        source = RESTART_SCRIPT.read_text(encoding="utf-8")
        constructor = "$preparationTimer = [Diagnostics.Stopwatch]::StartNew()"
        assert source.count(constructor) == 1
        script = tmp_path / "restart-preparation-clock.ps1"
        script.write_text(source.replace(constructor, "$preparationTimer = New-PreparationTestTimer"), encoding="utf-8")
    if pid_file_value is not None:
        (service_home / "run").mkdir(parents=True, exist_ok=True)
        (service_home / "run" / "pallium.pid").write_text(str(pid_file_value))
    if task_shape == "generated_cli":
        from unittest.mock import patch
        from app.cli.service import _install_windows

        service_home.mkdir(parents=True, exist_ok=True)
        (service_home / "run").mkdir(exist_ok=True)
        vbs = service_home / "run" / "pallium_launcher.vbs"
        with patch(
            "app.cli.service.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ):
            _install_windows("pallium", int(port or 21987), service_home)
        command = None
    elif task_shape == "legacy":
        python = Path(sys.executable).with_name("pythonw.exe")
        launcher = tmp_path / "service_launcher.py"
        assert python.exists()
        launcher.write_text(
            f'from app.run import run\nraise SystemExit(run(["service", "run", "--port", "{port}"]))\n',
            encoding="ascii",
        )
        command = f'WshShell.Run """{python}"" ""{launcher}""", 0, False\n'
    elif task_shape == "unparseable":
        command = 'WshShell.Run "not-python", 0, False\n'
    elif task_shape == "canonical_missing_home":
        port_arg = "" if port is None else f" --port {port}"
        command = f'WshShell.Run """{sys.executable}"" -m app.run service run{port_arg}", 0, False\n'
    else:
        port_arg = "" if port is None else f" --port {port}"
        if task_shape == "canonical_legacy":
            command = (
                f'WshShell.Run """{sys.executable}"" -m app.run service run{port_arg} '
                f'--home ""{service_home}""", 0, False\n'
            )
        elif task_shape == "new_launcher":
            python = Path(sys.executable).with_name("pythonw.exe")
            assert python.exists()
            launcher = tmp_path / "service_launcher.py"
            launcher.write_text(
                f'from app.run import run\nraise SystemExit(run(["service", "run", "--port", "{port}"]))\n',
                encoding="ascii",
            )
            command = f'WScript.Quit WshShell.Run("""{python}"" ""{launcher}""", 0, True)\n'
        else:
            command = (
                f'WScript.Quit WshShell.Run("""{sys.executable}"" -m app.run service run{port_arg} '
                f'--home ""{service_home}""", 0, True)\n'
            )
    if command is not None:
        vbs.write_text(
            'Set WshShell = CreateObject("WScript.Shell")\n' + command,
            encoding="ascii" if task_shape in {"legacy", "canonical_legacy"} else "utf-16",
        )

    env = os.environ.copy()
    env.update(
        RW010_CALL_LOG=str(call_log),
        RW010_HOME=str(tmp_path / "home"),
        USERPROFILE=str(tmp_path / "profile"),
        HOME=str(tmp_path / "home"),
        APPDATA=str(tmp_path / "profile" / "AppData" / "Roaming"),
        RW010_SCENARIO=scenario,
        RW010_SCRIPT=str(script),
        RW010_PYTHON=str(sys.executable),
        RW010_NATIVE_PYTHON=str(sys._base_executable),
        RW010_SERVICE_HOME=str(service_home),
        RW010_TASK_SHAPE=task_shape,
        RW010_VBS=str(vbs),
        RW010_WORKDIR=(
            str(tmp_path / "missing")
            if task_shape == "invalid_workdir"
            else str(working_directory or tmp_path)
        ),
        RW016_PID="" if pid_file_value is None else str(pid_file_value),
        RW010_READINESS_TIMEOUT_SECONDS=str(readiness_timeout_seconds),
        RW010_STOP_ONLY="1" if stop_only else "0",
        RW010_PROCESS_FAULT=process_fault,
        RW010_PREPARATION_CLOCK="1" if preparation_clock else "0",
    )
    result = subprocess.run(
        [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(harness)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
    return result, calls


def _output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def _assert_failure(result: subprocess.CompletedProcess[str]) -> str:
    output = _output(result)
    assert result.returncode != 0
    assert "Pallium restarted." not in output
    assert "Pallium log:" in output
    assert "\\logs\\pallium.log" in output
    return output


def _assert_port(result: subprocess.CompletedProcess[str], calls: list[str], port: int) -> None:
    assert f"Get-NetTCPConnection:{port}" in calls
    assert f"URI:http://127.0.0.1:{port}/health" in calls
    assert f"URI:http://127.0.0.1:{port}/status" in calls
    assert f"URI:http://127.0.0.1:{port}/debug/queue/health" in calls
    assert f"http://127.0.0.1:{port}/dashboard" in _output(result)


def test_wake_import_runs_after_stop_and_before_task_start(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "success")
    assert result.returncode == 0, _output(result)
    assert calls.index("Stop-ScheduledTask") < calls.index("Initialize-Wakes") < calls.index("Start-ScheduledTask")


def test_wake_import_failure_never_starts_service(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "wake_import_failure")
    _assert_failure(result)
    assert "Initialize-Wakes" in calls
    assert "Start-ScheduledTask" not in calls


def test_stop_only_does_not_import_wakes(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "success", stop_only=True)
    assert result.returncode == 0, _output(result)
    assert "Initialize-Wakes" not in calls
    assert f"Start-Process:{sys.executable}" in calls
    assert calls.count("Dispose:preflight") == 1


def test_preflight_failure_never_stops_the_healthy_service(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "preflight_failure")

    output = _assert_failure(result)
    assert "import preflight failed with exit code 7" in output
    assert "Stop-ScheduledTask" not in calls
    assert "Stop-Process" not in calls
    assert not any(call.startswith("taskkill") for call in calls)


@pytest.mark.parametrize(
    ("task_shape", "message"),
    [
        ("invalid_workdir", "working directory is missing or invalid"),
        ("unparseable", "Could not resolve the installed Python executable"),
    ],
)
def test_invalid_installed_task_metadata_never_stops(
    tmp_path: Path,
    task_shape: str,
    message: str,
) -> None:
    result, calls = _run_restart(tmp_path, "ready", task_shape=task_shape)

    assert message in _assert_failure(result)
    assert "Stop-ScheduledTask" not in calls
    assert "Stop-Process" not in calls
    assert not any(call.startswith("taskkill") for call in calls)


def test_canonical_task_omits_working_directory_and_sweeps_survivor(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "canonical_survivor", port=2198)

    assert result.returncode == 0, _output(result)
    assert f"Start-Process:{sys.executable}" in calls
    assert "PreflightWorkingDirectory:<omitted>" in calls
    assert any(call.endswith("/PID 4242") for call in calls)
    assert not any("4343" in call for call in calls)
    assert not any("9999" in call for call in calls)
    _assert_port(result, calls, 2198)


def test_legacy_task_passes_exact_working_directory(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "ready", task_shape="legacy", port=21988)

    assert result.returncode == 0, _output(result)
    assert f"Start-Process:{Path(sys.executable).with_name('pythonw.exe')}" in calls
    assert f"PreflightWorkingDirectory:{tmp_path}" in calls
    _assert_port(result, calls, 21988)


@pytest.mark.parametrize("task_shape", ["canonical_legacy", "generated_cli", "new_launcher"])
def test_restart_metadata_parses_legacy_and_generated_launcher_forms(
    tmp_path: Path, task_shape: str
) -> None:
    result, calls = _run_restart(tmp_path, "success", task_shape=task_shape, stop_only=True)

    assert result.returncode == 0, _output(result)
    assert "Stop-ScheduledTask" in calls


def test_legacy_task_passes_unicode_working_directory_exactly(tmp_path: Path) -> None:
    working_directory = tmp_path / "תיקייה עם רווחים"
    working_directory.mkdir()

    result, calls = _run_restart(
        tmp_path,
        "ready",
        task_shape="legacy",
        port=21988,
        working_directory=working_directory,
        readiness_timeout_seconds=10.0,
    )

    assert result.returncode == 0, _output(result)
    assert f"PreflightWorkingDirectory:{working_directory}" in calls


def test_canonical_unicode_home_controls_pid_cleanup_and_failure_log(tmp_path: Path) -> None:
    service_home = tmp_path / "שירות %TEMP% עם רווחים"
    result, calls = _run_restart(
        tmp_path,
        "start_failure",
        service_home=service_home,
        pid_file_value=5151,
    )

    output = _assert_failure(result)
    assert any(call.endswith("/PID 5151") for call in calls)
    assert f"Pallium log: {service_home / 'logs' / 'pallium.log'}" in output


def test_legacy_task_failure_keeps_default_home_log_path(tmp_path: Path) -> None:
    result, _calls = _run_restart(tmp_path, "start_failure", task_shape="legacy")

    output = _assert_failure(result)
    default_log = tmp_path / "home" / ".pallium" / "logs" / "pallium.log"
    assert f"Pallium log: {default_log}" in output

def test_canonical_missing_home_fails_before_stop(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "ready", task_shape="canonical_missing_home")

    output = _assert_failure(result)
    assert "resolve the installed service home" in output
    assert "Stop-ScheduledTask" not in calls
    assert "Stop-Process" not in calls
    assert not any(call.startswith("taskkill") for call in calls)

@pytest.mark.parametrize("port", [None, "abc", 0, 65536])
def test_missing_or_invalid_port_never_stops(tmp_path: Path, port: int | str | None) -> None:
    result, calls = _run_restart(tmp_path, "ready", port=port)

    assert "valid installed service port (1..65535)" in _assert_failure(result)
    assert "Stop-ScheduledTask" not in calls
    assert "Stop-Process" not in calls
    assert not any(call.startswith("taskkill") for call in calls)
    assert not any(call.startswith("Get-NetTCPConnection:") for call in calls)


@pytest.mark.parametrize("port", [1, 65535])
def test_boundary_ports_are_valid(tmp_path: Path, port: int) -> None:
    result, calls = _run_restart(tmp_path, "ready", port=port)

    assert result.returncode == 0, _output(result)
    _assert_port(result, calls, port)


def test_partial_taskkill_error_continues_cleanup_and_restarts(tmp_path: Path) -> None:
    result, calls = _run_restart(
        tmp_path,
        "partial_taskkill",
        pid_file_value=5151,
    )

    assert result.returncode == 0, _output(result)
    assert "partial failure for PID 5151" in _output(result)
    assert len([call for call in calls if call.startswith("Get-CimInstance:")]) >= 2
    assert calls.count("Start-ScheduledTask") == 1
    _assert_port(result, calls, 21987)


def test_nonzero_taskkill_error_continues_cleanup_and_restarts(tmp_path: Path) -> None:
    result, calls = _run_restart(
        tmp_path,
        "nonzero_taskkill",
        pid_file_value=5151,
    )

    assert result.returncode == 0, _output(result)
    assert "partial failure for PID 5151" in _output(result)
    assert calls.count("Start-ScheduledTask") == 1
    assert calls.count("Get-NetTCPConnection:21987") >= 2
    _assert_port(result, calls, 21987)


def test_stop_only_rejects_nonzero_taskkill(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "nonzero_taskkill", pid_file_value=5151, stop_only=True)

    assert "taskkill failed for PID 5151" in _assert_failure(result)
    assert "Start-ScheduledTask" not in calls


def test_stop_only_rejects_failed_process_enumeration(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "enumeration_failure", stop_only=True)

    assert result.returncode != 0
    assert "simulated process enumeration failure" in _output(result)
    assert "Pallium restarted." not in _output(result)
    assert "Start-ScheduledTask" not in calls


def test_multiple_initial_listeners_are_killed_once_each(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "multiple_initial_listeners")

    assert result.returncode == 0, _output(result)
    assert calls.count("taskkill /F /T /PID 6161") == 1
    assert calls.count("taskkill /F /T /PID 6262") == 1
    assert calls.count("Start-ScheduledTask") == 1
    _assert_port(result, calls, 21987)


def test_surviving_listener_fails_before_task_start(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "surviving_listener")

    output = _assert_failure(result)
    assert "port 21987 is still listening" in output
    assert "listener PID(s): 6161, 6262" in output
    assert "Start-ScheduledTask" not in calls
    assert not any(call.startswith("URI:") for call in calls)


def test_start_failure_is_nonzero_and_never_prints_success(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "start_failure")

    output = _assert_failure(result)
    assert "Failed to start the Pallium scheduled task" in output
    assert calls.count("Stop-ScheduledTask") == 1
    assert calls.count("Start-ScheduledTask") == 1


def test_transient_readiness_checks_all_contracts_before_success(tmp_path: Path) -> None:
    result, calls = _run_restart(
        tmp_path, "transient", readiness_timeout_seconds=10.0,
    )

    assert result.returncode == 0, _output(result)
    assert "Pallium restarted." in _output(result)
    assert calls.count("GET /health") == 25
    assert calls.count("GET /status") == 24
    assert calls.count("GET /debug/queue/health") == 22
    assert calls.count("Sleep:500") == 24
    for path, maximum in (
        ("/health", 2),
        ("/status", 2),
        ("/debug/queue/health", 10),
    ):
        timeouts = [
            int(call.rsplit(":", 1)[1])
            for call in calls
            if call.startswith(f"Timeout:{path}:")
        ]
        assert timeouts
        assert all(1 <= timeout <= maximum for timeout in timeouts)


def test_queue_health_can_use_longer_timeout_within_same_deadline(
    tmp_path: Path,
) -> None:
    result, calls = _run_restart(
        tmp_path, "slow_queue", readiness_timeout_seconds=6.0,
    )

    assert result.returncode == 0, _output(result)
    queue_timeouts = [
        int(call.rsplit(":", 1)[1])
        for call in calls
        if call.startswith("Timeout:/debug/queue/health:")
    ]
    assert queue_timeouts and 2 < queue_timeouts[0] <= 10
    assert all(
        int(call.rsplit(":", 1)[1]) <= 2
        for call in calls
        if call.startswith(("Timeout:/health:", "Timeout:/status:"))
    )


@pytest.mark.parametrize(
    ("scenario", "last_check", "last_endpoint"),
    [
        ("terminal_health", "/health status=initializing", "GET /health"),
        ("terminal_status", "/status embedding_provider_ok=", "GET /status"),
        ("terminal_queue", "/debug/queue/health HTTP 503", "GET /debug/queue/health"),
    ],
)
def test_terminal_readiness_exhausts_exact_budget_without_success(
    tmp_path: Path,
    scenario: str,
    last_check: str,
    last_endpoint: str,
) -> None:
    result, calls = _run_restart(
        tmp_path, scenario, readiness_timeout_seconds=4.1,
    )

    output = _assert_failure(result)
    assert "failed the 4.1-second readiness budget" in output
    assert last_check in output
    assert calls.count(last_endpoint) >= 1
    if scenario == "terminal_queue":
        assert all(
            int(call.rsplit(":", 1)[1]) <= 4
            for call in calls
            if call.startswith("Timeout:/debug/queue/health:")
        )

def test_stop_only_accepts_empty_listener_not_found(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "empty_listener_notfound", stop_only=True)

    assert result.returncode == 0, _output(result)
    assert "Pallium stopped." in _output(result)
    assert "Start-ScheduledTask" not in calls
    assert not any(call.startswith("URI:") for call in calls)


def test_stop_only_rejects_orphan_redirected_worker(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "redirected_worker_survivor", stop_only=True)

    output = _assert_failure(result)
    assert "taskkill /F /T /PID 8484" in calls
    assert "Managed Pallium process(es) survived stop: 8484" in output
    assert "Start-ScheduledTask" not in calls


def test_stop_only_rejects_quoted_codex_queue_survivor(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "quoted_codex_survivor", stop_only=True)

    output = _assert_failure(result)
    assert "Managed Pallium process(es) survived stop: 7373" in output
    assert "Start-ScheduledTask" not in calls

@pytest.mark.parametrize("role", ["preflight", "init", "taskkill"])
@pytest.mark.parametrize("fault", ["spawn", "null", "timeout", "wait_error", "kill_error", "cleanup_timeout", "cleanup_wait_error", "refresh_error", "exited_on_refresh", "dispose_error"])
def test_owned_preparation_child_failure_is_fatal_and_disposes_once(tmp_path, role, fault):
    result, calls = _run_restart(
        tmp_path, "success", pid_file_value=5151,
        process_fault=f"{role}:{fault}", preparation_clock=True,
    )
    output = _assert_failure(result)
    assert "Start-ScheduledTask" not in calls
    assert ("Stop-ScheduledTask" in calls) is (role != "preflight")
    assert calls.count(f"Dispose:{role}") == (0 if fault in {"spawn", "null"} else 1)
    if fault == "dispose_error":
        assert f"ExitCode:{role}" in calls
    else:
        assert f"ExitCode:{role}" not in calls
    waits = [int(call.rsplit(":", 1)[1]) for call in calls if call.startswith(f"Wait:{role}:")]
    assert all(0 <= value <= 2_147_483_647 for value in waits)
    work_wait = 1000 if role == "init" else 3000
    if fault in {"spawn", "null"}:
        message = "simulated spawn failure" if fault == "spawn" else "process start returned no owned handle"
        assert waits == [] and message in output
        assert not any(call.startswith(f"Kill:{role}:") for call in calls)
    elif fault == "dispose_error":
        assert waits == [work_wait] and "simulated disposal failure" in output
        assert not any(call.startswith(f"Kill:{role}:") for call in calls)
    elif fault == "exited_on_refresh":
        assert waits == [work_wait]
        assert "shared preparation work budget elapsed" in output
        assert f"Refresh:{role}" in calls
        assert not any(call.startswith(f"Kill:{role}:") for call in calls)
    else:
        assert waits[0] == work_wait
        assert any(call.startswith(f"Kill:{role}:93") for call in calls)
        if fault == "wait_error":
            cleanup_wait = 1900 if role == "init" else 3900
            assert waits == [work_wait, cleanup_wait] and "simulated wait failure" in output
        elif fault == "kill_error":
            assert waits == [work_wait]
            assert "shared preparation work budget elapsed" in output and "simulated root kill failure" in output
        else:
            assert waits == [work_wait, 1000]
            assert "shared preparation work budget elapsed" in output
            if fault == "cleanup_timeout":
                assert "owned root exit remains unconfirmed" in output
            elif fault == "cleanup_wait_error":
                assert "simulated cleanup wait failure" in output
            elif fault == "refresh_error":
                assert "simulated refresh failure" in output


def test_preparation_children_share_one_budget_including_cleanup(tmp_path):
    result, calls = _run_restart(
        tmp_path, "prep_cumulative", pid_file_value=5151,
        process_fault="init:timeout", preparation_clock=True, readiness_timeout_seconds=6,
    )
    _assert_failure(result)
    assert [call for call in calls if call.startswith("Wait:")] == [
        "Wait:preflight:4500", "Wait:taskkill:3900", "Wait:init:1300", "Wait:init:1500",
    ]
    assert "Start-ScheduledTask" not in calls
    assert all(calls.count(f"Dispose:{role}") == 1 for role in ("preflight", "taskkill", "init"))


@pytest.mark.parametrize("phase", ["stop", "start"])
def test_expired_preparation_is_checked_before_service_mutation(tmp_path, phase):
    result, calls = _run_restart(tmp_path, f"prep_expired_before_{phase}", preparation_clock=True)
    expected = "before stopping" if phase == "stop" else "before starting"
    assert expected in _assert_failure(result)
    assert ("Stop-ScheduledTask" in calls) is (phase == "start")
    assert "Start-ScheduledTask" not in calls


def test_preparation_does_not_consume_separate_readiness_allowance(tmp_path):
    result, calls = _run_restart(tmp_path, "prep_near_limit_ready", readiness_timeout_seconds=180, preparation_clock=True)
    assert result.returncode == 0, _output(result)
    assert "Wait:preflight:178000" in calls and "Wait:init:1000" in calls
    assert "Timeout:/debug/queue/health:10" in calls
    assert calls.index("Initialize-Wakes") < calls.index("Start-ScheduledTask") < calls.index("URI:http://127.0.0.1:21987/health")


def test_large_finite_preparation_wait_is_clamped_before_int_conversion(tmp_path):
    result, calls = _run_restart(tmp_path, "success", readiness_timeout_seconds=1e300, preparation_clock=True)
    assert result.returncode == 0, _output(result)
    assert [call for call in calls if call.startswith("Wait:")] == [
        "Wait:preflight:2147483647", "Wait:init:2147483647",
    ]

@pytest.mark.parametrize("fault", ["timeout", "cleanup_timeout"])
def test_stop_only_taskkill_timeout_and_uncertain_cleanup_remain_fatal(tmp_path, fault):
    result, calls = _run_restart(
        tmp_path, "success", pid_file_value=5151, stop_only=True,
        process_fault=f"taskkill:{fault}", preparation_clock=True,
    )
    output = _assert_failure(result)
    assert "taskkill could not settle for PID 5151" in output
    assert calls.count("Dispose:taskkill") == 1
    assert "Stop-ScheduledTask" in calls and "Start-ScheduledTask" not in calls
    assert "Initialize-Wakes" not in calls and "Pallium stopped." not in output
    if fault == "cleanup_timeout":
        assert "owned root exit remains unconfirmed" in output


@pytest.mark.parametrize("role", ["taskkill", "init"])
def test_expired_preparation_does_not_launch_the_next_child(tmp_path, role):
    result, calls = _run_restart(
        tmp_path, f"prep_expired_before_{role}", pid_file_value=5151, preparation_clock=True,
    )
    assert "shared preparation work budget elapsed" in _assert_failure(result)
    assert "Stop-ScheduledTask" in calls and "Start-ScheduledTask" not in calls
    if role == "taskkill":
        assert "Start-Process:taskkill.exe" not in calls
    else:
        assert calls.count("Dispose:taskkill") == 1
    assert "Initialize-Wakes" not in calls


@pytest.mark.parametrize("budget", [0, "NaN", "Infinity", "-Infinity"])
def test_invalid_preparation_budget_never_launches_or_stops(tmp_path, budget):
    result, calls = _run_restart(tmp_path, "success", readiness_timeout_seconds=budget)
    assert "must be a finite value of at least 1" in _assert_failure(result)
    assert not any(call.startswith("Start-Process:") for call in calls)
    assert "Stop-ScheduledTask" not in calls and "Start-ScheduledTask" not in calls

@pytest.mark.parametrize("stop_only", [False, True])
@pytest.mark.parametrize("budget", [1, 2, 2.1])
def test_low_preparation_budget_preserves_running_service(tmp_path, stop_only, budget):
    result, calls = _run_restart(
        tmp_path, "success", readiness_timeout_seconds=budget,
        preparation_clock=True, stop_only=stop_only,
    )
    assert "cannot fit settlement before stopping" in _assert_failure(result)
    assert calls.count("Dispose:preflight") == 1
    assert "Stop-ScheduledTask" not in calls and "Start-ScheduledTask" not in calls
    assert "Sleep:2000" not in calls and "Initialize-Wakes" not in calls


@pytest.mark.parametrize("scenario,should_stop", [
    ("prep_sleep_exact_boundary", False), ("prep_sleep_just_fits", True),
])
def test_fixed_settlement_requires_strictly_more_than_two_seconds(tmp_path, scenario, should_stop):
    result, calls = _run_restart(tmp_path, scenario, preparation_clock=True)
    assert ("Stop-ScheduledTask" in calls) is should_stop
    if should_stop:
        assert result.returncode == 0, _output(result)
        assert calls.count("Sleep:2000") == 1
        init_wait, = [int(call.rsplit(":", 1)[1]) for call in calls if call.startswith("Wait:init:")]
        assert 0 < init_wait <= 2
    else:
        assert "cannot fit settlement before stopping" in _assert_failure(result)
        assert "Sleep:2000" not in calls and "Start-ScheduledTask" not in calls


def test_preparation_expiring_after_stop_does_not_begin_fixed_sleep(tmp_path):
    result, calls = _run_restart(tmp_path, "prep_expired_before_sleep", preparation_clock=True)
    assert "cannot fit the two-second settlement wait" in _assert_failure(result)
    assert "Stop-ScheduledTask" in calls and "Start-ScheduledTask" not in calls
    assert "Sleep:2000" not in calls and "Initialize-Wakes" not in calls
