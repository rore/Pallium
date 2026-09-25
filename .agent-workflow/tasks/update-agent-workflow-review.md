<!-- agent-workflow:start -->
**Outcome:** Pallium's installed Agent Workflow consumers match upstream main at 7d6d46d without changing Pallium-specific governance decisions.

**Target:** Pallium repository.

**Scope:** Refresh both installed Agent Workflow skill trees and the mapped vendored checker from the pinned upstream distribution; add this Work Record.

**Constraints:** Preserve agent-workflow.yaml, agent-redline-policy.yaml, CI, CODEOWNERS, hooks/settings, AGENTS.md, existing documentation mirrors, Work Record history, and application behavior. No re-bootstrap or new dependency.

**Completion criteria:** Both installed skill trees and the mapped checker match the pinned upstream package; unrelated configuration remains unchanged; focused workflow checks, independent technical reviews, and PR CI pass.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Pallium's installed Agent Workflow consumers match upstream main at 7d6d46d without changing Pallium-specific governance decisions.","scope":"Refresh both installed Agent Workflow skill trees and the mapped vendored checker from the pinned upstream distribution; add this Work Record.","constraints":"Preserve agent-workflow.yaml, agent-redline-policy.yaml, CI, CODEOWNERS, hooks/settings, AGENTS.md, existing documentation mirrors, Work Record history, and application behavior. No re-bootstrap or new dependency.","completion_criteria":"Both installed skill trees and the mapped checker match the pinned upstream package; unrelated configuration remains unchanged; focused workflow checks, independent technical reviews, and PR CI pass."}

**Behavior changes:**
[]

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Installed .agents skill files are unclassified gray, setting an Elevated floor. Two skill consumers and a changed governance checker make this Moderate; no red-zone or application paths are intended.

**Discovery:** Upstream origin/main is 7d6d46d, newer than the last Pallium sync at fbe6c768. Its distribution changes six files: manifest, operating guidance, plan/result-review guidance, expanded Work Record template, and the checker. The new checker requires explicit independent agent technical review references for Elevated/High plans and Ready-for-review results.

**Material assumptions:** The pinned upstream dist tree is authoritative; a manifest/blob mismatch stops the sync. Existing Pallium policy and CI remain compatible; any required change outside the mapped consumers returns to planning.

**Plan:** 1. Invoke /agent-workflow to create this Work Record and classify risk before any consumer edit. 2. Verify the pinned upstream source and copy only the changed distribution files into both existing skill trees plus the mapped root checker. Preserve AGENTS.md and existing docs mirrors because their source template is unchanged and upstream upgrade guidance keeps mirrors intact. 3. Inspect exact diff and stop on unrelated or incompatible changes. 4. Run the repository test-plan selector, focused checker tests, source parity, Redline/Workflow gates, independent agent plan/result reviews, and PR CI.

**Verification plan:** Installed consumers match pinned upstream → normalized file-list/content parity and source blob verification. Unrelated governance configuration is unchanged → exact diff and schema compatibility. New review contract works in Pallium → focused checker tests and PR Agent Workflow/Redline jobs. Final change passes required validation → test-plan report and PR CI.

**Plan review:** Pending independent agent technical review.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Planning only. Branch `feat/update-agent-workflow-review` in isolated worktree; consumer edits await independent plan review.
