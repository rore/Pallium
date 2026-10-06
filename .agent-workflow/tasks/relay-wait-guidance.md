# Relay waiting guidance

<!-- agent-workflow:start -->
**Outcome:** Agents waiting solely for independent Relay replies yield their turn instead of preventing idle wake.
**Target:** Packaged Pallium memory skills.
**Scope:** integrations/{codex,claude-code,opencode}/skills/pallium-memory/SKILL.md, their references/wait.md files, and this Work Record.
**Constraints:** Preserve useful work, critical operations, normal tool/native-subagent waits, hook claim/ACK ownership and delivery guarantees. No runtime, configuration or service changes.
**Completion criteria:** All three skills contain identical narrow guidance to finish independent work, record pending replies and continuation, then end the turn; prohibit Relay-only sleep/poll loops and receive workarounds while preserving normal waits.
**Requirement baseline:** {"source":"user:adeee562-552b-4921-bc96-205b482017aa","outcome":"Agents waiting solely for independent Relay replies yield their turn instead of preventing idle wake.","scope":"integrations/{codex,claude-code,opencode}/skills/pallium-memory/SKILL.md and this Work Record.","constraints":"Preserve useful work, critical operations, normal tool/native-subagent waits, hook claim/ACK ownership and delivery guarantees. No runtime, configuration or service changes.","completion_criteria":"All three skills contain identical narrow guidance to finish independent work, record pending replies and continuation, then end the turn; prohibit Relay-only sleep/poll loops and receive workarounds while preserving normal waits."}
**Behavior changes:** [{"target": "task-context.scope", "classification": "equivalent", "before": "integrations/{codex,claude-code,opencode}/skills/pallium-memory/SKILL.md and this Work Record.", "after": "integrations/{codex,claude-code,opencode}/skills/pallium-memory/SKILL.md, their references/relay-waiting.md files, and this Work Record.", "reason": "Existing 3072-byte skill budget requires the same approved guidance in linked references; behavior and user scope stay unchanged."}, {"target": "task-context.scope", "classification": "equivalent", "before": "integrations/{codex,claude-code,opencode}/skills/pallium-memory/SKILL.md, their references/relay-waiting.md files, and this Work Record.", "after": "integrations/{codex,claude-code,opencode}/skills/pallium-memory/SKILL.md, their references/wait.md files, and this Work Record.", "reason": "Shorter reference filename fits the unchanged skill budget while preserving all old Relay wording."}]
**Risk:** Elevated
**Complexity:** Simple
**Reason:** Packaged skill paths are gray under the current policy; prose-only addition, no runtime behavior change.
**Discovery:** The three packaged Relay skill sections are identical. Skill paths are outside the documentation exemption. Busy recipients defer idle-only wake; guidance must not imply all delivery faults are waiting mistakes.
**Material assumptions:** Skills remain mirrored; verify byte parity. No runtime changes needed; stop if scope expands.
**Plan:** Invoke agent-workflow and classify before edits. Obtain independent plan review, add identical linked waiting guidance to each skill, preserve existing rules and size budget, verify parity and whole-change selector checks, obtain independent result review, commit and open a PR on the isolated branch.
**Verification plan:** Approved guidance and preserved safeguards -> independent text review and mirrored-file parity; skill budget -> tests/test_guidance_budget.py; whole change -> git diff --check, scripts/test-plan.py --base origin/main and reported checks, workflow and Redline checks.
**Plan review:** Agent technical review: /root/relay_wait_review. Independent read-only review approved the proposed paragraph and verification scope, with no findings.
**Approvals:** Approved by user 2026-10-06: "ok, so let's add this".
**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation
Applicability: normal workflow because packaged agent instructions are outside the documentation-only allowlist. Independent plan review approved. Added the identical bullet to all three packaged skills. Existing installed Codex and Claude skill files matched the original packaged text; applied only this paragraph and verified exact text parity. No service, settings, or runtime changes.

Proposed bullet: When waiting solely for independent agents' Relay replies, finish useful work that can proceed without them, record pending replies and the next action, then end the turn so idle wake can deliver. Do not keep the turn active solely by sleeping or polling for replies, or call receive to work around hook delivery. Finish critical operations before yielding; normal tool and native-subagent waits remain valid. This guidance does not replace reliable delivery once idle.

## Evidence
All three packaged skills are byte-identical and contain one waiting rule. git diff --check and import boundaries pass. Redline GRAY, no boundary violations. The whole-change selector requires the full non-slow suite for packaged skill paths; run in progress in build/validation.log.

## Result review
Agent technical review: /root/relay_wait_review
Reviewed revision: planned skill-only diff based on 525df5bbcdb845ccc0956046efe4f0fa5eafdea6.
Verification adequacy: independent review found no text findings; GO conditional on the selector-required full suite passing.

## Budget correction
The full suite found the existing 3072-byte SKILL.md budget exceeded (3526 bytes): 1 failed, 2347 passed, 2 skipped, 1 xfailed. Preserve the ceiling and move the approved paragraph to mirrored references/relay-waiting.md. Replace the existing send-status bullet with: "- Send=saved, not started; pending unconfirmed. `busy_queue`=capability, not busyness. For waiting or urgent handoff, see [Relay waiting](references/relay-waiting.md); do not resend." The reference retains the existing urgent-handoff advice and approved yielding paragraph. Await independent plan-delta review before editing skills.

Independent plan-delta review: /root/relay_wait_review approved the linked-reference layout with the unchanged size ceiling. Implemented mirrored references and preserved the existing urgent-handoff advice.

Final layout independently approved by /root/relay_wait_review: keep every existing Relay rule verbatim, shorten only the frontmatter capability description, and link references/wait.md directly under Relay. Exactly3072bytes per SKILL.md; no test ceiling or assertion changed.

Final focused verification: 13 passed (guidance-budget checks and both existing complete skill install/remove lifecycle tests). Mirrored SKILL.md and wait.md bytes match across all three runtimes; installed Codex and Claude copies match. Workflow checker CLEAN exit0; Redline GRAY with no boundary violations. Final full validation: 6141 passed, 34 skipped, 2 xfailed in 345.13 seconds (build/validation-final.log).

Completion: independent final-layout result review /root/relay_wait_review approved, conditional on the full suite; that condition is now satisfied. Ready for PR review. Worktree remains owned by this task for its open PR; no service or shared-clone changes.

## PR review correction
CodeRabbit4197862898 identified that OpenCode has durable next-turn delivery but no active wake (docs/agent-relay.md). Independent plan review /root/relay_wait_review approved qualifying idle wake as supported-path behavior and directing a normal recipient turn after current work finishes when wake is unsupported/deferred. Mirrored wait.md only; no runtime/test changes. Reuse the full6141 passing runtime baseline and rerun focused guidance/install checks plus fresh PR CI.
