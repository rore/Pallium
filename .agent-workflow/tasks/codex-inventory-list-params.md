<!-- agent-workflow:start -->
**Outcome:** Native Codex inventory succeeds when Desktop accepts a normal tools/list request, while malformed native responses remain fail-closed.

**Target:** Pallium Codex native inventory bridge.

**Scope:** Remove the empty tools/list params member from app/codex_bridge_pipe.py; update caller-facing tests/test_codex_bridge_pipe.py and this Work Record only.

**Constraints:** Preserve custody, authority, proof, retries, response validation, and public native-failed behavior. Do not perform a live native call, service operation, or config mutation. No protected-contract edits.

**Completion criteria:** An actual serialized caller request omits params and is accepted by the current Desktop schema; before/after inventory and malformed/error/fence paths keep their current behavior; required checks and CI pass.

**Requirement baseline:** {"source":"root delegated task after sanitized live invalid-request stage and installed Desktop 26.928.2636.0 source comparison","outcome":"Correct the native tools/list request shape","scope":"one request constructor, caller-facing tests, Work Record","constraints":"no validator loosening, no authority/custody/proof/retry change or live actions","completion_criteria":"wire-compatible before/after inventory with fail-closed boundaries and required validation"}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** app/codex_bridge_pipe.py is a watched, otherwise unclassified runtime path, so Redline gives an Elevated floor. The change is one coherent request-shape correction.

**Discovery:** Installed Desktop 26.928.2636.0 ASAR main-DkWgQSQe.js tools/list parser makes params optional but requires threadStartKind when params is present; handler defaults an absent params to default. Current _observe sends params: {}. Sanitized live stage before-validate-error-invalid-request matches the handler's -32602 branch. FakeDesktop test fixture currently asserts the incompatible empty params object. rg found one production request constructor.

**Material assumptions:** Omitted params reaches the same default inventory handler; disprove with current installed parser or caller red/green test, then stop and return to planning. Existing request fixture covers the only production constructor; disprove by another caller and reassess scope.

**Plan:** Before production edit, add a caller-visible failing test through the private native pipe that validates the serialized request against the current Desktop schema and drives before/after inventory. Update the existing FakeDesktop expectation to omitted params, leaving response and failure assertions intact. Then remove only params: {} from _observe. Preserve all response validation and fixed diagnostics. Run exact and affected tests, selector-required validation, independent result review, and PR/CI. Target app/codex_bridge_pipe.py and tests/test_codex_bridge_pipe.py. Stop on any new schema mismatch or protected behavior delta.

**Verification plan:** When before/after inventory sends tools/list, the wire request shall omit params and obtain inventory from a schema-faithful fake Desktop -> caller test. When malformed/error responses or authority conflicts occur, existing native-failed/proof/fence behavior shall persist -> affected private caller suite. Whole changed application shall satisfy selected full non-slow suite and CI.

**Plan review:** Pending independent service-handoff security review before production edit.

**Approvals:** Not required at this risk level; user delegated autonomous implementation through root.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Discovery and Elevated/Simple classification complete. Await independent plan review before production edit.

## Evidence

Installed ASAR source and sanitized fixed-stage incident; no native response contents inspected.

## Result review

Pending.
