<!-- agent-workflow:start -->
**Outcome:** Recover abandoned pre-write Codex wake reservations without repeating a native wake that may already have been submitted.

**Target:** Pallium Relay Codex wake scheduling and SQLite reservation authority.

**Scope:** Existing wake registry, SQLite transitions, scheduler/native write callers, regression tests, and relevant product documentation/roadmap.

**Constraints:** Preserve exact endpoint/generation checks, busy-session deferral, hook-owned claim/ACK, and ambiguous-write fences. No live reservation reset, resend, manual wake, new scheduler, or configuration switch. Existing legacy reservations lack pre-write proof and remain held until ordinary terminal/expiry reconciliation.

**Completion criteria:** Caller-surface regression reproduces abandoned pre-write starvation and passes after the fix; restart/concurrent recovery invokes at most one native write; legacy reserved, accepted, uncertain, invalid and claimed states do not replay; required validation and independent review pass; deploy safely and check the original workflow-manager notification without manufacturing receipt.

**Requirement baseline:**
{"source":"325c9e63-3369-4fe2-8669-f92a2ed4d4e4","outcome":"Recover abandoned pre-write Codex wake reservations without repeating a native wake that may already have been submitted.","scope":"Existing wake registry, SQLite transitions, scheduler/native write callers, regression tests, and relevant product documentation/roadmap.","constraints":"Preserve exact endpoint/generation checks, busy-session deferral, hook-owned claim/ACK, and ambiguous-write fences. No live reservation reset, resend, manual wake, new scheduler, or configuration switch. Existing legacy reservations lack pre-write proof and remain held until ordinary terminal/expiry reconciliation.","completion_criteria":"Caller-surface regression reproduces abandoned pre-write starvation and passes after the fix; restart/concurrent recovery invokes at most one native write; legacy reserved, accepted, uncertain, invalid and claimed states do not replay; required validation and independent review pass; deploy safely and check the original workflow-manager notification without manufacturing receipt."}

**Risk:** High

**Complexity:** Moderate

**Reason:** Durable native-action fences cross the red persistence boundary in storage/sqlite_relay.py. Incorrect recovery could repeat an ambiguous native write.

**Discovery:** workflow-manager notification relay-msg-cb3bf4767a1c429bb1bd40907425ef11 is pending behind older reservation generation 1847, outcome reserved, zero claim attempts. Existing reconciliation has no restart path for an unclaimed reservation whose worker is gone. Older legacy code could launch before recording outcome, so reserved alone is not durable no-write proof. Retained code already commits uncertain before action. Independent diagnosis: /root/wake_recovery_diagnosis; safety analysis: /root/service_handoff_security, 2026-10-02.

**Material assumptions:** Existing SQLite exact-row transactions provide the action CAS; verify with competing registries. Diagnostic trace is lossy and cannot authorize replay. Old reserved rows cannot be retroactively labelled safe; preserve them if no durable proof exists.

**Plan:** Invoke Agent Workflow and classify risk before code edits. Preserve the failing reservation regression and rejected patch as incident evidence; abandon the partial reservation implementation after automatic review rejected both replacement recovery and the narrower exact-row alternative. Ship only the independent retained-connection repair: for conclusively drained normal retained I/O failures, retain only the existing authenticated registration in RAM while its source connection remains alive; on scheduled demand reopen the same endpoint, recheck exact source/Desktop identity and ancestry, and validate the tool catalog. Clear this registration on source EOF, identity/schema mismatch, process loss, unresolved cancellation or stop; never replay a spent wake. Keep all reservation semantics unchanged. Verify failures/concurrency/lifecycle, run selector-required checks once, independent result review, PR/merge/install through normal installed wrapper and health verification. Stop on ambiguous live action; never reset or resend the incident notification. Report the reservation recovery case as blocked, not fixed.

**Verification plan:** Connection recovery -> focused red-green regression through existing HTTP/MCP/hook paths with Unicode payload and ACK readback. Security and duplicate safety -> source/Desktop/epoch loss, schema mismatch, unresolved I/O, EOF/stop, and already-submitted no-replay checks. Regression -> affected subsystem, scripts/test-plan.py and required checks once. Review -> independent security review. Live behavior -> exact traces of existing notifications after deployment; receipt is separate from scheduling evidence. Blocked reservation case -> preserve red evidence and unchanged production semantics; report automatic rejection rather than claiming success.

**Plan review:** Agent technical review: /root/service_handoff_security, 2026-10-02 accepted prepared provenance and exact CAS approach; required legacy hold and guarded scheduling recorded above. /root/wake_recovery_diagnosis confirmed starvation path independently. Subsequent security review accepted on-demand reopening from the existing standing authenticated caller after conclusive native I/O cleanup, provided exact source/Desktop identity, active source connection and strict descriptors are revalidated and all unresolved/identity-loss cases clear authority.

**Approvals:** Approved by user 2026-10-02: "so this is critical! when we see a bug like this we should dive into it heads on! relay should be solid!"

Approved by user 2026-10-02: "Approve this exact recovery case" — direct reply to request_user_input_async call_K7Z3hfdy04YAGF5ZeH7Z09V3 asking to recover only a new durable prepared replacement after the earlier hook claim expires; existing submitted/uncertain wakes never retry. This exact approval follows the automatic review rejection of the expired-claim replacement delta. Normal automatic review still applies.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Incident audit — 2026-10-02

User expanded the diagnosis to missed messages across all session states: "i see messages not arriving all the time, not just in unloaded sessions. something is still very much broken. i presume you can see in the db lost messages, we don't need to wait to catch it when i see it".

Metadata-only SQLite inspection found 17 pending deliveries across nine recipients: 16 Codex and one Claude. Today's snapshot had 18 delivered and six pending Codex deliveries. Old accepted/uncertain fences, unreachable recipients, a legacy reserved fence, and recent native-unavailable deferrals are distinct classes; historical trial expirations are not counted as production defects without corroboration. No payloads, claim tokens, state resets, resends or manual wake were used in this audit.

Workflow-manager's older delivery expires naturally at 2026-10-02 14:22:07 UTC; its newer notice expires the next day. The old reserved row cannot safely be upgraded to pre-write proof. Independent review requires preserving it until existing terminal/expiry reconciliation or actual hook receipt.

Dict-manager reported delivery relay-delivery-004214df236b4357a88e51df5000c248 repeatedly deferred native_unavailable before being delivered through their explicitly reported app fallback at 10:59:53 UTC. Existing logs show a native timeout preceding repeated stopped-custody failures around 10:56 UTC. Source inspection confirms conclusively cancelled state-read I/O drops custody while the admitted source stays connected and its worker waits for another runtime request. The reviewed on-demand repair above stays within the same retained-MCP transport and existing scheduler; no heartbeat, new identity, new configuration or alternate transport is added.

## Automatic-review limit

Automatic approval review rejected the prepared expired-claim replacement delta again after the exact human approval, citing possible duplicate native actions. It then rejected the reduced exact-row reserved-to-uncertain write fence as well. No further retry or workaround is permitted. The entire partial reservation implementation is excluded and reverted; its red regression and rejected diff are preserved privately. All existing reservation semantics, claimed/submitted/uncertain safety and tests remain mandatory. The separate retained-connection repair is unaffected. The final product claim must disclose this unrecovered crash boundary.

The original Outcome and Completion criteria remain intact and unfulfilled; State is Blocked for that reservation work. The user's subsequent broad real-use incident request authorizes the independently reviewed connection repair as unaffected work. Publishing that repair does not complete or close the blocked reservation defect.

## Connection repair review and validation

Independent security review accepted the final connection-only diff on 2026-10-02: bridge Git blob `d7e60a0f6eee9d667655641db570c5ed6c8da2de`, new regression blob `96320730bbaacf81816a551e7eec7082224bfc47`, existing fixture blob `4f7882beb755f85f44bf9bf966b03111cbf12e6d`. Review confirmed exact source/epoch/Desktop ancestry, image/version and both catalog descriptors are revalidated; unresolved cancellation, identity loss and source stop revoke recovery. Existing spent-action fences remain unchanged.

The original regression failed before the fix with one native connection instead of two (`timeout` then `stopped`). Final focused runs passed: 9 connection recovery cases in 6.78 seconds and 115 existing retained-wake cases in 33.92 seconds. The new cases include repeated read timeout, reconnect catalog timeout, identity/schema denial and post-owner no-replay. The first full run was interrupted for a review correction; no pass is claimed for it. Final selector chose the full lane; its result is pending. Import boundaries and workflow checks passed before final validation.

Full-lane triage: the original queue concurrency and dashboard qualification failures reproduced with the unchanged `origin/main` bridge loaded in memory. A complete four-worker run then reported 5,912 passed, 37 failed, 34 skipped and 2 expected failures. Thirty-six failures exercised the legacy queue transport without selecting it on Windows, where the shipped default is retained wake. The legacy module fixture, SQLite queue lifecycle case and dashboard queue projection case now select that transport explicitly; all original assertions remain intact. The remaining Claude lifecycle test asserted transport invocation before its scheduled background worker ran; it now waits on the mocked transport's event before the unchanged assertion. Its affected file passes 52 tests with 2 skips. An earlier readiness-write failure did not reproduce under exception instrumentation or in the complete run; no speculative production change was made for it. These are test corrections, not changes to reservation recovery or transport defaults.

Final validation: `.venv/Scripts/python.exe -m pytest tests/ -q --maxfail=0` completed with **5,949 passed, 34 skipped, 2 expected failures in 295.69 seconds**, using the configured four workers and non-slow selection. The affected legacy queue files passed 203 tests in 60.98 seconds. Independent review accepted the final test-only fixture corrections with the production hash unchanged. Import boundaries are clean, redline is GRAY with no boundary violations, workflow reports clean, and `git diff --check` passes. The connection repair is ready for publication; the reservation defect remains Blocked.
