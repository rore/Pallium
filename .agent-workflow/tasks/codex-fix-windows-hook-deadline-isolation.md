<!-- agent-workflow:start -->
**Outcome:** Full Windows CI no longer fails from hook test state leaking across xdist test modules.

**Target:** Pallium test suite.

**Scope:** `tests/test_codex_wake.py`, `tests/test_claude_code_hooks/test_container_derivation.py`, and this Work Record.

**Constraints:** Production hook behavior and test coverage remain unchanged; fixes must isolate test state rather than weaken assertions.

**Completion criteria:** When the affected tests share an xdist worker with dynamic hook loaders or prior deadline use, they still exercise the intended pinned-container and mocked-Git paths on Windows 3.12 and 3.13.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Redline scope is test/work-record only; both failures are deterministic cross-test state leakage introduced by PR #131, not product behavior from PR #134.

**Approach:** Reset the reused Codex hook deadline before pre-hook test setup, and patch the already-imported Claude common module object instead of resolving the mutable global module alias.

**Verification:** Run both failed targets serially and with their contaminating test modules under xdist, run the affected files, pass redline/agent-workflow checks, independent review, PR CI, and post-merge full Windows CI.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Discovery: the wake test calls pin_container before main resets an expired process-global deadline; the container tests patch sys.modules["common"] after another loader can replace that alias, while their imported function still points at the original module.
