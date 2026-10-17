# Preserve an oversized following-message handle

<!-- agent-workflow:start -->
**Outcome:**
An agent can open a requested following message even when its text does not fit the current source expansion.

**Target:**
Pallium source-context HTTP and MCP expansion.

**Scope:**
Add a privacy-checked next-message reference for an oversized following neighbor, carry it through bounded MCP packaging, and add generic caller-facing regression coverage and concise documentation.

**Constraints:**
Keep search ranking, the 4000-character MCP cap, source visibility and forgetting, redaction, lookup lineage, and retrieval-not-use semantics unchanged. No paid evaluations, private transcript fixtures, dependencies, installed-service changes, or merging the separate PR278 investigation.

**Completion criteria:**
When a requested eligible following message exceeds the remaining expansion budget, the caller receives a fetchable reference without its text being recorded as delivered evidence. When that reference is opened, current authorization and forgetting are reapplied. Bounded multi-hop navigation works through the public MCP surface; normal fitting expansions, anchor continuation, and response-size/error contracts remain covered.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"An agent can open a requested following message even when its text does not fit the current source expansion.","scope":"Add a privacy-checked next-message reference for an oversized following neighbor, carry it through bounded MCP packaging, and add generic caller-facing regression coverage and concise documentation.","constraints":"Keep search ranking, the 4000-character MCP cap, source visibility and forgetting, redaction, lookup lineage, and retrieval-not-use semantics unchanged. No paid evaluations, private transcript fixtures, dependencies, installed-service changes, or merging the separate PR278 investigation.","completion_criteria":"When a requested eligible following message exceeds the remaining expansion budget, the caller receives a fetchable reference without its text being recorded as delivered evidence. When that reference is opened, current authorization and forgetting are reapplied. Bounded multi-hop navigation works through the public MCP surface; normal fitting expansions, anchor continuation, and response-size/error contracts remain covered."}

**Risk:** High

**Complexity:** Moderate

**Reason:**
Caller-visible navigation contract crosses core/service.py (architecture-review), api/routes.py, api/schemas.py and app/mcp/server.py (api-review). Privacy gates and delivery accounting must remain intact.

**Discovery:**
Base 6be22d77, freshly fetched origin/main on 2026-10-11. get_source_context stops a side at its first oversized eligible neighbor and discards that ID. _bounded_expansion only sees selected neighbors. A read-only existing-evidence investigation demonstrated a 2362-character anchor followed by a 2787-character message exceeding 4000; this is a navigation capability failure, not proof of improved search recovery or downstream answers. Production callers are api/routes.py and app/mcp/client.py; reliable_pair_runner consumes the HTTP/MCP shape. Existing public-MCP integration and source-context visibility tests provide reusable isolated fixtures.

**Material assumptions:**
The existing bounded and authorized following window contains the next reference; do not scan beyond its 25-item limit. If the contract requires a new persistent cursor, authorization model, ranking change, or private corpus replay, stop and return to planning. A pointer is navigation metadata, not delivered message content or verified use.

**Plan:**
1. Invoke agent-workflow, establish this Work Record and classify the complete intended change before source edits; obtain clean-context technical plan review. Human approval of the narrow presented behavior is recorded below.
2. Add optional next_source_item_id for the first following neighbor rejected by the existing content budget, after existing eligibility checks. Carry it outside content items through the HTTP response and MCP formatter; retain it within the existing serialized cap, including anchor continuation. If MCP packaging itself removes a following item, retain the earliest removed following handle rather than skipping to a later service handle. If mandatory metadata cannot fit, return a bounded error, never silently remove the handle. No new endpoint, storage query, persistence schema, audit role or dependency. Keep normal content selection and evidence receipts unchanged: the pointer alone is navigation metadata, not delivered content. Document how to open it with existing parent_lookup_id and scope.
3. Add an anonymous red-before-green public-MCP regression using the demonstrated size class, then boundary/lifecycle cases. Target files: core/service.py, api/routes.py, api/schemas.py, app/mcp/server.py, tests/test_source_neighbor_handle_e2e.py, tests/test_mcp_server.py if needed, docs/session-history.md, and this Work Record. Reconcile roadmap prose only if needed; do not reopen the queued representation study or claim the older investigation passed.
4. Run focused tests, affected subsystem tests, whole-change test-plan and required full non-slow lane. Independent non-implementer result review covers API/architecture, privacy and evidence accounting. Prepare PR evidence; separate human result review and current CI/checkpoints remain merge gates. No live rollout.

**Verification plan:**
- When an eligible following message is over budget, the system shall return a fetchable handle without delivered-content credit -> public MCP-to-HTTP-to-service red/green test and persisted delivery receipt assertions.
- When traversing more than two messages, the system shall preserve scope and parent lineage and eventually open the oversized message -> generic four-hop public MCP test, including Unicode.
- When a handle target is forgotten, missing or no longer visible, the system shall deny opening it -> lifecycle tests through HTTP/MCP; hidden neighbors never appear in handle metadata.
- When before/after is zero, the thread ends, content fits exactly, or content is empty, the system shall preserve the bounded window and ordinary response -> boundary tests including max and over-max side bounds.
- When anchor content is continued or metadata cannot fit, the system shall keep the serialized cap and existing progress/error semantics -> MCP tests at minimum, normal and over-maximum budgets, stale revision and oversized anchor coverage.
- When the implementation is complete, the system shall preserve accepted unrelated behavior -> affected tests, test-plan-selected checks, full non-slow suite, independent review; no downstream task-effect claim.

**Plan review:**
Agent technical review: /root/neighbor_contract_review, 2026-10-11, base 6be22d77 and Work Record 82ddb441. Approved after clarifying serializer omissions and mandatory-handle cap behavior; clarification incorporated in step 2 before implementation. Reviewer inspected core, schema, HTTP, MCP and delivery consumers; High/Moderate and verification scope retained. No new audit role: a pointer is not message evidence.

**Approvals:**
Approved by user 2026-10-11: "ok, drive this"
Approval covers the presented next-message handle fix within existing limits and privacy rules, not live installation or unrelated retrieval changes.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Applicability and checkpoints

Normal isolated branch/PR workflow: intended runtime/API paths are outside the documentation-only allowlist. No protected behavior-contract edit is planned. API change is additive; architecture change carries a transient authorized navigation reference, not a new memory model. Technical plan review passed with the incorporated clarification; no source edits preceded review.

## Delivery boundaries

This is a new narrow correction from current main, separate from draft PR278. It does not establish complete recovery of the original historical question or resolve search discovery failures. No user environment or private evidence is changed.

## Implementation

Planned files: `core/service.py`, `api/routes.py`, `api/schemas.py`, `app/mcp/server.py`, `tests/test_source_neighbor_handle_e2e.py`, and `tests/test_mcp_server.py` only if formatter boundary coverage needs a focused unit case. The MCP client call path was inspected and already forwards its context scope and actor filter; no client signature change is planned. The root lead is handling the separately scoped `docs/session-history.md` guidance.

The implementer added a caller-facing MCP→ASGI→service regression first; it failed because the returned payload lacked the requested following handle. The lead implemented the service/HTTP/MCP propagation, while the implementer completed only `tests/test_source_neighbor_handle_e2e.py`. Coverage now includes three-hop navigation, Unicode and redaction on refetch, receipt exclusion before fetching and inclusion after fetching, current actor/container/visibility/forgetting checks, missing targets, exact/over content boundaries, empty content, end-of-thread, zero sides, public/private filtering, and the 25-item side clamp. Formatter omission, tiny-cap, and continuation cases are covered by the lead's focused tests in `tests/test_mcp_server.py`.

## Evidence

- Red: `python -m pytest tests/test_source_neighbor_handle_e2e.py -q -n 0` failed at the missing `next_source_item_id` assertion after successful MCP search and expansion receipt finalization.
- Green: `C:/Dev/rore/Pallium/.venv/Scripts/python.exe -m pytest tests/test_source_neighbor_handle_e2e.py -q -n 0 -p no:cacheprovider --basetemp=C:/Dev/rore/Pallium/.test-tmp-history-neighbor9` — 5 passed. The isolated `--basetemp` was needed because the managed worktree cannot write pytest cache/default temp paths under the sandbox.
- Lead reports 83 formatter tests passed, including four new formatter tests, and 141 affected existing tests passed before the final error-wording change; lead owns remaining whole-change verification.
- The lead added a sixth public-MCP case forcing metadata-only omission at an 800-character cap. The service returns all five messages, MCP removes neighbors, and its earliest omitted handle opens successfully. That focused node passed. Its first test setup lacked a required finalized lookup parent; adding a real search fixed the fixture without changing runtime behavior.
- The new pointer initially made the existing 400-character formatter case serialize to 401 characters. The fix conditionally omits optional `supported_memories: null` only when a handle-bearing response exceeds the cap. Existing fitting response behavior and all non-null opt-in handling remain intact; the independent reviewer approved this packing refinement.
- Whole-change selector requires the full lane. Full non-slow suite is running against the implementation commit following this record update. No required failure is being treated as success.
- First full invocation at `3677be01` stopped with 3 failures, 1728 passed, 2 skipped and 1 xfailed. All three were test-location artifacts: temporary paths inside the worktree picked up its Git identity/work reference, and the Relay fault harness correctly rejected a fake installation path containing `.codex/worktrees`. The exact recorded failures passed (`--lf --lfnf=none -q -n 0`: 3 passed) with a dedicated temporary directory outside any repository. No Relay/source/test changes were made for this. Full validation is being rerun with that corrected isolation.
- Correctly isolated full validation at `3677be01` found the new tool description exceeded the existing 1300-character combined History-tool guidance ceiling (1 failed, 3178 passed, 2 skipped, 1 xfailed); Linux CI found the same failure. Shortened only the expansion description, preserving navigation, revision reset, scope/lineage, actor filtering and historical guidance. `tests/test_guidance_budget.py`: 11 passed. No ceiling or assertion was changed. Full validation must run again on the corrected revision.
- Final local full non-slow run at `9c33e256`: `C:/Dev/rore/Pallium/.venv/Scripts/python.exe -m pytest tests/ -x -q --basetemp=C:/Users/I347041/AppData/Local/Temp/pallium-neighbor-20261011-full-final` — **6562 passed, 34 skipped, 2 xfailed**, 418.82 seconds on Windows/Python 3.13.14. This includes all six new caller-facing tests and the formatter/guidance regressions. Later changes to this record are evidence-only; tested application content is unchanged.
- Delivery and CI evidence surface: [PR #310](https://github.com/rore/Pallium/pull/310). Current PR checks and review comments, not this static record, determine CI and checkpoint status. No merge or installation has occurred.

## Result review

Agent technical review: /root/neighbor_contract_review, 2026-10-11.
Reviewed revision: `9c33e256`; the reviewer approved `3677be01` runtime, documentation and tests, then explicitly extended review to the shortened tool description at `9c33e256` without finding lost semantics.
Verification adequacy: focused public MCP/HTTP lifecycle and metadata-only omission cases plus formatter boundary cases cover the narrow approved contract. Existing affected tests protect visibility, forgetting, continuation and delivery semantics. The reviewer found no blocking runtime, API, architecture or privacy findings, and the required local full suite passed. PR CI/checkpoint status remains live in PR #310. This is navigation capability, not downstream answer quality. Separate human result review has not occurred.

## Roadmap alignment

The completed `fix-session-history-evidence-access` and `improve-session-history-search-quality` items describe earlier shipped slices. This is a narrow follow-up bug correction, not a reopening or completion of the queued `investigate-history-navigation-and-on-demand-compression` study. Their existing delivery evidence is not evidence for this change. Existing drift: the completed evidence-access item's relationship paragraph still calls its now-completed umbrella open; that unrelated historical wording is not used to infer task status here. No roadmap state is changed.

## Checkpoint: architecture-review

What changes: carry one transient, authorized following-source ID through the existing expansion result. Why: content-budget omission otherwise destroys the only forward opening path. Contract: the internal service tuple gains a sixth element and its sole production unpacking caller is updated; no persistence, ranking, import boundary or memory-model changes. Verification: public MCP navigation, lifecycle and receipts plus existing service/visibility tests.

## Checkpoint: api-review

Additive HTTP field `next_source_item_id` is optional; MCP includes it when present and counts it in the existing serialized cap. It is not evidence content and is excluded from content receipts. Opening it uses the existing tool and reapplies live gates. No endpoint or request parameter changes. Mandatory handle metadata that cannot fit returns a bounded error; an optional null supported-memory field may be elided under pressure. Separate human result review and PR checkpoints remain pending.

## Skill feedback

Trigger 5 dropped: initial missing reference paths were the lead's incorrect path guesses, not broken installed skill links. No upstream issue is warranted.
