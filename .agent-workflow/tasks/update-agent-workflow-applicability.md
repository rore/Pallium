<!-- agent-workflow:start -->
**Outcome:**
Pallium uses the current local agent-workflow distribution, with every installed integration artifact reconciled and the new bootstrap applicability capability evaluated explicitly.

**Target:**
Pallium repository on `feat/update-agent-workflow-applicability`.

**Scope:**
Refresh `.claude/skills/agent-workflow/`, vendored workflow/redline scripts, Claude hooks/settings, OpenCode plugin, checkpoint docs, the AGENTS marker block, and the existing CI workflow from `C:\Dev\rore\agent-workflow` at `0a5cb06`; propose `roadmap/` alone for the new applicability block; correct the stale Redline self-protection path and close its roadmap item.

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
Source `C:\Dev\rore\agent-workflow` is clean at `0a5cb06`; Pallium started from `origin/main` at `9c11b537`. The new release adds documentation-only applicability with fail-closed path/risk/protection checks, an OpenCode workflow plugin, a new checkpoint-doc layout, and checker/workflow changes. Pallium is already installed, so bootstrap mode forbids destructive re-bootstrap and directs a tracked operating-mode re-vendor. Bootstrap discovered `roadmap/`, `docs/`, and `README.md`; only `roadmap/` matches Pallium's existing narrow exception. GitHub reports default branch `main`, classic protection false, and no applicable rulesets. Policy drift exists: the self-protection red path names `agent-policy.yaml`, not the live `agent-redline-policy.yaml`.

**Material assumptions:**
The committed `dist/agent-workflow/` is the authoritative install source; disprove with package/manifest failure, then stop and repair the source package rather than hand-copying. Existing Pallium workflow and policy adaptations remain authoritative; if the upstream template requires a conflicting semantic change, return to planning. Documentation-only applicability is optional and requires explicit approved paths; without approval, omit it. Direct-default permission additionally requires explicit approval plus live proof that the default branch is unprotected; otherwise keep it false.

**Plan:**
1. Re-vendor the complete skill tree and supported scripts from one source revision; add the packaged OpenCode plugin; reconcile hooks/settings and only the AGENTS marker block with upstream helpers. 2. Replace the stale flat `docs/agent-workflow/*.md` mirror with `docs/agent-workflow/checkpoints/*.md` plus `docs/agent-workflow/skill-feedback.md`; refresh Redline reference docs and schema without leaving duplicate instructions. 3. Preserve Pallium's Python 3.12, import-linter, boundary-report, test, suppressions, guarded-path, and settings adaptations while updating CI to feed the same trusted merge-base-to-head NUL path set to Redline and the checker. 4. Correct only the policy's stale `agent-policy.yaml` self-protection entry and align `fix-redline-self-protection-path-mismatch` plus the board. 5. Present one inert applicability choice: approve `roadmap/` as Work-Record-exempt; separately approve direct-default eligibility, currently supported by live `main` protection=false and rules=[]. Do not add `docs/` or `README.md`. Generate the config fragment only through the new checker with strict NUL proposal/approval files. 6. Validate manifest/schema parity, doc links, idempotent merges, plugin syntax/behavior, fail-closed applicability, local Redline/checker behavior, affected repository tests, and diff hygiene. Stop on source-package inconsistency, protection ambiguity, unexpected application files, or broader policy drift.

**Verification plan:**
When refreshed, every installed packaged file shall match its manifest/source revision → manifest size/hash inventory and no-index diff. When applicability is configured or omitted, unapproved/risky/governance paths shall still require normal workflow → vendored checker applicability probes with NUL path inputs and Redline verdicts. When hooks/plugins run, existing settings and Pallium instructions shall remain intact → idempotent installers plus focused script/plugin checks. When CI/governance files change, Pallium shall retain its custom boundary and workflow behavior → inspect diff, run Redline/checker locally, schema validation, and affected repository tests. Before handoff, final diff shall have no unresolved independent-review findings → clean-context result review.

**Plan review:**
Clean-context architecture review recorded below; initial findings addressed in the revised scope/plan, re-review pending.

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

Clean-context architecture review: changes requested before implementation; the overall re-vendor approach is sound and needs no application-code change.

- Refresh the complete pinned distribution, installed checker/reporter/comment renderer, hook helpers, OpenCode plugin, and copied reference/schema artifacts only where upstream differs. Preserve Pallium's Python 3.12 CI, import-linter adapter and boundary-report wiring, binding boundary violations, shadow defaults, suppressions, guarded paths, settings, and all AGENTS text outside its marker block. Do not replace CI/config/policy with generic templates or copy the source repository's `python -m core.checker` invocation into Pallium.
- Make CI reconciliation explicit: both jobs must use a trusted PR merge base to the real head with `git diff --name-only -z --no-renames`, feeding the same complete path evidence via `--changed-files-z` to Redline and the vendored checker. Retain existing tests and independent boundary checks. Config needs no change if applicability is declined. Correct the policy's stale `agent-policy.yaml` self-protection entry to `agent-redline-policy.yaml` under this architecture-reviewed scope; preserve other classifications except separately approved governance alignment.
- Name the reference-doc layout migration in the plan: current flat `docs/agent-workflow/*.md` must be reconciled with the new `docs/agent-workflow/checkpoints/` layout and sibling `docs/agent-workflow/skill-feedback.md`. Validate links and avoid retaining stale duplicate instructions. The existing broken feedback link is already recorded in `codex-fix-vector-source-only-starvation.md`. If the self-protection fix ships, align the queued `roadmap/ideas/fix-redline-self-protection-path-mismatch.md` and its board state; that roadmap alignment is presently absent from the target scope.
- Present discovered `roadmap/`, `docs/`, and `README.md` as distinct inert choices, recommending only `roadmap/` for the minimal rollout matching Pallium's existing roadmap-only exception. Existing permission to push roadmap updates does not establish a Work Record exemption or authorize a docs/README expansion. Broad `docs/` includes installed harness instructions, testing conventions, architecture/decision documents, and normative designs; before proposing it for approval, explicitly classify those governance surfaces red/watch or narrow the ordinary-documentation candidates. The checker's built-in exclusions do not recognize all Pallium-specific names. README currently falls through to gray and needs blue alignment if approved; roadmap/docs already have broad blue entries.
- The single `directDefaultBranchAllowed` value applies to every approved path. Do not combine docs/README candidates with `true` while claiming to preserve roadmap-only direct-main permission. The reported live `main protected=false` and applicable `rules=[]` support only an unprotected-status finding, assuming successful checks against the actual resolved default branch; they are not approval. Record the separate direct-default decision, use strict NUL proposal/approval inputs and only the checker-emitted fragment, and require fresh runtime protection checks. Preserve existing AGENTS permission; any expansion or change to its surrounding prose must be explicitly included in the approved plan.
- Verification should cover the exact copied-file manifest and schema parity, doc links, idempotent hook/AGENTS merges, plugin syntax/behavior, and focused fail-closed applicability cases: approved-only, mixed/risky/governance, missing/duplicate/malformed evidence, rename endpoints, unicode, symlink/junction, absent risk data, and protected/unavailable default branch. Reuse upstream checks where possible; avoid a new local harness. No protection-setting mutation or destructive re-bootstrap is warranted.

Readiness blockers: make the concrete path/default-branch proposal and the two scope refinements above explicit, resolve any resulting policy/AGENTS conflict, and record required human approval. No additional architectural redesign is needed.

### Re-review

Approved for presentation to the human. The revised scope and plan resolve the architecture-review findings: they name the checkpoint-doc migration, self-protection correction and roadmap alignment, preserve Pallium-specific integrations, require complete NUL path evidence, and limit the proposed exemption to `roadmap/`. No plan-review blocker remains. Human approval is still required before implementation; the optional Work Record exemption and direct-default setting require their separately recorded decisions before configuration. Live protection evidence establishes eligibility only, with fresh runtime checks still required. Keep the initial review's focused verification cases as acceptance criteria.

## Result review

Pending.
