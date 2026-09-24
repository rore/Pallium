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

**Material assumptions:** The exact internal wake regex is the sole authority for the longer budget. A caller-surface test showing an ordinary or malformed prompt uses it invalidates the plan. A derived deadline must bound the hook main thread's wait for the exact HTTP response, including fragmented reads, while leaving one second for emission/ACK. The daemon HTTP worker may continue until hook process exit; no retry is issued. A fragmented-response test disproving bounded caller wait returns to planning.

**Plan:** Keep `relay_turn(timeout=0.75)` for bootstrap and scope replay. In the measured wrapper, only the final outgoing request carrying the regex-validated exact wake ID gets `min(2.0, remaining_safe_time() - 1.0)` and a derived HookDeadline of that elapsed duration, passed to relay_request so the caller stops waiting even if the socket read trickles; all earlier/ordinary requests retain 0.75 seconds. Add isolated actual-hook/loopback HTTP tests for sub-two-second success, slow pre-response failure, fragmented-read failure, and ordinary/noncanonical caps. Preserve existing lease recovery and native fence behavior. Roadmap states bounded mitigation only.

**Verification plan:** Actual HTTP/hook delayed exact wake below two seconds emits and ACKs once; over two seconds emits nothing and safely recovers → focused caller-surface lifecycle test. Ordinary/noncanonical prompts remain at 0.75 seconds → hook request-cap tests. Full hook host budget → measured test. Then affected subsystem files, one repository suite, workflow/Redline check, review, and PR CI.

**Plan review:** Fresh clean-context Luna review approved the bounded caller-wait revision; see `## Plan review`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

The Codex hook extends only the final validated exact-delivery HTTP request to at most two seconds, reserving one safe-work second for context emission and ACK. Earlier bootstrap/scope-replay requests and ordinary prompts stay at 0.75 seconds. Native reservations, retry, claim, and ACK semantics are unchanged. RW-034 in the roadmap separates this prevention from the upstream native-admission blocker. The actual hook/HTTP test delays the response after claim commit; ordinary and malformed prompt checks retain the short cap.

## Evidence

Focused loopback and prompt-cap nodes: 4 passed in 6.93s. After the independent review requested a whole-hook elapsed assertion, the same four nodes passed in 6.18s. The 1.15-second post-claim response delivered and ACKed once; the 2.2-second response failed closed with trace state claimed and attempts=1. Both complete hook.main() within its seven-second active budget.
Affected hook/Codex wake subsystem: 196 passed in 46.73s. Existing exact claim lease-expiry recovery node: 1 passed in 3.47s. Repository suite before the final test-only elapsed assertion: 5294 passed, 34 skipped, 2 xfailed in 266.18s; no second full-suite run was done for that assertion.
The first apply_patch edit worked, but a later invocation failed with Windows 1385. Exact file-scoped PowerShell replacements were used thereafter. One escaped-newline replacement error was caught by py_compile and corrected before tests.

## Plan review

The first plan was rejected because relay_turn may make bootstrap and scope-replay calls, each with its own timeout. The approved revision extends only the final outgoing request whose body carries the regex-validated exact wake delivery ID. Earlier calls retain 0.75 seconds. The cap leaves one second inside the hook safe-work budget for emission and ACK. The reviewer required a real loopback HTTP/hook regression and no response-loss retry. PR #238 review then found a trickled response could outlast the socket timeout. A fresh clean-context review approved using the existing HookDeadline to bound the hook caller wait, while explicitly acknowledging its daemon HTTP read can continue until process exit; no retry or cancellation claim is made.

## Result review

Independent clean-context review found one P2 evidence gap: the loopback test did not assert the total hook runtime. The test now measures hook.main() through request, emission/ACK or fail-closed exit and requires under seven seconds; focused rerun passed. No other actionable issue was found.
