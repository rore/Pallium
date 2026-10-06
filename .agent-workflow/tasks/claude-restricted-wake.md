<!-- agent-workflow:start -->
**Outcome:** A Claude session resumed without wake credentials cannot retain an earlier active wake registration, while normal-turn Relay delivery still works.

**Target:** Pallium Claude Code integration.

**Scope:** Exact-session Claude wake registration/revocation in the hook helper and focused hook/HTTP lifecycle tests. Qualify the final-answer quit/reopen History journey only if an isolated Claude 2.1.291+ binary is available; no product change for that journey without evidence.

**Constraints:** Preserve passive hook delivery, exact session/container ownership, durable intent ordering, and in-flight wake safety. Do not upgrade shared Claude, interrupt working chats, deploy independently, or edit protected behavior contracts.

**Completion criteria:** When a previously wake-registered Claude session resumes without socket/token credentials, the same exact-scope wake capability is no longer advertised ready or used for a native attempt; next-normal-turn delivery still claims and ACKs. Focused caller-surface and selector-required checks pass. Newer-Claude quit/reopen History outcome is reported as verified or explicitly unavailable.

**Requirement baseline:**
{"source":"relay-reply-099acbf1d06928c33cafe87f81ff0e96f4e10b761507714bfa235e3ead124cfd","outcome":"A Claude session resumed without wake credentials cannot retain an earlier active wake registration, while normal-turn Relay delivery still works.","scope":"Exact-session Claude wake registration/revocation in the hook helper and focused hook/HTTP lifecycle tests. Qualify the final-answer quit/reopen History journey only if an isolated Claude 2.1.291+ binary is available; no product change for that journey without evidence.","constraints":"Preserve passive hook delivery, exact session/container ownership, durable intent ordering, and in-flight wake safety. Do not upgrade shared Claude, interrupt working chats, deploy independently, or edit protected behavior contracts.","completion_criteria":"When a previously wake-registered Claude session resumes without socket/token credentials, the same exact-scope wake capability is no longer advertised ready or used for a native attempt; next-normal-turn delivery still claims and ACKs. Focused caller-surface and selector-required checks pass. Newer-Claude quit/reopen History outcome is reported as verified or explicitly unavailable."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Claude hook helper is a gray, shared runtime integration surface; durable wake revocation and turn admission interact, though no Redline red path or public API is intended. Moderate because lifecycle/error ordering needs caller-surface verification.

**Discovery:** Existing register_claude_wake returns False on absent/invalid socket or token and on encoded body overflow before writing a close intent. ClaudeWakeRegistry persists exact-scope registrations without expiry; a stale idle state can project availability=ready until successful turn admission marks busy. The existing close helper writes an exact-scope durable intent before loopback HTTP and the service reconciles intents each second. Close intentionally retains an in-flight reservation until ACK; failed close HTTP leaves an intent for later reconciliation, not immediate removal. UserPromptSubmit delivery uses relay_turn independently. Installed shared Claude is 2.1.278, below 2.1.291; no suitable newer binary was found on PATH or in the installed CLI directory. Relevant roadmap owner remains outside this worktree.

**Material assumptions:** Exact session/container identity remains available to the hook on restricted resume; disprove with isolated hook fixture, then stop and return to planning. Existing close intent/registry behavior safely fences any already-in-flight wake rather than cancelling uncertain transport; disprove with registry tests, then revise approach before editing further. A newer Claude binary is not available in this environment; if one is supplied in an isolated location, run the host/History witness without changing shared CLI.

**Plan:** In integrations/claude-code/hooks/common.py, validate exact session/container first; if socket/token credentials are absent, malformed, over-max, or cause encoded body overflow, call the existing close_claude_wake helper to publish an exact-scope closed intent and return False. Do not alter normal registration or Relay turn admission. In tests/test_claude_wake_registration.py, first reproduce stale idle readiness through hook/loopback HTTP and the Relay session read surface, then cover missing socket/token, empty/control/over-max credential, Unicode encoded-body overflow, invalid identity no-write, exact-scope isolation, failed close HTTP with later intent reconciliation, and next-normal-turn delivery/ACK. In tests/test_claude_wake_durability.py, verify accepted and uncertain in-flight reservations remain fenced through close/restart until exact ACK and do not become ready or trigger another native attempt. Run focused tests before/after, then selector-required checks once. Stop and re-plan if this needs a core/API change, violates in-flight fencing, or changes behavior contracts. Report newer-Claude lifecycle as unverified because only 2.1.278 is installed.

**Verification plan:** When an exact Claude session resumes without usable wake credentials or an oversized encoded body, activation no longer reports ready and native wake has no eligible capability → parameterized hook/HTTP regression with persistent registry and session read. When identity is invalid, no close intent is written; when close HTTP fails, the exact closed intent survives and subsequent reconciliation removes stale readiness without affecting a distinct scope → focused lifecycle regression. When an accepted or uncertain wake is already in-flight, close/restart retains the reservation until ACK and no second native attempt occurs → focused durability regression. When the next normal turn occurs without credentials, Relay claims/injects/ACKs independently → existing and added hook caller-surface test. All changed paths satisfy workflow/test selection → agent-workflow check, redline check, scripts/test-plan.py --base origin/main and its reported checks. Final answer quit/reopen on Claude 2.1.291+ → isolated witness only if suitable binary becomes available; otherwise explicit version limitation.

**Plan review:** Agent technical review: collaboration:/root/claude_wake_plan_review (2026-10-06). Reviewer accepted Elevated/Moderate and the existing-helper approach, requested encoded-overflow and in-flight coverage, then approved the revised plan with no further findings.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Initial task context and baseline recorded before code edits. Intended source is integrations/claude-code/hooks/common.py; intended test files are tests/test_claude_wake_registration.py and tests/test_claude_wake_durability.py. Discovery confirmed an existing exact-scope close helper and one-second intent recovery; no core/API change is planned. Independent reviewer found encoded-overflow and in-flight proof gaps; revised plan covers both and was approved before implementation.

The new hook-to-loopback HTTP regression first failed on the actual contract: after an idle registration and missing socket credentials, public `/relay/sessions` still reported `activation.availability=ready`. Earlier fixture setup attempts used a non-loopback TestClient and returned 403; corrected to an explicit loopback peer before recording this pre-fix failure.

The shared helper now publishes the existing exact-scope close intent for absent, invalid, or encoded-overflow credentials. The new public activation regression initially passed across seven unusable credential cases; it was expanded to nine. Updated the prior encoded-size test to expect a credential-free close intent instead of no request. Subsequent coverage added invalid identity, offline close recovery, passive hook delivery, and in-flight reservation ordering.

All planned behavior coverage is now implemented. Parameterized hook/HTTP checks cover missing, empty, control, over-max, and encoded-overflow credentials; invalid identities cause no close; failed close HTTP leaves an exact intent for later recovery; a restricted normal prompt still injects and ACKs a pending delivery. Accepted and uncertain in-flight attempts survive close/restart without a second native attempt and become non-ready after the normal-turn ACK. Independent result review requested one more qualification test: if close-intent publication itself fails, no unsafe HTTP close is sent and an old registration remains ready until a later successful retry removes it. That regression passes. The affected Claude registration, durability, and Relay hook files passed: 232 tests. The whole-change selector reports the full lane (`python -m pytest tests/ -x -q`); no newer installed Claude binary is available for a live quit/reopen witness.

Verification found one unrelated existing baseline failure in the selector-required full lane: `tests/test_codex_retained_wake.py::test_session_start_lock_budget_claims_emits_and_acks_once[user_prompt_submit-released]` measures a timeout of 1.821s against a 1.8s ceiling. `--lf` repeated it at 1.831s; the exact node on clean main at 3093df26 repeated it at 1.807s. This task does not change Codex code/tests, and the protected behavior must not be weakened to force green. State is Blocked pending root's CI/review decision on the baseline failure; do not claim full-lane success.

## Evidence

Focused affected files: `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest tests/test_claude_wake_registration.py tests/test_claude_wake_durability.py tests/test_agent_relay_hooks.py -q -n 0` — 232 passed.

`python scripts/test-plan.py --base origin/main` selected `python -m pytest tests/ -x -q` (full lane). Full lane: 1,156 passed, 2 skipped, 477 deselected, 1 xfailed, then the Codex timing node above failed; `--lf` failed again. The same exact node fails on clean main (3093df26), proving it is not introduced by this diff. No 2.1.291+ Claude binary was found; shared `claude --version` is 2.1.278.

Import-boundary check passed. Redline found no boundary violation and detected Elevated risk; final-state Agent Workflow check was clean with that verdict. The ordinary local wrapper did not provide a Redline verdict, so the checker was rerun with CI-equivalent generated boundary and Redline inputs. The focused suite was rerun after the publication-failure regression; the full lane was not rerun after that test-only addition because its known clean-main timing failure had already been independently reproduced.

## Result review

Independent technical review: collaboration:/root/claude_wake_result_review (2026-10-06), on the source change and focused tests. Verdict: no blocking correctness findings; exact identity, scoped intent ordering, in-flight fencing, and passive hook delivery are preserved. Reviewer requested the publication-failure/retry regression, which was added and passed. The limitation is explicit: when the close intent cannot be published because of binding, lock, or storage failure, the prior capability can remain ready until a later successful hook retry; bypassing the intent would violate ownership and durability ordering. Completion remains blocked by the selector-required full-lane baseline failure; root task owner must decide that follow-up before release. The Claude 2.1.291+ host witness is separately unavailable and reported as such, per the original scope.
