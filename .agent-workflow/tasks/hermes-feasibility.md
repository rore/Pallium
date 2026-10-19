# Hermes feasibility: isolated first slice

Canonical feature: `roadmap/features/add-hermes-agent-integration.md`
(`add-hermes-agent-integration`). Owner: this chat; owner-managed checkout:
`C:\Users\I347041\.codex\worktrees\hermes-feasibility\Pallium`.
Branch: `feat/hermes-feasibility`; base: `701608cd0f666fe5106bf7c91e2e98bf0fe21d0c`.

<!-- agent-workflow:start -->
**Outcome:**
Determine whether released Hermes supplies safe session-bound tool identity and payload-admission primitives, with reproducible evidence or precise blockers, while Relay reliability work proceeds independently.

**Target:**
Pallium Hermes integration feasibility; no supported-runtime claim.

**Scope:**
This Work Record, evals/hermes/README.md, evals/hermes/qualification.py, tests/test_hermes_qualification.py, roadmap/features/add-hermes-agent-integration.md, and the directly affected Hermes paragraph in roadmap/scope.md. Temporary pinned upstream source/probes may be used outside live installations.

**Constraints:**
Do not change shared Relay implementation, API/schema, persistence, scheduler, existing integration behavior, behavior contracts, dependencies, CI, or installed environment. No Hermes installation, paid inference, live service changes, or shared local full-suite qualification slot. Use one cheaper-model source researcher; parent reviews evidence. Stop this slice at a documented capability decision; missing public APIs are blockers, not permission for private host mutation.

**Completion criteria:**
Pin the release/source revision; probe the public identity and request/admission seams where executable without installation; include negative controls for unsupported identity/admission assumptions; record exact evidence level and unresolved host qualification; preserve the reliability integration/release gate in the canonical roadmap; publish a reviewable isolated slice with focused checks and required whole-change validation.

**Requirement baseline:**
{"source":"user:ca822373-84f0-43de-9c6b-ec54a6ace88b","outcome":"Determine whether released Hermes supplies safe session-bound tool identity and payload-admission primitives, with reproducible evidence or precise blockers, while Relay reliability work proceeds independently.","scope":"This Work Record, evals/hermes/README.md, evals/hermes/qualification.py, tests/test_hermes_qualification.py, roadmap/features/add-hermes-agent-integration.md, and the directly affected Hermes paragraph in roadmap/scope.md. Temporary pinned upstream source/probes may be used outside live installations.","constraints":"Do not change shared Relay implementation, API/schema, persistence, scheduler, existing integration behavior, behavior contracts, dependencies, CI, or installed environment. No Hermes installation, paid inference, live service changes, or shared local full-suite qualification slot. Use one cheaper-model source researcher; parent reviews evidence. Stop this slice at a documented capability decision; missing public APIs are blockers, not permission for private host mutation.","completion_criteria":"Pin the release/source revision; probe the public identity and request/admission seams where executable without installation; include negative controls for unsupported identity/admission assumptions; record exact evidence level and unresolved host qualification; preserve the reliability integration/release gate in the canonical roadmap; publish a reviewable isolated slice with focused checks and required whole-change validation."}

**Risk:** Routine

**Complexity:** Moderate

**Reason:**
Fresh Redline over the whole intended path set is blue with no boundary violations. This is isolated qualification tooling and documentation; uncertainty spans external host identity and middleware semantics, requiring expanded recovery/evidence notes.

**Discovery:**
Hermes v0.22.2 remains the latest published release on 2026-10-19, exact revision d923a5eb487a17c0a68801bba9ef0f56c81040a8. Prior inspection established public injection, turn hooks, reset route reuse and queued-intent retirement, but not per-tool session propagation or final request admission. PR314 currently owns shared Relay/API/storage recovery changes; PR297/306 own OpenCode work. The initial feature's blanket wait gate is stricter than the newly authorized isolated parallel slice. The shared checkout has unrelated dirty incident notes and temporary files; all are preserved.

**Material assumptions:**
Actual released code can be inspected and some relevant primitives executed with existing standard-library/test tools in a disposable source/profile context. Missing imports or a missing supported API disprove executable feasibility for that seam: record the limitation, do not install dependencies, fabricate runtime proof, or patch Hermes internals. Any shared-core requirement remains deferred until the reliability owner supplies the merged contract.

**Plan:**
1. Invoke Agent Workflow, evaluate applicability, and create this Work Record before implementation (done).
2. One cheaper-model read-only researcher inspects exact tagged public tool-context and execution-middleware APIs and identifies minimal runnable upstream seams; parent verifies conclusions.
3. Add only a small reproducible qualification probe and meaningful positive/negative tests supported by those findings. Use actual pinned source functions when possible and label extracted-function or synthetic checks explicitly. If no useful executable seam exists, record that blocker rather than constructing a fake integration.
4. Record the bounded decision and next permitted slice in the canonical feature; allow isolated preparation while shared integration/release remains gated. Keep board ordering unchanged.
5. Run focused probe tests without application conftest, fresh complete-change Redline/Workflow checks and the test selector. Request a safe local full non-slow-suite window through existing coordination rather than competing with reliability's reserved slot; run it once when assigned. Hosted CI remains separate required validation. Until required validation completes, retain the exact outstanding gate and do not declare Ready for review.
Key conventions: Python standard library first; no duplicate Relay queue/protocol; no production plugin or compatibility claim in this slice. Exact target paths are listed in Scope. Reassess before expanding them.

**Verification plan:**
When the probe receives pinned source, its report identifies exact provenance and evidence level -> local reproducible command with positive/negative controls and focused tests. When current identity or final admission cannot be proven, the report remains unqualified -> tests assert missing/replaced content and absent context fail closed rather than inventing identity. When qualification completes, the roadmap distinguishes completed preparation from unfinished integration -> metadata/section review and canonical feature diff. When publishing, the complete diff remains within Scope -> fresh Redline/Workflow, test-plan selector and required selected validation. No changes to tests/behavior_contracts: existing caller-visible requirements are preserved.

**Plan review:**
Self-review: Routine risk; all intended paths blue. Success includes an explicit negative feasibility decision. Actual host qualification is not inferred from source inspection or extracted-function probes. No application feature ships in this slice.

**Approvals:**
Not required at this risk level. User authorized parallel, budget-sensitive work on 2026-10-19; installed environment and shared Relay changes are outside scope.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Pickup: created an isolated managed worktree; whole-change applicability requires
  a Work Record because executable qualification tooling is intended. Fresh
  import-boundary report has no violations; Redline intended paths are all blue.
- Discovery: reused the prior source findings and checked current release/PR
  metadata. No existing research is being repeated unless needed to resolve the
  two outstanding feasibility questions.
- Source review: parent inspected the exact `invoke_tool` concurrent callsite,
  registry dispatch and middleware chain. Tool context is supplied from the
  owning agent; no explicit profile ID was found. Execution middleware can
  rewrite/short-circuit after the API observer. These are source findings, not
  actual-host qualification. The cheaper researcher now owns only the two probe
  code/test files; parent owns acceptance and documentation.
- Local tooling: apply_patch could not create evals/hermes's parent outside the
  default writable root. A narrowly scoped deterministic elevated write created
  only the intended README and parent directory; no error 1385 occurred.
- Coordination: the canonical Minimap association attached successfully as
  `work:v1:20d17af89e285e7039a2f7def9e5651f87fbfef7b9d4711c889d0004110ec578`.
  A single test-slot coordination request was saved for `@astra-reviewer` as
  `relay-msg-86d43a5d3b7f41449ef8b0463454a58a`. Delivery is pending/unconfirmed;
  no slot assignment or receipt is inferred.
- Probe implementation: the cheaper worker added only qualification.py and its
  focused test file, using deterministic writes after apply_patch could not
  create the parent directory. Parent review corrected the probe from the tool
  branch to the actual released LLM execution wrapper, expanded forged/empty
  context controls, replaced a mirrored-constant test with all-source hash-order
  validation, and verified cleanup of absent/None/existing module fixtures.
- Focused verification: six cases passed in 0.16 seconds with the actual pinned
  source supplied; all eight source-function assertions pass. No model, host,
  profile, or end-to-end Relay qualification is claimed. Parent reviewed the
  exact source callsite and final code. The test selector requires full validation.
- Test-slot status: a read-only snapshot of @astra-reviewer's completed turn
  confirms the request was forwarded to Pallium's manager. The coordinator
  explicitly reported no slot granted; manager confirmation remains pending.
  No local application suite has been started or existing test repeated.
- Earlier probe-development checks caught a missing class-extraction case and an
  invalid set containing a dict. Both were probe defects, fixed before final
  verification; neither is evidence of a Hermes defect.

## Evidence

Tested code revision: `684c9ddfec942bab099b9c3a593420c6dd2ea18c`.

- `python -m pytest --noconftest -q -n 0 tests/test_hermes_qualification.py`, with
  process-local `PALLIUM_HERMES_SOURCE_ROOT` pointing to the hash-pinned cache:
  **6 passed in 0.16s**.
- `python -m evals.hermes.qualification --source-root <pinned-cache>`: all eight
  checks true; `evidence_level=source_function_probe`, `qualified_host=false`.
- `python scripts/test-plan.py --base origin/main`: full lane,
  `python -m pytest tests/ -x -q`. **Not run** pending a coordinated local slot;
  this slice is not Ready for review and no PR/merge is claimed.
- Temporary source/risk evidence is under
  `%TEMP%\pallium-hermes-feasibility-01a1489e`. Source-function evidence is not
  actual host/profile/provider admission or E2E support.

## Recovery

The parent owns roadmap edits and acceptance. Blocking next action: obtain the
manager-confirmed full-local-suite window, run the selected full suite once,
inspect any failures without changing unrelated reliability behavior, then run
fresh whole-change governance and publish the isolated slice for review. The
coordinator forwarded the request; no slot is assumed. Branch and this committed
record preserve the exact pending state. The worktree is retained for that
validation and review, owned by this chat; it is not installed or shared with the
reliability workers. Full Hermes support remains unfinished.

## Result review

Parent reviewed the exact upstream callsite, final probe and tests. The first
worker draft used the tool-execution branch; the accepted draft exercises the
released LLM wrapper and chain. Negative controls distinguish observed input from
terminal execution and preserve fixture module state. Findings were addressed;
function-level evidence is adequate for this bounded primitive decision, but
full-suite validation and actual-host qualification are explicitly not satisfied.
