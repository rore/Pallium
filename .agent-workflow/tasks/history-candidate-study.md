<!-- agent-workflow:start -->
**Outcome:**
A sufficiently broad, reproducible offline study determines whether one small Session History candidate-selection change improves what calling agents receive, or reports that the observed corpus cannot support that conclusion.

**Target:**
Session History candidate recovery and presentation on the persisted historical-reuse corpus observed from 2026-08-16 through 2026-09-11.

**Scope:**
Create this Work Record plus private ignored artifacts under `.local/history-candidate-study/`. Read production code and copied telemetry/vector data; do not change production code unless a later, separately reviewed task is justified by measured evidence.

**Constraints:**
Never query the live service or mutate production telemetry, accessibility, ranking, database, or vector state. Use an isolated writable copy, current production retrieval/formatting, existing dependencies, and no paid evaluator/model calls. Freeze cases, labels, config, code identity, source state, and query-embedding identity before confirmation. Treat all previously inspected or rubric-shaping cases as development. State every metric as a candidate-recovery-family diagnostic; do not claim injection precision, downstream-task effect, absolute recall, or all-traffic generality.

**Completion criteria:**
1. Census all 370 finalized lookups and derive the valid directly linked request cohort from all 115 distinct non-null request IDs, retaining empty and invalid episodes in accounting.
2. Inventory every previously inspected episode, validate that at least 60 untouched episodes spanning at least 30 sessions and 5 containers remain, and calculate attainable paired resolution before confirmation; stop and recommend prospective collection if the gate fails.
3. Run deterministic development comparisons for B1 increased candidate depth, B2 task-notification demotion, and B3 cross-session equivalent-content demotion under the exact arm definitions and advancement rule below; advance at most one mechanism.
4. Freeze source labels, then independently score each arm's exact rendered preview with no credit for omitted or expansion-only facts; preserve source provenance, dates, and expansion neighborhoods.
5. If one mechanism advances, run the untouched confirmation once with durable resume records, identical restored/verified replay state per arm, no repeated completed calls, and reconciled counts/cost/bytes/latency.
6. Report a supported improvement, no material benefit, regression, or unresolved result using predeclared thresholds and honest scope limits; publish only text-free aggregates. Open no implementation PR from this research alone.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
The tracked Work Record is blue, but ignored `.local/**` study artifacts are gray under the repository policy, making the overall task Elevated. The study has multiple controlled stages but no production mutation or interface change.

**Discovery:**
The corpus contains 370 finalized lookups, 100 sessions, 15 containers, 115 distinct linked requests, and 93 linked requests with finalized expansion. The last 14 days contain 223 lookups and 84 distinct linked requests. Attempt depth cannot be joined to request episodes from persisted schema. Persisted lookup rows also do not prove the original MCP tool, source_type, role, artifact_kind, work_refs, or all actor/mode options, so replay eligibility requires an exact matching runtime tool-call record. Existing diagnostics cover only small purposive samples and are development evidence. evals/real_corpus_pull_eval.py supplies reconstruction ideas but caps samples at 20 and is not a frozen replay runner. evals/reliable_pair_runner.py supplies durable hash/resume patterns. core/query.py::QueryExecutor.query, core/query.py::_collapse_source_duplicates, retrieval/common.py::build_source_content_fingerprint, api/routes.py::_serialize_result, and app/mcp/server.py::_compact_history are the production selection/serialization/rendering seam. Live /query/debug writes lookup telemetry and is prohibited for this study. Vector retrieval may mutate stale index entries, so state must be prepared before freezing and restored or verified per arm.

**Material assumptions:**
- At least 60 untouched valid linked episodes remain after unioning all previously inspected and calibration cases. Disproof: inventory falls below 60 episodes, 30 sessions, or 5 containers. Action: stop before confirmation and specify prospective collection needs.
- Current replay answers the scoped question "would the same recorded information need be better served now." Disproof: required historical scope/options cannot be reconstructed or current source availability materially changes the episode. Action: mark the episode ineligible or descriptive; do not silently substitute as-of claims.
- Configured production retrieval can run against an isolated reproducible copy. Disproof: provider, embedding preprocessing/dimensions, cost, or mutable index identity cannot be fixed and recorded. Action: stop before candidate comparison.
- Source-level relevance can be judged without revealing arm identity. Disproof: useful facts depend only on arm-specific truncation/context. Action: keep source relevance uncertain and let the separately blinded rendered-preview judgment decide delivered usefulness.

**Plan:**
1. Close the contamination universe before extracting cases. Hash and enumerate every regular file under .local/history-search-diagnostic/**, .local/history-benefit-pilot/**, and .local/history-response-packaging/**; additionally hash .local/corpus-retrieval-study/{sample,opportunity,reconstructable,retrieval,reuse}.json, its REPORT.md, and docs/reports/session-history-search-quality-study.md. Extract every lookup/request/source ID named by those files and quarantine its linked request episode. Conservatively quarantine every lookup at or after 2026-09-08T00:00:00Z, which covers the recent structural audit, direct-agent interviews, and this thread. Persist paths, presence/absence, SHA-256 values, the cutoff, extracted IDs, and mapped request IDs in prior-inspection-sources.json; any later source/hash change invalidates the split.
2. Build and freeze an episode manifest. Group all finalized lookups by linked request ID, choose the first actual lookup as the baseline, and keep later queries only as observational reformulations. Match every lookup to an exact Codex/Claude runtime tool-call record and store the tool name plus complete arguments, scope, visibility, request link, and source-log hash. Broad and exact-work episodes are separate strata. Exclude ambiguous, unmatched, guessed-option, non-user-request, invalid-scope, forgotten, or unreconstructible episodes before splitting; exact-work is descriptive unless its tool call and work ref are recovered exactly. The primary mechanism comparison uses reconstructible broad pallium_search_history episodes only.
3. Assign every quarantined or rubric-shaping episode to development. Deterministically allocate other eligible broad episodes by SHA-256 of request ID plus frozen seed, adding development cases only to cover session/container/mechanism diversity. Confirmation must still contain at least 60 episodes, 30 sessions, and 5 containers. Calculate the exact paired outcome resolution (1/N) before labels; if the gate fails, stop and specify prospective collection rather than weaken it. Compare linked/unlinked structural distributions and limit claims to the valid linked cohort.
4. Prepare an isolated database/vector copy once, reconcile it before freezing, hash source/index/config/code/gold/cases, and restore that identical state per arm or prove before/after hashes unchanged. Cache query embeddings by query plus provider/model/version/preprocessing/dimension identity. Run the same recorded filters through resolve_query_filters, the configured production RetrievalProvider.query, _collapse_source_duplicates, _serialize_result, and _compact_history. The runner's unmodified K=3/K=10 outputs must byte-match QueryExecutor.query(source_only=True, limit=K) followed by production serialization/compaction on every development episode before any candidate score is accepted.
5. Freeze these exact arms. Control uses production raw retrieval depth min(max(4*K,12),200), production duplicate collapse/order, top K, and production rendering. B1 uses raw depth min(max(8*K,24),200) and is otherwise identical. B2 uses the exact control pool and stable-partitions only items whose left-trimmed source content case-folds to prefix <task-notification> after all other items, preserving order within both groups; nothing is excluded. B3 uses the exact control pool and stable-demotes later equivalents after all first/non-equivalent items, preserving every item and its own expansion neighborhood. B3 equivalence is non-null build_source_content_fingerprint(content) plus equal source_type, role, actor_ref, container_ref, sorted work_refs, and normalized historical-update state; thread_ref is intentionally omitted. A missing fingerprint or any work-ref/update conflict means non-equivalent. B2/B3 use the same pool, depth, K, byte budget, serializer, and renderer as their unmodified controls. No combined arm.
6. Calibrate blinded labels only on development. Label source usefulness as direct answer, useful background, irrelevant, or misleading/stale; separately tag task-notification structure and direct versus expansion-neighbor facts. Require at least 85% raw agreement and kappa at least 0.70 where supported; report rare-harm support/confusion/raw agreement. Allow one rubric revision; every case influencing it remains development.
7. Before inspecting any arm output, freeze and hash targets.json from pre-study telemetry. A known target is each distinct source_item_id that has a finalized expansion whose parent_lookup_id is the episode's first finalized baseline lookup. Multiple targets are allowed. A target is eligible only when that parent/anchor chain is complete, predates the frozen cutoff, is not the initiating request identity, and the exact source still exists and passes the replayed scope/visibility/forgotten checks; otherwise record the reason and exclude the episode only from target metrics. Equivalence is exact source_item_id only. Per-episode R@K is recovered eligible targets divided by eligible targets; aggregate R@K is the macro mean over episodes with at least one eligible target. MRR is reciprocal rank of the first exact target, zero when no target is returned, over the same denominator. These behaviorally selected anchors are a conservative no-regression safeguard, not relevance gold. Then freeze source labels and judge each arm's exact delivered preview. Episode usefulness is useful delivered slots divided by 3; missing slots are zero. Candidate win/loss/tie is positive/negative/zero usefulness difference from its matched control. Pooled relevant-hit/usefulness precision is conditional on the judged union, never absolute recall.
8. Apply the frozen development advancement rule. An arm is eligible only if (wins-losses)/N >= 0.10, at least three more wins than losses, no newly delivered misleading/stale source, no known-target R@10 loss, total and p95 response bytes do not increase, provenance is complete, and its warm paired p95 latency increment is at most 25 ms. Pick the eligible arm with highest net-win rate, then greatest known-target R@3 gain, then lowest paired p95 latency increment, then fixed simplicity order B2, B3, B1. If none qualify, or any required value is invalid, advance nothing and report no development candidate.
9. Confirm the one advancing arm once on untouched cases. The primary statistic is fixed-corpus net-win rate. Sensitivity is a deterministic 10,000-draw session-cluster bootstrap, seeded by the frozen manifest hash, with the 2.5th/97.5th percentiles as the 95% interval. Support requires net win at least +0.10 and interval lower bound above zero, plus every advancement safeguard. No material benefit requires interval upper bound below +0.10 with safeguards passing. A newly delivered misleading/stale exact source ID, any eligible known target present in control top 10 but absent from candidate top 10, incomplete candidate provenance, UTF-8 byte increase, or valid paired p95 latency increment over 25 ms is regression; otherwise report unresolved.
10. Measure bytes as UTF-8 length of production _json_text for the exact compact payload; require both summed bytes and nearest-rank p95 bytes no greater than control and every payload within the production hard limit. Measure latency on a deterministic 20-episode session/container-stratified subset (or all if fewer), in one isolated single-threaded process with network disabled and embeddings warm: two unmeasured warmups, then seven seeded AB/BA paired repetitions per episode. Use nearest-rank p95 of candidate-minus-control pair deltas. If control median absolute deviation divided by median exceeds 0.20, mark latency invalid and do not support the arm.
11. Save private case/gold/run records and a public text-free aggregate report. Do not implement or open a PR unless the evidence supports a separately scoped intervention.

**Verification plan:**
- Run the inventory twice and assert identical IDs, hashes, exclusions, development/confirmation split, and untouched-gate counts.
- Run one deterministic scripted pair through the exact replay/formatting path; interrupt and resume it; inject transient and permanent failures; include Unicode; assert no repeated completed work, preserved attempts, budget stop, and report-to-record reconciliation.
- Assert every arm starts from or verifies the same frozen source/index hashes and uses the recorded embedding cache identity.
- Assert B2/B3 control and treatment inputs match exactly on pool, depth, K, byte budget, and rendering path before transform.
- Double-label calibration and required review sample before freezing; verify no calibration or prior-inspection ID appears in confirmation.
- Recompute all metrics independently from durable records and reconcile episode/session/container counts, target eligibility, bytes, latency, and outcome thresholds.

**Plan review:**
See the Plan review section below. Clean-context Elevated final re-review passed on 2026-09-11.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Plan review

An Astra architecture reviewer found four blockers in the draft: rubric-changing cases could contaminate confirmation; B2/B3 had a deeper-pool confound; source usefulness was being conflated with the exact delivered preview; and mutable vector state could make arm order change the corpus. The plan above moves every inspected or rubric-shaping case to development, gives B2/B3 identical controls, freezes source labels before separately judging exact previews, and restores or verifies frozen state per arm. The reviewer concluded the corrected method is sound enough to execute and required all usefulness metrics to remain candidate-recovery-family diagnostics.

Clean-context Elevated plan review 2026-09-11: CHANGES NEEDED — freeze advancement/arm definitions, contamination inventory, replay eligibility manifest, and decision-statistic protocols before implementation. Steps 1-10 now define those items; awaiting re-review.

Clean-context Elevated plan re-review 2026-09-11: CHANGES NEEDED — define and freeze known-target construction/eligibility before implementation. Step 7 now defines source, parent mapping, multiplicity, eligibility, exact equivalence, denominators, and pre-output hash freeze; awaiting final re-review.

Clean-context Elevated plan final re-review 2026-09-11: PASS — all prior blockers closed; implementation may proceed within the frozen plan.

## Implementation

Not started.

## Evidence

Pending.

## Result review

Pending.
