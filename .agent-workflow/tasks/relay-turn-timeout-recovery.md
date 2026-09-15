# Recover Codex Relay wake claims lost after hook timeouts

<!-- agent-workflow:start -->
**Outcome:** A Codex wake whose `/relay/turn` response is lost after the claim commits is automatically retried after the claim lease expires, without a user prompt and without retrying a merely queued native write.

**Target:** Pallium Relay Codex wake recovery.

**Scope:** `integrations/codex/hooks/common.py`, `integrations/codex/hooks/user_prompt_submit.py`, `api/schemas.py`, `api/routes.py`, `core/codex_wake.py`, `core/relay.py`, `app/codex_wake.py`, `app/dependencies.py`, `storage/sqlite_relay.py`, focused Relay hook/Codex wake/Claude callback tests, `docs/agent-relay.md`, this Work Record, and the existing Relay incident ledger in `roadmap/features/fix-relay-claim-before-context-emission.md`.

**Constraints:** Preserve Relay delivery states, claim leases, native Codex queue semantics, ordinary-turn behavior, backward compatibility for callers that omit wake correlation, and active/pending wake fences. Never infer consumption from timeout, elapsed time, or claim count alone. Retry only after the exact current internal wake request claimed its own persisted delivery, the post-claim callback durably correlated it, and that claim lease later expired. A service crash or callback failure between DB claim commit and registry persistence remains conservatively fenced.

**Completion criteria:** When an exact Codex internal wake times out after `/relay/turn` commits its delivery claim, the post-claim callback shall durably correlate that exact wake fence, and recovery shall atomically replace that exact fence generation and queue the same durable delivery exactly once after lease expiry. A later internal wake shall inject and ACK it. Normal-turn claims, active claims, never-claimed queued wakes, overtaken wakes, endpoint/delivery mismatches, malformed reads, legacy uncorrelated fences, and newer generations shall not release or duplicate a wake; expired messages may release their terminal fence but shall never be requeued.

**Risk:** High

**Complexity:** Moderate

**Reason:** `api/schemas.py` and `api/routes.py` are Redline API-contract red zones, so the backward-compatible optional request correlation field requires High risk and API review. Hook/runtime/storage files are gray watch surfaces; tests, roadmap, and Work Record are blue. The change remains one bounded lifecycle fix with meaningful concurrency and crash/restart cases.

**Discovery:** Live trace `relay-delivery-e55ba5f62a1f4c9cad5c4ad7e10537dc` shows a native Codex wake accepted at 22:27:06Z, `/relay/turn` claim committed at 22:27:09.435Z, the server completed in 1.329s, and the 0.75s hook client timed out before receiving/rendering the response. The hook blocked the internal wake, the lease expired, and the accepted wake reservation prevented periodic recovery. Three clean-context probes ruled out weaker fixes: stored/effective state repeats across replacement generations; legacy baselines are unknowable; and claim counts cannot distinguish a normal turn from the queued internal wake. The exact delivery ID already exists in the native wake prompt, while the route already invokes a post-claim callback in the service process. Correlating those two existing boundaries is the smallest deterministic recovery witness.

**Material assumptions:** An optional validated `wake_delivery_id` on `/relay/turn`, supplied only by an exact internal Codex wake and excluded from the core Relay call, lets the existing post-claim callback mark only a matching current reservation when the successful result actually contains that delivery; disproved by a caller-surface test that marks a normal/overtaken/mismatched claim, which returns the task to planning. Persisting the matched claim attempt on the reservation makes recovery survive response loss and service restart; legacy version-1 reservations remain uncorrelated/fenced, avoiding migration guesses. The existing 30-second recovery loop remains active in the installed service; disproved by service/runtime inspection, which would require wiring rather than reconciliation changes.

**Plan:** Parse the exact delivery ID already validated by the Codex internal-wake regex and pass it as an optional `wake_delivery_id` in the final `/relay/turn` request. Add that backward-compatible request field with strict delivery-ID validation; strip it before calling `RelayService.turn`, then pass both validated request and successful result to the existing admission callback. In the Codex callback, mark the exact current reservation only when the result contains the same claimed delivery and endpoint, persisting its attempt number in a version-2 registry while loading version-1 reservations as uncorrelated. Reconciliation acts only when the exact delivery is effectively pending, stored claimed, and its attempt equals the correlated attempt; it holds the same immediate database write boundary as Relay claims while atomically replacing the current fence generation and scheduling one retry. Add request validation, hook payload, callback race, migration/restart, repeated/concurrent sweep, normal-turn/overtaken-wake, expiry, and full hook claim-timeout → recovery → injection/ACK lifecycle coverage. Drain the known legacy installed fence with one explicit normal recipient turn after deployment, then run a fresh automatic-wake witness. Record RF-009 in the existing ledger only after verification. Stop if exact correlation requires a DB schema, claim-token exposure, or a new coordinator.

**Verification plan:** Exact hook correlation and request validation → focused `tests/test_agent_relay_hooks.py` and `tests/test_codex_wake.py`. Timeout-after-commit recovery, negative interleavings, restart, repeated/concurrent sweeps, and injection/ACK → caller-surface lifecycle cases in `tests/test_codex_wake.py`. Repository contract and API-risk gates → local agent-workflow/Redline checks, focused subsystem tests, `python -m pytest tests/ -x -q` once before review, smart result review, API checkpoint review, and PR CI.

**Plan review:** Clean-context High-risk review approved the exact request/result correlation plan with the documented crash-window and public-contract clarifications below. See `## Plan review`.

**Approvals:** Approved by user 2026-09-15: "you're about to get assigned work from the architect agent, i approve this work and doing PRs"

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

The delivery-specific Codex wake hook now copies its already-validated delivery ID into an optional, Codex-only `/relay/turn` field. The route strips that field before the core Relay call and gives the successful request/result pair to the existing callback. The callback persists the exact matching claimed attempt on the current wake reservation. Registry version 2 retains that correlation across restart while version 1 loads as uncorrelated. For an expired correlated claim, reconciliation holds the same SQLite immediate-write boundary as Relay claims, verifies the recipient remains active, derives its current session/container scope, atomically swaps the current registry fence for a fresh uncorrelated generation, clears old-scope scheduling keys, and queues one replacement before ordinary claims resume. Terminal cleanup still uses generation-safe release; ACK/reply behavior is unchanged.

The smart result review reproduced a time-of-check/time-of-use race in the initial release-then-dispatch implementation: an ordinary turn could reclaim the delivery between the state read and fence release, leaving its active claim unfenced. It then found that direct replacement bypassed active-recipient/current-scope eligibility and that a moved scope retained old scheduling keys. The final shared storage boundary, current-target projection, generation replacement, explicit old-key cleanup, and regressions close all three findings without adding a coordinator or schema.

The public Relay lifecycle documentation records the narrow lease-expiry exception and the separate-commit crash window. RF-009 records the observed incident without claiming model-visible admission. A cheap delegated worker made the mechanical callback/test-contract updates; those edits were reviewed before acceptance. `apply_patch` failed once with the documented Windows process error, so all later edits used exact, asserted, file-scoped replacements as the repository's machine-local instructions require.

## Evidence

- Final focused reclaim-race, current-recipient lifecycle, scheduling-key, and real-hook recovery nodes: `5 passed in 2.63s`.
- Affected Relay hook/Codex wake/Claude callback/storage subsystem before the final one-line scheduling-key cleanup: `204 passed, 2 skipped in 57.48s`; the cleanup is covered by the final focused run and the required final repository suite below.
- Final required post-review repository suite: `5016 passed, 34 skipped, 2 xfailed in 222.30s`.
- `py_compile` for all changed Python modules/tests and `git diff --check`: passed.
- Import-linter boundary report: zero violations. Agent-workflow: every blocking predicate passed; the smart API review approved and PR #198 carries `api-reviewed` for the shadow checkpoint.
- The caller-surface lifecycle uses the real HTTP route, real persisted reservation file, actual hook, simulated client-side response loss after server commit, registry restart, 61-second lease advance, native-call counter, recovery turn, context injection, ACK readback, and a final no-third-wake assertion.

## API review

Change shape: additive. `/relay/turn` gains one optional `wake_delivery_id` request field, so existing clients remain unchanged. Validation accepts only canonical lowercase Relay delivery IDs and only for runtime `codex`; the route removes it before invoking the core Relay service. The in-repo Codex hook is the only producer, Claude compatibility is covered, and the OpenAPI model contains the additive field. No deprecation or migration period is required. The trusted-local field is correlation evidence, not authentication or proof of model visibility.

## Skill feedback (unsent)

**Affected surface:** `templates/checkpoints/plan-and-review.md` in the vendored agent-workflow skill.

**Expected:** A clean-context reviewer can read the required Work Record, relevant sources, and canonical SPEC.

**Actual:** The checkpoint requires `SPEC`, and templates/checker cite `SPEC.md`, but the installed skill package contains no `docs/SPEC.md` or `SPEC.md`.

**Minimal reproduction:** Install the skill package, follow the Elevated/High plan-review checkpoint, then list/search the package for the referenced specification.

**Evidence:** The plan-review checkpoint names `SPEC`; `rg -i 'spec.md|specification'` finds references, while both expected specification paths are absent.

**Suggested owner:** Package the canonical specification in the skill manifest or change the checkpoint to an available reference. Kept unsent because this task has no explicit authority for a public upstream defect report. Trigger 3 for the local `apply_patch` failure was dropped because the cause is machine/runtime-owned, not agent-workflow.

## Plan review

Three clean-context reviews rejected stored/effective state alone, a synthetic legacy baseline, and an uncorrelated attempt baseline. A fresh clean-context High-risk review approved using the exact delivery ID already carried by the internal wake prompt and the existing post-claim callback to persist a deterministic claim-to-wake witness. It required strict Codex-only validation, exact result/endpoint/session/attempt matching, lock-preserving concurrent mutation, stored-claimed/effective-pending/exact-attempt recovery, callback compatibility coverage, and the real registry/native-call lifecycle regression. It also bounded the crash window: DB claim commit and registry persistence are separate writes, so a crash or callback failure between them stays fenced; restart recovery applies after correlation persists. `docs/agent-relay.md` must record the verified exception to ACK/reply-only release and this limitation. Verdict: APPROVE; classification API_CHANGE, High/Moderate, api-review required.
## Result review

A clean-context smart reviewer reproduced and verified fixes for three interleavings: ordinary reclaim between state read and fence release, retry of a closed/unreachable or scope-moved recipient without current eligibility, and stale old-scope scheduling keys after replacement. Final review found no remaining actionable issue. API verdict: APPROVE; the optional Codex-only field is additive and backward-compatible, version-1 migration and the separate-commit crash window remain fail-closed, and classification remains API_CHANGE, High/Moderate. User approval supplies the human checkpoint; PR CI and installed-service smoke remain the release gates.
