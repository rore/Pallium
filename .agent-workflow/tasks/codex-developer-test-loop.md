<!-- agent-workflow:start -->
**Outcome:** Agents get seconds-scale feedback while editing by running explicit focused tests, the full non-slow suite remains a once-per-review validation, and the confirmed load-sensitive Relay capacity test no longer flakes under CI contention.

**Target:** Pallium developer test workflow and test infrastructure.

**Scope:** Repository test-running guidance, the Relay capacity isolation test, evidence-driven CI worker tuning only if measurements support it, and aligned Work Record/roadmap files. Product behavior, public contracts, dependencies, markers, and broad slow-suite contract repair are excluded.

**Constraints:** Preserve required Linux and full Windows coverage; do not weaken end-to-end coverage requirements; use pytest's existing targeting and last-failed features instead of a new dependency or speculative source-to-test mapper; do not change `pyproject.toml` without replanning and architecture review.

**Completion criteria:** Repository instructions define an explicit edit/subsystem/full validation ladder; a focused command completes without starting the whole suite; the observed Relay capacity timeout is stress-verified after a root-cause-aligned test fix; Windows worker configuration is changed only with supporting measurements; required full-suite coverage remains green.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** The likely implementation is test/docs-only, but `.github/workflows/ci.yml` is an authorized gray operational path if worker measurements justify a change. Test synchronization and CI parallelism interact across platforms.

**Discovery:** Current pytest defaults run the entire 4,578-test non-slow suite with four workers, taking 202.70 seconds locally. The merged full Windows run took 20m38 on Python 3.12 and 40m04 on Python 3.13; the latter showed multiple 90-150 second tests. Linux 3.12 failed once at `tests/test_relay_capacity_isolation.py` on a 0.5-second logical-isolation deadline, then passed on rerun. Existing guidance explains slow markers but does not tell agents to target tests during editing or reserve the full suite for final validation.

**Material assumptions:** (1) Explicit test-node/file selection with serial execution is the smallest reliable inner-loop contract; automatic changed-file mapping would be brittle and is excluded. (2) The Relay test asserts capacity isolation, not a 500ms service-level objective, so a bounded deadline aligned with its existing two-second synchronization window can remove load sensitivity without weakening the contract. (3) Representative worker-count measurements are sufficient to decide whether a CI-only worker change is warranted; inconclusive evidence means no CI change.

**Plan:** 1. Classify intended paths and inspect the slowest hosted-Windows tests plus Relay synchronization semantics. 2. Add the smallest repository guidance that requires targeted node/file tests while editing, affected-subsystem tests after a coherent change, and one full non-slow run before review; use native `-n 0` and `--lf --lfnf=none`. 3. Adjust only the load-sensitive Relay test deadline if source inspection confirms it is not a latency assertion, then stress-run that test. 4. Benchmark representative slow files at worker counts 0, 2, and 4; change the Windows full job only if results show a clear safe improvement. 5. Run focused tests, full non-slow validation, workflow/redline gates, clean-context result review, and the authorized PR lifecycle. Stop on product-code changes, dependency/marker changes, reduced required coverage, or an unbounded suite redesign.

**Verification plan:** Validate the documented focused commands directly; repeat the Relay capacity test enough times to expose the prior race; compare representative serial/two/four-worker wall times; run any structural workflow tests if CI changes; run the full default suite once after implementation; finish with `git diff --check`, redline, Agent Workflow, clean-context result review, and green PR CI.

**Plan review:** Pending clean-context review.

**Approvals:** User explicitly authorized this second optimization round with “ok, do it” and previously authorized full PR tracking and merge after review and green checks.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-07 Establish Context: created isolated branch `codex/developer-test-loop` from current `origin/main`; the separate root checkout remains untouched.
- 2026-09-07 Discover: recorded current local and hosted-Windows runtimes, the confirmed load-sensitive Relay capacity failure, and the missing developer test ladder.

## Plan review

Pending.

## Evidence

Pending implementation.

## Result review

Pending implementation.
