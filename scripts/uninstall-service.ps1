<#
.SYNOPSIS
    Remove the Pallium scheduled task.

.EXAMPLE
    .\uninstall-service.ps1
#>

$ErrorActionPreference = "Stop"
$TaskName = "Pallium"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    # Stop if running
    if ($existing.State -eq "Running") {
        Stop-ScheduledTask -TaskName $TaskName
        Write-Host "Stopped running Pallium task."
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Pallium scheduled task removed."
} else {
    Write-Host "No Pallium scheduled task found."
}
