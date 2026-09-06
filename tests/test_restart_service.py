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

HARNESS = r'''
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
        Actions = @([pscustomobject]@{
            Execute = "wscript.exe"
            Arguments = '"' + $env:RW010_VBS + '"'
            WorkingDirectory = $workingDirectory
        })
    }
}

function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$Wait, [switch]$PassThru)
    Log-Call "Start-Process:$FilePath"
    if ($PSBoundParameters.ContainsKey("WorkingDirectory")) {
        Log-Call "PreflightWorkingDirectory:$WorkingDirectory"
    } else {
        Log-Call "PreflightWorkingDirectory:<omitted>"
    }
    $exitCode = if ($env:RW010_SCENARIO -eq "preflight_failure") { 7 } else { 0 }
    [pscustomobject]@{ ExitCode = $exitCode }
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

function taskkill {
    param([Parameter(ValueFromRemainingArguments = $true)]$Arguments)
    Log-Call ("taskkill " + ($Arguments -join " "))
}

function Get-NetTCPConnection {
    param($LocalPort, $State, $ErrorAction)
    Log-Call "Get-NetTCPConnection:$LocalPort"
    return $null
}

function Get-Process {
    param($Id, $ErrorAction)
    return $null
}

function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    if ($env:RW010_SCENARIO -eq "canonical_survivor" -and $Filter -like "*app.run service run*") {
        return [pscustomobject]@{ ProcessId = 4242; Name = "python.exe" }
    }
    if ($env:RW010_SCENARIO -eq "canonical_survivor" -and $Filter -like "*app.run mcp*") {
        return [pscustomobject]@{ ProcessId = 9999; Name = "python.exe" }
    }
    return @()
}

function Start-Sleep {
    param($Seconds, $Milliseconds)
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
    $script:QueueCalls++
    if ($env:RW010_SCENARIO -eq "terminal_queue" -or
        ($env:RW010_SCENARIO -eq "transient" -and $script:QueueCalls -eq 1)) {
        return [pscustomobject]@{ StatusCode = 503 }
    }
    [pscustomobject]@{ StatusCode = 204 }
}

$env:USERPROFILE = $env:RW010_HOME
& $env:RW010_SCRIPT
exit $LASTEXITCODE
'''


def _run_restart(
    tmp_path: Path,
    scenario: str,
    *,
    task_shape: str = "canonical",
    port: int | str | None = 21987,
    working_directory: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None, "PowerShell is required on Windows"

    call_log = tmp_path / "calls.log"
    harness = tmp_path / "harness.ps1"
    vbs = tmp_path / "launcher.vbs"
    harness.write_text(HARNESS, encoding="utf-8")
    if task_shape == "legacy":
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
    else:
        port_arg = "" if port is None else f" --port {port}"
        command = f'WshShell.Run """{sys.executable}"" -m app.run service run{port_arg}", 0, False\n'
    vbs.write_text('Set WshShell = CreateObject("WScript.Shell")\n' + command, encoding="ascii")

    env = os.environ.copy()
    env.update(
        RW010_CALL_LOG=str(call_log),
        RW010_HOME=str(tmp_path / "home"),
        RW010_SCENARIO=scenario,
        RW010_SCRIPT=str(RESTART_SCRIPT),
        RW010_TASK_SHAPE=task_shape,
        RW010_VBS=str(vbs),
        RW010_WORKDIR=(
            str(tmp_path / "missing")
            if task_shape == "invalid_workdir"
            else str(working_directory or tmp_path)
        ),
    )
    result = subprocess.run(
        [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(harness)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=15,
    )
    calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
    return result, calls


def _output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def _assert_failure(result: subprocess.CompletedProcess[str]) -> str:
    output = _output(result)
    assert result.returncode != 0
    assert "Pallium restarted." not in output
    assert ".pallium\\logs\\pallium.log" in output
    return output


def _assert_port(result: subprocess.CompletedProcess[str], calls: list[str], port: int) -> None:
    assert f"Get-NetTCPConnection:{port}" in calls
    assert f"URI:http://127.0.0.1:{port}/health" in calls
    assert f"URI:http://127.0.0.1:{port}/status" in calls
    assert f"URI:http://127.0.0.1:{port}/debug/queue/health" in calls
    assert f"http://127.0.0.1:{port}/dashboard" in _output(result)


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
    result, calls = _run_restart(tmp_path, "canonical_survivor")

    assert result.returncode == 0, _output(result)
    assert f"Start-Process:{sys.executable}" in calls
    assert "PreflightWorkingDirectory:<omitted>" in calls
    assert any(call.endswith("/PID 4242") for call in calls)
    assert not any("9999" in call for call in calls)
    _assert_port(result, calls, 21987)


def test_legacy_task_passes_exact_working_directory(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "ready", task_shape="legacy", port=21988)

    assert result.returncode == 0, _output(result)
    assert f"Start-Process:{Path(sys.executable).with_name('pythonw.exe')}" in calls
    assert f"PreflightWorkingDirectory:{tmp_path}" in calls
    _assert_port(result, calls, 21988)


def test_legacy_task_passes_unicode_working_directory_exactly(tmp_path: Path) -> None:
    working_directory = tmp_path / "תיקייה עם רווחים"
    working_directory.mkdir()

    result, calls = _run_restart(
        tmp_path,
        "ready",
        task_shape="legacy",
        port=21988,
        working_directory=working_directory,
    )

    assert result.returncode == 0, _output(result)
    assert f"PreflightWorkingDirectory:{working_directory}" in calls


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


def test_start_failure_is_nonzero_and_never_prints_success(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "start_failure")

    output = _assert_failure(result)
    assert "Failed to start the Pallium scheduled task" in output
    assert calls.count("Stop-ScheduledTask") == 1
    assert calls.count("Start-ScheduledTask") == 1


def test_transient_readiness_checks_all_contracts_before_success(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "transient")

    assert result.returncode == 0, _output(result)
    assert "Pallium restarted." in _output(result)
    assert calls.count("GET /health") == 5
    assert calls.count("GET /status") == 4
    assert calls.count("GET /debug/queue/health") == 2
    assert calls.count("Sleep:500") == 4


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
    result, calls = _run_restart(tmp_path, scenario)

    output = _assert_failure(result)
    assert "failed readiness after 20 attempts" in output
    assert last_check in output
    assert calls.count(last_endpoint) == 20
    assert calls.count("Sleep:500") == 19