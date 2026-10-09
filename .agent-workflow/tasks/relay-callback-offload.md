# Relay callback offload

<!-- agent-workflow:start -->
**Outcome:** Keep HTTP health responsive while Relay callbacks wait on native registry locks, SQLite or file I/O.

**Target:** Pallium HTTP Relay routes.

**Scope:** api/routes.py, tests/test_relay_capacity_isolation.py and this Work Record, on fix/relay-callback-offload from origin/main17403b01d9a5d14c79b65f5f6d606e16085a33c1.

**Constraints:** Use the existing tracked Relay runner and fallback worker execution; preserve callback sequencing, fencing, failure handling, HTTP mappings, cancellation, runner limits and production budgets. No executor, configuration, dependency, cache, protected-contract edit or live operation. Root owns tests, full validation, CI, merge and installed rollout.

**Completion criteria:** All synchronous Relay snapshot/callback and native Claude registry operations execute off the event loop. Deterministic HTTP tests show concurrent health responsiveness, unchanged lifecycle/readback, ordering and error handling. Root validation and independent review pass before release.

**Requirement baseline:**
{"source":"human approval ab99c100-4148-4868-9e67-1a09390f6723; root precise callback-offload assignment 2026-10-09","outcome":"Keep HTTP health responsive while Relay callbacks wait on native registry locks, SQLite or file I/O.","scope":"api/routes.py, tests/test_relay_capacity_isolation.py and this Work Record, on fix/relay-callback-offload from origin/main17403b01d9a5d14c79b65f5f6d606e16085a33c1.","constraints":"Use the existing tracked Relay runner and fallback worker execution; preserve callback sequencing, fencing, failure handling, HTTP mappings, cancellation, runner limits and production budgets. No executor, configuration, dependency, cache, protected-contract edit or live operation. Root owns tests, full validation, CI, merge and installed rollout.","completion_criteria":"All synchronous Relay snapshot/callback and native Claude registry operations execute off the event loop. Deterministic HTTP tests show concurrent health responsiveness, unchanged lifecycle/readback, ordering and error handling. Root validation and independent review pass before release."}

**Risk:** High

**Complexity:** Moderate

**Reason:** API routes are a red api-review contract surface; callbacks carry persistence fences and post-admission side effects. Several caller paths and exception mappings must remain coherent.

**Discovery:** Root observed the old installed API MainThread blocked in activation projection through codex_registry.usable -> _refresh -> SQLAlchemy wake-authority validation, followed by supervisor replacement. Main now offloads projection, but exact-turn snapshots, turn/admission callbacks, send/reply dispatch, ACK/MCP-ACK release, and internal Claude register/close still execute synchronously in async routes. These perform the same registry/SQLite path or blocking native locks/file I/O. app/main.py already supplies tracked run_relay_operation; no new runner is necessary.

**Material assumptions:** Changing execution context at the same sequencing points preserves the contract. If tests show altered fencing, exception mappings, ordering, cancellation or capacity, stop and correct before acceptance. Historical incident attribution is limited to the observed stack; this patch closes independently evidenced remaining blocking call sites.

**Plan:** Extract the raw existing tracked/fallback runner invocation from _relay_call into a small local helper, preserving _relay_call's HTTP exception mapping and logging. Await that raw helper for the exact-turn snapshot, each existing callback at its current try/except boundary, and native Claude register/close. Keeping callbacks on the raw runner preserves their original exceptions and the native 400/409/204 mappings. Add deterministic ASGI HTTP regressions in the existing capacity file: worker-thread gates plus concurrent health, lifecycle readback and ordering/error checks. Obtain architecture plan review before source edits. Root runs selected validation and independent result review.

**Verification plan:** Root runs the new exact capacity tests, existing capacity/activation/Codex/Claude registration callback files, whole-change selector/full requirements and import/workflow checks. Tests cover all callback call sites, real HTTP lifecycle, error handling, snapshot-before-admission and ACK-before-next-dispatch, worker execution and concurrent health; reuse existing cancellation/capacity regressions for the unchanged runner.

**Plan review:** Agent technical review: /root/architecture_check, GO 2026-10-09 on this exact Work Record. Preserve raw exceptions for native 400/409 mappings, existing sequence/catches, externally observed gate assertions and callback failure continuation. No source blocker.

**Approvals:** Approved by user 2026-10-09: "so don't stop until pallium is analyzed, we know exactly what is the problem, we fixed it, merged it and updated the local service. this is top priority, you must not stop till this is fixed and done". Exact source ab99c100-4148-4868-9e67-1a09390f6723 is retained by root; root authorized this precise isolated callback-offload scope.

**Exceptions:** None

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

2026-10-09: Invoked Agent Workflow applicability/risk classification before source edits. Clean detached origin/main17403b01 checkout switched to fix/relay-callback-offload. Intended application/test/Work Record paths require normal workflow; no documentation exemption. Red API checkpoint classified High/Moderate. Independent architecture plan review accepted before source edits; no tests or live operations delegated.

## Evidence

Root owns all test execution and release evidence. No validation has run for this branch yet.

## Result review

Pending source implementation, root validation and independent non-implementer review.
