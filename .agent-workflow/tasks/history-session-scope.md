<!-- agent-workflow:start -->
**Outcome:**
Session History uses the active requesting session only for telemetry, request lineage, and response-local grouping, while an optional source-thread filter independently narrows historical candidates.

**Target:**
Pallium.

**Scope:**
Separate active-session attribution from source-thread filtering across the two Session History MCP tools, MCP client, source-only HTTP query contract, route, and core query orchestration; add focused and caller-surface E2E coverage; align `docs/session-history.md` and delivery slice 4 in `roadmap/features/fix-session-history-evidence-access.md`.

**Constraints:**
Keep container, actor, visibility, exact-work, redaction, forgetting, ranking, candidate ordering, result paging, response budgets, and historical-state warnings unchanged. Broad History remains broad when no source-thread filter is supplied. Exact-work search intersects an optional source-thread filter and never broadens. Active session identity must never be inferred from a historical source or exposed raw in MCP responses. Retrieval alone must not update accessibility or ranking state.

**Completion criteria:**
The public contracts name requester attribution and source scope separately; broad, thread-exact, exact-work, empty-scope, same/other/unknown grouping, request-lineage, visibility, forgetting, audit attribution, and raw-identity non-leakage are proven through focused tests and at least one real MCP-to-HTTP lifecycle journey; required workflow, redline, review, and test gates pass.

**Requirement baseline:**
{"source":"roadmap-slice-4","outcome":"Session History uses the active requesting session only for telemetry, request lineage, and response-local grouping, while an optional source-thread filter independently narrows historical candidates.","scope":"Separate active-session attribution from source-thread filtering across the two Session History MCP tools, MCP client, source-only HTTP query contract, route, and core query orchestration; add focused and caller-surface E2E coverage; align docs and roadmap delivery slice 4.","constraints":"Keep container, actor, visibility, exact-work, redaction, forgetting, ranking, candidate ordering, result paging, response budgets, and historical-state warnings unchanged. Broad History remains broad without a source-thread filter; exact-work never broadens; active session identity is never inferred from a historical source or exposed raw.","completion_criteria":"Distinct public contracts and full broad/thread-exact/exact-work/empty/grouping/lineage/visibility/forgetting/audit/non-leakage coverage pass with workflow and review gates."}

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Pre-edit agent-redline classifies `api/schemas.py`, `api/routes.py`, and `core/service.py` as red/watch, with architecture-review and API-review checkpoints; `app/mcp/client.py` and `app/mcp/server.py` are gray/watch. The change corrects caller-visible scope semantics and audit identity at a trust boundary, but remains additive and uses the existing query/filter/audit path without persistence or ranking changes.

**Discovery:**
Both History MCP tools build payloads through `PalliumMcpClient._scope_params()`, which copies the context `thread_ref` into `QueryRequest.thread_ref`. `core.service.query` then uses that one value both as `QueryFilters.thread_ref` and as the persisted historical lookup `session_id`; it also uses it for runtime context and `request_source_item_id` scope validation. Consequently an active MCP task silently narrows broad History to its own thread, while telemetry cannot distinguish requester from historical source scope. Source expansion already models the desired split through `active_session_ref` plus the anchor's source thread, so slice 4 can reuse that naming and behavior.

**Material assumptions:**
- `QueryRequest.thread_ref` remains the historical source-thread filter, while a new optional `active_session_ref` is requester attribution for source-only queries. Disproof: a non-History HTTP caller relies on source-only `thread_ref` as requester-only metadata; action: preserve a compatibility alias only if that caller is identified and add an explicit deprecation contract rather than guessing.
- MCP `thread_ref` remains the trusted/current requesting task context and a new optional `source_thread_ref` is the model-selected historical filter. Disproof: an integration supplies `thread_ref` as historical scope today; action: stop and document/migrate that integration before merge.
- Source-only runtime-context resolution and `request_source_item_id` validation should use `active_session_ref`, while retrieval filters continue to use `thread_ref`. Disproof: replay tests show candidate/ranking changes when active session is separated; action: stop and return to planning because ranking is outside this slice.

**Plan:**
1. Add red focused tests proving the current conflation: broad MCP search from active session C must recover eligible sources in A and B; an explicit source-thread filter must return only its exact thread; exact-work plus a source-thread filter must intersect rather than broaden; empty scope returns no candidates.
2. Add `active_session_ref` to the source-only HTTP query contract and `source_thread_ref` to both MCP History tools/client methods. The MCP client removes context `thread_ref` from History payload filters, emits it as `active_session_ref`, and emits `thread_ref` only when `source_thread_ref` is explicitly supplied.
3. In query orchestration, keep `thread_ref` as the retrieval filter. For source-only queries use `active_session_ref` for runtime-context resolution, request-source lineage validation, and persisted lookup `session_id`; never fall back to the historical source filter as requester identity. Leave non-source-only behavior unchanged.
4. Keep response-local `current`/`other-N`/`unknown` grouping relative to the MCP context active session, not the optional source filter. Bind `source_thread_ref` into result-page revision context and retain raw thread-ID suppression.
5. Add a real MCP-to-HTTP lifecycle journey covering omitted filter, same-thread, other-thread, unknown-thread, exact-work intersection, nonexistent thread, visibility, forgetting, audit session attribution, and absence of raw session IDs. Reuse existing fixtures and cite existing edge tests instead of duplicating them.
6. Align docs/tool descriptions and mark only roadmap delivery slice 4 complete. Stop if correctness requires ranking, storage schema, dependency, or authorization-policy changes.

**Verification plan:**
- When active session C performs broad History with no source filter, eligible A/B/unknown candidates shall remain available and the lookup audit shall attribute C -> focused client/tool tests plus real MCP-to-HTTP E2E.
- When `source_thread_ref=A` is supplied, only A candidates shall be returned; nonexistent/empty scope shall return the existing bounded no-result contract -> focused API/MCP tests plus E2E.
- When exact-work search has no source filter or an explicit A/B filter, it shall stay exact to the work reference and intersect the thread filter without broadening -> focused client/tool tests plus E2E.
- When request lineage is supplied, its live user request must match the active requesting session, not the historical source filter; missing/mismatched/forgotten lineage shall fail closed and finalize nothing -> HTTP/service-focused tests.
- When same/other/unknown source sessions are grouped, labels shall be relative to the active session and serialized output shall contain neither `thread_ref` keys nor raw source/requester session values -> presentation tests plus E2E response assertions.
- When visibility, actor, forgetting, paging, stale revisions, and replacement guidance are exercised, existing enforcement and ordering shall remain unchanged -> existing History visibility/lifecycle/paging suites and the new E2E journey.
- Before review, focused nodes, affected History/MCP/API files, `pytest --lf --lfnf=none -q -n 0`, one full `pytest tests/ -x -q`, import-linter, redline, workflow checker, and `git diff --check` shall pass.

**Plan review:**
Pending clean-context review.

**Approvals:**
Approved by user 2026-09-22: "yes, i told you i approve all the work on this feature. i'm not here all the time so don't wait for me. continue with all the issues we need to fix"

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Checkpoint: architecture-review

What is changing: split source-only History requester identity from retrieval thread filtering in core query orchestration, without changing ranking or persistence schema.

Why: the current shared `thread_ref` silently narrows broad retrieval and misstates the role of the active task identity.

Affected contract / model / boundary: `core/service.py` orchestration receives separate active and source session values; query filters remain generic and unchanged.

Compatibility / migration risk: medium-high; source-only HTTP callers gain an additive requester field and must no longer treat a source filter as requester attribution.

Verification plan: focused service/request-lineage tests, real MCP-to-HTTP broad/exact lifecycle, existing visibility/forgetting/paging suites, full suite, and clean-context review.

## Checkpoint: api-review

What is changing: add optional HTTP `active_session_ref` and MCP `source_thread_ref` inputs with explicit, non-overlapping semantics.

Why: existing `thread_ref` is overloaded between requester telemetry and historical candidate filtering.

Affected contract / model / boundary: additive QueryRequest and MCP tool inputs; existing response shapes and budgets remain stable.

Compatibility / migration risk: medium; existing MCP calls become correctly broad by default, while explicit filtering moves to `source_thread_ref`.

Verification plan: tool-schema/payload tests, strict scope/lifecycle tests, and caller-surface E2E assertions for grouping and non-leakage.

## Implementation

Discovery and pre-edit redline classification complete. No production or test edits have been made.

## Evidence

Pending red baseline and implementation verification.

## Result review

Pending.
