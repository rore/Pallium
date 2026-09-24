# Reproduce late-claim Codex wake fence

<!-- agent-workflow:start -->
**Outcome:** Reproduce whether a committed claim after an exact Codex wake hook timeout leaves an accepted wake fence blocking a later delivery.

**Target:** Pallium Relay Codex wake.

**Scope:** Caller-surface regression in `tests/test_codex_wake.py` and this Work Record only; production correction requires reclassification and a reviewed plan.

**Constraints:** No live recipient mutation, native resend, fence deletion, scope/model/effort change, or weakening of existing single-flight regressions.

**Completion criteria:** A real hook/HTTP delayed-claim test records the original delivery's claim/ACK outcome and the successor delivery's state after lease expiry and sweep, including the current fence generation and native submission count.

**Requirement baseline:** {"source":"manager-task-01a07bef-18c8-71b2-89ab-c0cbe91e73ad","outcome":"Reproduce whether a committed claim after an exact Codex wake hook timeout leaves an accepted wake fence blocking a later delivery.","scope":"Caller-surface regression in tests/test_codex_wake.py and this Work Record only; production correction requires reclassification and a reviewed plan.","constraints":"No live recipient mutation, native resend, fence deletion, scope/model/effort change, or weakening of existing single-flight regressions.","completion_criteria":"A real hook/HTTP delayed-claim test records the original delivery's claim/ACK outcome and the successor delivery's state after lease expiry and sweep, including the current fence generation and native submission count."}

**Risk:** Routine

**Complexity:** Simple

**Reason:** Test and Work Record paths are blue; no production or contract surface changes in this first slice.

**Approach:** Extend the existing actual hook/HTTP loopback pattern to delay the server claim past the exact wake request deadline, then inspect only test-store state and the isolated wake registry before and after lease expiry.

**Verification:** Focused `tests/test_codex_wake.py` node plus existing busy single-flight and crash-after-claim regressions.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Discovery

Live incident (identifiers kept out of fixtures): an accepted older wake began an exact hook; the hook failed `relay_unavailable`, then the server claimed its delivery after the hook returned. The retained fence has no correlated claim attempt. Two later messages remain pending with attempts 0. The accepted fence is distinct from uncertain nonzero native admission. An isolated test must determine whether the current route callback persists correlation when a claim finishes after the client times out.
