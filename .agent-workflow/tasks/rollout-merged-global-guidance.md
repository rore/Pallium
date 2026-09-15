<!-- agent-workflow:start -->
**Outcome:** The installed managed Pallium guidance for Codex and Claude exactly reflects merged commit `c419981b` while every user-authored and unrelated section remains byte-preserved.

**Target:** Pallium local Codex and Claude integrations.

**Scope:** Update only the managed Pallium blocks in `C:\Users\I347041\.codex\AGENTS.md` and `C:\Users\I347041\.claude\CLAUDE.md`; record this rollout in this Work Record.

**Constraints:** Use the stable merged source and a supported guidance-only updater when available. Preserve user cost/model/Relay bullets and all unrelated text. Do not contact `relaydev` or `workflow-dev`, create Claude sessions, change hooks/settings/trust, restart services/hosts, or rerun behavior tests.

**Completion criteria:** The two installed managed blocks match their merged emitted base guidance exactly; before/after evidence proves hooks and trust unchanged, user/unrelated text preserved, and actual installed sizes reported.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Clean-context redline classified the Work Record blue and external global instruction files gray, with no boundary, red zone, contract surface, or checkpoint. Elevated because global instructions affect every local agent; simple because only two managed blocks may change.

**Discovery:** Full `pallium setup codex` and `pallium setup claude-code` are unsuitable: they also reconcile MCP/config/hooks/readiness, reinstall skills, create state, probe the service, and may require restart. Existing tested helpers `_append_agents_md_block("base")` and `_append_claude_md_block("base")` replace only marker-bounded guidance. Dry-run replacement from stable commit `c419981b` found exactly one marker pair and base arm in each file, exact preserved prefix/suffix text, CRLF-only inputs, and expected blocks of Codex 2,859 chars / 404 words and Claude 2,858 / 404.

**Material assumptions:** A supported updater can replace guidance without mutating hook definitions, trust, settings, or services; if not, stop and report its exact side effects before execution. Managed markers are unique and user additions are outside them; otherwise stop without writing.

**Plan:** From stable isolated commit `c419981b`, snapshot the two guidance files plus Codex/Claude hook, settings, config, readiness, and trust files. Validate unique markers, base arms, exact helper previews, and preserved outside text. Invoke only the existing tested `_append_agents_md_block("base")` and `_append_claude_md_block("base")` helpers in one guarded process, retaining original bytes for rollback on failure; never call either full installer. Re-read and prove exact emitted blocks, preserved outside text, unchanged hook/settings/config/trust hashes and readiness state, then record actual sizes. Stop before writing on any snapshot or preview mismatch; restore originals if either helper fails.

**Verification plan:** Exact managed-block equality → compare normalized emitted merged blocks with installed marker spans. Preservation → hash and diff all text outside managed markers before/after. No hook/trust/settings mutation → snapshot relevant definitions and trust state before/after. No service restart → perform no service operation. Installed sizes → measure final managed blocks directly.

**Plan review:** Pending clean-context high-reasoning review; see `## Plan review`.

**Approvals:** Not required at this risk level; user explicitly requested local rollout.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-15: Created isolated branch `feat/rollout-merged-global-guidance` from merged `origin/main` commit `c419981b`. Applicability is non-exempt because global agent instructions and a Work Record are outside the documentation-only allowlist. Clean-context pre-edit redline returned GRAY with no boundary, checkpoint, or contract finding.
- 2026-09-15: Discovery rejected the full setup commands because they mutate surfaces explicitly frozen during relay wake investigation. The existing tested marker replacement helpers are guidance-only; a no-write preview confirmed unique markers, base arms, exact stable-source blocks, CRLF-only inputs, and preservation of all text outside each managed block.

## Plan review

- Pending clean-context review.

## Evidence

- Pre-rollout Codex readiness is `verified`; Codex-owned hook trust and MCP exposure remain `unknown` by the bounded public readiness API. Exact pre-rollout hashes are captured for both guidance files, Codex hooks/config/readiness, Claude settings, and Claude trust registry.

## Result review

- Pending.
