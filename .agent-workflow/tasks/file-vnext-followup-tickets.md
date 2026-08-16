# file-vnext-followup-tickets

Files two backlog tickets surfaced during vNext work and adds them to the board. First
PR to exercise the `.agent-workflow/**` blue-list fix (#27) — all-blue diff → Routine.

<!-- agent-workflow:start -->
**Outcome:**
Two follow-up tickets exist under `roadmap/ideas/` and are listed on the board:
(1) reconcile the two conflicting unprompted-pull/direction signals; (2) fix the redline
self-protection path so `agent-redline-policy.yaml` is actually self-protected.

**Target:**
Pallium — `roadmap/` workspace (ticket files + board index). Docs only.

**Scope:**
Add `roadmap/ideas/idea-reconcile-unprompted-pull-direction-signal.md` (already drafted),
add `roadmap/ideas/fix-redline-self-protection-path-mismatch.md` (new), and add both slugs
to `roadmap/board.md`. No code, no policy, no test changes.

**Constraints:**
- No product/internal/external system names in the tickets.
- Do NOT fix the self-protection gap itself here — this only FILES the ticket for it.

**Completion criteria:**
Both ticket files present and valid; both slugs on the board under Ideas; CI green.

**Risk:** Routine

**Complexity:** Simple

**Reason:** —

**Approach:**
Keep the drafted direction-signal ticket; draft the self-protection ticket following the
same frontmatter shape (id/title/status/priority/commitment); add both slugs to
`board.md` Ideas. Roadmap docs only.

**Verification:**
Minimap/board consistency by inspection; CI: agent-workflow, redline (expect all-blue →
Routine), test lanes (trivially pass — no code touched).

**State:** Ready for review
<!-- agent-workflow:end -->
