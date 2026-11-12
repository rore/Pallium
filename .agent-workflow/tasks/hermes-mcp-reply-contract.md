# Hermes MCP reply caller contract

Branch: `fix/hermes-mcp-reply-contract`. Trusted source base: `16e5a2cc6f631f1556b9d7b99da8260d87b94a6e`.

Current phase: the task owner accepts the architect's corrected-delta PLAN GO and releases FIRST TEST-SOURCE implementation only. No mandatory plan corrections remain and no repeat plan review is required. Execution/setup and product changes remain held. The existing selected-workspace contribution retains its ownership and separate gates.

<!-- agent-workflow:start -->
**Outcome:**
Hermes MCP replies accept nonblank strings through 16000 Unicode code points and report caller-message errors separately without weakening reply authority or changing the legacy direct reply contract.

**Target:**
Pallium native Hermes reply adapter.

**Scope:**
Hermes MCP reply-message validation in integrations/hermes/__init__.py, directly affected caller-surface tests and their existing hook/middleware/bridge/stdio/HTTP fixture join, and this Work Record. Product and test edits require a separate implementation release; this submission contains only the source plan.

**Constraints:**
Preserve legacy direct payload acceptance at 2400 and refusal at 2401; do not globally raise MAX_REPLY_CHARS. Validate caller messages only after trusted host identity and registered active-scope gates. Invalid messages must not dispatch or consume/change admission. Valid messages still require the exact live session, turn, delivery and private receipt, with generic authority refusal preserved. Preserve downstream content validation, exact Unicode text and receipt privacy/lifetime/persistence/binding. Receipt 512/64 differences, generic Relay/core/server redesign, protected-test weakening, installed/host/skill/settings changes, setup, new workers or coding CLIs, publication and automatic rollout are outside scope. Existing execution controls and serialized-run holds remain; no dependent production before valid observed RED.

**Completion criteria:**
The reviewable plan names actual base anchors, the smallest adapter/test paths, an actual existing-fixture join, edge cases and exact proposed RED nodes. After separately authorized implementation and execution, admitted MCP messages at 2401 and 16000 code points yield exact peer-visible replies; 16001, empty, blank and non-string messages yield explicit argument failure without dispatch/admission consumption; an invalid call followed by a valid same-turn call succeeds once. Unicode limits count code points rather than encoded bytes. Wrong or ended turns, missing/failed admission, post-success replay and unload remain refused; legacy direct 2400/2401 behavior and downstream content validation remain unchanged. Fake-bridge assertions do not substitute for caller-surface E2E or independent review.

**Requirement baseline:**
{"source":"task-owner-adopted caller contract; source-plan-only continuation","outcome":"Hermes MCP replies accept nonblank strings through 16000 Unicode code points and report caller-message errors separately without weakening reply authority or changing the legacy direct reply contract.","scope":"Hermes MCP reply-message validation in integrations/hermes/__init__.py, directly affected caller-surface tests and their existing hook/middleware/bridge/stdio/HTTP fixture join, and this Work Record. Product and test edits require a separate implementation release; this submission contains only the source plan.","constraints":"Preserve legacy direct payload acceptance at 2400 and refusal at 2401; do not globally raise MAX_REPLY_CHARS. Validate caller messages only after trusted host identity and registered active-scope gates. Invalid messages must not dispatch or consume/change admission. Valid messages still require the exact live session, turn, delivery and private receipt, with generic authority refusal preserved. Preserve downstream content validation, exact Unicode text and receipt privacy/lifetime/persistence/binding. Receipt 512/64 differences, generic Relay/core/server redesign, protected-test weakening, installed/host/skill/settings changes, setup, new workers or coding CLIs, publication and automatic rollout are outside scope. Existing execution controls and serialized-run holds remain; no dependent production before valid observed RED.","completion_criteria":"The reviewable plan names actual base anchors, the smallest adapter/test paths, an actual existing-fixture join, edge cases and exact proposed RED nodes. After separately authorized implementation and execution, admitted MCP messages at 2401 and 16000 code points yield exact peer-visible replies; 16001, empty, blank and non-string messages yield explicit argument failure without dispatch/admission consumption; an invalid call followed by a valid same-turn call succeeds once. Unicode limits count code points rather than encoded bytes. Wrong or ended turns, missing/failed admission, post-success replay and unload remain refused; legacy direct 2400/2401 behavior and downstream content validation remain unchanged. Fake-bridge assertions do not substitute for caller-surface E2E or independent review."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:**
Architect-reviewed reassessment: Elevated is the unclassified/gray floor for the intended adapter path; ordinary test paths are blue. The change separates caller-message validation after unchanged trusted gates and changes no identity, scope, admission authority, receipt, lifetime, persistence or routing contract. Proximity to authority checks alone did not justify the initial High classification. Moderate complexity remains appropriate for the existing hook/bridge/stdio/HTTP fixture join and its cleanup. This replaces the proximity-only judgment, not the effective policy floor, and is not an executed Redline verdict.

**Discovery:**
The approved base combines MCP message and receipt checks at integrations/hermes/__init__.py:924-928 under legacy MAX_REPLY_CHARS; trusted host/scope gates are at901-920. Unlike the earlier shared-checkout analysis, this base uses batched per-delivery reply_receipt/settle_reply helpers at823-844; keep those unchanged. The real bridge/stdio/HTTP seams exist, but mcp_plugin_context at tests/test_hermes_relay_plugin.py:1766-1799 is a fake bridge, not joined E2E. Public guidance still describes all host-bound replies as 2400 (docs/hermes-integration.md:55-56; integrations/hermes/README.md:88-89), while app/mcp/server.py:2153 advertises16000. This documentation drift needs owner-managed reconciliation before delivery; no guide edits are included in this source-plan submission. No product/test code has been edited.

**Material assumptions:**
1. This is an integration-specific restoration of the adopted MCP16000 contract; the legacy2400 contract remains unchanged. If protected accepted requirements conflict, stop for task-owner resolution rather than weakening them.
2. Existing fixture seams can be joined without changing production bridge/context/server code. If the actual fixtures disprove this, return the plan for bounded review before expanding scope or inventing a harness.
3. The task owner has released only first test-source authorship after accepted corrected-delta PLAN GO. Application/helper imports, collection, tests, probes, setup and product edits remain unreleased. Plan GO is not observed RED or enforceable execution containment.

**Plan:**
1. Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit. The repository's documented native-file fallback is used; no application/runtime command is executed.
2. The original independent technical plan review and corrected-delta confirmation are COMPLETE, PLAN GO, accepted by the task owner. Preserve the settled contract/join/RED expectations; no repeat plan review.
3. Establish the unchanged public-safe Work Record baseline locally, then author only the joined fixture and three decisive caller-surface test nodes in tests/test_hermes_mcp.py. Execution remains held until separately accepted containment/interpreter/serialized slot. Unexecuted source or setup/collection failure is not RED.
4. Only after valid observed RED and release: separate MCP-only message validation from authority checks, without changing legacy constants or receipt/binding behavior; verify the joined caller-surface cases and preserved controls.
5. Obtain independent result review and owner-managed roadmap reconciliation after real authorized evidence. No commit, push, merge, live operation or worktree removal is currently authorized.

**Verification plan:**
- Source-plan milestone: read actual base fixtures and contract paths; verify isolated branch/base and that only this Work Record is changed; inspect the record for private disclosures.
- Future admitted 2401/16000 success and exact peer text: proposed test_hook_mcp_reply_message_contract_e2e below, with a fresh admission per case and actual bridge/stdio/HTTP/readback.
- Future explicit empty/blank/type/16001 failure, zero dispatch and same-turn recovery: proposed test_hook_mcp_reply_invalid_message_preserves_admission_e2e, using a forwarding spy on the real bridge plus ordinary peer readback; no fabricated bridge result.
- Future trusted-gate precedence, authority/lifecycle/batch privacy and preserved legacy2400/2401: the matrix and existing control nodes below; no private receipt or lifetime changes.
- Future whole-change selection, protected-contract verification and CI lanes remain required when applicable, but are not execution permission and have not run.

**Plan review:**
Original independent architect review and corrected-delta review COMPLETE: PLAN GO, accepted by the task owner; no mandatory plan corrections remain. Explicit admitted identity/identical SCOPE, actual bridge assertions, all-resource exception-safe cleanup/positive bounded joins and Elevated/Moderate rationale are accepted. Contract, real-transport join and RED expectations remain settled. Do not reopen either review. This is test-source permission only, not execution or product permission.

**Approvals:**
The task owner explicitly releases first TEST-SOURCE implementation in this existing checkout/record and establishment of the unchanged public-safe local record baseline. This covers only the smallest joined fixture and MCP2401/16000 success plus16001 explicit-error/same-admission-survival source cases. Full feature edge coverage remains required later. No execution/setup, application/helper imports, installs, new workers, product edits before valid observed RED, installed/skill/settings changes or publication is released. Existing conditional execution permissions/controls and primary ownership are unchanged; no duplicate approval request.

**Exceptions:**
None.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Prepared the isolated source branch at the trusted base without copying dirty files from the shared checkout. Created this expanded Work Record through the existing Agent Workflow procedure before any product/test edit. No product/test edit, import, test, setup, new worker or application launch has occurred.

Test-source checkpoint: invoked the existing Agent Workflow native-file procedure before edits; inspected current branch/base and existing fixtures. Retain Elevated/Moderate for the unchanged approved overall task; this first slice touches only blue test source and this record. Establish the first public-safe record-only local Git snapshot with the exact existing Requirement baseline before editing tests. Authorized target: tests/test_hermes_mcp.py only, plus checkpoint updates here; adapter and other tests remain untouched. No local test/setup execution or imports are released.

## Short fixture plan

### Minimal change and ordering

Planned application paths are only `integrations/hermes/__init__.py` and `tests/test_hermes_mcp.py`, plus this record. The legacy plugin tests, bridge/context/server/core, dependencies, shared conftest and protected contracts are preserved, not refactored.

After valid observed RED and release, add an MCP-only 16000 limit (a proposed new `MAX_MCP_REPLY_CHARS`, not an existing symbol). Inside `mcp_handler`, after the unchanged trusted identity and registered active-scope gates at901-920, reject non-string, empty/blank or over-limit `message` before calling `reply_receipt` or dispatching. Proposed public argument text for review: `Invalid reply message: expected a nonblank string of at most 16000 Unicode code points.` Valid messages then use the unchanged receipt lookup, generic authority refusal, bridge call and settlement. Do not raise global `MAX_REPLY_CHARS`, cast/trim/normalize accepted text, change receipt512/64 checks, or duplicate downstream content policy. Here, invalid caller messages means the local shape/blankness/length checks; server-only content validation remains authoritative downstream.

### Actual fixture join

Place the new E2E cases in the existing MCP test module, which already gates its MCP dependency at `tests/test_hermes_mcp.py:15`. Explicitly reuse `plugin_context` and hook helpers from `tests/test_hermes_relay_plugin.py`; do not import the fake `mcp_plugin_context` as the E2E transport.

1. Reuse `client` (`tests/conftest.py:26-68`) and `_RelayHandler` (`tests/test_hermes_mcp.py:29-59`) with that SAME client. Import the existing plugin fixture's `SCOPE` and use its identical container for sender/recipient registration, plugin config, real bridge/server and every peer readback; assert equality instead of mixing in the separate stdio test's scope. Follow the existing ephemeral-loopback HTTP lifecycle at214-257. Keep vector indexing disabled and all identities/data anonymous.
2. Before `register(ctx)`, use the existing fixture's in-memory config and temporary plugin-package seam (`plugin_context`:211-301; the relative bridge seam at1766-1799) to bind the ACTUAL `RelayMcpBridge` from `integrations/hermes/mcp_bridge.py:123-177`. A forwarding registration spy retains each fixture context before registration can fail; a forwarding constructor records real bridge objects for cleanup without substituting their behavior. Assert each returned object is an instance of the actual bridge class, `bridge.config[1] == SCOPE["container_ref"]`, and the reply entry in `bridge.catalog` exposes MCP `message`, not the legacy `payload` fallback. Set only disposable test config to the proxy URL, this source checkout, private scope and the already-qualified test interpreter. No real profile settings or installed interpreter. Let registration create the bridge once; never replace its call/response with a canned message ID.
3. Reuse `_plugin_wake`:417-442 and `_admit_plugin_wake`:552-558 to drive registration, injection, claim, request rewrite/execution and hook-owned admission. Explicitly bind `admitted_session = "ses_שלום"` and `admitted_turn = "wake"` for each fresh case; pass that session/turn to admission and EVERY `_mcp_tool` invocation, including invalid input, valid follow-up, status/address checks and replay. `_mcp_tool` defaults to DIFFERENT `session_שלום`/`turn-1`; never rely on those defaults. Authority-negative cases change only their explicitly named field; all other identity/scope values remain the admitted ones. No manually seeded receipt metadata or direct receive/ACK shortcut. Normal `tool_execution` supplies the explicit identity and the registered MCP handler supplies the receipt.
4. The unchanged real bridge copies metadata at184-214, starts `app.mcp.hermes` over stdio at154-177, and calls the real MCP tool at179-182. `_RelayHandler` forwards its HTTP request to the SAME real API/storage behind `client`. Assert exact reply text and source identity through the peer's ordinary `/relay/turn` and reply message/status read paths, with full payload budgets/pagination and no truncated preview accepted as success.
5. A forwarding spy counts real bridge entry while invoking the original method; `_RelayHandler.calls` observes HTTP mutations. The fixture retains exact owned contexts, returned bridge instances, proxy listener/request threads and plugin poller handles as they are acquired. Any thread-construction capture is forwarding and scoped to the test-loaded module/resource, not a global replacement or enumeration of unrelated processes. Assert a normal successful MCP call reached the captured real bridge, not a direct fallback.
6. Construct/start/yield/unwind inside exception-safe ownership. Snapshot and retire ALL test-owned `ctx.cleanups` entries before invoking callbacks, so the original fixture cannot re-run stale callbacks after proxy/client teardown. Attempt EVERY registered callback in its existing order even if an earlier callback fails; then attempt remaining owned bridge/stdio closure, proxy shutdown, server_close and each owned thread join independently in finally-style cleanup. Plugin/bridge callbacks retire BEFORE proxy teardown; proxy resources retire BEFORE the shared client. Track startup acquisitions and whether the proxy serve loop actually started; do not wait for shutdown of a loop that never started, but always attempt socket close. Preserve constructor/startup cleanup failures and report uncertain closure rather than manufacture success.
7. Every bounded join is followed by `is_alive()`/equivalent positive completion checks on its exact owned handle; a returned join alone is not success. Check the real bridge's `_finished`, `_thread` exit and `_failed` flag, plugin poller exit, and proxy listener/request-worker exit. A normal close return with a serve/cleanup failure flag is still a teardown failure; retain that signal without inventing a hidden exception cause. Keep real SDK stdio context cleanup rather than mock it. Collect ALL cleanup exceptions and non-exit assertions while continuing the remaining cleanup. The supported Python baseline is >=3.12: report aggregated cleanup failures with an ExceptionGroup/BaseExceptionGroup as appropriate; preserve the original construction failure with those errors, and let pytest retain any body failure alongside teardown failure. Never swallow cleanup errors or convert them to valid RED/GREEN. This fixture cleanup is NOT a substitute for independently accepted whole-run containment; no runtime guardian or production cleanup change is introduced.

This is caller-surface adapter E2E, not a real Hermes UI/resume qualification. Existing SDK bridge lanes stay required; a missing SDK2 interpreter/skip is not compatibility proof.

### Edge cases and preserved controls

| Case | Required observable assertion |
|---|---|
| Admitted sizes 1, 2400, 2401, 15999, 16000 | Fresh admission each; one accepted reply and exact peer-visible original text. Use ASCII, non-ASCII BMP, astral and combining-sequence vectors whose Python length is checked by the test; never UTF-8 bytes or grapheme count. Preserve nonblank surrounding whitespace. |
| 16001, empty, whitespace-only, null, number, list and missing message | Explicit public argument error after trusted gates; no real bridge entry or reply mutation; a later valid call with the SAME admission succeeds once, followed by replay refusal. |
| Invalid message plus missing/unregistered/inactive host context | Existing identity/scope gates win; no admission lookup/dispatch bypass or secret disclosure. |
| Valid message plus wrong delivery/turn, ended turn, failed admission, post-success or unload | Existing generic authority/trust refusal as applicable; no reply mutation or restored old receipt. A same-live-turn API retry is not a new authorization or an ended turn. |
| Three admitted delivery targets | Invalid target call consumes none; valid independent replies retain their own receipts, including sibling-before-anchor ordering. Reuse the existing batch control at tests/test_hermes_relay_plugin.py:566 and late-ACK/lifetime controls rather than weaken them. |
| Legacy direct and downstream validation | Existing test_plugin_reply_boundaries at1672 preserves 2400 success/2401 refusal. The real server still receives accepted message text unchanged and performs its existing content checks. No server/core edits or protected-contract changes. |

### Exact proposed RED nodes — not present or executed yet

All new nodes are planned in `tests/test_hermes_mcp.py`. These commands are inert design references, NOT authorization to invoke a default interpreter:

```text
python -m pytest 'tests/test_hermes_mcp.py::test_hook_mcp_reply_message_contract_e2e[mcp-2401]' -q -n 0
python -m pytest 'tests/test_hermes_mcp.py::test_hook_mcp_reply_message_contract_e2e[mcp-16000]' -q -n 0
python -m pytest 'tests/test_hermes_mcp.py::test_hook_mcp_reply_invalid_message_preserves_admission_e2e[over-16000]' -q -n 0
```

The first two MUST expect successful exact peer replies, not the old reject2401/short-valid diagnostic. The third MUST expect explicit argument failure for16001 and subsequent valid same-turn success. The baseline shared2400 guard predicts these behavioral failures, but none has been observed. Fixture, import, collection, timeout, skipped dependency or cleanup failures do not count as RED. Future authority cases use proposed `test_hook_mcp_reply_authority_e2e`; existing legacy, batch, authorization/reset and lifecycle tests remain required. Exact node commands must be rechecked after authorized test authorship, and slow-marked targets need their documented lane.

Corrected-delta PLAN GO is accepted and first test-source authorship is released. Execution still requires independently accepted containment/interpreter/serialized slot; product code waits for valid observed RED and release. No new review, worker or repeated contract consultation is started here. The manager assigns the narrow technical MCP16000/legacy2400 clarification in `docs/hermes-integration.md` and `integrations/hermes/README.md` before eventual delivery; it is NOT a first-test-source blocker. No guide edits are included in this slice.

## Evidence

Git confirmed the requested branch/path were absent, the trusted base object existed, and the new checkout was initially clean on `fix/hermes-mcp-reply-contract` at the stated base. Shared dirty/untracked files and existing worktrees were preserved. The actual fixture definitions and adapter anchors above were read without importing them. A targeted source scan found no matching Hermes/2400/16000 requirement in configured protected-test files; no protected file is planned for edit. Native identity lookup confirmed the existing Relay name; the base mapping has no entry for it, so no guide or new role was inferred. No formal Workflow/Redline checker, test selector, pytest or application command ran. Native prevention is unqualified, not claimed verified.

## Result review

Implementation-result review has not started. Both technical plan review and corrected-delta confirmation are complete with accepted PLAN GO. Test-source authorship is the current milestone, not observed RED, implementation-result acceptance or feature completion.

## Recovery

Accepted corrected-delta PLAN GO releases first test-source authorship only; no repeat review. Retain this checkout for that source and later qualified focused RED observation. Product remains untouched and execution/setup/imports remain held. Preserve primary selected-workspace ownership, all execution controls and the later full feature edge/legacy/lifecycle obligations. Manager owns the two-guide technical delivery clarification. Exact private review references and machine-local operational evidence stay outside this public record. No canonical source relationship tuple was supplied/resolved; sources:null remains explicitly unverified. Local record-baseline establishment is authorized; no push/merge/publication, installed change or worktree removal is released. If Relay handoff remains unavailable, leave the substantive result in the native final response rather than block authorized work.
