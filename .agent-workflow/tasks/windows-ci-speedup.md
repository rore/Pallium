# Speed up the Windows CI test job

<!-- agent-workflow:start -->
**Outcome:** The Windows `test` matrix jobs in `.github/workflows/ci.yml` complete materially faster (target: closer to the ~2 min Ubuntu jobs, down from ~10–11 min) without changing what is tested or reducing coverage.

**Target:** rore/pallium — `.github/workflows/ci.yml` only.

**Scope:** `.github/workflows/ci.yml`. Add a Windows-only step that excludes the workspace + runner temp dirs from Windows Defender real-time scanning, and enable pip caching on `actions/setup-python`. No changes to test code, test selection, matrix dimensions, or `pyproject.toml` addopts.

**Constraints:** Do not reduce test coverage (no matrix trimming, no `-m` change). Do not touch guarded code paths. Windows Defender step must be Windows-only (`if: runner.os == 'Windows'`) and must not fail the job if the exclusion cmdlet is unavailable. Do not execute `Add-MpPreference` on the local dev machine — local verification is syntax/parse-only.

**Completion criteria:** `ci.yml` parses as valid YAML; the Windows Defender step's PowerShell parses without error; the CI run on the PR shows the Windows `test` jobs faster than the current ~10 min baseline with the same test count and green result.

**Risk:** Routine

**Complexity:** Simple

**Reason:** `.github/workflows/ci.yml` is not a guarded path and not in the redline red/watch lists (closest analog: `scripts/**` = blue, local tooling). CI-config-only change; no product surface touched.

**Approach:** In the `test` job add (1) `cache: pip` + `cache-dependency-path: pyproject.toml` on `actions/setup-python@v5`, and (2) a Windows-only pre-install step running `Add-MpPreference -ExclusionPath` for `${{ github.workspace }}` and `$env:RUNNER_TEMP`, wrapped so a failure is non-fatal. Root cause: every test builds a fresh SQLite DB in `tmp_path`; Defender real-time scanning of that file churn is the dominant Windows-only cost.

**Verification:** Local — `yaml.safe_load(ci.yml)` parses; PowerShell `[Parser]::ParseInput` on the Defender step parses clean (no execution). CI — the `test (windows-latest, *)` jobs on the PR finish faster than the ~10 min baseline, green, same collected test count. True speedup can only be proven by the CI run (no local GitHub-Windows-runner equivalent).

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Edited `.github/workflows/ci.yml` `test` job: added `cache: pip` + `cache-dependency-path: pyproject.toml` to `actions/setup-python@v5`, and a Windows-only step (`if: runner.os == 'Windows'`, `shell: pwsh`) that runs `Add-MpPreference -ExclusionPath` for `${{ github.workspace }}` and `$env:RUNNER_TEMP`, wrapped in try/catch so an unavailable cmdlet degrades to a `::warning::` instead of failing the job.

## Evidence (local verification)

Ran on the local Windows dev machine — no `Add-MpPreference` executed (would mutate the machine's real Defender config); checks are parse/structure only.

- **YAML valid**: `yaml.safe_load(ci.yml)` parses; step order is checkout → setup-python(cache) → Defender(win-only) → install → test; matrix unchanged (`{ubuntu,windows} × {3.12,3.13}`); `setup-python` `with` = `{python-version, cache: pip, cache-dependency-path: pyproject.toml}`.
- **PowerShell parses clean**: post-substitution run block fed to `[Parser]::ParseInput` → 0 syntax errors.
- **Cmdlet real**: `Get-Command Add-MpPreference` → present (confirms cmdlet + `-ExclusionPath` param are valid).
- **Not locally provable**: the actual Windows speedup can only be measured by the PR's CI run — there is no local GitHub-Windows-runner equivalent. Definitive check = compare `test (windows-latest, *)` wall time vs the ~10 min baseline, same collected test count, green.
