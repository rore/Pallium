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

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-08-24: Confirmed the failing main run exceeded the wall-clock assertion by 46 ms while the same commit's Windows 3.13 full job and four later Windows smoke jobs passed. Discovery found the timer includes OS descheduling; SQLite's connection timeout directly tests lock contention. Redline classified the intended test-only change BLUE with no checkpoint or boundary finding.
- 2026-08-24: `apply_patch` failed once with the known machine-local Windows error 1385; used the permitted deterministic replacement limited to the two Work Records and `tests/test_snapshot_concurrent.py`.
- 2026-08-24: Implemented at `9638f0c`: the test helper now accepts a SQLite connection timeout, the contention test sets one second, and wall-clock duration collection was removed. Production snapshot code was not changed.
- 2026-08-24: Verification passed: focused regression 10/10 repetitions under four workers; snapshot concurrency file 7 passed; clean-CI Windows-sensitive selection 371 passed, 7 skipped at `9638f0c`; final redline verdict BLUE with no checkpoint or boundary finding. The first local Windows batch's unrelated `test_prompt_variants_legacy_fallback_unaffected` failure came from the repository-local service config and disappeared when the child process used an absent config path, matching CI.
- 2026-08-24: Workflow checker has one non-blocking commit-order advisory because the initial commit updated the previous task's Work Record alongside creating this task's Work Record; no implementation code existed in that commit.
- 2026-08-24: Independent final review found that the writer was not explicitly ready before the snapshot and WAL setup exceptions could escape the error list. Added readiness/first-insert events and captured setup failures at `7548c9a`; repeat review accepted the minimal synchronization and the clean-CI Windows selection passed again.

## Evidence

- Revision `7548c9a`: exact Windows-sensitive CI selection with repository-local config disabled → 371 passed, 7 skipped; `tests/test_snapshot_concurrent.py` → 7 passed.
- Initial timeout regression: focused contention test → 10/10 repetitions passed under `-n 4`.
- Final redline report: BLUE; 3 blue files, 0 gray/red/watch, 0 checkpoints, 0 boundary violations.
