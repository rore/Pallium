<!-- agent-workflow:start -->
**Outcome:** Agents get seconds-scale feedback while editing by running explicit focused tests, the full non-slow suite remains a once-per-review validation, and the confirmed load-sensitive Relay capacity test no longer flakes under CI contention.

**Target:** Pallium developer test workflow and test infrastructure.

**Scope:** Repository test-running guidance, the Relay capacity isolation test, evidence-driven CI worker tuning only if measurements support it, and aligned Work Record/roadmap files. Product behavior, public contracts, dependencies, markers, and broad slow-suite contract repair are excluded.

**Constraints:** Preserve required Linux and full Windows coverage; do not weaken end-to-end coverage requirements; use pytest's existing targeting and last-failed features instead of a new dependency or speculative source-to-test mapper; do not change `pyproject.toml` without replanning and architecture review.

**Completion criteria:** Repository instructions define an explicit edit/subsystem/full validation ladder; a focused command completes without starting the whole suite; the observed Relay capacity timeout is stress-verified after a root-cause-aligned test fix; Windows worker configuration is changed only with supporting measurements; required full-suite coverage remains green.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** The likely implementation is test/docs-only, but `.github/workflows/ci.yml` is an authorized gray operational path if worker measurements justify a change. Test synchronization and CI parallelism interact across platforms.

**Discovery:** Current pytest defaults run the entire 4,578-test non-slow suite with four workers, taking 202.70 seconds locally. The merged full Windows run took 20m38 on Python 3.12 and 40m04 on Python 3.13; the latter showed multiple 90-150 second tests. Linux 3.12 failed once at `tests/test_relay_capacity_isolation.py` on a 0.5-second logical-isolation deadline, then passed on rerun. Existing guidance explains slow markers but does not tell agents to target tests during editing or reserve the full suite for final validation. Focused Windows measurements showed the one-file Relay test at 2.475s serial, 5.421s with two workers, and 6.522s with four; the two-test count gate stayed about 8-9s at all worker counts; both files together were 11.356s serial, 8.859s with two, and 10.224s with four. Source inspection confirms the Relay deadline is a test synchronization guard, not a latency SLA, and the count-gate module performs the same expensive deterministic measurement twice.

**Material assumptions:** (1) Explicit test-node/file selection with serial execution is the smallest reliable inner-loop contract; automatic changed-file mapping would be brittle and is excluded. (2) The Relay test asserts capacity isolation, not a 500ms service-level objective; a one-second bound remains below the blocked diagnostic operation's two-second release timeout and therefore preserves the isolation proof while tolerating scheduler jitter. (3) The representative worker measurements do not support a global worker-count change, so `.github/workflows/ci.yml` remains untouched. (4) Both count-gate assertions may safely share one immutable measurement report because the seeded-regression test mutates only its separately loaded baseline.

**Plan:** 1. Add concise repository guidance requiring a targeted node/file test with `-n 0` while editing, affected-subsystem files after a coherent change, native `--lf --lfnf=none` for failure reruns, and one full non-slow run before review rather than after each edit. 2. Raise only the Relay-during-saturated-diagnostics guard from 0.5 to 1.0 seconds, preserving its completion-before-the-two-second-blocker proof, then stress-run the test. 3. Reuse one module-scoped count measurement across the two count-gate assertions so the expensive deterministic seed/run is paid once without changing the gate's counts or baseline comparison. 4. Do not add a wrapper, dependency, marker, changed-file mapper, or CI worker change. 5. Run focused tests, full non-slow validation once, workflow/redline gates, clean-context result review, and the authorized PR lifecycle. Stop on product-code changes, dependency/marker changes, reduced required coverage, or an unbounded suite redesign.

**Verification plan:** Validate the documented focused and last-failed commands directly; repeat the Relay capacity test at least 20 times serially and under the default four-worker setting; verify both count-gate assertions pass and compare module runtime before/after; run the full default suite once after implementation; finish with `git diff --check`, redline, Agent Workflow, clean-context result review, and green PR CI.

**Plan review:** Pending clean-context review.

**Approvals:** User explicitly authorized this second optimization round with “ok, do it” and previously authorized full PR tracking and merge after review and green checks.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-07 Establish Context: created isolated branch `codex/developer-test-loop` from current `origin/main`; the separate root checkout remains untouched.
- 2026-09-07 Discover: recorded current local and hosted-Windows runtimes, the confirmed load-sensitive Relay capacity failure, and the missing developer test ladder.
- 2026-09-07 Assess Risk: clean-context redline review classified tests/docs/roadmap/Work Record blue and root `AGENTS.md` gray; no checkpoint or boundary applies. Optional CI was gray but measurements did not justify touching it.
- 2026-09-07 Plan discovery: focused n0/n2/n4 measurements favored serial execution for the one-file Relay inner loop, showed no global worker winner, confirmed the 0.5-second guard is not a latency SLA, and found the count gate repeats the same expensive immutable measurement.

## Plan review

Pending.

## Evidence

Pending implementation.

## Result review

Pending implementation.
