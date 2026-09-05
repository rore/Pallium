<#
.SYNOPSIS
    Install Pallium as a Windows scheduled task that starts at logon.

.PARAMETER Port
    Port for Pallium HTTP server (default: 19836).

.PARAMETER PythonPath
    Path to Python executable. Auto-detected from current environment if not specified.

.EXAMPLE
    .\install-service.ps1
    .\install-service.ps1 -Port 19837
#>

param(
    [int]$Port = 19836,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$TaskName = "Pallium"

# Detect Python
if (-not $PythonPath) {
    $PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PythonPath) {
        $PythonPath = (Get-Command python3 -ErrorAction SilentlyContinue).Source
    }
    if (-not $PythonPath) {
        Write-Error "Python not found. Specify -PythonPath or ensure Python is on PATH."
        exit 1
    }
}

# Detect repo root (directory containing this script's parent)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

if (-not (Test-Path (Join-Path $RepoRoot "app\run.py"))) {
    Write-Error "Cannot find app\run.py in $RepoRoot. Run this script from the Pallium repo."
    exit 1
}

Write-Host "Installing Pallium service..."
Write-Host "  Python: $PythonPath"
Write-Host "  Repo:   $RepoRoot"
Write-Host "  Port:   $Port"

# Service data directory — isolated from dev DB
$DataDir = Join-Path $env:USERPROFILE ".pallium\data"
if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
}
$SqliteUrl = "sqlite:///$DataDir/pallium.db"
$VectorIndexPath = "$DataDir/vector_index"
Write-Host "  Data:   $DataDir"

# Remove existing task if present (idempotent)
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "  Removed existing scheduled task."
}

# Create launcher script that sets env vars and starts Pallium
$LauncherDir = Join-Path $env:USERPROFILE ".pallium"
$LauncherPath = Join-Path $LauncherDir "service_launcher.py"
$LauncherContent = @"
import os, sys
os.environ["PALLIUM_SQLITE_URL"] = "$($SqliteUrl -replace '\\', '/')"
os.environ["PALLIUM_VECTOR_INDEX_PATH"] = "$($VectorIndexPath -replace '\\', '/')"
sys.path.insert(0, r"$RepoRoot")
from app.run import run
raise SystemExit(run(["all", "--port", "$Port"]))
"@
Set-Content -Path $LauncherPath -Value $LauncherContent -Encoding UTF8
Write-Host "  Wrote launcher: $LauncherPath"

# VBScript wrapper — wscript.exe + SW_HIDE (0) guarantees no console window,
# more reliable than pythonw.exe on Windows venvs.
$PythonwPath = Join-Path (Split-Path $PythonPath) "pythonw.exe"
if (-not (Test-Path $PythonwPath)) {
    $PythonwPath = $PythonPath
}
$VbsPath = Join-Path $LauncherDir "service_launcher.vbs"
$VbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """$PythonwPath"" ""$LauncherPath""", 0, False
"@
[System.IO.File]::WriteAllText($VbsPath, $VbsContent, [System.Text.Encoding]::ASCII)
Write-Host "  Wrote VBS launcher: $VbsPath"

# Task action: wscript.exe runs the VBS silently (SW_HIDE is baked into the VBS)
$Action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "`"$VbsPath`"" `
    -WorkingDirectory $RepoRoot

# Trigger at logon
$Trigger = New-ScheduledTaskTrigger -AtLogOn

# Settings: restart on failure, don't stop on idle, run indefinitely, no window
$Settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Days 0) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -Hidden

# Register the task (runs as current user)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -RunLevel Limited `
    -Description "Pallium local agent service" | Out-Null

Write-Host ""
Write-Host "Pallium scheduled task installed. It will start at next logon."
Write-Host "To start now: Start-ScheduledTask -TaskName '$TaskName'"
