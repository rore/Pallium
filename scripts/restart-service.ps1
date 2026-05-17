<#
.SYNOPSIS
    Restart the Pallium Windows scheduled task service.

.EXAMPLE
    .\restart-service.ps1
#>

$ErrorActionPreference = "Stop"
$TaskName = "Pallium"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Error "Pallium scheduled task not found. Run install-service.ps1 first."
    exit 1
}

Write-Host "Stopping Pallium..."
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

# Kill the process tree — Stop-ScheduledTask only marks the task stopped,
# it doesn't kill the VBS → pythonw → supervisor → server process chain.
# Strategy 1: kill by listening port (normal case)
$Port = 19836
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $procId = $conn.OwningProcess
    Write-Host "  Killing process tree (PID $procId) on port $Port..."
    taskkill /F /T /PID $procId 2>$null | Out-Null
}

# Strategy 2: kill by PID file (handles WinError 64 stuck-socket where port is
# no longer in Listen state — process alive but accept loop dead)
$PidFile = "$env:USERPROFILE\.pallium\run\pallium.pid"
if (Test-Path $PidFile) {
    $filePid = [int](Get-Content $PidFile -ErrorAction SilentlyContinue)
    if ($filePid -and ($filePid -ne $conn.OwningProcess)) {
        $proc = Get-Process -Id $filePid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  Killing stale process tree (PID $filePid) from PID file..."
            taskkill /F /T /PID $filePid 2>$null | Out-Null
        }
    }
}

Start-Sleep -Seconds 2

Write-Host "Starting Pallium..."
Start-ScheduledTask -TaskName $TaskName

Write-Host "Pallium restarted. Dashboard at http://localhost:19836/dashboard"
