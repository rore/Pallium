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
