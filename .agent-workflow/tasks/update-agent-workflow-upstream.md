<!-- agent-workflow:start -->
**Outcome:** Pallium's installed Agent Workflow consumers match upstream main at fbe6c768b05a9afe60c623d2dfbb42db2ce6ff72 without changing Pallium-specific governance decisions.

**Target:** Pallium repository.

**Scope:** Refresh both installed Agent Workflow skill trees, their existing vendored scripts/schema, and the owned Agent Workflow AGENTS marker from the pinned upstream distribution; inspect but preserve existing doc mirrors; add this Work Record.

**Constraints:** Preserve agent-workflow.yaml, agent-redline-policy.yaml, the live CI workflow, CODEOWNERS, unrelated hooks/settings, Work Record history, and application behavior. No re-bootstrap or new dependency.

**Completion criteria:** Both skill installs and mapped consumer assets match the pinned upstream package; unrelated configuration is unchanged; focused workflow/Redline checks and PR CI pass.

**Requirement baseline:**
{"source":"source_item_id:5686f4fa-37de-41c8-b40f-26f449b52d68","outcome":"Pallium's installed Agent Workflow consumers match upstream main at fbe6c768b05a9afe60c623d2dfbb42db2ce6ff72 without changing Pallium-specific governance decisions.","scope":"Refresh both installed Agent Workflow skill trees, their existing vendored scripts/schema/doc mirrors, and the owned Agent Workflow AGENTS marker from the pinned upstream distribution; add this Work Record.","constraints":"Preserve agent-workflow.yaml, agent-redline-policy.yaml, the live CI workflow, CODEOWNERS, unrelated hooks/settings, Work Record history, and application behavior. No re-bootstrap or new dependency.","completion_criteria":"Both skill installs and mapped consumer assets match the pinned upstream package; unrelated configuration is unchanged; focused workflow/Redline checks and PR CI pass."}

**Behavior changes:**
[{"target":"task-context.scope","classification":"equivalent","before":"Refresh both installed Agent Workflow skill trees, their existing vendored scripts/schema/doc mirrors, and the owned Agent Workflow AGENTS marker from the pinned upstream distribution; add this Work Record.","after":"Refresh both installed Agent Workflow skill trees, their existing vendored scripts/schema, and the owned Agent Workflow AGENTS marker from the pinned upstream distribution; inspect but preserve existing doc mirrors; add this Work Record.","reason":"Upstream upgrade guidance explicitly keeps existing docs/agent-workflow mirrors intact; the installed skill remains the authoritative updated guidance."}]

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Clean-context Redline review classified the consumer sync GRAY because installed skill trees, the governance schema, and AGENTS marker are unclassified; scripts/docs are blue and the Claude skill tree is excluded. Several mapped consumers and compatibility checks make this Moderate.

**Discovery:** Upstream origin/main is fbe6c768 (2026-09-25), newer than Pallium's last verified Agent Workflow sync at c355df09. The source archive matches all 67 blobs of that exact commit and its 66-entry manifest. The package adds proportionality and behavior-integrity guidance. Pallium already has the reporter, runtime adapters, schema, and hooks; normalized deltas remain in both skill trees, the checker, and the owned marker. Upstream explicitly preserves existing docs/agent-workflow mirrors on upgrade. Pallium's live CI workflow has local adaptations and is not a byte-copy target. The sole open PR (#236) first committed its Work Record with a Requirement baseline, satisfying the new checker migration rule.

**Material assumptions:** The committed dist/agent-workflow tree at fbe6c768 is authoritative; a manifest/blob mismatch stops the sync. Existing Pallium config/policy/CI remain compatible; a required semantic change outside the mapped consumer scope returns to planning. Existing docs mirrors, unrelated settings/hooks, and non-owned AGENTS text must remain unchanged.

**Plan:** 1. Invoke /agent-workflow to create this Work Record and classify risk before any code edit. 2. Export pinned upstream dist; replace both complete existing skill trees and only the changed existing mapped scripts/schema. Keep the existing docs mirrors intact per upstream upgrade guidance. Reconcile only the owned AGENTS marker using the upstream helper; run official settings installers only if a changed hook registration requires them. 3. Inspect exact diff; stop on unexpected files, manifest mismatch, or config/CI incompatibility. 4. Verify source parity after Git newline normalization, script syntax, schema compatibility, focused consumer tests, fresh Redline/Workflow checks, independent result review, and PR CI. Preserve existing live CI rather than copying its template.

**Verification plan:** When synced, both skill trees and mapped assets shall match the pinned upstream package after Git newline normalization → file-list and content parity. When helpers run, unrelated settings/hooks/instructions shall remain unchanged → before/after diff and idempotence. When the new checker/reporter run on Pallium, existing config and policy shall remain valid and gates shall pass → focused tests, local Redline/Workflow checks, and PR CI.

**Plan review:** Clean-context Sol review found no CI incompatibility and requested exact-commit archive provenance plus preservation of the docs mirror; both are addressed below.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Discovery and pre-edit Redline classification complete. Upstream source archive verified against all 67 commit blobs; schemas accept Pallium config/policy. Clean-context review conditions are resolved before consumer edits.


## Plan review

Reviewer checked the mapped consumer scope and CI CLI compatibility. The archive has no Git metadata, so all 67 files were verified against upstream commit blobs; Windows core.autocrlf=true requires newline-normalized destination comparisons. Upstream bootstrap guidance says to preserve, not refresh, existing docs mirrors; the plan now does so. Local checks will use the repository's existing Python 3.11+ executable via PYTHON.
