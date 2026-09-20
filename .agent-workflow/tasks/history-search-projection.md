<!-- agent-workflow:start -->
**Outcome:** Exact semantic history searches avoid materializing full source content for rejected ANN candidates while preserving ranking and lifecycle/visibility semantics.

**Target:** Pallium retrieval.

**Scope:** `retrieval/vector.py`, the narrow storage projection contract/SQLite implementation it requires, and focused vector retrieval tests only.

**Constraints:** No schema, dependency, query-specific hardcoding, runtime changes, or edits outside the isolated checkout. The storage change is limited to one joined read-shape contract; preserve ANN order, exact work-ref filtering, visibility/actor/container filters, forgotten/deleted guarantees, and final emitted-source hydration.

**Completion criteria:** Source-item ANN expansion reads only the projection required for filters, visibility, work-ref extraction, and lifecycle checks; final emitted IDs are fully hydrated/revalidated; focused tests cover projection shape, filtering/visibility/order, missing/forgotten races, and final revalidation.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Retrieval is a gray/watch shared behavior surface; projection changes affect filtering and visibility correctness. Moderate because the change spans storage read shape, retrieval lifecycle semantics, and focused regression coverage.

**Discovery:** The installed vector path expands through 5,120 index rows and performs 3,155 per-candidate source reads; full source content is materialized before work-ref and visibility rejection. ANN search is negligible relative to candidate hydration. Existing source batch helper returns full `SourceItem` rows and cannot serve a projection.

**Material assumptions:** The required source projection can be represented by existing source fields and metadata parsing without changing storage schema; if a caller needs content before final emission, stop and widen the plan. Final emitted IDs remain small and can use existing full-row hydration/revalidation.

**Plan:** Inspect all vector filter/visibility/work-ref callers and source model fields. Reuse the smallest existing storage/query pattern or add the narrowest internal projection path permitted by scope. Keep full hydration only after result selection and in final revalidation. Add focused tests for query shape and lifecycle races. Stop on any public storage API/schema expansion.

**Verification plan:** Candidate filtering, visibility, lifecycle, trace parity, and deferred hydration -> focused vector/source-only/forget tests. Production result and latency parity -> disposable coherent snapshot full service query.

**Plan review:** clean-context agent-redline classification: gray/watch retrieval surface, no boundary violation; Elevated/Moderate classification.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Added a bounded SQLite joined projection keyed by ANN index-entry IDs using a small immutable filter/visibility DTO; it excludes content, text_view, and processing fields, preserves ANN order and below-floor stopping, and defers full source hydration to one final emitted-ID batch revalidation that reapplies filters and visibility. Added focused regressions for deferred hydration, stale/missing rows, distinct source IDs, chunking, and lifecycle races.

## Evidence

- Focused retrieval suite: 91 passed.
- Full suite: 5,031 passed, 34 skipped, 2 xfailed.
- Production-shaped full `service.query` replay: 1.157 seconds with the same five result IDs; temporary snapshot removed.
- Independent high-reasoning review: approved after compatibility fallback and below-threshold trace parity fixes.

## Result review

The narrow projection removes wide-row materialization from ANN expansion without changing ranking, visibility, lifecycle, or trace contracts. Final full rows are hydrated and revalidated only for emitted results.
