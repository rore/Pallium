# Keep Claude wake eligibility after idle compaction

<!-- agent-workflow:start -->
**Outcome:**
After Claude Code compacts an idle session, Relay wakes reach that session again without waiting for a human prompt. Compaction no longer leaves the wake registration `busy` with no later Stop to reset it.

**Target:**
Claude Code SessionStart hook (`integrations/claude-code/hooks/session_start.py`) when `source == "compact"`: its baseline wake registration call.

**Scope:**
`integrations/claude-code/hooks/session_start.py` (compact branch only) and focused tests in `tests/test_agent_relay_hooks.py`. Stacked on the custody-only change (`a5debb0c`), which stays a separate review and publication. SessionStart `startup`, `resume` and `clear`, the registry, the register route and historical attribution are out of scope.

**Constraints:**
Compact-only. Conditional candidate: on compact, skip `register_claude_wake` and keep the existing row as it is. This is valid only if the pre-compaction registration stays usable. If the evidence gate below fails, do not implement the skip. Record the failure and return to planning with the state-preserving refresh below. No change to the registry, route, admission, `common.py` or other hooks in this candidate. Do not revive held candidate `133f2a21`. No product or test edit, push, rerun or live operation before the plan review. Never induce a live compaction or wake, and never touch the installed binding. Credential evidence is equality booleans only, never values or digests.

**Completion criteria:**
1. Idle compact: the hook makes no wake registration and no Relay request. The existing `idle` row keeps its credential, generation and state. One later wake is `accepted` using the pre-compaction registration. The delivery ends `delivered` with attempts 1 and exactly one ACK.
2. Mid-turn compact: a row that is `busy` stays `busy` through compaction. Stop then sets it `idle`, and one later wake is accepted and ACKed once.
3. Compact during `wake_inflight`: the persisted row is byte-identical before and after the hook, including `delivery_id`, `attempted_at`, `recipient_endpoint_id` and `admission_id`.
4. Pending close or replacement intent: compact does not write, consume or apply a scoped intent. The intent file is byte-identical after the hook.
5. Registry refusal (rehydration refused, or the scoped lock not acquired): compact makes no registration request. The refusal state is unchanged.
6. Stale or uncertain wake: when the registration's endpoint is missing or the transport result is uncertain, the delivery is not lost, replayed or duplicated. One ordinary pickup (UserPromptSubmit or Stop) delivers it and ACKs it exactly once. The registry ends with no accumulated `wake_inflight` reservation for that session, and later wakes are eligible again after a normal idle registration.
7. Non-compact SessionStart (`startup`, `resume`, `clear`, empty and missing `source`) keeps one `idle=False` registration, the Relay turn and the ACK, exactly as on `a5debb0c`.
8. The custody behavior from `a5debb0c` is unchanged on compact: no `/relay/turn`, claim or ACK, and orientation output unchanged.

**Requirement baseline:**
{"source": "work-record-initial", "outcome": "After Claude Code compacts an idle session, Relay wakes reach that session again without waiting for a human prompt. Compaction no longer leaves the wake registration `busy` with no later Stop to reset it.", "scope": "`integrations/claude-code/hooks/session_start.py` (compact branch only) and focused tests in `tests/test_agent_relay_hooks.py`. Stacked on the custody-only change (`a5debb0c`), which stays a separate review and publication. SessionStart `startup`, `resume` and `clear`, the registry, the register route and historical attribution are out of scope.", "constraints": "Compact-only. Conditional candidate: on compact, skip `register_claude_wake` and keep the existing row as it is. This is valid only if the pre-compaction registration stays usable. If the evidence gate below fails, do not implement the skip. Record the failure and return to planning with the state-preserving refresh below. No change to the registry, route, admission, `common.py` or other hooks in this candidate. Do not revive held candidate `133f2a21`. No product or test edit, push, rerun or live operation before the plan review. Never induce a live compaction or wake, and never touch the installed binding. Credential evidence is equality booleans only, never values or digests.", "completion_criteria": "1. Idle compact: the hook makes no wake registration and no Relay request. The existing `idle` row keeps its credential, generation and state. One later wake is `accepted` using the pre-compaction registration. The delivery ends `delivered` with attempts 1 and exactly one ACK.\n2. Mid-turn compact: a row that is `busy` stays `busy` through compaction. Stop then sets it `idle`, and one later wake is accepted and ACKed once.\n3. Compact during `wake_inflight`: the persisted row is byte-identical before and after the hook, including `delivery_id`, `attempted_at`, `recipient_endpoint_id` and `admission_id`.\n4. Pending close or replacement intent: compact does not write, consume or apply a scoped intent. The intent file is byte-identical after the hook.\n5. Registry refusal (rehydration refused, or the scoped lock not acquired): compact makes no registration request. The refusal state is unchanged.\n6. Stale or uncertain wake: when the registration's endpoint is missing or the transport result is uncertain, the delivery is not lost, replayed or duplicated. One ordinary pickup (UserPromptSubmit or Stop) delivers it and ACKs it exactly once. The registry ends with no accumulated `wake_inflight` reservation for that session, and later wakes are eligible again after a normal idle registration.\n7. Non-compact SessionStart (`startup`, `resume`, `clear`, empty and missing `source`) keeps one `idle=False` registration, the Relay turn and the ACK, exactly as on `a5debb0c`.\n8. The custody behavior from `a5debb0c` is unchanged on compact: no `/relay/turn`, claim or ACK, and orientation output unchanged."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Risk:**
High

**Complexity:**
Simple

**Reason:**
The change decides whether a session can be woken after compaction and which credential a wake uses. A mistake could strand a delivery, leave a reservation stuck or mark a live session unreachable, so Risk is High. The candidate is one branch in one hook with no server change, so Complexity is Simple. If the evidence gate fails, the refresh alternative is a registry and route change and must be reclassified.

**Discovery:**
- On native idle compaction, SessionStart runs with source `compact` without a turn or Stop. The real-hook regression shows that `register_claude_wake(idle=False)` replaces the `idle` row with a `busy` row, so the next wake is deferred as `not_eligible`.
- After `a5debb0c`, compact no longer calls `/relay/turn`, so `_relay_turn_admission` no longer calls `mark_busy`. The baseline registration is now the only busy writer on compact. Skipping it removes the defect if the existing row stays usable.
- `ClaudeWakeRegistry.register` has no state-preserving mode. For `idle`, `busy` and `unreachable` rows it writes a new row whose state comes only from `idle`. For `wake_inflight` it keeps the fence, swaps the credential and drops `admission_id`. Every successful register also runs `complete_registration` (Relay `mark_active`) and bumps the generation.
- `attempt()` uses the stored socket and token. A missing endpoint gives `failed`/`endpoint_missing` and moves the row to `unreachable`. An exception or other result gives `uncertain` and keeps the `wake_inflight` reservation. So a stale credential does not simply delay delivery: it turns `not_eligible` into a real transport attempt with persistent side effects. Criterion 6 must prove the recovery path, not assume it.
- Host contract: Claude Code documents SessionStart source `compact`. That it also runs after idle compaction with no turn is observed, not documented. Whether `CLAUDE_CODE_MESSAGING_SOCKET` and `CLAUDE_CODE_MESSAGING_TOKEN` stay the same across compaction is undocumented and unproven.

**Material assumptions:**
- A1 (unverified; post-deployment observation): after a real native idle compaction, a wake sent with the unchanged pre-compaction registration is accepted by the same session. The woken turn emits the delivery and ACKs it once. If disproved, record it and re-plan. No qualifying observation means unverified, not a pass.
- A2: no consumer depends on SessionStart compact to refresh the wake credential or to mark the session busy. Turn admission (`UserPromptSubmit` / `/relay/turn`) and Stop own the busy and idle transitions.

**Plan:**
1. On `source == "compact"`, leave the existing wake registration unchanged. Every other source still registers with `idle=False`. The custody skip from `a5debb0c` is unchanged.
2. Verify the exact change offline and in hosted CI. Keep the custody contribution separately reviewable.
3. Observe A1 after deployment only if it occurs naturally. There must be no intervening prompt, turn, Stop, registration, refresh or competing pickup between the idle Stop and the start of the woken turn. Do not induce compaction or wake, run a separate host experiment, or change installed bindings.

Refresh alternative (not in this scope; only if the gate fails): a register mode "refresh credential, keep state":
- It uses the existing write-ahead intent and compare-before-apply.
- It applies only to an existing row for the exact scope, and refuses when no row exists.
- It replaces only `socket_path` and `token`, and bumps the generation.
- It keeps the state, `delivery_id`, `attempted_at`, `recipient_endpoint_id` and `admission_id`.
- It does not call `complete_registration`.
- Compact would send only that mode.
- Whether an `unreachable` row returns to `idle` on a fresh credential needs an explicit review decision.

**Verification plan:**
- A1 → observe after deployment, as directed by the owner. A qualifying observation still requires native idle compaction, an accepted wake on the unchanged pre-compaction registration, and the same delivery emitted and ACKed once. A fake transport, normal Stop or manual `/compact` does not qualify.
- Criterion 1 → run the real compact hook against the loopback router and preserve the idle registration. A fake transport accepts a wake on that registration. Run the real UserPromptSubmit hook with a synthetic wake notice: it emits and ACKs the same delivery once, the delivery ends delivered with attempts 1, and the exact reservation clears. Criterion 8 checks no Relay request during compact.
- Criterion 2 → `test_claude_mid_turn_compact_stays_busy_until_stop_then_wakes`: a `busy` row stays `busy` with the same generation through the real compact hook, with no register request. Work that arrives during the turn is not woken and is picked up once by ordinary pickup. After Stop's idle registration, a later delivery's wake is accepted, emitted once and ACKed once, and the fence is released. That acceptance is attributed to Stop's registration, never to A1.
- Criterion 3 → `test_claude_session_start_compact_leaves_registry_state_untouched[inflight]`: seed a `wake_inflight` row with an `admission_id`. After the real compact hook, `capabilities.json` bytes and the row are identical, the `admission_id` is kept, and there are no register, close or Relay requests.
- Criterion 4 → `test_claude_session_start_compact_leaves_registry_state_untouched[pending_close|pending_replacement]`: seed a closed intent, or a replacement intent with different credentials. The intent file and `capabilities.json` bytes are identical after the compact hook, and no register or close request is made.
- Criterion 5 → `test_claude_session_start_compact_leaves_registry_state_untouched[refused|lock_held]`: with the app registry refused, or the scoped intent lock held by the test, the compact hook makes no request. The bytes are identical, the refusal flag is still set, and the lock is still held.
- Criterion 6 → `test_claude_failed_wake_recovers_by_ordinary_pickup_then_wakes_again[unreachable|uncertain]`, with no fixture clearing. The same delivery stays pending with attempts 0 in an `unreachable` row or an exact `wake_inflight` fence. One ordinary emission and one router ACK end with it `delivered` and attempts 1. The ACK releases the uncertain fence before Stop. After Stop's idle registration, a distinct later delivery gets a successful wake.
- Criterion 7 → the existing parametrized non-compact test, unchanged.
- Criterion 8 → the existing compact custody test from `a5debb0c`, with its registration assertion updated only for the skipped registration.
- Regression → focused suites only: `tests/test_agent_relay_hooks.py`, `tests/test_claude_wake_registration.py`, `tests/test_claude_wake_dispatch.py`, `tests/test_claude_wake_durability.py`, `tests/test_claude_code_hooks`, `tests/test_claude_code_integration.py`.

**Plan review:**
Agent technical review: independent clean-context GO for the bounded offline one-line candidate on exact commit `450d0247`. That review left native A1 as a release gate. The owner subsequently moved A1 to post-deployment observation without changing the product patch or the A1 acceptance criteria.

**Approvals:**
The task owner approved the Claude compaction custody and wake fixes and directed deployment without waiting for A1. The verbatim approval is retained privately. This does not replace separate human result review.

**Exceptions:**
- rule: approval.high_risk_approval_recorded
  reason: The task owner directed deployment without further approval paperwork. Keep the verbatim approval private.
  scope: Public approval quote for the Claude idle-compaction wake fix in PR 430 only.
  approver: repository owner
  expiry: 2026-12-09
  compensating_validation: The task owner explicitly approved this fix and its deployment. Retain the private approval and keep the independent review and CI requirements.

**State:**
Ready for review
<!-- Ready to implement | Blocked | Ready for review -->
<!-- agent-workflow:end -->

Stacked on the separately reviewed custody fix in [#429](https://github.com/rore/Pallium/pull/429). Separate human result review and hosted checks are pending. Native A1 is unverified.

## Remaining evidence gap

- Native A1 has no evidence yet. The disposable journey is not part of the release plan.
- Criterion 6 is covered offline by its test (see below). The offline tests use a fake transport and cannot qualify A1.

## Offline test-first evidence (separate from native gate A1)

This evidence covers the real hook and Pallium router, not the native Claude wake transport.

- Test: `tests/test_agent_relay_hooks.py::test_claude_session_start_compact_keeps_idle_wake_eligibility`. It uses the real-hook and loopback-router harness with synthetic credentials and a fake transport that records the credential a wake would use.
  1. The real `register_claude_wake(idle=True)` seeds the row `idle`, as Stop does.
  2. The real `session_start.py` runs as a subprocess with `source: compact`.
  3. A delivery is queued afterwards, and the app's own dispatch and reconciler attempt the wake.
- RED on the custody baseline (product `session_start.py` blob `25622d92`): `('busy', [(204, False)], ('deferred', 'not_eligible'), ('pending', 0))` against the expected `('idle', [], ('accepted', 'transport_accepted'), ('pending', 0))`. That shows:
  - compact's registration makes the idle row busy;
  - the wake is deferred as `not_eligible`;
  - the delivery is not consumed.
- Candidate check, not committed: with the one-line skip applied temporarily, this test passes. The custody test then fails only on its registration-count assertion, as criterion 8 anticipates. The product file was restored to `25622d92` afterwards.
- Stale or uncertain recommendation, from code (criterion 6 still needs its test):
  - With the skip, the row keeps the pre-compaction credential.
  - Static inspection of Claude Code 2.1.332 shows the messaging token is generated once per inbox start and the socket is named by process id. So a stale credential needs an inbox restart, not a compaction.
  - If it is stale anyway, the attempt ends either `unreachable` (row `unreachable`, delivery still pending) or `uncertain` (`wake_inflight` kept until `release_delivery` on that delivery's ACK, then `busy`). Both are existing states that any dead or replaced session already reaches, and neither claims or consumes the delivery. The ordinary pickup then emits and ACKs it once.
  - Recommendation: advance the skip after exact review, with the criterion 6 test. A state-preserving refresh primitive is not required for this defect.
- Criterion 6 lifecycle control on the unchanged product (`session_start.py` blob `25622d92`):
  - Test: `tests/test_agent_relay_hooks.py::test_claude_failed_wake_recovers_by_ordinary_pickup_then_wakes_again[unreachable|uncertain]`. It uses the same harness with synthetic credentials and no fixture clearing.
  - Flow: the real idle registration, then one delivery; the first wake fails, either `unreachable` or ambiguous (`uncertain`).
  - Failure state is kept: `unreachable` leaves the row `unreachable` with the delivery pending and attempts 0; `uncertain` leaves `wake_inflight` fenced on that exact delivery, pending with attempts 0.
  - Recovery: the real UserPromptSubmit pickup emits the payload once with one ACK. Right after the ACK, and before any Stop, the row is `busy` with no fence (`mark_busy` leaves a `wake_inflight` row unchanged, so the ACK's `release_delivery` clears it). The delivery is `delivered` with attempts 1.
  - Afterwards: Stop's real idle registration, then a distinct later delivery gets an accepted wake on the same credential.
  - Result: 2 passed.
- This control and the RED above are offline evidence only. A fake transport acceptance does not qualify native A1 or release. Product edits wait for plan review.

## Implementation and verification (offline candidate)

- `integrations/claude-code/hooks/session_start.py`: on `source == "compact"` the hook no longer calls `register_claude_wake`. Every other source still registers with `idle=False`. The custody skip from `a5debb0c` is unchanged.
- Custody test (criterion 8): only its registration assertion changed. On compact it now asserts no register request and no registry row created. Orientation, no Relay pickup, pending with attempts 0, then one ACK and delivered with attempts 1 are unchanged.
- The RED from `450d0247` now passes. The criterion 6 control passes on the candidate.
- Criteria 2 and 6 were restored to their baseline wording. The reviewer's stricter requirements live in the verification plan and the tests, so no Behavior changes entry is needed.
- Focused runs on this candidate (the mid-turn test was added after these runs and passes on its own; the compact and failed-wake cases, 10 in all, were rerun after the criteria restore and pass):
  - `tests/test_agent_relay_hooks.py` compact, non-compact (startup, resume, clear, empty, missing) and failed-wake cases: 11 passed.
  - `tests/test_claude_wake_registration.py` and `tests/test_claude_code_hooks`: 253 passed.
  - Every other Claude test that loads `session_start.py`: 6 passed.
- Criteria 3–5 controls (added after the result-review HOLD): `test_claude_session_start_compact_leaves_registry_state_untouched[inflight|pending_close|pending_replacement|refused|lock_held]`. Only these five cases were run on this revision: 5 passed. `git diff --check` is clean.
  - With `session_start.py` temporarily restored to its `a5debb0c` bytes, `inflight`, `pending_close`, `pending_replacement` and `refused` fail, so the tests discriminate. `lock_held` also passes there, because the old hook could not take the intent lock and so sent nothing. The product file was restored to blob `cb373487`.
- Native A1 was not run. A fake transport acceptance does not qualify it.
- Delta-review correction (test only): the `[inflight]` case now seeds the fence with a nonempty synthetic `delivery_id` and a valid `relay-session-…` `recipient_endpoint_id`. Before compact it asserts both, plus `admission_id`; after compact it asserts the same exact values alongside the existing byte and row equality. Only `[inflight]` was run: 1 passed. `git diff --check` is clean.

## Whole-change qualification

- First Windows run: 6,025 passed before an unchanged concurrent History test returned 404. The symptom reproduced on clean base, but the cause of this run's 404 was not captured.
- Second Windows run, with an independently reviewed History test correction: 7,555 passed before an unchanged offline Relay repair test hit a SQLite lock. The failing path matches base, and that node passed in a separate composition. Neither run passed; the lock cause is not established. The History test change is not in this PR.
- Hosted run `45686503052` on `97eefb8b`: Windows smoke passed. Linux 3.12 stopped after 7,026 passes on an unchanged OpenCode wake test (`KeyError: 'wake'`). Linux 3.13 stopped after 4,719 passes on the new stale-wake test: it read the reservation after publication but before the transport outcome settled. Neither Linux lane nor the aggregate passed. Governance recognized both privacy exceptions but rejected an untracked rewrite of the constraint field.
- The follow-up changes tests and this record only. Snapshot the stale-wake result under the registry lock after transport is reached, not on the first non-idle state. Assert the compact controls reach orientation and that the idle-wake test emits and ACKs the exact delivery once and releases its reservation. Restore the original constraint field and keep the owner's verification-order decision explicit in the plan. Fifteen focused Windows cases passed; no additional local full run.

## Result review

Agent technical review: independent non-implementer offline GO on the final exact candidate.
Reviewed revision: `98ce6960efbd228a27a1b9382ee5e55c0e156e7e`.
Verification adequacy: real-hook RED/GREEN, exact in-flight custody, compact and non-compact controls, and stale or uncertain wake recovery cover the hook change. The follow-up test-only delta, fresh hosted result, and separate human result review remain pending. No native idle-compaction success is claimed.
