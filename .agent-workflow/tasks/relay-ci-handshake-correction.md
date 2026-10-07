# Bound the publisher compare-delete test handshake

<!-- agent-workflow:start -->
**Outcome:** The publisher compare-delete test proves real OS lock contention without a one-second fixture release racing subprocess startup.

**Target:** Claude wake durability validation.

**Scope:** tests/test_claude_wake_durability.py and this Work Record.

**Constraints:** Test-only. Preserve all compare-delete, latest-intent and restart-readback assertions, real OS locking, production deadlines and error behavior. No source, configuration, protected-contract, live installation or outage-patch change; no exclusions or asserted-success retries.

**Completion criteria:** Normal and delayed subprocess startup both prove actual contention before releasing deletion, retain the newer intent and recover its busy state. Parent waits and subprocess/thread cleanup are bounded. The delayed journey fails against the old fixture gate and passes after the correction. Independent smart review, focused validation and exact combined-candidate full/CI evidence pass; unexplained historical probe failure and hang remain separately open.

**Requirement baseline:**
{"source":"pallium-manager:2026-10-07T20:24:validation-fixture-ownership","outcome":"The publisher compare-delete test proves real OS lock contention without a one-second fixture release racing subprocess startup.","scope":"tests/test_claude_wake_durability.py and this Work Record.","constraints":"Test-only. Preserve all compare-delete, latest-intent and restart-readback assertions, real OS locking, production deadlines and error behavior. No source, configuration, protected-contract, live installation or outage-patch change; no exclusions or asserted-success retries.","completion_criteria":"Normal and delayed subprocess startup both prove actual contention before releasing deletion, retain the newer intent and recover its busy state. Parent waits and subprocess/thread cleanup are bounded. The delayed journey fails against the old fixture gate and passes after the correction. Independent smart review, focused validation and exact combined-candidate full/CI evidence pass; unexplained historical probe failure and hang remain separately open."}

**Risk:** Routine

**Complexity:** Simple

**Reason:** Two policy-blue test/governance files; no caller-visible behavior or new authority. Parent recovery remains High/Large.

**Approach:** Invoke agent-workflow and classify before edits (completed). Reuse the clean managed diagnostics checkout on a fresh branch from e9eb3956; prior PR300 branch/evidence remain reachable. First add normal/delayed-startup coverage to reproduce the existing one-second gate race. Then hold the paused deletion until explicit parent release, guaranteed in finally. Observe genuine child OS lock failure through a test-private marker, bounded parent polling and communicate; retain stdout and stored-state assertions. No generic subprocess framework, dependencies, production budget changes or unrelated fixture edits. Root owns the record and independent review; a bounded cheap worker edits only the named test. Freeze/review/focused checks precede one coordinated monitored full run on the exact combined candidate, not parallel broad suites or untested-tree evidence transfer.

**Verification:** Delayed startup with the old gate fails at missing contention; both startup cases pass after the correction through a real child/native lock and unchanged registry readback. Run the exact node with -q -n 0, then the affected file and whole-change selector. Application/test changes require one full non-slow run, coordinated with outage/OC3 validation at an explicitly recorded combined revision, per-test faulthandler and a behavior-preserving observer limited to the unexplained hook probe. Fresh workflow/Redline and exact-head CI remain required. Preserved failure/hang logs and isolated passing retries do not establish historical causes.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Discovery and ownership

Independent pre-edit technical review by /root/wake_output_plan_review
(gpt-6.1-sol/high) approved 232560cda607ad8cb447a147dcac3b1e5dcb062a as
Routine/Simple. The marker must come only from the existing native nonblocking
lock-failure observer; delayed startup occurs before common loads. Keep all
production budgets unchanged, parent polling and process/thread cleanup finite,
and publication single-shot. The review found no smaller existing helper that
preserves actual OS contention and avoids unbounded readline. Implementation is
delegated only in the named test file; root owns this record and acceptance.

Manager assigned relaydev sole bounded shared Claude/Codex validation diagnosis
and the separate narrow test-only correction. The retained OC3 xdist failure
shows finish_delete.wait(1) expired before the publisher could report real lock
contention, then stdout True instead of contended. This explains the fixture
race, not why startup was delayed or a production compare-delete defect.
The serial hang has no stack or reliable active-node evidence. The unrelated
non-registering hook probe failed before its request; natural-stage observation
later passed with ~1 ms locks and valid state. Both historical causes remain open.
No live environment changes; pal-dev1 is paused on broad tests. Preserve parent
outage source/test blobs and keep this branch separate.

## Implementation evidence

The delayed pre-fix startup journey failed as required: 1 failed and 1 warning
in 2.84 seconds, stdout True instead of contended and register-old's
finish_delete.wait(1) expiration. The 1.2 second delay runs before common loads,
so no spent hook deadline is manufactured. After the marker/explicit-release
correction, both startup parameters passed in 2.94 seconds and the affected
file passed 54 cases in 20.46 seconds at fixture blob
36f00b9c7d468061fdb87136ea97646791a11156. An intermediate inline-script
indentation error was corrected before those passing runs; it is not product
failure evidence. Root review then required finally to attempt child cleanup
even if worker join fails, and vice versa. Corrected finally to release the gate,
attempt child kill/wait, and always join/assert the worker in its own finally.
Both final startup parameters passed in 2.67 seconds at fixture blob
4d1d4095a214be5b8188bf47088a085c9fc909d9; source/test diff checks passed.
The earlier 54-case file evidence is reused for unaffected paths only, not
represented as a final-blob file run; the combined full run will include it.
The pre-fix output was retained in the worker's tool result, not copied to a
filesystem log. No file path or artifact is invented for that witness.
Independent final fixture review and full/CI gates remain pending.

Root's 0.57 second isolated observer check may have overlapped the worker's
20.46 second affected-file run; this cannot be established from retained timing.
No broad suites overlapped and no source/test edits occurred during the passing
file run. Do not claim exclusive scheduling for that interim evidence. The
manager-authorized combined full run will have one owner and no overlapping
pytest, on explicitly recorded constituent commits and tree/blob identities.

## Result review

Agent technical review: /root/wake_output_plan_review, independent
gpt-6.1-sol/high, approved the exact fixture source/test adequacy.
Reviewed revision: HEAD 952b9fb04f829c6ce9f71915c121f69b4de7f6bd plus
test blob 4d1d4095a214be5b8188bf47088a085c9fc909d9.
Verification adequacy: the final focused startup/control cases qualify the
changed handshake and cleanup; prior 54-case file evidence is limited to its
recorded earlier blob. The marker follows actual native lock failure, all
original stdout/result/state/restart assertions remain, and no production
deadline or caller behavior changes. Routine/Simple is independently confirmed.
No fixture blocker remains before integration into the approved exact combined
candidate. Required combined full validation and eventual exact-head CI/review
remain gates; parent recovery and historical probe/hang causes remain open.
The stale implementation text and tool-result/file-log distinction were already
corrected while this review was running; no reviewed test bytes changed.
