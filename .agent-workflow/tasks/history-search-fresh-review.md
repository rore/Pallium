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

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

2026-09-30: Created isolated worktree from e0e38178. Initial scope is not documentation-exempt because it includes research/eval/test work. Read-only inventory and plan review are next; material implementation waits for plan review. Lead owns roadmap updates and this record; workers receive explicit bounded file ownership.

Plan-review refinement before case-content review: private `C:\Dev\rore\Pallium\.local\history-search-fresh-review\PROTOCOL.md` freezes eligibility, exclusions, connected-component grouping, deterministic confirmation reservation, 12-case batches up to 60 or eligible-pool exhaustion, coverage descriptors, and saturation/uncertainty stopping rules. This operationalizes the authorized expansion without changing Task Context. The first review requested these explicit limits; re-review approved. Initial tracked path classification is BLUE with zero boundary violations; judgment retains Elevated for evidence-handling uncertainty.

## Evidence

Pending.

## Result review

Pending.
