param(
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$sqliteUrl = & $python -c "from app.config import AppConfig; print(AppConfig.from_env().sqlite_url)" 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($sqliteUrl)) {
    throw "Failed to resolve sqlite_url from the current Pallium config."
}

$sqliteUrl = $sqliteUrl.Trim()
if (-not $sqliteUrl.StartsWith("sqlite:///")) {
    throw "Only sqlite URLs are supported by this reset script. Resolved sqlite_url: $sqliteUrl"
}

$rawPath = $sqliteUrl.Substring("sqlite:///".Length)
if ([string]::IsNullOrWhiteSpace($rawPath) -or $rawPath -eq ":memory:") {
    throw "The resolved sqlite_url does not point to a file-backed SQLite database."
}

if ([System.IO.Path]::IsPathRooted($rawPath)) {
    $dbPath = $rawPath
} else {
    $dbPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $rawPath))
}

$targets = @($dbPath, "$dbPath-wal", "$dbPath-shm")

if (-not $Quiet) {
    Write-Host "Resolved sqlite_url: $sqliteUrl"
    Write-Host "Deleting database files:"
    $targets | ForEach-Object { Write-Host "  $_" }
}

foreach ($target in $targets) {
    if (Test-Path $target) {
        Remove-Item -Force $target
    }
}

Write-Host "Development SQLite database reset complete."
