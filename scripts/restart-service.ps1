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
$Port = 19836
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $pid = $conn.OwningProcess
    Write-Host "  Killing process tree (PID $pid) on port $Port..."
    taskkill /F /T /PID $pid 2>$null | Out-Null
}

Start-Sleep -Seconds 2

Write-Host "Starting Pallium..."
Start-ScheduledTask -TaskName $TaskName

Write-Host "Pallium restarted. Dashboard at http://localhost:19836/dashboard"
