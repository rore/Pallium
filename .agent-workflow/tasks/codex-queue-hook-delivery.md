<!-- agent-workflow:start -->
**Outcome:** Relay wakes an exact loaded Codex Desktop task through native cross-process queue dispatch, and every queued Relay payload is model-visible before its delivery can be acknowledged.

**Target:** Codex wake adapter, internal router wiring, receipt-based MCP acknowledgement/reply context, installed wake profile, focused E2E/regression coverage, and Relay wake roadmap evidence.

**Scope:** Reuse the existing Relay claim lease before wake; pass the existing Relay service and send scope into the internal wake callback; render claimed attributed deliveries, trusted container/actor scope, and receipts directly in the Codex wake prompt; use `exec resume` when no writer owns the task and fall back to hidden `codex queue` only for the exact active-writer conflict; enable the ACK tool in the narrow wake profile. Add an internal `register_session=False` turn option so wake claiming cannot create/reopen a recipient. No database schema, public Relay HTTP contract, other-runtime wake adapter, payload-limit, or orchestration changes.

**Constraints:** Persist before launch; callback/worker failure never changes the successful send response; a failed/ambiguous launch never ACKs and the lease must expire into natural-turn fallback; no shell or visible window; queue only on the exact active-writer status and error; preserve lower-authority attribution, exact recipient validation, bounded batches, multiple-message delivery, Unicode, and existing natural-turn hook delivery.

**Completion criteria:** A loaded idle Desktop task is externally queued and runs the exact attributed Relay batch; an unloaded task still wakes through `exec resume`; busy loaded work queues for its next turn; each visible message is ACKed/replied with its receipt; launch failure, missing tool call, crash, expiry, and restart leave the delivery recoverable; unrelated/newer pending deliveries are not prematurely ACKed; duplicate callbacks do not duplicate a wake; no visible command window; all caller-surface E2E and focused regressions pass.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Redline classifies `app/codex_wake.py` as watch/gray and the change affects process launch plus Relay lease timing. The design reuses the existing claim/receipt contract and avoids API/storage-schema changes, keeping one coherent adapter slice.

**Discovery:** Live Codex 0.149.1 evidence after restart proved `codex queue --thread` wakes an already-loaded Desktop-owned task: queue item `01a05d3a-8304-71d1-95b1-224f3d0d1d12` produced a completed model turn in about nine seconds. The same run proved the current hook path is unsafe for queue dispatch: delivery `relay-delivery-af244228a60146b2b5f4a2c85db176ab` was claimed and ACKed, but hook `additionalContext` was not model-visible; the queued static prompt produced `Pallium Relay wake failed: no delivery was injected.` Official OpenAI App Server docs confirm `turn/start` begins generation and exposes completion, while the attached source research identifies the cross-process queue watcher added in current Codex.

**Material assumptions:** The existing `RelayService.turn` claim lease can safely reserve the target backlog before launch without reopening the session; disproved by a claim/close race or inability to recover after launch failure, which stops implementation. A queue/exec prompt is model-visible even when hook additional context is not; disproved by a unique direct-payload live marker failing to appear, which blocks the adapter. Receipt possession plus exact container/actor scope is sufficient for ACK/reply; disproved by a wrong-scope acceptance test, which requires restoring stronger binding before merge. A model-visible task can ACK within the 60-second lease; a slower/missing ACK intentionally degrades to at-least-once natural-turn redelivery rather than loss.

**Plan:** Claim a bounded target-session batch through the already-built Relay service immediately before launch, with registration disabled so a closed/missing session yields no wake. Construct one attributed prompt containing trusted container/actor scope, each delivery ID, receipt, metadata, payload, an immediate ACK instruction, and optional later reply using the same receipt. Run hidden `exec resume`; only its exact active-writer status and error may run hidden `codex queue` with the same prompt. Let unsuccessful, slow, or unacknowledged attempts age out through the existing lease as deliberate at-least-once fallback. Keep callback and worker failures isolated from the persisted send response, and add ACK to the generated wake profile. Cover loaded/unloaded/busy/failure/batch/Unicode/cross-scope/idempotence/fallback behavior through the same HTTP/MCP/hook/CLI surfaces, run a live no-ping Codex↔Codex acceptance, then align the roadmap.

**Verification plan:** Unit tests assert exact active-writer-only queue fallback, hidden vector argv, executable resolution, batch rendering bounds, and callback dedupe; service/API tests assert send → claim-before-launch and lease recovery; MCP tests assert valid receipt ACK/reply without thread inference and reject wrong scope/receipt; hook tests assert claimed wake items are not re-claimed while ordinary natural-turn delivery remains unchanged; live E2E on the installed service asserts loaded queue wake, unloaded resume, multi-message visibility, reply/ACK, and failure fallback; run workflow/redline, full focused suites, service health, PR CI, and review-thread resolution.

**Plan review:** Clean-context review `/root/queue_wake_plan_review` approved the claim-lease/direct-payload/strict-queue design after requiring trusted scope propagation, callback-failure isolation, no session reactivation during wake claim, explicit 60-second at-least-once lease behavior, and exact active-writer matching. All five requirements are incorporated above.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-09-01: Established live root cause and selected the existing claim-lease/receipt contract to avoid a new public API or persistence schema.
- 2026-09-01: Clean-context plan review incorporated scope, callback isolation, closed-session, lease-duration, and strict active-writer requirements before code edits.
