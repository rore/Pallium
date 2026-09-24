# Bound exact Codex Relay wake hook timeout

<!-- agent-workflow:start -->
**Outcome:** An exact Codex Relay wake tolerates ordinary sub-two-second Relay turn latency without falling into claim-lease recovery.

**Target:** Pallium Relay Codex hook.

**Scope:** `integrations/codex/hooks/user_prompt_submit.py`, focused hook/Relay tests, Relay roadmap, and this Work Record.

**Constraints:** Ordinary user prompts keep their 0.75-second Relay request cap. Keep the 8-second host hook budget and one-second reserve, exact wake validation, claim/ACK, native wake reservations/retries, scope, model, and effort unchanged. A slower response remains fail-closed and recoverable; no duplicate processing.

**Completion criteria:** A delayed exact wake response below the new bounded cap emits and ACKs once through the actual hook/HTTP path; a response beyond it emits nothing and retains safe lease-expiry recovery. Ordinary and malformed/noncanonical prompts do not gain the longer request budget. The full hook stays within its host deadline.

**Requirement baseline:** {"source":"manager-task-01a07bef-18c8-71b2-89ab-c0cbe91e73ad","outcome":"An exact Codex Relay wake tolerates ordinary sub-two-second Relay turn latency without falling into claim-lease recovery.","scope":"`integrations/codex/hooks/user_prompt_submit.py`, focused hook/Relay tests, Relay roadmap, and this Work Record.","constraints":"Ordinary user prompts keep their 0.75-second Relay request cap. Keep the 8-second host hook budget and one-second reserve, exact wake validation, claim/ACK, native wake reservations/retries, scope, model, and effort unchanged. A slower response remains fail-closed and recoverable; no duplicate processing.","completion_criteria":"A delayed exact wake response below the new bounded cap emits and ACKs once through the actual hook/HTTP path; a response beyond it emits nothing and retains safe lease-expiry recovery. Ordinary and malformed/noncanonical prompts do not gain the longer request budget. The full hook stays within its host deadline."}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** The integration hook is an unclassified behavioral surface; tests, roadmap, and Work Record are blue. No API, persistence, or native queue contract changes.

**Discovery:** The exact wake path calls `/relay/turn` with a fixed 0.75-second cap under an 8-second hook deadline with one-second host reserve. In a synthetic actual-hook/loopback HTTP probe, committed claims with response-ready times 470 and 617 ms emitted and ACKed, while 770 ms returned unavailable without emission. The rotated service log has 83 slow turn calls, 11 at least 750 ms and three at least 2 seconds; these are not all exact wakes. Exact correlated lease-expiry recovery already shipped in PR #198; native uncertain CLI admission remains separate and unchanged.

**Material assumptions:** The exact internal wake regex is the sole authority for the longer budget. A caller-surface test showing an ordinary or malformed prompt uses it invalidates the plan. The exact final request can reserve one second of the hook safe-work budget for emission/ACK; a measured test exceeding the eight-second host deadline invalidates the plan.

**Plan:** Keep `relay_turn(timeout=0.75)` for bootstrap and scope replay. In the measured request wrapper, only the final request carrying the regex-validated exact wake ID gets a cap of `min(2.0, remaining_safe_time() - 1.0)`; all other requests retain 0.75 seconds. The existing global hook deadline still clamps the request. Add real loopback HTTP + actual hook boundary tests with isolated synthetic data below/above two seconds, and ordinary/noncanonical cap checks. Preserve the existing loss/recovery regression. Update the roadmap as bounded mitigation, not a historical root-cause claim or complete reliability.

**Verification plan:** Actual HTTP/hook delayed exact wake below two seconds emits and ACKs once; over two seconds emits nothing and safely recovers → focused caller-surface lifecycle test. Ordinary/noncanonical prompts remain at 0.75 seconds → hook request-cap tests. Full hook host budget → measured test. Then affected subsystem files, one repository suite, workflow/Redline check, review, and PR CI.

**Plan review:** Clean-context Luna review approved revised exact-final-request budget with one-second emission/ACK reserve; see `## Plan review`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Planning only; no hook code edited.

## Plan review

The first plan was rejected because elay_turn may make bootstrap and scope-replay calls, each with its own timeout. The approved revision extends only the final outgoing request whose body carries the regex-validated exact wake delivery ID. Earlier calls retain 0.75 seconds. The cap also leaves one second inside the hook safe-work budget for emission and ACK. The reviewer required a real loopback HTTP/hook regression and no response-loss retry.
