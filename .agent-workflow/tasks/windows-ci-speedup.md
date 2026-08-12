# Speed up the Windows CI test job

<!-- agent-workflow:start -->
**Outcome:** PR CI feedback is fast (~2 min) by keeping the full Windows suite off the per-PR critical path, while preserving Windows regression coverage: a fast Windows smoke on every PR + the full Windows matrix on push-to-main and nightly.

**Target:** rore/pallium — `.github/workflows/ci.yml` only.

**Scope:** `.github/workflows/ci.yml`. Restructure into three jobs: `test` (Ubuntu full matrix, PR+push), `windows-smoke` (Windows 3.13, curated Windows-sensitive path list, PR+push), `windows-full` (Windows full matrix, `if: github.event_name != 'pull_request'` — push-to-main + nightly `schedule`). Retain the Defender exclusion + pip cache. No test-code, test-selection-marker, or `pyproject.toml` changes.

**Constraints:** Do not reduce total test coverage (full Windows matrix still runs, just on push/nightly not PR). Do not touch guarded code paths. Defender step must be non-fatal. Smoke path list must reference only existing test paths.

**Completion criteria:** `ci.yml` parses as valid YAML; all smoke paths exist; PR runs `test` + `windows-smoke` only (no `windows-full`); push/nightly runs `windows-full`; CI green including the `agent-workflow` + `redline` gates.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Redline classified the final diff as GRAY — both changed paths (`.github/workflows/ci.yml` and this Work Record) are unmatched by the policy's red/blue/watch lists and default to gray. Per the risk table, any gray path → Elevated. (My initial `Routine` call assumed ci.yml would map to blue like `scripts/**`; CI re-classification on the real diff corrected it. Complexity remains Simple — one config file.)

**Discovery:** Existing single `test` job ran a 4-cell matrix ({ubuntu,windows}×{3.12,3.13}); Windows ~10–11 min vs Ubuntu ~2 min, gating every PR. pytest self-times 513–624s on Windows vs ~90s on Ubuntu. Cause is in-pytest execution (NTFS file I/O for per-test SQLite DBs + per-worker native imports), not step overhead. Defender exclusion removes only ~17%; `-n 8` oversubscription destabilizes timeout-bound subprocess tests. Redline defaults unmatched paths (incl. `.github/workflows/ci.yml`) to gray.

**Material assumptions:**
- Windows-specific regressions cluster in identifiable modules (process mgmt, subprocess hooks, file I/O, SQLite locking). Disproved by: a Windows-only break landing in a module outside the smoke set → action: it surfaces on push/nightly, then add that module to the smoke list.
- Scheduled runs execute against the default branch's workflow copy (standard GitHub behavior). Disproved by: nightly not running windows-full → action: check the cron/branch.

**Plan:** Split the single matrix job into three: `test` (Ubuntu {3.12,3.13}, no `if` → PR+push+nightly), `windows-smoke` (Windows 3.13, folded-scalar pytest over a curated Windows-sensitive path list, no `if` → PR+push), `windows-full` (Windows {3.12,3.13}, `if: github.event_name != 'pull_request'` + a `schedule` cron `17 6 * * *`). Retain Defender exclusion + pip cache on the Windows jobs. Stop condition: if a smoke path is missing, pytest errors — verified all paths exist before push.

**Verification plan:** Local — `yaml.safe_load` parses; enumerate jobs + `if`/trigger wiring; assert every smoke path exists on disk. CI — on the PR, `test`+`windows-smoke` run green and `windows-full` is skipped; PR wall-time vs the ~10 min baseline; `agent-workflow`+`redline` gates green. Post-merge/nightly — confirm `windows-full` runs.

**Plan review:** clean-context review by Explore subagent (read-only, no planning context) — verdict *sound-with-nits*; full prose under `## Plan review` below. Two nits applied: corrected branch-protection check names; added `tests/test_queue_concurrent_claim.py` (SQLite locking-under-contention) to the smoke set.

**Approvals:** Not required at this risk level (Elevated; High would require verbatim human approval).

**Exceptions:** —

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
- `windows-smoke` — Windows 3.13, curated 16-path Windows-sensitive set (supervisor/kill-tree, codex + claude-code hooks, asyncio-windows, snapshot×4, storage-sqlite, sqlite-write-retry, queue-concurrent-claim, launch-token, config, runtime-logging), every PR + push.
- `windows-full` — Windows {3.12, 3.13}, full suite, `if: github.event_name != 'pull_request'` + nightly `schedule` cron (17 6 * * *).

Local verification: YAML parses; triggers = push/pull_request/schedule; `windows-full` correctly gated off PRs; all smoke paths exist on disk.

**Coverage tradeoff (recorded):** a Windows-only regression outside the smoke set won't block a PR — it surfaces on push-to-main or nightly. Smoke path list lives in `ci.yml` and needs occasional curation as Windows-sensitive tests are added.

**Follow-up for humans:** if branch protection is later enabled, require `test (3.12)`, `test (3.13)`, and `windows-smoke`. Do **not** use `test (ubuntu-latest, ...)` (runs-on is hardcoded, not a matrix axis, so the check names carry only the python-version) and do **not** require `windows-full` (it doesn't run on PRs).

## Plan review

Clean-context review (Explore subagent, read-only, no planning context) of the Work Record + `ci.yml`:

**Trigger wiring — correct.** `windows-full` carries `if: github.event_name != 'pull_request'`: skipped on PRs (`event == 'pull_request'`), runs on push (`'push'`) and nightly (`'schedule'`). `test` and `windows-smoke` have no `if`, so they run on every PR/push/nightly. Windows coverage never drops to zero: PRs get `windows-smoke`; push-to-main and nightly get both. (Scheduled runs execute against the default branch's workflow copy — expected.)

**YAML — clean, no bugs.** cron `17 6 * * *` valid; `if` implicit-expression syntax valid (no `${{ }}` needed); the `>` folded scalar yields one `python -m pytest -x -q tests/... ` with all paths space-joined; Defender step is per-job copy (not a within-job duplicate), non-fatal via try/catch + `::warning::`.

**Smoke selection — reasonable; one gap fixed.** Process/subprocess, file I/O, path handling well covered. Gap: `tests/test_queue_concurrent_claim.py` (real threads on one SQLite file — claim-exclusivity, expired-lease reclaim, integrity-error races) is precisely Windows-sensitive SQLite locking-under-contention → **added to the smoke set.** `test_w3_memory_writes_e2e` (signal handling) and mocked-subprocess tests judged low-value/omitted.

**Branch protection — check names corrected** (see follow-up note): real names are `test (3.12)` / `test (3.13)`, not `test (ubuntu-latest, ...)`.

**Verdict: sound-with-nits** — both nits applied.
