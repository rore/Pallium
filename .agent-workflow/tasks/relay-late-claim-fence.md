# Make exact Codex wake claims durable

<!-- agent-workflow:start -->
**Outcome:** A committed exact Codex wake claim remains correlated after the route loses its post-claim registry write, permitting safe lease-expiry recovery.

**Target:** Pallium Relay Codex wake claim and reservation reconciliation.

**Scope:** `app/codex_wake.py`, `core/codex_wake.py`, `app/dependencies.py`, `api/routes.py`, `api/schemas.py`, `core/relay.py`, `storage/sqlite_relay.py`, `storage/sqlite_schema.py`, both Codex hook files, focused caller-surface tests, the Relay roadmap, and this Work Record. Remove unnecessary paths during implementation.

**Constraints:** Do not clear historical uncorrelated fences, retry uncertain native submissions without exact claim evidence, interrupt a busy recipient, or change workspace, scope, model, or effort. Preserve single-flight native submission and exact claim/ACK semantics. No live user-session experiments or private incident fixtures.

**Completion criteria:** A real hook/API claim committed before callback/process loss recovers once after lease expiry; a newer generation cannot use older evidence. Ordinary, mismatched, live-lease, uncertain-without-claim, and legacy cases remain fenced. ACK releases the fence. The roadmap distinguishes future prevention from unresolved historical and native-admission cases.

**Requirement baseline:** {"source":"user Relay reliability objective and manager task 01a07bef-18c8-71b2-89ab-c0cbe91e73ad","outcome":"Prevent an exact Codex wake claim committed before callback/process loss from leaving a permanent accepted reservation.","scope":"Minimal durable exact-claim evidence, recovery and caller-surface tests, roadmap and Work Record.","constraints":"No blind native retry, duplicate queued turns or payload processing, user-session interruption, or workspace/scope/model/effort changes; preserve historical fences without invented evidence.","completion_criteria":"Exact claim evidence survives callback/process loss and permits only lease-expired same-generation recovery; unrelated, stale, partial, or legacy evidence cannot unlock a reservation."}

**Risk:** High

**Complexity:** Moderate

**Reason:** Redline reports `api/routes.py` and `api/schemas.py` red/API_CHANGE and `storage/sqlite_schema.py` red/SCHEMA_CHANGE, requiring API and persistence review. This changes a durable recovery contract across hook, API, storage, and wake registry.

**Discovery:** The live accepted wake began an automatic turn; its hook failed before a Relay claim committed, while the reservation kept no correlated attempt. A controlled actual-hook/loopback test shows current callbacks normally correlate even after hook timeout; the historical loss point remains unproven. Current recovery writes exact claim correlation to a separate file after the SQLite claim, leaving a split-write window. Native queue absence and timeout do not justify releasing an uncorrelated fence. Existing prompts lack generation and remain conservative.

**Material assumptions:** The shipped exact wake prompt is the existing correlation authority, not trusted native queue-origin attestation; if review requires a stronger origin guarantee, stop rather than invent it. Newly scheduled prompt generation stays stable until its hook turn and can be recorded only for the selected exact delivery in the claim transaction; a failing caller-surface test returns this to planning. Existing Relay SQLite stores can add a nullable claim-generation column safely; failed migration stops rollout.

**Plan:** Keep the existing delivery-ID filter and post-claim file correlation. Put the current reservation generation in new exact wake prompts and carry it only in the final exact /relay/turn request; legacy prompts remain accepted without new proof. Within the SQLite transaction that claims that exact delivery, store its wake generation; clear the marker on ordinary/legacy claims. Reconcile an expired lease only when the existing file-correlated attempt still matches the current attempt, or when the stored generation matches the current reservation and latest claim, endpoint, session, and scope match. Replacement allocates a new generation, so older evidence cannot release it. Keep native submission/retry and ACK order unchanged. First demonstrate the current split-write failure by dropping the route callback after DB commit; then prove the new path and negative cases. Update the roadmap. Stop for clean-context review and explicit human approval before production edits.

**Verification plan:** Exact claim commit followed by callback loss recovers after lease expiry with one replacement, not during the live lease → actual hook/API controlled-clock test. Old, unrelated, missing, or wrong-scope evidence causes no retry → route/reconcile negatives. Busy accepted wake stays single-flight → existing regression. Hook emit+ACK gives one delivered state and releases fence → actual hook lifecycle. Schema upgrade/restart preserves new evidence and leaves old rows conservative → file-backed migration/restart test. Then affected subsystem, one repository suite, workflow/Redline check, PR/CI review, and exact-main installed health checks.

**Plan review:** Pending clean-context review.

**Approvals:** Pending explicit human High-risk plan approval.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Discovery and evidence

The existing actual-hook/loopback delayed-claim test passed (1 test, 3.44s): after hook timeout, the current route still recorded attempt 1 and lease recovery submitted one replacement. This is a positive control, not reproduction of the live missing correlation. A bounded real-ASGI setup stopped before any request. Recipient metadata shows an automatic turn started 84 ms after the prior turn, with no separate user prompt during the observed late claim. No live fence was cleared or wake resent.

## Plan review

Pending clean-context review. Historical accepted/null-correlation reservations predate the proposed generation marker and cannot be auto-repaired with missing evidence. Do not blanket-clear them.