<!-- agent-workflow:start -->
**Outcome:** Produce decision-grade, budget-capped evidence of whether Pallium history improves downstream work, reusing already-paid outputs before permitting any new model calls.

**Target:** Pallium real-corpus evaluation.

**Scope:** `evals/real_corpus_pull_eval.py`, `tests/test_real_corpus_pull_eval.py`, `roadmap/ideas/idea-pull-real-corpus-validation.md`, this Work Record, and ignored private reports under `.local/research/`.

**Constraints:** Keep the source database read-only and private text local. The zero-cost reassessment makes no provider calls. A paid replacement pilot remains fail-closed unless preflight finds at least eight genuine direct replacements across at least four sessions and three task types. New spend is capped at 48 calls and 20,000 estimated input tokens; the first replacement pilot is capped at 12 calls. Do not change production retrieval, ranking, API, storage, visibility, or lifecycle behavior. Every reported number must be labelled as downstream-task-effect, not candidate recovery or injection precision.

**Completion criteria:** Existing paid outputs receive a blinded, answerability-first agent review; evaluator controls support exact case selection, lower per-run call/token caps, and a no-model-judge path; focused tests prove each control and prove budget/preflight stops make no unintended calls; a read-only lineage inventory either qualifies a staged paid pilot or stops it at zero calls; the roadmap records the evidence, limitation, decision, and next gate.

**Risk:** Low

**Complexity:** Moderate

**Reason:** All intended files are BLUE under the repository redline policy and no production boundary is touched. Complexity is Moderate because the task combines deterministic evaluator controls, a blinded reuse analysis, and a conditional staged experiment, while keeping one narrow product outcome.

**Discovery:** The completed 20-case run already contains raw, guarded, and no-history answers but its automatic judge overstated value on malformed tasks. The corrected direct-claim filter invalidated its only apparent replacement case, leaving zero qualifying replacements. The evaluator already centralizes caching, lineage preflight, and hard global caps, but its CLI fixes the run at 100 calls / 50,000 estimated input tokens, cannot select exact case IDs, and always spends two judge calls per case in the three-arm run. Reusing the paid answers can answer the general-value question at zero cost; new calls are justified only for genuine direct replacements.

**Material assumptions:** Prior private outputs are complete enough for a blinded reassessment; disproved by missing/corrupt answer records, which stops the reassessment rather than reconstructing answers with paid calls. The live snapshot may contain enough direct replacements; disproved if preflight finds fewer than eight or insufficient session/task diversity, which must stop the paid pilot at zero calls. Exact provider usage may remain unavailable; in that case report the conservative estimated-input cap and never claim exact cost.

**Plan:** 1. Add the smallest evaluator controls for exact case IDs, configurable lower call/token caps, and disabling model judging while preserving current defaults. 2. Add focused tests for selection, bounds, zero-judge behavior, cache accounting, and fail-closed preflight. 3. Label existing cases for answerability/applicability without seeing their answers, then review valid guarded versus no-history answers in deterministic blinded order and write a private agent-review report. 4. Inventory direct replacement cases from the scratch snapshot without provider calls. 5. Only if the preregistered lineage/diversity gate passes, run four replacement cases (12 calls), expanding to eight cases and at most 32 calls / 15,000 estimated input tokens only when informative; use the absolute 48-call / 20,000-token ceiling solely for justified ambiguous repeats or missing general-value evidence. 6. Update the roadmap with the observed outcome and product decision; verify, review, and close the PR.

**Verification plan:** Exact selection accepts known IDs and rejects unknown/duplicate IDs without provider calls. Lower caps stop before exceeding either call or estimated-input limits and leave no partial aggregate presented as complete. No-judge mode emits answers/review material with zero judge calls. Existing defaults remain backward compatible. Guarded/both lineage preflight remains zero-call on insufficient direct replacements. Focused pytest, workflow checker, redline report, and `git diff --check` pass. Private reports record case exclusions, blinded choices, model calls, estimated input tokens, failures, and the downstream-task-effect interpretation.

**Plan review:** Self-reviewed; clean-context redline review classified the complete intended scope BLUE with no checkpoint or boundary risk and required preserving fail-closed lineage preflight and non-partial budget stops.

**Approvals:** User approved execution on 2026-08-25: "ok, go".

**Exceptions:** Human review is unavailable by product constraint; any manual review is explicitly labelled agent review and cannot satisfy a human-validation claim.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Pre-edit redline classification: BLUE; no production, API, schema, persistence, security, or runtime-config path is in scope.

## Evidence

- Pending.

## Result review

- Pending.
