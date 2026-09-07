<!-- agent-workflow:start -->
**Outcome:** Windows full-suite workers cannot inherit an expired hook deadline in the crash-after-claim recovery test.

**Target:** Pallium test suite.

**Scope:** `tests/test_codex_wake.py` and this Work Record only.

**Constraints:** Production behavior and assertions remain unchanged; fix only process-global test isolation.

**Completion criteria:** The crash-recovery test and both deadline-sensitive recovery tests pass alone and together under xdist, and merged full Windows CI passes on Python 3.12 and 3.13.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Redline classified both intended paths BLUE with no boundaries or surface flags; this is one test-state reset.

**Approach:** Renew the public hook deadline immediately before the crash-recovery test's setup pin, matching the adjacent isolation fix already merged in PR #135.

**Verification:** Run the failing test alone, both recovery tests together under xdist, the affected Codex wake module, workflow/redline checks, PR CI, and post-merge full Windows CI.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Discovery: run 34150660242 failed because this analogous recovery test reaches setup with an expired process-global hook deadline; PR #135 reset only the neighboring recovery test.
- Risk: clean-context redline review classified the two intended paths BLUE with no boundary or surface findings.
