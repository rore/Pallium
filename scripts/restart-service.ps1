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

# Strategy 3: kill by commandline signature — catches the supervisor, its
# child processor/cleaner/snapshot subprocesses, and the MCP subprocess,
# even when the parent chain was severed by the wscript → pythonw
# fire-and-forget launcher pattern. Strategies 1 and 2 alone leave the
# supervisor + processor + cleaner alive; those processes have their own
# imported-module cache and continue running stale code across a
# scheduled-task restart, silently defeating the "restart to deploy new
# code" invariant. See scripts/restart-service.md for the failure mode
# that motivated this addition.
Write-Host "  Sweeping surviving Pallium subprocesses by commandline..."
$signatures = @(
    "service_launcher.py",
    "app.processor",
    "app.cleaner",
    "app.snapshot",
    "app.run serve",
    "app.run mcp",
    "app.run all"
)
foreach ($sig in $signatures) {
    # Escape wildcards for Get-CimInstance WQL LIKE
    $pattern = "%{0}%" -f $sig
    # Match both python.exe (foreground console) and pythonw.exe (background,
    # what the installed service uses via wscript.exe launcher). Without the
    # pythonw branch, the scheduled-task service is never swept.
    $procs = Get-CimInstance Win32_Process `
        -Filter "(Name='python.exe' OR Name='pythonw.exe') AND CommandLine LIKE '$pattern'" `
        -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        Write-Host "    Killing PID $($p.ProcessId) ($($p.Name) $sig)..."
        taskkill /F /T /PID $p.ProcessId 2>$null | Out-Null
    }
}

Start-Sleep -Seconds 2

Write-Host "Starting Pallium..."
Start-ScheduledTask -TaskName $TaskName

Write-Host "Pallium restarted. Dashboard at http://localhost:19836/dashboard"
