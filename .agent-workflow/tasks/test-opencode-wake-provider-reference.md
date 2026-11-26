# Verify Relay references in native OpenCode provider requests

<!-- agent-workflow:start -->
**Outcome:** Check that an ACKed OpenCode wake exposes an exact recoverable reference in the serialized provider request.
**Target:** The existing released-host coalesced wake test.
**Scope:** `tests/test_opencode_native_wake_e2e.py`, its extracted-handler control in `tests/test_ci_workflow.py`, and this Work Record.
**Constraints:** No production changes, installed host operations, private payloads, real provider calls, or delivery replay. Keep existing native identity, custody and settlement checks.
**Completion criteria:** The correlated first native request contains the exact delivery and message IDs and a usable continuation offset for a truncated body. Existing full-body wakes retain their IDs and single ACKs.
**Requirement baseline:**
{"source":"work-record-initial","outcome":"Check that an ACKed OpenCode wake exposes an exact recoverable reference in the serialized provider request.","scope":"`tests/test_opencode_native_wake_e2e.py` and this Work Record.","constraints":"No production changes, installed host operations, private payloads, real provider calls, or delivery replay. Keep existing native identity, custody and settlement checks.","completion_criteria":"The correlated first native request contains the exact delivery and message IDs and a usable continuation offset for a truncated body. Existing full-body wakes retain their IDs and single ACKs."}
**Behavior changes:**
[{"target":"task-context.scope","classification":"equivalent","before":"`tests/test_opencode_native_wake_e2e.py` and this Work Record.","after":"`tests/test_opencode_native_wake_e2e.py`, its extracted-handler control in `tests/test_ci_workflow.py`, and this Work Record.","reason":"Keep the existing synthetic handler control compatible with the native fixture's new request collector. No production behavior or acceptance criterion changes."}]
**Risk:** Routine
**Complexity:** Simple
**Reason:** Test-only change in the existing isolated native fixture; no production or protected behavior-contract paths.
**Approach:** Reuse the fixture's first-primary witness, fake provider and backlog. Lengthen only the original message and compare its real serialized provider envelope with the retained HTTP context response.
**Verification:** The exact native node collected. One renderer control and both Unicode first-attempt ACKed HTTP controls passed. Hosted qualification `45786039068` executed and passed the exact native node on OpenCode 2.3.0 at `9e6d4c3c`. Both ordinary Linux jobs failed on the extracted-handler control's missing collector; Linux 3.12 also reported `503 relay_busy` in an unchanged expiry test. Preserve both failures. The follow-up retains the qualified native file byte-for-byte and fixes the extracted-handler control. Ordinary hosted checks remain required.
**State:** Ready for review
<!-- agent-workflow:end -->

The hosted native run exercised the actual serialized request, the exact
IDs and continuation offset, short backlog messages, and owned teardown.
It does not establish the cause of the live incident or qualify OpenCode
2.4.1. No installed host was launched.
