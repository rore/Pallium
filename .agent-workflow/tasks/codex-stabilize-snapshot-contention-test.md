<!-- agent-workflow:start -->
**Outcome:** The snapshot contention test detects actual SQLite writer blocking without failing from Windows thread-scheduling delays.

**Target:** Pallium.

**Scope:** `tests/test_snapshot_concurrent.py` and task records only.

**Constraints:** Production snapshot behavior and public contracts remain unchanged; preserve the one-second writer-contention requirement.

**Completion criteria:** During a WAL snapshot with concurrent writes, a write lock lasting at least one second fails the test, while scheduler pauses alone do not.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Redline classified the test-only path BLUE with no watch flags, checkpoints, or boundary findings.

**Approach:** Give the test writer a configurable SQLite connection timeout, use one second in the contention test, and remove the wall-clock duration assertion that includes thread descheduling.

**Verification:** Run the focused test repeatedly with xdist, the snapshot concurrency file, the Windows-sensitive CI selection, and the workflow/redline checks.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-08-24: Confirmed the failing main run exceeded the wall-clock assertion by 46 ms while the same commit's Windows 3.13 full job and four later Windows smoke jobs passed. Discovery found the timer includes OS descheduling; SQLite's connection timeout directly tests lock contention. Redline classified the intended test-only change BLUE with no checkpoint or boundary finding.