# Reuse judge calibration completion

Branch: `codex/reuse-judge-calibration`
Roadmap item: `roadmap/ideas/idea-reuse-judge-calibration.md`

<!-- agent-workflow:start -->
**Outcome:**
Pallium reports whether its reuse judge agrees with the maintained reference set, with per-category accuracy and repeat-run stability, and never overstates that evidence as independent human calibration.

**Target:**
Pallium repository.

**Scope:**
Existing reuse-judge prompt metadata, reference-set metrics/runner, focused tests, validation evidence, and roadmap status. No production retrieval, storage, API, dashboard, or integration behavior.

**Constraints:**
Reuse the existing judge and scratch-DB runner; no replacement evaluator, model change, production DB access, product-specific fixtures, or tuning examples to force a pass. Retrieval remains non-mutating. Evidence-span enforcement stays in its separate ticket: this task measures rung-label agreement, not whether evidence spans are executable.

**Completion criteria:**
The report records prompt/version, confusion matrix, per-class precision/recall/support, two independent seed-group results, and an honest reference-set pass/fail verdict at the authoritative 0.70 threshold. Both seed groups agree with the maintained reference set at kappa >= 0.70 and agree mutually at kappa >= 0.70. Focused and full verification pass; roadmap and validation docs state that this is a single-author reference-set check, not independent human calibration.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Redline classifies the eval/tests/docs/roadmap scope BLUE with no boundary findings, but the required Work Record path is unclassified and has previously made final diffs GRAY; risk is conservatively raised to Elevated. Moderate because reporting, repeated live runs, threshold semantics, and evidence must agree.

**Discovery:**
Calibration plumbing already exists: consensus-vs-gold kappa, scratch runner, rollup gating, and dashboard status. Current prompt is the hardened rubric and previously moved kappa 0.50→0.75 on N=12, but validation.md still records only 0.50. The fixture is synthetic and single-author with no verified independent human rater. Missing for the achievable reference-set claim: per-class metrics, prompt/version, and repeated independent runs. Roadmap says ≥0.70 while code/docs gate at 0.60. Evidence-span output remains prompt-only but is separately queued.

**Material assumptions:**
- The 2026-08-17 reopened roadmap note is the latest approved threshold decision: 0.70 is the live gate, and 0.60 is historical only.
- Two independent human raters are not available and are not part of the product workflow. The maintained single-author labels are therefore a regression reference set, not evidence of objective human agreement.
- The minimum stability gate is: seed group A vs reference labels >=0.70, seed group B vs reference labels >=0.70, and group A vs group B >=0.70. Any failure is uncalibrated.

**Plan:**
1. Reuse the current fixture→scratch DB→real judge path. Add only stable prompt id/version, confusion matrix, and per-class precision/recall/support in the existing judge/calibration modules.
2. Change the exported `GOLD_KAPPA_THRESHOLD` constant to 0.70 and use it as the sole live threshold for reports and verdicts. Preserve historical 0.50 and provisional hardened-rubric 0.75 results as dated evidence; remove any active 0.60 gate from validation and roadmap text.
3. Keep the existing single-author fixture as a clearly named reference set. Do not add a labeling workflow, rater schema, adjudication machinery, or any claim of independent human calibration.
4. Run two scratch-DB evaluations over identical event IDs in identical order, using disjoint seed groups `0,1,2` and `3,4,5`, with eval cache disabled. Build one consensus vector per group over the same successfully judged events and compute mutual kappa, reporting `n`, missing events, and failed events. The reference-set verdict passes only when both group-vs-reference kappas and mutual kappa use the exported threshold and meet 0.70; an empty comparison or any missing/all-failed group fails.
5. Add focused unit and CLI/report end-to-end coverage: dry run and serialized report; empty, exact, and over-count samples; invalid reference labels; mismatched event sets; a missing seed group; zero-denominator metrics; and all judge calls failed. Run the full non-slow suite plus workflow/redline checks. Update roadmap status only after all completion criteria hold.

**Verification plan:**
- Report completeness → deterministic tests assert prompt/version, all three classes, confusion-matrix totals, precision/recall zero-denominator behavior, and the 0.70 verdict.
- Honest evidence semantics → tests and docs call the fixture a maintained single-author reference set and never describe its pass result as independent human agreement.
- Repeat stability → two cache-disabled real-provider runs over identical ordered events with disjoint three-seed groups and scratch DBs record both reference kappas, mutual kappa, `n`, and missing/failed events; any empty, mismatched, missing, or all-failed group fails the reference-set gate.
- CLI lifecycle → dry-run and serialized-report paths cover empty, exact, and over-count sampling, invalid reference labels, mismatched event sets, a missing group, and all-failed judge calls without division errors or false passes.
- No regression and roadmap truth → focused tests, full non-slow suite, agent-workflow checker, redline report, validation evidence, and roadmap status agree.

**Plan review:**
Initial clean-context review returned REVISE. Its two-human-label requirement was made obsolete by the user's explicit constraint that two independent people will not be available. The revised achievable claim is reference-set validation only. Final independent re-review: APPROVE; the exported 0.70 gate, paired repeat-run contract, honest terminology, and CLI/report boundaries resolve all blockers.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Established context and completed read-only discovery. No production or evaluation code edited.
- Pre-edit redline verdict: BLUE for intended eval/tests/docs/roadmap scope; no boundary findings. Elevated declared conservatively because the Work Record path is unclassified in the current policy.
- The first Work Record update attempt hit the documented Windows `CreateProcessWithLogonW failed: 1385`. Per local instructions it was not retried; this file was updated through a deterministic, single-file .NET replacement.

## Evidence

Pending.

## Plan review

Initial clean-context review: REVISE. The user then ruled out two independent human raters, so the plan removes that workflow and narrows the claim to single-author reference-set validation. Final independent re-review: APPROVE; all three remaining blockers were resolved.

## Result review

Pending.
