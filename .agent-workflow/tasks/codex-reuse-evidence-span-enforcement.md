# Reuse evidence-span enforcement

Branch: `codex/reuse-evidence-span-enforcement`
Roadmap item: `roadmap/ideas/idea-reuse-judge-evidence-span-enforcement.md`

<!-- agent-workflow:start -->
**Outcome:**
Pallium counts a judged lookup as reuse only when the judge supplies short, verifiable evidence present in both the retrieved history and the work that followed; malformed evidence is reported as a judge failure.

**Target:**
Pallium repository.

**Scope:**
The existing historical reuse evaluator, its historical-lookup and reference-calibration tests, validation evidence, roadmap/board status, and this Work Record. No production retrieval, ranking, storage, API, dashboard, or integration behavior.

**Constraints:**
Reuse the existing judge/parser and report shape where compatible; no new evaluator, dependency, model, prompt-tuning examples, production writes, or claim about downstream product effect. Retrieval remains non-mutating.

**Completion criteria:**
When the judge returns incorporation, Pallium accepts it only with a string evidence span of 1–200 characters overlapping both retrieved history and work-after text; influence/none accept only an empty span. Every invalid type, length, label/span combination, or missing overlap becomes an explicit failure, focused lifecycle and boundary tests pass, and a cache-disabled reference run records the failure-rate impact.

**Risk:**
Routine

**Complexity:**
Moderate

**Reason:**
Redline classifies every intended path BLUE with no contract, boundary, API, persistence, security, or config finding. Complexity is Moderate because judge-output validation, report failure semantics, edge coverage, and a live failure-rate comparison must agree.

**Discovery:**
`_judge_once` is the sole provider-response boundary used by `run_judge`; it currently string-coerces and truncates raw evidence without validation, and failures are already excluded from labels, persistence, consensus, and kappa while incrementing `n_judge_failures`. Both focused test stubs emit the known-invalid work-only `"marker"`, so enforcing the contract requires correcting those stubs plus dedicated rejection cases. No reusable eval-local normalizer exists; `" ".join(text.casefold().split())` supplies the specified case/whitespace normalization without a dependency. The maintained N=12 reference runner already disables eval caching and is the existing impact-measurement path. `roadmap/board.md` still lists the now-completed calibration item, which is small roadmap drift resolvable in scope.

**Material assumptions:**
- Normalized substring presence—not fuzzy semantic similarity—is the intended executable meaning of overlap. If the live judge cannot reliably quote such a span, the measured failure increase is evidence to stop rather than weaken the validator.
- Existing handling of invalid rung/direction/genuine values is outside this evidence-only slice; evidence validation must not broaden into a response-schema rewrite.

**Plan:**
1. At `_judge_once`, validate raw `evidence_span` before coercion or truncation: exact string type, raw length <=200, incorporation requires non-empty normalized text present in the combined retrieved-history and work-after text, and every other accepted result requires the raw empty string. Raise into the existing sanitized failure path; do not change prompts, report shape, consensus, persistence, or production code.
2. Correct the two existing judge stubs to quote evidence present on both sides for incorporation and emit empty evidence for influence/none. Add focused run-through-the-public-runner tests for valid case/whitespace/unicode overlap; empty, exact-200, and over-200 boundaries; non-string values; one-sided/missing overlap; and non-empty influence/none. Assert invalid results increment failures and are not persisted.
3. Run focused suites and the cache-disabled two-group reference validation. Record before/after failure count and kappa/rung impact honestly. If enforcement makes the gate fail, keep the validator fail-closed, leave rung rates untrusted, reopen calibration, and defer real-window interpretation rather than weakening validation.
4. Mark this roadmap item done, remove the already-completed calibration item from the active board, and record the dated downstream-task-effect observational evidence in validation docs. Run workflow/redline/full checks, independent result review, then close the PR through green CI and resolved review threads.

Key conventions: retrieval alone remains non-mutating; every reported number is labeled downstream-task-effect/observational; use the existing sanitized judge-failure path and scratch-DB reference runner; no product-specific fixture or new dependency.

Target files: `evals/historical_lookup_judge.py`, `tests/test_historical_lookup_judge.py`, `tests/test_reuse_judge_calibration.py`, `docs/context/validation.md`, `roadmap/ideas/idea-reuse-judge-evidence-span-enforcement.md`, `roadmap/board.md`, and this Work Record.

**Verification plan:**
- Valid contract → when evidence is a string of 1–200 characters and normalized text occurs in both sides for incorporation, the runner shall accept and persist the label → focused runner-level tests including exact-200 and non-ASCII/case/whitespace normalization.
- Invalid contract → when type, length, rung consistency, or either overlap fails, the runner shall count an explicit failure and persist no label → parameterized runner-level rejection tests for empty, 201, non-string, retrieved-only, work-only, and non-empty influence/none.
- Measurement remains honest → cache-disabled two-group N=12 reference run shall report failure-rate and kappa/rung-rate impact as downstream-task-effect/observational and must still satisfy the 0.70 maintained-reference gate → serialized report plus validation entry.
- No regression/drift → focused suites, full non-slow suite, workflow checker, redline report, diff check, and roadmap active/done lists agree.

**Plan review:**
Self-reviewed for Routine risk: the plan fixes the single shared response boundary, reuses the existing failure mechanism and live runner, and covers all stated boundaries through the caller surface. After the live gate failed, an independent result review recommended shipping fail-closed, reopening calibration, and adding deterministic committed-fixture coverage; the revised plan records that honest stop on downstream interpretation rather than weakening the contract.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Established task context before code inspection. Clean-context redline classified all intended paths BLUE with no boundary or contract findings.
- Discovery confirmed one shared response boundary and two affected focused suites. Planning is complete and self-reviewed; no code has been edited yet.
- The planned Work Record update hit the documented Windows `CreateProcessWithLogonW failed: 1385`. Per local instructions it was not retried; this file was updated through a deterministic, single-file .NET replacement.
- Implemented the shared validator and runner-level boundary/lifecycle tests. The first live enforced-contract gate failed with 16/72 malformed spans, so result review returned the task to planning; calibration was reopened and committed-fixture coverage was added without weakening the guard.

## Evidence

- Focused historical-lookup/reference-calibration suites: 53 passed, including the committed N=12 fixture through the executable contract.
- Full non-slow suite under an explicit nonexistent config path: 3692 passed, 23 skipped, 2 xfailed. An earlier run had one unrelated local-config leak; the single test and full suite passed after isolating PALLIUM_CONFIG_FILE.
- Cache-disabled real-provider maintained-reference run: 16/72 calls failed evidence validation (22.2%; 8/36 per group). Group A compared 10/12 events, group B 11/12, mutual 10/12; incomplete-subset kappa was 1.0, but the overall gate correctly failed. Measurement kind: downstream-task-effect / observational judge reliability.
- Four-call diagnostic confirmed the cause without exposing prompt text: one retrieved-only and two work-after-only incorporation spans failed; one influence span was correctly empty.
- Python compile and git diff checks passed. Agent-workflow checker is clean. Import-linter/redline verdict is BLUE with zero boundary violations and no checkpoints.

## Result review

Independent result review recommended shipping the fail-closed validator, reopening calibration, and adding deterministic committed-fixture coverage. It found no validator defect and confirmed that perfect kappa on the incomplete surviving subset must not be called a pass. The requested fixture coverage and roadmap/docs alignment are implemented. Final-diff independent re-review: APPROVE, with no remaining concrete blockers.