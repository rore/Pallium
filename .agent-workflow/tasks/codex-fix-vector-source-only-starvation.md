<!-- agent-workflow:start -->
**Outcome:** Source-only vector retrieval returns up to K eligible raw source items even when more than 8×K higher-scoring derived memories precede them in the shared vector index.

**Target:** Pallium.

**Scope:** `retrieval/vector.py`, focused retrieval tests, this Work Record, and the existing roadmap item/board status when delivery state changes.

**Constraints:** Preserve ordering, visibility/container/lifecycle filtering, public retrieval contracts, lexical/hybrid behavior, and existing dependency boundaries. Do not change storage schemas, APIs, embedding generation, or authorization semantics.

**Completion criteria:** Against a stable index, vector source-only retrieval returns min(K, eligible raw sources) in similarity order without derived leakage for 0, <K, =K, and >K sources; remains correct with >8×K higher-ranked derived entries, visibility filtering, forgotten sources, shared-index container isolation, Unicode/semantic queries, and vector-only/full caller lifecycle coverage. Concurrent index mutation remains bounded, duplicate-free, and within the existing weak-consistency contract. Focused/full tests and workflow/redline checks pass; roadmap status matches delivered evidence.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Redline verdict is GRAY: `retrieval/vector.py` is a watched retrieval surface while tests/docs are blue, with no boundary violation or specialized checkpoint. Elevated reflects shared retrieval top-K correctness despite a deliberately small diff.

**Discovery:** `retrieval/vector.py` fetches only `limit*8` for target-kind queries, then applies kind, similarity, filter, visibility, forgotten/lifecycle, stale-entry, and dedup rejection; therefore even K source-kind candidates are insufficient to guarantee K eligible results. `VectorIndex.search` is exact, prefix-ordered, capped by finite index size, and supports repeated increasing K. Source-only enters through HTTP → `core/query.py` → composite → vector with `target_kind="source_item"`; default target-kind-none queries must remain one fixed `limit*4` search. Existing HTTP source-only tests disable vector retrieval, so they do not catch this defect. Redline found only the gray `retrieval/**` watch and no boundary expansion.

**Material assumptions:** `entry_count()` at query start can define a finite candidate horizon: stable indexes return exact ordered prefixes; concurrent additions after that horizon need not enter the query, and removals may shorten it, matching the index's documented weak-consistency contract. Disprove with an index-contract or mutation test failure, then return to planning for a filtered-index design. Unique first-exposure processing preserves stable-index ordering and trace counts; disprove with trace/dedup/stale tests, then revise batching. A deterministic fake embedding provider plus enabled vector configuration can exercise the HTTP path without a live model; disprove during fixture construction, then use the existing real-vector fixture and record its skip limitation.

**Plan:** Add a small private expanding-search batch iterator in `retrieval/vector.py`. Default queries keep one `limit*4` search. Target-kind queries capture `entry_count()` once as a finite horizon, start at `limit*8`, double up to that horizon, yield each entry ID only on first exposure, and stop on short search, horizon, or no progress. Feed batches through the existing filtering/hydration pipeline without moving rules; stop after K eligible results or when a matching target-kind candidate is below the similarity floor. Stable indexes preserve similarity order; concurrent mutation is explicitly start-horizon weak consistency, bounded and duplicate-free, not a global snapshot. Trace counts/candidates represent unique first-exposed matching IDs only; selected hits are recorded after hydration and the unsearched tail is absent. Add provider tests for K boundaries, >8K starvation, rejection/stale/dedup/exhaustion, trace/order, no-progress mutation, and unchanged default search. Add vector-enabled TestClient coverage with a deterministic embedding/index fixture for Unicode, >8K derived clutter, raw-rank/no-injection shape, visibility isolation, lifecycle, and `/health` embedding readiness. No new dependency/API/storage contract. After verification, mark the roadmap item done and move it from P1 to Done. Stop if correctness needs schema changes or forbidden dependencies.

**Verification plan:** Stable-index 0/<K/=K/>K source counts behind >8K derived entries → parameterized provider tests assert min(K, eligible), order, no leakage, K growth, and bounded calls. Invisible, cross-container, forgotten, role-filtered, below-threshold, stale, and duplicate early candidates → focused tests assert continuation/exhaustion and unique trace semantics. A mutating/no-progress fake index → termination and duplicate-free assertions within the start horizon. No target kind → exactly one `limit*4` search. Vector-enabled Unicode HTTP source-only lifecycle with derived clutter → TestClient asserts source-only decision, contiguous raw ranks, no injection, isolation, and `/health` embedding readiness. Run focused vector/source-only tests, relevant multilingual real-vector test when available, full suite, workflow checker, redline report, and PR CI/review-thread checks.

**Plan review:** Approved by clean-context reviewer; see `## Plan review`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-08-24: Established task context and recorded pre-edit GRAY redline verdict. Discovery is in progress; no production code edited.
- 2026-08-24: Discovery traced HTTP → source-only composite/vector flow, confirmed stable finite exact-search prefixes, and found the existing HTTP suite is lexical-only. Plan recorded; guarded edits remain blocked pending clean-context review.
- 2026-08-24: `apply_patch` hit machine-local Windows error 1385; used this deterministic replacement limited to the Work Record, as required by local instructions.

- 2026-08-24: Initial clean-context plan review blocked on concurrent-mutation termination and trace semantics; plan revised with a start-horizon/no-progress contract and returned for repeat review.

- 2026-08-24: Repeat clean-context review approved the revised plan; State advanced to Ready to implement before guarded edits.

## Evidence

- Pending.

## Result review

- Pending.

## Plan review

- Initial clean-context verdict: blocked pending concurrency/termination and trace-semantics clarification. Reviewer required a finite/no-progress guard, qualified ordering under concurrent mutation, matching-kind similarity-floor semantics, unique cross-batch trace rules, and proof that HTTP E2E actually enables vector retrieval.
- Plan response: capture a start-of-query entry-count horizon, stop on short/horizon/no-progress, process IDs once, preserve stable-index ordering while explicitly retaining the documented weak-concurrency contract, stop below threshold only on matching-kind candidates, define unique first-exposure trace semantics, and assert vector readiness in the E2E fixture.
- Repeat clean-context verdict: APPROVED. The start-horizon and termination semantics resolve the blockers. Non-blocking conditions: do not call `search(k=0)` for an empty index, and assert horizon/no-progress call bounds.