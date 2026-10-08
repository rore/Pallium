from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows script host required")

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install-service.ps1"


def test_powershell_launcher_waits_and_propagates_child_status(tmp_path: Path) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    cscript = shutil.which("cscript.exe")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    assert powershell and cscript and pythonw.exists()

    profile = tmp_path / "Профиль with spaces"
    profile.mkdir()
    harness = tmp_path / "install-harness.ps1"
    harness.write_text(
        r'''
function Get-ScheduledTask { param($TaskName, $ErrorAction) return $null }
function Unregister-ScheduledTask { param($TaskName, $Confirm) }
function New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory); [pscustomobject]@{} }
function New-ScheduledTaskTrigger { param([switch]$AtLogOn); [pscustomobject]@{} }
function New-ScheduledTaskSettingsSet {
    param($RestartCount, $RestartInterval, [switch]$DontStopOnIdleEnd, $ExecutionTimeLimit,
          [switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries, [switch]$Hidden)
    [pscustomobject]@{}
}
function Register-ScheduledTask { param($TaskName, $Action, $Trigger, $Settings, $RunLevel, $Description) }
& $env:PALLIUM_INSTALL_SCRIPT -PythonPath $env:PALLIUM_TEST_PYTHON
''',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        USERPROFILE=str(profile),
        HOME=str(profile),
        APPDATA=str(profile / "AppData" / "Roaming"),
        PALLIUM_HOME=str(profile / ".pallium"),
        PALLIUM_CONFIG_FILE=str(profile / "config.toml"),
        PALLIUM_ENV_FILE=str(profile / ".env"),
        PALLIUM_SNAPSHOT_ENABLED="false",
        PALLIUM_INSTALL_SCRIPT=str(INSTALL_SCRIPT),
        PALLIUM_TEST_PYTHON=sys.executable,
    )
    installed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(harness)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr

    launcher = profile / ".pallium" / "service_launcher.py"
    vbs = profile / ".pallium" / "service_launcher.vbs"
    launcher.write_text(
        'import os, time\n'
        'time.sleep(float(os.environ["PALLIUM_TEST_DELAY"]))\n'
        'raise SystemExit(int(os.environ["PALLIUM_TEST_STATUS"]))\n',
        encoding="utf-8",
    )
    raw_vbs = vbs.read_bytes()
    vbs_text = vbs.read_text(encoding="utf-16")
    assert raw_vbs.startswith(b"\xff\xfe")
    assert str(profile) in vbs_text
    assert ", 0, True)" in vbs_text

    for status in (0, 7):
        launch_env = env | {
            "PALLIUM_TEST_DELAY": "0.5",
            "PALLIUM_TEST_STATUS": str(status),
        }
        started = time.monotonic()
        result = subprocess.run(
            [cscript, "//nologo", str(vbs)],
            cwd=REPO_ROOT,
            env=launch_env,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert result.returncode == status, result.stdout + result.stderr
        assert time.monotonic() - started >= 0.4


def test_cli_generated_launcher_runs_private_stub_and_returns_status(tmp_path: Path, monkeypatch) -> None:
    import importlib

    home = tmp_path / "Домашний каталог with spaces"
    run_dir = home / "run"
    run_dir.mkdir(parents=True)
    env = {
        "HOME": str(tmp_path / "profile"),
        "USERPROFILE": str(tmp_path / "profile"),
        "PALLIUM_HOME": str(home),
        "PALLIUM_CONFIG_FILE": str(tmp_path / "config.toml"),
        "PALLIUM_ENV_FILE": str(tmp_path / ".env"),
        "PALLIUM_STORAGE_BACKEND": "memory",
        "PALLIUM_SNAPSHOT_ENABLED": "false",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    service = importlib.import_module("app.cli.service")
    with monkeypatch.context() as patcher:
        patcher.setattr(
            service.subprocess,
            "run",
            lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 0, "", ""),
        )
        service._install_windows("pallium", 21987, home)

    vbs = run_dir / "pallium_launcher.vbs"
    text = vbs.read_text(encoding="utf-16")
    assert str(home) in text
    assert ", 0, True)" in text
    stub_root = tmp_path / "private app cwd"
    package = stub_root / "app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        'import sys\n'
        'assert not {"app.cli.service", "app.supervisor", "app.main"}.intersection(sys.modules)\n',
        encoding="utf-8",
    )
    (package / "run.py").write_text(
        'import os, sys, time\n'
        'assert not {"app.cli.service", "app.supervisor", "app.main"}.intersection(sys.modules)\n'
        'time.sleep(float(os.environ["PALLIUM_TEST_DELAY"]))\n'
        'raise SystemExit(int(os.environ["PALLIUM_TEST_STATUS"]))\n',
        encoding="utf-8",
    )
    assert (package / "run.py").resolve().is_relative_to(stub_root.resolve())
    cscript = shutil.which("cscript.exe")
    assert cscript

    for status in (0, 7):
        launch_env = os.environ.copy() | {
            "PALLIUM_TEST_DELAY": "0.5",
            "PALLIUM_TEST_STATUS": str(status),
            "PYTHONPATH": str(stub_root),
            "PYTHONSAFEPATH": "1",
        }
        launch_env.pop("PYTHONHOME", None)
        started = time.monotonic()
        result = subprocess.run(
            [cscript, "//nologo", str(vbs)],
            cwd=stub_root,
            env=launch_env,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert result.returncode == status, result.stdout + result.stderr
        assert time.monotonic() - started >= 0.4
