<!-- agent-workflow:start -->
**Outcome:** The OpenCode integration suite reflects the actor-free Relay close contract and passes.

**Target:** Pallium.

**Scope:** The single stale assertion in integrations/opencode/tests/plugin.test.mjs and this Work Record.

**Constraints:** No production code, API, schema, integration behavior, or governance policy change.

**Completion criteria:** When OpenCode deletes a session, the test asserts runtime, session, and container targeting while confirming actor_ref is absent; the canonical OpenCode package suite passes.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Redline classifies the nested integration-test path as gray because it is not covered by the tests/** blue rule; no boundary or contract surface is changed.

**Discovery:** Merged production code intentionally omits actor_ref from POST /relay/sessions/close, but the OpenCode test still expects the retired field. npm test passes 48 tests and fails only that assertion, with seven platform skips.

**Material assumptions:** This is test drift only; disproved if production Relay close still requires actor_ref or another package test fails after the assertion is corrected, in which case stop and return to planning.

**Plan:** Replace the stale equality assertion with an absence assertion, run the canonical npm test from integrations/opencode, then run workflow/redline checks and open a focused PR. Stop on any production-code need or additional failure.

**Verification plan:** Actor-free Relay close contract and complete OpenCode integration suite pass -> npm test from integrations/opencode; workflow classification remains valid -> agent-workflow and redline checks.

**Plan review:** Clean-context smart review by /root/opencode_test_plan_review: APPROVE; production and schema omit actor_ref, and the absence assertion directly checks the serialized contract.

**Approvals:** Not required at this risk level.

**Exceptions:** -

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

2026-09-08 — Discovery isolated the post-merge failure to one stale test assertion; production already matches the approved actor-free Relay contract.

2026-09-08 — Clean-context smart plan review approved the one-assertion change with no findings.

2026-09-08 — Replaced only the retired actor_ref equality check with an explicit absence assertion; production code was unchanged.

## Evidence

2026-09-08 — Before the fix, canonical npm test: 48 passed, 1 failed, 7 skipped; sole failure expected actor_ref in the Relay close payload.

2026-09-08 — After the fix, canonical npm test: 49 passed, 0 failed, 7 Windows-specific skips. Redline and agent-workflow checks are clean with no boundary findings or review checkpoints.

## Result review

2026-09-08 — Smart review by /root/opencode_test_result_review: APPROVE. The one-line absence assertion matches the serialized production contract, retains all targeting and cleanup checks, and stays within scope.
