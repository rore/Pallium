# retrieval-source-fetch-batching

<!-- agent-workflow:start -->
**Outcome:**
The shared lexical retrieval path replaces the per-candidate source_item N+1 (up to 3 reads per candidate) with batched reads — one batched read at the candidate gate (`storage/sqlite_search.py`) and one at hydration (`retrieval/lexical.py`), plus one batched emission-time revalidation read of the final result ids — dropping the per-slot engine-query slope from O(candidates) (~9/slot) to a small constant. The committed deterministic count baseline is regenerated (lower) and the default-lane count gate stays green. Zero behavior change to retrieval results, visibility enforcement, forgotten-source exclusion, and redaction; a source item forgotten/deleted mid-query is never emitted (emission-time revalidation).

**Target:**
Pallium storage + retrieval layers (watch-zone): `storage/sqlite_search.py`, `storage/sqlite.py`, `storage/base.py`, `retrieval/lexical.py`. Plus regenerated `evals/vnext_perf_baseline.json`.

**Scope:**
- Add a batched source-item accessor `get_source_items(ids) -> dict[str, SourceItem]` (abstract in `storage/base.py`, implemented in `storage/sqlite.py`) via a single `WHERE id IN (...)`.
- In `storage/sqlite_search.py`: prefetch all source_item candidate ids once, pass a memoizing getter into `matches_filters` + `target_visibility_and_container` (collapses the double per-candidate fetch to one batched query).
- In `retrieval/lexical.py`: batch the per-hit hydration fetch for source_item hits.
- Regenerate `evals/vnext_perf_baseline.json` via the harness.

**Constraints:**
- NO edits to `core/filters.py`, `core/query.py`, `core/visibility.py`, `core/routing.py`, or any red-zone file. Batching is upstream of core: core receives identical `SourceItem` objects.
- Query-COUNT optimization only. Retrieval results, visibility enforcement, forgotten-source exclusion, redaction, and the forgotten-gate ordering (forgotten check before the `filters is None` early return in `matches_filters`) must be byte-for-byte unchanged.
- No red persistence touch — N+1 #2 (offline loader index on `storage/sqlite_schema.py`) is DEFERRED (see Discovery).

**Completion criteria:**
- `tests/test_historical_lookup_funnel_e2e.py`, `tests/test_source_only_search.py`, `tests/test_visibility_scope.py`, `tests/test_soft_deleted_visibility.py`, `tests/test_global_visibility.py`, `tests/test_raw_turn_forgetting.py` all green.
- `tests/test_vnext_perf_count_gate.py` green against regenerated baseline; both count-gate self-tests pass (including seeded-regression).
- Regenerated baseline shows source_only_query + n1_double_get_source_item engine_queries DROP vs current (182 -> small constant); loader numbers unchanged.
- Full default pytest lane green (only allowed failure: known-benign `tests/test_config.py::test_prompt_variants_legacy_fallback_unaffected`).

**Risk:** Elevated

**Complexity:** Moderate

**Reason:**
Redline: all planned files are watch-zone (`storage/**`, `retrieval/**`); no named red file touched -> Elevated (conservative default for watch/gray). Judgment considered High because the path enforces visibility + forgotten-source exclusion (security-adjacent), but the batching is transparent upstream of `core/filters.py`/`core/visibility.py` (core sees identical `SourceItem` objects and the same call order), so Elevated is proportional. CI redline re-classifies against the final diff. Moderate complexity: two layers (storage search + retrieval hydration) + new accessor + baseline regen + invariant proof.

**Discovery:**
Three redundant per-candidate source_item fetches confirmed:
1. `storage/sqlite_search.py:84` — `matches_filters(...)` -> `self.get_source_item` (forgotten gate + field filters).
2. `storage/sqlite_search.py:102` — `target_visibility_and_container(...)` -> `self.get_source_item` (visibility/container).
3. `retrieval/lexical.py:154` — `self._storage.get_source_item(hit.target_id)` (hydration).
Candidate window: `core/query.py:127` source_only `retrieval_limit=min(max(limit*4,12),50)`, then `retrieval/lexical.py:111` searches with `limit*4` -> FTS window up to ~4x. Measured ~9 engine queries/slot (`evals/vnext_perf_baseline.json`, `docs/reports/vnext-perf-e2e-validation.md`).
The forgotten gate + `filters is None` early-return ordering lives entirely in `core/filters.py:67-91`; we do not touch it — we only change the source of the `SourceItem` (prefetched dict vs per-call storage read). No existing test asserts `get_source_item` call counts (grep clean); only the harness measures engine_queries (expected to drop; baseline regenerated).
DEFERRED FOLLOW-UP — N+1 #2 (offline loader): `evals/historical_lookup_measurement.py:404` `_load_reuse_events` full-scans `WHERE event_type='lookup'` (index `idx_historical_lookup_event_container_session` leads with container_ref) and `:586` does one `source_items WHERE id=?` per exposed id. Fixing it well needs an index on the red persistence file `storage/sqlite_schema.py` (persistence-review checkpoint). Offline-only, low value per architect review. Stays OPEN on `roadmap/ideas/idea-retrieval-source-fetch-batching.md`; NOT in this PR.

**Material assumptions:**
- A1: `matches_filters`/`target_visibility_and_container` only reach source_items via the passed `get_source_item` callable (never `self.`). Confirmed by reading `core/filters.py` (both take the callable). If disproved: widen prefetch injection point.
- A2: FTS candidate set <= ~200 ids (retrieval_limit capped at 50, x4 window), safely under SQLite IN-param limits. If disproved: chunk the IN query.
- A3: `_regressed` only flags increases, so a lower count passes without baseline change — but the ticket requires regenerating the baseline so numbers reflect the win and the seeded-regression test stays meaningful. Evidence: `evals/vnext_perf_harness.py:662`.
- A4: prefetch is a request-local SNAPSHOT — a dict-HIT returns the item as of prefetch; a forget landing mid-query (after prefetch) is not seen on the batched path (acceptable for local single-user; documented in code at the prefetch site). dict-MISS falls back to `self.get_source_item`, preserving KeyError-on-race exactly.

**Plan:**
See `## Plan` prose below.

**Verification plan:**
See `## Verification` prose below.

**Plan review:**
Approved by architect (planning conversation). CI redline re-checks the final diff (`risk.declared_not_below_detected`).

**Approvals:**
Not required at Elevated.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Plan

**Batching mechanism (single mechanism, applied at two sites):** a new batched
storage accessor + request-local prefetch dict (snapshot semantics).

1. `storage/base.py` — add abstract `get_source_items(self, ids) -> dict[str, SourceItem]`.
2. `storage/sqlite.py` — implement it: one `select(SourceItemRecord).where(SourceItemRecord.id.in_(list(ids)))`; return `{r.id: self._to_source_item(r)}`; empty ids -> `{}`. Reuses `_to_source_item`, so objects are identical to `get_source_item`.
3. `storage/sqlite_search.py` — after fetching FTS `rows`, collect source_item `target_id`s, call `get_source_items(...)` once into `prefetched`. Define `_cached_get_source_item(sid)` = `prefetched.get(sid)` else fallback `self.get_source_item(sid)` (preserves KeyError-on-race exactly). Pass `_cached_get_source_item` (not `self.get_source_item`) into `matches_filters` and `target_visibility_and_container`. `get_memory_object`/`get_evidence_for_memory_object` unchanged -> memory path untouched. One-line comment documents the prefetch-snapshot semantics.
4. `retrieval/lexical.py` — collect source_item hit ids, `prefetched = self._storage.get_source_items(ids)` once; in the hydration loop read `prefetched.get(hit.target_id)`; if None -> existing `logger.debug(...skip deleted...); continue` (preserves deleted-skip). Memory_object hydration unchanged.

**Why semantics stay identical:** the forgotten gate, `filters is None` early return, field filters, and `is_visible` all live in core and are called in the same order with the same `SourceItem` values — we only change the *source* of the object from a per-call DB read to a prefetched dict (fallback preserves the race path). No content transform; redaction is downstream and untouched.

## Verification

Real interpreter prefix:
`PYTHONPATH="C:/Dev/rore/Pallium/.local/test-env/site-packages;." "C:/Users/I347041/AppData/Roaming/uv/python/cpython-3.13-windows-x86_64-none/python.exe"`

1. Behavior-invariance tests (prove zero behavior change):
   `-m pytest tests/test_historical_lookup_funnel_e2e.py tests/test_source_only_search.py tests/test_visibility_scope.py tests/test_soft_deleted_visibility.py tests/test_global_visibility.py tests/test_raw_turn_forgetting.py tests/test_storage_sqlite.py -q`
2. Regenerate baseline (shows the drop): `-m evals.vnext_perf_harness --baseline`
3. Count gate against new baseline: `-m pytest tests/test_vnext_perf_count_gate.py -q`
4. Full default lane: `-m pytest tests/ -x -q`

## Implementation

- Added abstract `get_source_items(ids) -> dict[str, SourceItem]` to `storage/base.py` and implemented it in `storage/sqlite.py` as a single `select(...).where(id.in_(...))` (dedupes ids, empty -> `{}`, reuses `_to_source_item` so objects are identical to `get_source_item`).
- `storage/sqlite_search.py`: prefetch all source_item candidate ids once before the loop; introduced `_get_source_item` (dict-hit else fallback to `self.get_source_item`, preserving KeyError-on-race) and passed it into both `matches_filters` and `target_visibility_and_container`. Memory-object getters unchanged. Prefetch-snapshot semantics documented in a code comment at the prefetch site.
- `retrieval/lexical.py`: batch-hydrate source_item hit ids once; hydrate from the map with a per-id fallback that preserves the deleted-between-read debug-skip. Memory-object hydration unchanged.
- No edits to `core/filters.py`, `core/query.py`, `core/visibility.py`, or `storage/sqlite_schema.py`. N+1 #2 remains deferred.

## Evidence

Real interpreter (`.local/test-env` + cpython-3.13).

Before/after per-path engine-query counts (regenerated `evals/vnext_perf_baseline.json`). "After" is the final value including the emission-time revalidation read added to close the mid-query forget TOCTOU (batching-only was 4; revalidation adds one O(1) batched read -> 5):

| Path | Before | After |
|---|---|---|
| `source_only_query` | 182 | **5** |
| `n1_double_get_source_item` limit=2 | 110 | **5** |
| `n1_double_get_source_item` limit=5 | 182 | **5** |
| `n1_double_get_source_item` limit=10 | 362 | **5** |
| `n1_double_get_source_item` limit=12 | 434 | **5** |
| `source_context_expansion` | 4 | 4 (unchanged) |
| loader (`visibility_loader_queries` etc.) | — | unchanged (N+1 #2 deferred) |

Per-candidate slope collapsed from ~9/slot (O(candidates)) to a flat constant 5 (O(1)).

Forget guarantee: `retrieval/lexical.py` re-reads the FINAL emitted source ids once at emission time and drops any that became forgotten/deleted mid-query. Covers both snapshot windows (candidate gate + hydration) at the single output boundary. New regression test `tests/test_retrieval_forget_revalidation.py::test_forget_landing_mid_query_is_not_emitted` deterministically commits a forget after the gate snapshot and asserts the item is not emitted.

Test results:
- New forget-race test (2 tests): `tests/test_retrieval_forget_revalidation.py` PASS.
- Invariance set (89 tests): `test_historical_lookup_funnel_e2e`, `test_source_only_search`, `test_visibility_scope`, `test_soft_deleted_visibility`, `test_global_visibility`, `test_raw_turn_forgetting`, `test_storage_sqlite` — all PASS.
- `test_vnext_perf_count_gate` (incl. seeded-regression self-test): PASS against regenerated baseline.
- Full default lane (round 1): 3517 passed, 15 skipped, 2 xfailed. Only failure is the pre-existing, unrelated `tests/test_config.py::test_prompt_variants_legacy_fallback_unaffected`.
