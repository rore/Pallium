# Relay ACK wire-boundary correction

<!-- agent-workflow:start -->
**Outcome:** The hook delay test observes a real loopback ACK response independently of completion of the response-owned ASGI callback.

**Target:** Pallium Relay hook test bridge.

**Scope:** tests/test_agent_relay_hooks.py, tests/test_relay_capacity_isolation.py, and this Work Record.

**Constraints:** Tests only. Preserve ACK API semantics, 0.5s timeout, existing four delay rows and late-ACK assertions, all current ownership rows, and all callback/server/storage cleanup checks. Do not change production, global helpers, dependencies, or user environment.

**Completion criteria:** The existing delayed-hook rows use real loopback HTTP and prove exact matching response receipt within existing budgets; the TCP ownership test proves the full response returns before its held callback and ASGI invocation finish, then proves cleanup.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"The hook delay test observes a real loopback ACK response independently of completion of the response-owned ASGI callback.","scope":"tests/test_agent_relay_hooks.py, tests/test_relay_capacity_isolation.py, and this Work Record.","constraints":"Tests only. Preserve ACK API semantics, 0.5s timeout, existing four delay rows and late-ACK assertions, all current ownership rows, and all callback/server/storage cleanup checks. Do not change production, global helpers, dependencies, or user environment.","completion_criteria":"The existing delayed-hook rows use real loopback HTTP and prove exact matching response receipt within existing budgets; the TCP ownership test proves the full response returns before its held callback and ASGI invocation finish, then proves cleanup."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** All scoped paths classify BLUE, but judgment is Elevated/Moderate because the proof changes a timing-sensitive transport boundary and owns real server, worker, and storage cleanup.

**Discovery:** The approved source assessment at `C:\Dev\rore\Pallium\build\relay-health-observation-clock-hosted-20261024\ack-bridge-source-assessment.md` has SHA-256 `307105D52FF99DED48E4AC7DCBBE1DD092A529D93E24C93C398DD9217275BE1E`. It identifies the current bridge's in-process `TestClient` serialization boundary and existing `ScratchServer` plus TCP ownership proof as the supported reuse points. Compared target base `982cc369bc31cc252c3131d83af475c7db95a516` with pinned `267e9ace0e749fa3314074931be3a24bdf288186`: the selected delayed-hook function, TCP ownership function, `ScratchServer`/HTTP helpers, app lifespan, and ACK route are unchanged. The same two test files contain unrelated edits in other cases (legacy pin and UTF-8 setup in the hook tests; admission-clock and diagnostic-worker cases in capacity tests); no unrelated hunk is imported. The current source retains the planned APIs and cleanup pattern.

**Material assumptions:** The isolated app and storage can have one explicit lifespan owner using the existing TCP ownership fixture pattern; disproved by needing borrowed-app/double-lifespan behavior, then stop. Test-local proxy-free health/client setup can avoid ambient Windows proxy configuration without changing `ScratchServer`; disproved if global/helper edits are required, then stop. The existing approved plan review `C:\Dev\rore\Pallium\build\relay-health-observation-clock-hosted-20261024\ack-bridge-source-assessment.md SHA-256 307105D52FF99DED48E4AC7DCBBE1DD092A529D93E24C93C398DD9217275BE1E` covers unchanged scope and approach; any material mismatch returns to owner.

**Plan:** Reuse the parent-approved source-plan review at C:\Dev\rore\Pallium\build\relay-health-observation-clock-hosted-20261024\ack-bridge-source-assessment.md SHA-256 307105D52FF99DED48E4AC7DCBBE1DD092A529D93E24C93C398DD9217275BE1E; retain the existing proxy handler semantics and use the unchanged ScratchServer for the loopback upstream. Add only local ASGI send/invocation observation to the existing TCP ownership test, forwarding each ASGI message unchanged. Use test-local no-proxy/no-redirect health and HTTP clients and a test-local fixed-loopback urllib opener for the real hook. Preserve all current timing, exact response/state/attempt/trace, no-refresh, late-ACK, and cleanup assertions. Stop if production/global helper/dependency/framework changes or any assertion weakening is needed. The already approved nine-case focus is eligible after actual diff and packet review is CLEAR.

**Verification plan:** Static diff review confirms only the three scoped files changed and preserves all named assertions and four existing parameter rows. After actual diff and packet review is CLEAR, run the exact nine existing source-expected cases in the supplied qualification envelope; do not collect, import, probe, or run CI before then.

**Plan review:** Agent technical review: C:\Dev\rore\Pallium\build\relay-health-observation-clock-hosted-20261024\ack-bridge-source-assessment.md SHA-256 307105D52FF99DED48E4AC7DCBBE1DD092A529D93E24C93C398DD9217275BE1E. Parent delegated authority approved this exact test-only implementation and one nine-case focus, subject to actual diff/packet review being CLEAR.

**Approvals:** Not required at this risk level; implementation and one nine-case focus explicitly approved by parent delegated task-owner mandate, subject to actual diff/packet review being CLEAR.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Initial record established against base 982cc369bc31cc252c3131d83af475c7db95a516; source-plan SHA-256 verified. The Work Record was committed before source edits.
- Frozen starting point: full CI run 40133974202 at base 982cc369bc31cc252c3131d83af475c7db95a516.
- Implemented only the delayed-hook transport/local setup, its existing late-ACK caller, and the TCP ACK ownership proof. Edits used deterministic .NET text replacement because apply_patch had already failed with machine error 1385; it was not retried.
- Blocked pending parent actual-diff/packet review being CLEAR before the already approved nine-case qualification focus.

## Evidence

- Approved source assessment: `C:\Dev\rore\Pallium\build\relay-health-observation-clock-hosted-20261024\ack-bridge-source-assessment.md` (SHA-256 `307105D52FF99DED48E4AC7DCBBE1DD092A529D93E24C93C398DD9217275BE1E`).
- Approved source-plan review: C:\Dev\rore\Pallium\build\relay-health-observation-clock-hosted-20261024\ack-bridge-source-assessment.md (SHA-256 307105D52FF99DED48E4AC7DCBBE1DD092A529D93E24C93C398DD9217275BE1E); parent delegated authority approved implementation and one nine-case focus subject to CLEAR actual-diff/packet review.
- git diff --check passed on the three scoped paths. No tests, collection, imports, probes, or CI run.
- Expected selectors, preserved from the approved source plan: four delayed-hook rows, the existing ack_response_delay=0.65 late-ACK wrapper, and four TCP ownership rows.
- Privacy closure: test-local urllib opener uses ProxyHandler({}) and rejects redirects; both health readers and HTTPX clients use fixed loopback URLs with environment proxies and redirects disabled. No ambient provider, profile, model, or proxy configuration was inspected.

## Source-review repair before qualification

SAME independent actual-source review rejected e0dac24209a5aa8a7fdf74f437443827431cc7e2 on four concrete lifecycle issues: early construction/initialization lacked a registered fallback; the hook shared HTTP client closed before its handler users drained; fallback storage cleanup could run under a live server/request owner; closure flags preceded actual completion. Review evidence actual-source-review.md SHA256 2F834CD1F6775961280D48A848BC17A97C731E5CC6DF91D4B93BFD7F0869FDBA in build/relay-ack-wire-qualification-20261024.

The bounded implementation worker encountered an exact-replacement/line-ending failure while applying the review fixes. Root stopped it, inspected the dirty diff and restored only its uncommitted capacity-test edits to e0dac242, including two accidentally touched unrelated functions. No work outside the two approved test paths was lost or changed. Root completed narrowly scoped deterministic .NET replacements within the two named functions; the machine-local apply_patch1385 no-retry constraint remains in effect. No interpreter, tests, collection, import, probe or CI was run.

Cleanup fallback is registered before construction and initialization. Hook proxy handlers drain before their upstream client closes. Owned resources are retained and the test fails if server/request owners remain alive; fallback never disposes storage underneath them. Both completed-close flags now follow original_close return. The TCP proof releases its callback in finally and checks owned worker/server/shutdown threads before fallback closure. The test-local urllib builder delegates to the original builder with explicit no-proxy/no-redirect handlers, preserving its lazy HTTPS handler. Every original parameter row, delay, timeout, matching-response/state/attempt/trace/late-ACK assertion remains unchanged. SAME actual revised-source review and the exact reviewed nine-case packet/current manager CLEAR remain before the already-approved one focused execution. Historical REDs remain; no physical-cause, native availability, production or release claim follows this test correction.