# Keep exact Codex claims out of background wake admission

<!-- agent-workflow:start -->
**Outcome:** An exact Codex hook claim and its ACK can finish while background OpenCode wake work occupies the wake admission slots.

**Target:** `POST /relay/turn` on `a1401448fc49fd8756421882bc824da5a57fdd05`; reviewed plan and retained RED on `5d33ed575a264cbe31f38991dbc54dd16b2dbd5c`.

**Scope:** Use the existing durable Relay runner for the composed exact Codex turn in `api/routes.py`. Reuse the regression and controls in `tests/test_relay_capacity_isolation.py` and `tests/test_codex_wake.py`, and record results here.

**Constraints:** Preserve the single composed operation, claim deadline and errors, replay behavior, shared capacity, and shutdown ownership. No dependency on PR #375, retry tuning, product changes outside the exact Codex branch, repeated baseline run, or installed operations. The manager may publish this independently reviewed exact candidate for ordinary PR validation; merge requires the final review and CI gates.

**Completion criteria:** The two retained timeout cases pass with the real hook and unchanged deadline while poll or projection remains held. The exact claim and ACK settle once; the duplicate exact request returns no delivery. Existing ACK-only and no-hold controls, timing, one-admission and cancellation checks pass.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"An exact Codex hook claim and its ACK can finish while background OpenCode wake work occupies the wake admission slots.","scope":"Use the existing durable Relay runner for the composed exact Codex turn in `api/routes.py`. Reuse the regression and controls in `tests/test_relay_capacity_isolation.py` and `tests/test_codex_wake.py`, and record results here.","constraints":"Preserve the single composed operation, claim deadline and errors, replay behavior, shared capacity, and shutdown ownership. No dependency on PR #375, retry tuning, product changes outside the exact Codex branch, repeated baseline run, publication, or installed operations.","completion_criteria":"The two retained timeout cases pass with the real hook and unchanged deadline while poll or projection remains held. The exact claim and ACK settle once; the duplicate exact request returns no delivery. Existing ACK-only and no-hold controls, timing, one-admission and cancellation checks pass."}

**Behavior changes:**
[{"target":"task-context.constraints","classification":"equivalent","before":"Preserve the single composed operation, claim deadline and errors, replay behavior, shared capacity, and shutdown ownership. No dependency on PR #375, retry tuning, product changes outside the exact Codex branch, repeated baseline run, publication, or installed operations.","after":"Preserve the single composed operation, claim deadline and errors, replay behavior, shared capacity, and shutdown ownership. No dependency on PR #375, retry tuning, product changes outside the exact Codex branch, repeated baseline run, or installed operations. The manager may publish this independently reviewed exact candidate for ordinary PR validation; merge requires the final review and CI gates.","reason":"Advance from the local implementation phase to ordinary PR validation under the existing bug-fix and publication direction. Product scope, requirements and installed-environment constraints are unchanged."}]

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** High

**Complexity:** Moderate

**Reason:** `api/routes.py` is red-zone and triggers `api-review`. The edit is one line; admission fairness and lifecycle evidence span the hook, route, and shared runner.

**Discovery:** On current main, the exact Codex turn runs snapshot, service claim, callbacks and activation projection in one worker admitted through both the three-slot wake gate and four-slot Relay limiter. Other runtimes use their existing paths. The ACK mutation already uses the durable runner. Retained manager RED on this base and regression test blob `6b9d22f204ca5226437cd9071bd1c3d00a80eff4`: two real hook timeouts at 1,997 and 2,002 ms with poll/projection held; four controls passed.

**Material assumptions:** Background wake work can take at most three normal slots; the fourth remains shared among durable operations. Exact claims can now queue against ACK, other durable calls, or each other. There is no new priority, reservation per runtime, or guarantee under durable saturation or a blocked worker. The same tracked worker wrapper handles cancellation and drain, with no nested runner call in the exact branch.

**Plan:** Obtain independent plan and architecture review and record the human approval required for this High-risk plan before a product edit. Reuse `7e39be63`'s exact Codex runner switch and its three-file delta adapted to current main; use the manager's already-adapted capacity test without redoing RED. Point both existing exact-turn runner doubles at `relay_runner`: the refusal test and the current-main timing test that models 0 and 500 ms of admission delay. Keep all assertions. Keep snapshot, claim, callbacks, projection and HTTP mapping in the same tracked call. Stop if current callers introduce a nested wait or require a new capacity/fairness policy.

**Verification plan:**
- Exact hook progress, original cutoff, one claim and ACK, no second delivery → six cases of `test_shared_wake_admission_preserves_ack_under_poll_and_projection`, reusing the retained two RED cases.
- One durable admission, same worker execution and phase failure behavior → `test_exact_codex_turn_uses_one_admission_and_preserves_phase_failures`.
- Deadline, route and worker timing, pre-entry failure and replay semantics → existing exact turn timing and expiry nodes in `tests/test_codex_wake.py`.
- Shared capacity, queued/started cancellation and shutdown ownership → existing limiter fairness test and `test_operation_tracking_covers_cancellation_and_failure_boundaries`.
- Exact candidate and broader gates → record file hashes, focused receipts, and whole-change selector/workflow results; report full qualification status separately before release.

**Plan review:** Agent technical review: independent architect GO on plan `eba68673eb5444cadb07da858a387b45f367c98f` at `5d33ed57`, applicable through `a1401448`, confirmed by the task owner. The review covers the existing durable runner for the composed exact Codex claim only, both runner doubles, and unchanged tracking and assertions. The PR API checkpoint remains separate.

**Approvals:** Approved by user in the original Work Record (timestamp unavailable): [verbatim approval and scope](https://github.com/rore/Pallium/blob/e7ee020bfd2a6fa9fbc207d3190887cee1cc64eb/.agent-workflow/tasks/relay-reconnect-outcome.md). That approval explicitly covers the `7e39be63` runner switch, its tests and the exact timing-fixture correction. The standing reliability direction authorizes ordinary PR publication. PR-time review remains separate.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Fast-forwarded to `a1401448` after verifying that the reviewed route,
runners, fixtures, tests, and dependency declarations match `5d33ed57`.
Apply only the exact Codex runner switch in `api/routes.py`, retarget the
two exact-turn doubles in `tests/test_codex_wake.py`, and reuse the
retained regression blob in `tests/test_relay_capacity_isolation.py`.

## Evidence

- Candidate on `a1401448`: route blob `2a2beba26506ca10714f5baebd0a861b32c0096c`,
  Codex test blob `c0e5f123a0548a5cc384200f63f3756caf9b76d8`, and capacity
  test blob `6b9d22f204ca5226437cd9071bd1c3d00a80eff4`. Before and after
  hashes match. The only product change selects the existing durable
  runner for the single composed exact Codex turn.
- Focused Windows run: **36 passed** in 34.40 seconds. All six
  claim/ACK capacity cases passed, including both retained RED cases,
  held poll and held projection. They check the original hook deadline,
  one claim and ACK, the delivered row, and an empty duplicate claim.
  All twelve one-admission/phase cases passed. The 0/500 ms timing,
  pre-entry failure, expiry, safe error, callback, limiter fairness,
  and cancellation/drain controls also passed.
- The original RED was not rerun. Focused log, JUnit, and hash receipt
  are retained locally. The whole-change selector requires the full
  lane. Import boundaries and `git diff --check` passed. Agent Workflow
  had no blocking findings; `api-review` remains open at PR time.
  Full qualification remains open.

## Result review

Agent technical review: The independent architect gave result and
API GO for ordinary PR validation in the exact recipient's native
turn. No source correction was requested.

Reviewed revision: `a1401448` plus route `2a2beba2`, Codex timing and
refusal tests `c0e5f123`, and capacity tests `6b9d22f2`; source
composition checked through `cfb5b5ae`.

Verification adequacy: The identical retained RED timed out in both
held-work cases. All 36 focused cases passed on the candidate, including
claim and ACK within the original deadline and the duplicate-empty
readback. Cancellation and shutdown still use the existing tracked
runner. The fourth worker stays shared. This is evidence for ordinary
CI, with no whole-change or installed qualification claim.
