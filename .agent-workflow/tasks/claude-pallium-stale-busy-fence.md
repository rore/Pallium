# Stop late Claude turn admission from overwriting a newer idle registration

<!-- agent-workflow:start -->
**Outcome:**
A Claude Stop hook whose Relay turn outlives its client timeout no longer leaves its session busy and wake-ineligible. A Stop with a confirmed idle registration marks its turn so the server skips the post-turn busy stamp, and confirms busy itself before emitting delivered work. Every other Claude turn keeps the existing fail-closed busy stamp.

**Target:**
Pallium service process (`/relay/turn` schema, route and Claude admission wiring) and the Claude Code Stop hook.

**Scope:**
`api/schemas.py` (`RelayTurnRequest.claude_turn_admission`); `api/routes.py` (keep the field out of the storage turn call); `app/dependencies.py` (`_relay_turn_admission` skips `mark_busy` for a flagged turn); `integrations/claude-code/hooks/common.py` (`relay_turn` keyword sent on every turn POST of the call); `integrations/claude-code/hooks/stop.py` (confirmed-idle gate and busy-before-emit); tests in `tests/test_claude_wake_dispatch.py` and `tests/test_agent_relay_hooks.py`; this Work Record.

**Constraints:**
The flag is an additive, optional, Claude-only HTTP request field on non-exact `/relay/turn`; the server rejects it for other runtimes and other values, and Claude cannot send exact claims. It changes only whether admission calls `mark_busy`. Claim, ACK, lease, reservation, routing, remap, native wake reservations and unflagged clients are unchanged. SessionStart and UserPromptSubmit are unchanged. Codex and Hermes paths are unchanged. If busy cannot be confirmed or output fails, the Stop does not ACK and custody stays with the existing lease. No live restart, fault injection, dependency, settings or environment change.

**Completion criteria:**
1. Through the real `/relay/turn` and `/internal/claude-wake/register` routes built by `build_router`, a flagged Claude turn held in storage while a newer idle registration lands leaves `attempt()` accepted.
2. An unflagged Claude turn still marks the session busy; a flagged one leaves it idle.
3. The flag is rejected (422) for other runtimes and for values other than `"none"`; old-shape bodies are unchanged.
4. The actual Stop hook sends the flag only after a confirmed initial idle registration; without it, the turn is unflagged and legacy emit and ACK are unchanged.
5. A flagged Stop with rendered work registers busy, then emits, then ACKs and exits 2.
6. A flagged Stop whose busy registration is not confirmed does not emit, ACK or exit 2, and attempts the final idle registration.
7. Existing Stop, wake, durability, exact-claim and codex tests pass, with only expected-registration assertions updated for the new busy step.

**Requirement baseline:**
{"source": "work-record-initial", "outcome": "A Claude Relay turn whose post-turn admission runs after a newer Claude wake registration for the same session no longer overwrites that registration with busy. An idle Claude session therefore stays wake-eligible when its Stop hook's turn request outlives the hook's client timeout. A turn admitted with no intervening registration still marks the session busy.", "scope": "`core/claude_wake.py` (`generation_for`, `mark_busy` expected generation); `api/routes.py` (non-exact `/relay/turn` pre-turn Claude generation capture passed to the admission callback); `app/dependencies.py` (`_claude_turn_generation`, `_relay_turn_admission` fence); tests in `tests/test_claude_wake_dispatch.py`; this Work Record.", "constraints": "No change to the codex exact path or its pre-turn snapshot callback contract, Relay lease, claim, receipt or ACK semantics, wake dispatch, registration intents, durability or hooks. Without a generation observation, admission keeps the existing fail-closed busy. `wake_inflight` is never downgraded. No live restart, fault injection, dependency or settings change.", "completion_criteria": "1. Through the real `/relay/turn` and `/internal/claude-wake/register` HTTP routes built by `build_router`, a Claude turn held after its pre-turn observation while a newer idle registration lands leaves the session wake-eligible: `attempt()` is accepted.\n2. Through the same routes, a Claude turn admitted with no intervening registration still marks that exact session busy, so `attempt()` is `not_eligible`.\n3. Turns for another container or another session do not change the registration.\n4. A current-generation turn does not downgrade a `wake_inflight` reservation.\n5. Codex exact-turn snapshot behavior is unchanged."}

**Behavior changes:**
[{"target": "task-context.outcome", "classification": "requirement-change", "before": "A Claude Relay turn whose post-turn admission runs after a newer Claude wake registration for the same session no longer overwrites that registration with busy. An idle Claude session therefore stays wake-eligible when its Stop hook's turn request outlives the hook's client timeout. A turn admitted with no intervening registration still marks the session busy.", "after": "A Claude Stop hook whose Relay turn outlives its client timeout no longer leaves its session busy and wake-ineligible. A Stop with a confirmed idle registration marks its turn so the server skips the post-turn busy stamp, and confirms busy itself before emitting delivered work. Every other Claude turn keeps the existing fail-closed busy stamp.", "reason": "Independent review rejected the server-side generation fence (candidate 8404f922): no server observation after request arrival can order the hook's separate registration and turn requests. The hook-gated opt-out replaces it.", "impact": "Claude Stop turns with a confirmed idle registration no longer receive the late busy stamp; the Stop confirms busy before emitting. Unflagged clients are unchanged.", "alternatives": "Server-side generation fence (rejected in review); emitting after a failed busy registration (rejected in review).", "authority": {"scope": "task", "name": "task-owner"}, "approval": {"by": "user", "reference": "Owner approval relayed by @pallium-manager (Relay message claude-stop-hook-plan-owner-approval-20261124, remote source: Telegram). Scope: implementation and testing only of the refined conditional Claude Stop-hook plan, including lease recovery when busy cannot be confirmed.", "verbatim": "I approve"}}, {"target": "task-context.scope", "classification": "requirement-change", "before": "`core/claude_wake.py` (`generation_for`, `mark_busy` expected generation); `api/routes.py` (non-exact `/relay/turn` pre-turn Claude generation capture passed to the admission callback); `app/dependencies.py` (`_claude_turn_generation`, `_relay_turn_admission` fence); tests in `tests/test_claude_wake_dispatch.py`; this Work Record.", "after": "`api/schemas.py` (`RelayTurnRequest.claude_turn_admission`); `api/routes.py` (keep the field out of the storage turn call); `app/dependencies.py` (`_relay_turn_admission` skips `mark_busy` for a flagged turn); `integrations/claude-code/hooks/common.py` (`relay_turn` keyword sent on every turn POST of the call); `integrations/claude-code/hooks/stop.py` (confirmed-idle gate and busy-before-emit); tests in `tests/test_claude_wake_dispatch.py` and `tests/test_agent_relay_hooks.py`; this Work Record.", "reason": "Independent review rejected the server-side generation fence (candidate 8404f922): no server observation after request arrival can order the hook's separate registration and turn requests. The hook-gated opt-out replaces it.", "impact": "Claude Stop turns with a confirmed idle registration no longer receive the late busy stamp; the Stop confirms busy before emitting. Unflagged clients are unchanged.", "alternatives": "Server-side generation fence (rejected in review); emitting after a failed busy registration (rejected in review).", "authority": {"scope": "task", "name": "task-owner"}, "approval": {"by": "user", "reference": "Owner approval relayed by @pallium-manager (Relay message claude-stop-hook-plan-owner-approval-20261124, remote source: Telegram). Scope: implementation and testing only of the refined conditional Claude Stop-hook plan, including lease recovery when busy cannot be confirmed.", "verbatim": "I approve"}}, {"target": "task-context.constraints", "classification": "requirement-change", "before": "No change to the codex exact path or its pre-turn snapshot callback contract, Relay lease, claim, receipt or ACK semantics, wake dispatch, registration intents, durability or hooks. Without a generation observation, admission keeps the existing fail-closed busy. `wake_inflight` is never downgraded. No live restart, fault injection, dependency or settings change.", "after": "The flag is an additive, optional, Claude-only HTTP request field on non-exact `/relay/turn`; the server rejects it for other runtimes and other values, and Claude cannot send exact claims. It changes only whether admission calls `mark_busy`. Claim, ACK, lease, reservation, routing, remap, native wake reservations and unflagged clients are unchanged. SessionStart and UserPromptSubmit are unchanged. Codex and Hermes paths are unchanged. If busy cannot be confirmed or output fails, the Stop does not ACK and custody stays with the existing lease. No live restart, fault injection, dependency, settings or environment change.", "reason": "Independent review rejected the server-side generation fence (candidate 8404f922): no server observation after request arrival can order the hook's separate registration and turn requests. The hook-gated opt-out replaces it.", "impact": "Claude Stop turns with a confirmed idle registration no longer receive the late busy stamp; the Stop confirms busy before emitting. Unflagged clients are unchanged.", "alternatives": "Server-side generation fence (rejected in review); emitting after a failed busy registration (rejected in review).", "authority": {"scope": "task", "name": "task-owner"}, "approval": {"by": "user", "reference": "Owner approval relayed by @pallium-manager (Relay message claude-stop-hook-plan-owner-approval-20261124, remote source: Telegram). Scope: implementation and testing only of the refined conditional Claude Stop-hook plan, including lease recovery when busy cannot be confirmed.", "verbatim": "I approve"}}, {"target": "task-context.completion_criteria", "classification": "requirement-change", "before": "1. Through the real `/relay/turn` and `/internal/claude-wake/register` HTTP routes built by `build_router`, a Claude turn held after its pre-turn observation while a newer idle registration lands leaves the session wake-eligible: `attempt()` is accepted.\n2. Through the same routes, a Claude turn admitted with no intervening registration still marks that exact session busy, so `attempt()` is `not_eligible`.\n3. Turns for another container or another session do not change the registration.\n4. A current-generation turn does not downgrade a `wake_inflight` reservation.\n5. Codex exact-turn snapshot behavior is unchanged.", "after": "1. Through the real `/relay/turn` and `/internal/claude-wake/register` routes built by `build_router`, a flagged Claude turn held in storage while a newer idle registration lands leaves `attempt()` accepted.\n2. An unflagged Claude turn still marks the session busy; a flagged one leaves it idle.\n3. The flag is rejected (422) for other runtimes and for values other than `\"none\"`; old-shape bodies are unchanged.\n4. The actual Stop hook sends the flag only after a confirmed initial idle registration; without it, the turn is unflagged and legacy emit and ACK are unchanged.\n5. A flagged Stop with rendered work registers busy, then emits, then ACKs and exits 2.\n6. A flagged Stop whose busy registration is not confirmed does not emit, ACK or exit 2, and attempts the final idle registration.\n7. Existing Stop, wake, durability, exact-claim and codex tests pass, with only expected-registration assertions updated for the new busy step.", "reason": "Independent review rejected the server-side generation fence (candidate 8404f922): no server observation after request arrival can order the hook's separate registration and turn requests. The hook-gated opt-out replaces it.", "impact": "Claude Stop turns with a confirmed idle registration no longer receive the late busy stamp; the Stop confirms busy before emitting. Unflagged clients are unchanged.", "alternatives": "Server-side generation fence (rejected in review); emitting after a failed busy registration (rejected in review).", "authority": {"scope": "task", "name": "task-owner"}, "approval": {"by": "user", "reference": "Owner approval relayed by @pallium-manager (Relay message claude-stop-hook-plan-owner-approval-20261124, remote source: Telegram). Scope: implementation and testing only of the refined conditional Claude Stop-hook plan, including lease recovery when busy cannot be confirmed.", "verbatim": "I approve"}}]

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Risk:**
High

**Complexity:**
Simple

**Reason:**
`api/routes.py` is a Redline red-zone path (api-review), so Risk is High. The change adds one optional request field, one admission branch and one hook gate, so Simple.

**Discovery:**
- Retained evidence: a Claude session's Stop hook ran while the service was congested. The service logged a Relay `turn` taking 1217 ms, longer than the Stop hook's 0.75 s client timeout. The hook then re-registered idle. Wakes for a later delivery were deferred `not_eligible` every 30 s for about 53 minutes, until the session's next natural turn.
- `integrations/claude-code/hooks/stop.py` registers idle, calls `relay_turn(timeout=0.75)`, swallows its failure, and registers idle again.
- `api/routes.py` runs `relay_turn_admission_callback` after `turn` completes, regardless of client disconnect. For claude-code, `app/dependencies.py::_relay_turn_admission` calls `ClaudeWakeRegistry.mark_busy`, which had no ordering check.
- Every registry transition bumps the global generation and stamps it on the registration, so a per-registration generation comparison detects any newer transition: register, attempt, release, close.
- Legitimate busy transitions are unaffected: SessionStart and UserPromptSubmit register busy directly before their turns; `release_delivery` sets busy; `wake_inflight` already made `mark_busy` a no-op.
- The existing codex pre-turn snapshot callback is invoked only for codex exact turns, and `tests/test_codex_wake.py::test_old_inflight_claim_generation_cannot_unlock_replacement` relies on that. Reusing it for Claude broke that test, so the Claude observation uses its own callback.
- Independent review of candidate `8404f922` found two blocking paths, so that mechanism is superseded. First, a delayed pre-turn snapshot can observe the replacement idle registration created after the hook's timeout, and then still stamp busy. Second, a failed snapshot falls back to stamping whatever registration is current. The extra Relay runner hop also adds queueing at the affected boundary. No server-side observation after request arrival can order the hook's requests: the hook's idle registration is a separate HTTP request, so server arrival order is not hook send order.
- `integrations/claude-code/hooks/common.py::relay_turn` is the shared helper used by SessionStart, UserPromptSubmit and Stop. One call can send up to two `POST /relay/turn` requests: an intermediate replay to the previous container (`max_chars=1`, `max_messages=1`) during a container remap, then the final destination request. Every request is built from one `payload` dict per loop iteration.
- `api/schemas.py::RelayTurnRequest` has no `extra="forbid"`, and its before-validator inspects only Hermes exact-claim keys, so released servers ignore an unknown body field.
- Hook registration ordering already exists: `register_claude_wake` writes a per-scope write-ahead intent with a fresh `intent_id` before its HTTP POST, and `ClaudeWakeRegistry.register` applies only the latest scoped intent (compare-before-apply). A pending intent is applied later by the reconciler. Production uses the persistent registry, which has a state directory, so intents are active.
- Stop flow today: register idle; `relay_turn`; on rendered deliveries, emit to stderr, then ACK, then exit 2; on no output or any exception, register idle again. The continuation's Stop arrives with `stop_hook_active` true; it still registers idle at entry but skips the Relay turn.

**Material assumptions:**
- `register_claude_wake` returns True only after an HTTP 2xx, which the server returns only after `ClaudeWakeRegistry.register` applied the hook's latest intent. Verified in code; if disproved, return to planning.
- The Stop hook's own registrations, ordered by write-ahead `intent_id`, are the only source of truth for a Stop's busy or idle state once it opts out of the server stamp.

**Plan:**
Authoritative plan (approved; implemented). It supersedes the generation-fence plan, retained below for history. Candidate `8404f922` stays untouched as evidence.
1. Shared helper: `relay_turn` gains an optional keyword `claude_turn_admission: str | None = None`. When it is `"none"`, every outgoing `POST /relay/turn` of that call carries body field `"claude_turn_admission": "none"`, both the intermediate remap replay and the final destination request. When it is absent, the payload is byte-for-byte unchanged. Only `stop.py` passes it. SessionStart and UserPromptSubmit are unchanged.
2. Schema: `RelayTurnRequest` accepts the optional `claude_turn_admission: Literal["none"] | None`. It is rejected with 422 for runtimes other than claude-code and for exact claims.
3. Admission: `_relay_turn_admission` skips `ClaudeWakeRegistry.mark_busy` when the request carries `"none"`. Nothing else reads the field. Claim, ACK, lease, delivery reservation, routing, endpoint registration, remap, activation projection and codex or Hermes paths are unchanged, and so are unflagged clients. There is no snapshot, no generation compare and no extra runner hop.
4. Gate: the Stop hook keeps the result of its existing entry `register_claude_wake(session_id, container_ref, idle=True)`. `True` means confirmed: an HTTP 2xx, which the server returns only after `ClaudeWakeRegistry.register` applied the matching latest intent. Only a Stop with a confirmed initial idle registration passes `claude_turn_admission="none"`. If the initial registration returned False, the Stop uses the legacy unflagged path unchanged: unflagged turn, emit, ACK, exit 2. That covers:
   - wake credentials absent (`CLAUDE_CODE_MESSAGING_SOCKET` or `CLAUDE_CODE_MESSAGING_TOKEN` missing or invalid, which also closes);
   - intent write refused;
   - binding mismatch;
   - a 409 or 400;
   - ambiguous HTTP.
   Clients without native wake therefore keep natural delivery.
5. Flagged Stop that renders work: after `format_relay` returns rendered text and before `_emit_relay`, it calls `register_claude_wake(session_id, container_ref, idle=False)` and requires `True`.
   - On `True`: emit, then ACK, then exit 2, as today, so output still precedes ACK.
   - On `False`, which includes intent-write refusal, missing credentials, a 409 or ambiguous HTTP: do not emit, do not ACK, and do not exit 2. Fall through to the existing post-try `register_claude_wake(idle=True)`. Custody stays with the unchanged lease: the claimed deliveries return to pending when it expires and can then wake the idle session or reach its next natural turn.
6. Output failure after a confirmed busy: `_emit_relay` raises. The existing `except Exception: pass` skips ACK and exit 2, and the hook falls through to the same final idle registration, whose newer intent supersedes busy. Custody again stays with the lease.
   - Confirmed non-idle: in `ClaudeWakeRegistry.register`, `idle=False` produces `state="busy"`, `idle=False`. An existing `wake_inflight` is preserved, and it is also `idle=False`. `attempt()` requires `registration.idle`, so both are wake-ineligible. Verified in code.
   - Ordering of ambiguous busy followed by newer idle: the busy intent file is overwritten by the idle intent with a new `intent_id`. A late busy POST then fails `register`'s compare (409), and a reconciler pass applies only the latest idle intent. If busy was applied first, the later idle applies over it.
   - Remaining ambiguity:
     a. If the final idle intent cannot be written, an applied or pending busy can remain until the next hook registration. That is fail-closed, the same exposure as today's legacy behavior.
     b. If the initial idle registration was ambiguous, the hook later succeeds server-side and the Stop took the legacy path, so today's late `mark_busy` race remains for that subcase.
     c. Claimed but unemitted deliveries wait one lease before becoming wakeable. That adds latency, not loss.
     d. The extra pre-emit busy POST runs under the Stop budget, which is 15 s with a 1 s host reserve. Under the same congestion that causes this bug it can fail, which turns into lease-delayed delivery.
   - Material compatibility: none breaking.
     - New hook + old server: the flag is ignored, so legacy busy applies. The registration endpoint exists on servers with Claude wake.
     - Servers without that endpoint fail the initial registration, and the Stop takes the legacy path.
     - Old hook + new server: unchanged legacy behavior.
7. The `8404f922` product mechanism is not carried: implementation branches from current main. Its HTTP-boundary tests are retargeted to the flag.
Revised stop conditions: any needed change to claim, ACK, lease, reservation or routing; changing SessionStart or UserPromptSubmit admission; any test requiring weakened existing assertions.

Invariant: a Claude session's wake eligibility changes only through:
- hook registration intents, ordered per session by the hook's write-ahead `intent_id`, latest wins;
- registry-internal reservation transitions: attempt, release, close.

A Stop turn marked non-admitting never changes registry state, whenever it arrives. An unmarked Claude turn keeps today's fail-closed `mark_busy`.

Compatibility:
- Old hook + new server: no field, so legacy busy; the bug persists until hooks update, with no break.
- New hook + old server: the field is ignored, so legacy busy; the extra pre-emit busy registration is redundant and harmless.
- A forged or replayed flagged turn only suppresses a busy stamp. It cannot create or revive idle, because idle requires a hook registration with the session's socket and token. Its eligibility effect equals sending no turn.

Superseded generation-fence plan (history only, not authoritative):
1. Characterization: add both HTTP-boundary tests; the late-admission test must fail on base only because the session stays busy.
2. Add `ClaudeWakeRegistry.generation_for` and an optional `expected_generation` atomic compare in `mark_busy` under the registry lock.
3. Capture the Claude generation before the non-exact turn through a new `relay_turn_claude_generation_callback`; pass it as the admission callback's third argument. A capture failure leaves it None, which keeps legacy busy.
4. Run the focused Claude wake, codex wake, exact-claim and Claude integration test files.
Stop conditions: any needed change to hooks, lease or ACK semantics, or the codex snapshot contract; any test requiring weakened existing assertions.

API checkpoint: `claude_turn_admission` is an additive, optional HTTP request field on `POST /relay/turn`, accepted only for runtime claude-code with value `"none"`. Old hook + new server: no field, legacy busy. New hook + old server: field ignored (no `extra="forbid"`), legacy busy. Response shape unchanged.
Gate versus enforcement: the hook, not the server, gates the flag on a confirmed initial idle registration. The server validates only runtime and value; it cannot verify the hook's registration. A forged flag only suppresses a busy stamp and cannot create idle.

**Verification plan:**
Authoritative verification (the generation-fence verification below is superseded). Real `build_router` HTTP routes on real storage, plus the existing `_load_claude_hook` harness for actual hooks.
- Pre-route delay → a flagged Stop turn sent only after a newer idle registration has fully landed leaves `attempt()` accepted. RED on base, because base ignores the field and stamps busy.
- Delay after route entry → a flagged Stop turn held at `storage.relay_turn` while a newer idle registration lands leaves `attempt()` accepted. RED on base.
- Unflagged control → the same two orderings without the flag still end busy and `not_eligible`.
- Scope → another container's or session's turn leaves the registration unchanged, and a current turn keeps `wake_inflight`.
- Flag inertness → for a flagged versus an unflagged turn with identical deliveries, the claim result, delivery states, lease, ACK outcome, endpoint row and remap outcome are equal. Only the busy stamp differs.
- Schema → the flag is rejected for codex, Hermes and opencode and for exact claims; an old-shape body is accepted unchanged.
- Helper → with the flag, both the intermediate remap request and the final request carry it; without it, the payloads equal the base payloads.
- Actual Stop hook, no deliveries → the flag is sent and the session ends idle.
- Actual Stop hook, rendered deliveries with confirmed busy → the call order is register busy, emit, ACK, exit 2.
- Continuation → the continuation Stop (`stop_hook_active`) ends idle.
- No wake credentials → the initial registration fails and the Stop sends no flag. Legacy emit and ACK still deliver.
- Initial intent-write refusal → same as no credentials.
- Flagged Stop, busy intent-write refusal → no emit, no ACK, no exit 2; the final idle is attempted; the deliveries stay claimed and become pending after the lease.
- Flagged Stop, ambiguous busy HTTP followed by newer idle → the busy POST is held until after the final idle intent; the session ends idle and eligible, and the late busy is rejected (409); no emit and no ACK.
- Output failure after confirmed busy → no ACK, no exit 2; the session ends idle; the deliveries become pending after the lease.
- Codex → `tests/test_codex_wake.py` unchanged.

Superseded generation-fence verification (history only):
- Criterion 1 → `tests/test_claude_wake_dispatch.py::test_late_turn_admission_cannot_overwrite_newer_idle_registration`, failing on base and passing after the fix.
- Criteria 2, 3 and 4 → `tests/test_claude_wake_dispatch.py::test_current_generation_turn_admission_still_marks_busy`.
- Criterion 5 → `tests/test_codex_wake.py`, unchanged, including `test_old_inflight_claim_generation_cannot_unlock_replacement`.
- Regression → `tests/test_claude_wake_dispatch.py tests/test_claude_wake_durability.py tests/test_relay_exact_claim_e2e.py tests/test_codex_wake.py tests/test_claude_code_integration.py` with `-n 0`. The full suite and reviews are sequenced by the manager.

**Plan review:**
Agent technical review: independent reviewer via @pallium-manager, Relay message claude-stale-busy-authoritative-plan-20261124 — conditional GO for the revised plan, conditional on this record reconciliation (done). The first candidate (`8404f922`) and emit-after-failed-busy were rejected earlier (see Discovery).

**Approvals:**
Approved by user 2026-11-24T19:17:09 (time the manager relayed it; original approval time not recorded): "I approve" — owner approval relayed by @pallium-manager from a remote source (Telegram). Scope: implementation and testing only of the refined conditional Claude Stop-hook plan, including lease recovery when busy cannot be confirmed. Not covered: publication, merge, live fault injection, service restart, host reload, permission, environment, security or access changes. A separate High-risk result review is still required.
Approved by user 2026-11-25T10:58:00: "the pallium manager should decide, you shouldn't ask me, i'm not always watching this session" — the owner's direct answer in this session when asked about publication. It delegates the decision to @pallium-manager, which directed normal release of the exact reviewed result (Relay message claude-stop-result-release-proceed-20261125). Merge still waits for the recorded result review and hosted gates. No live changes.

**Exceptions:**
—

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Ready for review
<!-- agent-workflow:end -->

## Evidence

- Base `312aca09` with the new tests only, `-n 0`: `test_late_turn_admission_cannot_overwrite_newer_idle_registration` failed with `('deferred', 'not_eligible') == ('accepted', 'transport_accepted')`; `test_current_generation_turn_admission_still_marks_busy` passed, confirming it characterizes existing behavior.
- After the fix, `-n 0`: both new tests passed.
- First wiring attempt reused the codex snapshot callback and failed `tests/test_codex_wake.py::test_old_inflight_claim_generation_cannot_unlock_replacement`; replaced by a dedicated Claude callback.
- Focused regression after the final change, `-n 0`: the five files above gave 598 passed, 4 skipped.
- The evidence above is for the superseded generation-fence candidate `8404f922`.

Approved Stop-hook opt-out, branched from current main `24fe8d64`, `-n 0`:
- RED on main product code with the new tests: 12 failed (late flagged turn left busy; flag accepted for other runtimes and values; Stop sent no flag, registered no busy before emitting, emitted when busy was unconfirmed; remap requests lacked the flag), and the 4 legacy-path tests passed.
- GREEN after the fix: all new and updated tests pass.
- Updated existing assertions: `test_claude_stop_emits_rendered_subset_before_ack` now expects the flag in the turn body; `test_expired_claim_rewakes_once_after_real_app_restart` now expects the busy registration before emit when the initial idle was confirmed; `tests/test_relay_capacity_isolation.py` drops the new field where it mirrors the route's request-to-`turn()` conversion.
- Focused regression (`tests/test_claude*.py`, `tests/test_agent_relay_hooks.py`, `tests/test_hook_deadline_safety.py`, `tests/test_structural_work_refs_e2e.py`, `tests/test_codex_wake.py`, `tests/test_relay*.py`): 1610 passed, 6 skipped; then the two changed files again: 297 passed, 2 skipped. Remaining failure `test_capacity_limiter_reserves_released_token_for_waiting_borrower` exercises only the third-party `anyio` limiter with no Pallium code, so it is environmental. `tests/test_relay_mcp_tools.py` is not collectable locally (missing `pywintypes`).
- Coverage gaps closed on successor commit, `-n 0`:
  - `test_flagged_and_unflagged_claude_turns_are_equivalent_over_http`: through real `build_router` routes, a flagged and an unflagged session have equal registration generation, claim result, claim and lease timestamps, lease-expiry reclaim, ACK outcome, delivered state and remap result. It is a characterization: it passes on main too, where the flag is ignored.
  - `test_ambiguous_busy_after_newer_idle_leaves_lease_custody`: a real app, real intent store and the actual Stop hook. The busy intent is written but its POST is held; the hook does not emit, ACK or exit 2; its final idle registration returns 204; the held busy POST then returns 409; the registry stays idle; after the lease the same delivery is reclaimed with attempts 2. It fails on main.
  - Both new tests together: 2 passed; on main product code: 1 failed (ambiguous busy), 1 passed (equivalence).
  - `tests/test_relay_mcp_tools.py` with the existing dependency target plus `win32` and `win32/lib` on a process-local `PYTHONPATH`, no install: 201 passed. Inherited host Claude session identity (`CLAUDE_CODE_SESSION_ID` and related variables) must be unset for that process; with it set, 5 fail-closed identity tests fail because the MCP server inherits the host session.
- Historical attribution, likely only and not closed: two deliveries to a Claude session were deferred on every 30 s wake attempt (108 and 1470 attempts) until a natural turn, the first right after a 775 ms Relay `turn` (above the Stop hook's 0.75 s timeout) and the second during heavy Relay congestion. Durations and repeated `not_eligible` do not prove the exact late `mark_busy` transition.
- Schema successor `363c89b3`: one added parametrized case, claude-code + `claude_turn_admission="none"` + a valid `wake_delivery_id`, returns 422. `test_claude_turn_admission_rejects_other_runtimes_and_values`: 3 passed. Product files are byte-identical to `c62eb1bf`.
- Release reconciliation: rebased `2311eb9f..363c89b3` onto `origin/main` `0aa8f0e9` as `313695cd`, `d77f0ade` and `65adf78a`. `git range-diff` shows all three patch-identical, and main's changes since `24fe8d64` touch no file on this branch. The branch is renamed `fix/claude-pallium-stale-busy-fence` so CI derives this record's slug; the old `claude-pallium/stale-busy-fence` branch keeps `8404f922` untouched.
- Separate item: the delivery trace recorded `prepared` activations with no matching `completed` events while the service log showed deferred outcomes. The omitted events were not recovered, so trace completeness stays open on its own.

## Result review

Independent High-risk result review via @pallium-manager:
- `2311eb9f`: HOLD, pending real-route and actual-hook lifecycle tests and an explicit marker-plus-exact 422 (Relay `relay-reply-fb1139df7326e797a7bf2a0f2fc5f36fea871b3f1c9b1bfb79ed240ab478ffbb`).
- `c62eb1bf`: both added lifecycle controls accepted; one schema case remained (Relay `relay-reply-ec400b3d7cfa49ffe878963bd45eac2781c2284b50cb73333b6cde0b4c163a41`).
- `363c89b3`: verified as the exact requested test-only successor (Relay `relay-reply-fe99ba80a899ce319acca93674f8a924628b94b117180bdbbbeed1c7ca6dbe18`).
- The rebased head is patch-identical to `363c89b3` (see Evidence).
