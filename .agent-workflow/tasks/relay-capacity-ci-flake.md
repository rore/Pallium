<!-- agent-workflow:start -->
**Outcome:**
Eliminate the observed hosted Python 3.12 capacity-isolation timeout while preserving the regression signal.

**Target:**
`tests/test_relay_capacity_isolation.py`

**Scope:**
Test synchronization/timing only; no production capacity semantics.

**Constraints:**
Preserve the test's saturation and diagnostics-survival contract. Do not weaken production behavior.

**Completion criteria:**
Focused test passes reliably, workflow/redline checks pass, and the diff remains test-only.

**Risk:** Routine

**Complexity:** Simple

**Reason:**
Redline classification is BLUE: only a test path is intended to change.

**Approach:**
Trace the test and worker capacity path, then replace the flaky fixed timing dependency with deterministic synchronization or a safely bounded test wait.

**Verification:**
Run the focused pytest node repeatedly, then the repository workflow/redline checks and inspect the final diff.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Discovery found no production issue: `/relay/turn` and diagnostics dispatch through dedicated runners, while this test deliberately blocks the default AnyIO worker. The hosted failure is the combined request batch exceeding a 1-second wall-clock budget during legitimate startup/SQLite scheduling overhead. Increased the batch budget to 5 seconds and the blocked-worker ceiling to 10 seconds, preserving the proof that the batch completes before the saturated worker can self-release.

`apply_patch` failed with machine-local Windows error 1327. Per `AGENTS.local.md`, edits used a narrowly scoped deterministic PowerShell replacement limited to the test and Work Record.

## Evidence

- Final 10s/5s focused test passed five consecutive runs: 0.89s, 0.49s, 0.51s, 0.49s, 0.48s.
- Full affected file: 2 passed.
- `python -m pytest tests/ -x -q -n 0`: 4,948 passed, 34 skipped, 215 deselected, 2 xfailed.
- Independent Astra review approved. A behavioral mutation routing all `anyio.to_thread.run_sync` calls through default capacity still raised the expected timeout in 5.29s, before the 10-second blocker ceiling.
- `git diff --check`: clean.
- Fresh import-linter/redline verdict: BLUE, no boundary violations or checkpoints.
- Agent-workflow check: no blockers; one non-blocking same-commit-order advisory.

## Result review

The wider relative timing window removes the observed runner-pressure failure without allowing the deliberately saturated default worker to self-release before the assertion budget. No production files changed.
