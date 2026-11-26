# Preserve confirmed OpenCode wake context through Pallium startup

<!-- agent-workflow:start -->
**Outcome:** Keep an acknowledged OpenCode wake on the same native input when Pallium answers with its pre-readiness 503.
**Target:** Internal wake context continuation in `integrations/opencode/.opencode/plugins/pallium-v2.mjs`.
**Scope:** Recognize the startup gate response in the existing bounded continuation loop and cover it in `tests/test_opencode_native_wake_e2e.py` and `integrations/opencode/tests/v2-plugin.test.mjs`.
**Constraints:** No request replay or second ACK beyond the existing exact continuation lookup. No new timeout, broader 503 retry, relaxed ownership proof, or live operation.
**Completion criteria:** A confirmed wake survives the startup response, restores only the same input and delivery, and completes its second tool without another ACK. A wake without proof and an unrelated parsed 503 remain refused.
**Requirement baseline:**
{"source":"work-record-initial","outcome":"Keep an acknowledged OpenCode wake on the same native input when Pallium answers with its pre-readiness 503.","scope":"Recognize the startup gate response in the existing bounded continuation loop and cover it in `tests/test_opencode_native_wake_e2e.py`.","constraints":"No request replay or second ACK beyond the existing exact continuation lookup. No new timeout, broader 503 retry, relaxed ownership proof, or live operation.","completion_criteria":"A confirmed wake survives the startup response, restores only the same input and delivery, and completes its second tool without another ACK. A wake without proof and an unrelated parsed 503 remain refused."}
**Behavior changes:**
[{"target":"task-context.scope","classification":"equivalent","before":"Recognize the startup gate response in the existing bounded continuation loop and cover it in `tests/test_opencode_native_wake_e2e.py`.","after":"Recognize the startup gate response in the existing bounded continuation loop and cover it in `tests/test_opencode_native_wake_e2e.py` and `integrations/opencode/tests/v2-plugin.test.mjs`.","reason":"Add focused controls for the already required refusal without custody and for a parsed lookalike response. No change to the accepted runtime scope."}]
**Risk:** Elevated
**Complexity:** Simple
**Reason:** The change extends outage classification on a wake custody path.
**Discovery:** The production startup gate returns `503 {"error":"service not initialized"}`. The plugin rejects that parsed body even for a confirmed continuation. A real acknowledged continuation failed after server bind and before runtime readiness; the exact HTTP response was not retained.
**Material assumptions:** The production startup message is exact and the gate does not run the context operation. Only the confirmed exact continuation is eligible for this branch.
**Plan:** Invoke Agent Workflow and classify before code edits. Reproduce the refusal through the existing isolated real-HTTP continuation fixture. After independent plan review, recognize the exact startup response at the context lookup only and leave all continuation guards intact.
**Verification plan:**
- Real startup gate response, same-input restore and second-tool progress with one ACK → isolated existing HTTP continuation fixture with production startup gate on the guarded path.
- Unrelated parsed 503 or absent proof → retain refusal and no claim/ACK using the existing focused controls.
**Plan review:** Agent technical review: independent architect GO at `332cd733`. Recognize the exact startup response at the continuation lookup site, not in the helper shared by re-enrollment; preserve identity, deadline, one ACK and second-tool progress.
**Approvals:** Not required at this risk level.
**State:** Ready for review
<!-- agent-workflow:end -->

No live request, retry or install change. The incident timeline selects
the first reproduction; it does not prove the exact response.

An isolated executable control invoked the real startup gate and
passed its status and parsed body to the exact current plugin
predicate. The gate refused before entering the app, and the plugin
classified it as non-recoverable. The same predicate classified typed
busy and transport loss as recoverable. This is a classification
witness, not end-to-end qualification.

The isolated real HTTP journey failed on the unmodified plugin: the
startup response aborted context recovery after one request instead of
continuing on the same input.

After the plugin change, all three HTTP journeys passed: startup,
typed busy 503, and transport loss. Each finished both tool steps on
the original input with no duplicate ACK or replacement prompt.
Three focused plugin checks also passed: unknown 503, startup
lookalike with a nonretryable detail, and exact startup response
without local confirmation. The full plugin test file passed 279 cases before the two
new focused refusal cases were added; both new cases passed in the
focused run. No live change.

## Result review

Agent technical review: independent architect GO for source and focused evidence.
Reviewed revision: base `332cd733`; plugin `6f1f078c`, HTTP test `a690d0c3`, plugin tests `7c4c9dbc`.
Verification adequacy: exact local confirmation and the original deadline still govern recovery. Real HTTP verifies same-input second-tool progress and one ACK; refusal controls cover unconfirmed and unrelated responses. Whole-change validation is separate.

The first full Windows non-slow run stopped at 4,149 passes with two
unchanged fixture failures: a temporary registration intent could not be
created and a deep-directory test hit WinError 206. Both exact cases
passed using a shorter test root. The first run remains failed. The
single corrected full run on the same candidate bytes passed: 9,338
passed, 37 skipped, two xfailed. Publish separately for normal hosted
checks. No further local full run.
