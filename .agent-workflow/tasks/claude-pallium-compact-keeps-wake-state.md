# Keep Relay custody on Claude SessionStart compact

<!-- agent-workflow:start -->
**Outcome:**
Claude Code compaction no longer claims or ACKs Relay deliveries into hook context that no model turn may read. On SessionStart compact, pending Relay work stays pending for the next ordinary pickup: a wake, a prompt or Stop. This fixes unread custody only. It does not fix wake eligibility after an idle compaction.

**Target:**
Claude Code SessionStart hook (`integrations/claude-code/hooks/session_start.py`) when `source == "compact"`: its Relay turn, render and ACK block.

**Scope:**
`integrations/claude-code/hooks/session_start.py` (compact branch of the Relay block only) and focused tests in `tests/test_claude_wake_registration.py`. Wake registration, idle-wake eligibility after compaction, SessionStart `startup`, `resume` and `clear`, and attributing past missed wakes are out of scope.

**Constraints:**
Compact-only. Keep baseline wake registration (`register_claude_wake(idle=False)`) and the orientation `/query` and context output unchanged on compact. No change to router, registry, admission, `common.py` or other hooks. No product edit, push or live change until the required plan gates pass. No service restart, install or live probe. Candidate `133f2a21` stays unpublished.

**Completion criteria:**
1. On SessionStart compact, the real hook sends no `/relay/turn` request and no claim or ACK, and renders no Relay output.
2. A delivery pending before the compact hook is still pending with attempts = 0 after it. One ordinary pickup then delivers it and ACKs it exactly once.
3. On compact, the baseline wake registration and the orientation `/query` and context output are unchanged.
4. Non-compact SessionStart (`startup`, and a missing or empty `source`) keeps today's registration, Relay delivery and ACK.
5. Existing Claude wake registration, dispatch, durability and Claude hook tests pass.

**Requirement baseline:**
{"source": "work-record-initial", "outcome": "Claude Code compaction no longer claims or ACKs Relay deliveries into hook context that no model turn may read. On SessionStart compact, pending Relay work stays pending for the next ordinary pickup: a wake, a prompt or Stop. This fixes unread custody only. It does not fix wake eligibility after an idle compaction.", "scope": "`integrations/claude-code/hooks/session_start.py` (compact branch of the Relay block only) and focused tests in `tests/test_claude_wake_registration.py`. Wake registration, idle-wake eligibility after compaction, SessionStart `startup`, `resume` and `clear`, and attributing past missed wakes are out of scope.", "constraints": "Compact-only. Keep baseline wake registration (`register_claude_wake(idle=False)`) and the orientation `/query` and context output unchanged on compact. No change to router, registry, admission, `common.py` or other hooks. No product edit, push or live change until the required plan gates pass. No service restart, install or live probe. Candidate `133f2a21` stays unpublished.", "completion_criteria": "1. On SessionStart compact, the real hook sends no `/relay/turn` request and no claim or ACK, and renders no Relay output.\n2. A delivery pending before the compact hook is still pending with attempts = 0 after it. One ordinary pickup then delivers it and ACKs it exactly once.\n3. On compact, the baseline wake registration and the orientation `/query` and context output are unchanged.\n4. Non-compact SessionStart (`startup`, and a missing or empty `source`) keeps today's registration, Relay delivery and ACK.\n5. Existing Claude wake registration, dispatch, durability and Claude hook tests pass."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Risk:**
High

**Complexity:**
Simple

**Reason:**
The change decides who holds Relay custody after compaction. A mistake could strand or double-deliver work, so Risk is High. It is one branch in one hook with no server or registry change, so Complexity is Simple.

**Discovery:**
- Observed incident (2026-11-25): Claude Code compacted an idle session ("Compacted while idle") and ran SessionStart with source `compact`. No turn and no Stop followed. Later Relay wakes for that session were deferred as `not_eligible` until a human prompt. That wake-eligibility defect is a separate lane and is not fixed here.
- Custody: on compact, SessionStart calls `/relay/turn`, renders claimed deliveries into hook context and ACKs them. After an idle compaction, no model turn reads that context until the next prompt, so ACKed work waits unread. A mid-turn compaction would deliver into the ongoing turn, but ordinary pickup at Stop covers that case without risk.
- The same unflagged `/relay/turn` call also makes `_relay_turn_admission` call `registry.mark_busy` (`app/dependencies.py`). Removing the call on compact removes that write, but the baseline `register_claude_wake(idle=False)` still marks busy, so idle-wake eligibility is unchanged by design.
- Host contract: Claude Code documents SessionStart sources `startup`, `resume`, `clear` and `compact`; `compact` follows manual and automatic compaction. That it also follows idle compaction, with no turn, is observed in this incident's session transcript, not documented.
- Registry credential refresh: `ClaudeWakeRegistry.register` has no state-preserving refresh primitive. It always sets `idle` or `busy` from the request, except for a `wake_inflight` row, where it keeps the fence and swaps the credential. See the idle-wake lane note below.

**Material assumptions:**
- No consumer depends on SessionStart compact to deliver Relay messages. Ordinary pickup (wake, UserPromptSubmit, Stop) retains custody. If disproved, return to planning.

**Plan:**
In `session_start.py`, when `source == "compact"`, skip the Relay block: `relay_turn`, `format_relay` output and `acknowledge_relay`. Everything else on compact is unchanged, including `register_claude_wake(idle=False)` and the orientation `/query` and its context output. Every other source, and a missing or empty `source`, is unchanged.

Candidate `133f2a21` (skipped registration on compact) is out of this scope and stays unpublished. The implementation starts from `origin/main` and does not include it.

**Verification plan:**
- Criterion 1 → run the real hook as a subprocess with `source: compact` against a loopback router; record every request and assert no `/relay/turn`, claim or ACK, and no Relay text in the hook output.
- Criterion 2 → with the real router and Relay store: queue a delivery, run the compact hook, assert it is still pending with attempts = 0; then run one ordinary pickup (UserPromptSubmit hook) and assert it is delivered and ACKed exactly once.
- Criterion 3 → in the same compact run, assert exactly one baseline wake registration with `idle=False`, and that the orientation `/query` request and its context output occur as before.
- Criterion 4 → existing startup SessionStart registration and Relay-delivery tests, plus one missing-source case that still delivers and ACKs.
- Criterion 5 → focused Claude wake registration, dispatch, durability and Claude hook suites only.

**Plan review:**
Agent technical review: independent clean-context GO on exact plan blob `9de00538` (commit `bcfd7d1a`), relayed by the project manager on 2026-11-25. Separate from owner approval.

**Approvals:**
The task owner approved the Claude compaction custody and wake fixes. The project manager limited this change to custody and authorized implementation after independent plan review. The verbatim approval is retained privately. This does not replace separate human result review.

**Exceptions:**
- rule: approval.high_risk_approval_recorded
  reason: The task owner directed deployment without further approval paperwork. Keep the verbatim approval private.
  scope: Public approval quote for the Claude compaction custody fix in PR 430 only.
  approver: repository owner
  expiry: 2026-12-09
  compensating_validation: The task owner explicitly approved this fix and its deployment. Retain the private approval and keep the independent review and CI requirements.

**State:**
Ready for review
<!-- Ready to implement | Blocked | Ready for review -->
<!-- agent-workflow:end -->

Implemented and independently reviewed. Earlier plans that skipped registration or compared credentials inside the hook were held. Neither is included in this change.

## Evidence

- Plan base: `origin/main` `5110d239`. Implementation base: `origin/main` `e543ccc6`.
- Rejected candidate `133f2a21` is preserved on a separate local branch and is not part of this branch.
- Candidate `133f2a21` (held, out of scope): its test failed on main and passed with the change. Focused suites: 443 passed, 4 skipped. That test stubs `relay_request`, so it does not cover the `/relay/turn` busy write. Not rerun.

## Idle-wake lane (separate, no implementation)

Question: does the registry have a safe, state-preserving credential refresh primitive? No.
- `register()` replaces an `idle`, `busy` or `unreachable` row with a new row whose state comes only from the request's `idle` flag. A refresh therefore always asserts idle or busy.
- For a `wake_inflight` row it keeps the fence and delivery and swaps `socket_path` and `token`. That is the only state-preserving path, and it drops `admission_id`.
- The HTTP route accepts only `idle` (and `intent_id`), with no "keep current state" mode. Every successful register also runs `complete_registration` (Relay `mark_active`) and bumps the generation.
- So a refresh that preserves state needs a new, reviewed primitive. Examples: a server-side "refresh credential, keep state" mode under the same intent compare-before-apply, or a generation-conditioned register. Either is a registry and route change.

## Separate follow-ups (not in this scope)

- SessionStart `clear` and `resume` also register busy while the session waits idle at the prompt, so wakes stay blocked until the first prompt.
- Which earlier missed wakes the compact cause explains is not yet established.

## Implementation

- `integrations/claude-code/hooks/session_start.py`: the Relay turn runs only when `source != "compact"`. On compact the response is empty, so nothing is rendered or ACKed and the hook falls through to the unchanged orientation path. Registration is unchanged.
- Tests are in `tests/test_agent_relay_hooks.py`, not `tests/test_claude_wake_registration.py` as planned, because the real-router hook harness (`client` fixture and hook-state isolation) lives there. No other scope change.
- Test method (compact node, amended after the first result review): the actual `session_start.py` runs as a subprocess with `source: compact`. It is bound, through the standard binding file and owner file, to the app's own durable Claude wake registry directory, and every hook HTTP call crosses a real loopback server into the real app router and Relay store over a loopback client address. Only `/query` is answered by the test with a known orientation block. The hook's own resolver, in the hook's environment, names the container the delivery is queued into. The ordinary pickup is the actual `user_prompt_submit.py` module in process over the same loopback router.
- `test_claude_session_start_compact_leaves_relay_custody_for_ordinary_pickup` (criteria 1–3): the compact hook exits 0 and makes exactly one wake registration over real HTTP: `idle=False`, HTTP 204, and the app registry row is `busy`. It posts `/query`; its stdout contains the known orientation block and not the queued payload. It makes no `/relay/*` request. The delivery stays `pending` with attempts 0. One UserPromptSubmit then emits the payload with exactly one `/relay/deliveries/ack`, and the delivery is `delivered` with attempts 1.
- `test_claude_session_start_non_compact_keeps_relay_turn[startup|resume|clear|empty|missing]` (criterion 4): one `idle=False` registration, one Relay turn and one ACK, as before.

## Verification

- RED on `e543ccc6` (first test version, test-only): the compact test failed with `assert ('delivered', 1) == ('pending', 0)`. The five non-compact cases passed (baseline preserved).
- GREEN on `2081be7c`: the new tests gave 6 passed.
- Amended compact node: with `session_start.py` temporarily restored to `origin/main` bytes it fails with `assert ('delivered', 1) == ('pending', 0)`. With the unchanged fix (blob `25622d92`) it gives 1 passed. Only this node was run for the amendment.
- Focused suites on `2081be7c`, before the test amendment (`tests/test_agent_relay_hooks.py`, `tests/test_claude_wake_registration.py`, `tests/test_claude_wake_dispatch.py`, `tests/test_claude_wake_durability.py`, `tests/test_claude_code_hooks`, `tests/test_claude_code_integration.py`): 717 passed, 4 skipped.
- Not run: broad suite, CI, live probe. No idle-wake claim.

## Result review

Agent technical review: independent non-implementer GO after checking the
amended test and unchanged product bytes. Exact receipt retained privately.
Reviewed revision: `a5debb0c4e94185aaaf5e950dde74ec7926619c8` on `e543ccc6`.
Verification adequacy: the actual compact subprocess registered busy over
HTTP, emitted orientation without Relay payload, and left the same
delivery pending at attempt zero. The next ordinary prompt emitted it and
ACKed it once. The amended test failed on baseline and passed with the
fix. The earlier 717 passes and four skips remain prior evidence.

Use the first hosted full run for whole-change qualification. Separate
human result review is pending. This review does not establish idle-wake
eligibility or authorize live rollout.
