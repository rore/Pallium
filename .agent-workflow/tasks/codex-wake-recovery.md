# Codex wake recovery

<!-- agent-workflow:start -->
**Outcome:** Pending Relay messages reach eligible Codex recipients without manual recovery after an older wake has an uncertain outcome.
**Target:** Pallium Codex wake scheduling and delivery recovery.
**Scope:** app/codex_wake.py, app/codex_bridge_pipe.py, core/codex_wake.py, storage/sqlite_relay.py and existing reservation schema only if necessary; focused caller-surface recovery tests; docs/codex-integration.md, docs/agent-relay.md and owning roadmap item.
**Constraints:** Preserve exact recipient identity and scope, durable claim/ACK exclusion, active-claim protection, fresh non-busy eligibility and single-owner transitions. No live database resets, payload resend, working-chat tests, new transport or speculative infrastructure. Do not claim exactly-once model execution from a hook ACK.
**Completion criteria:** An isolated caller-surface test reproduces old uncertain wake plus later message starvation; the corrected path delivers pending payload through the hook and ACK without a manual turn; concurrent and late wake paths do not concurrently claim or re-emit acknowledged payload; unavailable and working targets remain pending and recover when eligible.
**Requirement baseline:** {"source":"user:ec23dc00-5d29-465a-9012-17458b3a4841","outcome":"Pending Relay messages reach eligible Codex recipients without manual recovery after an older wake has an uncertain outcome.","scope":"app/codex_wake.py, app/codex_bridge_pipe.py, core/codex_wake.py, storage/sqlite_relay.py and existing reservation schema only if necessary; focused caller-surface recovery tests; docs/codex-integration.md, docs/agent-relay.md and owning roadmap item.","constraints":"Preserve exact recipient identity and scope, durable claim/ACK exclusion, active-claim protection, fresh non-busy eligibility and single-owner transitions. No live database resets, payload resend, working-chat tests, new transport or speculative infrastructure. Do not claim exactly-once model execution from a hook ACK.","completion_criteria":"An isolated caller-surface test reproduces old uncertain wake plus later message starvation; the corrected path delivers pending payload through the hook and ACK without a manual turn; concurrent and late wake paths do not concurrently claim or re-emit acknowledged payload; unavailable and working targets remain pending and recover when eligible."}
**Risk:** High
**Complexity:** Moderate
**Reason:** Persistent wake fencing and delivery liveness interact with non-idempotent native submission. Persistence review applies if storage changes; independent review is required before production edits.
**Discovery:** Live incident recovered manually: September 15 legacy nonzero_exit left an uncertain durable reservation for a never-expiring unclaimed delivery. October 6 later assignment could not reserve the endpoint. Ordinary hook receipt released it and all three messages were ACKed. Existing regression intentionally asserts no second native submission, so passing it does not satisfy the new liveness requirement.
**Material assumptions:** Payload claim/ACK deduplication does not imply exactly-once native wake or exactly-once model execution. If safe recovery needs another native notification, expose that tradeoff before production edits. No age-only inference that an uncertain wake was never submitted.
**Plan:** Invoke agent-workflow and classify before edits; first add an isolated failing liveness regression through existing HTTP scheduler surfaces. Obtain a clean-context architecture assessment of the smallest recovery mechanism. Record the concrete production plan and exact semantic tradeoff, then review before changing runtime or storage. Reuse the existing scheduler, durable generations and hook protocol.
**Verification plan:** Old uncertain wake plus later message must recover without manual turns -> failing then passing caller-surface regression. Concurrent recovery, active claims, receipt races, restarts and late native wakes -> existing fixture-based boundary coverage plus focused new cases. Run affected files, test-plan selector and required suite once after coherent implementation. Live checks only in dedicated test sessions after reviewed install.
**Plan review:** Pending architecture assessment; production implementation is not approved by an agent review yet. Isolated reproduction does not change production behavior.
**Approvals:** User 2026-10-06: "so? how are we fixing this? can you reproduce this and then see that we can fix this?" Research and isolated reproduction authorized. Concrete native retry tradeoff remains to be assessed, not inferred as approved.
**State:** Blocked
<!-- agent-workflow:end -->

## Implementation
2026-10-06: Applicability is normal workflow because runtime/storage changes are intended; no documentation-only exemption. Production edits await a concrete reviewed recovery design. Read-only architecture assessment and isolated failing reproduction proceed.

## Evidence
Incident message relay-msg-8bb5cb4dd7cd404e9c1092eaf386503f. Prior anchor delivery relay-delivery-f432aa391eea49d8925f0bbbb70fe356, uncertain reservation generation 318, no claim, durable expiry. Manual recovery resolved the incident but is not the product fix.

## Roadmap
Owning item: roadmap/features/add-wake-first-relay-delivery.md. Root owns shared roadmap; do not modify unrelated work.
