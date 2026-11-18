# Preserve valid OpenCode wake context across long same-input turns

<!-- agent-workflow:start -->
**Outcome:** A valid admitted Relay wake can continue across a long same-input model/tool turn without losing model-bound context, while empty, stale and unowned wakes remain refused.

**Target:** OpenCode V2 wake context lifecycle, using source `0fe69525e2ab3c037e694c100e0ad4f2b68f46b1` as the reference.

**Scope:** Trace and repair reusable integration lifecycle failures across repeated context callbacks for the same native input, including registration freshness, owner/generation authority, terminal state and HTTP outcomes.

**Constraints:** Preserve exact native input, delivery, owner, endpoint, scope, generation, claim-attempt and model-attachment authority. No payload without proof, implicit ACK, task/native-input replay, takeover, timeout or lease expansion. Keep ordinary receipt recovery and other unfinished work separate.

**Completion criteria:** Caller-surface E2E coverage proves safe same-input continuation across more than two model/tool steps and long work, explicit handling of expiry, owner conflict, stale/incomplete/null responses, genuine empty/unowned refusal, lifecycle disposal and later-message progress. Required independent review and repository validation establish the fix and its limits before release.

**Requirement baseline:**
{"source":"roadmap/features/add-wake-first-relay-delivery.md; task-owner request to fix repeated live same-input wake failure","outcome":"A valid admitted Relay wake can continue across a long same-input model/tool turn without losing model-bound context, while empty, stale and unowned wakes remain refused.","scope":"Trace and repair reusable integration lifecycle failures across repeated context callbacks for the same native input, including registration freshness, owner/generation authority, terminal state and HTTP outcomes.","constraints":"Preserve exact native input, delivery, owner, endpoint, scope, generation, claim-attempt and model-attachment authority. No payload without proof, implicit ACK, task/native-input replay, takeover, timeout or lease expansion. Keep ordinary receipt recovery and other unfinished work separate.","completion_criteria":"Caller-surface E2E coverage proves safe same-input continuation across more than two model/tool steps and long work, explicit handling of expiry, owner conflict, stale/incomplete/null responses, genuine empty/unowned refusal, lifecycle disposal and later-message progress. Required independent review and repository validation establish the fix and its limits before release."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Owner freshness and model-bound payload custody require independent review. The V2 integration paths are GRAY; no API, storage, shared transport or protected behavior-contract path changes.

**Discovery:** Healthy polling preserves the same delivered input across long work. A registration lapse makes the context endpoint reject before restoring continuation authority. Poll already handles that explicit conflict; the context callback did not. This characterizes a reusable failure class, not the historical incident's HTTP cause or loaded revision.

**Material assumptions:** A delivered snapshot remains restorable only while its exact input, owner, endpoint, scope, generation and continuation custody remain current. Equivalent concurrent progress may invalidate an opaque revision and conservatively refuse recovery.

**Plan:** Invoke the /agent-workflow skill to create the Work Record and classify risk, before any code edit. Completed before implementation. Use an optional guard in existing V2 enrollment and one context-local recovery for the explicit registration conflict. Preserve default enrollment callers. Keep the reviewed four application/test/documentation files unchanged for draft publication. Retain failed validation and separate History contract drift.

**Verification plan:** Same-input recovery and refusal → 38 caller cases and six production-plugin/HTTP E2Es. Custody, envelope and lifecycle limits → 20 existing backend controls. Regression safety → affected caller/E2E files and full non-slow validation with all failures retained. Publication → whole-change selector, Redline, Agent Workflow, privacy checks and existing platform CI.

**Plan review:** Agent technical review: independent plan review accepted the enrollment-await, pre-mutation and final attachment guards and named boundary coverage. Independent actual source and changed-feature adequacy review accepted the exact application/test/documentation bytes summarized below. This does not establish passing full validation or installed recovery.

**Approvals:** Standing task-owner delivery authority permits reviewed fixes to proceed through draft publication and existing CI without repeated routine approval. The coordinator released this exact five-path draft candidate after accepting source and bounded feature review. No merge, installation, live operation, CI retry or further local application campaign is authorized.

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation and review

Branch: `feat/opencode-wake-context-continuity`.
Base: `0fe69525e2ab3c037e694c100e0ad4f2b68f46b1`.
Canonical source item: [Add wake-first Relay delivery](../../roadmap/features/add-wake-first-relay-delivery.md).

Only an explicit readable stale-registration conflict permits one enrollment and
one exact context retry per callback. Guards fence ownership awaits, response
application and final attachment. Higher-scope retirement and conservative
revision refusal remain intact. No payload caching, replay, extra ACK, takeover,
lease extension or shared transport change is introduced.

Independent plan, actual source and bounded changed-feature adequacy reviews
accepted these exact SHA-256 file identities:

| Path | SHA-256 |
| --- | --- |
| `integrations/opencode/.opencode/plugins/pallium-v2.mjs` | `77bd85ace820f1c2bcba86881bdf50b35ecb19f4852e3f36a24d1dbe43be4a2e` |
| `integrations/opencode/tests/v2-plugin.test.mjs` | `475d269ce4717f3df704b2bf79a1f09edadd5674ac243845115118376dbdcebf` |
| `tests/test_opencode_native_wake_e2e.py` | `934c45f39bd9733977dfdb646492f74176de91652c7f90d80a0477872652502c` |
| `integrations/opencode/README.md` | `43c713361b710baa5666cbf3a53f45367641c082bb9299ab450370789616d4eb` |

## Validation and limits

| Evidence | Actual result |
| --- | --- |
| New V2 caller coverage | All 38 new cases pass. |
| Changed-feature real HTTP and existing backend controls | Six E2Es and 20 controls pass, including a 26-case run after dependency correction. |
| Affected V2 caller file | 190 passed, one preserved supersession failure. |
| Affected native-wake E2E file | Seven passed, eight failed, three absent-host skips. All six new cases pass. |
| Exact-reference comparison | All eight old capture/history failures reproduce at the base revision; later assertions remain unreached. |
| First full non-slow run | Failed: 4,271 passed, one failed, three skipped, one xfailed. Nested Hermes interpreter could not import `pydantic`. |
| Interpreter qualification | Normal and scrubbed dependency imports and the exact failed Hermes node pass. |
| Conditional full non-slow run | Failed: 7,412 passed, one failed, 16 skipped, two xfailed. Exact-claim JSON-budget test received `503 relay_busy` before its claim body. |

Both full runs used Windows/Python 3.13.14, declared non-slow/four-worker defaults
and fail-fast. They completed below their caps with zero owned survivors.
The second failure records a setup deadline, 554 ms connection acquisition and
555 ms total. Physical cause and baseline reproducibility remain unknown.
It is a failed required gate, not a waived test or evidence that V2 caused it.

The known V2 failure is
`fresh supersession consumes uncertain terminal without stale follow-up`.
The eight old Python failures are seven ownership/history rows and
`test_capture_callbacks_retry_through_real_http_and_history`.
Their fixtures lack required capture prerequisites. Separately, their aggregate
capture expectation and README conflict with existing per-assistant behavior.
No fixture, oracle, History behavior or timeout was changed to conceal that drift.
Initial new-test fixture failures and dependency-preflight failures were retained
before their bounded corrections; the passing results do not erase them.

The second full failure is
`tests/test_relay_exact_claim_e2e.py::test_codex_batch_never_claims_siblings_without_projected_trigger[json_budget]`.
The first was
`tests/test_hermes_bridge.py::test_bridge_stdio_call_on_supported_sdk[False-sdk1]`.
Both SDK1 bridge cases pass in the second full run; absent SDK2 qualification and
native-host skips remain limits. Later unexecuted full-suite cases are unknown.

Detailed raw evidence remains private. This public projection preserves the
requirements and actual outcomes, not machine-specific operational records.
Publication checks pass: whole-change selector requires FULL, import boundaries
and Agent Workflow pass, and Redline reports a GRAY review advisory.
Required platform CI still applies. The draft is
blocked pending validation disposition; it is not merged, installed or claimed
to explain the historical incident. The separate receipt-recovery contribution
and broader roadmap remain unfinished.
