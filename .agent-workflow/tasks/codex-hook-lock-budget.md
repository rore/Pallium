<!-- agent-workflow:start -->
**Outcome:** A Codex Relay hook that encounters brief session-lock contention can still claim and ACK its scoped delivery within the hook budget.

**Target:** Pallium Codex hook integration.

**Scope:** integrations/codex/hooks/common.py, integrations/codex/hooks/user_prompt_submit.py, tests/test_codex_retained_wake.py, tests/test_agent_relay_hooks.py, roadmap/features/add-wake-first-relay-delivery.md, and this Work Record.

**Constraints:** Preserve short default waits for unrelated identity writes, exact scope, delivery/ACK ordering, existing host and hook budgets, and the emission/ACK reserve. Do not change native wake retries, runtime configuration, Claude behavior, protected behavior contracts, or infrastructure. Do not claim the historical Oct 4 missed wake is explained or fixed.

**Completion criteria:** When a lock releases within the remaining reserved hook budget, the actual Codex SessionStart hook shall make the temporary HTTP Relay claim, emit the payload, and ACK once; when the lock remains held or the budget is exhausted, it shall make no late Relay call, remain bounded, preserve exact scope, and leave the delivery pending. Consecutive hooks shall not duplicate delivery.

**Requirement baseline:**
{"source":"task instructions and root-confirmed independent temporary HTTP Relay reproduction","outcome":"A Codex Relay hook that encounters brief session-lock contention can still claim and ACK its scoped delivery within the hook budget.","scope":"integrations/codex/hooks/common.py, tests/test_codex_retained_wake.py, roadmap/features/add-wake-first-relay-delivery.md, and this Work Record.","constraints":"Preserve short default waits for unrelated identity writes, exact scope, delivery/ACK ordering, existing host and hook budgets, and the emission/ACK reserve. Do not change native wake retries, runtime configuration, Claude behavior, protected behavior contracts, or infrastructure. Do not claim the historical Oct 4 missed wake is explained or fixed.","completion_criteria":"When a lock releases within the remaining reserved hook budget, the actual Codex SessionStart hook shall make the temporary HTTP Relay claim, emit the payload, and ACK once; when the lock remains held or the budget is exhausted, it shall make no late Relay call, remain bounded, preserve exact scope, and leave the delivery pending. Consecutive hooks shall not duplicate delivery."}

**Behavior changes:** [{"target":"task-context.scope","classification":"equivalent","before":"integrations/codex/hooks/common.py, tests/test_codex_retained_wake.py, roadmap/features/add-wake-first-relay-delivery.md, and this Work Record.","after":"integrations/codex/hooks/common.py, integrations/codex/hooks/user_prompt_submit.py, tests/test_codex_retained_wake.py, tests/test_agent_relay_hooks.py, roadmap/features/add-wake-first-relay-delivery.md, and this Work Record.","reason":"Independent review identified the exact-wake caller's existing timeout reset; forward its existing budget through the same bounded operation and adjust existing timeout-cap assertions. Same delivery, reserve, deadline, and duplicate-protection requirements; no new product behavior or changed acceptance criteria."}]

**Risk:** Elevated

**Complexity:** Simple

**Reason:** `integrations/codex/hooks/common.py` is gray and sets the risk floor to Elevated. The correction is a single bounded behavior change with existing caller-surface fixtures, so complexity is Simple.

**Discovery:** The root assistant's independent reproduction reports that an unlocked SessionStart hook receives a 200 response and claims/ACKs once with a 1,104-character payload; with the per-session lock held for 300ms, the pin and Relay acquisitions each spend about 101ms, no HTTP request occurs, and the delivery remains at attempts=0 without an error. `integrations/codex/hooks/common.py::_acquire_session_lock` caps every wait at 100ms, including `relay_turn`; its existing `HookDeadline` supports a caller budget and reserve. Codex `session_start.py` currently starts an eight-second hook with a one-second host reserve, then computes a request timeout with another one-second reserve. Codex `relay_turn` accepts an optional `deadline` but currently acquires the session lock without passing a turn-specific budget and forwards the same `timeout` to each HTTP request. The real-HTTP actual-hook fixture is in `tests/test_codex_retained_wake.py`. Claude Code has a parallel lock helper capped at 100ms and a `relay_turn` without Codex's `wake_delivery_id` argument; `tests/test_hook_common_parity.py` does not enforce these signatures or lock semantics. The scoped fix can remain Codex-only. The observed behavior establishes a lock-contention failure class. The separate Oct 4 record says `native_submitted` with a missing payload; this reproduction does not prove that incident's cause. The PR #282 queue `TimeoutExpired` evidence is also separate.

**Material assumptions:** The existing real-HTTP fixture in `tests/test_codex_retained_wake.py` can deterministically hold and release the same session lock while invoking the actual SessionStart hook, and can observe claim/ACK and pending attempts through the fixture's Relay HTTP routes. If it cannot model timeout and late-call boundaries reliably, stop and revise the plan before widening test scope.

**Plan:** Preserve `_acquire_session_lock`'s default short wait for identity writes and use the existing hook deadline only for the Codex Relay turn path. Derive one bounded operation deadline from the supplied Relay deadline (when present), the global hook safe time, and the remaining request timeout; reserve time for HTTP request/claim, emission, and ACK as already computed by the caller. Pass only the remaining budget to each lock acquisition and HTTP request so lock delay cannot be followed by a fresh full timeout. Leave the Claude helper unchanged after checking its separate signature and call sites. Add actual-SessionStart HTTP regressions to `tests/test_codex_retained_wake.py` for brief release and one ACK, permanent contention with no claim, consecutive hook idempotence, and exhausted budget with no late request; retain exact-scope and attempts=0 assertions. Update the roadmap's current execution status with this demonstrated failure class and bounded correction, explicitly leaving the historical incident cause unproved. Stop and return to planning if satisfying the tests requires changing wake/native retry policy, caller budgets, Claude behavior, or scope isolation. Do not edit code before independent plan review.

**Verification plan:** Brief contention released within budget shall recover through actual SessionStart HTTP claim, emission, and one ACK → focused real-hook regression. Permanent contention, exhausted budget, and subsequent/consecutive hooks shall produce no late call or duplicate and leave delivery pending as specified → same caller-surface regression cases. Existing Codex hook lifecycle and deadline coverage shall remain green → affected Codex hook test files. Whole-change scope and final redline classification shall pass → `python scripts/test-plan.py --base origin/main`, Agent Workflow check, and Redline check.

**Plan review:** Agent technical review: `/root/hook_boundary_review` (accepted; disposition relayed by `/root`). Reviewer requires one absolute effective deadline from the passed Relay deadline, global hook safe time, and caller timeout; recompute remaining budget before each lock/request, issue no request at zero, and preserve the caller's emission/ACK reserve. The 100ms default for unrelated state writes and deterministic deadline clock remain required.

**Approvals:** Not required at this risk level.

**Exceptions:** —

<!-- Blocked -->
**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Plan accepted by clean-context reviewer `/root/hook_boundary_review`, as relayed by `/root`. Current branch: `feat/codex-hook-lock-budget`. Implement the accepted scope below; no code edits preceded review.

Root took over implementation after planning to shorten the iteration; the planning worker was interrupted before code edits. Added the actual SessionStart regression first: baseline 1 failed / 2 passed, with the released-lock case reproducing scope-only output. The bounded lock/request correction then passed all three cases, including real ACK and a subsequent hook with no duplicate payload. Added deterministic caller/global/provided deadline cases for lock and bootstrap exhaustion. Affected hook validation and independent result review are in progress. No live service, configuration, or messages changed.

Affected validation: 377 passed, two existing parameter cases expected exactly 0.75 seconds rather than the remaining timeout after lock/state work. Updated that assertion to require a positive timeout no greater than 0.75 seconds, preserving the short-budget contract. This mechanical fixture adjustment adds `tests/test_agent_relay_hooks.py` to scope and was sent to the independent reviewer; no protected behavior contract changed.

Result review found that the exact UserPromptSubmit wake callback rebuilds its own two-second budget rather than respecting remaining Relay time. Proposed narrow plan adjustment: compute its existing budget once at the caller, pass it to `relay_turn`, and forward remaining timeout/deadline through the measured callback. This removes duplicate timing logic and retains the existing two-second cap and emission/ACK reserve. Independent review of that scope adjustment is pending; the full-suite run was interrupted before completion to avoid validating a known incomplete revision.

The independent reviewer accepted the exact-wake caller adjustment before its edit. Scope now includes `integrations/codex/hooks/user_prompt_submit.py`; its existing two-second ceiling covers both lock wait and HTTP instead of restarting in the callback. Ordinary prompts keep the 0.75-second cap. The actual-hook HTTP test now covers SessionStart and exact UserPromptSubmit, including positive held-lock waits, post-lock timeout reduction, actual ACK, and no duplicate on a second hook. Historical incident attribution remains unproved.

## Result review

Agent technical review: `/root/hook_boundary_review`, final diff and callback compatibility adjustment accepted.

Reviewed revision: `539b1f2b` (production, tests, and roadmap unchanged from the independently reviewed working diff).

Verification adequacy: actual hook/HTTP release, contention, exhaustion, ACK and duplicate regressions plus deterministic deadline checks and the final 5,980-test green full run cover the scoped correction. Historical incident attribution and baseline readiness flakiness remain unproved and are not completion claims.

Post-commit workflow validation has no blocking findings; its only advisory is that the already-written and reviewed Work Record was committed together with code in `539b1f2b`. The record and independent plan review preceded edits, as the implementation history above records.

Publication blocker: automatic approval review rejected the combined metadata-commit/push command before execution because publishing this exact branch's code and Work Record to public `https://github.com/rore/Pallium.git` requires direct human authorization for that payload and destination. No push or PR exists, and no installed change occurred. Do not retry or publish indirectly. Root must obtain that exact approval, then use normal automatic review to push `feat/codex-hook-lock-budget`, create/attach the prepared PR, verify CI and review threads, merge, synchronize clean clones, and use the installed restart wrapper plus health checks. The implementation and all final tests are complete; no rerun is required absent a finding or code change.

Agent result review: `/root/hook_boundary_review` accepted the corrected diff. The reviewer verified one deadline across lock and requests, existing output/ACK reserve and timeout caps, short defaults elsewhere, both actual hook paths, real ACK and duplicate prevention, and deterministic lock/bootstrap exhaustion. The exact-wake budget finding and test-output expectation finding were addressed; no concrete findings remain. Affected validation: 380 passed initially; two new negative UserPromptSubmit cases were corrected to assert the existing block output, then both passed on the exact failed-test rerun. Full-suite validation remains in progress.

Broader validation caught an additional timeout-only custom-callback compatibility issue in the existing `test_no_hook_completion_preserves_delivery_until_real_hook_recovery`. Removing the callback-identity shortcut preserved its established interface; the exact test failed before and passed afterward without test edits. Explicit-deadline SessionStart and exact-wake callers retain the shared deadline. Two earlier full runs stopped with 1,327 and 1,549 passing tests respectively. The unchanged readiness test `test_codex_wake_evidence_is_bounded_and_definition_matched` also failed on clean baseline `ae40fc8ea945ae4fef8c20708543d995dffa999c`; the other setup failure and a separate Windows directory-rename failure passed isolated reruns. These baseline/environment failures are not claimed fixed. Final full non-slow validation runs without early exit to collect complete evidence.

Final verification: `python -m pytest tests/ -q` passed 5,980 tests, with 34 skipped and 2 expected failures in 338.80 seconds (configured four workers). The selector required this full non-slow lane. Import boundaries passed; fresh Redline is GRAY with no boundary violations or additional checkpoints. Agent Workflow check was clean. Independent reviewer `/root/hook_boundary_review` also accepted the final timeout-only callback compatibility adjustment. Next action: root publication, CI/review resolution, merge, synchronized stable installation, and health checks; no broader reliability or historical-cause claim.

## Evidence

- Root assistant's independent temporary HTTP Relay reproduction and task acceptance criteria.
- `integrations/codex/hooks/common.py`, `integrations/codex/hooks/session_start.py`, and `integrations/claude-code/hooks/common.py` inspected for current lock, deadline, and signature behavior.
- `tests/test_codex_retained_wake.py` inspected for its actual-hook and temporary HTTP Relay fixture.
- `tests/test_hook_common_parity.py` inspected; no lock-acquisition or `relay_turn` parity assertion is present.
