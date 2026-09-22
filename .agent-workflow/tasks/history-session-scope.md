<!-- agent-workflow:start -->
**Outcome:**
Session History uses the active requesting session only for telemetry, request lineage, and response-local grouping, while an optional source-thread filter independently narrows historical candidates.

**Target:**
Pallium.

**Scope:**
Separate active-session attribution from source-thread filtering across the two Session History MCP tools, MCP client, source-only HTTP query/debug contracts, routes, service orchestration, and query filter resolution; migrate the repository's benchmark and live-smoke callers; add focused and caller-surface E2E coverage; align `docs/http-api.md`, `docs/session-history.md`, and delivery slice 4 in `roadmap/features/fix-session-history-evidence-access.md`.

**Constraints:**
Keep container, actor, visibility, exact-work, redaction, forgetting, ranking, candidate ordering, result paging, response budgets, and historical-state warnings unchanged. Broad History remains broad when no source-thread filter is supplied. Exact-work search intersects an optional source-thread filter and never broadens. Active session identity must never be inferred from a historical source or exposed raw in MCP responses. Retrieval alone must not update accessibility or ranking state.

**Completion criteria:**
The public contracts name requester attribution and source scope separately; broad, thread-exact, exact-work, empty-scope, same/other/unknown grouping, request-lineage, visibility, forgetting, audit attribution, and raw-identity non-leakage are proven through focused tests and at least one real MCP-to-HTTP lifecycle journey; required workflow, redline, review, and test gates pass.

**Requirement baseline:**
{"source":"roadmap-slice-4","outcome":"Session History uses the active requesting session only for telemetry, request lineage, and response-local grouping, while an optional source-thread filter independently narrows historical candidates.","scope":"Separate active-session attribution from source-thread filtering across the two Session History MCP tools, MCP client, source-only HTTP query contract, route, and core query orchestration; add focused and caller-surface E2E coverage; align docs and roadmap delivery slice 4.","constraints":"Keep container, actor, visibility, exact-work, redaction, forgetting, ranking, candidate ordering, result paging, response budgets, and historical-state warnings unchanged. Broad History remains broad without a source-thread filter; exact-work never broadens; active session identity is never inferred from a historical source or exposed raw.","completion_criteria":"Distinct public contracts and full broad/thread-exact/exact-work/empty/grouping/lineage/visibility/forgetting/audit/non-leakage coverage pass with workflow and review gates."}

**Behavior changes:**
[{"target":"task-context.scope","classification":"equivalent","before":"Separate active-session attribution from source-thread filtering across the two Session History MCP tools, MCP client, source-only HTTP query contract, route, and core query orchestration; add focused and caller-surface E2E coverage; align docs and roadmap delivery slice 4.","after":"Separate active-session attribution from source-thread filtering across the two Session History MCP tools, MCP client, source-only HTTP query/debug contracts, routes, service orchestration, and query filter resolution; migrate the repository's benchmark and live-smoke callers; add focused and caller-surface E2E coverage; align `docs/http-api.md`, `docs/session-history.md`, and delivery slice 4 in `roadmap/features/fix-session-history-evidence-access.md`.","reason":"Discovery expanded the implementation surfaces and caller migrations needed to deliver the same approved scope split."},{"target":"task-context.constraints","classification":"equivalent","before":"Keep container, actor, visibility, exact-work, redaction, forgetting, ranking, candidate ordering, result paging, response budgets, and historical-state warnings unchanged. Broad History remains broad without a source-thread filter; exact-work never broadens; active session identity is never inferred from a historical source or exposed raw.","after":"Keep container, actor, visibility, exact-work, redaction, forgetting, ranking, candidate ordering, result paging, response budgets, and historical-state warnings unchanged. Broad History remains broad when no source-thread filter is supplied. Exact-work search intersects an optional source-thread filter and never broadens. Active session identity must never be inferred from a historical source or exposed raw in MCP responses. Retrieval alone must not update accessibility or ranking state.","reason":"The revised wording makes the exact-work intersection and existing repository retrieval invariant explicit without changing required behavior."},{"target":"task-context.completion_criteria","classification":"equivalent","before":"Distinct public contracts and full broad/thread-exact/exact-work/empty/grouping/lineage/visibility/forgetting/audit/non-leakage coverage pass with workflow and review gates.","after":"The public contracts name requester attribution and source scope separately; broad, thread-exact, exact-work, empty-scope, same/other/unknown grouping, request-lineage, visibility, forgetting, audit attribution, and raw-identity non-leakage are proven through focused tests and at least one real MCP-to-HTTP lifecycle journey; required workflow, redline, review, and test gates pass.","reason":"The revised wording enumerates the same coverage classes and names the required real lifecycle path."}]

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Pre-edit agent-redline classifies `api/schemas.py`, `api/routes.py`, `core/service.py`, and the required source-only filter-resolution boundary in `core/query.py` as red/watch, with architecture-review and API-review checkpoints; `app/mcp/client.py` and `app/mcp/server.py` are gray/watch. The change corrects caller-visible scope semantics and audit identity at a trust boundary, but remains additive and uses the existing query/filter/audit path without persistence or ranking changes.

**Discovery:**
Both History MCP tools build payloads through `PalliumMcpClient._scope_params()`, which copies the context `thread_ref` into `QueryRequest.thread_ref`. `core.service.query` then uses that one value both as `QueryFilters.thread_ref` and as the persisted historical lookup `session_id`; it also uses it for runtime context and `request_source_item_id` scope validation. `core.query.QueryExecutor` resolves filters before its source-only branch, and runtime-context policy can remove explicit thread filters for same-thread, resumed, and insufficient-context new sessions. Consequently requester identity and historical scope are conflated, and an intended exact filter can silently broaden. Source expansion already models the desired attribution split through `active_session_ref` plus the anchor's source thread. Two repository callers require migration: `evals/continuity_handoff_benchmark.py` copies requester context into source-only queries and `scripts/live_funnel_smoke.py` sends a generated smoke-session `thread_ref` as lookup identity.

**Material assumptions:**
- `QueryRequest.thread_ref` remains the historical source-thread filter, while a new optional `active_session_ref` is requester attribution for source-only queries. Identified requester-only source-only callers are migrated in this slice; no fallback alias is added because that would recreate the conflation.
- MCP `thread_ref` remains the trusted/current requesting task context and a new optional `source_thread_ref` is the model-selected historical filter. Disproof: an integration supplies `thread_ref` as historical scope today; action: stop and document/migrate that integration before merge.
- Source-only filter resolution must ignore runtime context entirely so an explicit historical filter is never relaxed. `request_source_item_id` validation uses `active_session_ref`; non-source-only runtime inference and filtering remain unchanged. Disproof: proactive-query regressions require changing shared policy; action: stop and return to planning rather than weakening the exact History contract.

**Plan:**
1. Add red focused tests proving the current conflation: broad MCP search from active session C must recover eligible sources in A and B; an explicit source-thread filter must return only its exact thread; exact-work plus a source-thread filter must intersect rather than broaden; empty scope returns no candidates.
2. Add `active_session_ref` to the source-only HTTP query contract and `source_thread_ref` to both MCP History tools/client methods. The MCP client removes context `thread_ref` from History payload filters, emits it as `active_session_ref`, and emits `thread_ref` only when `source_thread_ref` is explicitly supplied.
3. At the shared query-executor boundary, pass `runtime_context=None` into source-only filter resolution, including when the caller explicitly supplied runtime context, so exact historical thread scope is never relaxed. Skip source-only runtime inference entirely. Leave non-source-only runtime inference and filtering unchanged.
4. In service orchestration, keep `thread_ref` as the retrieval filter. For source-only queries use `active_session_ref` for request-source lineage validation and persisted lookup `session_id`; never fall back to the historical source filter as requester identity. Forward the split through `/query` and `/query/debug`.
5. Keep response-local `current`/`other-N`/`unknown` grouping relative to the MCP context active session, not the optional source filter. Bind requester context and `source_thread_ref` into result-page revisions and retain raw thread-ID suppression.
6. Migrate `evals/continuity_handoff_benchmark.py` and `scripts/live_funnel_smoke.py` to `active_session_ref`, retaining HTTP `thread_ref` only when they intentionally request historical filtering.
7. Add a real MCP-to-HTTP lifecycle journey covering omitted filter, same-thread, other-thread, unknown-thread, exact-work intersection, nonexistent thread, visibility, forgetting, audit session attribution, expansion lineage, and absence of raw session IDs. Reuse existing fixtures and cite existing edge tests instead of duplicating them.
8. Align HTTP/MCP docs and tool descriptions, explicitly document the source-only compatibility change, and mark only roadmap delivery slice 4 complete. Stop if correctness requires ranking, persistence schema, dependencies, or authorization-policy changes.

**Verification plan:**
- When active session C performs broad History with no source filter, eligible A/B/unknown candidates shall remain available and the lookup audit shall attribute C -> focused client/tool tests plus real MCP-to-HTTP E2E.
- When `source_thread_ref=A` is supplied, only A candidates shall be returned; nonexistent/empty scope shall return the existing bounded no-result contract -> focused API/MCP tests plus E2E.
- When source-only callers provide same-thread, resumed, or new/insufficient runtime context, explicit source-thread scope shall remain requested/effective and never relax; proactive queries shall retain existing relaxation -> HTTP trace regressions and existing proactive routing tests.
- When exact-work search has no source filter or an explicit A/B filter, it shall stay exact to the work reference and intersect the thread filter without broadening -> focused client/tool tests plus E2E.
- When request lineage is supplied, its live user request must match the active requesting session, not the historical source filter; missing/mismatched/forgotten lineage shall fail closed and finalize nothing -> HTTP/service-focused tests.
- When same/other/unknown source sessions are grouped, labels shall be relative to the active session and serialized output shall contain neither `thread_ref` keys nor raw source/requester session values -> presentation tests plus E2E response assertions.
- When visibility, actor, forgetting, paging, stale revisions, and replacement guidance are exercised, existing enforcement and ordering shall remain unchanged -> existing History visibility/lifecycle/paging suites and the new E2E journey.
- When implementation is ready for review, all focused and affected History/MCP/API files plus the required last-failure, full-suite, import-linter, redline, workflow, and diff checks shall pass -> named local commands and CI evidence.

**Plan review:**
Clean-context reviewer /root/session_scope_plan_review rejected commit 165606f2 because runtime-context policy could still relax explicit source scope and requester-only benchmark/smoke callers were omitted. The corrected plan in f6bcf6c9 adds an unconditional source-only runtime-context bypass, proactive compatibility checks, both HTTP routes, caller migrations, and HTTP documentation. The same reviewer approved f6bcf6c9 with no remaining blockers.

**Approvals:**
Approved by user 2026-09-22: "yes, i told you i approve all the work on this feature. i'm not here all the time so don't wait for me. continue with all the issues we need to fix"

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Checkpoint: architecture-review

What is changing: split source-only History requester identity from retrieval thread filtering in core query orchestration, without changing ranking or persistence schema.

Why: the current shared `thread_ref` silently narrows broad retrieval and misstates the role of the active task identity.

Affected contract / model / boundary: `core/service.py` orchestration receives separate active and source session values; `core/query.py` prevents runtime policy from relaxing source-only filters; generic filter models remain unchanged.

Compatibility / migration risk: medium-high; source-only HTTP callers gain an additive requester field and must no longer treat a source filter as requester attribution.

Verification plan: focused service/request-lineage tests, real MCP-to-HTTP broad/exact lifecycle, existing visibility/forgetting/paging suites, full suite, and clean-context review.

## Checkpoint: api-review

What is changing: add optional HTTP `active_session_ref` and MCP `source_thread_ref` inputs with explicit, non-overlapping semantics.

Why: existing `thread_ref` is overloaded between requester telemetry and historical candidate filtering.

Affected contract / model / boundary: additive QueryRequest and MCP tool inputs; existing response shapes and budgets remain stable.

Compatibility / migration risk: medium; existing MCP calls become correctly broad by default, while explicit filtering moves to `source_thread_ref`.

Verification plan: tool-schema/payload tests, strict scope/lifecycle tests, and caller-surface E2E assertions for grouping and non-leakage.

## Implementation

Discovery, refreshed pre-edit classification, and clean-context plan review are complete. Planned edits are limited to `app/mcp/client.py`, `app/mcp/server.py`, `api/schemas.py`, `api/routes.py`, `core/service.py`, `core/query.py`, the two identified eval/smoke callers, focused History/MCP tests, `docs/http-api.md`, `docs/session-history.md`, this Work Record, and roadmap slice 4. Red/API checkpoints apply through the schema, route, and service files; core query and MCP surfaces are gray/watch; no boundary dependency changes are planned. Two bounded workers added non-overlapping red tests only. The client/tool run produced 5 intended failures and 46 passes: missing requester attribution, missing source-filter parameters, and missing tool schema/forwarding. The HTTP lifecycle regression failed at request lineage because the implementation compared the request source against the historical source filter. These red baselines are committed in 684894ed and d91f7602; production implementation can now start.

Implementation now separates the scopes at their shared boundaries: the History client remaps integration context to requester attribution, MCP exposes an optional source filter and binds both values into paging revisions, HTTP forwards both fields, source-only filter resolution bypasses runtime relaxation, and service lineage/audit use the active requester. The continuity benchmark, live funnel smoke, and history-pull decision harness requester-only callers were migrated; the exact-thread Relay association example remains intentionally filtered. Proactive query handling is unchanged. Legacy test fixtures were migrated only where they encoded requester identity in the old overloaded field. Because apply_patch had already failed with the known Windows 1327 process error, all edits used narrowly scoped deterministic replacements; an attempted stdin Git patch made no changes. The focused History/tool/lifecycle set passes: 80 passed.

High-reasoning result review found no production defect but requested three P2 coverage/status corrections. The remediation now makes work-ref and source-thread dimensions independently necessary, exercises both real MCP client methods through HTTP with active-session lineage and finalized audit attribution, invalidates paging revisions when either scope changes, covers missing active lineage on both routes and all relaxing runtime-context modes, repairs a legacy exact-work lifecycle assertion, keeps slice 1 active in the roadmap, and restores the MCP guidance budget. Follow-up review confirmed those three findings closed, then caught that the budget edit had removed the explicit warning that history cannot prove live state, approval, or completed actions. The full warning is restored within budget; both the historical-warning and guidance-budget nodes pass.
## Evidence

Red baselines: 5 client/tool failures with 46 passes, plus the HTTP lineage failure, were committed before production code. Focused implementation verification passed 80 tests. The affected subsystem run reached 383 passes, 2 skips, and 7 deselections before one legacy attribution assertion; its migrated node and the history-pull harness then passed (12 tests). The required last-failure run was clear. Import Linter kept all 8 contracts. Fresh redline classification is RED with zero boundary violations and architecture/API checkpoints; the workflow checker is non-blocking pending PR labels. Reviewer remediation passed the 119-test set after one duplicate-content fixture correction, both warning/budget nodes passed, and the final high-reasoning review approved d3033b35. The clean full suite passed: 5,177 passed, 34 skipped, 2 xfailed in 200.90 seconds.

## Result review

High-reasoning reviewer /root/session_scope_plan_review reviewed acb6d17d and found no production-code defect. It requested three P2 corrections: independent source/work scope regressions plus real finalized MCP-to-HTTP coverage and runtime/revision edge cases; migration of an exact-work lifecycle fixture that silently searched an empty scope; and correction of premature slice-1 roadmap completion. Follow-up at 428b1d61 confirmed those findings closed but found one new P2 regression: the shortened tool description omitted the required approval/live-state/completed-actions warning. The warning is restored under the guidance budget. Final follow-up approved d3033b35 with all findings closed; the only residual risk is the documented migration for external source-only HTTP callers that used `thread_ref` only as requester identity.
