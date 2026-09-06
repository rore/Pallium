<!-- agent-workflow:start -->
**Outcome:** The merged Linux service lifecycle change passes the Windows full-test CI job.

**Target:** Pallium repository.

**Scope:** Update the stale `_check_health` test double in `tests/test_service.py` only, plus this Work Record.

**Constraints:** Production code and service behavior remain unchanged; preserve all Unicode-home test coverage.

**Completion criteria:** The four Windows-only `test_install_carries_exact_home_in_unicode_launcher` cases pass with the timeout-aware health call.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Test-only blue-zone change; one stale mock signature and no runtime surface change.

**Approach:** Let the existing test lambda accept the new `timeout` keyword while preserving its fixed green-health result.

**Verification:** Run `TestStartWindows::test_install_carries_exact_home_in_unicode_launcher` on Windows, then the service test module and agent-workflow checker.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Discovery: post-merge Windows CI failed because `_service_ready` now calls `_check_health(port, timeout=...)`, while this one Windows-only test still monkeypatches `_check_health` with a single positional parameter.
- Risk assessment: `tests/**` and `.agent-workflow/**` are blue zones; the referenced redline skill file is absent from this checkout, so classification used the checked-in redline policy directly.
- Plan self-review: changing the test double is sufficient; changing production code would weaken the explicit timeout behavior added by PR #120.
