# Session search roadmap alignment

Source request: `f6f93d93-a006-4d6c-a96c-fbc3e976e6a6`.

<!-- agent-workflow:start -->
**Outcome:** Session-search exploration evidence is durably captured, duplicate roadmap state is cleared, and strategy documents agree on the next investigation.

**Target:** Pallium.

**Scope:** Session History search-quality roadmap, optional-reranker idea, board/scope, and the two vNext strategy/execution documents.

**Constraints:** Preserve exact-work scope, validation-first sequencing, measurement invariants, and the uncommitted status of any model or search-engine choice.

**Completion criteria:** The documents describe one ordered candidate-preserving reranking hypothesis, retire the duplicate idea, and consistently place it before broader navigation/compression work.

**Risk:** Routine

**Complexity:** Simple

**Reason:** All intended paths are redline blue-zone documentation; no boundary, contract, watch, or checkpoint surface is touched.

**Approach:** Fold the exploration into the committed search-quality item, mark the redundant reranker idea superseded, update the board/scope, and reconcile stale strategy sequencing.

**Verification:** Inspect the final diff, search for contradictory “next” sequencing, and run the workflow/redline checks on the complete changed-file set.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Discovery confirmed that the production baseline is SQLite FTS5 plus optional USearch fused by RRF; the active search-quality feature already owns fusion/overfetch/limit investigation and a qualified paired runner.
- Redline pre-edit classification: BLUE for every intended path; no boundary findings, watch flags, or required checkpoints.
- Planned edits: `roadmap/features/improve-session-history-search-quality.md`, `roadmap/ideas/idea-optional-reranker-support.md`, `roadmap/board.md`, `roadmap/scope.md`, `docs/context/strategy-vnext.md`, and `docs/designs/015-vnext-historical-work-execution.md`.
- Implementation folded the exploration into the active feature as an ordered candidate-availability and fixed-candidate reranking hypothesis, moved the duplicate idea to Superseded, and aligned strategy/design sequencing. No implementation technology or production dependency was selected.
- `apply_patch` failed with Windows process-launch error 1327; edits used exact assertion-backed replacements limited to the planned files.

## Evidence

Verified against base revision `c326475fdb1e5e46733568c5a8d68aac9270bf85` plus the current seven-file working-tree diff:

- `git diff --check` passed.
- Focused roadmap searches confirmed one superseded board placement, the captured candidate-reranking hypothesis, and no stale immediate-navigation sequence.
- `agent-redline-report.py` classified the complete path set clean with no boundary findings or checkpoints.
- `agent-workflow-check.py --require-implementation-ready` passed every blocking predicate.
