<!-- agent-workflow:start -->
**Outcome:**
Pallium uses the current local agent-workflow distribution, with every installed integration artifact reconciled and the new bootstrap applicability capability evaluated explicitly.

**Target:**
Pallium repository on `feat/update-agent-workflow`.

**Scope:**
Refresh `.claude/skills/agent-workflow/`, vendored workflow/redline scripts, Claude hooks/settings, OpenCode plugin, checkpoint docs, the AGENTS marker block, and the existing CI workflow from `C:\Dev\rore\agent-workflow` at `0a5cb06`; inspect and propose only the new `agent-workflow.yaml` applicability block and any required policy alignment.

**Constraints:**
Preserve Pallium-specific CI, Redline, and agent instructions; never overwrite existing config/policy wholesale; do not touch application code or the three user-owned dashboard screenshots; direct-to-main and documentation-only exemptions require separate explicit approval and must fail closed.

**Completion criteria:**
Installed artifacts match the current source package where intended; new applicability behavior is either approved and validated or explicitly declined; existing Pallium adaptations remain intact; manifest/schema/hook/plugin/checker/Redline checks pass; the final diff receives independent result review.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
The update changes repository-wide governance and the CI enforcer, including a large checker refresh and new applicability/OpenCode surfaces. Clean-context Redline classification requires architecture review; no application import-boundary risk was found.

**Discovery:**
Source `C:\Dev\rore\agent-workflow` is clean at `0a5cb06`; Pallium started from `origin/main` at `9c11b537`. The new release adds documentation-only applicability with fail-closed path/risk/protection checks, an OpenCode workflow plugin, a new checkpoint, and checker/workflow changes. Pallium is already installed, so bootstrap mode forbids destructive re-bootstrap and directs a tracked operating-mode re-vendor. Policy drift exists: the self-protection red path names `agent-policy.yaml`, not the live `agent-redline-policy.yaml`.

**Material assumptions:**
The committed `dist/agent-workflow/` is the authoritative install source; disprove with package/manifest failure, then stop and repair the source package rather than hand-copying. Existing Pallium workflow and policy adaptations remain authoritative; if the upstream template requires a conflicting semantic change, return to planning. Documentation-only applicability is optional and requires explicit approved paths; without approval, omit it. Direct-default permission additionally requires explicit approval plus live proof that the default branch is unprotected; otherwise keep it false.

**Plan:**
1. Inventory current-versus-source artifacts and run the new bootstrap applicability discovery/protection probe without changing config. 2. Obtain clean-context architecture plan review, present the applicability proposal and governance plan, and record human approval before edits. 3. Re-vendor the complete skill tree and supported scripts from one source revision; add the packaged OpenCode plugin/checkpoint; reconcile hooks/settings and only the AGENTS marker block using upstream helpers. 4. Preserve and minimally adapt Pallium's CI/config/policy rather than replacing them; apply only separately approved applicability settings. 5. Validate manifest sizes, schemas, hook/settings/plugin behavior, vendored checker and Redline parity, focused applicability cases, repository workflow check, and diff hygiene. Stop on source-package inconsistency, protection ambiguity for direct-main, unexpected application files, or destructive policy drift.

**Verification plan:**
When refreshed, every installed packaged file shall match its manifest/source revision → manifest size/hash inventory and no-index diff. When applicability is configured or omitted, unapproved/risky/governance paths shall still require normal workflow → vendored checker applicability probes with NUL path inputs and Redline verdicts. When hooks/plugins run, existing settings and Pallium instructions shall remain intact → idempotent installers plus focused script/plugin checks. When CI/governance files change, Pallium shall retain its custom boundary and workflow behavior → inspect diff, run Redline/checker locally, schema validation, and affected repository tests. Before handoff, final diff shall have no unresolved independent-review findings → clean-context result review.

**Plan review:**
Pending clean-context architecture review.

**Approvals:**
Pending human approval after plan review.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Established the isolated branch, inspected the current/source installs, and completed a clean-context pre-edit Redline classification. No implementation files changed.

## Evidence

- Source revision: `0a5cb066a735b7ca6634c6c5ccb87fa1b28d86b5`.
- Target base: `9c11b5375f0703cafe6d69c32bd134508a4cf371`.

## Plan review

Pending.

## Result review

Pending.
