<!-- agent-workflow:start -->
**Outcome:** Agents encountering protected behavior tests preserve accepted product requirements instead of weakening tests to restore green.

**Target:** Pallium repository.

**Scope:** Add one concise protected-behavior rule to AGENTS.md; record this task here.

**Constraints:** Do not change tests, product behavior, Redline policy, CI, CODEOWNERS, or GitHub protection. Keep suite selection guidance in its README.

**Completion criteria:** AGENTS.md tells agents how to handle protected test failures and edits, including the exact task-owner approval rule for genuine requirement changes, without implying GitHub merge enforcement.

**Requirement baseline:**
{"source":"user request: let's do it","outcome":"Agents encountering protected behavior tests preserve accepted product requirements instead of weakening tests to restore green.","scope":"Add one concise protected-behavior rule to AGENTS.md; record this task here.","constraints":"Do not change tests, product behavior, Redline policy, CI, CODEOWNERS, or GitHub protection. Keep suite selection guidance in its README.","completion_criteria":"AGENTS.md tells agents how to handle protected test failures and edits, including the exact task-owner approval rule for genuine requirement changes, without implying GitHub merge enforcement."}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** AGENTS.md is an unclassified gray governance path, so Redline's gray-path floor makes this Elevated; the instruction-only edit is simple.

**Discovery:** The suite README already defines admission and local collection; the roadmap and behavioral-integrity checkpoint define per-path classification and task-owner approval for requirement changes. AGENTS.md lacks the immediate handling rule. The directory uses workflow protection with verification `test`, not GitHub merge enforcement.

**Material assumptions:** The request is only to add the short repo instruction; if implementation or policy changes prove necessary, stop and re-plan.

**Plan:** Add one bullet beside AGENTS.md's test rules, linking to the suite README. State failure handling and protected-path classification. A genuine requirement change needs exact before/after approval from the user as task owner; agent review is not a substitute. State that workflow evidence is not repository-authenticated and does not prevent a GitHub merge. Stop if the wording contradicts the existing policy.

**Verification plan:** AGENTS.md expresses the agreed handling rule without promising merge enforcement -> inspect the exact diff against the suite README, roadmap, and behavioral-integrity checkpoint; run the local Redline/Agent Workflow checks and PR `test` verification.

**Plan review:** Clean-context reviewer approved the revised plan (see below).

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Planned edit targets: AGENTS.md and this Work Record only. Discovery found no need to change the protected tests or policy.

## Plan review

Clean-context reviewer returned REVISE: name approval by the user as task owner for exact before/after requirement changes; avoid implying authenticated repository authority or GitHub merge prevention. Plan clarified before editing AGENTS.md.

Clean-context reviewer re-reviewed the revised plan and returned APPROVE: exact task-owner approval and workflow-only limits are clear; scope and verification align with policy.

Added only the planned AGENTS.md bullet; no protected tests or policy changed. The wording distinguishes suspected regressions from approved requirement changes and explicitly disclaims GitHub merge enforcement.

## Evidence

On branch feat/protected-contract-instructions, git diff --check passed; fresh Redline verdict was GRAY for AGENTS.md with behaviorContractChanges version 2 and no changed protected paths; Agent Workflow check with that verdict returned clean. Full repository suite: 5316 passed, 34 skipped, 2 xfailed (264.16s), exit 0. Test content is the current branch worktree based on cc789032; commit and PR CI remain to verify.
