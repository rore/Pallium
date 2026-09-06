<!-- agent-workflow:start -->
**Outcome:**
Windows full CI keeps its fast parallel suite while the real-PowerShell restart tests run once without cross-worker process contention.

**Target:**
The Windows-full job in `.github/workflows/ci.yml`.

**Scope:**
Change only `.github/workflows/ci.yml` and this Work Record. Run `tests/test_restart_service.py` serially, then exclude it from the remaining parallel suite.

**Constraints:**
Do not change production code, test assertions, sleeps, subprocess timeouts, PR smoke coverage, Linux CI, or pytest defaults. Do not make an always-run test intrinsically slower.

**Completion criteria:**
Both Windows-full Python versions run `tests/test_restart_service.py` exactly once with xdist disabled, exclude that module from the subsequent xdist run, retain fail-fast behavior, and pass in hosted CI. All other CI jobs remain unchanged.

**Risk:** Elevated

**Complexity:** Simple

**Reason:**
The change is limited to CI scheduling, but the workflow gate classifies `.github/workflows/ci.yml` as Elevated. Product behavior and test contracts are unchanged.

**Discovery:**
Eight consecutive recent main runs fail Windows-full 3.12 and/or 3.13 at the same `test_preflight_failure_never_stops_the_healthy_service` 15-second PowerShell subprocess timeout under xdist. The newest run fails both versions while Linux and Windows smoke pass. The exact serial module command passes locally in 14.37 seconds.

**Material assumptions:**
- The timeout is caused by full-suite xdist process contention, not a product defect. Evidence: the module passes serially and in Windows smoke, while repeated full xdist runs fail at the same harness boundary.
- `-n 0` overrides the repository `-n 4` addopt. Verified by the exact local command and clean-context review.
- `--ignore=tests/test_restart_service.py` prevents duplicate collection while leaving the remaining suite unchanged. Verified by collect-only output.

**Plan:**
Split only the Windows-full test step: run `tests/test_restart_service.py -x -q -n 0`, then run the existing `tests/ -x -q` command with that file ignored. If the serial hosted command still times out, diagnose the harness lifecycle instead of extending the timeout.

**Verification plan:**
- Serial isolation -> run `python -m pytest tests/test_restart_service.py -x -q -n 0`.
- No duplicate collection -> collect the remaining command and confirm the restart module is absent.
- Workflow integrity -> validate YAML, diff, and agent-workflow gates.
- Hosted correctness -> require Windows-full 3.12 and 3.13 to pass after merge.

**Plan review:**
Approved 2026-09-06 by clean-context agent `/root/ci_process_plan_review`: the split is minimal, root-cause aligned, valid with repository pytest defaults, preserves coverage and fail-fast behavior, and has no simpler safer fix within scope.

**Approvals:**
Standing user authorization to take managed PRs through review, CI, and merge.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Split only the Windows-full test step: restart-service caller-surface tests run once with xdist disabled, then the existing parallel suite runs with that file ignored. Test code, assertions, sleeps, and subprocess timeouts are unchanged.

## Evidence

- Eight consecutive recent main failures across Windows Python 3.12/3.13 share the same 15-second PowerShell subprocess timeout; ordinary test and Windows-smoke jobs pass.
- Newest completed main run `34025104733`: both Windows-full 3.12 and 3.13 fail the same test; every other job passes.
- Exact serial command: 24 passed in 14.37s.
- Remaining-suite collect-only command: 4,480 selected, 168 deselected, and no restart-service node collected.
- Clean-context plan review: APPROVE; `git diff --check` clean.

## Result review

- Hosted Windows-full 3.12 and 3.13 are the decisive result gate.