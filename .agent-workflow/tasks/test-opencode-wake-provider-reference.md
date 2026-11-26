# Verify Relay references in native OpenCode provider requests

<!-- agent-workflow:start -->
**Outcome:** Check that an ACKed OpenCode wake exposes an exact recoverable reference in the serialized provider request.
**Target:** The existing released-host coalesced wake test.
**Scope:** `tests/test_opencode_native_wake_e2e.py` and this Work Record.
**Constraints:** No production changes, installed host operations, private payloads, real provider calls, or delivery replay. Keep existing native identity, custody and settlement checks.
**Completion criteria:** The correlated first native request contains the exact delivery and message IDs and a usable continuation offset for a truncated body. Existing full-body wakes retain their IDs and single ACKs.
**Requirement baseline:**
{"source":"work-record-initial","outcome":"Check that an ACKed OpenCode wake exposes an exact recoverable reference in the serialized provider request.","scope":"`tests/test_opencode_native_wake_e2e.py` and this Work Record.","constraints":"No production changes, installed host operations, private payloads, real provider calls, or delivery replay. Keep existing native identity, custody and settlement checks.","completion_criteria":"The correlated first native request contains the exact delivery and message IDs and a usable continuation offset for a truncated body. Existing full-body wakes retain their IDs and single ACKs."}
**Risk:** Routine
**Complexity:** Simple
**Reason:** Test-only change in the existing isolated native fixture; no production or protected behavior-contract paths.
**Approach:** Reuse the fixture's first-primary witness, fake provider and backlog. Lengthen only the original message and compare its real serialized provider envelope with the retained HTTP context response.
**Verification:** The exact native node collected. The renderer control passed from the package directory, and both Unicode first-attempt ACKed HTTP controls passed. The first renderer invocation used the wrong working directory and failed to import the plugin. The whole-change selector requires the full application lane. The native assertions still require the existing hosted 2.3.0 qualification.
**State:** Blocked
<!-- agent-workflow:end -->

The test-only patch is local on `test/opencode-wake-provider-reference`.
The existing native workflow selects the exact test through the
`qualify-opencode-2.3.0` PR label. No installed host was launched and
no live incident is attributed. The native run is outstanding.
