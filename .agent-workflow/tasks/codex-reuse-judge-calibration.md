# Reuse judge calibration completion

Branch: `codex/reuse-judge-calibration`
Roadmap item: `roadmap/ideas/idea-reuse-judge-calibration.md`

<!-- agent-workflow:start -->
**Outcome:**
Pallium reports whether its reuse judge agrees with the maintained reference set, with per-category accuracy and repeat-run stability, and never overstates that evidence as independent human calibration.

**Target:**
Pallium repository.

**Scope:**
Existing reuse-judge prompt metadata, reference-set metrics/runner, focused tests, validation evidence, roadmap status, and the existing dashboard calibration copy, legacy report fields, and responsive summary layout. No production retrieval, storage, API, dashboard endpoint, or integration behavior.

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
4. Run two scratch-DB evaluations over identical event IDs in identical order, using disjoint seed groups `0,1,2` and `3,4,5`, with eval cache disabled. Build one consensus vector per group over the same successfully judged events and compute mutual kappa, reporting `n`, missing, extra, and partial/all-failed events. Any failed seed call rejects the verdict while remaining visible. The verdict otherwise passes only when both group-vs-reference kappas and mutual kappa use the exported threshold and meet 0.70 over the exact expected event set.
5. Add focused unit and CLI/report end-to-end coverage: dry run and serialized report; empty, exact, and over-count samples; invalid reference labels; mismatched event sets including extras; a missing seed group; zero-denominator metrics; and partial/all judge failures.
6. Preserve the existing dashboard report shape by mapping combined kappa to the minimum of the two group-vs-reference kappas and combined N to the minimum group comparison N. Change app/dashboard.html copy only from human-review to maintained-reference-set wording; do not alter endpoints.
7. In response to user visual feedback, make a CSS-only reuse-summary layout change: wrap only its existing key/value rows, cap that wrapper at 760px, use a two-column grid with adjacent left-aligned values, and collapse to one column at the existing narrow-screen breakpoint. Do not change report data, field order, copy, endpoint behavior, or rendering semantics. Add HTML/CSS contract assertions for the reuse-only wrapper, 760px cap, two-column grid, and narrow fallback; then run dashboard/focused/full checks, restart the local service, and validate wide/narrow browser screenshots.

**Verification plan:**
- Report completeness → deterministic tests assert prompt/version, all three classes, confusion-matrix totals, precision/recall zero-denominator behavior, and the 0.70 verdict.
- Honest evidence semantics → tests and docs call the fixture a maintained single-author reference set and never describe its pass result as independent human agreement.
- Repeat stability → two cache-disabled real-provider runs over identical ordered events with disjoint three-seed groups and scratch DBs record both reference kappas, mutual kappa, `n`, and missing/failed events; any empty, mismatched, missing, extra, or failed seed call rejects the gate.
- CLI lifecycle → dry-run and serialized-report paths cover empty, exact, and over-count sampling, invalid reference labels, mismatched event sets, a missing group, and all-failed judge calls without division errors or false passes.
- Dashboard semantics and layout → tests assert the legacy summary fields equal minimum group kappa/minimum group N plus threshold/verdict and caller-facing HTML contains honest wording; HTML/CSS contract assertions require the reuse-only wrapper, `max-width: 760px`, two-column grid, and narrow-screen `1fr` fallback without data/render-semantic changes. The restarted service is checked in a real headless browser at wide and narrow viewports, with screenshots inspected.
- No regression and roadmap truth → focused tests, full non-slow suite, agent-workflow checker, redline report, validation evidence, and roadmap status agree.

**Plan review:**
Initial clean-context review returned REVISE. Its two-human-label requirement was made obsolete by the user's explicit constraint that two independent people will not be available. The revised achievable claim is reference-set validation only. Final independent re-review: APPROVE; the exported 0.70 gate, paired repeat-run contract, honest terminology, and CLI/report boundaries resolve all blockers. UX addition re-review: APPROVE; the plan is limited to a reuse-only 760px CSS grid with contract tests and wide/narrow browser evidence, with no data or rendering-semantic changes.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Established context and completed read-only discovery. No production or evaluation code edited.
- Pre-edit redline verdict: BLUE for intended eval/tests/docs/roadmap scope; no boundary findings. Elevated declared conservatively because the Work Record path is unclassified in the current policy.
- The first Work Record update attempt hit the documented Windows `CreateProcessWithLogonW failed: 1385`. Per local instructions it was not retried; this file was updated through a deterministic, single-file .NET replacement.

- Implemented the 0.70 constant, prompt provenance, confusion/per-class metrics, two-group comparison, mandatory CLI cache disablement, honest docs, and focused lifecycle tests.
- Result review found ignored extra events, hidden partial failures, and stale dashboard human-review copy/report shape. State returned to Blocked for the scoped correction and review.
- Redline reassessment for app/dashboard.html: BLUE watch-only, no boundary findings or checkpoint; edit remains copy/rendering-only.
- Final verification passed and the roadmap item moved from queued to done.
- User requested a follow-up reuse-card readability improvement before merge; state returned to Blocked for the responsive layout edit and review.
- UX re-plan was independently approved. Implemented only `app/dashboard.html` and `tests/test_dashboard.py`: a reuse-only 760px grid wrapper, adjacent left-aligned values, and the existing 900px breakpoint's single-column fallback. Report data, field order, copy, endpoints, and rendering semantics are unchanged. The documented deterministic .NET replacement was used because `apply_patch` had already failed with Windows error 1385.
- UX result review found stale human-review claims in the initial/fetch-failure fallback. State returned to Blocked for the already-scoped copy correction and a stronger contract assertion.
- Corrected the static fallback and nearby explanatory comment to maintained-reference-set/seed-group wording. Added negative assertions for the stale phrases; no data or runtime behavior changed.
- PR review found two remaining scoped boundary defects: the dashboard missing-threshold fallback was still 0.60, and direct validation callers could supply other than two seed groups. State returned to Blocked for minimal guards and focused tests.
- Changed the fallback to 0.70 and added an exact-two-groups guard before indexing. Added one dashboard contract assertion and parameterized one-group/three-group regression cases.
- A follow-up PR thread correctly found that maintained-reference wording alone still hid the single-author limitation. State returned to Blocked to make that qualifier explicit in every reuse-card state and revalidate the longer layout.
- Added the single-author qualifier across the initial, unavailable, calibrated, and uncalibrated card copy plus the reference-count label and explanatory comment. The dashboard contract now requires the qualifier.

## Evidence

- Focused judge/reference/dashboard suites: 66 passed after all result-review corrections.
- Full non-slow suite with the ignored local config explicitly disabled: 3678 passed, 23 skipped, 2 xfailed. The earlier single failure was reproduced as local-config contamination and passed in isolation under the neutral config.
- Caller-facing full-fixture dry-run wrote a valid two-group report and failed honestly at the 0.70 gate.
- After explicit user approval, the evaluator inherited the existing launcher credential in-memory without displaying or copying it. Cache-disabled real-provider result: group A κ=0.750 (N=12), group B κ=0.875 (N=12), mutual κ=0.870 (N=12), zero failures → PASSED at 0.70.
- Compile check and git diff --check passed; Ruff is not installed in the local environment.
- Final workflow checker: clean. Redline: BLUE, app/dashboard.html watch-only, no checkpoints or boundary findings; reporter exit 1 is advisory review-warnings in shadow mode.
- UX verification: `tests/test_dashboard.py` 27 passed; full non-slow suite 3678 passed, 23 skipped, 2 xfailed with the ignored local config disabled; git diff --check passed.
- Restarted the installed scheduled-task service. /health returned 200 status=ok, `vector_index_ready=true`, and `embedding_provider_ok=true`; /status returned 200.
- Bundled Playwright validated the served dashboard at 2048×700 and 480×900. Wide summary width was exactly 760px with 280px/456px columns and the value 304px from the wrapper edge; narrow layout computed one 414px column with the value below its label. Screenshots: .local/research/reuse-card-wide.png and .local/research/reuse-card-narrow.png.
- After the review correction, the dashboard suite again passed 27 tests. The installed service was restarted to healthy status and the identical Playwright wide/narrow assertions passed again.
- PR review corrections: dashboard plus reuse-calibration focused suites passed 56 tests. The installed service was restarted again and returned 200 with status ok, vector index ready, and embedding provider working.
- Single-author copy correction: dashboard suite passed 27 tests; installed service restarted healthy; Playwright wide/narrow geometry remained unchanged and passed.

## Plan review

Initial clean-context review: REVISE. The user then ruled out two independent human raters, so the plan removes that workflow and narrows the claim to single-author reference-set validation. Final independent re-review: APPROVE; all three remaining blockers were resolved.

## Result review

Correction-plan re-review: APPROVE after making any failed seed call fatal, defining exact extra-event rejection and min-kappa/min-N legacy mapping, and limiting dashboard scope to copy only.


Independent result review: APPROVE after exact event-set rejection, partial/all-failure rejection, three distinct disjoint seeds per group, compatible minimum-kappa/minimum-N dashboard fields, and honest reference-set copy. Live evidence subsequently passed all three 0.70 gates with zero failures; roadmap and validation evidence are aligned.

UX result review initially found stale human-review claims in the static fallback. After correction and regression assertions, independent re-review: APPROVE; fallback semantics are honest, CSS is reuse-only and responsive, and data/render semantics remain unchanged.

PR review then found the stale 0.60 display fallback and missing outer seed-group cardinality validation. Both were accepted as valid scoped findings and corrected with focused regression coverage. Independent re-review: APPROVE; the authoritative threshold and exact-two guard are now consistent and covered.

A later PR thread found the dashboard did not expose that the reference set is single-author. The finding was accepted and every reuse-card state now carries that qualifier with contract and browser verification. Independent re-review: APPROVE; all states are honest and the longer copy remains responsive.
