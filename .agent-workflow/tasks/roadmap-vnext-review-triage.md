# roadmap-vnext-review-triage

Triage of the external vNext code + product review into roadmap state: verify every code finding against
source (done via three clean-context passes), reopen P1 · Reuse Measurement, and create/promote tickets
carrying the reviewer's full Definition-of-Done. Docs-only (roadmap markdown); no code, no guarded paths.

<!-- agent-workflow:start -->
**Outcome:**
P1 · Reuse Measurement is reopened and populated with all verified review findings (security defects,
measurement repair, retrieval quality, product-validation), each ticket carrying the reviewer's DoD; the
cross-cutting release gate is recorded; P2/P3 stay parked and gated.

**Target:**
`roadmap/board.md` and `roadmap/ideas/*.md` in the Pallium repo. No production code.

**Scope:**
- Reorder `board.md`: reopen P1, promote existing product ideas, keep P2/P3 parked.
- Add new idea tickets for review items 1–9 + 14; reopen `idea-reuse-judge-calibration`.
- Backfill the reviewer's full DoD (items 10, 11, 13, cross-cutting) into promoted tickets.

**Constraints:**
- Roadmap markdown only — no code, no guarded paths.
- Board lines must be headers or `- item` only (no comment lines — parser rejects them).
- No internal/product names.

**Completion criteria:**
Board parses cleanly in minimap; P1 lists the 14 items; new/updated tickets exist with the reviewer's
DoD captured; CI (agent-workflow + redline) green.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Docs-only roadmap markdown; no guarded/red paths touched → (Routine, Simple).

**Approach:**
Verify findings via clean-context subagents, then edit roadmap files directly; split from any code branch
so this PR is docs-only.

**Verification:**
Minimap board renders without parse errors; `gh pr checks` agent-workflow + redline green on PR #37.

**State:** Ready for review
<!-- agent-workflow:end -->
