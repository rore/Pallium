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
**Plan review:** Pending independent technical review from parent before production edits.
**Approvals:** Prior user authorization for mission-critical isolated incident fixes relayed by parent; exact quote/source requested for final workflow evidence.
**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Isolated branch feat/relay-activation-projection starts at 1042385ea78e4a372dbd1aac311b1ea9410273ba. Target files are api/routes.py and tests/test_relay_capacity_isolation.py only. No code edits before plan review. Root is sole operator for live service and deployment.

## Evidence

Read all shared decorator callers, app/dependencies.py activation callback, and app/main.py operation runner. No tests run yet.

## Handoff

Parent owns independent result review, full-suite evidence, PR/merge and installed-service qualification. Retain this isolated worktree until parent has reviewed and integrated its commit.
