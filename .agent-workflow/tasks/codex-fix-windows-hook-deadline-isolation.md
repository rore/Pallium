<!-- agent-workflow:start -->
**Outcome:** Full Windows CI no longer fails from hook test state leaking across xdist test modules.

**Target:** Pallium test suite.

**Scope:** `tests/test_codex_wake.py`, `tests/test_claude_code_hooks/test_container_derivation.py`, and this Work Record.

**Constraints:** Production hook behavior and test coverage remain unchanged; fixes must isolate test state rather than weaken assertions.

**Completion criteria:** When the affected tests share an xdist worker with prior hook deadline use, they still exercise the intended pinned-container and mocked-Git paths on Windows 3.12 and 3.13.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Redline scope is test/work-record only; both failures are deterministic cross-test state leakage introduced by PR #131, not product behavior from PR #134.

**Approach:** Renew the reused Codex hook deadline before pre-hook test setup, and clear the retained Claude common module deadline before each container-derivation test.

**Verification:** Run both failed targets serially and with their contaminating test modules under xdist, run the affected files, pass redline/agent-workflow checks, independent review, PR CI, and post-merge full Windows CI.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Discovery: the wake test calls pin_container before main resets an expired process-global deadline; the container tests retain the shared Claude common module after other hook tests can leave its process-global deadline expired.
- Implemented: renew the public hook deadline immediately before pre-hook pin setup; clear the retained Claude common module deadline before every container-derivation test.

## Evidence

- Revision cf83ec26: explicit expired-deadline recovery passed; dynamic-loader plus container suite passed 40/40; affected hook/deadline files passed 102/102 under xdist; committed failed targets passed 2/2; redline and workflow gates are clean.
- Review correction: reverted the non-causal subprocess patch rewrite; all common modules share the same stdlib subprocess object, while the retained deadline state is the actual isolation boundary.
- Review-fix verification: explicitly expired retained Claude deadline passed the original failing target; affected hook/deadline files again passed 102/102 under xdist.
