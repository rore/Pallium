# Controlled unloaded Relay payload trial

Owner: minimap_wake_diagnosis. Branch: `feat/codex-unloaded-payload-trial`. Canonical roadmap: `roadmap/features/add-wake-first-relay-delivery.md`; root owns roadmap and live execution.

<!-- agent-workflow:start -->
**Outcome:** One exclusively owned idle disposable Codex recipient can be given one service-owned Desktop action over a retained connection, and an already-pending Relay payload is observed in its genuine turn with hook ACK, without retrying an ambiguous action.

**Target:** Pallium's optional Codex Desktop service custody and Relay delivery witness.

**Scope:** Plan and later implement one separately armed finite operator action using the existing service RAM Desktop connection: `app/codex_bridge_pipe.py`, minimal `app/main.py` read-only Relay wiring if needed, matching private-pipe/caller tests, and `docs/designs/codex-mcp-desktop-bridge.md`. This plan-only checkpoint changes this Work Record; no production or protected contract edits yet.

**Constraints:** Exact exclusive idle disposable only, one recipient and one stable delivery/logical action, at most one native owner call after a durable pre-call fence. No automatic dispatcher path, native queue resubmission, claim/ACK in the service, payload over Desktop, model/settings/effort override, retry or rearm after uncertainty, invented zero-child/restart/busy-turn guarantee, normal policy broadening, live operation, or purge. Preserve current inventory-only admission and native reservation fences. Root owns operator arming, rollout, and roadmap.

**Completion criteria:** Without fresh exact finite action authority, qualifying inventory and endpoint possession produce zero owner calls. With one exact eligible pending delivery, verified custody, positive inventory lifetime proof, and exclusive operator ownership, one durable fence is committed before at most one fixed Desktop owner request; same action on any epoch/revision/restart has no second call. Drift, expired/moved/claimed/ACKed delivery, malformed response, timeout, crash, and concurrent requests fail closed, retaining an uncertain fence as needed. The live trial counts only genuine unloaded-to-turn observation plus exact hook payload emission and ACK/trace readback as success, never request acceptance alone.

**Requirement baseline:**
{"source":"root assignment and direct overnight user authorization, 2026-09-30","outcome":"One exclusively owned idle disposable Codex recipient can be given one service-owned Desktop action over a retained connection, and an already-pending Relay payload is observed in its genuine turn with hook ACK, without retrying an ambiguous action.","scope":"Plan and later implement one separately armed finite operator action using the existing service RAM Desktop connection: `app/codex_bridge_pipe.py`, minimal `app/main.py` read-only Relay wiring if needed, matching private-pipe/caller tests, and `docs/designs/codex-mcp-desktop-bridge.md`. This plan-only checkpoint changes this Work Record; no production or protected contract edits yet.","constraints":"Exact exclusive idle disposable only, one recipient and one stable delivery/logical action, at most one native owner call after a durable pre-call fence. No automatic dispatcher path, native queue resubmission, claim/ACK in the service, payload over Desktop, model/settings/effort override, retry or rearm after uncertainty, invented zero-child/restart/busy-turn guarantee, normal policy broadening, live operation, or purge. Preserve current inventory-only admission and native reservation fences. Root owns operator arming, rollout, and roadmap.","completion_criteria":"Without fresh exact finite action authority, qualifying inventory and endpoint possession produce zero owner calls. With one exact eligible pending delivery, verified custody, positive inventory lifetime proof, and exclusive operator ownership, one durable fence is committed before at most one fixed Desktop owner request; same action on any epoch/revision/restart has no second call. Drift, expired/moved/claimed/ACKed delivery, malformed response, timeout, crash, and concurrent requests fail closed, retaining an uncertain fence as needed. The live trial counts only genuine unloaded-to-turn observation plus exact hook payload emission and ACK/trace readback as success, never request acceptance alone."}

**Risk:** High

**Complexity:** Moderate

**Reason:** Service-held Desktop capability plus new mutating native request is security/behavior sensitive. Durable fence and Relay state across several components require meaningful review; the intended `app/*` path is watched and the service-facing contract is not routine.

**Discovery:** Current `InventoryService._observe` in `app/codex_bridge_pipe.py` sends only fixed `tools/list`; its private policy action is exactly `desktop-inventory-only`. `app/main.py` owns the RAM instance and separately builds RelayService/SQLite-backed native wake registry. `core/relay.py` exposes exact pending-candidate and reservation-state reads; `storage/sqlite_relay.py` returns endpoint/state/generation/wake target without claim. `app/codex_wake.py` already preserves accepted/uncertain native queue reservations and sends a delivery-ID-only prompt. The installed Codex hook emits `payload_emitted` and `delivery_acked` after actual claim/injection/ACK. Existing design requires an owner-action fence separate from native queue reservation and warns that scope generation and wake generation are different domains. Private inventory operator plan authorizes no owner call and cannot simply be reused as action authority.

**Material assumptions:** A qualified same-process RAM connection still exists with a positively observed source exit and current peer/policy identity; otherwise no experiment action. A delivery remains exactly pending for the same endpoint, scope, and immutable native wake reservation generation at the pre-call check; absent/mismatched evidence aborts. The operator exclusively owns an idle disposable and sends no concurrent message; this narrows the finite witness but cannot prove production busy-turn safety or prevent all external races. A protected create-once action fence can be retained across service restarts and operator gate cleanup; if exact persistence/retention cannot be demonstrated, stop before any owner call and review a SQLite-backed fence instead. Current Desktop owner-call request schema must be proven from the exact installed source and an actual fake-pipe decoded request before implementation; a changed/unknown schema aborts. The returned owner acceptance cannot prove unloaded delivery.

**Plan:** Keep shipped inventory authority and protocol unchanged. After historical before/positive-exit/after proof and an independently armed finite action policy, accept only one operator-created private action ticket for the exact disposable endpoint, session/container scope, stable delivery and immutable action identity. The service loop reads that ticket under existing protected path/owner/epoch/revision checks; no normal Relay send or model tool triggers it. Resolve the current Relay endpoint and exact pending candidate and native reservation state through read-only service wiring; reject a moved, expired, claimed, terminal or unresolved target. Compare each generation only within its own domain. Atomically publish a bounded protected create-once fence keyed by the stable logical action before Desktop write, and retain it through error, timeout, crash, restart, revision change and ordinary gate cleanup. Recheck finite authority, Desktop peer/pipe identity, exact target, and fence before one version-pinned `tools/call` on the existing RAM connection, carrying only the delivery-ID wake instruction. Unknown outcome is spent/uncertain; no second call, native queue retry, or service-side claim/ACK. The operator observes genuine turn and hook/Relay readback, then revokes action authority and closes custody without deleting an unresolved fence. No automatic action for ordinary recipients. If protected create-once persistence cannot meet the cross-restart identity/retention check, return to plan review for a minimal SQLite fence instead of sending.

**Verification plan:** Missing/revoked/expired/wrong-process action ticket plus valid inventory -> actual private-pipe caller test shows zero Desktop calls and no secret output. Exact pending endpoint/scope/generation versus moved/expired/claimed/terminal/unresolved state -> service caller E2E with SQLite readback and zero call on mismatch. Concurrent same-action requests, simulated crash after fence, timeout after write, service epoch/revision change and restart -> durable fence readback and at most one decoded native call; no marker cleanup permits a second attempt. Current installed owner-call schema and malformed/extra/error response -> fake Desktop byte-stream caller test with one fixed request, no payload/settings fields, fail-closed public outcome. Valid before/exit/after custody -> one action on the same connection; wrong peer or incomplete phase -> zero action. Genuine target turn -> hook `payload_emitted`, exact `delivery_acked`, attempt/trace and message readback; inventory or owner-call acceptance alone fails the acceptance check. Later code slice runs focused caller tests, affected subsystem, selector-required full once, independent result/security review and CI; no application tests in this plan-only checkpoint.

**Plan review:** Pending independent clean-context security review of this exact plan. No implementation until accepted. Root owns final scope acceptance and live arming.

**Approvals:** Approved by user 2026-09-29: "this is a night job so you have my approval to complete it". Root's 2026-09-30 assignment expressly applies that authorization to preparing this finite plan; independent security review remains required before code.

**Exceptions:** None

**State:** Blocked
<!-- agent-workflow:end -->

## Checkpoint: security-review

What is changing: A separately armed finite operator action could send one fixed Desktop request over existing service custody after durable fencing.
Why: Inventory lifetime alone cannot demonstrate a genuine unloaded Relay payload turn.
Affected contract: Native capability custody, exact recipient scope, durable duplicate suppression, and private operator authority.
Compatibility risk: High; the action is opt-in and experiment-scoped, but a wrong recipient or repeated native call could create an unintended turn.
Verification: Private-pipe and SQLite-backed caller E2E, crash/ambiguity/restart tests, exact decoded wire assertion, hook ACK readback, and independent security/result review.

## Implementation

Plan-only: classified before any production edits. Managed checkout starts at `e0e381789fa79b22c9883e9999ed27c9994d0ca3`; branch `feat/codex-unloaded-payload-trial`. The source pass found no existing service owner-action API or durable action fence. The inventory proof and native wake reservation do not themselves grant action authority. Reviewer must resolve the fence retention and exact current Desktop request shape before TDD production work.

## Evidence

Code references: `app/codex_bridge_pipe.py` policy parse and `InventoryService._observe/_run`; `app/main.py` service lifespan; `core/relay.py` pending/reservation reads; `storage/sqlite_relay.py` exact pending state; `app/codex_wake.py` native reservation and delivery-ID prompt; `integrations/codex/hooks/user_prompt_submit.py` emission/ACK; `docs/designs/codex-mcp-desktop-bridge.md` owner-fence limits. No live action or test run in this planning checkpoint.

## Result review

Pending implementation; no result claim.
