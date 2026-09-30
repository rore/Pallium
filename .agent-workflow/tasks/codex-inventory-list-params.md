<!-- agent-workflow:start -->
**Outcome:** Native Codex inventory succeeds when Desktop accepts a normal tools/list request, while malformed native responses remain fail-closed.

**Target:** Pallium Codex native inventory bridge.

**Scope:** Remove the empty tools/list params member from app/codex_bridge_pipe.py; update caller-facing tests/test_codex_bridge_pipe.py and this Work Record only.

**Constraints:** Preserve custody, authority, proof, retries, response validation, and public native-failed behavior. Do not perform a live native call, service operation, or config mutation. No protected-contract edits.

**Completion criteria:** An actual serialized caller request omits params and is accepted by the current Desktop schema; before/after inventory and malformed/error/fence paths keep their current behavior; required checks and CI pass.

**Requirement baseline:** {"source":"root delegated task after sanitized live invalid-request stage and installed Desktop 26.928.2636.0 source comparison","outcome":"Native Codex inventory succeeds when Desktop accepts a normal tools/list request, while malformed native responses remain fail-closed.","scope":"Remove the empty tools/list params member from app/codex_bridge_pipe.py; update caller-facing tests/test_codex_bridge_pipe.py and this Work Record only.","constraints":"Preserve custody, authority, proof, retries, response validation, and public native-failed behavior. Do not perform a live native call, service operation, or config mutation. No protected-contract edits.","completion_criteria":"An actual serialized caller request omits params and is accepted by the current Desktop schema; before/after inventory and malformed/error/fence paths keep their current behavior; required checks and CI pass."}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** app/codex_bridge_pipe.py is a watched, otherwise unclassified runtime path, so Redline gives an Elevated floor. The change is one coherent request-shape correction.

**Discovery:** Installed Desktop 26.928.2636.0 ASAR main-DkWgQSQe.js tools/list parser makes params optional but requires threadStartKind when params is present; handler defaults an absent params to default. Current _observe sends params: {}. Sanitized live stage before-validate-error-invalid-request matches the handler's -32602 branch. FakeDesktop test fixture currently asserts the incompatible empty params object. rg found one production request constructor.

**Material assumptions:** Omitted params reaches the same default inventory handler; disprove with current installed parser or caller red/green test, then stop and return to planning. Existing request fixture covers the only production constructor; disprove by another caller and reassess scope.

**Plan:** Before production edit, add a caller-visible failing test through the private native pipe that validates the serialized request against the current Desktop schema and drives before/after inventory. Update the existing FakeDesktop expectation to omitted params, leaving response and failure assertions intact. Then remove only params: {} from _observe. Preserve all response validation and fixed diagnostics. Run exact and affected tests, selector-required validation, independent result review, and PR/CI. Target app/codex_bridge_pipe.py and tests/test_codex_bridge_pipe.py. Stop on any new schema mismatch or protected behavior delta.

**Verification plan:** When before/after inventory sends tools/list, the wire request shall omit params and obtain inventory from a schema-faithful fake Desktop -> caller test. When malformed/error responses or authority conflicts occur, existing native-failed/proof/fence behavior shall persist -> affected private caller suite. Whole changed application shall satisfy selected full non-slow suite and CI.

**Plan review:** Agent technical review: /root/service_handoff_security accepted the exact omission plan after checking the current installed parser, single production constructor, and before/after same-connection caller test obligation. No blocker; sanitized live error remains corroboration rather than sole-cause proof.

**Approvals:** Not required at this risk level; user delegated autonomous implementation through root.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Discovery and Elevated/Simple classification complete. Independent plan review accepted. Added a schema-faithful response through FakeDesktop's actual private pipe; exact native caller test failed before production edit with unavailable and before-validate-error-invalid-request as expected. The checkout virtual environment lacks pywin32, so used the existing primary checkout's pywin32-enabled Python for this native test. Corrected the initial Requirement baseline transcription to match the original four context fields exactly; no requirement changed.

Removed only `params: {}` from the `_observe` request and updated FakeDesktop's exact decoded-wire assertion. Focused new caller and existing before/after source-exit tests: 18 passed. Affected slow bridge file: 230 passed, two existing `before-write/transport-failed` source-exit cases failed; exact `--lf` rerun passed both. Selector full non-slow `-x` stopped at an unrelated Claude wake lost-HTTP fixture after 1115 passed, two skipped, one xfailed; exact `--lf` reproduced its missing transport event. The task owner supplied an established disposable-profile fixture isolation used for the one full completion below. No cause for the initial transport failures is claimed fixed.

2026-09-30 verification: The root owner's established isolation sets only subprocess USERPROFILE to a disposable directory under this checkout's ignored tmp. The exact unrelated Claude test passed 1/0.84s under that isolation. One full non-slow completion passed: 5763 passed, 34 skipped, two xfailed in 327.71s. The owned disposable directory was verified inside this checkout, created during this run, and removed; no installed profile was changed. Workflow check is clean. Existing before/after source-exit test supplies all 16 cases on the same native connection; the new test targets only the missing/default params contract, not the full optional params schema.

## Evidence

Installed ASAR source and sanitized fixed-stage incident; no native response contents inspected. Red: `test_inventory_list_request_matches_desktop_optional_params_schema` failed with unavailable versus registered, matching the live fixed error stage. Green: 18 focused cases; affected file 230 passed with two pre-validation transport failures, exact `--lf` both passed; isolated full 5763 passed, 34 skipped, two xfailed. Workflow check clean.

## Result review

Agent technical review: `/root/service_handoff_security`, 2026-09-30, accepted the sole production request-member deletion, decoded-wire fixture, red-to-green private caller test, and existing before/after 16-case coverage.

Reviewed revision: `68a34a3b` source and test delta; this record-only formatting follow-up does not change them.

Verification adequacy: Adequate for this narrow request shape: 18 focused cases, existing before/after lifecycle, isolated full 5763 pass, and clean workflow check. Pre-write transport failures and installed Claude hook fixture issue are not claimed fixed. CI pending.
