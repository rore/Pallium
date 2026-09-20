<!-- agent-workflow:start -->
**Outcome:** Exact work-reference history searches complete promptly and return a Pallium result or structured Pallium timeout before the Codex 30-second tool deadline.

**Target:** Pallium.

**Scope:** `retrieval/vector.py`, `app/mcp/server.py`, `tests/test_vector_retrieval.py`, `tests/test_exact_work_ref_search.py`, `tests/test_mcp_server.py`, `roadmap/ideas/idea-retrieval-source-fetch-batching.md`, and `docs/reports/vnext-perf-e2e-validation.md` only.

**Constraints:** Preserve exact work-ref filtering, semantic-only vector recovery, visibility/actor/container filters, forgotten/deleted source guarantees, result ordering, public HTTP/MCP contracts, and retrieval-only accessibility invariants. No schema, dependency, or general storage rewrite.

**Completion criteria:** When an exact work-ref query must pass many higher-ranked ineligible vector candidates, Pallium shall batch source reads instead of issuing per-candidate reads and still return the same eligible results. When a history backend exceeds its bounded budget, the MCP caller shall receive a structured timeout before the host's 30-second deadline. The reproduced production query shall no longer time out after installation, and measured before/after latency shall be recorded.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Clean-context redline classified retrieval/app implementation paths as gray/watch with no boundary or contract checkpoint. Moderate complexity because the fix spans retrieval correctness, timeout behavior, deterministic E2E coverage, and live latency verification.

**Discovery:** The affected Codex call ran for 30.004 s and failed at the host boundary. Its server-side lookup attempt was persisted roughly six seconds later and never finalized. Replaying the same HTTP query took 29.589 s; the same exact work-ref lookup with blank text (vector intentionally bypassed) took 0.970 s. The exact lexical SQL itself took 0.110-0.136 s. `retrieval/vector.py` batch-loads index entries but calls `get_source_item` through filtering, visibility, and hydration for each vector candidate; `retrieval/lexical.py` already uses the shared `get_source_items` batch helper plus final emission revalidation. `app/mcp/client.py` gives each sequential HTTP request the same 30 s timeout as the entire host tool call, so it cannot surface its own timeout reliably.

**Material assumptions:** The per-candidate vector source reads dominate the incident; if the same production query remains above 5 s after batch hydration, stop and profile ANN expansion before widening scope. A 25 s aggregate history-tool deadline leaves adequate host-return headroom; if focused tests disprove that timing margin, stop and measure FastMCP overhead rather than extending the deadline.

**Plan:** 1. In `retrieval/vector.py`, call existing `get_source_items` once per ANN expansion batch; serve work-ref/filter, visibility, and hydration reads from that map, skip missing rows, then batch-revalidate final emitted source IDs and keep selected trace hits consistent. Do not add a storage API, schema, dependency, or ranking change. 2. In `tests/test_vector_retrieval.py`, prove zero per-candidate `get_source_item` calls, one batch source read per ANN expansion plus one final revalidation, ordered eligible-tail recovery, and mid-query forget/hard-delete exclusion. Keep the enabled-vector HTTP semantic-only tail E2E in `tests/test_exact_work_ref_search.py` so lexical retrieval cannot mask vector failure. 3. In `app/mcp/server.py`, apply one 25 s outer deadline around each complete broad/exact history search -> compaction -> delivery-finalization sequence; on expiry return a bounded structured `transport_timeout`. In `tests/test_mcp_server.py`, cover search-stage expiry and finalization-stage expiry through FastMCP. 4. Correct the existing roadmap/report text to distinguish the completed lexical batching from this vector residual; do not change harness schema. 5. Run focused tests, affected retrieval/MCP/E2E files, workflow checks, full tests once, independent smart result review, and a measured same-query live replay after installing/restarting through the repository wrapper. Stop and return to planning if batching does not reduce the reproduced query below 5 s or changes retrieval results.

**Verification plan:** When exact-work vector search crosses many ineligible candidates, it shall issue no per-candidate source reads, use one batch read per ANN expansion plus one final revalidation, and return ordered eligible tail candidates -> deterministic provider query-shape test plus semantic-only enabled-vector HTTP E2E. When a source is forgotten or deleted during batched retrieval, it shall not be emitted and its trace selection shall be removed -> vector emission-boundary regressions. When search itself stalls or finalization stalls after a successful search, the whole FastMCP history tool shall return structured `transport_timeout` before 30 s -> parameterized MCP server tests with a shortened test deadline. When the fix is installed, the exact incident query shall complete below 5 s with the same eligible result count -> timed local production replay recorded as evidence, not a CI timing gate. All changed behavior -> focused pytest files, affected subsystem tests, `--lf`, workflow/redline check, then `python -m pytest tests/ -x -q` once.

**Plan review:** Clean-context gpt-5.6-sol review recorded in `## Plan review`; all blocking findings are resolved in this plan.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Diagnose: reproduced the exact incident and isolated the delay to text-bearing vector retrieval rather than lexical SQLite search.
- Assess risk: clean-context redline verdict GRAY, no boundary/checkpoint finding; declared Elevated/Moderate.

## Evidence

- Affected request source: `1bae2bf2-8a31-451f-b8a0-ecc49e3fbcc3`; deferred attempt `e5b5afbd-f55d-4dfe-9880-0fe9f3aebe4a` persisted after the host timeout.
- Reproduction: exact HTTP query 29.589 s; blank exact-work query 0.970 s; bounded/unbounded lexical SQL 0.110/0.136 s.

## Plan review

Clean-context gpt-5.6-sol review verdict was "Revise before implementation." It found that per-request timeouts could still exceed the host deadline, batching only hydration would retain the filter/visibility N+1, and output-only tests would not prove the query shape. The revised plan now uses one aggregate 25 s tool deadline, one source batch map for every vector candidate gate plus final revalidation, deterministic DB-call assertions and forget/delete races, a semantic-only vector E2E, explicit target files, and correction of the stale performance report.

## Result review

Pending.
