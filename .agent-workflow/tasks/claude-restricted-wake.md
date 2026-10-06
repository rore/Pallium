<!-- agent-workflow:start -->
**Outcome:** A Claude session resumed without wake credentials cannot retain an earlier active wake registration, while normal-turn Relay delivery still works.

**Target:** Pallium Claude Code integration.

**Scope:** Exact-session Claude wake registration/revocation in the hook helper and focused hook/HTTP lifecycle tests. Qualify the final-answer quit/reopen History journey only if an isolated Claude 2.1.291+ binary is available; no product change for that journey without evidence.

**Constraints:** Preserve passive hook delivery, exact session/container ownership, durable intent ordering, and in-flight wake safety. Do not upgrade shared Claude, interrupt working chats, deploy independently, or edit protected behavior contracts.

**Completion criteria:** When a previously wake-registered Claude session resumes without socket/token credentials, the same exact-scope wake capability is no longer advertised ready or used for a native attempt; next-normal-turn delivery still claims and ACKs. Focused caller-surface and selector-required checks pass. Newer-Claude quit/reopen History outcome is reported as verified or explicitly unavailable.

**Requirement baseline:**
{"source":"relay-reply-099acbf1d06928c33cafe87f81ff0e96f4e10b761507714bfa235e3ead124cfd","outcome":"A Claude session resumed without wake credentials cannot retain an earlier active wake registration, while normal-turn Relay delivery still works.","scope":"Exact-session Claude wake registration/revocation in the hook helper and focused hook/HTTP lifecycle tests. Qualify the final-answer quit/reopen History journey only if an isolated Claude 2.1.291+ binary is available; no product change for that journey without evidence.","constraints":"Preserve passive hook delivery, exact session/container ownership, durable intent ordering, and in-flight wake safety. Do not upgrade shared Claude, interrupt working chats, deploy independently, or edit protected behavior contracts.","completion_criteria":"When a previously wake-registered Claude session resumes without socket/token credentials, the same exact-scope wake capability is no longer advertised ready or used for a native attempt; next-normal-turn delivery still claims and ACKs. Focused caller-surface and selector-required checks pass. Newer-Claude quit/reopen History outcome is reported as verified or explicitly unavailable."}

**Risk:** High

**Complexity:** Moderate

**Reason:** In the combined branch, the Codex reservation schema is a High-risk persistence surface. The Claude hook lifecycle change remains exact-session scoped and independently tested; the full combined change received a clean-context technical GO. Complexity remains Moderate because lifecycle/error ordering spans hook, HTTP, and durable state.

**Discovery:** Existing register_claude_wake returns False on absent/invalid socket or token and on encoded body overflow before writing a close intent. ClaudeWakeRegistry persists exact-scope registrations without expiry; a stale idle state can project availability=ready until successful turn admission marks busy. The existing close helper writes an exact-scope durable intent before loopback HTTP and the service reconciles intents each second. Close intentionally retains an in-flight reservation until ACK; failed close HTTP leaves an intent for later reconciliation, not immediate removal. UserPromptSubmit delivery uses relay_turn independently. Installed shared Claude is 2.1.278, below 2.1.291; no suitable newer binary was found on PATH or in the installed CLI directory. Relevant roadmap owner remains outside this worktree.

**Material assumptions:** Exact session/container identity remains available to the hook on restricted resume; disprove with isolated hook fixture, then stop and return to planning. Existing close intent/registry behavior safely fences any already-in-flight wake rather than cancelling uncertain transport; disprove with registry tests, then revise approach before editing further. A newer Claude binary is not available in this environment; if one is supplied in an isolated location, run the host/History witness without changing shared CLI.

**Plan:** In integrations/claude-code/hooks/common.py, validate exact session/container first; if socket/token credentials are absent, malformed, over-max, or cause encoded body overflow, call the existing close_claude_wake helper to publish an exact-scope closed intent and return False. Do not alter normal registration or Relay turn admission. In tests/test_claude_wake_registration.py, first reproduce stale idle readiness through hook/loopback HTTP and the Relay session read surface, then cover missing socket/token, empty/control/over-max credential, Unicode encoded-body overflow, invalid identity no-write, exact-scope isolation, failed close HTTP with later intent reconciliation, and next-normal-turn delivery/ACK. In tests/test_claude_wake_durability.py, verify accepted and uncertain in-flight reservations remain fenced through close/restart until exact ACK and do not become ready or trigger another native attempt. Run focused tests before/after, then selector-required checks once. Stop and re-plan if this needs a core/API change, violates in-flight fencing, or changes behavior contracts. Report newer-Claude lifecycle as unverified because only 2.1.278 is installed.

**Verification plan:** When an exact Claude session resumes without usable wake credentials or an oversized encoded body, activation no longer reports ready and native wake has no eligible capability → parameterized hook/HTTP regression with persistent registry and session read. When identity is invalid, no close intent is written; when close HTTP fails, the exact closed intent survives and subsequent reconciliation removes stale readiness without affecting a distinct scope → focused lifecycle regression. When an accepted or uncertain wake is already in-flight, close/restart retains the reservation until ACK and no second native attempt occurs → focused durability regression. When the next normal turn occurs without credentials, Relay claims/injects/ACKs independently → existing and added hook caller-surface test. All changed paths satisfy workflow/test selection → agent-workflow check, redline check, scripts/test-plan.py --base origin/main and its reported checks. Final answer quit/reopen on Claude 2.1.291+ → isolated witness only if suitable binary becomes available; otherwise explicit version limitation.

**Plan review:** Agent technical review: collaboration:/root/claude_wake_plan_review (2026-10-06). Reviewer accepted the existing-helper approach, requested encoded-overflow and in-flight coverage, then approved the revised plan. The combined change was later classified High because the Codex reservation schema is in the same branch; /root/delivery_recovery_architecture reviewed the combined result and returned GO.

**Approvals:** Approved by user 2026-10-06: "yes, i approve and we should fix all" (source: user:db438fc2-ba15-4824-ab53-39fdd69be399). This approval covers the exact Claude lifecycle behavior as part of the combined branch.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Initial task context and baseline recorded before code edits. Intended source is integrations/claude-code/hooks/common.py; intended test files are tests/test_claude_wake_registration.py and tests/test_claude_wake_durability.py. Discovery confirmed an existing exact-scope close helper and one-second intent recovery; no core/API change is planned. Independent reviewer found encoded-overflow and in-flight proof gaps; revised plan covers both and was approved before implementation.

The new hook-to-loopback HTTP regression first failed on the actual contract: after an idle registration and missing socket credentials, public `/relay/sessions` still reported `activation.availability=ready`. Earlier fixture setup attempts used a non-loopback TestClient and returned 403; corrected to an explicit loopback peer before recording this pre-fix failure.

The shared helper now publishes the existing exact-scope close intent for absent, invalid, or encoded-overflow credentials. The new public activation regression initially passed across seven unusable credential cases; it was expanded to nine. Updated the prior encoded-size test to expect a credential-free close intent instead of no request. Subsequent coverage added invalid identity, offline close recovery, passive hook delivery, and in-flight reservation ordering.

All planned behavior coverage is now implemented. Parameterized hook/HTTP checks cover missing, empty, control, over-max, and encoded-overflow credentials; invalid identities cause no close; failed close HTTP leaves an exact intent for later recovery; a restricted normal prompt still injects and ACKs a pending delivery. Accepted and uncertain in-flight attempts survive close/restart without a second native attempt and become non-ready after the normal-turn ACK. Independent result review requested one more qualification test: if close-intent publication itself fails, no unsafe HTTP close is sent and an old registration remains ready until a later successful retry removes it. That regression passes. The affected Claude registration, durability, and Relay hook files passed: 232 tests. The whole-change selector reports the full lane (`python -m pytest tests/ -x -q`); no newer installed Claude binary is available for a live quit/reopen witness.

The first combined selector-required full run reproduced a timing fixture issue in `tests/test_codex_retained_wake.py::test_session_start_lock_budget_claims_emits_and_acks_once[user_prompt_submit-released]`; the corrected fixture now starts its release timer at deadline-aware lock acquisition. The combined full rerun passed, superseding the earlier clean-main timing block. No protected behavior was weakened. The only remaining environment limitation is the separate live quit/reopen witness: Claude 2.1.291+ is unavailable, while the installed shared CLI is 2.1.278.

## Evidence

Focused affected files: `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest tests/test_claude_wake_registration.py tests/test_claude_wake_durability.py tests/test_agent_relay_hooks.py -q -n 0` — 232 passed.

`python scripts/test-plan.py --base origin/main` selected `python -m pytest tests/ -x -q` (full lane). The initial pre-combined run and first combined run each stopped on the lock-budget fixture; after the deterministic fixture correction, the final combined full lane passed: 6,014 passed, 34 skipped, 2 xfailed. No 2.1.291+ Claude binary was found; shared `claude --version` is 2.1.278.

Import-boundary check passed. Redline found no boundary violation and detected Elevated risk; final-state Agent Workflow check was clean with that verdict. The ordinary local wrapper did not provide a Redline verdict, so the checker was rerun with CI-equivalent generated boundary and Redline inputs. The focused suite was rerun after the publication-failure regression, and the combined full lane subsequently passed. The newer-Claude host witness remains explicitly unavailable.

## Result review

Independent technical review: collaboration:/root/claude_wake_result_review (2026-10-06), on the source change and focused tests. Verdict: no blocking correctness findings; exact identity, scoped intent ordering, in-flight fencing, and passive hook delivery are preserved. Reviewer requested the publication-failure/retry regression, which was added and passed. The limitation is explicit: when the close intent cannot be published because of binding, lock, or storage failure, the prior capability can remain ready until a later successful hook retry; bypassing the intent would violate ownership and durability ordering. Combined full-lane verification is green. The Claude 2.1.291+ host witness is separately unavailable and reported as such, per the original scope.

Agent technical review: /root/delivery_recovery_architecture (2026-10-06), final combined-change review returned GO with no remaining correctness blockers.
Reviewed revision: HEAD cdc0e9ff plus reviewed source/test fingerprint SHA-256 `4651d939f67ea546d1c111af74507c9388418b180e89a6ccee6ca2b78968fad6`.
Verification adequacy: Combined selector-required full suite passed 6,014 tests, with 34 skipped and 2 xfailed; the Claude affected suite passed 232 tests. Exact task scope and completion criteria remained unchanged from this record's immutable baseline. Human result review: Approved by user 2026-10-06: "approve", for combined result `c938c068`, publication, merge after CI and installation.
