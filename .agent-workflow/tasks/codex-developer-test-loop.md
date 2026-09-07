<!-- agent-workflow:start -->
**Outcome:** Agents get seconds-scale feedback while editing by running explicit focused tests, the full non-slow suite remains a once-per-review validation, and the confirmed load-sensitive Relay capacity test no longer flakes under CI contention.

**Target:** Pallium developer test workflow and test infrastructure.

**Scope:** `AGENTS.md`, `docs/testing-conventions.md`, `app/main.py`, `tests/test_relay_capacity_isolation.py`, `tests/test_vnext_perf_count_gate.py`, and aligned Work Record/roadmap files. CI configuration, pytest configuration, public contracts, dependencies, markers, and broad slow-suite contract repair are excluded.

**Constraints:** Preserve required Linux and full Windows coverage; do not weaken end-to-end coverage requirements; use pytest's existing targeting and last-failed features instead of a new dependency or speculative source-to-test mapper; do not change `pyproject.toml` without replanning and architecture review.

**Completion criteria:** Repository instructions define an explicit edit/subsystem/full validation ladder; a focused command completes without starting the whole suite; repeated cancellation proves the shutdown barrier cannot finish before the actual Relay worker; the count gate performs one measurement while preserving both checks; CI worker configuration and required full-suite coverage remain unchanged and green.

**Risk:** High

**Complexity:** Moderate

**Reason:** `app/main.py` is a watched guarded path and the newly reproduced defect affects cancellation/shutdown safety. Tests/docs/roadmap remain blue and root `AGENTS.md` gray; redline requires no formal checkpoint, but concurrency accounting warrants high-risk clean-context review.

**Discovery:** Current pytest defaults run the entire 4,578-test non-slow suite with four workers, taking 202.70 seconds locally. The merged full Windows run took 20m38 on Python 3.12 and 40m04 on Python 3.13; the latter showed multiple 90-150 second tests. Linux 3.12 failed once at `tests/test_relay_capacity_isolation.py` on a 0.5-second logical-isolation deadline, then passed on rerun. Existing guidance explains slow markers but does not tell agents to target tests during editing or reserve the full suite for final validation. Focused Windows measurements showed the one-file Relay test at 2.475s serial, 5.421s with two workers, and 6.522s with four; the two-test count gate stayed about 8-9s at all worker counts; both files together were 11.356s serial, 8.859s with two, and 10.224s with four. Source inspection confirms the Relay deadline is a test synchronization guard, not a latency SLA, and the count-gate module performs the same expensive deterministic measurement twice.

**Material assumptions:** (1) Explicit test-node/file selection with serial execution is the smallest reliable inner-loop contract; automatic changed-file mapping would be brittle and is excluded. (2) The Relay test asserts capacity isolation, not a 500ms service-level objective; a one-second bound remains below the blocked diagnostic operation's two-second release timeout and therefore preserves the isolation proof while tolerating scheduler jitter. (3) The representative worker measurements do not support a global worker-count change, so `.github/workflows/ci.yml` remains untouched. (4) Both count-gate assertions may safely share one immutable measurement report because the seeded-regression check mutates only its separately loaded baseline; they must be one test item so default xdist cannot schedule duplicate measurements on separate workers. (5) Incrementing before limiter admission and decrementing only in the tracked worker's `finally` retains queued-operation coverage and prevents request cancellation from declaring a still-running worker complete.

**Plan:** 1. Add concise repository guidance requiring a targeted node/file test with `-n 0` while editing, affected-subsystem files after a coherent change, native `--lf --lfnf=none` for failure reruns, and one full non-slow run before review rather than after each edit. 2. Keep operation admission counted before limiter acquisition, but move decrement/notification into a tracked worker `finally` so request cancellation cannot let shutdown pass while the worker continues; retain the same accounting for Relay and diagnostics. 3. Raise only the Relay-during-saturated-diagnostics guard from 0.5 to 1.0 seconds, preserving its completion-before-the-two-second-blocker proof, then stress-run active cancellation and queued diagnostic draining. 4. Combine the two count-gate assertions into one test item sharing one count measurement, so the expensive deterministic seed/run is paid once even under default xdist without changing the gate's counts or baseline comparison. 5. Do not add a wrapper, dependency, marker, changed-file mapper, or CI worker change. 6. Run focused tests, full non-slow validation once, workflow/redline gates, clean-context result review, and the authorized PR lifecycle. Stop on public-contract, dependency/marker, required-coverage, or unbounded suite changes.

**Verification plan:** Validate the documented focused and last-failed commands directly; repeat the Relay capacity test at least 20 times serially and under the default four-worker setting, asserting the barrier stays blocked until worker completion and queued diagnostics drain; verify both count-gate checks pass in the single test item and compare module runtime before/after; run the full default suite once after implementation; finish with `git diff --check`, redline, Agent Workflow, clean-context result review, and green PR CI.

**Plan review:** Reopened after stress verification exposed a product-level cancellation/accounting race. Expanded clean-context review is pending before editing `app/main.py`.

**Approvals:** User explicitly authorized this second optimization round with “ok, do it” and previously authorized full PR tracking and merge after review and green checks.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-07 Establish Context: created isolated branch `codex/developer-test-loop` from current `origin/main`; the separate root checkout remains untouched.
- 2026-09-07 Discover: recorded current local and hosted-Windows runtimes, the confirmed load-sensitive Relay capacity failure, and the missing developer test ladder.
- 2026-09-07 Assess Risk: clean-context redline review classified tests/docs/roadmap/Work Record blue and root `AGENTS.md` gray; no checkpoint or boundary applies. Optional CI was gray but measurements did not justify touching it.
- 2026-09-07 Plan discovery: focused n0/n2/n4 measurements favored serial execution for the one-file Relay inner loop, showed no global worker winner, confirmed the 0.5-second guard is not a latency SLA, and found the count gate repeats the same expensive immutable measurement.
- 2026-09-07 Plan review: senior clean-context review rejected a module fixture because xdist can duplicate it across workers, approved one combined count-gate item instead, and signed off the narrowed no-CI plan with no remaining blockers.
- 2026-09-07 Verification finding: native duplicate collection reproduced a real operation-tracking race (4 failures in 20 runs): after request cancellation, `_wait_for_operations()` sometimes returned while the mocked Relay worker was still blocked. Redline classified `app/main.py` as watched with no formal checkpoint; product-code implementation is paused for expanded high-risk plan review.

## Plan review

Senior clean-context review confirmed the Relay guard is test synchronization rather than a latency SLA and that one second remains safely below the two-second blocked-diagnostic timeout. It verified that one combined count-gate test can preserve the baseline-exists, no-latency, real-hit, normal comparison, and seeded-regression assertions. The initial module-fixture idea was rejected because default xdist can schedule the two test items on different workers; combining them into one item resolves that finding without scheduler or CI changes.

## Evidence

Pending implementation.

## Result review

Pending implementation.
