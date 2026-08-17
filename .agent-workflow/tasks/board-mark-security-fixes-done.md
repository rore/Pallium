# board-mark-security-fixes-done

Close the loop on the two merged security fixes: move `fix-source-forget-scope-authorization` (PR #38)
and `fix-source-expansion-visibility-enforcement` (PR #39) from P1 to Done on the board, and flip their
ticket status to `done`. Board-accuracy hygiene only — no code.

<!-- agent-workflow:start -->
**Outcome:**
The board and ticket frontmatter reflect reality: both merged security fixes are in Done (not lingering
in the active P1 list), so P1 shows only the remaining (unstarted) measurement/validation work.

**Target:**
`roadmap/board.md` + the two ticket files' `status:` frontmatter. No code.

**Scope:**
- board.md: move the two fixes from P1 to Done.
- fix-source-forget-scope-authorization.md, fix-source-expansion-visibility-enforcement.md: status → done.

**Constraints:**
- Roadmap markdown only. Board lines must be headers or `- item`. No internal/product names.

**Completion criteria:**
Board renders; both fixes under Done; ticket status=done; CI (agent-workflow + redline) green.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Docs-only status update; no guarded paths → (Routine, Simple).

**Approach:**
Edit board.md + two frontmatter lines on a branch; PR; merge when green.

**Verification:**
Minimap board renders; `gh pr checks` agent-workflow + redline green.

**State:** Ready for review
<!-- agent-workflow:end -->
