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
**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Created isolated branch feat/pallium-roles at 701608cd; primary dirty checkout preserved. Independent plan review passed before role-file edits. The current test selector treats roles/ as unknown and requires the full suite; policy remains unchanged.

## Handoff

Parent verified acceptance: @historydev in turn 01a17838-5150-7390-b4ca-a0a8f04ae478, and @relaydev in turn 01a1783a-d3b5-7c91-a1f7-950aa03659e5. Owner self-name @pallium-manager verified. Mapping does not register or rename sessions.

No exact source-provider relationship references supplied to this child. The primary checkout's pending workflow refresh template includes Relationships, but this branch's checker does not support it; kept this note outside the structured block and left workflow files unchanged.

Worktree: C:/Dev/rore/Pallium/build/pallium-roles. Parent owns agent assignments and delivery through draft PR https://github.com/rore/Pallium/pull/360. Retain this worktree for validation evidence and PR completion. No runtime changes authorized by this subtask.

## Evidence

- Mapping validation: three unique exact names, contained readable Markdown files, and all local links passed.
- Import boundaries passed; Redline classified the four role files gray with no required checkpoints.
- git diff --check passed. Whole-change selector chose full validation because roles/ is unknown.
- Full suite first failed before collection because sandbox temporary-directory creation was unavailable. The isolated xdist retry and full serial retry (-n 0) stalled without completing a test. Interrupted only those owned processes; no tests were skipped or changed.
- A single bounded diagnostic of tests/behavior_contracts/test_codex_busy_wake.py::test_busy_queue_recovery_stays_single_flight_and_competing_hook_blocks_overtaken_wake with -n 0 -o faulthandler_timeout=30 showed a stall at line 98: Starlette TestClient starts an AnyIO portal, whose asyncio Windows event-loop initialization blocks in socket._fallback_socketpair -> socket.accept. This is before the request executes; no application assertion failed. The underlying environment cause remains unproven. The diagnostic process was stopped after recording the trace in build/roles-stall-diagnostic.log. Full validation remains incomplete.
- Workflow checker passed all predicates after using the branch-supported Work Record fields and explicit criterion-to-method lines.
- Hosted run 40325252126: Python 3.13 reported failures in unchanged test_claude_wake_registration.py::test_prompt_cleanup_retries_real_wake_and_relay_transition (cleanup list empty instead of git:old/repo) and test_claude_wake_dispatch.py::test_crash_after_claim_idle_stop_rewakes_actual_claude_hook_once (503 relay_busy). These results are not dismissed as flaky or attributed to the role files without evidence.
- On the user's merge request, reran required full non-slow validation outside the sandbox with the existing qualified Python 3.13.14 interpreter: python -m pytest tests/ -x -q -n 0 --basetemp build/roles-pytest-elevated. Isolated data only; no live changes. Result: 1 failed, 807 passed, 2 skipped, 487 deselected, 1 xfailed in 212.32s. The socket startup limitation cleared. The first actual failure is unchanged tests/test_claude_wake_dispatch.py::test_persisted_claude_d1_d2_d3_actual_hooks at line 1289: actual injected scope includes extra work_ref=git-branch:feat/pallium-roles, absent from the expected dictionary. Log: build/role-tests-elevated.log. No application/test changes or repeat full run were made; environment/branch metadata leakage is a hypothesis, not a verified root cause.

## Result review

Agent technical review: /root/roles_review, content GO on 2026-10-26, conditional on required verification. Its stale pending-History-assignment finding is corrected above using parent-provided current acceptance evidence.
Reviewed revision: 86f201c2 role content, based on 701608cd; no application diff.
Verification adequacy: mapping, link, import-boundary and workflow checks pass; required full validation is blocked by the actual failure and hosted failures above. Parent independently reviewed the guide content and found no additional issue. Do not claim merge readiness. Next action: parent resolves validation failure or obtains required CI evidence before delivery; no application debugging added to this role-definition change.
