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

# Wait for process to exit
$maxWait = 10
for ($i = 0; $i -lt $maxWait; $i++) {
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    if ($info.LastTaskResult -ne 267009) { break }  # 267009 = task is running
    Start-Sleep -Seconds 1
}

Start-Sleep -Seconds 1

Write-Host "Starting Pallium..."
Start-ScheduledTask -TaskName $TaskName

Write-Host "Pallium restarted. Dashboard at http://localhost:19836/dashboard"
