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
    [pscustomobject]@{
        Actions = @([pscustomobject]@{
            Execute = "wscript.exe"
            Arguments = '"' + $env:RW010_VBS + '"'
            WorkingDirectory = $env:RW010_WORKDIR
        })
    }
}

function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$Wait, [switch]$PassThru)
    Log-Call "Start-Process"
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
    Log-Call "taskkill"
}

function Get-NetTCPConnection {
    param($LocalPort, $State, $ErrorAction)
    return $null
}

function Get-Process {
    param($Id, $ErrorAction)
    return $null
}

function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
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


def _run_restart(tmp_path: Path, scenario: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None, "PowerShell is required on Windows"

    call_log = tmp_path / "calls.log"
    harness = tmp_path / "harness.ps1"
    vbs = tmp_path / "launcher.vbs"
    harness.write_text(HARNESS, encoding="utf-8")
    vbs.write_text(
        f'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.Run """{sys.executable}"" -m app.run service run --port 19836", 0, False\n',
        encoding="ascii",
    )

    env = os.environ.copy()
    env.update(
        RW010_CALL_LOG=str(call_log),
        RW010_HOME=str(tmp_path / "home"),
        RW010_SCENARIO=scenario,
        RW010_SCRIPT=str(RESTART_SCRIPT),
        RW010_VBS=str(vbs),
        RW010_WORKDIR=str(tmp_path),
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


def test_preflight_failure_never_stops_the_healthy_service(tmp_path: Path) -> None:
    result, calls = _run_restart(tmp_path, "preflight_failure")

    output = _assert_failure(result)
    assert "import preflight failed with exit code 7" in output
    assert "Stop-ScheduledTask" not in calls
    assert "Stop-Process" not in calls
    assert "taskkill" not in calls


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