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
# Resolve installed authority without substituting the calling checkout.
$timer = [Diagnostics.Stopwatch]::StartNew()
# Resolve the exact registered action and its existing installed controller.
# Synchronous native/filesystem calls may return late; check before each admission.
if (-not [Diagnostics.Stopwatch]::IsHighResolution) { throw "QPC clock required; no controller admission" }
$absoluteDeadline = ([Diagnostics.Stopwatch]::GetTimestamp() / [double][Diagnostics.Stopwatch]::Frequency) + $ReadinessTimeoutSeconds
function Assert-Admission {
    if (([Diagnostics.Stopwatch]::GetTimestamp() / [double][Diagnostics.Stopwatch]::Frequency) -ge $absoluteDeadline) {
        throw "transaction deadline elapsed; no controller/replacement admission"
    }
}
Assert-Admission
$scheduler = New-Object -ComObject Schedule.Service
$scheduler.Connect()
$task = $scheduler.GetFolder('\').GetTask('Pallium')
if ($task.Path -cne '\Pallium' -or $task.Definition.Actions.Count -ne 1 -or $task.Definition.Settings.RestartCount -ne 0) {
    throw "exact managed task identity required; no migration attempted"
}
$actionMetadata = $task.Definition.Actions.Item(1)
if ([IO.Path]::GetFileName($actionMetadata.Path) -ine 'wscript.exe' -or
    $actionMetadata.Arguments -notmatch '^"([^"\r\n]+)" "\$\(Arg0\)"$') {
    throw "unsupported legacy task action; no stop attempted"
}
$vbsPath = $Matches[1]
$text = [IO.File]::ReadAllText($vbsPath, [Text.Encoding]::Unicode)
if (-not $text.StartsWith("' Pallium cooperative launcher v1") -or $text -notmatch '--home\s+""([^"\r\n]+)""') {
    throw "unsupported launcher; no stop attempted"
}
$commandMatch = [regex]::Match($text, '(?m)^command = """([^"\r\n]+)"" -m app\.windows_service observe --home ""([^"\r\n]+)"""\r?$')
$cwdMatch = [regex]::Match($text, '(?m)^WshShell\.CurrentDirectory = "([^"\r\n]+)"\r?$')
if (-not $commandMatch.Success -or -not $cwdMatch.Success) {
    throw "installed launcher command/cwd cannot be verified"
}
$installedPython = $commandMatch.Groups[1].Value
$serviceHome = $commandMatch.Groups[2].Value
$manifest = [IO.File]::ReadAllText((Join-Path $serviceHome 'run\windows-launch.json'), [Text.Encoding]::UTF8) | ConvertFrom-Json
if ($manifest.version -ne 1 -or $manifest.home -cne $serviceHome -or $manifest.vbs -cne $vbsPath -or
    $manifest.python -cne $installedPython -or $manifest.cwd -cne $cwdMatch.Groups[1].Value -or
    $manifest.cwd -cne $actionMetadata.WorkingDirectory -or -not [IO.Path]::IsPathRooted($manifest.python) -or
    -not [IO.File]::Exists($manifest.python) -or -not [IO.Directory]::Exists($manifest.cwd)) {
    throw "installed controller authority mismatch; no development fallback"
}
Assert-Admission
$action = if ($StopOnly) { "stop" } else { "restart" }
$budget = $ReadinessTimeoutSeconds.ToString([Globalization.CultureInfo]::InvariantCulture)
$absolute = $absoluteDeadline.ToString('R', [Globalization.CultureInfo]::InvariantCulture)
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = $manifest.python
$start.Arguments = "-m app.windows_service $action --home `"$serviceHome`" --timeout $budget --deadline $absolute"
$start.WorkingDirectory = $manifest.cwd
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$controller = New-Object -TypeName System.Diagnostics.Process
$controller.StartInfo = $start
try {
    Assert-Admission
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
