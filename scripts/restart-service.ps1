<#
.SYNOPSIS
    Restart the Pallium Windows scheduled task service.

.EXAMPLE
    .\restart-service.ps1
#>

$ErrorActionPreference = "Stop"
$TaskName = "Pallium"
$ServiceHome = "$env:USERPROFILE\.pallium"
$LogPath = "$ServiceHome\logs\pallium.log"

function Stop-WithError([string]$Message) {
    [Console]::Error.WriteLine("Error: $Message")
    [Console]::Error.WriteLine("Pallium log: $LogPath")
    exit 1
}

function Stop-ProcessTree([int]$ProcessId) {
    $failed = $false
    try {
        taskkill /F /T /PID $ProcessId 2>$null | Out-Null
        $failed = $LASTEXITCODE -ne 0
    } catch {
        $failed = $true
    }
    if ($failed) {
        Write-Host "    taskkill reported a partial failure for PID $ProcessId; continuing cleanup verification..."
    }
}

function Get-ListenerPids([int]$Port) {
    @(
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { $_.OwningProcess } |
            Where-Object { $_ } |
            Sort-Object -Unique
    )
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Stop-WithError "Pallium scheduled task not found. Run 'pallium service install' first."
}

$action = @($task.Actions)[0]
if (-not $action -or [IO.Path]::GetFileName($action.Execute) -ine "wscript.exe") {
    Stop-WithError "Installed Pallium task does not contain the expected wscript.exe action."
}

$workingDir = [Environment]::ExpandEnvironmentVariables(([string]$action.WorkingDirectory).Trim())
$vbsPath = [Environment]::ExpandEnvironmentVariables(([string]$action.Arguments).Trim().Trim('"'))
if ($workingDir -and -not (Test-Path -LiteralPath $workingDir)) {
    Stop-WithError "Installed task working directory is missing or invalid: $workingDir"
}
if (-not $vbsPath -or -not (Test-Path -LiteralPath $vbsPath)) {
    Stop-WithError "Installed task launcher is missing or invalid: $vbsPath"
}

$vbs = Get-Content -Raw -LiteralPath $vbsPath
$homeMatch = [regex]::Match($vbs, '--home\s+""([^"\r\n]+)""', [Text.RegularExpressions.RegexOptions]::IgnoreCase)
if ($homeMatch.Success) {
    $ServiceHome = $homeMatch.Groups[1].Value
    $LogPath = "$ServiceHome\logs\pallium.log"
}
$pythonMatch = [regex]::Match(
    $vbs,
    'WshShell\.Run\s+"""([^"\r\n]+pythonw?\.exe)""',
    [Text.RegularExpressions.RegexOptions]::IgnoreCase
)
$pythonPath = if ($pythonMatch.Success) {
    [Environment]::ExpandEnvironmentVariables($pythonMatch.Groups[1].Value)
} else {
    ""
}
if (-not $pythonPath -or -not (Test-Path -LiteralPath $pythonPath)) {
    Stop-WithError "Could not resolve the installed Python executable from $vbsPath"
}

$portMatch = [regex]::Match(
    $vbs,
    'WshShell\.Run\s+"""[^"\r\n]+pythonw?\.exe""\s+-m\s+app\.run\s+service\s+run\b[^"\r\n]*?--port\s+([^\s",]+)',
    [Text.RegularExpressions.RegexOptions]::IgnoreCase
)
if ($portMatch.Success -and -not $homeMatch.Success) {
    Stop-WithError "Could not resolve the installed service home from canonical launcher metadata in $vbsPath"
}
$portText = if ($portMatch.Success) { $portMatch.Groups[1].Value } else { "" }
if (-not $portText) {
    $launcherMatch = [regex]::Match(
        $vbs,
        'WshShell\.Run\s+"""[^"\r\n]+pythonw?\.exe""\s+""([^"\r\n]+\.py)""',
        [Text.RegularExpressions.RegexOptions]::IgnoreCase
    )
    if ($launcherMatch.Success) {
        $launcherPath = [Environment]::ExpandEnvironmentVariables($launcherMatch.Groups[1].Value)
        if (Test-Path -LiteralPath $launcherPath) {
            $launcher = Get-Content -Raw -LiteralPath $launcherPath
            $portMatch = [regex]::Match(
                $launcher,
                '["'']--port["'']\s*,\s*["'']([^"'']+)["'']',
                [Text.RegularExpressions.RegexOptions]::IgnoreCase
            )
            if ($portMatch.Success) {
                $portText = $portMatch.Groups[1].Value
            }
        }
    }
}

[int]$Port = 0
if (-not [int]::TryParse($portText, [ref]$Port) -or $Port -lt 1 -or $Port -gt 65535) {
    Stop-WithError "Could not resolve a valid installed service port (1..65535) from $vbsPath"
}
try {
    $preflightArgs = @{
        FilePath = $pythonPath
        ArgumentList = '-c "import app.run, app.main"'
        WindowStyle = "Hidden"
        Wait = $true
        PassThru = $true
    }
    if ($workingDir) {
        $preflightArgs.WorkingDirectory = $workingDir
    }
    $preflight = Start-Process @preflightArgs
} catch {
    Stop-WithError "Installed service import preflight could not run: $($_.Exception.Message)"
}
if ($preflight.ExitCode -ne 0) {
    Stop-WithError "Installed service import preflight failed with exit code $($preflight.ExitCode); the running service was not stopped."
}

Write-Host "Stopping Pallium..."
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

# Kill the process tree — Stop-ScheduledTask only marks the task stopped,
# it doesn't kill the VBS → pythonw → supervisor → server process chain.
# Strategy 1: kill by listening port (normal case)
$listenerPids = @(Get-ListenerPids $Port)
foreach ($procId in $listenerPids) {
    Write-Host "  Killing process tree (PID $procId) on port $Port..."
    Stop-ProcessTree ([int]$procId)
}

# Strategy 2: kill by PID file (handles WinError 64 stuck-socket where port is
# no longer in Listen state — process alive but accept loop dead)
$PidFile = "$ServiceHome\run\pallium.pid"
if (Test-Path $PidFile) {
    $filePid = [int](Get-Content $PidFile -ErrorAction SilentlyContinue)
    if ($filePid -and ($filePid -notin $listenerPids)) {
        $proc = Get-Process -Id $filePid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  Killing stale process tree (PID $filePid) from PID file..."
            Stop-ProcessTree $filePid
        }
    }
}

# Strategy 3: kill by commandline signature — catches the supervisor and its
# processor/cleaner/snapshot subprocesses even when the parent chain was
# severed by the wscript → pythonw fire-and-forget launcher pattern.
# Standalone `app.run mcp` processes are client-owned stdio bridges; killing
# one disconnects its Codex task permanently, so service restart leaves them
# running. They proxy the newly started HTTP service without stale service code.
Write-Host "  Sweeping surviving Pallium subprocesses by commandline..."
$signatures = @(
    "service_launcher.py",
    "app.processor",
    "app.cleaner",
    "app.snapshot",
    "app.run serve",
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
        Stop-ProcessTree $p.ProcessId
    }
}

$servicePattern = "%app.run service run%"
$servicePortPattern = '(?i)(?:^|\s)--port\s+{0}(?=\s|$)' -f [regex]::Escape($Port.ToString())
$serviceProcs = Get-CimInstance Win32_Process `
    -Filter "(Name='python.exe' OR Name='pythonw.exe') AND CommandLine LIKE '$servicePattern'" `
    -ErrorAction SilentlyContinue
foreach ($p in $serviceProcs) {
    if ($p.CommandLine -notmatch $servicePortPattern) {
        continue
    }
    Write-Host "    Killing PID $($p.ProcessId) ($($p.Name) app.run service run on port $Port)..."
    Stop-ProcessTree $p.ProcessId
}

Start-Sleep -Seconds 2

$remainingPids = @(Get-ListenerPids $Port)
if ($remainingPids.Count -gt 0) {
    $pidDetail = "; listener PID(s): $($remainingPids -join ', ')"
    Stop-WithError "Could not stop Pallium; port $Port is still listening$pidDetail"
}

Write-Host "Starting Pallium..."
try {
    Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
} catch {
    Stop-WithError "Failed to start the Pallium scheduled task: $($_.Exception.Message)"
}

$BaseUrl = "http://127.0.0.1:$Port"
$ready = $false
$lastCheck = "service did not become ready"
for ($attempt = 1; $attempt -le 20; $attempt++) {
    try {
        $lastCheck = "/health request"
        $health = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 2
        if ($health.status -ne "ok") {
            $lastCheck = "/health status=$($health.status)"
            throw $lastCheck
        }

        $lastCheck = "/status request"
        $status = Invoke-RestMethod -Uri "$BaseUrl/status" -TimeoutSec 2
        if ($status.embedding_provider_ok -ne $true) {
            $lastCheck = "/status embedding_provider_ok=$($status.embedding_provider_ok)"
            throw $lastCheck
        }
        if ($status.ingestion.status -ne "ok") {
            $lastCheck = "/status ingestion.status=$($status.ingestion.status)"
            throw $lastCheck
        }

        $lastCheck = "/debug/queue/health request"
        $queue = Invoke-WebRequest -Uri "$BaseUrl/debug/queue/health" -UseBasicParsing -TimeoutSec 2
        if ($queue.StatusCode -lt 200 -or $queue.StatusCode -ge 300) {
            $lastCheck = "/debug/queue/health HTTP $($queue.StatusCode)"
            throw $lastCheck
        }

        $ready = $true
        break
    } catch {
        if ($_.Exception.Message -ne $lastCheck) {
            $lastCheck = "{0}: {1}" -f $lastCheck, $_.Exception.Message
        }
        if ($attempt -lt 20) {
            Start-Sleep -Milliseconds 500
        }
    }
}

if (-not $ready) {
    Stop-WithError "Pallium failed readiness after 20 attempts; last check: $lastCheck"
}

Write-Host "Pallium restarted. Dashboard at $BaseUrl/dashboard"
exit 0
