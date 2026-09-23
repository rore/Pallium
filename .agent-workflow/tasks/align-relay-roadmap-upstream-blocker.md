<!-- agent-workflow:start -->
**Outcome:** The Relay roadmap treats safe automatic activation of unloaded Codex Desktop tasks as an upstream Codex limitation, not unfinished Pallium reliability work.

**Target:** Pallium.

**Scope:** Update roadmap/features/add-wake-first-relay-delivery.md; retain this Work Record.

**Constraints:** Preserve the proven loaded/busy safe-turn path, uncertain-wake safety, and other runtime/platform work. Do not change Relay behavior or recommend codex exec resume/environment replay.

**Completion criteria:** RW-031 is closed as Pallium work, the supported pending-until-natural-turn behavior is explicit, and the roadmap names the upstream capability that would justify revisiting automatic unloaded-task activation.

**Requirement baseline:**
{"source":"user request 2026-09-23 and supplied research report","outcome":"The Relay roadmap treats safe automatic activation of unloaded Codex Desktop tasks as an upstream Codex limitation, not unfinished Pallium reliability work.","scope":"Update roadmap/features/add-wake-first-relay-delivery.md; retain this Work Record.","constraints":"Preserve the proven loaded/busy safe-turn path, uncertain-wake safety, and other runtime/platform work. Do not change Relay behavior or recommend codex exec resume/environment replay.","completion_criteria":"RW-031 is closed as Pallium work, the supported pending-until-natural-turn behavior is explicit, and the roadmap names the upstream capability that would justify revisiting automatic unloaded-task activation."}

**Risk:** Routine

**Complexity:** Simple

**Reason:** Clean-context redline classification: both intended files are blue; no boundary, API, schema, security, runtime-config, or checkpoint surface is touched.

**Approach:** Reconcile the current-status, remaining-work, readiness-track, and RW-031 incident text in the existing roadmap item. Keep the change documentation-only and avoid creating a new feature.

**Verification:** `git diff --check`; targeted text review of every RW-031/unloaded/automatic-recovery occurrence; Agent Workflow local check for this slug.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Pre-edit classification is Routine/Simple. Target files are this Work Record and `roadmap/features/add-wake-first-relay-delivery.md`; no product code or delivery contract changes are planned.

Reconciled RW-031 as closed Pallium work and an upstream Codex dependency, removed it from remaining Pallium work, preserved the natural-turn fallback and other runtime/platform qualification, and added the primary upstream issue/discussion references. `apply_patch` hit the documented Windows process-logon failure, so the roadmap edit used a narrowly scoped assertion-checked deterministic replacement.

## Evidence

- `git diff --check` passed.
- Targeted `rg` review found the closed/upstream status, supported fallback, exact researched versions, and references with no stale RW-031 open-work wording.
- `scripts/run-import-linter.py` produced a clean boundary report.
- `agent-workflow-check.py --slug align-relay-roadmap-upstream-blocker --redline-verdict build/redline-verdict.json` passed with Routine risk and no checkpoint.
