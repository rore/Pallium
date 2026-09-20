<!-- agent-workflow:start -->
**Outcome:** Exact-work source-only vector searches score only the scoped vector subset while preserving exact ranking, filters, visibility, lifecycle, trace, and final hydration semantics.

**Target:** Pallium retrieval and SQLite storage.

**Scope:** `retrieval/vector.py`, `storage/base.py`, `storage/sqlite.py`, `storage/vector_index.py`, and focused tests under `tests/` only.

**Constraints:** No schema, dependency, runtime, API, or unrelated retrieval changes. Fast path only when both scoped candidate and index-subset capabilities exist; preserve captured-index behavior, blank exact-work bypass, default/no-work behavior, fallback semantics, OR work-ref matching, multiple rows per source, and deterministic ranking.

**Completion criteria:** Exact-work source-only vector retrieval uses one unbounded narrow scoped candidate query and optional subset ANN scoring; higher-ranked wrong-work vectors do not invoke global search; missing subset keys and zero-norm vectors are safe; fallback and all existing semantic/lifecycle contracts remain intact.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Retrieval and storage are gray/watch shared behavior surfaces; the scoped candidate contract and ANN subset scoring affect ranking and persistence-backed filtering. Moderate complexity because the change spans retrieval, storage, vector-index capability, and an end-to-end regression.

**Discovery:** Existing exact-work routing normalizes one readable work reference and source metadata uses the shared JSON predicate. Existing vector search captures one index reference and performs global ANN expansion. The current VectorIndex wrapper exposes search but not subset scoring; the new path must use optional capabilities and preserve fallback.

**Material assumptions:** The SQLite predicate can return real vector IndexEntry plus narrow SourceItemVectorProjection rows without schema changes; if the predicate cannot express OR semantics or multiple rows/source, stop and widen the plan. The vector backend can expose keyed subset scoring without changing dependencies; otherwise retain fallback and report.

**Plan:** Inspect exact normalized work-ref SQL helpers, StorageProvider/SQLite contracts, VectorIndex keyed access, and exact-work/vector tests. Add the smallest optional candidate-query and subset-scoring contracts. Route only exact-work source-only vector queries through the fast path, preserving existing callbacks and final revalidation. Add focused unit, SQLite, and real-index caller E2E coverage. Run the reviewer-requested focused suite and local workflow/redline checks.

**Verification plan:** Scoped retrieval semantics -> real SQLite/USEARCH HTTP E2E asserts no global search, normalized OR refs, multiple entries/source, and stable results. Ranking parity -> real USEARCH subset-vs-global score comparison plus missing, duplicate, zero, negative, and tie cases. Fail-closed behavior -> fast-path race tests mutate work refs, lifecycle, and visibility before final hydration and inspect trace output. Regression safety -> focused retrieval suite, workflow/redline checks, and full repository suite. Production performance -> isolated snapshot benchmark uses the installed profile and verifies latency plus the exact five result IDs.

**Plan review:** clean-context architecture/redline review required by elevated gray retrieval/storage scope; parent review before commit.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Added an optional exact-work source-only path in retrieval/vector.py: it queries the complete normalized JSON work-ref source/vector scope, scores only keyed vectors through VectorIndex.score_subset, preserves deterministic cosine ordering and existing filters/visibility/final hydration, and falls back on absent capabilities or NotImplementedError. Added the narrow SQLite candidate method and base capability hook, plus keyed cosine/zero-norm handling and real SQLite/vector HTTP and unit regressions. No commit created; state is Ready for review pending parent review.

## Evidence

- Batched keyed scorer: tests/test_vector_index.py - 18 passed.
- Focused suite: 113 passed in 11.94s, including real USEARCH parity and fast-path race/trace coverage.
- Direct candidate-query assertions cover normalized OR refs and multiple vector entries for one source.
- Native Index.get batch return shape is normalized without discarding per-key vectors.
- Isolated production snapshot: exact failing query completed in 0.5168s and returned the same five result IDs; repeated calls without request exclusion completed in 0.4565-0.5471s.
- Smart re-review: approved with no blocking correctness or performance findings; independent native score comparison matched exactly or within 2.98e-8.
- Agent Workflow check: clean; redline verdict GRAY with no boundary violations or required checkpoints.
- Full repository suite: 5038 passed, 34 skipped, 2 xfailed in 191.42s.

## Result review

Pending.
