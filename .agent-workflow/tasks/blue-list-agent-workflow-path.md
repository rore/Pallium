# blue-list-agent-workflow-path

Adds `.agent-workflow/**` to the redline **blue** zone so a task's own Work Record file
(pure workflow bookkeeping) stops defaulting to gray and forcing every task — even a doc
typo — to detect as Elevated.

<!-- agent-workflow:start -->
**Outcome:**
`.agent-workflow/**` is classified blue in `agent-redline-policy.yaml`, so a change whose
only non-blue path is its own Work Record no longer detects as gray/Elevated. A
genuinely-blue task (e.g. an evals-only or docs-only change) can classify Routine again.

**Target:**
Pallium — `agent-redline-policy.yaml` (redline zone config; governance file).

**Scope:**
Add one `.agent-workflow/**` entry to the `zones.blue` list in `agent-redline-policy.yaml`.
No change to red/watch zones, boundaries, modes, or any other path.

**Constraints:**
- Do NOT alter any red-zone entry, boundary contract, or the `modes`/`default: shadow`.
- Do NOT touch the (separately-noted) `agent-policy.yaml` vs `agent-redline-policy.yaml`
  self-protection naming gap — out of scope.
- The change only reclassifies Work Record bookkeeping; it must not blue-list any
  code/runtime/persistence surface.

**Completion criteria:**
`.agent-workflow/**` appears under `zones.blue`; a Work-Record-only diff no longer yields a
GRAY redline verdict; existing redline/CI checks pass.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** `agent-redline-policy.yaml` is a governance file (its header declares itself
red-zone → architecture-review), and the WR path currently defaults to gray → Elevated.
Per the redline→Risk table a red/gray touch that is NOT a contract/security/persistence/
financial surface maps to Elevated (not High). Complexity Simple: one list entry.

**Discovery:**
`.agent-workflow/**` matches no red or watch glob in `agent-redline-policy.yaml`, so it
falls through to the gray default — confirmed empirically on PR #26, whose only gray path
was its Work Record file, forcing Routine→Elevated. Blue already covers comparable
bookkeeping/non-runtime trees (`docs/**`, `roadmap/**`, `scripts/**`, `tests/**`,
`evals/**`); a Work Record is strictly less risky than those. User explicitly approved
this change ("Blue-list .agent-workflow/** - yes"). Separately observed (NOT fixed here):
the red self-protection entry is `path: "agent-policy.yaml"` but the real file is
`agent-redline-policy.yaml`, so the policy file may not actually be self-protected — a
governance gap worth its own ticket.

**Material assumptions:**
- ASSUMPTION: `.agent-workflow/**` currently has no higher-priority (red/watch) match, so
  adding it to blue cleanly reclassifies it. DISPROVED BY: redline still returning gray/
  watch for a WR-only diff after the change. ACTION IF DISPROVED: inspect glob precedence
  in the redline engine and adjust.
- ASSUMPTION: blue is the correct zone (no checkpoint) for WR bookkeeping. DISPROVED BY: a
  reviewer arguing WRs warrant cautious review. ACTION: keep gray and instead fix the
  agent-workflow checker's risk mapping — but that is a larger change.

**Plan:**
Add a single entry to `zones.blue` in `agent-redline-policy.yaml`:
`- path: ".agent-workflow/**"` with a reason noting it is Work Record bookkeeping /
workflow metadata, not a code or runtime surface. Nothing else changes.

**Verification plan:**
- Reclassification works → after the edit, a Work-Record-only diff produces a non-gray
  redline verdict (validated by this PR's own redline job: its non-blue paths are the WR +
  the policy file; the WR should now be blue).
- No unintended zone change → clean-context reviewer confirms the diff adds exactly one
  blue entry and touches no red/watch/boundary/mode.
- CI: redline, agent-workflow, test(3.12/3.13), windows-smoke.

**Plan review:** Clean-context Explore subagent — see `## Plan review` below.

**Approvals:** Not required at this risk level (Elevated). User approved the change in
conversation ("Blue-list .agent-workflow/** - yes").

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Added `- path: ".agent-workflow/**"` to `zones.blue` in `agent-redline-policy.yaml`
  (lines 108-109). YAML re-parsed clean; red (16) and watch (9) zones untouched. Verified
  `.agent-workflow/` holds only `tasks/*.md` (Work Record markdown) — no config/hooks/
  executable content, so the `**` glob is exactly WR bookkeeping.

## Plan review

Clean-context Explore subagent (read-only; read the WR and diffed the working-tree
`agent-redline-policy.yaml` against `HEAD~1`). **Verdict: correctly scoped, correct, and
safe to apply.**

1. **Scope — OK.** Diff adds exactly one blue entry (+2 lines) and nothing else; no
   red/watch/boundary/modes/default touched. Policy edit fully isolated from the WR commit.
2. **Correctness — OK.** Blue (no checkpoint) is right — `.agent-workflow/` is pure Work
   Record markdown, strictly less risky than the already-blue `docs/**`/`roadmap/**`/`scripts/**`.
3. **Unintended breadth — OK.** Dir contains only `tasks/*.md` + a README today; nothing
   risky. Forward-looking note: `**` is recursive, so future non-doc content under
   `.agent-workflow/` would inherit blue — none exists now.
4. **YAML validity — OK.** Entry at lines 108-109 under `blue:`, correct indentation,
   well-formed.
5. **Governance note — CONFIRMED (out of scope).** The red self-protection entry is
   `path: "agent-policy.yaml"` but the real file is `agent-redline-policy.yaml`, so the glob
   does NOT match — this policy file is not actually self-protected, which is also why it
   falls through to gray. Deferred to a follow-up ticket (see WR Discovery).
