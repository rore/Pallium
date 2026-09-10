# Task: history-budget-4000-trial

<!-- agent-workflow:start -->
**Outcome:**
Decide whether increasing the agent-facing raw-history search response budget from 2,000 to 4,000 characters improves frozen-source retrieval-answer success without baseline losses, safety regressions, or more than 25% aggregate search-plus-expansion text growth.

**Target:**
pallium

**Scope:**
Current authorized phase: isolated workflow setup and a read-only feasibility inventory over a consistent local SQLite snapshot, with ignored artifacts under `.local/history-budget-4000-trial/`. If the inventory is approved: `app/mcp/server.py` (2,000 to 4,000 search response budget), focused history-presentation/MCP tests, `docs/reports/session-history-search-quality-study.md`, and `roadmap/features/improve-session-history-search-quality.md`. No merge, install, or service change.

**Constraints:**
Use 20 fresh independent tasks if credible: 16 answerable and 4 frozen-neighborhood negatives, excluding the prior development sample and reserved holdout. Deduplicate shared-source/task clusters before selection. Freeze gold from full sources before trial outputs; verify a 1,200-character answer can express every critical fact. Compare two separately graded contexts per task (10 results / 2,000 chars and 10 results / 4,000 chars) through search, up to three 2,400-character expansions, and answer/abstain. Retrieval alone never updates accessibility. Label results as downstream-task-effect. Preserve identity/security semantics and byte identity for already-fitting responses. No test-set tuning, resampling, or synthetic real evidence.

**Completion criteria:**
1. Feasibility inventory reports credible independent-task count, pressure/fitting split, source/gold volume, and revised model-token estimate before any grading.
2. If approved, contract tests pass; the candidate adds at least three answerable successes, loses zero baseline successes, and adds no safety or negative regression.
3. Aggregate search-plus-expansion text is at most 125% of baseline; otherwise reject the change and close without prompt/model tuning or another automatic study.
4. Evidence, report, roadmap, and Work Record agree; production remains unchanged unless a later PR is explicitly approved.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:**
`app/mcp/server.py` is a watched runtime surface, raising the eventual change above Routine. The implementation is one response-budget constant plus focused contract tests and evidence/document alignment; no red-zone, architecture, API, persistence, or security checkpoint is triggered.

**Discovery:**
- `_compact_history` in `app/mcp/server.py` is the shared packaging seam; the current search budget is 2,000 characters.
- The installed service was healthy at inventory start (`/health`, `/status`, `/debug/queue/health`; embedding provider OK and queue clean).
- The current report explicitly recommends keeping 2,000 characters, so accepted trial evidence must reconcile that claim rather than leaving docs/code drift.
- Prior comparison and reserved holdout identifiers are available in ignored study artifacts and must be excluded without opening holdout content.

**Material assumptions:**
1. Historical lookup events with a linked live user request and a frozen ten-source candidate set can support a fair paired packaging trial. Disproof: fewer than the required independent answerable/negative tasks survive exclusions and cluster deduplication. Action: report the largest credible set and the narrower decision it supports before execution.
2. Changing only the shared response budget preserves ranking, visibility, identity, and expansion behavior. Disproof: contract or parity checks show any semantic drift. Action: reject and close.
3. Two separately presented variants per task are sufficient for paired downstream grading when gold is frozen first. Disproof: answer-cap validation or reviewer audit shows the rubric cannot express/score critical facts. Action: stop before grading.

**Plan:**
1. Create the isolated branch/worktree and this Work Record; obtain clean-context risk classification.
2. Create one consistent paired SQLite snapshot with the repository helper; inventory eligible events after prior-sample/holdout exclusion and connected-component deduplication.
3. Return the count, pressure/fitting split, source/gold volume, and revised token estimate to the architect. Stop pending approval; do not grade.
4. If approved, freeze task selection and full-source gold, validate the answer cap, generate paired contexts, grade independently, and score the predeclared rule without tuning.
5. Only if the rule passes, apply the one-line budget change, add focused contract coverage, align report/roadmap, run the required tests and smart review, then open (but do not merge/install) a PR.

**Verification plan:**
- Selection independence → inventory artifact asserts all selected IDs are outside prior development and reserved holdout sets, and no two tasks share a deduplication component.
- Trial limits and parity → trial artifacts assert input/parity invariants, per-task answer limits, expansion limits, and actual character totals.
- Packaging contract → focused tests cover empty/default/max/over-budget packaging, Unicode, errors, and unchanged already-fitting output; run affected files, `--lf`, then the full suite once before review/PR.
- Review quality → clean-context smart review covers correctness, evidence claims, and redline/workflow output.

**Plan review:**
Pending after feasibility approval. Pre-edit risk classification completed 2026-09-10: Elevated/Moderate; `app/mcp/server.py` watched; no special checkpoint; docs conflict must be reconciled.

**Approvals:**
User approved architect-assigned work and PR creation. Architect approved only workflow setup and feasibility inventory at this checkpoint; grading, production edit, merge, and install are not yet approved.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Feasibility inventory in progress. Blocked on architect approval before grading or production edits.

