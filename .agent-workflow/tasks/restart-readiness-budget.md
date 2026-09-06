<!-- agent-workflow:start -->
**Outcome:** The supported Windows restart wrapper waits through a measured legitimate cold start and reports success only after all required endpoints are ready.

**Target:** `scripts/restart-service.ps1` readiness retry budget.

**Scope:** Increase the existing bounded readiness budget, add one instant mocked regression for a service becoming ready after the old limit, and align the Relay wake roadmap/work record.

**Constraints:** Keep the wait bounded and diagnostics actionable; do not add wall-clock delay to tests; do not change service startup or endpoint contracts.

**Completion criteria:** A deterministic real-script test fails at the old 20-attempt limit and succeeds after a later transient cold start; terminal failure remains bounded; the installed wrapper exits 0 and all three endpoints are healthy.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Script, test, and documentation-only change outside guarded/redline paths; one constant and its regression.

**Approach:** Reuse the existing retry loop and test harness, raising only its attempt count to cover the observed 68-second startup without adding dependencies or test sleeps.

**Verification:** Focused restart-wrapper tests, workflow/diff checks, installed wrapper restart, and direct `/health`, `/status`, `/debug/queue/health` probes.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-09-06: Dogfood restart reached healthy state after the wrapper's 20-attempt budget and was falsely reported as failed. Scope is limited to the existing bounded readiness loop and its mocked Windows test.
