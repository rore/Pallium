# Recover Codex Relay wake claims lost after hook timeouts

<!-- agent-workflow:start -->
**Outcome:** A Codex wake whose `/relay/turn` response is lost after the claim commits is automatically retried after the claim lease expires, without a user prompt and without retrying a merely queued native write.

**Target:** Pallium Relay Codex wake recovery.

**Scope:** `integrations/codex/hooks/common.py`, `integrations/codex/hooks/user_prompt_submit.py`, `api/schemas.py`, `api/routes.py`, `core/codex_wake.py`, `app/codex_wake.py`, `app/dependencies.py`, `storage/sqlite_relay.py`, focused Relay hook/Codex wake/Claude callback tests, `docs/agent-relay.md`, this Work Record, and the existing Relay incident ledger in `roadmap/features/fix-relay-claim-before-context-emission.md`.

**Constraints:** Preserve Relay delivery states, claim leases, native Codex queue semantics, ordinary-turn behavior, backward compatibility for callers that omit wake correlation, and active/pending wake fences. Never infer consumption from timeout, elapsed time, or claim count alone. Retry only after the exact current internal wake request claimed its own persisted delivery, the post-claim callback durably correlated it, and that claim lease later expired. A service crash or callback failure between DB claim commit and registry persistence remains conservatively fenced.

**Completion criteria:** When an exact Codex internal wake times out after `/relay/turn` commits its delivery claim, the post-claim callback shall durably correlate that exact wake fence, and the existing periodic recovery sweep shall requeue the same durable delivery exactly once after lease expiry. A later internal wake shall inject and ACK it. Normal-turn claims, active claims, never-claimed queued wakes, overtaken wakes, endpoint/delivery mismatches, malformed reads, legacy uncorrelated fences, and newer generations shall not release or duplicate a wake; expired messages may release their terminal fence but shall never be requeued.

**Risk:** High

**Complexity:** Moderate

**Reason:** `api/schemas.py` and `api/routes.py` are Redline API-contract red zones, so the backward-compatible optional request correlation field requires High risk and API review. Hook/runtime/storage files are gray watch surfaces; tests, roadmap, and Work Record are blue. The change remains one bounded lifecycle fix with meaningful concurrency and crash/restart cases.

**Discovery:** Live trace `relay-delivery-e55ba5f62a1f4c9cad5c4ad7e10537dc` shows a native Codex wake accepted at 22:27:06Z, `/relay/turn` claim committed at 22:27:09.435Z, the server completed in 1.329s, and the 0.75s hook client timed out before receiving/rendering the response. The hook blocked the internal wake, the lease expired, and the accepted wake reservation prevented periodic recovery. Three clean-context probes ruled out weaker fixes: stored/effective state repeats across replacement generations; legacy baselines are unknowable; and claim counts cannot distinguish a normal turn from the queued internal wake. The exact delivery ID already exists in the native wake prompt, while the route already invokes a post-claim callback in the service process. Correlating those two existing boundaries is the smallest deterministic recovery witness.

**Material assumptions:** An optional validated `wake_delivery_id` on `/relay/turn`, supplied only by an exact internal Codex wake and excluded from the core Relay call, lets the existing post-claim callback mark only a matching current reservation when the successful result actually contains that delivery; disproved by a caller-surface test that marks a normal/overtaken/mismatched claim, which returns the task to planning. Persisting the matched claim attempt on the reservation makes recovery survive response loss and service restart; legacy version-1 reservations remain uncorrelated/fenced, avoiding migration guesses. The existing 30-second recovery loop remains active in the installed service; disproved by service/runtime inspection, which would require wiring rather than reconciliation changes.

**Plan:** Parse the exact delivery ID already validated by the Codex internal-wake regex and pass it as an optional `wake_delivery_id` in the final `/relay/turn` request. Add that backward-compatible request field with strict delivery-ID validation; strip it before calling `RelayService.turn`, then pass both validated request and successful result to the existing admission callback. In the Codex callback, mark the exact current reservation only when the result contains the same claimed delivery and endpoint, persisting its attempt number in a version-2 registry while loading version-1 reservations as uncorrelated. Reconciliation releases that generation only when the exact delivery is effectively pending, stored claimed, and its attempt equals the correlated attempt; the normal generation-CAS release and periodic candidate dispatch remain unchanged. Add request validation, hook payload, callback race, migration/restart, repeated/concurrent sweep, normal-turn/overtaken-wake, expiry, and full hook claim-timeout → recovery → injection/ACK lifecycle coverage. Drain the known legacy installed fence with one explicit normal recipient turn after deployment, then run a fresh automatic-wake witness. Record RF-009 in the existing ledger only after verification. Stop if exact correlation requires a DB schema, claim-token exposure, or a new coordinator.

**Verification plan:** Exact hook correlation and request validation → focused `tests/test_agent_relay_hooks.py` and `tests/test_codex_wake.py`. Timeout-after-commit recovery, negative interleavings, restart, repeated/concurrent sweeps, and injection/ACK → caller-surface lifecycle cases in `tests/test_codex_wake.py`. Repository contract and API-risk gates → local agent-workflow/Redline checks, focused subsystem tests, `python -m pytest tests/ -x -q` once before review, smart result review, API checkpoint review, and PR CI.

**Plan review:** Clean-context High-risk review approved the exact request/result correlation plan with the documented crash-window and public-contract clarifications below. See `## Plan review`.

**Approvals:** Approved by user 2026-09-15: "you're about to get assigned work from the architect agent, i approve this work and doing PRs"

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

No production edit has started. Intended production files are the two Codex hook files, the Relay turn request/route, the Codex wake registry/adapter/dependency callback, and the payload-free wake-state projection; focused tests, the public Relay lifecycle paragraph, and the existing incident ledger complete the bounded slice.

## Plan review

Three clean-context reviews rejected stored/effective state alone, a synthetic legacy baseline, and an uncorrelated attempt baseline. A fresh clean-context High-risk review approved using the exact delivery ID already carried by the internal wake prompt and the existing post-claim callback to persist a deterministic claim-to-wake witness. It required strict Codex-only validation, exact result/endpoint/session/attempt matching, lock-preserving concurrent mutation, stored-claimed/effective-pending/exact-attempt recovery, callback compatibility coverage, and the real registry/native-call lifecycle regression. It also bounded the crash window: DB claim commit and registry persistence are separate writes, so a crash or callback failure between them stays fenced; restart recovery applies after correlation persists. `docs/agent-relay.md` must record the verified exception to ACK/reply-only release and this limitation. Verdict: APPROVE; classification API_CHANGE, High/Moderate, api-review required.