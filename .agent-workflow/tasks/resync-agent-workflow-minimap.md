<!-- agent-workflow:start -->
**Outcome:**
Pallium uses the current stable agent-workflow and Minimap packages without changing application behavior or weakening repository governance.

**Target:**
Pallium repository on `feat/resync-agent-workflow-minimap`.

**Scope:**
Refresh the installed agent-workflow skill, runtime adapters, hook settings, OpenCode plugin, consumer docs, and owned AGENTS marker from agent-workflow `main` at `8b428af`; refresh `.claude/skills/minimap-roadmap/` from Minimap `main` at `b21e0a5`; add the now-required identical `.agents/skills/agent-workflow/` install.

**Constraints:**
Preserve `agent-workflow.yaml`, `agent-redline-policy.yaml`, `.github/workflows/agent-workflow.yml`, historical Work Records, Pallium-specific instructions outside the owned AGENTS marker, and all third-party hooks. Do not touch application code, roadmap state, `Pallium-installed`, or Minimap's unmerged `e9bae35` branch.

**Completion criteria:**
Both agent-workflow skill installs match one source manifest and revision; installed host/runtime assets match the supported package while existing settings remain intact; Minimap roadmap skill matches stable source `main`; focused integration checks, workflow/redline gates, and Pallium tests pass.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Redline classifies the new `.agents` install plus hook, settings, plugin, and AGENTS integration surfaces as gray; scripts/docs are blue and `.claude/skills/**` is excluded. The task spans two upstream packages and several runtime integrations, with no application boundary risk.

**Discovery:**
Pallium is clean at current `main`; its last recorded agent-workflow source was `0a5cb06` and Minimap source was `06ac46d`. Agent-workflow `main` is clean at `8b428af` and adds native runtime guards, dual Claude/Codex skill discovery, three root runtime adapters, and revised hook/settings behavior. Minimap stable `main` is `b21e0a5`, a descendant of `06ac46d`; its checkout also has an unmerged `e9bae35` commit that is intentionally excluded. Current Pallium has only the Claude agent-workflow skill install and stale Claude-shaped registrations in `.codex/hooks.json`.

**Material assumptions:**
Committed upstream `main` distributions are the authoritative stable install sources; if either manifest/package is inconsistent or target tests expose a source defect, stop and fix upstream rather than patching vendored code. Existing Pallium configuration, policy, CI workflow, and non-owned hook entries remain authoritative; any required semantic change to them returns the task to planning.

**Plan:**
1. Copy the complete agent-workflow distribution from `8b428af` into both `.claude/skills/agent-workflow/` and `.agents/skills/agent-workflow/`; refresh the checker, three runtime adapters, changed root Claude hook helpers, OpenCode plugin, consumer checkpoint docs, and only the marker-owned AGENTS section. Preserve configuration, policy, CI, historical records, and consumer-relative doc links. 2. Run the new settings installer for Claude and Codex, preserving third-party entries and removing only the obsolete agent-workflow Claude commands currently misplaced in `.codex/hooks.json`; verify a second run is a no-op. 3. Replace `.claude/skills/minimap-roadmap/` from Minimap stable `main` at `b21e0a5`; do not include the unmerged list-card ordering commit. 4. Verify manifest sizes and byte parity, JSON and script syntax, installer idempotence, Minimap package parity, focused Pallium workflow tests, local Redline/workflow checks, then the required full Pallium test run. Stop on source-package inconsistency, unexpected non-owned settings changes, application paths, or config/policy/CI drift.

**Verification plan:**
When installed, both agent-workflow skill trees shall match the `8b428af` manifest and each other → manifest inventory plus byte comparison. When hooks are reconciled, Claude and Codex shall contain the new runtime registrations without losing unrelated entries → JSON inspection, installer rerun, and runtime-focused tests. When Minimap is refreshed, Pallium's roadmap skill shall match `b21e0a5` exactly → recursive byte comparison and syntax/package checks. When the branch is ready, governance and application behavior shall remain intact → Redline/checker, focused `tests/test_agent_workflow_ci.py`, then `python -m pytest tests/ -x -q`.

**Plan review:**
Pending clean-context review.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Established the isolated branch and completed read-only discovery. No implementation files changed.
- Clean-context Redline classification: gray overall, no boundary risk or policy checkpoint; mapped to Elevated/Moderate.

## Evidence

- Agent-workflow source: `8b428afbe51003bf1e7ac9f7ed8ba08821a03376`.
- Minimap stable source: `b21e0a5a8f7cedb96d3e64ef6b44cb4b42d87bc8`.

## Plan review

Pending.

## Result review

Pending.
