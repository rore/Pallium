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
Pallium is clean at current `main`; its last recorded agent-workflow source was `0a5cb06` and Minimap source was `06ac46d`. Agent-workflow `main` is clean at `8b428af` and adds native runtime guards, dual Claude/Codex skill discovery, three root runtime adapters, and revised hook/settings behavior. Minimap stable `main` is `b21e0a5`, a descendant of `06ac46d`; its checkout also has an unmerged `e9bae35` commit that is intentionally excluded. Current Pallium has only the Claude agent-workflow skill install; tracked `.claude/settings.json` contains the three prior plan-mode hooks and tracked `guarded-paths.json`, while `.codex/hooks.json` is absent and must be created by the new installer.

**Material assumptions:**
Committed upstream `main` distributions are the authoritative stable install sources; if either manifest/package is inconsistent or target tests expose a source defect, stop and fix upstream rather than patching vendored code. Existing Pallium configuration, policy, CI workflow, and non-owned hook entries remain authoritative; any required semantic change to them returns the task to planning.

**Plan:**
1. Use explicit source→destination maps pinned to agent-workflow `8b428af`: copy `dist/agent-workflow/**` byte-for-byte to both `.claude/skills/agent-workflow/**` and `.agents/skills/agent-workflow/**`; copy its checker and three runtime adapters to root `scripts/`; copy changed hook helpers to `.claude/hooks/`, the OpenCode plugin to `.opencode/plugins/`, checkpoint docs to `docs/agent-workflow/`, and reconcile only the marker-owned AGENTS section. Verify both install manifests independently and against the pinned source; preserve config, policy, CI, historical records, and consumer-relative doc links. 2. Run the pinned settings installer against explicit `.claude/settings.json` and new `.codex/hooks.json` targets. Preserve unrelated entries, assert the Claude sidecar still equals `agent-workflow.yaml` guarded paths, assert Codex creation does not affect that sidecar, and rerun both installers to a zero-diff state. Cover missing/malformed-config degradation with the upstream installer tests rather than adding consumer-only logic. 3. Export only `package/minimap/skills/minimap-roadmap/**` from the pinned Minimap tree object `b21e0a5`, replace the target skill, and compare it recursively to that exported tree; never copy from the source checkout's current `e9bae35` HEAD. 4. Verify JSON and script syntax; exercise representative seed/guard payloads through the copied runtime adapters including the Windows PowerShell wrapper; assert root hook commands target root runtime scripts; run focused Pallium workflow tests, local Redline/workflow checks, then the required full Pallium test run. Stop on source-package inconsistency, unexpected non-owned settings changes, application paths, or config/policy/CI drift.

**Verification plan:**
When installed, both agent-workflow skill trees shall match the pinned `8b428af` manifest and each other → per-target manifest inventory and recursive byte comparison. When hooks are reconciled, explicit Claude/Codex installer targets shall contain portable seed/guard registrations without losing unrelated entries → before/after semantic comparison, guarded-path sidecar assertion, upstream degradation tests, and zero-diff second runs. When runtime hooks execute, root adapters shall handle representative seed/guard payloads on Python, shell, and Windows surfaces → upstream runtime-guard tests plus direct copied-adapter probes and command-target inspection. When Minimap is refreshed, Pallium's roadmap skill shall match the exported `b21e0a5` tree exactly → recursive byte comparison and syntax/package checks. When the branch is ready, governance and application behavior shall remain intact → Redline/checker, focused `tests/test_agent_workflow_ci.py`, then `python -m pytest tests/ -x -q`.

**Plan review:**
Clean-context review approved after the six initial blockers were resolved; recorded below.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- Established the isolated branch and completed read-only discovery. No implementation files changed.
- Clean-context Redline classification: gray overall, no boundary risk or policy checkpoint; mapped to Elevated/Moderate.

## Evidence

- Agent-workflow source: `8b428afbe51003bf1e7ac9f7ed8ba08821a03376`.
- Minimap stable source: `b21e0a5a8f7cedb96d3e64ef6b44cb4b42d87bc8`.

## Plan review

Initial clean-context review blocked on six gaps: correct the absent-versus-stale Codex baseline; specify additive installer preservation and idempotence; map every pinned source to each destination; cover Claude guarded-path sidecar behavior; exercise actual runtime adapter contracts including Windows; and export Minimap from `b21e0a5` rather than the checkout's unmerged HEAD. The revised Discovery, Plan, and Verification plan address all six without expanding into application, policy, CI, roadmap, installed-service, or unmerged Minimap scope. Clean-context re-review approved the amended plan with no remaining blockers.

## Result review

Pending.
