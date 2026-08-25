# Link history lookups to their initiating requests

Branch: `codex/link-lookups-to-requests`

<!-- agent-workflow:start -->
**Outcome:**
Each deliberate history lookup can identify the exact user request that initiated it, so real-corpus experiments compare work with and without history using defensible pairs rather than timestamp guesses.

**Target:**
Pallium repository.

**Scope:**
Additive request-to-lookup telemetry across the existing prompt integrations, MCP query path, SQLite lookup-event schema, real-corpus evaluator, focused caller-surface tests, roadmap alignment, and this Work Record.

**Constraints:**
No authorization semantics, retrieval/ranking change, new endpoint, provider call during an insufficient-data preflight, or inferred “nearest request” fallback. Preserve clients that omit linkage, legacy rows, visibility/container isolation, Unicode, hard injection budgets, and the Windows VBS launcher.

**Completion criteria:**
When a supported prompt integration stores a user request and its agent calls `pallium_search_history`, the persisted lookup event shall reference that exact user source item after validating the same container, active thread, actor, visibility, user role, and live lifecycle. Missing linkage remains nullable for compatibility; every supplied invalid link returns HTTP 422 with the same non-enumerating validation detail before retrieval or best-effort telemetry begins. The real-corpus evaluator shall use the linked user request text as the downstream task, accept only valid direct links, report why data is insufficient, and perform zero provider construction or calls unless it has the requested sample size. Caller-surface lifecycle and schema-upgrade E2E coverage, focused regression, full regression, and roadmap alignment are required.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Redline classifies the additive query contract as API-review and the nullable SQLite column as persistence-review; persistence makes the task High risk. Several existing integrations and the evaluator must stay compatible.

**Discovery:**
`/item-and-query` already returns the exact `source_item_id` just stored for each UserPromptSubmit hook. The Python formatters already emit a bounded scope marker even without retrieved memory. OpenCode receives the same response ID, but its formatter accepts only blocks/container/budget and returns empty when there are no blocks, so its common formatter, caller, and tests require explicit scope-marker parity. `pallium_search_history` funnels through the MCP client and optional `QueryRequest` into `PalliumService.query`, which unconditionally stores `HistoricalLookupReuseEventRecord` inside a best-effort telemetry block. Supplied-link validation therefore must happen before retrieval and outside that block; the route will translate its single `ValueError` contract to HTTP 422. The tracked real-corpus loader currently uses lookup `query_text` as the task and does not reconstruct a user request at all, so it cannot measure the work that initiated the lookup. SQLite already has `_HISTORICAL_LOOKUP_COLUMN_MIGRATIONS` and `_ensure_historical_lookup_columns` for additive nullable columns. No new endpoint or retrieval surface is required.

**Material assumptions:**
- The `/item-and-query` response ID is the authoritative initiating request because it is returned from the same hook call; disprove by a caller-surface test showing a different stored user item, then stop and revisit the integration contract.
- An optional additive query field and nullable column preserve existing callers/rows; disprove with schema-upgrade or existing MCP regression failures, then stop rather than add a compatibility shim.
- Exact linkage is measurement telemetry, not authorization; any proposed visibility/access behavior change invalidates scope and requires replanning.

**Plan:**
1. Extend the existing bounded Python scope marker with the exact prompt `source_item_id`; pass it from Codex and Claude UserPromptSubmit. Bring OpenCode's `pallium-common.mjs` formatter and `pallium.mjs` caller to the same bounded, control-safe, empty-result behavior. Update all three concise skill/guidance sources to supply the marker's `request_source_item_id` only to `pallium_search_history`.
2. Add one optional `request_source_item_id` field through `QueryRequest`, both `/query` and `/query/debug`, the MCP tool/client, and `PalliumService.query`. Before retrieval and outside best-effort telemetry, validate any supplied ID as an existing, unforgotten user source whose canonical container, active thread, actor, and visibility exactly match the query. Raise one `ValueError` message for every invalid case; both routes map it to the same HTTP 422 detail so callers cannot distinguish missing from mismatched IDs. Omission remains compatible.
3. Add one nullable `request_source_item_id` column to `HistoricalLookupReuseEventRecord` and `_HISTORICAL_LOOKUP_COLUMN_MIGRATIONS`; rely on and verify `_ensure_historical_lookup_columns`. Do not backfill or infer legacy rows. Persist the validated ID on lookup events only.
4. In `evals/real_corpus_pull_eval.py`, require the new column for real-corpus loading, resolve the linked source row, use its redacted content as `PullCase.query`, and reject unlinked, missing, wrong-container/thread/actor/visibility, non-user, forgotten, empty, or temporally unsafe links. Report each attrition count. Require `len(snapshot.cases) >= sample_size` before `build_eval_providers`; return an insufficient-data aggregate with zero calls otherwise. Explicit `--sample-size 4` remains the budget-aware pilot gate; the default 20 remains the product gate.
5. Add focused HTTP/MCP/hook lifecycle tests for exact linkage, omission, all uniform-invalid cases, Unicode/control and budget limits, OpenCode empty-result parity, ORM persistence, old-schema additive upgrade, legacy NULL rows, direct task text, attrition counts, and zero provider construction/calls below requested sample size. Align the active roadmap item and scope; run workflow/redline, focused, and full checks. Stop and replan if implementation requires a new endpoint, authorization semantics, or inferred linkage.

**Verification plan:**
- Exact request-to-lookup link through each supported caller → Codex, Claude, and OpenCode hook tests plus MCP/HTTP persisted-event E2E.
- Invalid references fail visibly without existence or cross-scope leakage → `/query`, `/query/debug`, and MCP E2E asserting the same 422 detail for missing, wrong container/thread/actor/visibility, non-user, and forgotten items.
- Omitted linkage and legacy rows remain compatible → existing MCP regression plus ORM write and raw SQLite old-schema upgrade/NULL-row E2E through `_ensure_historical_lookup_columns`.
- Real-corpus results use defensible pairs without wasting model budget → evaluator tests asserting linked user content replaces lookup query text, all link attrition counts, temporal safety, and zero provider construction/calls below requested sample size.
- No retrieval, visibility, or lifecycle regression → focused suites, full pytest, agent-workflow check, and redline report.

**Plan review:**
Clean-context review found five blockers: OpenCode parity, undefined invalid-link behavior, stale evaluator discovery, unspecified sample threshold, and incomplete migration verification. After two focused revisions added the exact contracts and the shared /query/debug edge, the reviewer returned APPROVED.

**Approvals:**
Approved by user 2026-08-25: "ok, so do that"

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Plan review

Initial clean-context review withheld approval on OpenCode parity, invalid-link error semantics, the evaluator's actual current behavior, sample sufficiency, and migration verification. The first re-review confirmed four findings resolved and identified the shared /query/debug schema edge; both query routes now share the validation and 422 contract. The final focused re-review returned APPROVED with no remaining blocker.

## Implementation

Added one optional request source ID through the existing prompt marker, MCP/query contract, core validation, and nullable lookup-event row. Validation is centralized before retrieval and rejects every supplied invalid reference with one non-enumerating 422 contract; omitted links and legacy NULL rows remain compatible. The real-corpus loader now uses only the exact linked live user request, reports link attrition, and exits before provider construction when the requested sample is unavailable. Codex, Claude, and OpenCode integrations and concise guidance now carry the marker within their existing hard budgets. Roadmap text records the free collection phase, four-case pilot, and twenty-case product gate.

No authorization, retrieval/ranking, endpoint, inferred-link, or launcher behavior was added. OpenCode formatting reused the Python scope-marker contract rather than adding a new protocol. A lower-cost delegated worker implemented the integration propagation; the primary agent reviewed and corrected shared orientation/trigger caller parity. `apply_patch` hit the documented Windows error 1385, so subsequent edits used narrowly scoped deterministic PowerShell replacements as permitted by the repo-local instructions.

## Evidence

- Focused Python feature suite: `135 passed, 4 warnings`.
- Guidance budget and affected integration suite after shortening the new instruction: `35 passed`.
- OpenCode integration suite: `36 passed`.
- Full isolated regression with a nonexistent `PALLIUM_CONFIG_FILE`: `3847 passed, 23 skipped, 2 xfailed, 4 warnings`.
- `git diff --check`: clean; only Git's existing LF-to-CRLF notice for the roadmap idea file.
- HTTP E2E covers missing, non-user, forgotten, wrong container/thread/actor/visibility, and non-source-only links on both `/query` and `/query/debug`, asserting uniform 422 before retrieval and no lookup write.
- MCP/client tests cover exact Unicode propagation, omission compatibility, and visible compact error detail.
- Storage tests cover ORM round-trip and additive repair of a legacy event table with Unicode linkage.
- Eval tests prove linked user content replaces the agent search phrase, every invalid-link class is counted, and insufficient directly linked data constructs no configured model provider.

## Result review

Independent clean-context lower-cost review inspected the full 32-file diff against `origin/main`, including validation-before-retrieval, API/MCP propagation, all three integration callers, nullable schema migration, evaluator direct-link and zero-provider preflight behavior, roadmap alignment, context budgets, and public identifier exposure. Verdict: APPROVED with no actionable findings. PR review later requested one domain-generic MCP fixture; the real repository identifier and matching assertion were anonymized, and the focused MCP suite passed 35 tests.
