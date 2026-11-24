# Reuse shared cost routing in Pallium role guides

<!-- agent-workflow:start -->
**Outcome:** Pallium role guides reuse Collection's dispatch guidance and keep Pallium-specific responsibilities and safeguards.

**Target:** Pallium repository-local manager, developer, architect, and legacy owner guides.

**Scope:** `roles/manager.md`, `roles/developer.md`, `roles/architect.md`, `roles/owner.md`, and this Work Record.

**Constraints:** Preserve role mappings, approved session settings, independent review, test selection, and installed-change approval. Do not edit other worktrees, maintained skills, application code, or live configuration. Commit and push this change and merge it to main through the normal PR workflow. No new test campaign.

**Completion criteria:** Active guides have no fixed model or effort defaults and point to the shared routing rule. Pallium-specific responsibilities remain explicit. The unmapped owner guide remains as a compatibility pointer. Existing drafts remain intact.

**Requirement baseline:**
{"source":"direct task-owner authorization for the Pallium cost-guidance change","outcome":"Pallium role guides reuse Collection's dispatch guidance and keep Pallium-specific responsibilities and safeguards.","scope":"`roles/manager.md`, `roles/developer.md`, `roles/architect.md`, `roles/owner.md`, and this Work Record.","constraints":"Preserve role mappings, approved session settings, independent review, test selection, and installed-change approval. Do not edit other worktrees, maintained skills, application code, or live configuration. No commit, push, or new test campaign.","completion_criteria":"Active guides have no fixed model or effort defaults and point to the shared routing rule. Pallium-specific responsibilities remain explicit. The unmapped owner guide remains as a compatibility pointer. Existing drafts remain intact."}

**Behavior changes:**
[{"target":"task-context.constraints","classification":"requirement-change","before":"Preserve role mappings, approved session settings, independent review, test selection, and installed-change approval. Do not edit other worktrees, maintained skills, application code, or live configuration. No commit, push, or new test campaign.","after":"Preserve role mappings, approved session settings, independent review, test selection, and installed-change approval. Do not edit other worktrees, maintained skills, application code, or live configuration. Commit and push this change and merge it to main through the normal PR workflow. No new test campaign.","reason":"The task owner authorized publication of the role guidance.","impact":"Publish only the reviewed guidance and its Work Record; no live adoption or runtime change.","alternatives":"Keep the change local or open a PR without merging.","authority":{"scope":"task","name":"task-owner"},"approval":{"by":"user","reference":"Direct task-owner publication request","verbatim":"make sure the role changes are also pushed and get to main"}}]

**Relationships:**
{"schema_version":1,"sources":[],"pull_requests":[]}

**Risk:** Routine

**Complexity:** Simple

**Reason:** The intended paths are explicit blue zones. The change consolidates guidance without changing decisions, permissions, or required checks.

**Approach:** Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit. Reuse the Collection rule without copying it. Keep Pallium-specific duties, reconcile useful detail from the older draft, and reduce the unmapped compatibility guide without breaking its path.

**Verification:** Review the exact diff and live role mapping. Run whitespace, whole-change selection, scoped Redline and Agent Workflow, and the selected governance checks. No application suite for this guidance-only change.

**State:** Ready for review
<!-- agent-workflow:end -->

## Context

The isolated branch starts at `e2b55fbc`. The earlier dirty manager draft and
active stability tasks are in separate worktrees and remain untouched.
The legacy owner path is referenced by historical records and selector tests,
but no live role mapping points to it.

## Implementation

The manager, developer, and architect guides point to Collection for cost and
dispatch. Pallium-specific consultation, reviewer independence, test selection,
and installed-change rules stay in place. The former owner guide remains at
its existing path as a pointer. No session settings changed.

## Evidence

On `chore/pallium-role-cost-routing` at `e2b55fbc` plus the five-path working
diff, whitespace and role reference checks passed. Collection's tracked
coordination guide contains the linked dispatch rule. The selector chose
governance, and all 55 selected tests passed. The first Redline run produced
no verdict because the required boundary report was missing. After verifying
the existing report's digest and unchanged import graph inputs, Redline
returned BLUE with no violations or review checkpoints. Agent Workflow
returned clean. No application suite, live adoption, or rollout was attempted.

The separate stability work and earlier manager draft remain untouched.
