# Relay ACK wire-boundary correction

<!-- agent-workflow:start -->
**Outcome:** The hook delay test observes a real loopback ACK response independently of completion of the response-owned ASGI callback.

**Target:** Pallium Relay hook test bridge.

**Scope:** `tests/test_agent_relay_hooks.py`, `tests/test_relay_capacity_isolation.py`, and this Work Record.

**Constraints:** Tests only. Preserve ACK API semantics, 0.5s timeout, existing four delay rows and late-ACK assertions, all current ownership rows, and all callback/server/storage cleanup checks. Do not change production, global helpers, dependencies, or user environment.

**Completion criteria:** The existing delayed-hook rows use real loopback HTTP and prove exact matching response receipt within existing budgets; the TCP ownership test proves the full response returns before its held callback and ASGI invocation finish, then proves cleanup.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"The hook delay test observes a real loopback ACK response independently of completion of the response-owned ASGI callback.","scope":"tests/test_agent_relay_hooks.py, tests/test_relay_capacity_isolation.py, and this Work Record.","constraints":"Tests only. Preserve ACK API semantics, 0.5s timeout, existing four delay rows and late-ACK assertions, all current ownership rows, and all callback/server/storage cleanup checks. Do not change production, global helpers, dependencies, or user environment.","completion_criteria":"The existing delayed-hook rows use real loopback HTTP and prove exact matching response receipt within existing budgets; the TCP ownership test proves the full response returns before its held callback and ASGI invocation finish, then proves cleanup."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** All scoped paths classify BLUE, but judgment is Elevated/Moderate because the proof changes a timing-sensitive transport boundary and owns real server, worker, and storage cleanup.

**Discovery:** The approved source assessment at `C:\Dev\rore\Pallium\build\relay-health-observation-clock-hosted-20261024\ack-bridge-source-assessment.md` has SHA-256 `307105D52FF99DED48E4AC7DCBBE1DD092A529D93E24C93C398DD9217275BE1E`. It identifies the current bridge's in-process `TestClient` serialization boundary and existing `ScratchServer` plus TCP ownership proof as the supported reuse points. Current source is compared to pinned `267e9ace0e749fa3314074931be3a24bdf288186` before implementation; any material difference affecting the plan is a stop condition.

**Material assumptions:** The isolated app and storage can have one explicit lifespan owner using the existing TCP ownership fixture pattern; disproved by needing borrowed-app/double-lifespan behavior, then stop. Test-local proxy-free health/client setup can avoid ambient Windows proxy configuration without changing `ScratchServer`; disproved if global/helper edits are required, then stop. The existing approved plan review `review307...` covers unchanged scope and approach; any material mismatch returns to owner.

**Plan:** Reuse the parent-approved source plan and its review reference `review307...`; retain the existing proxy handler semantics and use the unchanged `ScratchServer` for the loopback upstream. Add only local ASGI send/invocation observation to the existing TCP ownership test, forwarding each ASGI message unchanged. Use a test-local no-proxy/no-redirect health/client path if the current fixture does not already own one. Preserve all current timing, exact response/state/attempt/trace, no-refresh, late-ACK, and cleanup assertions. Stop if production/global helper/dependency/framework changes or any assertion weakening is needed. Static review only until the parent authorizes qualification after diff review.

**Verification plan:** Static diff review confirms only the three scoped files changed and preserves all named assertions and four existing parameter rows. After separate parent authorization, run the exact nine existing source-expected cases in the supplied qualification envelope; do not collect, import, probe, or run CI in this implementation turn.

**Plan review:** Agent technical review: `review307...` (parent-provided approved source-plan review; source assessment SHA-256 above). Parent delegated authority approved this exact test-only implementation and one nine-case focus.

**Approvals:** Not required at this risk level; implementation scope explicitly approved by parent delegated task-owner mandate.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Initial record established against base `982cc369bc31cc252c3131d83af475c7db95a516`; source-plan SHA-256 verified. No tests, collection, imports, probes, or CI run.

## Evidence

- Approved source assessment: `C:\Dev\rore\Pallium\build\relay-health-observation-clock-hosted-20261024\ack-bridge-source-assessment.md` (SHA-256 `307105D52FF99DED48E4AC7DCBBE1DD092A529D93E24C93C398DD9217275BE1E`).
- Approved plan review reference: `review307...` (provided by parent).