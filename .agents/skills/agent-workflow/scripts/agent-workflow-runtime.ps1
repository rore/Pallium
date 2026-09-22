[CmdletBinding(PositionalBinding=$false)]
param(
    [Parameter(Position=0)]
    [ValidateSet("claude", "codex", "opencode")]
    [string]$Runtime = "codex",
    [Parameter(Position=1)]
    [ValidateSet("guard", "seed", "check")]
    [string]$Action = "guard",
    [Parameter()]
    [string]$HookInput,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$CheckerArgs
)

function Exit-Unavailable([string]$Reason) {
    if ($Action -eq "check") {
        [Console]::Error.WriteLine("[agent-workflow] ERROR: $Reason")
        exit 2
    }
    [Console]::Error.WriteLine("[agent-workflow] DEGRADED: $Reason; final CI remains authoritative")
    exit 0
}

$repoRoot = (git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) { Exit-Unavailable "git repository unavailable" }
$scriptName = if ($Action -eq "check") { "agent-workflow-check.py" } else { "agent-workflow-runtime.py" }
$script = Join-Path $repoRoot "scripts/$scriptName"
if (-not (Test-Path -LiteralPath $script)) {
    Exit-Unavailable "$scriptName missing"
}

$localPython = Join-Path $repoRoot ".venv/Scripts/python.exe"
if ($env:PYTHON) {
    $command = $env:PYTHON
    $prefix = @()
} elseif (Test-Path -LiteralPath $localPython) {
    $command = $localPython
    $prefix = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $command = "py"
    $prefix = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $command = "python"
    $prefix = @()
} else {
    Exit-Unavailable "Python 3.11+ unavailable; install or select it, or set PYTHON to one executable path"
}

$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

if ($Action -eq "check") {
    try {
        $probe = @(& $command @prefix -c "import sys; assert sys.version_info >= (3, 11); print('agent-workflow-python-3.11')" 2>$null)
        if ($LASTEXITCODE -ne 0 -or $probe.Count -ne 1 -or $probe[0].Trim() -ne "agent-workflow-python-3.11") {
            Exit-Unavailable "selected Python unavailable or older than 3.11: $command; install or select Python 3.11+, or set PYTHON to one executable path"
        }
        & $command @prefix $script @CheckerArgs
        $childExit = $LASTEXITCODE
    } catch {
        [Console]::Error.WriteLine("[agent-workflow] ERROR: Python unavailable: $command; install or select Python 3.11+, or set PYTHON to one executable path")
        exit 2
    }
    if ($childExit -eq 0 -or $childExit -eq 1 -or $childExit -eq 2) { exit $childExit }
    [Console]::Error.WriteLine("[agent-workflow] ERROR: checker failed with exit $childExit")
    exit 2
}

$arguments = @($script, "--runtime", $Runtime)
if ($Action -eq "seed") { $arguments += "--seed" }
$inputText = if ($PSBoundParameters.ContainsKey("HookInput")) { $HookInput } else { [Console]::In.ReadToEnd() }
$inputText | & $command @prefix @arguments
$childExit = $LASTEXITCODE
if ($Action -eq "seed" -or $childExit -eq 0 -or $childExit -eq 2) { exit $childExit }
[Console]::Error.WriteLine("[agent-workflow] DENY: runtime adapter failed with exit $childExit")
exit 2