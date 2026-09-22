<!-- agent-workflow:start -->
**Outcome:**
Agents repair and continue Session History retrieval without repeating delivered evidence, and an anonymized deterministic replay reports navigation/presentation cost and required-evidence recovery without overstating the measured layer.

**Target:**
Pallium.

**Scope:**
Session History retry and continuation guidance across supported integration surfaces; a deterministic history-pull replay driver and report; focused tests; integration documentation; and roadmap slice 6.

**Constraints:**
Add no production API, store, retrieval/ranking behavior, dependency, automatic query rewriter, or generated recap service. Reuse existing search paging, expansion continuation, and parent lineage. Preserve privacy, visibility, forgetting, historical-state warnings, and the rule that retrieval alone never changes accessibility or ranking. Bound retries, keep guidance within existing byte ceilings, verify current-state claims separately against live state, and label the replay as navigation/presentation evidence unless an agent actually performs the downstream task.

**Completion criteria:**
1. Supported skill copies, global guidance, the OpenCode command, and integration docs consistently tell agents to keep a delivered-page ledger across query repair, retry the same failed page, continue only unread pages, bound retries, preserve lookup lineage, and verify current state live.
2. One anonymized deterministic replay exercises query repair, search-result continuation, expansion continuation, and retry without duplicate or missing delivered content.
3. The replay reports searches, unique candidates, exact repeats, expansions, returned characters, latency, required evidence recovered, and an honest navigation/presentation measurement label.
4. Focused regression coverage captures empty and boundary pages, stale revisions, retry exhaustion, missing/forgotten/unauthorized sources, Unicode and escaped text, lineage, and ledger idempotence through caller-facing surfaces or deterministic replay adapters.
5. The roadmap and shipped guidance agree, focused and affected tests pass, known failures are rerun, the full non-slow suite passes once, and clean-context result review has no unresolved findings.

**Requirement baseline:**
{"source":"roadmap/features/fix-session-history-evidence-access.md#6-tighten-retry-guidance-and-run-the-end-to-end-replay","outcome":"Update all supported Pallium-memory skill copies consistently so agents reuse lookup lineage, remember completed source pages during query repair, continue unread pages, bound retries, and separate a historical recap from live verification. Re-run one anonymized deterministic version of the observed recap.","scope":"Guidance and deterministic end-to-end replay for Session History retry, continuation, cost, and required-evidence recovery.","constraints":"Default to deterministic fixtures and zero paid model calls; do not add production retrieval-model work; report the measured layer honestly; preserve visibility, forgetting, and historical-versus-live-state semantics.","completion_criteria":"The anonymized replay reports exact-repeat and expansion cost before and after without claiming candidate recovery, injection precision, or downstream task effect unless measured; documentation, skill templates, roadmap state, and shipped contract agree."}

**Risk:**
Elevated.

**Complexity:**
Moderate.

**Reason:**
Agent Redline classifies the integration guidance paths as gray and the docs, evals, tests, and roadmap as blue, with no boundary violation or mandatory checkpoint. The change synchronizes several guidance surfaces and adds a deterministic multi-step replay, but deliberately avoids production code.

**Discovery:**
- Existing MCP contracts already provide frozen search paging (`result_offset`/`result_revision`), expansion continuation (`content_offset`/`content_revision`/`next_offset`), and `parent_lookup_id`; no production primitive is missing.
- All three installed skill copies are byte-identical and currently describe only one search followed by expansion. Global guidance, the OpenCode command, and integration docs likewise omit a delivered-page ledger, bounded repair/retry, unread-page continuation, and live verification.
- `evals/history_pull_decision/harness.py` performs one search and at most one expansion. Its current behavioral metrics do not measure query repair, paging, exact repeats, returned characters, latency, or required-evidence recovery.
- Existing caller-surface paging and diagnostics E2E coverage belongs to earlier slices. This slice should reuse those contracts and add only the missing deterministic caller-efficiency replay and guidance contracts.
- Redline pre-edit classification: `integrations/**` gray; `docs/**`, `evals/**`, `tests/**`, and `roadmap/**` blue; no API, persistence, security, runtime-config, watch-path, or dependency checkpoint applies. Gray paths must be explicit in the pull request.

**Material assumptions:**
1. Existing MCP paging and lineage contracts suffice. Disproved by a replay requirement that cannot be expressed through current search/expand inputs or outputs; if disproved, stop implementation and return to planning instead of changing production APIs in this slice.
2. Guidance fits existing byte ceilings. Disproved by the guidance budget test after removing redundant prose; if disproved, tighten wording rather than raising caps unless separately replanned.
3. A deterministic adapter can replay the navigation behavior without paid model calls. Disproved if task completion itself must be judged; if disproved, keep the report at navigation/presentation evidence and do not claim downstream-task effect.

**Plan:**
1. Add failing focused tests for the replay ledger, query repair, continuation, retry bounds, boundaries, lineage, duplicate/gap prevention, report fields/layer label, and synchronized guidance within existing budgets.
2. Implement the smallest deterministic replay state and driver inside the existing history-pull eval package, reusing current service search/expand primitives and avoiding production changes or new dependencies.
3. Update the three skill copies, generated/global guidance, OpenCode command, and integration docs in lockstep; retain all existing safeguards and byte ceilings.
4. Run focused tests while editing, affected Session History/eval tests after the coherent change, `--lf`, and the full non-slow suite once. Update roadmap slice 6 with exact measurement-layer wording only after evidence passes.
5. Obtain clean-context result review, resolve every finding, open a pull request that calls out gray integration paths, wait for required checks/reviews, merge, and verify the installed service only if runtime code or installed guidance deployment requires it.

**Verification plan:**
- Criterion 1: guidance-parity and byte-budget tests inspect every supported surface and assert ledger, bounded retry, continuation, lineage, and live-verification rules.
- Criteria 2–4: focused deterministic replay tests cover empty/one-hit/repeated-hit repair, failed-page retry, stale revision restart, multi-page expansion, exact/over-end offsets, Unicode/escaped content, missing/forgotten/unauthorized sources, retry exhaustion, parent lineage, idempotence, and no duplicate/gap; existing HTTP/MCP E2E tests remain the production caller-contract evidence.
- Criterion 3: serialize and assert the replay report fields and `navigation/presentation` label; reject candidate-recovery, injection-precision, and downstream-task-effect claims.
- Criterion 5: run the repository workflow check, focused tests, affected subsystem tests, `python -m pytest --lf --lfnf=none -q -n 0`, Import Linter, the full non-slow suite once, and clean-context exact-HEAD result review; record commands and outcomes below.
- Significant risk: inspect the final diff for production code, public signature, new dependency, visibility/forgetting, and retrieval-state changes. Any such change invalidates this plan and requires reclassification.

**Plan review:**
Pending clean-context agent review.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

No implementation yet. The machine-local `apply_patch` fallback, if needed, will be recorded here.

## Evidence

Pending.

## Result review

Pending.
