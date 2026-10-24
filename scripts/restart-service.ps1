<#
.SYNOPSIS
    Cooperatively control a newly generated managed Pallium Windows launcher.
    Legacy launchers are refused; installed metadata is never rewritten.
#>
param(
    [double]$ReadinessTimeoutSeconds = 180,
    [switch]$StopOnly
)
$ErrorActionPreference = "Stop"
if ($ReadinessTimeoutSeconds -lt 1 -or
    [double]::IsNaN($ReadinessTimeoutSeconds) -or
    [double]::IsInfinity($ReadinessTimeoutSeconds)) {
    [Console]::Error.WriteLine("ReadinessTimeoutSeconds must be finite and at least 1.")
    exit 1
}
# Metadata and identity reads belong to the bounded controller, not this shell.
$timer = [Diagnostics.Stopwatch]::StartNew()
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$action = if ($StopOnly) { "stop" } else { "restart" }
$budget = $ReadinessTimeoutSeconds.ToString([Globalization.CultureInfo]::InvariantCulture)
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = $pythonPath
$start.Arguments = "-m app.windows_service $action --timeout $budget"
$start.WorkingDirectory = $repoRoot
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$controller = New-Object -TypeName System.Diagnostics.Process
$controller.StartInfo = $start
try {
    if (-not $controller.Start()) { throw "controller did not start" }
    $stdout = $controller.StandardOutput.ReadToEndAsync()
    $stderr = $controller.StandardError.ReadToEndAsync()
    $remaining = [Math]::Max(0, $ReadinessTimeoutSeconds - $timer.Elapsed.TotalSeconds)
    if (-not $controller.WaitForExit([int][Math]::Min([int]::MaxValue, $remaining * 1000))) {
        # No kill: observer custody and active writes outlive a timed-out caller.
        throw "controller deadline elapsed; settlement UNKNOWN, no replacement permitted"
    }
    $remaining = [Math]::Max(0, $ReadinessTimeoutSeconds - $timer.Elapsed.TotalSeconds)
    if (-not [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($stdout, $stderr), [int][Math]::Min([int]::MaxValue, $remaining * 1000))) {
        throw "controller output deadline elapsed; settlement UNKNOWN"
    }
    [Console]::Out.Write($stdout.GetAwaiter().GetResult())
    [Console]::Error.Write($stderr.GetAwaiter().GetResult())
    exit $controller.ExitCode
} catch {
    [Console]::Error.WriteLine("Windows lifecycle refused/UNKNOWN: $($_.Exception.Message)")
    exit 1
} finally {
    $controller.Dispose()
}
