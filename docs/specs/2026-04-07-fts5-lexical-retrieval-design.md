# FTS5 Lexical Retrieval Migration — Design Spec

**Date:** 2026-04-07
**Status:** Draft
**Closes:** `roadmap/features/investigate-lexical-retrieval-scaling`

---

## Problem

The lexical search implementation in `storage/sqlite_search.py` loads ALL lexical index entries into memory on every query, tokenizes them in Python, and scores by IDF-weighted token overlap. This is O(N) per query with no database-level optimization. It works at hundreds of entries but will not scale to production workloads with thousands of entries across many containers.

## Goals

1. Replace the full-table-scan lexical search with FTS5 inverted-index lookup + BM25 scoring.
2. Push container-scoped filtering into SQL to narrow the candidate set before scoring.
3. Encapsulate all changes inside the storage layer — callers don't change.
4. Adopt BM25 as the native scoring model. Recalibrate downstream thresholds against real BM25 output rather than preserving a fake integer mapping.
5. No material regression in acceptance metrics, injection safety, or eval aggregates. A scoring engine swap may improve some individual cases and worsen others — the bar is aggregate behavior, not zero regression everywhere.

## Non-Goals

- Legacy database migration (greenfield only — `clean-data.sh` resets everything).
- Custom FTS5 tokenizer (C extension). Pre-normalization in Python is sufficient.
- Trigram tokenizer for fuzzy/substring matching.
- PostgreSQL FTS (separate future work).

---

## Architecture

### Approach: Standalone FTS5 Table

A new `lexical_fts` FTS5 virtual table lives alongside the existing `index_entries` table. Lexical index entries continue to be written to `index_entries` (vector code untouched), and a parallel row is inserted into `lexical_fts`. Search queries hit FTS5 via `MATCH` + `bm25()`. Deletion removes from both tables in the same transaction.

**Why standalone, not external-content:** External-content FTS5 tables (`content=index_entries`) require trigger-based sync and a special DELETE syntax. Silent drift between the FTS index and the base table is hard to diagnose. A standalone table with explicit application-level writes in the same transaction is simpler and more reliable.

**Why not replace `index_entries` for lexical:** `index_entries` stores both lexical and vector entries behind a uniform API. Splitting the table would fork every consumer that reads index entries. The duplication cost (normalized text stored in both places) is negligible.

### FTS5 Schema

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS lexical_fts USING fts5(
    text_view,
    index_entry_id UNINDEXED,
    target_kind UNINDEXED,
    target_id UNINDEXED,
    text_view_name UNINDEXED,
    container_ref UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);
```

- `text_view` — the only searchable column. Receives pre-normalized text from `normalize_for_index()` (lowercased, combining marks stripped, CJK space-separated).
- `UNINDEXED` columns — stored metadata, not full-text indexed. Used for container-scoped filtering and JOIN-back to resolve full objects. Eliminates JOINs from the search hot path.
- `unicode61` with `remove_diacritics 2` — belt-and-suspenders alongside Python's `strip_combining_marks()`. Handles any edge cases the Python normalization misses.
- `container_ref` — denormalized from source_items/memory_objects. Resolved at write time. Immutable after creation, so denormalization is safe.

### Tokenization Strategy

FTS5 receives pre-normalized text (output of `normalize_for_index()`). The `unicode61` tokenizer classifies Unicode characters into token and separator classes based on Unicode categories. For Pallium's normalized text (lowercased, combining-marks-stripped, CJK-space-separated), `unicode61` should produce token boundaries that mostly align with our existing Python tokenization via `TOKEN_PATTERN` in `core/text.py`. Exact equivalence is not guaranteed — `unicode61` is subtler than pure whitespace splitting — but the risk is low for pre-normalized input and `matched_tokens` is treated as approximate/trace-only (see Search Path).

This makes FTS5 a thin inverted-index + BM25 scorer over our existing normalization. Python owns text normalization; FTS5 owns indexing, matching, and scoring.

**Plural expansion:** `_token_variants()` in `retrieval/lexical.py` expands English plurals at query time (e.g., "reservations" → ["reservations", "reservation"]). This continues to run in Python before the MATCH expression is built. All variants are included as OR terms in the MATCH query.

---

## Write Path

### Index Creation

Inside `create_index_entry()` in `storage/sqlite.py`, when `index_type == "lexical"`:

1. Write to `index_entries` as before (unchanged).
2. Resolve `container_ref` for the target:
   - For `source_item`: read `source_items.container_ref` directly.
   - For `memory_object`: read `memory_objects.container_ref`, falling back to `envelope_json → scope.container_ref` if the direct column is NULL (matching the resolution logic in `core/filters.py:96-98`).
   - If container_ref is NULL (no container), store NULL in the FTS5 row.
3. INSERT into `lexical_fts` with the same `text_view` plus UNINDEXED metadata.

Both writes happen in the same SQLite transaction. Callers continue to call `storage.create_index_entry(entry)` unchanged.

### Index Deletion

Retention in `storage/sqlite_retention.py` currently deletes `IndexEntryRecord` objects directly via `session.delete()` at two sites:

- Source item cleanup (line ~614): iterates `source_index_records` and deletes each.
- Memory object orphan cleanup (line ~677): iterates `index_records` and deletes each.

Both paths must also delete the corresponding `lexical_fts` rows. Extract a helper:

```python
def _delete_index_entry_in_session(self, session, record: IndexEntryRecord) -> None:
    """Delete an index entry and its FTS5 shadow row (if lexical)."""
    if record.index_type == "lexical":
        session.execute(
            text("DELETE FROM lexical_fts WHERE index_entry_id = :id"),
            {"id": record.id},
        )
    session.delete(record)
```

**Invariant:** All lexical index entry deletion MUST go through this helper, full stop. No code path should call `session.delete()` on an `IndexEntryRecord` directly. This is the only safe way to keep `index_entries` and `lexical_fts` in sync.

---

## Search Path

The new `search_index_entries()` in `storage/sqlite_search.py`:

### 1. Build MATCH Expression

Receive tokens from `tokenize_query()` (already includes plural variants). Build a safe FTS5 MATCH expression:

```python
# Quote each token to prevent MATCH syntax injection.
# FTS5 MATCH has its own syntax (AND, OR, NOT, NEAR, *, "phrases").
# A bare token like "NOT" or "NEAR" would alter query semantics.
# TOKEN_PATTERN only matches word characters and CJK ideographs, so tokens
# cannot contain double quotes today. The escape is defensive insurance
# against future TOKEN_PATTERN changes.
quoted = [f'"{token.replace(chr(34), chr(34)+chr(34))}"' for token in tokens]
match_expr = " OR ".join(quoted)
```

**OR semantics** match the current behavior: a document matches if ANY query token is present. BM25 naturally ranks documents matching more rare terms higher.

**Empty token guard:** `LexicalRetrievalProvider.query()` returns early if `tokenize_query()` produces no tokens (line 85 in `retrieval/lexical.py`). An empty MATCH expression never reaches `search_index_entries()`.

### 2. Execute FTS5 Query

```sql
SELECT index_entry_id, target_kind, target_id, text_view_name,
       text_view, bm25(lexical_fts) AS score
FROM lexical_fts
WHERE lexical_fts MATCH :match_expr
  AND (:container_ref IS NULL OR container_ref = :container_ref)
ORDER BY score   -- bm25() returns negative; lower = better match; negated at storage boundary
LIMIT :limit
```

The main performance win comes from FTS5's inverted index (O(matching docs) instead of O(all docs)). The `container_ref` predicate is an additional post-MATCH narrowing filter — since it is `UNINDEXED`, it does not participate in MATCH lookup itself, but it reduces the candidate rows returned to Python for further filtering.

The LIMIT should be `limit` as passed by the caller (typically `limit * 4` from `LexicalRetrievalProvider.query()`), which already accounts for downstream filtering and deduplication losses.

### 3. Post-FTS5 Score Floor

After FTS5 returns candidates, apply a minimum BM25 score cutoff to prevent weak single-token noise from consuming result slots. Scores are negated at the storage boundary (higher = better), so the floor is a minimum positive value:

```python
# After negation: higher = better match. Filter out weak candidates.
candidates = [(row, score) for row, score in raw_results if score >= LEXICAL_BM25_FLOOR]
```

The `LEXICAL_BM25_FLOOR` threshold is determined empirically during eval calibration. BM25 magnitudes depend on corpus and query composition, so no default value is specified here — calibrate from observed score distributions in eval runs.

### 4. Apply matches_filters()

For each candidate, call `matches_filters()` for lifecycle and field filtering. This requires looking up the target object (source_item or memory_object), same as today. Now runs on the small post-FTS5 result set instead of the full corpus.

### 5. Reconstruct matched_tokens (Approximate, Trace-Only)

For each surviving candidate:

```python
text_tokens = set(tokenize_text(row.text_view))
matched_tokens = tuple(sorted(unique_tokens & text_tokens))
```

**Important:** `matched_tokens` is approximate and intended for trace/debug output only. No routing decision should depend on it. The reconstruction uses Python's `tokenize_text()` which may not produce identical token boundaries to FTS5's `unicode61` in all edge cases. In practice the boundaries align for pre-normalized text, but the contract is best-effort.

Current consumers of `matched_tokens`:
- `api/routes.py` — debug API response
- `core/models.py:RetrievalTraceHit` — trace output
- `retrieval/common.py` — trace hit building
- No routing decisions depend on `matched_tokens` directly.

### 6. Apply Visibility Filtering

Same Python checks as today (`is_visible()`, `target_visibility_and_container()`), on the small post-filter result set.

### 7. Build IndexSearchResult

Same `IndexSearchHit` and `IndexSearchResult` dataclasses. The `score` field changes from IDF integer to BM25 float (see Scoring section).

---

## Scoring

### BM25 Replaces IDF

**Before:** IDF-only scoring — binary term presence, no term frequency, no document length normalization. Scores are small positive integers (1-10 range).

**After:** BM25 scoring via FTS5's `bm25()` function. Term frequency with saturation (k1=1.2), document length normalization (b=0.75). FTS5 hardcodes these parameters. Scores are negative floats where more negative = better match.

BM25 is a better default ranking model for general-purpose text search. For Pallium's short text views (memory summaries, source excerpts), the practical difference from the current IDF-only approach is: (a) documents mentioning a term multiple times score slightly higher, and (b) shorter documents matching a term rank above longer ones. Both are directionally correct.

FTS5's `bm25()` function supports per-column weight arguments, but since `lexical_fts` has only one searchable column (`text_view`), default weighting is the only option and is intentional.

**Note:** "Better ranking model" does not automatically mean "better retrieval behavior." Weak lexical hits can be dangerous in Pallium (they can trigger injection). The post-FTS5 score floor and downstream routing gates protect against this, but eval validation is required.

### Score Contract Change

The `IndexSearchHit.score` field changes from `int` to `float`. FTS5's `bm25()` returns negative floats (lower = better). We **negate at the storage boundary** so the rest of the codebase keeps the existing "higher = better" convention. No further scaling or fake integer mapping — the magnitude is BM25-native (positive floats, typically 0-15 range for good matches depending on corpus).

This means `score = -bm25_score`. All existing sort keys, comparisons, and threshold checks keep their direction. Only the magnitude changes.

**Downstream recalibration required:**

| Consumer | Current | Change |
|---|---|---|
| `LEXICAL_NORM_SCALE = 6` | Divides IDF integer by 6 for 0-1 normalization | Replace with BM25-appropriate normalization. Empirically determine the scale from eval corpus BM25 score distribution. |
| `_compute_quality_score()` | `min(lexical_score / 6, 1.0)` | Adapt to BM25 float range. |
| Injection gate thresholds | `best_lexical >= set_lexical_threshold` (calibrated to IDF integers) | Recalibrate thresholds against real BM25 output from eval runs. |
| `lexical_score >= moderate_retrieval_score` in justification | Calibrated to IDF integers | Same recalibration. |
| `test_retrieval_relevance_floor.py` | `assert item.lexical_score >= 1` | Update to BM25 float assertions. |

**Calibration approach:** Run existing evals with FTS5 + BM25. Observe the BM25 score distribution. Set `LEXICAL_NORM_SCALE` to the empirical "good match" BM25 magnitude. Adjust injection/routing thresholds to produce equivalent gate behavior. This is an eval-driven process, not a formula.

---

## FTS5 Availability Check

At startup during schema initialization, verify FTS5 is available:

```python
try:
    connection.execute(text(
        "CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_check USING fts5(x)"
    ))
    connection.execute(text("DROP TABLE IF EXISTS _fts5_check"))
except Exception:
    raise RuntimeError(
        "SQLite FTS5 extension is not available. "
        "Pallium requires FTS5 for lexical search. "
        "Python 3.9+ bundles SQLite with FTS5 enabled by default."
    )
```

Low risk (Python's bundled SQLite has FTS5 since 3.9+), but a clear error message is cheap insurance.

---

## Files Changed

### Storage layer (core change)

| File | Change |
|---|---|
| `storage/sqlite_schema.py` | Add FTS5 virtual table creation in `_initialize_schema()`. Add FTS5 availability check. |
| `storage/sqlite.py` | Modify `create_index_entry()` to also INSERT into `lexical_fts` for lexical entries. Resolve `container_ref` at write time. |
| `storage/sqlite_search.py` | Replace full-table-scan with FTS5 MATCH + bm25() query. Add MATCH expression building with token quoting. Add post-FTS5 score floor. Reconstruct matched_tokens as approximate/trace-only. |
| `storage/sqlite_retention.py` | Extract `_delete_index_entry_in_session()` helper. Both retention sites (source item cleanup, memory object orphan cleanup) call this helper to ensure FTS5 row cleanup. |
| `storage/base.py` | Change `IndexSearchHit.score` from `int` to `float`. |

### Score type ripple (int → float)

The `lexical_score` field changes from `int` to `float` throughout. The RRF fused `score` on `QueryResultItem` stays `int` (it's rank-based, derived from RRF, not from raw lexical/vector scores). The `vector_score` stays `int` (vector retrieval is unchanged).

| File | Change |
|---|---|
| `core/models.py` | `QueryResultItem.lexical_score: int \| None` → `float \| None`. `RetrievalTraceHit.score` stays `int` (trace uses fused score). |
| `retrieval/composite.py` | `lexical_raw_score` pass-through carries BM25 float. `fused_score = int(rrf_score * RRF_SCORE_SCALE)` stays `int` — RRF uses rank, not raw score. |
| `api/schemas.py` | Update `lexical_score` type in API debug response schemas. |

### Routing recalibration (threshold + type changes)

All `int(lexical_score)` casts must be removed or replaced with float-aware comparisons. Thresholds recalibrated against BM25 score distribution.

| File | Change |
|---|---|
| `semantic/agent_conversation_memory_routing_constants.py` | Add `normalize_lexical_score()` utility. Recalibrate `LEXICAL_NORM_SCALE` for BM25 score range. All lexical thresholds expressed in normalized 0-1 space via this utility. |
| `semantic/agent_conversation_memory_routing_scoring.py` | Call `normalize_lexical_score()` in `_compute_quality_score()`. Remove `int()` cast on `item.lexical_score` (line 554). |
| `semantic/agent_conversation_memory_routing_injection.py` | Call `normalize_lexical_score()` for best_lexical (line 84). Thresholds in normalized 0-1 space. |
| `semantic/agent_conversation_memory_routing_justification.py` | Remove `int()` cast on `lexical_score` (line 142). |
| `semantic/agent_conversation_memory_routing_selection.py` | Call `normalize_lexical_score()` (line 286). |
| `semantic/agent_conversation_memory_routing_floor.py` | Call `normalize_lexical_score()` on `raw_lex` (line 46). Update `filtered_score_ranges` type annotation. Thresholds in normalized 0-1 space. |

### Tests

| File | Change |
|---|---|
| `tests/test_lexical_tokenize.py` | Update score assertions for BM25 floats. Verify tokenization and plural expansion still work. |
| `tests/test_storage_sqlite.py` | Update score assertions. Add FTS5-specific tests. |
| `tests/test_retrieval_relevance_floor.py` | Update score assertions to BM25 float range. |
| `tests/test_routing_justification.py` | Update lexical_score fixtures and assertions. |

---

## What Gets Removed

- `_IDF_SCORE_SCALE` constant in `sqlite_search.py`.
- The entire Python IDF computation loop in `search_index_entries()` (doc_freq building, IDF formula, effective_corpus logic).
- The full-table-scan query (`SELECT * FROM index_entries WHERE index_type = 'lexical'`).
- Per-record Python tokenization in the search hot path (replaced by FTS5 inverted-index lookup).

---

## Migration

Greenfield only. No legacy DB migration. Any existing database is rebuilt via `clean-data.sh` (deletes DB + vector index). On restart, schema initialization creates the FTS5 table. The background processor re-ingests source items, and both `index_entries` and `lexical_fts` get populated as part of normal processing.

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| BM25 score recalibration breaks routing/injection gates | High | Run full eval suite after FTS5 integration. Calibrate thresholds empirically before merging. |
| MATCH expression injection (user query contains FTS5 syntax) | High | Quote every token with double quotes in MATCH expression. |
| Delete path misses FTS5 cleanup | Medium | Encapsulated `_delete_index_entry_in_session()` helper used by all retention code paths. |
| `container_ref` resolution for memory_objects complex (direct column vs envelope fallback) | Medium | Match existing resolution logic from `core/filters.py:96-98`. Test both paths. |
| Tokenization drift between Python normalize and FTS5 unicode61 | Low | `matched_tokens` marked as approximate/trace-only. No routing decision depends on it. Pre-normalized text minimizes drift surface. |
| FTS5 not available in some Python builds | Low | Startup check with clear error message. Python 3.9+ bundles FTS5. |
| BM25 noise from OR matching (weak single-token hits fill LIMIT) | Low | Post-FTS5 score floor filters weak candidates. Downstream routing gates provide further protection. |

---

## Eval Plan

1. Run full existing test suite (`python -m pytest tests/ -x -q`) — verify no regressions.
2. Run agent simulation (`python -m app.agent_simulation`) — verify end-to-end retrieval.
3. Run exploratory QA invariant runner — verify injection/routing behavior.
4. Run fact consolidation eval — verify retrieval quality.
5. Observe BM25 score distribution from evals. Use distribution to calibrate:
   - `LEXICAL_NORM_SCALE` replacement value
   - Injection gate thresholds
   - Routing justification thresholds
   - Post-FTS5 score floor (`LEXICAL_BM25_FLOOR`)
6. Re-run all evals after calibration to verify equivalent behavior.
