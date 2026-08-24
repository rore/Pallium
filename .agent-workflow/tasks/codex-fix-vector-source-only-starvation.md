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

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-08-24: Established task context and recorded pre-edit GRAY redline verdict. Discovery is in progress; no production code edited.
- 2026-08-24: Discovery traced HTTP → source-only composite/vector flow, confirmed stable finite exact-search prefixes, and found the existing HTTP suite is lexical-only. Plan recorded; guarded edits remain blocked pending clean-context review.
- 2026-08-24: `apply_patch` hit machine-local Windows error 1385; used this deterministic replacement limited to the Work Record, as required by local instructions.

- 2026-08-24: Initial clean-context plan review blocked on concurrent-mutation termination and trace semantics; plan revised with a start-horizon/no-progress contract and returned for repeat review.

- 2026-08-24: Repeat clean-context review approved the revised plan; State advanced to Ready to implement before guarded edits.
- 2026-08-24: Implemented bounded adaptive vector-prefix expansion at `f79d609c8d73af01d772ebd91154b22a8659c75e`, preserving the fixed default-query search and existing filter/hydration rules. Added focused boundary, starvation, rejection, trace/dedup, mutation-bound, and vector-enabled Unicode HTTP lifecycle coverage.
- 2026-08-24: The delegated first implementation over-expanded and queried storage per candidate; parent review rejected it before commit and retained batched storage resolution within the reviewed start-horizon plan.
- 2026-08-24: Early Windows test runners used `WScript.Shell.Exec`, left two orphaned pytest trees, and surfaced console windows. Exact task processes were stopped; subsequent verification used hidden `WScript.Shell.Run(..., 0, True)`. Trigger 7 did not pass the skill-feedback actionability filter because this is a machine-local launcher constraint, not a repeatable workflow-skill rule.
- 2026-08-24: Final reviewer found missing below-floor and actual add/remove mutation regressions, an incorrect full-suite pass count, and non-managed HTTP client cleanup. Added both regressions, registered `client.close` as a test finalizer without enabling the hanging app lifespan, corrected evidence arithmetic, and reran the focused suites at `26571408e12d5a04216dc1e87af5a27db331f888`.
- 2026-08-24: PR review requested a non-shadowing HTTP payload name and a full repeated-batch no-progress regression; both were fixed and 55 focused tests passed at `bdab4b0aa973dcfd5372d7c8a5ab407f7ba85c56`. The suggestion to move State beyond `Ready for review` was not applied because the installed workflow defines only `Ready to implement`, `Blocked`, and `Ready for review`; this is its terminal reviewed-work state.
- 2026-08-24: Follow-up PR review clarified the intentionally over-returning defensive fixture and requested explicit stale-removal plus eligible-source cross-batch dedup assertions. Documented the fixture contract and added both assertions; 55 focused tests passed at `b423e8ded6a64ab76eacec138bdb0337ed82bc9c`.

## Evidence

- Revision `b423e8ded6a64ab76eacec138bdb0337ed82bc9c`: `tests/test_vector_retrieval.py` + `tests/test_source_only_search.py` → 55 passed, 0 failed, 0 skipped.
- Vector-enabled HTTP regression alone → 1 passed; exercises >8×K derived clutter, Unicode semantic query, cross-container isolation, source-only response shape, and ingest → retrieve → forget → absent lifecycle.
- Normal full suite → 3,832 tests collected: 3,806 passed, 25 skipped, 1 unrelated local-configuration failure in `tests.test_config::test_prompt_variants_legacy_fallback_unaffected` because the local QAR prompt override is enabled. No configuration file is changed by this branch; clean PR CI remains required before merge.

## Result review

- Initial final review: P1 missing below-threshold adaptive-stop regression; P2 no actual inter-search add/remove mutation test; P2 evidence arithmetic mismatch; P3 HTTP client not explicitly closed.
- Response: all four addressed in `26571408e12d5a04216dc1e87af5a27db331f888`. Repeat final review: APPROVED; no new correctness issues. Residual risk is limited to the documented weak-consistency contract under concurrent index mutation.
- PR review: two valid test-maintainability findings addressed in `bdab4b0aa973dcfd5372d7c8a5ab407f7ba85c56`; terminal-state suggestion answered without code change because `Ready for review` is the highest valid workflow state.
- PR follow-up: over-return fixture intent documented; stale cleanup and cross-batch eligible dedup assertions added in `b423e8ded6a64ab76eacec138bdb0337ed82bc9c`; all inline threads answered and resolved.

## Skill feedback (unsent)

**Trigger fired:** 5 — skill cross-reference was broken.

**What the skill said (or failed to say):** `docs/agent-workflow/review-result.md` links to `../skill-feedback.md`, but that file is absent from `docs/`; the usable source is `.claude/skills/agent-workflow/templates/skill-feedback.md`.

**What happened:** The required feedback checkpoint could not be loaded from the documented repository path.

**Suggested fix:** Generate `docs/agent-workflow/skill-feedback.md` during bootstrap or change the review-result cross-reference to an installed path that exists.

**Work Record:** `f79d609c8d73af01d772ebd91154b22a8659c75e` + `.agent-workflow/tasks/codex-fix-vector-source-only-starvation.md`; source commit not recorded because the skill is vendored in this consumer repository.

## Plan review
- Initial clean-context verdict: blocked pending concurrency/termination and trace-semantics clarification. Reviewer required a finite/no-progress guard, qualified ordering under concurrent mutation, matching-kind similarity-floor semantics, unique cross-batch trace rules, and proof that HTTP E2E actually enables vector retrieval.
- Plan response: capture a start-of-query entry-count horizon, stop on short/horizon/no-progress, process IDs once, preserve stable-index ordering while explicitly retaining the documented weak-concurrency contract, stop below threshold only on matching-kind candidates, define unique first-exposure trace semantics, and assert vector readiness in the E2E fixture.
- Repeat clean-context verdict: APPROVED. The start-horizon and termination semantics resolve the blockers. Non-blocking conditions: do not call `search(k=0)` for an empty index, and assert horizon/no-progress call bounds.
