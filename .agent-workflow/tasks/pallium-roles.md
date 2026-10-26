# Pallium persistent roles

<!-- agent-workflow:start -->
**Outcome:** Three durable role guides select established ownership without adding mandatory agent processes.
**Target:** Pallium repository role guidance.
**Scope:** roles/mapping.yaml, roles/owner.md, roles/relay-developer.md, roles/session-history-developer.md, and this Work Record.
**Constraints:** Preserve existing work and names; no takeover, installations, service changes, permissions, or permanent reviewer role. Parent coordinates assignment acceptance.
**Completion criteria:** Three exact name mappings resolve to readable guides; guides capture agreed responsibilities and proven lessons without duplicating shared policies; focused validation and independent review pass.
**Requirement baseline:**
{"source":"work-record-initial","outcome":"Three durable role guides select established ownership without adding mandatory agent processes.","scope":"roles/mapping.yaml, roles/owner.md, roles/relay-developer.md, roles/session-history-developer.md, and this Work Record.","constraints":"Preserve existing work and names; no takeover, installations, service changes, permissions, or permanent reviewer role. Parent coordinates assignment acceptance.","completion_criteria":"Three exact name mappings resolve to readable guides; guides capture agreed responsibilities and proven lessons without duplicating shared policies; focused validation and independent review pass."}
**Risk:** Elevated
**Complexity:** Simple
**Reason:** roles/ is unclassified (gray); no runtime or protected behavior changes.
**Discovery:** AGENTS.md already loads persistent-agent-roles. Its installed setup reference defines a flat exact-name map with contained readable Markdown targets. Existing operations and lessons remain authoritative.
**Material assumptions:** Parent-confirmed @pallium-manager, @relaydev and @historydev names remain suitable. If ownership changes, parent revises assignment evidence before delivery. No runtime reads these files except agent guidance.
**Plan:** Create the four scoped role files. Map @pallium-manager to owner.md, @relaydev to relay-developer.md, and @historydev to session-history-developer.md. Keep responsibility-specific lessons in each guide; link existing AGENTS.md, operations and lessons. State roles are guidance, not permissions or mandatory separate sessions. Validate exact map, unique keys, contained files and links; run whole-change test selector and workflow checks. Stop on mapping conflict or scope expansion.
**Verification plan:**
- Mapping criterion -> parse YAML with duplicate rejection and verify exact keys, contained Markdown paths and readability.
- Content criterion -> independent review against user-agreed boundaries and referenced docs.
- Verification criterion -> git diff --check, test-plan selector and workflow/redline checks; run any required selected checks.
**Plan review:** Agent technical review: /root/roles_review, 2026-10-26, GO with no findings on the initial Work Record plan; relayed by parent before guide edits.
**Approvals:** Not required at this risk level. User requested defining the roles and assigning suitable agents.
**Exceptions:** —
**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Created isolated branch feat/pallium-roles at 701608cd; primary dirty checkout preserved. Independent plan review passed before role-file edits. The current test selector treats roles/ as unknown and requires the full suite; policy remains unchanged.

## Handoff

Parent verified acceptance: @historydev in turn 01a17838-5150-7390-b4ca-a0a8f04ae478, and @relaydev in turn 01a1783a-d3b5-7c91-a1f7-950aa03659e5. Owner self-name @pallium-manager verified. Mapping does not register or rename sessions.

No exact source-provider relationship references supplied to this child. The primary checkout's pending workflow refresh template includes Relationships, but this branch's checker does not support it; kept this note outside the structured block and left workflow files unchanged.

Worktree: C:/Dev/rore/Pallium/build/pallium-roles. Parent owns agent assignments and later delivery. No runtime changes authorized by this subtask.

## Evidence

- Mapping validation: three unique exact names, contained readable Markdown files, and all local links passed.
- Import boundaries passed; Redline classified the four role files gray with no required checkpoints.
- git diff --check passed. Whole-change selector chose full validation because roles/ is unknown.
- Full suite first failed before collection because sandbox temporary-directory creation was unavailable. The isolated xdist retry entered tests but produced no completion output for several minutes; interrupted only that owned process. Full serial run uses -n 0 and isolated build/roles-pytest-serial; result pending, not claimed passing.
- Workflow checker passed all predicates after using the branch-supported Work Record fields and explicit criterion-to-method lines.

## Result review

Agent technical review: /root/roles_review, content GO on 2026-10-26, conditional on required verification. Its stale pending-History-assignment finding is corrected above using parent-provided current acceptance evidence.
Reviewed revision: 701608cd plus the four new roles/ files; no application diff.
Verification adequacy: mapping and link checks pass; full suite is still running. Parent independently reviewed the guide content and found no additional issue.
