<!-- agent-workflow:start -->
**Outcome:** Windows full-suite workers cannot inherit an expired hook deadline in the crash-after-claim recovery test.

**Target:** Pallium test suite.

**Scope:** `tests/test_codex_wake.py` and this Work Record only.

**Constraints:** Production behavior and assertions remain unchanged; fix only process-global test isolation.

**Completion criteria:** The crash-recovery test and both deadline-sensitive recovery tests pass alone and together under xdist, and merged full Windows CI passes on Python 3.12 and 3.13.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Redline classified both intended paths BLUE with no boundaries or surface flags; this is one test-state reset.

**Approach:** Clear the deadline on `user_prompt_submit._common`, the actual dynamically loaded hook module, in the existing per-test setup; remove the now-redundant one-off reset from PR #135.

**Verification:** Run the failing test alone, both recovery tests together under xdist, the affected Codex wake module, workflow/redline checks, PR CI, and post-merge full Windows CI.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Discovery: run 34150660242 failed because this analogous recovery test reaches setup with an expired process-global hook deadline; PR #135 reset only the neighboring recovery test.
- Risk: clean-context redline review classified the two intended paths BLUE with no boundary or surface findings.
- Implementation: the existing module setup now clears the retained hook deadline for every wake test; the one-off neighboring reset is removed as redundant.
- Editing fallback: apply_patch failed with Windows error 1327, so the two explicitly scoped files were updated with exact deterministic replacements.
- Result review found a P1 module-identity bug before push; implementation returned to Ready to implement for correction and re-verification.
- Correction: setup now resets `user_prompt_submit._common`, the actual dynamic module; high-effort re-review signed off with no remaining findings or roadmap drift.

## Evidence

- Actual-hook seeded-expired crash-recovery test: 1 passed.
- Both recovery tests from an actual expired hook deadline, serially: 2 passed.
- Both deadline-sensitive recovery tests under xdist (`-n 2`): 2 passed.
- Full `tests/test_codex_wake.py` under xdist (`-n 4`): 41 passed.
- Import boundary report, redline verdict, and agent-workflow checker: clean.
- Corrected implementation revision: `722f0ba7`.
