<!-- agent-workflow:start -->
**Outcome:** The installed managed Pallium guidance for Codex and Claude exactly reflects merged commit `c419981b` while every user-authored and unrelated section remains byte-preserved.

**Target:** Pallium local Codex and Claude integrations.

**Scope:** Update only the managed Pallium blocks in `C:\Users\I347041\.codex\AGENTS.md` and `C:\Users\I347041\.claude\CLAUDE.md`; record this rollout in this Work Record.

**Constraints:** Use the stable merged source and a supported guidance-only updater when available. Preserve user cost/model/Relay bullets and all unrelated text. Do not contact `relaydev` or `workflow-dev`, create Claude sessions, change hooks/settings/trust, restart services/hosts, or rerun behavior tests.

**Completion criteria:** The two installed managed blocks match their merged emitted base guidance exactly; before/after evidence proves hooks and trust unchanged, user/unrelated text preserved, and actual installed sizes reported.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Clean-context redline classified the Work Record blue and external global instruction files gray, with no boundary, red zone, contract surface, or checkpoint. Elevated because global instructions affect every local agent; simple because only two managed blocks may change.

**Discovery:** Pending supported-updater and installed-state inspection.

**Material assumptions:** A supported updater can replace guidance without mutating hook definitions, trust, settings, or services; if not, stop and report its exact side effects before execution. Managed markers are unique and user additions are outside them; otherwise stop without writing.

**Plan:** Pending discovery and clean-context review; no installation action is authorized until both are complete.

**Verification plan:** Exact managed-block equality → compare normalized emitted merged blocks with installed marker spans. Preservation → hash and diff all text outside managed markers before/after. No hook/trust/settings mutation → snapshot relevant definitions and trust state before/after. No service restart → perform no service operation. Installed sizes → measure final managed blocks directly.

**Plan review:** Pending clean-context review after discovery.

**Approvals:** Not required at this risk level; user explicitly requested local rollout.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-15: Created isolated branch `feat/rollout-merged-global-guidance` from merged `origin/main` commit `c419981b`. Applicability is non-exempt because global agent instructions and a Work Record are outside the documentation-only allowlist. Clean-context pre-edit redline returned GRAY with no boundary, checkpoint, or contract finding.

## Plan review

- Pending discovery.

## Evidence

- Pending.

## Result review

- Pending.
