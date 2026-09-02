<!-- agent-workflow:start -->
**Outcome:** Historical search is distinct, interpretable, and safe, and the real-corpus evaluator measures the exact search-plus-expansion context an agent received with correct historical time semantics.

**Target:** Pallium.

**Scope:** Historical lookup/expansion delivery telemetry, MCP history presentation, source-result diversity, real-corpus replay evaluation, focused public-surface E2E coverage, and aligned roadmap/docs.

**Constraints:** Work only in the isolated feature worktree; do not touch/restart the installed service or local integrations; preserve visibility/redaction/forgetting and retrieval-does-not-equal-use invariants; preserve response budgets; avoid schema/API expansion unless discovery proves it necessary; no provider calls before deterministic checks pass; paid rerun capped at 8 answer calls and 10,000 estimated input tokens with no model judge.

**Completion criteria:** Agent-visible search and expansion exposure is reconstructable exactly; historical and current replay modes cannot leak future replacements into as-of evaluation; duplicates do not consume visible top-K; current guidance and compact relevance/freshness cues are unambiguous; required HTTP/MCP lifecycle and edge-case E2E tests pass; the four-case private rerun is reviewed under its hard budget before any expansion decision.

**Risk:** TBD after pre-edit redline review.

**Complexity:** Large

**Reason:** Multiple independently verifiable runtime, retrieval, evaluation, and presentation outcomes must land together before the product gate is trustworthy.

**Discovery:** Pending.

**Material assumptions:** Existing persistence can represent exact delivered lookup/expansion exposure without a schema migration; invalidate if delivery ownership cannot update the existing event safely, then return to planning. Existing retrieval results expose enough deterministic information for compact relevance cues without a learned reranker; invalidate if not, then omit the cue rather than invent confidence. The four private cases and snapshot remain available locally; invalidate if missing or changed, then stop before paid rerun.

**Plan:** Pending discovery and required clean-context review.

**Verification plan:** Pending discovery.

**Plan review:** Pending.

**Approvals:** Pending risk classification.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-02: Established isolated task context on `codex/fix-real-corpus-memory-access-and-evaluation`; discovery and risk classification are pending before code edits.

## Evidence

- Roadmap source: `roadmap/features/fix-real-corpus-memory-access-and-evaluation.md`.

## Result review

- Pending.
