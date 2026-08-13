# Task: add-raw-historical-search-mode

Pallium vNext P1. Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 1).
Part of the overnight P1 run (auto-merge when green; resolve blockers with best judgment).

<!-- agent-workflow:start -->
**Outcome:**
A caller can request a source-only history search and receive relevance-ranked prior raw `source_hit`s as first-class results — with stable source ids and a raw rank — scoped and visibility-enforced, not starved by memory objects, and without the memory-only abstention gate. The existing proactive/injection query path is unchanged.

**Target:**
pallium

**Scope:**
`retrieval/base.py` (add default-off `target_kind` param to `RetrievalProvider.query`); `storage/sqlite_search.py` + `retrieval/vector.py` + `retrieval/composite.py` (honor the kind restriction at the candidate level, before top-K/fusion; skip-only, additive); `core/query.py` (`QueryExecutor.query` gains a `source_only` mode: restrict candidates + bypass `core_route`, return results directly with `should_inject=False` and a source-only trace); `core/service.py` (`PalliumService.query` passthrough — redaction barrier already covers it); `core/models.py` (`raw_rank` on `QueryResultItem`); `api/schemas.py` + `api/routes.py` (`source_only` on `QueryRequest`; `raw_rank` on result serialization); `tests/`. NOT: the agent-facing tool (`add-agent-historical-lookup-tool`); source-context expansion (`add-source-context-expansion`); any change to routing scoring/selection/abstention; RAW/DERIVED/HYBRID shadow eval.

**Constraints:**
Every new parameter defaults to current behavior (default-off) — the proactive path stays byte-identical when unset (Done-When #2). Candidate restriction happens BEFORE top-K/fusion (not a post-filter on a blended page) so memory hits never consume source-search slots; no parallel retrieval stack (reuse lexical/vector/RRF/visibility/filter/redaction/trace). Do NOT reuse `resolve_query_filters` to carry the mode (it feeds the proactive path). Do NOT touch `_specificity_bonus_source_hit`, `MIN_SOURCE_HIT_SLOTS`, or companion logic. Visibility fail-closed (0 violations). Forgotten-source gate (P0) must still exclude forgotten turns. `api-stays-thin`. No internal/external product names in committed docs/tests.

**Completion criteria:**
1. A source-only search returns up to K relevance-ranked prior source turns (stable source id + raw rank), scoped + visibility-enforced, and memory hits never occupy source-search slots — proven by a test where memory objects would otherwise starve sources → source-only still returns the source turns.
2. The source-only mode does not alter `should_inject`/`injectable_blocks` for existing proactive queries → regression test on the default path.
3. Retrieval trace explains the source-only ranking (stages + fusion + a mode marker + result_summary) → test/inspection.
4. Visibility enforcement on raw results is fail-closed (0 violations) AND forgotten turns are excluded → tests.
5. No parallel stack: fusion/visibility/filtering/redaction/trace are the existing shared components (verified by the additive-param design; default path unchanged).

**Risk:** High

**Complexity:** Moderate

**Reason:**
`core/service.py` red → architecture-review; `core/query.py` watch; touches the shared retrieval providers used by the live proactive path → persistence/retrieval-contract surface. High per contract-surface + shared-retrieval clause. Moderate: ~9 files, additive default-off params, one coherent slice. Redline pre-edit verdict is the first implementation step (may raise, not lower).

**Discovery:**
(from a read-only retrieval-surface investigation, 2026-08-13 — file:line cited)
- `QueryExecutor.query` (`core/query.py:57-212`) orchestrates: `resolve_query_filters` → visibility guard → over-fetch `min(max(limit*4,12),50)` → `self._retrieval.query` → `core_route`. A no-routing branch already exists at `core/query.py:200-212` (returns results with a `result_summary`, no routing) — the template for the source-only bypass.
- `CompositeRetrievalProvider._rrf_merge` (`retrieval/composite.py:68-205`) is kind-agnostic (fuses on `result_id`). Starvation: both providers over-fetch `limit*4` (`retrieval/lexical.py:114`, `retrieval/vector.py:87`) but hydrate+truncate to `limit` (`lexical.py:182`, `vector.py:226`), and lexical tie-breaks toward `memory_object` (`storage/sqlite_search.py:130-136`) → memory consumes the shared budget before fusion.
- `target_kind` is available at candidate level in BOTH paths before truncation: lexical `row.target_kind` (`storage/sqlite_search.py:64,74`), vector `index_entry.target_kind` (`retrieval/vector.py:122,147`). No existing kind filter on `RetrievalProvider.query` (`retrieval/base.py:15-28`) → clean additive insertion point.
- Memory-injection gating lives entirely in `route_query_results` (`semantic/agent_conversation_memory_routing.py:131-558`) and `_build_injectable_blocks` (`..._routing_selection.py:880-1135`, incl. abstention `should_allow_injection` at `:923`). Bypassing `core_route` for source-only avoids it entirely; `should_inject`/`injectable_blocks` never entered → proactive path untouched.
- `QueryResultItem` source_hit (`core/models.py:229-266`) already carries excerpt/occurred_at/thread_ref/actor_ref/source_item_id/score/retrieval_source. MISSING: a raw-rank ordinal on the item (rank exists only in `FusionTraceHit.rrf_rank`, `core/models.py:309`). → add `raw_rank`.
- Redaction `_redact_query_result` (`core/service.py:111-155`, invoked `:701`) + visibility `is_visible` (`storage/sqlite_search.py:99-114`, `retrieval/vector.py:162`) + `matches_filters` (`core/filters.py:44-91`, with the P0 forgotten gate at `:67-76`) all run on the shared path → source-only reusing the executor gets them for free.
- `/query` route `api/routes.py:411-457`, `QueryRequest` `api/schemas.py:95-116`, `_serialize_result` `api/routes.py:86-109`. MCP `pallium_query` (`app/mcp/server.py:35-54`) — MCP passthrough is out of scope (the tool is P1.2).
- Test harness: `tests/test_vector_retrieval.py:191-207` (source_hit), `tests/test_visibility_scope.py` (HTTP source_hit filtering), `tests/test_retrieval_relevance_floor.py`.

**Material assumptions:**
1. A default-off `source_only` bool on `QueryRequest` (mapped internally to `target_kind="source_item"`) is the right minimal surface; a general `mode` enum / RAW-DERIVED-HYBRID is out of scope. Disproof: reviewer wants an extensible `mode` enum now. Action: rename the param to `mode: Literal[...]` — mechanically small.
2. Bypassing `core_route` entirely (vs. running routing with a source-only flag) is correct and lowest-risk. Disproof: some cross-cutting concern (e.g. query-stats/audit) only fires inside routing and is needed for source-only. Action: attach the missing concern in the bypass branch (mirror the existing no-routing branch).
3. Raw rank = 1..K by final fused result order, set on the item in the source-only branch. Disproof: rank must reflect pre-fusion per-provider rank. Action: carry provider rank through (fusion trace already has rrf_rank to map from).

**Plan:**
1. Redline pre-edit verdict (via `/agent-workflow`) to confirm High + checkpoints.
2. `retrieval/base.py`: add `target_kind: str | None = None` to `RetrievalProvider.query`.
3. `storage/sqlite_search.py` + `retrieval/vector.py`: skip non-matching `target_kind` at the candidate loop (before truncation); `retrieval/composite.py`: pass through to both sub-providers (RRF unchanged).
4. `core/query.py`: `QueryExecutor.query(..., source_only: bool = False)`. When set: pass `target_kind="source_item"` to retrieval, skip `core_route`, build `QueryResult(results=..., should_inject=False, decision_reason="source_only_search", injectable_blocks=[], trace=<stages+fusion+visibility+result_summary+{"mode":"source_only"}>)`; assign `raw_rank` 1..K by order.
5. `core/service.py`: thread `source_only` through `PalliumService.query` (redaction already applied on return).
6. `core/models.py`: `raw_rank: int | None = None` on `QueryResultItem`.
7. `api/schemas.py`: `source_only: bool = False` on `QueryRequest`; `raw_rank` on `QueryResultResponse`. `api/routes.py`: pass through; set `raw_rank` in `_serialize_result`.
8. Tests: (a) starvation — seed many memory objects + a few source turns on the same query; source-only returns the source turns with raw_rank; default mode may bury them. (b) default path `should_inject`/`injectable_blocks` unchanged (regression). (c) visibility fail-closed on source-only (mixed-container). (d) forgotten turn excluded from source-only. (e) trace has mode marker + result_summary.
Key conventions: additive default-off params; anonymized tests; label eval numbers per `docs/context/lessons.md`.
Stop conditions: if the candidate-level kind filter can't be made strictly skip-only without perturbing the default path → stop, reconsider. If bypassing routing drops a concern the proactive path depends on for correctness → reconcile.

**Verification plan:**
1. Source-only returns ranked source turns not starved by memory → integration test (HTTP + provider level).
2. Default `/query` `should_inject`/`injectable_blocks`/results unchanged → regression test + full suite.
3. Visibility fail-closed (0 violations) on source-only + forgotten excluded → tests.
4. Trace explains source-only ranking → assert stages/fusion/result_summary/mode present.
5. Full suite green → `python -m pytest tests/ -q` (real interpreter per `~/.claude/python-on-windows.md`).

**Plan review:**
Clean-context agent review completed (2026-08-13). Findings adopted:
- SEV-1: the loop-skip runs AFTER the truncating fetch (lexical FTS `LIMIT :limit`, vector `k`), so memory rows can fill the window and starve sources. FIX: push the kind restriction into the lexical FTS SQL — keyword-only `target_kind` on `search_index_entries`, append `AND target_kind = :target_kind` to the WHERE. Lexical becomes a true guarantee (all fetched rows are sources) and the `memory_object` tie-break becomes irrelevant. Vector ANN can't filter by kind → stays best-effort within over-fetch; acceptable because lexical is required (`composite.py:24-30`) and has higher RRF weight (1.5 vs 1.0), so it dominates fusion. Keep the loop-skip too (defense-in-depth) but do NOT rely on it alone.
- SEV-2a: both existing terminal branches call `self._query_stats.record_query(result)` (`query.py:197-198,210-211`); the source-only branch MUST also call it or source-only queries vanish from stats/metrics.
- SEV-2b: add a redaction test (governance-mandated by the feature Notes) — a secret in a source excerpt comes back redacted on the source-only path; confirm the `artifact_kind=="note"` carve-out.
- SEV-3a: `QueryTrace` has no mode field; put the marker at `trace.routing = {"mode":"source_only"}` (already serialized by `_serialize_trace`). Normal `/query` returns no trace (only `/query/debug` does) and `include_trace=False` → `retrieval_result.trace is None`; guard the `replace(trace, ...)` exactly like the no-routing branch (`query.py:200-202`). Assert trace via `/query/debug` or executor level.
- SEV-3b: keep the DEFAULT retrieval call site (`query.py:124-133`) byte-identical — pass `target_kind` ONLY inside the source-only branch. New params keyword-only. Test stubs (`StubRetrievalProvider`/`CapturingProvider`) don't accept the kwarg but are never driven through the executor, so this is safe.
- SEV-3c: insert the source-only branch AFTER the visibility fail-closed guard (`query.py:87-115`) so missing container/visibility still fails closed; the source-only `self._retrieval.query(...)` must pass the SAME visibility args (`visibility=`, `query_container_ref=`, `require_visibility=`, `query_actor_ref=`) + reuse `effective_filters` (carries the P0 forgotten gate). Passing only `target_kind` would skip `is_visible`.
- raw_rank: append `raw_rank: int | None = None` to frozen `QueryResultItem`; set via `dataclasses.replace(item, raw_rank=i)`; add to `QueryResultResponse` + `_serialize_result` or Pydantic drops it.

**Approvals:**
Approved by user 2026-08-13: "yes, auto merge if all green" — overnight mandate to complete all P1 work, auto-merging each PR when CI + review are fully green. Blocker policy (user 2026-08-13): "try to resolve blockers if you can, only break if you really need me." This is the recorded High-risk human approval for the P1 items in this run.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

(in progress — overnight P1 run)
