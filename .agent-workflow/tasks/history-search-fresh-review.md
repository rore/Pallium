<!-- agent-workflow:start -->
**Outcome:**
Identify remaining Session History search failures using fresh and expanded real cases, and ship at most one evidence-supported fix with regression coverage when warranted.

**Target:**
Pallium Session History.

**Scope:**
Bounded private audit and replay of real search cases; anonymized research report and regression reproductions; one justified search or caller-guidance fix with verification, reviewed delivery, and roadmap alignment.

**Constraints:**
Preserve visibility, exact-work scope, forgetting, redaction, historical-state cautions, and retrieval-is-not-use. Keep private corpus content and identifiers uncommitted. Preserve previous reserved holdouts. Use at most two concurrent workers and no paid model-evaluation runs or model downloads. Expand beyond twelve initial cases when coverage is insufficient; distinguish independent cases, related examples, and synthetic regressions. Reclassify and review the concrete implementation before production edits.

**Completion criteria:**
A reviewed report records sample provenance, expansion, exclusions, independent-task limits, failure classes, and a supported next action. Every confirmed changed behavior has caller-surface regression coverage. Any selected fix passes the scope-selected validation and independent review, is delivered through the authorized PR/merge workflow, and the roadmap states precisely what remains open.

**Requirement baseline:**
{"source":"15e6e26c-5ea6-49dc-a534-03adf278f53a","outcome":"Identify remaining Session History search failures using fresh and expanded real cases, and ship at most one evidence-supported fix with regression coverage when warranted.","scope":"Bounded private audit and replay of real search cases; anonymized research report and regression reproductions; one justified search or caller-guidance fix with verification, reviewed delivery, and roadmap alignment.","constraints":"Preserve visibility, exact-work scope, forgetting, redaction, historical-state cautions, and retrieval-is-not-use. Keep private corpus content and identifiers uncommitted. Preserve previous reserved holdouts. Use at most two concurrent workers and no paid model-evaluation runs or model downloads. Expand beyond twelve initial cases when coverage is insufficient; distinguish independent cases, related examples, and synthetic regressions. Reclassify and review the concrete implementation before production edits.","completion_criteria":"A reviewed report records sample provenance, expansion, exclusions, independent-task limits, failure classes, and a supported next action. Every confirmed changed behavior has caller-surface regression coverage. Any selected fix passes the scope-selected validation and independent review, is delivered through the authorized PR/merge workflow, and the roadmap states precisely what remains open."}

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Initial report, eval, test, and roadmap paths are BLUE; judgment raises risk for private evidence handling, sampling validity, and a possible production fix that needs separate concrete classification before editing.

**Discovery:**
Main e0e38178 has the September 23 reliability work and no later search-quality delivery. The umbrella queues equivalent-result review before a conditional fixed-candidate ranking preflight. Prior studies lacked independent cases. Existing private studies and eval harnesses are available; health and embedding-provider checks passed on pickup.

**Material assumptions:**
Fresh audit data may be insufficient: expand to older unused cases and replay them against current behavior, labeling historical versus current evidence. Equivalent text may carry different provenance: retain original handles and inspect before recommending grouping. If no reproducible fix is supported after expanded review, deliver evidence and the precise gap instead of inventing a change. Unknown production paths require a revised concrete plan, risk assessment, and review within the authorized objective.

**Plan:**
1. Invoke Agent Workflow, record context and risk, and commit this record before implementation. Initial tracked targets: this record, docs/reports/session-history-fresh-review.md, roadmap/features/improve-session-history-search-quality.md, and any justified generic reproduction under tests/ or evals/. Private evidence stays under .local/history-search-fresh-review in the shared checkout.
2. Delegate a bounded inventory to Luna and a read-only clean-context plan review to Sol. Inventory recent linked lookups first; expand older unused candidates if twelve cases lack diversity or failure coverage. Record exclusions before opening reserved evidence. Use existing SQLite/audit/eval helpers and read-only source access; never modify live corpus or call model judges.
3. Review a diverse initial batch and expand in batches when conclusions remain unstable or failure classes unexplored. Separate search availability, candidate recovery, ranking, presentation, query repair, and provenance. Report navigation observations separately from candidate recovery, injection precision, and downstream task effect; do not claim unmeasured outcomes.
4. Have a bounded worker map confirmed failures to tests. Select at most one coherent fix only after reviewing the evidence; add a failing caller-surface reproduction before changing behavior. Record exact paths, classify risk, and get independent plan review before production edits. Missing fixed-window evidence routes to recovery/query repair; reranking comparison is not authorized without its preflight gate and separate paid-study authority.
5. Verify with scripts/test-plan.py over the whole change, required workflow checks, affected caller E2E, and independent result review. Resolve PR findings, merge when green, update installed service and health, align roadmap, and retire the temporary checkout after preserving private evidence.

**Verification plan:**
- Sample provenance, expansion and exclusions shall be traceable -> inspect private case manifest and reviewed report; verify holdout protection and task/session grouping.
- Published findings shall distinguish measured outcomes and supported fixes -> independent evidence/result review with successful and no-answer counterexamples.
- Changed caller behavior shall meet current requirements -> failing-before/passing-after caller-surface regression and boundary tests, plus the whole-change test selector and reported checks.
- Delivered changes and roadmap shall agree -> PR review, CI, merge SHA and installed health verification; leave wider umbrella open unless its criteria are actually met.

**Plan review:**
Agent technical review: /root/fresh_plan_review approved bbc5174d with the frozen sampling protocol recorded before case-content review. The protocol below resolves the sole finding; no other blocking findings. Approval covers observational research, not a yet-unspecified production change.

**Approvals:**
Approved by user 2026-09-30: "ok. be systematic and remember the goal. you can drive this". Prior approval includes PRs and merge according to guidelines; user explicitly requires expanding researched cases if fresh data is insufficient.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

2026-09-30: Created isolated worktree from e0e38178. Initial scope is not documentation-exempt because it includes research/eval/test work. Read-only inventory and plan review are next; material implementation waits for plan review. Lead owns roadmap updates and this record; workers receive explicit bounded file ownership.

Plan-review refinement before case-content review: private `C:\Dev\rore\Pallium\.local\history-search-fresh-review\PROTOCOL.md` freezes eligibility, exclusions, connected-component grouping, deterministic confirmation reservation, 12-case batches up to 60 or eligible-pool exhaustion, coverage descriptors, and saturation/uncertainty stopping rules. This operationalizes the authorized expansion without changing Task Context. The first review requested these explicit limits; re-review approved. Initial tracked path classification is BLUE with zero boundary violations; judgment retains Elevated for evidence-handling uncertainty.

## Evidence

Expanded census completed with 265 pre-investigation lookup records and 226 expansions in the exact container. The newer eligible metadata window has eight linked events / three request-session groups, all overlapping earlier exposed evidence at group level. Prior holdout identities could not be recovered; no source content was opened, no ranking replay or paid evaluation ran, and content-review coverage remains unmet. This is the protocol's protected-pool exhaustion/uncertainty stop, not saturation or feature completion. Private protocol, reproducible read-only inventory, aggregate, manifest, and report survive under the shared checkout's ignored `.local/history-search-fresh-review/`; public report and both affected roadmap items retain the evidence prerequisite and separate downstream-value gates.

Before result review, fresh `origin/main` remained e0e38178. Whole-change `scripts/test-plan.py --base origin/main` selected the full lane. Redline over all seven changed paths is BLUE with zero boundary violations, no protected-contract edits, and no required checkpoints; declared risk remains Elevated. Agent Workflow check is clean. Full non-slow `python -m pytest tests/ -x -q` passed on Windows/shared Python environment: 5772 passed, 34 skipped, 2 xfailed in 346.36 seconds. It ran against 58a05c6a plus exactly the code/test diff committed as 8509038c; subsequent changes are documentation/evidence only. PR CI remains a delivery gate.

2026-09-30 implementation verification: the extended HTTP → persisted audit → `load_corpus` regression failed before the fix because neither persisted lookup was admitted (`cases == {}`). After removing only request/event actor equality, the exact test passed (`1 passed`), and `python -m pytest tests/test_historical_lookup_funnel_e2e.py tests/test_real_corpus_pull_eval.py -q -n 0` passed (`58 passed`). The test asserts both replay modes, exact event IDs, request text, source IDs, and the explicit actor filter's isolation; existing invalid-link attrition is checked in both modes.

## Concrete correction plan and review

2026-09-30: Expanded metadata inventory found eight pre-investigation lookups from September 12-22 whose directly linked user requests were rejected solely by the evaluator's actor-equality check. Production `PalliumService.query` validates request lineage using live/user/container/active-session/visibility, while actor_ref is an optional source filter. `test_request_link_actor_is_optional_metadata` already proves absent and different actors are valid through HTTP and audit. The evaluator's extra equality check is contract drift, not a retrieval or ranking failure.

Selected bounded fix: remove only request/lookup actor equality in `evals/real_corpus_pull_eval.py::load_corpus`; retain all other request checks and source visibility/redaction/forgetting behavior. Extend `tests/test_historical_lookup_funnel_e2e.py::test_request_link_actor_is_optional_metadata` through nonempty HTTP search, audit read, and evaluator loading in both replay modes. Seed older scoped evidence first and assert both exact event IDs and expected source IDs survive. Extend `tests/test_real_corpus_pull_eval.py` only as needed to prove genuine invalid request links remain rejected in both modes. No protected contract edits, dependencies, API, ranking, index, or live-data changes. These eval/test paths are BLUE; Elevated evidence-handling review remains in force.

Before/after acceptance: the new caller regression must fail on the old evaluator with zero admitted valid cases and pass with both valid actor variants admitted; all scope/role/forgotten/time reject cases remain rejected. Validate affected files, whole-change selector, full non-slow lane if selected, architecture/workflow checks, and independent result review. This demonstrates measurement eligibility, not candidate recovery, injection precision, or downstream task effect. Expanded content-equivalence investigation continues and has its own evidence limitations.

Agent technical review: /root/fresh_plan_review APPROVE at dab74103, after independently comparing `core/service.py:1027-1050`, `app/mcp/client.py:113-116`, loader request/source gates, and the existing HTTP contract witness. Reviewer required nonempty older evidence and both replay modes; these requirements are incorporated above.

## Result review

Agent technical review: /root/fresh_plan_review (clean-context non-implementer, Sol) APPROVE, conditional on full suite, required checks, and PR CI. The local full suite subsequently passed.

Reviewed revision: 8509038c.

Verification adequacy: HTTP → persisted audit → evaluator regression covers both replay modes, absent/different source actor filters, exact exposed sources, and preserved invalid-link rejection; focused red→green and 58 affected passing tests are sufficient for the one-condition correction alongside full-suite/CI validation. Reviewer reconciled all published population/group counts against private metadata, found no correctness/privacy blocker, and confirmed uncertainty and the queued umbrella are explicit.

Review clarification: audit/replay and generic regression work already include evaluator eligibility. The concrete correction plan was independently reviewed before code; no task behavior, immutable baseline, or protected contract was changed. An initial request to alter structured Scope was withdrawn after checking behavioral-integrity. Optional report wording now explicitly distinguishes unopened prior source contents from normalized query metadata used for overlap checks. Delivery remains pending PR CI/merge; this record does not assert the wider search-quality feature is finished.
