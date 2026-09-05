<!-- agent-workflow:start -->
**Outcome:** Agents can deliberately search one exactly identified work item or search broadly across eligible session history, with clear bounded results and no semantic scope leakage.

**Target:** Pallium.

**Scope:** Public MCP history-search surface, its shared source-only query path where required, caller guidance, telemetry, and focused unit/integration/E2E coverage.

**Constraints:** Reuse existing retrieval and expansion; preserve current broad-search behavior, privacy/visibility/lifecycle rules, hard response budgets, and package-independent raw history; do not alter active local integrations or hooks without Relay coordination with `pall-arc`.

**Completion criteria:** Exact work search returns only SourceItems carrying the requested normalized work reference; broad search retains referenced and unreferenced history; both modes remain bounded, auditable, expandable, and fail closed under every roadmap-specified boundary/error/state/lifecycle case; required checks and PR review are green before merge.

**Risk:** High

**Complexity:** Moderate

**Reason:** Agent-redline reports gray runtime/retrieval/storage paths plus red public HTTP and cross-package result contracts (`api/routes.py`, `api/schemas.py`, `core/models.py`). This is High because correctness changes an externally visible retrieval/scoping contract; no persistence or visibility-policy change is planned.

**Discovery:** Existing `pallium_search_history` already funnels through one source-only `/query` path, compact response budgeting, deferred delivered-result telemetry, and shared source expansion. `QueryFilters.work_refs` is normalized/plumbed but `core.filters.source_item_matches_filters` ignores it; lexical SQL limits candidates before this missing filter, while vector retrieval can expand to exhaustion. Raw refs live as normalized `metadata["pallium_work_refs"]`. Broad results do not expose them. An omitted query cannot currently retrieve by structural ref because raw lexical/vector index text is content-only. The smallest coherent fix extends the existing lexical provider with exact metadata filtering (including a blank-query, recency-ordered structural lane), keeps vector out of blank-query work lookup, carries source refs on the existing result contract, and adds one MCP wrapper over the same HTTP query/expansion funnel. Redline found no boundary violation and no schema migration need. Related shipped seams: `app/mcp/{server,client}.py`, `core/{filters,work_ref,query}.py`, `retrieval/{lexical,vector}.py`, `storage/sqlite_search.py`, and source-only/funnel E2E tests.

**Material assumptions:**
- Omitted/whitespace-only work-search query means “return eligible items carrying this exact normalized work ref by effective recorded time (occurred_at else created_at), newest first, then stable id”; a nonblank query ranks/narrows inside that ref. Punctuation-only text is a query, not an omitted-query alias. Disproved if approved product text requires a different no-query ordering; then stop and re-plan rather than add semantic inference.
- Source work refs remain sanitized, normalized, deduplicated, and capped at ingest. Disproved by an E2E round trip returning malformed metadata; then fix the shared normalization seam before retrieval.
- SQLite JSON functions are available alongside the repository-required SQLite/FTS runtime. Disproved by focused Windows/Linux CI; then stop and choose a bounded storage-native alternative without weakening pre-limit exact filtering.
- `pall-arc` may concurrently touch `app/mcp/server.py`; no edit to that file and no integration reinstall/service restart occurs until Relay confirms a safe sequence. A reported overlap changes sequencing, not the product contract.

**Plan:**
1. Add one safe core metadata-to-work-ref helper, enforce exact normalized SourceItem membership in the shared filter, and carry bounded safe refs on raw query results. Extend the existing SQLite lexical candidate stream—not a second retrieval stack—to apply exact JSON-array membership before SQL LIMIT. Page in stable score/id order (or effective-recorded-time/id order for truly blank text) until K eligible unique results or stream exhaustion; accumulate trace counts once, guarantee progress, and stop at exhaustion. Punctuation-only text remains a query and never becomes recent-history listing. Skip blank vector embedding before any provider call. Target: core/work_ref.py, core/filters.py, core/models.py, retrieval/lexical.py, retrieval/vector.py, storage/sqlite_search.py.
2. Add the work-search mode to the existing HTTP result/telemetry contract and MCP client/server funnel. Keep ordinary pallium_search_history(query) broad while retaining its existing optional work_refs argument as a documented compatibility filter; add the preferred pallium_search_history_by_work_ref(work_ref, query?) with one required valid structural reference that Pallium normalizes. Its description must say this is a narrow exact-reference search that can miss related work under another or no identifier; omitted/whitespace query returns newest eligible exact-ref items. The broad description must direct topic-level search across eligible history/work items to pallium_search_history. Reuse compacting/finalization/expansion, include mode/requested ref and safe result work cues, and attribute exact-work lookups with a distinct existing-schema origin. Include that origin in actual-exposure/reuse population evaluation, but explicitly exclude it from RAW/DERIVED candidate replay because work scope is not persisted and cannot be faithfully reconstructed. Do not encode refs in query text or change persistence. Target: api/schemas.py, api/routes.py, app/mcp/client.py, app/mcp/server.py, evals/real_corpus_pull_eval.py, and truthful replay docs/caveats in evals/raw_derived_hybrid/runner.py.
3. Update the canonical roadmap contract, public guidance, and generated integration skill text to use the selected name and exact wording distinction; each tool name starts its own line. Do not alter hook behavior. Target: roadmap/features/add-distinct-work-and-broad-history-search-tools.md, integrations/{codex,claude-code,opencode}/skills/pallium-memory/SKILL.md, setup guidance builders as required by generated-text tests, and focused Session History/API/integration docs.
4. Add focused unit/integration tests plus caller-surface E2E journeys covering missing/type-invalid/empty/separator-only/overlong/unsafe/unknown refs; exact normalization and similar-ref rejection; one/multiple/max/over-max refs and results; blank versus punctuation-only, short, Unicode, equal-time, and omitted-date ordering; broad referenced+unreferenced retrieval; more than a full window of wrong-ref and same-ref-but-ineligible candidates; forgotten/deleted/stale/replacement-chain/duplicate cases; container/actor/visibility isolation; request-link validation; exact delivered-result telemetry including empty/failure paths; and search→expansion parent linkage. Exercise vector-enabled tests explicitly and add a bounded-size SQLite query-plan/scan-ceiling check. Reuse existing fixtures/tests where they already prove unchanged shared behavior; add tests only for uncovered contracts.
5. Run focused checks, all affected integration/E2E suites, full repository tests, lint/import/redline/workflow gates, then clean-context result review. Stop and re-plan if scope reaches persistence, visibility policy, a second retrieval system, or active hook behavior. Push a PR, satisfy architecture/API checkpoints, inspect and resolve all review threads and CI failures, then merge only when green.

Key conventions: Exact refs use `core.work_ref` normalization and OR membership against normalized stored refs; filtering occurs before visible top-K; retrieval alone never counts as use; evaluation text labels candidate recovery vs downstream effect; response budgets and delivered-result telemetry use the existing helpers.

Target files or classes: `core.work_ref`, `core.filters.source_item_matches_filters`, `core.models.QueryResultItem`, `storage.sqlite_search.SQLiteSearchMixin`, `retrieval.{lexical,vector}`, `api.{schemas,routes}`, `app.mcp.{client,server}`, evaluation origin defaults, focused integration skills/docs, and tests named in the verification plan.

**Verification plan:**
- When an exact normalized work ref is supplied, every returned SourceItem shall carry it and similar/unlinked or same-ref-but-ineligible items shall never occupy or starve the requested page → shared-filter unit tests plus paged lexical/vector HTTP E2E beyond the former overfetch window, with duplicate/progress/exhaustion assertions.
- When query is omitted, exact work search shall return newest eligible work items; when query is supplied, it shall rank/narrow only inside that work → MCP→HTTP E2E for blank, short, Unicode, punctuation-heavy, empty, one, max, and over-max corpora.
- When broad history is searched, referenced and unreferenced history shall remain searchable and compact work/session cues shall stay within hard character/result budgets → broad MCP E2E and compact-budget tests.
- When refs are missing, wrong-typed, empty, separator-only, overlong, duplicated, case/separator variants, unknown, or one of multiple source refs, the public tool shall fail clearly or return the exact bounded result required by contract → FastMCP public-schema/call E2E.
- When sources are forgotten, duplicated, stale/replaced, cross-container, actor-mismatched, or visibility-ineligible, neither mode shall weaken current lifecycle/governance behavior → parameterized HTTP/MCP lifecycle and isolation E2E through the same public read surfaces.
- When a delivered search hit is expanded, telemetry shall identify broad versus exact-work lookup, persist exactly the compacted result ids, link expansion to its parent, and include exact-work events in actual-exposure/reuse evaluation without replaying them as unscoped candidate-recovery queries → database-observed MCP search→expand E2E, population tests, and explicit replay-exclusion assertions/caveat.
- When legacy metadata contains unsafe/malformed refs, neither HTTP nor MCP output shall expose them and SQL/core matching shall agree on list-only normalized membership → legacy-row HTTP/MCP E2E plus helper/SQL parity tests.
- When the old broad MCP work_refs argument is used, it shall retain its prior filtered behavior while guidance directs new single-ref callers to the explicit work tool → FastMCP schema and real-call compatibility E2E.
- When changes are complete, architectural/API boundaries and repository behavior shall remain healthy → focused pytest, integration Node tests if guidance changes, full pytest, Ruff/import-linter, agent-redline report, and `agent-workflow-check`.

**Plan review:** Clean-context architecture review under “Plan review” below; first draft and naming delta findings are incorporated, and the reviewer approved the final wording.

**Approvals:** Approved by user 2026-09-05T20:35:57Z: "i told you i approve for you to follow up on the feature i assign you and get them done and merged, no need to ask each tiem"

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

No active blocker. User approval is recorded above, Relay integration coordination is complete, and the feature remains isolated from the other agent's checkout.

Rebased the required first Work Record commit onto origin/main 7b8dcf09 before guarded edits; implementation now proceeds only in this isolated worktree.

Before guarded edits, intended implementation targets are: core/work_ref.py, core/filters.py, core/models.py, storage/sqlite_search.py, retrieval/lexical.py, retrieval/vector.py, api/schemas.py, api/routes.py, app/mcp/client.py, app/mcp/server.py, eval origin selection, the three generated integration skills/setup guidance, and focused tests. The branch will be rebased onto the current main before any of these files are edited.

## Plan review
Independent clean-context architecture review (distinct_search_plan_review, 2026-09-05) rejected the first draft. Resolved findings:

1. Eligible-result starvation: exact-ref SQL pushdown alone was insufficient because same-ref but lifecycle/visibility/actor-ineligible rows could fill a fixed window. The revised plan pages the existing ordered stream until K eligible unique results or exhaustion, with stable ordering, trace accumulation, and termination tests.
2. Unfaithful evaluation replay: lookup telemetry lacks persisted work scope, so scoped queries must not be replayed broadly. The revised plan uses a distinct origin, includes actual delivered events in reuse/population evaluation, and keeps them out of candidate-recovery replay with an explicit reason.
3. MCP compatibility: removing the existing broad tool's optional work_refs would silently break callers. The revised plan retains it as a compatibility path while making the new one-ref tool the documented interface.
4. Legacy output safety: ingest-time sanitization does not protect legacy rows. The revised plan uses one safe projection helper and tests unsafe/malformed historical metadata through HTTP and MCP.
5. High-risk approval timing: the earlier blanket authorization preceded these surfaced decisions. The revised plan records approval only after the user sees this review summary.

The reviewer approved the shared-retrieval architecture conditionally on these changes: no second retrieval/index/package path, no persistence change, no visibility-policy change, and explicit architecture/API checkpoints. The user then selected the clearer public name pallium_search_history_by_work_ref and required both tool descriptions and all installed skill guidance to explain the narrow exact-ref versus broad topic-search intent.
### Naming/guidance delta review

A fresh reviewer accepted pallium_search_history_by_work_ref as the clearer identity-search name, conditional on four wording corrections now in the plan: update the canonical roadmap; accept and normalize one valid structural ref rather than demanding caller-normalized input; define omitted/whitespace query as newest eligible exact-ref history; and repeat the narrow/may-miss versus broad-topic distinction in both tool descriptions and all three integration skills. The old broad work_refs argument remains explicitly labeled a compatibility filter.

Implementation completed in the isolated `codex/distinct-work-broad-history-search` worktree: one exact-work MCP wrapper reuses the source-only HTTP query, shared expansion, delivery finalization, and existing lexical/vector providers. Exact matching now uses the shared safe normalization projection before top-K, streams one ordered SQLite result through lifecycle/visibility gates, skips blank vector embedding, expands only the exact post-retrieval dedup window, and preserves broad-search behavior. Public output carries bounded safe work cues and a distinct `agent_pull_work` origin; actual-use evaluation includes it while unfaithful unscoped replay excludes it.

The first clean-context result review found five P2 gaps: legacy SQL/core normalization disagreement, repeated SQLite scans, deferred empty-result budget overflow, malformed public validation input echo, and incomplete caller-surface coverage. All five were addressed with regressions, including real MCP → HTTP → delivery telemetry → expansion, one-statement refill, vector exact-filter exhaustion, malformed secret-bearing HTTP/MCP inputs, and 128-character empty exact searches. The whitespace-only `/query` compatibility tightening is intentional and limited to the new exact origin; existing broad history still requires a nonblank query.

Verification complete on code revision `736efcf0`: 368 affected Python tests passed; the full repository passed with 4,395 tests, 14 platform/dependency skips, and 2 expected failures; OpenCode Node integration passed with 45 tests and 6 Windows platform skips; compileall and `git diff --check` passed; the repository import-linter adapter reported zero violations. Final clean-context result review approved both architecture and API with no P0–P2 findings. All edits used narrowly scoped deterministic PowerShell replacements after `apply_patch` failed with the documented local Windows 1327/1385 process-creation limitation.

## Evidence

- Code revision: `736efcf0` (final following commit contains documentation and Work Record alignment only).
- Affected verification: `368 passed`.
- Full repository: `4395 passed, 14 skipped, 2 xfailed`.
- OpenCode integration: `45 passed, 6 skipped` (Windows-only structural-ref skips).
- Import boundaries: `build/import-linter-report.json` contains zero violations.
- Ruff is neither installed nor configured as a repository or CI check; `compileall`, `git diff --check`, import-linter, and full tests supplied the configured static/runtime verification.
- Clean-context final result review: architecture-review and api-review approved; no P0–P2 findings.
- Skill-feedback check: all seven triggers were false; no upstream skill issue required.
- Workflow gate: all blocking predicates passed; the sole advisory is a false-positive commit-order signal because the first commit contained the Work Record plus roadmap planning, before any guarded code edit.
