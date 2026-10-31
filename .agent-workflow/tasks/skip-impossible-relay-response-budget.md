# Skip Relay candidate work when no response can fit

<!-- agent-workflow:start -->
**Outcome:** A Relay turn whose positive response budget cannot fit even the empty response skips candidate selection and rendering while preserving its existing empty response and transactional fences.

**Target:** SQLite Relay turn response-budget admission.

**Scope:** storage/sqlite_relay.py, tests/test_agent_relay_e2e.py and this Work Record. Port only the demonstrated seven-line generic correction and its tests onto current main. Exclude installed-only timing, expiry-label, writer-owner and body-observation diagnostics.

**Constraints:** Preserve response/schema, eligible counts, registration/scope effects, claim-expiry checks, rollback, token/lease/attempt ownership, runtime behavior, structural enrichment and later claim/ACK. No budgets, assertions, protected tests, workflow configuration, dependencies, live installation, service, owner source/index or model/account settings change. Keep private paths, operational pointers and identity out of public artifacts. No historical cause or overall recovery claim.

**Completion criteria:** Positive budgets of one, below and equal to the empty response size execute no candidate scan or delivery render; above-boundary and unlimited budgets retain existing behavior. Four runtimes, Unicode/long payloads, unchanged pending state and later claim/ACK are covered through HTTP/read paths. Expiry at the new early return and flush rolls back existing/new/scope-change state. Structural reference refresh remains outside the claim transaction. Independent target review, required local/full/platform validation and the persistence checkpoint precede merge.

**Requirement baseline:**
{"source":"stable-impossible-budget-publication-handoff","outcome":"A Relay turn whose positive response budget cannot fit even the empty response skips candidate selection and rendering while preserving its existing empty response and transactional fences.","scope":"storage/sqlite_relay.py, tests/test_agent_relay_e2e.py and this Work Record. Port only the demonstrated seven-line generic correction and its tests onto current main. Exclude installed-only timing, expiry-label, writer-owner and body-observation diagnostics.","constraints":"Preserve response/schema, eligible counts, registration/scope effects, claim-expiry checks, rollback, token/lease/attempt ownership, runtime behavior, structural enrichment and later claim/ACK. No budgets, assertions, protected tests, workflow configuration, dependencies, live installation, service, owner source/index or model/account settings change. Keep private paths, operational pointers and identity out of public artifacts. No historical cause or overall recovery claim.","completion_criteria":"Positive budgets of one, below and equal to the empty response size execute no candidate scan or delivery render; above-boundary and unlimited budgets retain existing behavior. Four runtimes, Unicode/long payloads, unchanged pending state and later claim/ACK are covered through HTTP/read paths. Expiry at the new early return and flush rolls back existing/new/scope-change state. Structural reference refresh remains outside the claim transaction. Independent target review, required local/full/platform validation and the persistence checkpoint precede merge."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":["https://github.com/rore/Pallium/pull/381"]}

**Risk:** High

**Complexity:** Moderate

**Reason:** storage/sqlite_relay.py is red-zone persisted Relay lifecycle code with a persistence-review checkpoint. The production change is small, but early returns must preserve expiry and transaction rollback. Public-target and test-observer adaptation require independent assessment.

**Discovery:** Current main is 9382b95b6496967c043269c8bee832eefafccc97. The target already supplies zero-argument check_claim_expiry() and finalize() with in-transaction flush/expiry validation. The seven-line handoff uses a diagnostic stage argument absent here; omit only that argument. The frozen test file differs from main only by three new test definitions, but its work counters depend on an unpublished diagnostic attribute. Replace that test-only ownership check with a thread-local marker around the existing transaction context. Keep every behavioral assertion and original test body otherwise unchanged. RelayService.turn and the HTTP route remain existing callers; no export or API change is needed.

**Material assumptions:** The empty response size is a conservative lower bound: any added delivery envelope costs more than fewer remaining-count digits can save. The guard runs after existing registration/scope/expiry bookkeeping and eligible-count calculation, before candidate execution. If target review finds a response/fence difference or requires prior unpublished diagnostics, stop and return to planning.

**Plan:** First invoke Agent Workflow and record this classification before source/test edits. Obtain independent plan/target review. Add only the captured tests, adapting their ownership observer to the existing transaction context without production hooks, extra storage reads, clocks or locks. Run the four-runtime counter cases before the production edit and preserve the expected red result. Add the seven-line early return using the target's zero-argument expiry helper and existing finalizer. Run the new controls and affected E2E file, then the complete change selector and one required full non-slow suite in the existing isolated runtime with temporary fixtures outside Git ancestry. Reuse only source-compatible prior evidence, preserving overlap and limits. Run import/workflow/Redline checks and independent result review. Publish a separate reviewable PR, resolve every finding, satisfy the persistence checkpoint and merge only after current-head gates pass. No standalone diagnostic campaign or owner/local incident dependency.

**Verification plan:**
- Demonstrated needless work -> four-runtime pre-fix counter cases assert candidate/render 1/10 where the fixed contract requires 0/0; preserve the red outcome.
- Budget/lifecycle boundaries -> new HTTP cases for one/below/equal/above/unlimited, four runtimes, Unicode, maximum payload, readback of unchanged claims and later ACK.
- Transaction fences -> new early-return/flush expiry cases across existing, new and moved-scope sessions; compare full persisted state before and after refusal.
- Structural separation -> HTTP structural-reference mutation/readback and later claim/ACK controls.
- Target regressions and complete coverage -> affected E2E file, whole-change selector, required full non-slow suite once and normal current-head Linux/Windows CI.
- Structural and privacy obligations -> import boundaries, Redline, Agent Workflow and review of added public content.
- Final acceptance -> independent result review, explicit persistence checkpoint and settled inline findings; no installed acceptance inference.

**Plan review:** Agent technical review: independent publication_review returned PLAN GO at 0fc66871 on main 9382b95b. The empty-response bound holds because count-digit savings are at most one per added delivery and every delivery envelope costs substantially more; false has_more is longer. The target check_claim_expiry() and finalize() preserve pre-mutation and flush-expiry rollback. Earlier OpenCode replay and absent/inactive no-registration returns remain unchanged; structural enrichment stays after storage transaction exit. No PR #381 or unpublished diagnostic dependency exists. Test-only thread-local observation is accepted when set after acquisition and its prior value is restored in finally; it observes transaction-body work, not lock duration. Require the four-runtime red controls, 11 new cases, affected file, selected full validation, normal CI and final review. High/Moderate and the separate persistence checkpoint remain binding.

**Approvals:** Approved by user in the standing incident directive (timestamp unavailable): "yes, i approve, and no need to ask every time - i approve all the work to get this bug fixed". The task owner separately authorized publication validation, push and merge of demonstrated fixes; the stable packet explicitly carries manager-authorized separate publication. This bounded optimization preserves the accepted caller contract and excludes every live environment action. Independent technical review and the separate persistence result checkpoint remain required; implementation authority is not checkpoint satisfaction.

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Captured only the immutable patch, installed candidate and frozen E2E test packet with matching SHA256 identities and unchanged source bytes before/after capture. The port was implemented in an isolated branch after independent plan approval. No current owner workspace or installed-only diagnostic is used as the publication source.

Independent plan review is GO before source/test edits. The test observer will restore its prior thread-local value on every exit. Standing human implementation authorization remains separate from the final persistence checkpoint.

The three captured test definitions were ported with only the reviewed transaction-body observer adaptation. Before the production change, all four runtime cases failed at the expected counter assertion: one candidate scan and ten delivery renders instead of zero, with the production file unchanged. The seven-line guard is now ported using the existing zero-argument expiry check and finalizer. No installed diagnostic or other production line is included. The red evidence is preserved separately from subsequent validation.

All 11 new controls passed in 8.06 seconds. The affected E2E file then passed 117 with one existing skip in 60.36 seconds. Independent source review is GO for production SHA256 `cb48f616a194ec0d5115d86fb82fa048ddd24f91b9b8082f82531c2df71e405f` and tests `dcf631896a80dd9966666ffb58a9e368967a376e07faf8b93130959235eb0181`. The reviewer independently confirmed that all existing test-module AST nodes are unchanged after removing exactly the three new definitions. The test observer covers transaction-body work only. Whole-change selection requires the full lane; one full non-slow execution is next, preserving all results and source/config identity.

The single required full non-slow run completed normally with exit zero: 8,505 passed, 37 skipped and two xfailed over 8,544 unique cases in 625.78 seconds. All 11 new controls passed within that run. Before/after/current hashes match for all 976 source/config files; temporary fixtures were outside Git ancestry. The affected-file skip is the existing Hermes process-boundary case requiring a disposable GitHub runner, not new feature coverage. Import boundaries and the added-content privacy scan passed. Local workflow checks report only the unsatisfied persistence checkpoint as advisory under current policy. State remains Blocked on current-head platform qualification, final findings and the separate human persistence result review; passing local tests do not satisfy those gates.

## Result review

Agent technical review: independent publication_review returned LOCAL RESULT GO after independently checking the final raw XML, manifest, source identities and focused/full coverage relationships.

Reviewed revision: `88f5a3e6afe2910c8ce8fb597bb0f7c63b000968`.

Verification adequacy: normal termination and exit zero are verified; raw XML contains 8,544 unique terminal cases with 8,505 passes, 37 skips and two xfails. All 11 new cases pass and the focused/affected/full identity sets nest without duplicate cases. All 976 source/config hashes match the full run's before/after maps. Four preserved pre-fix failures show exactly one candidate scan and ten renders where the fixed contract requires zero. The seven production lines and test-only observer adaptation are source-reviewed; no protected test or prior assertion changed. This is adequate for separate PR/current-head platform qualification. Final platform CI, findings and human persistence checkpoint remain mandatory; no installed recovery or historical-cause claim follows.

## Prior evidence and limits

Installed candidate SHA256 `66631801e5f44232fb179f2e1332f0fafa76136720151784e049798109776442`; frozen tests `5ac43437cea8c6c93611b4f18a7f5cc2df4324e116e17a3116633e717f0a1c55`; normalized patch `6fff6faf36025be4f6dd53904fba28d2c584d2232e50f231ef0fac0a8342f3c2`. The handoff reports 34 affected HTTP passes and 15 exact-installed-dependency passes that overlap those 34. These are not 49 distinct cases or complete public-target qualification. The port changes test observation and the target helper call, so destination validation is required. The source demonstration establishes unnecessary candidate work under an impossible budget, not historical writer ownership, latency cause or overall recovery.
