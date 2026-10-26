# Hermes native wake route repair

<!-- agent-workflow:start -->
**Outcome:**
Hermes wakes target the native host route of the intended conversation instead of its Relay conversation identifier.

**Target:**
Pallium Hermes native integration.

**Scope:**
integrations/hermes/__init__.py runtime route capture and poller target selection; focused tests/test_hermes_relay_plugin.py fixture and routing regressions.

**Constraints:**
Copy host-provided identity unchanged; never construct native routes from profile/name/session text. Preserve Relay session refs, profile/endpoint/claim/ACK and uncertain-wake fences. No desktop control, forced turn, resend, receive or unapproved state/config/installed edits. Retain legacy callback-ID targeting only when the public route module is genuinely absent.

**Completion criteria:**
Two distinct conversations in one profile use their respective runtime-provided native routes even from a poller started in the first context; intended payload reaches hook/request admission and ACK with original Relay identity. Missing/invalid current-host routes fail closed, legacy host behavior is preserved, and uncertain attempted wakes remain fenced.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Hermes wakes target the native host route of the intended conversation instead of its Relay conversation identifier.","scope":"integrations/hermes/__init__.py runtime route capture and poller target selection; focused tests/test_hermes_relay_plugin.py fixture and routing regressions.","constraints":"Copy host-provided identity unchanged; never construct native routes from profile/name/session text. Preserve Relay session refs, profile/endpoint/claim/ACK and uncertain-wake fences. No desktop control, forced turn, resend, receive or unapproved state/config/installed edits. Retain legacy callback-ID targeting only when the public route module is genuinely absent.","completion_criteria":"Two distinct conversations in one profile use their respective runtime-provided native routes even from a poller started in the first context; intended payload reaches hook/request admission and ACK with original Relay identity. Missing/invalid current-host routes fail closed, legacy host behavior is preserved, and uncertain attempted wakes remain fenced."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Gray integration runtime path; native addressing must stay separated from Relay identity and profile ownership. No service/API/persistence contract changes.

**Discovery:**
PR363 fixed missing profile context and is installed through approved profile-only reload. Poller now attempts original reply d5553ca, but gateway.log2026-10-26T17:15:39.362+02 reports injected session local-b7... was not routed. Runtime hook supplies agent.session_id; ctx.inject_message(session_key=...) expects native route. Hermes public hermes_cli.plugin_session.session_key() returns the current task-local route unchanged. Host accepts scheduling before route resolution, so injection_attempted is still uncertain to plugin; no retry/reset authorized. Original Relay reply remains pending attempts0.

**Material assumptions:**
Public helper supplies the route under the same validated foreground hook scope. Assert explicit per-session binding; never use a poller's ambient first-session context to select another destination. Missing public module retains legacy existing path; any installed-module failure, empty/malformed key refuses a new binding. Stop/replan if native key cannot be obtained through public APIs.

**Plan:**
At successful register_session, capture the public session_key() in foreground context and keep an in-memory per-session wake target beside existing sessions. Only fall back to the existing callback session_id on exact missing optional public module, not accessor failure/invalid output. Poll_session injects using the captured explicit native target; Relay API identity/state stays unchanged. Add a fake public accessor and host router that deliberately distinguish native key from callback ID for two sessions, plus empty/invalid/error and legacy controls. Reuse PR363 profile-context fix. Do not alter persisted attempted-wake policy; operator recovery for the definitively unrouted original requires a separate reviewed exact action/approval.

**Verification plan:**
Native route/callback separation and multi-session ownership -> regression fails before fix, then drives correct injection, full payload and ACK through existing caller surfaces.
Current-helper invalidity and legacy compatibility -> focused failure matrix and unchanged affected Hermes checks.
Review/delivery -> independent technical review, normal governance checks, required hosted CI and approved local application only. Preserve original pending reply; no manual fallback counts as automatic qualification.

**Plan review:**
Agent technical review: astra-reviewer, turn01a178d3-edab-7660-8b44-6a4bc852c4bb: GO with lifecycle conditions. Capture exact public key during validated foreground registration; publish under existing lock with matching session/endpoint. Missing/invalid accessor must invalidate an old in-memory target; refuse absent/mismatched binding before persisting injection_attempted. Exact missing optional module may retain legacy behavior; nested import/accessor failure must not fall back. Preserve attempted-wake fences on route changes. Require two-conversation payload/ACK and valid-to-invalid binding tests. No live change/reset approval implied.

**Approvals:**
Continuing isolated emergency bugfix/PR/green merge authorized. PR363 profile update approval does not authorize a new runtime result or clearing the failed wake record. Not required at this risk level.

**Exceptions:**
—

**State:**
Ready to implement
<!-- agent-workflow:end -->

## Implementation

2026-10-26: New isolated branch feat/hermes-native-wake-route from merged39d21623. Prior PR363 source and installed evidence preserved. Exact intended edits are in Scope; no live changes for this new boundary. Sole owner @relaydev, canonical add-wake-first-relay-delivery stays with manager. User explicitly requested no desktop takeover and to avoid restarts. Previous fixtures accepted callback IDs as routes and missed the installed host boundary; the new fixture must separate these values.

## Evidence

Installed original reply relay-delivery-d5553ca452614c7f97225ce68288acfe remains pending with attempts0; private wake is injection_attempted with no turn_id. Definite gateway not-routed diagnostic explains one failed enqueue, but no general automatic retry of uncertain wakes is authorized.

Implementation captures hermes_cli.plugin_session.session_key() during foreground registration, validates the opaque key, and binds it under the existing lock to the matching session/endpoint record. Invalid or changed accessors retire the old in-memory target. The poller checks the binding before persisting a wake and supplies the exact native key explicitly. Only the exact absent optional module retains legacy callback-ID behavior. Persisted wake state, Relay identity, claim/ACK and uncertain-wake rules are unchanged.

The two-conversation regression failed before production edits (1 failed in5.61s; build/hermes-route-before.log), because its native scheduler deliberately accepts scheduling without routing callback IDs. After the fix, both conversations inject through distinct native routes, admit full payload and ACK with original Relay refs. Six valid-to-invalid accessor cases prevent injection/claim; two route-change cases preserve an existing injection_attempted record unchanged. Legacy-host coverage remains exercised by the existing fixture with the optional module absent.

Focused routing/accessor cases:7 passed in4.47s, build/hermes-route-focused.log. Final affected plugin file:212 passed in150.01s, build/hermes-route-subsystem.log, including the two attempted-wake preservation cases. Related History and role tests:52 passed in28.20s, build/hermes-route-related.log. An earlier sandbox test attempt failed during pytest temporary-directory creation before running either case; isolated elevated execution succeeded. All tests disable the live service URL and use private temporary data. No installed or persistent user files were modified.

Whole-change selector reports the full lane. Under the human's emergency instruction, required hosted full CI supplies broad validation; no redundant broad local suite. Import-linter passed; actual changed-path redline report is GRAY with no boundary/API/schema/security/config or protected-contract changes. Source evidence and native installed qualification remain separate. No new native-host success is claimed.

## Result review

Agent technical review: astra-reviewer, turn01a178e1-8248-7ec0-a8ab-03889c1d0439, reviewed dd7bd64f and found a validation-to-dispatch race. Route invalidation could win after the binding check but before injection. Current tests changed routes only after injection and missed that interleaving. No GO yet.

Review correction: keep the existing RLock across the short host scheduling call, and recheck the binding after profile validation immediately before dispatch. Other-thread invalidation serializes with dispatch; synchronous reentrant callbacks remain supported. Two deterministic state-write boundary cases replace/invalidate the route after wake persistence and before dispatch, then assert no stale injection, no claim, and conservative attempted-wake fencing. Both failed before this correction (build/hermes-route-race-before.log,2 failed in1.82s); both plus late-refusal replacement and the two-conversation payload/ACK case passed afterward (build/hermes-route-race-after.log,4 passed in2.49s). Native gateway scheduling returns before dispatch and the classic host enqueues, so this does not hold a lock across model execution. No new transport/fence policy.

