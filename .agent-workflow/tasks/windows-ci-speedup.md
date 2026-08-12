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

- Edited `.github/workflows/ci.yml` `test` job: added `cache: pip` + `cache-dependency-path: pyproject.toml` to `actions/setup-python@v5`, and a Windows-only step (`if: runner.os == 'Windows'`, `shell: pwsh`) that runs `Add-MpPreference -ExclusionPath` for `${{ github.workspace }}` and `$env:RUNNER_TEMP`, non-fatal via per-path try/catch.
- Opened PR #6; CI run 31611370742 completed green.

## Evidence (CI measurement — the definitive check)

The Defender step **applied cleanly** on both Windows jobs (logged "Defender exclusions added…", no `::warning::`). Yet:

| Job | pytest self-timed, baseline | pytest self-timed, with fix |
|---|---|---|
| ubuntu (3.12 / 3.13) | ~84–90s | ~84–90s |
| windows-latest 3.13 | ~618s | **513s** |
| windows-latest 3.12 | ~618s | **624s** |

pip cache: install 42s → 38s (cold-miss on first run; negligible).

## Assumption failure — the plan's premise was wrong

**Recorded assumption (Approach):** Windows Defender real-time scanning of per-test SQLite temp files is the *dominant* Windows cost.

**Disproved by:** exclusion applied successfully but yielded only ~17% on 3.13 and ~0% on 3.12 (within variance). The ~6× gap is real in-pytest execution time (513–624s vs ~90s), pointing at NTFS file I/O for thousands of per-test SQLite DB create/open/close ops + per-worker native imports — costs Defender exclusion does not remove.

**Returned to planning.** The Defender + pip-cache change is harmless and a small partial win, but does not meet the Outcome (close the gap with Ubuntu). Candidate next levers, pending developer direction on scope/risk:
1. In-memory SQLite (`sqlite:///:memory:`) for tests that don't need a file DB — highest-confidence lever (removes the file I/O), but touches `tests/**`/conftest and carries behavior risk (WAL, snapshot/cross-connection tests). Separate, larger task.
2. Oversubscribe xdist workers on Windows (`-n 8`) — cheap one-line CI probe; helps only if the suite is I/O-bound (waiting), not CPU-bound.
3. Pragmatic matrix reduction — run Windows on fewer Python versions / nightly only; cost reduction, not a real speedup.

## Decision (lever 1 chosen)

Developer chose the cheap probe. Windows `test` jobs now run `pytest -n 8` (Ubuntu stays `-n 4` via addopts). Rationale: the Windows cost is largely blocking file-I/O; oversubscribing past the 4 vCPUs can hide that latency for a one-line change. If the probe doesn't land, escalate to lever 1's in-memory-SQLite fix as a separate task. Defender exclusion + pip cache retained as a harmless partial win.

**Verification:** compare `test (windows-latest, *)` pytest self-time on the next CI run vs this run's 513–624s baseline.
