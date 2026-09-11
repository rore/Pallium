param(
    [ValidateSet("claude", "codex", "opencode")]
    [string]$Runtime = "codex",
    [ValidateSet("guard", "seed")]
    [string]$Action = "guard",
    [string]$HookInput
)

$repoRoot = (git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) { exit 0 }
$script = Join-Path $repoRoot "scripts/agent-workflow-runtime.py"
if (-not (Test-Path -LiteralPath $script)) {
    [Console]::Error.WriteLine("[agent-workflow] DEGRADED: runtime script missing; final CI remains authoritative")
    exit 0
}

$localPython = Join-Path $repoRoot ".venv/Scripts/python.exe"
if (Test-Path -LiteralPath $localPython) {
    $command = $localPython
    $prefix = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $command = "py"
    $prefix = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $command = "python"
    $prefix = @()
} else {
    [Console]::Error.WriteLine("[agent-workflow] DEGRADED: Python unavailable; final CI remains authoritative")
    exit 0
}

$arguments = @($script, "--runtime", $Runtime)
if ($Action -eq "seed") { $arguments += "--seed" }
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$inputText = if ($PSBoundParameters.ContainsKey("HookInput")) { $HookInput } else { [Console]::In.ReadToEnd() }
$inputText | & $command @prefix @arguments
$childExit = $LASTEXITCODE
if ($Action -eq "seed" -or $childExit -eq 0 -or $childExit -eq 2) { exit $childExit }
[Console]::Error.WriteLine("[agent-workflow] DENY: runtime adapter failed with exit $childExit")
exit 2