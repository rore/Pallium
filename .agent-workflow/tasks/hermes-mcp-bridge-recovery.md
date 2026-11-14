# Hermes dedicated MCP bridge recovery

Canonical identity: `agent-workflow:hermes-mcp-bridge-recovery`.
Current branch: `feat/hermes-mcp-bridge-recovery`; continuation base: `93f497bf0eed29659630c277626d821d24964524`.
Historical source branch: `fix/hermes-mcp-bridge-recovery`; preparation base: `d7ecc2b2b89624ef8444934e0332f930b9894f84`. The historical checkout and branch remain untouched.

Current phase: first regression AUTHORED, unexecuted. Standing-architect technical PLAN GO is confirmed for the exact original record SHA256 e6f28a98c4b07cd82d5a2f5f4e77dd6d883efc0a2f2c9242d297660863c46a6d; Elevated/Moderate is validated. This source-only milestone is ready for the existing source/actual-RED gates. Product implementation still requires actual accepted RED. No new human source approval or generic re-plan is required.

<!-- agent-workflow:start -->
**Outcome:**
Retire an unusable dedicated Hermes MCP transport safely so a later independent call can reconnect, without replaying a possibly committed operation or changing trusted identity, fixed scope, private receipts or host authorization.

**Target:**
Pallium native Hermes plugin-owned MCP connection lifecycle.

**Scope:**
Isolated source preparation and, after the existing technical plan gate, integrations/hermes/mcp_bridge.py plus directly affected caller-surface tests in tests/test_hermes_bridge.py and tests/test_hermes_mcp.py and this Work Record. Preserve existing reply-contract work and independently owned runtime reconciliation.

**Constraints:**
Never replay a queued or possibly committed operation. Preserve immutable per-call identity/scope/receipt metadata, tool restrictions, private visibility, memory opt-in and SDK wire compatibility. Dispose only owned resources; terminal close cannot reconnect. Continue only in the new isolated current-main checkout; do not change the historical checkout, branch or role name. No local app/test imports, tests/collection/setup/probes, host/profile/service/installed/config/model/effort changes, upgrades, protocol/guardian/framework, legacy MCP setup, new workers or native-host qualification. Ordinary source review, publication, existing hosted CI and later merge are task-owner-authorized, subject to the existing gates. No product implementation before accepted actual RED. Do not weaken protected contracts or claim the initiating cancellation race is proven.

**Completion criteria:**
A real bridge/stdio/HTTP/storage regression observes one mutation followed by transport failure and an explicit uncertain outcome, then a separate caller reconnects with its own immutable binding without replaying the first mutation. Cover unusable transport, partial startup/cleanup/reconnect failures, concurrency and stale generations, close/unload, catalogue restrictions, Unicode and repeated recovery. Independent review and later authorized existing CI establish runtime qualification separately from static source evidence and installed adoption.

**Requirement baseline:**
{"source":"manager-adopted dedicated Hermes MCP bridge recovery offer; source-only preparation","outcome":"Retire an unusable dedicated Hermes MCP transport safely so a later independent call can reconnect, without replaying a possibly committed operation or changing trusted identity, fixed scope, private receipts or host authorization.","scope":"Isolated source preparation and, after the existing technical plan gate, integrations/hermes/mcp_bridge.py plus directly affected caller-surface tests in tests/test_hermes_bridge.py and tests/test_hermes_mcp.py and this Work Record. Preserve existing reply-contract work and independently owned runtime reconciliation.","constraints":"Never replay a queued or possibly committed operation. Preserve immutable per-call identity/scope/receipt metadata, tool restrictions, private visibility, memory opt-in and SDK wire compatibility. Dispose only owned resources; terminal close cannot reconnect. No host/profile/service/installed/config/model/effort/cwd changes, app/test imports, tests/collection/setup/probes, upgrades, protocol/guardian/framework, legacy MCP setup, new workers, manual qualification, push or merge. Do not weaken protected contracts or claim the initiating cancellation race is proven.","completion_criteria":"A real bridge/stdio/HTTP/storage regression observes one mutation followed by transport failure and an explicit uncertain outcome, then a separate caller reconnects with its own immutable binding without replaying the first mutation. Cover unusable transport, partial startup/cleanup/reconnect failures, concurrency and stale generations, close/unload, catalogue restrictions, Unicode and repeated recovery. Independent review and later authorized existing CI establish runtime qualification separately from static source evidence and installed adoption."}

**Behavior changes:**
[{"classification":"equivalent","target":"task-context.constraints","before":"Never replay a queued or possibly committed operation. Preserve immutable per-call identity/scope/receipt metadata, tool restrictions, private visibility, memory opt-in and SDK wire compatibility. Dispose only owned resources; terminal close cannot reconnect. No host/profile/service/installed/config/model/effort/cwd changes, app/test imports, tests/collection/setup/probes, upgrades, protocol/guardian/framework, legacy MCP setup, new workers, manual qualification, push or merge. Do not weaken protected contracts or claim the initiating cancellation race is proven.","after":"Never replay a queued or possibly committed operation. Preserve immutable per-call identity/scope/receipt metadata, tool restrictions, private visibility, memory opt-in and SDK wire compatibility. Dispose only owned resources; terminal close cannot reconnect. Continue only in the new isolated current-main checkout; do not change the historical checkout, branch or role name. No local app/test imports, tests/collection/setup/probes, host/profile/service/installed/config/model/effort changes, upgrades, protocol/guardian/framework, legacy MCP setup, new workers or native-host qualification. Ordinary source review, publication, existing hosted CI and later merge are task-owner-authorized, subject to the existing gates. No product implementation before accepted actual RED. Do not weaken protected contracts or claim the initiating cancellation race is proven.","reason":"Task owner explicitly authorizes an isolated current-main continuation and ordinary source/review/hosted-verification/publication/merge. This changes execution authority and source custody only, not the required product behavior, non-replay guarantees, accepted plan or RED gate. The immutable original baseline and historical evidence remain preserved."}]

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-hermes-agent-integration"}],"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:**
The intended bridge path is unclassified/gray under the existing policy; tests and this record are blue. This owns connection lifecycle, not authorization, receipt or persistence policy. Moderate reflects bounded single-integration concurrency/cleanup uncertainty. The standing architect validated Elevated/Moderate for the reviewed plan. Any necessary red-contract/security/persistence or host-authorization change returns the slice for owner reassessment. No executed Redline verdict is claimed.

**Discovery:**
At the exact base, _serve publishes _session/_ready then waits only for _stop (integrations/hermes/mcp_bridge.py:154-177). _call reads self._session when executed (179-182). call guards cached readiness and schedules outside its try block (184-216); generic call failure does not invalidate the session, while a finished owner is refused permanently. A closed-loop scheduling error can escape before the handler. close has one-thread disposal but no terminal-close/reconnect coordination (223-231). These observations explain the lifecycle gap, not the initiating SDK cancellation/double-response race. Existing SDK probes check normal wire/catalogue/identity behavior, not dead-transport recovery or non-replay. Plugin middleware/profile/active-scope/private-receipt gates remain unchanged.

**Material assumptions:**
1. Supported SDK stdio/session async contexts can close and recreate owned resources with the same immutable configuration. If termination cannot be established, fail closed rather than start an overlapping replacement; do not patch protocol or private SDK internals.
2. Reconnection retains the registered catalogue contract. A normalized visible catalogue/schema mismatch fails closed; use no compatibility engine, silent host-tool re-registration or memory/scope expansion.
3. A structured tool refusal is not dead transport. Classify supported transport/scheduling failures without inspecting private error text; a queued failure may follow commit.
4. Existing real stdio/HTTP fixtures suffice without depending on unpublished reply-contract source. Return a specific seam gap if disproved, not a new harness or canned success.

**Plan:**
1. Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit. Completed through the documented native-file fallback for this source-preparation milestone.
2. Manager routes this bounded lifecycle/first-regression delta to the standing architect; reuse the incident assessment and existing process. No worker or repeated generic investigation. No product/test implementation before the applicable technical plan verdict.
3. After that verdict, establish the baseline under the existing Workflow and author the first deterministic caller-surface regression below. Static-only locally. Obtain and review actual valid RED only through a separately authorized existing execution path; unexecuted source/setup/collection failure is not RED.
4. After accepted RED, implement the smallest bridge-owned lifecycle: immutable construction configuration, atomically captured connection generation and per-call metadata, single-flight retirement/reconnect and terminal close. Reuse asyncio/threading/SDK ownership; no supervisor/retry framework or health probes.
5. Submit each scheduled invocation at most once. Timeout or transport uncertainty retains an explicit unknown-outcome error; never resubmit that invocation. Only a later independent caller can use the next connection after positive old-resource closure. Keep healthy structured tool errors usable.
6. Fence late failure/completion/cleanup by exact generation; coalesce overlapping reconnect attempts and preserve every caller's copied identity/arguments/private-reply metadata. Terminal close prevents resurrection. Never join while holding a lock needed by the owner; unresolved cleanup prevents overlapping replacement.
7. Complete the matrix below, preserve existing controls, run allowed static checks and return actual result material for existing independent review. Publication/execution remain excluded until their separate release; later ordinary existing CI supplies runtime evidence. No installed adoption.

**Verification plan:**
- Non-replay/recovery -> proposed test_bridge_transport_failure_after_commit_is_not_replayed_and_next_call_recovers_e2e: one actual stored message/HTTP mutation, uncertain first result and successful separate call on a fresh connection.
- Unusable owner/scheduling -> proposed test_bridge_unusable_transport_recovers_for_next_call_e2e: finished/closed-loop/EOF cases, bounded explicit result, no leaked scheduling exception or unawaited coroutine.
- Immutable binding/concurrency -> proposed test_bridge_recovery_keeps_each_call_binding_e2e: distinct Unicode identities, caller-dictionary mutation after snapshot, private-reply isolation, simultaneous recovery and stale-generation completion.
- Ownership/terminal close -> proposed test_bridge_recovery_closes_owned_generations_e2e: partial startup, failed cleanup, repeated close and close during recovery; exact acquired handles must finish, with no resurrection or overlapping successor.
- Wire/error/catalogue -> retain existing catalogue and response tests and test_bridge_stdio_call_on_supported_sdk; add structured-error/no-reconnect and incompatible reconnect-catalogue controls. Missing SDK2 execution is not compatibility proof.
- Whole change/privacy -> baseline/context agreement, AST/source-boundary checks, unchanged existing-work fingerprints, whitespace/disclosure checks and existing validation selector. Static evidence does not discharge RED/GREEN or remote gates.

**Plan review:**
Agent technical review: standing-architect technical PLAN GO confirmed through the manager's source release for the exact original record SHA256 e6f28a98c4b07cd82d5a2f5f4e77dd6d883efc0a2f2c9242d297660863c46a6d, with Elevated/Moderate validated. Author only the first regression after recording the concrete setup/identity/non-replay clarifications below. Product implementation remains excluded until actual valid RED is obtained and accepted through the existing gates. This is not runtime, installed or publication release; no helper is dispatched.

**Approvals:**
The original Elevated/Moderate plan remains accepted. The task owner now explicitly authorizes isolated current-main continuation: "You may ACCEPT continuation in a NEW isolated branch from current main93f497bf." The current milestone is "fresh-source compatibility + source-only adoption of the existing first regression and canonical record, then same current architect's bounded ACTUAL SOURCE assessment (reuse accepted plan, no generic replan)." Ordinary source/review/hosted verification/publication/merge authority does not authorize local execution, installed changes, old-checkout custody or product implementation before accepted actual RED.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Initial preparation checkpoint — historical

Created an isolated branch at the exact preparation base without moving shared HEAD or copying another task's dirty files. Read actual Workflow/config/risk/template and bridge/caller/test sources before this record. That initial milestone wrote only the record and was blocked on technical plan review. The verdict has since arrived; the current product hold is actual accepted RED, not the completed plan review, and never blocks runtime-source reconciliation.

## Smallest contract and mechanism boundaries

- Handshake readiness is not permanent usability. Separate usable connection ownership, immutable per-call capture and terminal bridge closure.
- Retire/recreate only owned SDK stdio/session/context/thread resources with unchanged construction configuration. No service probing, process discovery, plugin reload or shared environment change.
- Capture values, session/turn and private reply metadata before waiting for recovery or crossing the loop. Never inherit an old call's identity or replay its tool operation on a successor.
- Preserve the timeout warning that the operation may have committed. Other queued transport failures must also express uncertainty without private exception/receipt text. Known pre-dispatch refusal must not claim a commit.
- Close is terminal/idempotent. A stale callback cannot clear a successor. Unresolved disposal must be reported, not called successful recovery.

## First regression — authored, not executed

Authored node: `tests/test_hermes_mcp.py::test_bridge_transport_failure_after_commit_is_not_replayed_and_next_call_recovers_e2e`.

1. Reuse the existing client fixture and tests/test_hermes_mcp.py::_RelayHandler forwarding proxy with the SAME real API/storage. Start an actual RelayMcpBridge through its normal SDK stdio contexts in one anonymous private scope. The _RelayProxy in test_hermes_bridge.py returns canned session rows; do not use it as persistence proof.
2. Normally register the sending Hermes endpoint and recipient through the public turn API. Explicitly use that registered Unicode recipient as the later independent address caller; address lookup does not register an unknown session. Call a real send WITHOUT a caller-supplied message_id/idempotency key, since server deduplication could hide replay. Independently count actual send HTTP mutations and persisted messages.
3. A fixture-local forwarding wrapper at the SDK call boundary first awaits the real send's completion, then raises a controlled transport exception and leaves that exact session unusable for later calls. It must not fabricate results, seed authority or bypass the operation. This deterministic injected stale-session case is not proof of real EOF or the original SDK failure cause.
4. Through ordinary peer/status readback, assert exactly one matching persisted message and one send HTTP mutation. The failed invocation must report uncertainty, not fabricate success.
5. Make a separate read-only address call as the already-registered Unicode recipient with a distinct Unicode turn. Assert that exact session_id AND turn_id at the SDK metadata boundary, plus fixed scope in the dispatched arguments; the address response proves session, not turn. Require a fresh usable connection, exact returned identity and unchanged private scope. Poison only the original failed session, never replacements. Assert one send dispatch/HTTP mutation and one persisted message before and after recovery.
6. Track every acquired thread/context/connection, including partial construction. Retire callbacks before proxy/client teardown, attempt every cleanup and assert bounded joins actually exit. Retain body/startup/cleanup failures together. Both retired and replacement owners must dispose at final close.

Source-predicted RED: the baseline exception branch leaves readiness/session intact, so the separate call reuses the poisoned session and fails the fresh-call assertion. This is not an observed RED. Setup/admission/dependency/collection/timeout/cleanup failure or skip is not valid behavioral evidence.

## Remaining coverage — not waived by the first regression

| Interaction | Required observable assertion |
|---|---|
| Healthy repeated calls | No unnecessary reconnect; existing result/error/catalogue contracts stay intact. |
| Real stream EOF, finished owner, closed loop | Bounded recovery/refusal, no leaked scheduling exception/coroutine; supplement injected-error coverage using only owned supported stream/context handles. |
| Failure before/after scheduling, timeout/cancellation | At most one dispatch; truthful unknown outcome; no automatic current-call replay. |
| Structured tool/application errors | Do not retire healthy transport; private response details remain hidden. |
| Concurrent callers/recovery | Single replacement, distinct immutable caller metadata and no duplicate request. |
| Late old-generation completion/failure | Cannot retire, clear or contaminate a successor. |
| Reconnect timeout/partial startup/catalogue mismatch | Dispose all acquired resources; no unsafe fallback, tool re-registration or memory expansion. |
| Close/unload during active work/recovery | Terminal, idempotent, bounded cleanup; no resurrection; uncertain outcomes retained. |
| Cleanup failure | Fail closed to overlapping replacement; preserve primary and cleanup errors. |
| More than two failure/recovery cycles | Isolated generations, no replay, full create/use/retire/dispose journey. |
| Unicode/invalid binding/argument mutation | Exact valid text and copies, unchanged identity/scope/receipt refusal. |
| Optional memory/SDK wire variants | Existing opt-in and aliases; no unqualified interpreter/setup or skip-as-proof. |

## Existing controls and scope preservation

Keep integrations/hermes/__init__.py profile/trusted middleware/active-scope/admission/private-receipt checks and unload registration unchanged. Existing plugin controls include test_packaged_mcp_preserves_authorization_and_clears_binding, test_packaged_mcp_binds_each_conversation_and_never_model_identity and test_packaged_mcp_reply_receipt_stays_in_host_memory. Their fake bridge constrains unchanged host behavior, not recovery E2E.

The SDK probe uses bridge.catalog, bridge.call, bridge._call and close. Preserve caller compatibility or make only an affected internal-test adjustment without weakening wire/authority assertions. No new public retry protocol or shared SDK upgrade.

## Evidence, roadmap and result limits

This is source/static preparation only: no app/test imports, collection, tests, bridge subprocesses, live probes, setup or restarts. No observed RED/GREEN, disposal result, full qualification or installed behavior is claimed. Incident evidence is retained privately and not reinvestigated; initiating race causality remains unproven.

Initial preparation static checks passed: the original Requirement baseline exactly matched all four Task Context fields; expanded classification/state/first-step fields parsed correctly; the record contained no private local path or session identifier. The bridge, plugin caller, SDK bridge test, MCP test and Relay plugin test parsed as AST and their explicit working-source text matched the exact base after line-ending normalization. All five existing reply-contract contribution files retained their previously recorded raw SHA256 fingerprints. These were focused source checks, not a whole-tree cleanliness assertion, application execution or observed RED. Existing named plugin controls were resolved from actual test definitions. No product/test source had been authored at that initial checkpoint; the current authored-source result follows below.

The existing active item is roadmap/features/add-hermes-agent-integration.md. Manager owns shared roadmap and broader documentation/adoption. The exact supplied Minimap tuple is captured in Relationships by the supported Workflow establish-context copy/save/readback procedure; no identity is derived from a title, branch or path. Optional Relay association is separate from this capture and is not claimed. Preserve reply-contract source/record/docs/tests, the delivered read-only seven-path report, paused selected-workspace work and the independently progressing runtime reconciliation. This contribution does not gate those tasks or the merged OpenCode fix.

## Recovery / handoff

Technical PLAN GO has arrived and the first-regression source is authored in tests/test_hermes_mcp.py, reusing its real forwarding handler and existing client/storage; integrations/hermes/mcp_bridge.py and every other product file remain unchanged. Retain the small owned-connection identity fence, standard synchronization/SDK ownership, normalized-catalogue fail-closed and terminal-close plan. The next action is the existing source review and separately authorized actual-RED milestone, not another plan verdict or more first-test authoring; no product code before accepted RED. No new worker, permission exchange, local execution, commit, push, merge or installed change is authorized. Retain this checkout for review and the subsequent authorized phase.

## First-regression authoring checkpoint

Before the first test edit, read the actual bridge/stdio/HTTP fixture surfaces, Workflow relationship procedure, canonical item and dependency manifest. Verified the reviewed original record hash and captured raw protected-source fingerprints, all five PR400 fingerprints and the selected-workspace regression fingerprint. The only planned writes are this record and tests/test_hermes_mcp.py. The test will forward real SDK stdio calls to the real HTTP/storage fixture, inject failure only after a successful original-session send, and use local public SDK context/thread wrappers for exact owned-resource cleanup. Post-success injection is not genuine EOF or proof of the initiating race. Runtime reconciliation, its CI/matcher correction and other tracks are untouched.

## First-regression source result — no observed RED

Authored joined_bridge_recovery_context and the single node above in tests/test_hermes_mcp.py. The fixture subclasses the existing real forwarding handler, uses the normal RelayMcpBridge and SDK stdio/session contexts, and tracks directly owned bridge/request/listener threads and public SDK context handles, including partial construction. Cleanup attempts every owner, asserts bounded joins and completed SDK context exit, and preserves setup/body/teardown failures. It does not enumerate unrelated threads, patch SDK internals, seed registrations or return canned protocol results.

The sender and Unicode recipient are registered through /relay/turn before any send; the recipient explicitly doubles as the later independent caller. Both sender and later exact session/turn metadata are asserted at ClientSession.call_tool, independently of the address response. A real successful send is followed by a controlled ClosedResourceError, poisoning only that exact SDK session. Calls on a replacement still forward normally. SDK dispatch and successful HTTP response counts, exact message status and paginated message-list readback require one actual mutation and one persisted message before and after the later call. The caller supplies no message_id. The existing HTTP client generates a fresh UUID per tool invocation; its generated identity is checked against persistence rather than incorrectly assumed absent at HTTP. Multiple HTTP attempts require prerequisite/replay disposition and are not automatically valid RED.

The baseline-predicted decisive assertion is tests/test_hermes_mcp.py:576: a separately registered caller must receive a usable address rather than the original poisoned-session error. All registration, post-success injection, persistence/non-replay and later SDK turn checks precede that assertion. After recovery, the test additionally checks truthful first-call uncertainty, exact returned identity/fixed scope, distinct SDK session, real address HTTP read and positive old-context exit before successor entry. On the current unchanged bridge, cached _session/readiness remain set after the injected call exception, so the later invocation is predicted to fail there. This has NOT been executed or observed; failed setup, dependency/collection, skipped coverage, multiple prerequisite HTTP attempts or cleanup failure is not accepted behavioral RED. The post-success injection proves neither genuine EOF nor the original cancellation/double-response cause.

Actual static checks: AST parsing and comparison preserve all20 existing top-level test/helper/class definitions; only one fixture and one regression are added. The original Requirement baseline and all four Task Context fields remain unchanged. Relationships was saved and read back as the exact supplied provider/scope_ref/local_ref tuple under Workflow's supported procedure. Nine protected bridge/caller/test/roadmap files, all five PR400 contribution files and the selected-workspace regression retain their pre-edit raw hashes. Git whitespace checking passed. These are source checks only, not test execution or runtime qualification.

Test source SHA256: 2f0679c6c62b1d41dd3f2dce5b407f235dce47c3b55defd4046ecc57180aeed4. State is Blocked specifically on the existing source-review/authorized actual-RED milestone and its acceptance before product implementation, not a renewed plan/human-permission gate. The broader concurrency, catalogue-failure, SDK ownership and terminal-close matrix remains unchanged and unwaived. No product source, runtime checkout, installed/profile/settings/model/cwd state, new worker, commit, push or merge was changed. Manager owns the next existing source/RED gate; retain this checkout and all other tracks.

## Isolated current-main continuation — 2026-11-14

The preceding checkpoints describe the original source contribution, not current execution or a completed custody transfer. The task owner chooses reuse in an independent checkout instead of modifying the historical owner's checkout. The current developer owns only this continuation. No prior owner is declared stopped; no role name or old remote branch is transferred. Earlier unadmitted review dispatch is not retried, rerouted or counted as review. The current architect's bounded source assessment is a new assignment under current team authority.

Invoked Agent Workflow before the first continuation edit. Its resolver preserves `agent-workflow:hermes-mcp-bridge-recovery` verbatim and locates this same record path; both branch prefixes derive that slug. The carried original record has SHA256 `9b68480b2315c54831c30a0f5f592d84a412b3387daddd3418b0a5e072b57a79`; the untouched saved test has SHA256 `2f0679c6c62b1d41dd3f2dce5b407f235dce47c3b55defd4046ecc57180aeed4`. Preserve the original Requirement baseline verbatim. The only planned source adoption is that exact existing fixture/regression/import delta, not other dirty or reply-contract work.

Compatibility discovery: committed bridge, plugin caller, MCP entry/client, original MCP tests, client fixture and dependency manifest are unchanged between the original preparation base and current `93f497bf`. Read the actual plugin construction/unload/trusted call path and the SDK-to-HTTP send/address/readback path. The forwarding helper, identity shape, generated per-invocation send ID and normal storage read surfaces still match the saved regression. Keep the same accepted Elevated/Moderate classification: current intended bridge path remains gray; tests and this record are blue. No protected contract changes or boundary crossing are intended.

Minimap resolved the owning item afresh from the shared roadmap checkout; the exact tuple matches Relationships. Manager retains shared-roadmap ownership. Current roadmap prose still describes a custody hold; the manager must narrow that hold to old-checkout mutation after accepting this isolated contribution, without claiming recovery or closing the feature.

Next: adopt only the saved source delta, validate syntax/unchanged definitions/baseline chain and preserved hashes without imports, then obtain the existing current architect's actual-source assessment. Product implementation remains Blocked on accepted actual RED. Inspect existing hosted workflow selectors before publication/dispatch; do not add a runner or treat setup failure, skipped coverage or teardown failure as behavioral RED.

### Adoption evidence and existing execution seam

Adopted only the original imports, `joined_bridge_recovery_context` and first regression into `tests/test_hermes_mcp.py`. Normalized source text exactly matches the preserved saved test; all 20 existing top-level definitions remain AST-identical to current main. In-memory AST compilation passed without importing or executing application/tests. Original two raw hashes remain unchanged. Adopted test raw SHA256 is `fa14fb9c5ddbbd18058e9ed1465022a19764670eb875b3ae78c065aad9b72359`; the raw difference from the saved test is line endings only. Requirement baseline is verbatim, its constraint-change chain ends at current Task Context, and the exact Relationships tuple passed readback. Privacy and whitespace checks passed.

Whole-change selector chose `full` for the two intended paths. Local tests remain prohibited and unexecuted. No product path is changed. Current architect source assessment is pending; no actual RED/GREEN or earlier review is claimed.

Inspected the existing hosted workflow inputs. `ci.yml` has no node/file/profile input: application/test changes select the existing full PR lane (Linux 3.12/3.13 and Windows smoke). Its manual dispatch is broader, also enabling full Windows, so it is not a smaller RED route. `hermes-native-qualification.yml` accepts only an immutable candidate revision and runs two 60-minute native-host jobs; it is not this bridge regression selector. The OpenCode-only qualification workflow is unrelated and must not be repurposed. The smallest currently supported route is therefore one normal draft-PR CI round after source assessment, inspecting this exact regression's JUnit/log failure and cleanup result rather than using aggregate CI failure as RED. No runner/workflow modification is proposed. Bound the observation/dispatch budget and stop on prerequisite or unrelated fail-fast gaps instead of blindly repeating unchanged runs.

## Implementation — continuation checkpoint

The two-path source-only adoption is complete; the current architect has been sent the exact source snapshot for its bounded assessment. That request is saved, not confirmed accepted or completed. The test source is frozen pending its substantive result. Shared-roadmap reconciliation remains with the manager. There are no local test results and no product changes.

The real local Workflow checker validated record shape, classification, baseline/change chain, Relationships and accepted plan reference. It returned blocking because this fresh checkout has no genuine Redline/versioned behavior-contract verdict artifact. No artifact was fabricated, copied from unrelated work or policy relaxed. The existing PR governance workflow produces that evidence through its actual boundary check; local compliance is not claimed complete. Draft publication must not be confused with merge acceptance.

Next action after actual-source GO: publish this test-only candidate as a deliberate RED draft and inspect the exact non-slow node on ordinary Linux CI, which already installs and verifies MCP. Prior unrelated fail-fast, skip, setup, teardown or missing-node results are not RED. Do not dispatch the manual full matrix or add a qualification workflow. Until the source result arrives, end the turn for supported Relay delivery rather than keep a polling/status loop alive. No old-owner/name transfer, environment operation or privacy-cleanup dependency is introduced.

## Result review — first-regression source adoption

The current independent architect assessed frozen `86be6218482c2d6b209b50162c239e7a9f979a9b` against `93f497bf0eed29659630c277626d821d24964524` and returned SOURCE GO with no blocking source finding. Reviewed Git blobs: test `7f006b190487acfe86bf15bffef190d3fadde02d`, record `21cbab979b674254b1ecd665a4f0ec93a118115a`, unchanged bridge `ecf533a32db1a9d1598eeeb1b519a5ee988dd8c9`. The full verdict was read through its final page. It accepts the real stdio/HTTP/storage path, post-success injection, independent mutation/readback counts, distinct Unicode caller/turn/fixed scope and owned cleanup assertions. It is source assessment only, not observed RED or qualification of the broader recovery matrix.

Proceed with the already-authorized test-only deliberate RED draft and ordinary automatic CI. Inspect this exact node's failure and prerequisites/readbacks/teardown; stop the observation at 15 minutes if it cannot yield valid subject evidence. The missing local genuine Redline/versioned verdict remains disclosed and is not waived by draft publication. Product implementation and merge remain held. No new review assignment, old-review replay, manual qualification, local application execution or environment change is authorized by this source verdict.
