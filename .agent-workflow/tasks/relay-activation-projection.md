# Keep Relay activation projection off the event loop

<!-- agent-workflow:start -->
**Outcome:** Relay activation response projection does not block unrelated HTTP requests while synchronous activation reads wait.
**Target:** Pallium Relay HTTP response projection.
**Scope:** api/routes.py shared activation projection and its existing route call sites; tests/test_relay_capacity_isolation.py; this Work Record.
**Constraints:** Preserve response and error contracts, recursive projection, callback order after admission/persistence, and configured Relay runner/limiter and cancellation tracking. No new runner, queue, configuration, storage schema, live service operations, or unrelated work-reference projection changes.
**Completion criteria:** Health progresses while activation projection blocks; every projection call uses the existing Relay operation runner; turn admission callbacks precede projection; activation results and best-effort error handling remain unchanged.
**Requirement baseline:** {"source":"parent-assignment:relay-activation-projection:2026-10-08","outcome":"Relay activation response projection does not block unrelated HTTP requests while synchronous activation reads wait.","scope":"api/routes.py shared activation projection and its existing route call sites; tests/test_relay_capacity_isolation.py; this Work Record.","constraints":"Preserve response and error contracts, recursive projection, callback order after admission/persistence, and configured Relay runner/limiter and cancellation tracking. No new runner, queue, configuration, storage schema, live service operations, or unrelated work-reference projection changes.","completion_criteria":"Health progresses while activation projection blocks; every projection call uses the existing Relay operation runner; turn admission callbacks precede projection; activation results and best-effort error handling remain unchanged."}
**Risk:** High
**Complexity:** Simple
**Reason:** api/routes.py is a red-zone public API path requiring api-review. The change preserves caller contracts but changes where shared synchronous response work executes.
**Discovery:** All 12 external projection call sites execute the synchronous recursive decorator directly after an offloaded primary operation. app/dependencies.py activation projection can read persisted Relay state. app/main.py already provides a tracked Relay runner with four capacity slots, independent of diagnostic capacity.
**Material assumptions:** The existing callback is safe in the same worker context as Relay storage operations; if disproved, stop and report the affected callback. Public schemas and callback ordering need no changes.
**Plan:** Invoke agent-workflow, classify risk and obtain independent technical review before source edits. Keep recursive projection synchronous; add one shared async wrapper through _relay_call and await it at all external sites. Keep admission/send/reply callbacks in their existing order. Add a deterministic ASGI event-driven regression to the existing capacity isolation test file; run focused and affected files only. Commit for parent review; parent owns full validation, publication and installed qualification.
**Verification plan:** When activation reads wait, health and an event-loop task progress -> deterministic ASGI event regression. When a projection is dispatched, the configured Relay runner receives it and its shutdown tracking remains active -> runner/capacity regression. When a turn returns, admission callbacks precede recursive projection and activation fields are preserved -> event ordering and response assertions. When the activation callback raises, the admitted response survives -> existing best-effort contract plus focused regression. Existing route/subsystem tests validate schema, scope, send and wake behavior; no protected contract edits.
**Plan review:** Agent technical review: root task 01a0d7ce-83c6-77e2-90f7-d413894059e1, 2026-10-08. Root independently read every external projection site and app/dependencies.py, approved the synchronous inner projection plus async wrapper through the existing runner/limiter, confirmed callback order and best-effort exceptions, and required the no-callback early return.
**Approvals:** Approved by user 2026-10-08: "i might be gone later so you have my approval to drive this fix till merge and done". Source: root task 01a0d7ce-83c6-77e2-90f7-d413894059e1, relayed by root; preceding scope was "we should treat this as mission critical issue, meaning - stop doing complicated and long processes, get the fucking thing working" and "all hands on deck - laser focused on finding and solving the problem".
**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Isolated branch feat/relay-activation-projection starts at 1042385ea78e4a372dbd1aac311b1ea9410273ba. Target files are api/routes.py and tests/test_relay_capacity_isolation.py only. Work Record committed before edits. Root is sole operator for live service and deployment. The parent assignment reviewed and prescribed the bounded implementation; the regression is added first to reproduce the existing projection thread failure.

Implementation keeps synchronous recursive projection and its existing exception handling intact, with one async wrapper using _relay_call("activation_projection", ...). All 12 external callers await it after their existing callbacks. No-callback responses return unchanged without dispatch. The ASGI regression intercepts the existing router injection and delegates to the real app.main runner; it verifies concurrent health progress, operation tracking, callback order, Unicode identity, preserved activation results, and best-effort projection errors for turn and session-list responses. Its readback assertion normalizes the existing SQLite UTC timezone formatting difference; production timestamp behavior is unchanged.

## Evidence

Read all shared decorator callers, app/dependencies.py activation callback, and app/main.py operation runner. The new focused regression on old source failed at the assertion that projection must execute outside the event-loop thread (1 failed in 1.01s). After implementation and adjustment for the existing SQLite timestamp formatting, focused known failures passed: 2 passed in 0.73s.

Affected HTTP route checks: `python -m pytest tests/test_relay_capacity_isolation.py tests/test_agent_relay_e2e.py tests/test_relay_mcp_lifecycle.py tests/test_cross_container_relay_e2e.py tests/test_relay_work_ref_associations_e2e.py tests/test_opencode_relay_wake_e2e.py -q -n 0` -> 148 passed in 76.27s. `python scripts/run-import-linter.py --out build/import-linter-report.json` -> exit 0, no boundary violations. `git diff --check` -> clean. Fresh redline verdict: RED, api-review required; no boundary violations. Workflow check before result-review transition: advisory only for the unsatisfied api-review checkpoint. No protected behavior-contract paths changed.

The validation selector requires the full application lane (`python -m pytest tests/ -x -q`). Parent explicitly owns the final combined full run, including its test-transport isolation change; no duplicate full suite was run here. Independent result review and installed qualification are pending parent completion.

## Result review

Agent technical review: /root/incident_integration_review, independent non-implementer, accepted combined source on 2026-10-08.
Reviewed revision: dba1bb1f743e456ab706e35f29edeeee97d68973.
Verification adequacy: deterministic ASGI red/green and 148 affected passes establish component behavior; combined full regression and CI remain pending. No source changes after the affected run.

## Handoff

Parent owns independent result review, full-suite evidence, PR/merge and installed-service qualification. Retain this isolated worktree until parent has reviewed and integrated its commit.
