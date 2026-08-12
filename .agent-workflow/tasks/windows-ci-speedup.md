# Speed up the Windows CI test job

<!-- agent-workflow:start -->
**Outcome:** PR CI feedback is fast (~2 min) by keeping the full Windows suite off the per-PR critical path, while preserving Windows regression coverage: a fast Windows smoke on every PR + the full Windows matrix on push-to-main and nightly.

**Target:** rore/pallium — `.github/workflows/ci.yml` only.

**Scope:** `.github/workflows/ci.yml`. Restructure into three jobs: `test` (Ubuntu full matrix, PR+push), `windows-smoke` (Windows 3.13, curated Windows-sensitive path list, PR+push), `windows-full` (Windows full matrix, `if: github.event_name != 'pull_request'` — push-to-main + nightly `schedule`). Retain the Defender exclusion + pip cache. No test-code, test-selection-marker, or `pyproject.toml` changes.

**Constraints:** Do not reduce total test coverage (full Windows matrix still runs, just on push/nightly not PR). Do not touch guarded code paths. Defender step must be non-fatal. Smoke path list must reference only existing test paths.

**Completion criteria:** `ci.yml` parses as valid YAML; all smoke paths exist; PR runs `test` + `windows-smoke` only (no `windows-full`); push/nightly runs `windows-full`; CI green.

**Risk:** Routine

**Complexity:** Simple

**Reason:** `.github/workflows/ci.yml` is not a guarded path and not in the redline red/watch lists (closest analog: `scripts/**` = blue, local tooling). CI-config-only change; no product surface touched.

**Approach:** Split the single matrix job into Ubuntu-full (PR+push), Windows-smoke (curated path list, PR+push), and Windows-full (push+nightly via `if` + `schedule` cron). This takes the ~10 min Windows suite off the PR gate (PR feedback ~2 min) while a fast Windows smoke guards the OS-sensitive hotspots on every PR and the full matrix still runs post-merge and nightly.

**Verification:** Local — YAML parses; smoke test paths all exist on disk; job `if`/trigger wiring inspected. CI — on the PR, only `test` + `windows-smoke` run (windows-full skipped), green; confirm on a push-to-main / nightly that `windows-full` runs. Definitive PR-latency improvement measured by the PR run's wall time vs the ~10 min baseline.

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

## Probe result — lever 1 disproved, reverted

CI run 31613050924 with `-n 8` on Windows: **windows 3.13 failed.** `tests/test_codex_integration.py::test_codex_hooks_import_cleanly_as_subprocess[session_start.py]` hit `subprocess.TimeoutExpired` (10s) — the test spawns its own python subprocess and expects it within 10s; 8 pytest workers on a 4-vCPU runner oversubscribed the box and pushed that subprocess past its deadline. Oversubscription doesn't just fail to help, it **destabilizes** timeout-bound subprocess tests.

Reverted the `Run tests` step to the addopts default (`-n 4` both OSes). PR is back to the Defender-exclusion + pip-cache partial win (~17% on 3.13). The real lever remains in-memory SQLite for tests (separate, larger task); not pursued here.

## Final design — fast Windows regression on PR, full matrix on push/nightly

Developer chose: keep a fast Windows smoke on every PR, run the full Windows matrix on push-to-main + nightly. Restructured `ci.yml` into three jobs:
- `test` — Ubuntu {3.12, 3.13}, full suite, every PR + push + nightly (gates PRs, ~2 min).
- `windows-smoke` — Windows 3.13, curated 15-path Windows-sensitive set (supervisor/kill-tree, codex + claude-code hooks, asyncio-windows, snapshot×4, storage-sqlite, sqlite-write-retry, launch-token, config, runtime-logging), every PR + push.
- `windows-full` — Windows {3.12, 3.13}, full suite, `if: github.event_name != 'pull_request'` + nightly `schedule` cron (17 6 * * *).

Local verification: YAML parses; triggers = push/pull_request/schedule; `windows-full` correctly gated off PRs; all 15 smoke paths exist on disk.

**Coverage tradeoff (recorded):** a Windows-only regression outside the smoke set won't block a PR — it surfaces on push-to-main or nightly. Smoke path list lives in `ci.yml` and needs occasional curation as Windows-sensitive tests are added.

**Follow-up for humans:** if branch protection is later enabled, the required-check names change (`test (ubuntu-latest, 3.12/3.13)`, `windows-smoke`); do not require `windows-full` (it doesn't run on PRs).
