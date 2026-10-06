# Relay waiting guidance

<!-- agent-workflow:start -->
**Outcome:** Agents waiting solely for independent Relay replies yield their turn instead of preventing idle wake.
**Target:** Packaged Pallium memory skills.
**Scope:** integrations/{codex,claude-code,opencode}/skills/pallium-memory/SKILL.md and this Work Record.
**Constraints:** Preserve useful work, critical operations, normal tool/native-subagent waits, hook claim/ACK ownership and delivery guarantees. No runtime, configuration or service changes.
**Completion criteria:** All three skills contain identical narrow guidance to finish independent work, record pending replies and continuation, then end the turn; prohibit Relay-only sleep/poll loops and receive workarounds while preserving normal waits.
**Requirement baseline:** {"source":"user:adeee562-552b-4921-bc96-205b482017aa","outcome":"Agents waiting solely for independent Relay replies yield their turn instead of preventing idle wake.","scope":"integrations/{codex,claude-code,opencode}/skills/pallium-memory/SKILL.md and this Work Record.","constraints":"Preserve useful work, critical operations, normal tool/native-subagent waits, hook claim/ACK ownership and delivery guarantees. No runtime, configuration or service changes.","completion_criteria":"All three skills contain identical narrow guidance to finish independent work, record pending replies and continuation, then end the turn; prohibit Relay-only sleep/poll loops and receive workarounds while preserving normal waits."}
**Risk:** Elevated
**Complexity:** Simple
**Reason:** Packaged skill paths are gray under the current policy; prose-only addition, no runtime behavior change.
**Discovery:** The three packaged Relay skill sections are identical. Skill paths are outside the documentation exemption. Busy recipients defer idle-only wake; guidance must not imply all delivery faults are waiting mistakes.
**Material assumptions:** Skills remain mirrored; verify byte parity. No runtime changes needed; stop if scope expands.
**Plan:** Invoke agent-workflow and classify before edits. Obtain independent plan review, add one identical Relay bullet to each skill, verify parity and whole-change selector checks, obtain independent result review, commit on the isolated branch.
**Verification plan:** Review text against completion criteria; compare all three skill files; git diff --check; scripts/test-plan.py --base origin/main and reported checks; workflow and Redline checks.
**Plan review:** Agent technical review: /root/relay_wait_review. Independent read-only review approved the proposed paragraph and verification scope, with no findings.
**Approvals:** Approved by user 2026-10-06: "ok, so let's add this".
**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation
Applicability: normal workflow because packaged agent instructions are outside the documentation-only allowlist. Independent plan review approved; no runtime changes planned.

Proposed bullet: When waiting solely for independent agents' Relay replies, finish useful work that can proceed without them, record pending replies and the next action, then end the turn so idle wake can deliver. Do not keep the turn active solely by sleeping or polling for replies, or call receive to work around hook delivery. Finish critical operations before yielding; normal tool and native-subagent waits remain valid. This guidance does not replace reliable delivery once idle.
