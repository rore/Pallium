# Make exact Codex wake claims durable

<!-- agent-workflow:start -->
**Outcome:** A committed exact Codex wake claim remains correlated after the route loses its post-claim registry write, permitting safe lease-expiry recovery.

**Target:** Pallium Relay Codex wake claim and reservation reconciliation.

**Scope:** `app/codex_wake.py`, `core/codex_wake.py`, `app/dependencies.py`, `api/routes.py`, `core/relay.py`, `storage/sqlite_relay.py`, `storage/sqlite_schema.py`, focused caller-surface tests, the Relay roadmap, and this Work Record. No hook prompt or public API request change.

**Constraints:** Do not clear historical uncorrelated fences, retry uncertain native submissions without exact claim evidence, interrupt a busy recipient, or change workspace, scope, model, or effort. Preserve single-flight native submission and exact claim/ACK semantics. No live user-session experiments or private incident fixtures.

**Completion criteria:** A real hook/API claim committed before callback/process loss recovers once after lease expiry; a newer generation cannot use a snapshot from an older in-flight request. Ordinary, mismatched, live-lease, uncertain-without-claim, and uncorrelated historical cases remain fenced. ACK releases the fence. Existing validated moved-endpoint recovery continues. The roadmap distinguishes future prevention from unresolved historical and native-admission cases.

**Requirement baseline:** {"source":"user Relay reliability objective and manager task 01a07bef-18c8-71b2-89ab-c0cbe91e73ad","outcome":"Prevent an exact Codex wake claim committed before callback/process loss from leaving a permanent accepted reservation.","scope":"Minimal durable exact-claim evidence, recovery and caller-surface tests, roadmap and Work Record.","constraints":"No blind native retry, duplicate queued turns or payload processing, user-session interruption, or workspace/scope/model/effort changes; preserve historical fences without invented evidence.","completion_criteria":"Exact claim evidence survives callback/process loss and permits only lease-expired same-generation recovery; unrelated, stale, partial, or legacy evidence cannot unlock a reservation."}

**Risk:** High

**Complexity:** Moderate

**Reason:** Redline reports `api/routes.py` red/API_CHANGE and `storage/sqlite_schema.py` red/SCHEMA_CHANGE, requiring API and persistence review. This changes durable claim/recovery behavior across route, storage, and wake registry.

**Discovery:** The live accepted wake began an automatic turn; its hook failed before a Relay claim committed, while the reservation kept no correlated attempt. A controlled actual-hook/loopback test shows current callbacks normally correlate even after hook timeout; the historical loss point remains unproven. Current recovery writes exact claim correlation to a separate file after the SQLite claim, leaving a split-write window. The callback currently binds to whichever generation is current after claim. Native queue absence and timeout do not justify releasing an uncorrelated fence.

**Material assumptions:** The shipped exact wake delivery ID is the existing correlation authority, not trusted native queue-origin attestation. A matching immutable reservation snapshot taken before the claim can be used for both DB evidence and callback compare-and-set; if a caller-surface race disproves this, stop. A copied old prompt arriving only after replacement could snapshot the new generation, just as the current callback could; this plan must not claim to solve that host-origin limitation or worsen it. Existing Relay SQLite stores can add a nullable claim-generation column safely; failed migration stops rollout.

**Plan:** Keep the existing hook prompt and HTTP request contract. Before an exact /relay/turn claim, capture one immutable current reservation matching delivery ID, session, and container. Pass only its endpoint ID and generation as internal arguments to RelayService.turn; the SQLite claim transaction stores that generation only if the selected exact delivery matches the captured endpoint, and clears the marker on ordinary claims. Pass the same captured snapshot to the existing post-claim callback, which compare-and-sets correlation against that generation instead of whichever fence is current later. During recovery, permit the existing expired-lease replacement only if either the file-correlated attempt matches the latest claim or the stored DB generation matches the current reservation and latest exact claim. Keep the existing validated current-endpoint target after a scope move; neither claim nor recovery creates a move. New generations do not match old DB evidence. Do not alter native submission/retry or ACK order. First demonstrate the split-write failure with a caller-surface callback-loss test, then prove recovery and negatives. Update roadmap. Stop for fresh clean-context review and human approval before production edits.

**Verification plan:** Exact claim commit followed by callback loss recovers after lease expiry with one replacement, not during a live lease → actual hook/API controlled-clock test. A generation change during the request fails the callback CAS and old DB evidence cannot unlock the new fence → race and stale-generation tests. Ordinary, missing, partial, wrong-endpoint, and uncertain-without-claim evidence causes no retry → route/reconcile negatives. Busy accepted wake stays single-flight → existing regression. A validated endpoint move still rehomes recovery, while ACK gives one delivered state and releases the fence → existing and new lifecycle tests. Schema upgrade/restart preserves new evidence and leaves old rows conservative → file-backed migration/restart test. Then affected subsystem, one repository suite, workflow/Redline check, PR/CI review, and exact-main installed health checks.

**Plan review:** Fresh clean-context review approved the revised server-only plan with callback CAS and explicit SQLite migration caveats; see ## Plan review.

**Approvals:** Pending explicit human High-risk plan approval.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Discovery and evidence

The existing actual-hook/loopback delayed-claim test passed (1 test, 3.44s): after hook timeout, the current route still recorded attempt 1 and lease recovery submitted one replacement. This is a positive control, not reproduction of the live missing correlation. A later bounded real-Uvicorn socket replay passed on #235 parent a3c045b5 (1.78s), #235 a29bb260 (2.44s), and current f39b30d7 (1.64s): a 250 ms client timeout preceded the exact server claim; callback correlation persisted, the second delivery coalesced without another native submission, and one expired-lease sweep rearmed once after 61 controlled seconds. It used isolated databases/registries and a stub launcher. This does not reproduce the historical missing correlation or prove its cause. At the incident-time revision, no-ID scope bootstrap/replay requests have a one-character response budget smaller than the fixed Relay message envelope, so they cannot themselves mark a delivery claimed. The exact request that made the historical claim was not logged. The post-claim callback can silently return false, and a separate stale registry writer could overwrite a successful correlation, but neither is established for this incident; the earlier temporary benchmark ended before #233 merged, over two hours before this claim. The installed canonical Relay database maps to the same wake directory before and after #235; #233 did not change turn/wake behavior, and #237/#238 postdate the first failures. The earlier temporary API cross-instance fence release is real but not causally linked to this later reservation. Recipient metadata shows an automatic turn started 84 ms after the prior turn, with no separate user prompt during the observed late claim. No live fence was cleared or wake resent.

## Plan review

The first clean-context review blocked the prompt-generation draft: the file callback could attach to a newer generation, and a strict old-scope comparison would break validated moved-endpoint recovery. The revised server-only snapshot plan fixes the in-flight generation race and preserves moved-scope behavior. A fresh clean-context reviewer approved it with two implementation checks: use the same captured snapshot for callback CAS, and migrate the nullable SQLite column explicitly while old rows remain conservative. An old copied prompt arriving after replacement remains an existing host-origin limitation, not solved here. Historical accepted/null-correlation reservations cannot be auto-repaired from missing evidence; do not blanket-clear them.
