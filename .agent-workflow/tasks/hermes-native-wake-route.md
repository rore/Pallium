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
Pending independent non-implementer technical review before code/test edits.

**Approvals:**
Continuing isolated emergency bugfix/PR/green merge authorized. PR363 profile update approval does not authorize a new runtime result or clearing the failed wake record. Not required at this risk level.

**Exceptions:**
—

**State:**
Blocked
<!-- agent-workflow:end -->

## Implementation

2026-10-26: New isolated branch feat/hermes-native-wake-route from merged39d21623. Prior PR363 source and installed evidence preserved. Exact intended edits are in Scope; no live changes for this new boundary. Sole owner @relaydev, canonical add-wake-first-relay-delivery stays with manager. User explicitly requested no desktop takeover and to avoid restarts. Previous fixtures accepted callback IDs as routes and missed the installed host boundary; the new fixture must separate these values.

## Evidence

Installed original reply relay-delivery-d5553ca452614c7f97225ce68288acfe remains pending with attempts0; private wake is injection_attempted with no turn_id. Definite gateway not-routed diagnostic explains one failed enqueue, but no general automatic retry of uncertain wakes is authorized.

## Result review

Pending.

