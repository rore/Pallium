# Simplify manager and architect guidance

<!-- agent-workflow:start -->
**Outcome:**
Manager and architect guidance makes simplification a primary responsibility while preserving required guarantees and checks.

**Target:**
Pallium role guidance.

**Scope:**
roles/manager.md, roles/architect.md and this Work Record.

**Constraints:**
Keep model defaults, permissions, workflow gates, independent-review rules and environment safeguards unchanged. No application, runtime, mapping, imported-skill or external-repository changes. Publication and conditional normal merge are authorized by the task owner's whole-fix-list direction. Use source-only local checks and existing hosted governance; no local application tests, installation or restart as part of this guide edit.

**Completion criteria:**
Both role guides prioritize simple code/process, reuse/deletion, concrete justification for added machinery and bounded simplification follow-up, without weakening required behavior, safety or verification.

**Requirement baseline:**
{"source":"direct-user-request","outcome":"Manager and architect guidance makes simplification a primary responsibility while preserving required guarantees and checks.","scope":"roles/manager.md, roles/architect.md and this Work Record.","constraints":"Keep model defaults, permissions, workflow gates, independent-review rules and environment safeguards unchanged. No application, runtime, mapping, imported-skill or external-repository changes. No commit, push, installation or restart.","completion_criteria":"Both role guides prioritize simple code/process, reuse/deletion, concrete justification for added machinery and bounded simplification follow-up, without weakening required behavior, safety or verification."}

**Relationships:**
{"schema_version":1,"sources":[],"pull_requests":[]}

**Behavior changes:**
[{"target":"task-context.constraints","classification":"requirement-change","before":"Keep model defaults, permissions, workflow gates, independent-review rules and environment safeguards unchanged. No application, runtime, mapping, imported-skill or external-repository changes. No commit, push, installation or restart.","after":"Keep model defaults, permissions, workflow gates, independent-review rules and environment safeguards unchanged. No application, runtime, mapping, imported-skill or external-repository changes. Publication and conditional normal merge are authorized by the task owner's whole-fix-list direction. Use source-only local checks and existing hosted governance; no local application tests, installation or restart as part of this guide edit.","reason":"The task owner renewed authority to finish the existing fix list with minimal overhead, rather than seek repeated routine publication and merge approval.","impact":"Releases normal publication and merge of the existing documentation-only guide contribution; no runtime, permission or required-check change.","alternatives":"Do not create another task, repeat unchanged technical review or run application tests for role prose.","authority":{"scope":"task","name":"task-owner"},"approval":{"by":"user","reference":"Direct task-owner whole-fix-list continuation, 2026-11-14","verbatim":"we said you don't need extra approvals, you need to find the shortest way with minimal overhead and complications to get our list fixed and merged and aligned into local"}}]

**Risk:** Routine

**Complexity:** Simple

**Reason:**
The complete scope is covered by explicit blue zones for top-level role Markdown and Work Records. The change strengthens existing simplification practice without changing authority, policy or required checks.

**Approach:**
Add a short primary objective to the manager guide and concrete simplification duties to both existing guides. Adapt the supplied core-role examples without importing their project-specific rules or creating shared guides, checklists or approval stages.

**Verification:**
Review the exact diff against the requested principles and unchanged safeguards; run source-only content assertions, git diff --check, the whole-change validation selector and Agent Workflow compliance checks. Application tests are not needed for this guidance-only change and remain outside the existing execution allowance.

**State:** Ready for review
<!-- agent-workflow:end -->

## Plan and discovery

1. Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit. Completed before editing either role guide.
2. Update only the two existing guides with concise, role-specific simplification rules.
3. Verify the diff, preserve safeguards and report source/adoption evidence separately from publication.

The supplied examples emphasize simple code and process, proactive deletion/reuse, avoiding unnecessary handoffs and approval loops, concrete need for added layers, and follow-up in existing records. Their unrelated architecture, delivery and environment policies are not part of this change. Self plan review is sufficient at Routine/Simple. There is no assigned roadmap item for this direct guidance request.

## Initial source-preparation recovery (historical)

Branch: `chore/simplify-manager-architect-roles`. Baseline: `744f113f4191f9c7d90ce19f5282031b4f975bce`. No commit or push is authorized. Keep this isolated checkout for the unpublished change. Native pre-edit prevention is unverified/degraded; no guard qualification is claimed.

## Implementation and evidence

Added one primary-objective paragraph and one follow-up bullet to the manager guide, plus two simplification bullets to the architect guide. Existing model defaults, permissions, independent-review requirements and environment safeguards are unchanged. No new guide, review gate or application behavior was added.

- Exact diff review and source-only content assertions passed for the requested principles and preserved safeguards. `git diff --check` passed with only existing line-ending conversion warnings.
- The whole-change selector included both modified guides and this untracked record. It selected the governance lane and its three governance test files, not application tests. The reported pytest command was not run because the existing local-execution restriction remains in force.
- The default shell had no Python launcher. Selecting an existing virtual-environment interpreter backed by an already-installed physical interpreter allowed source-only selector/checker execution without changing configuration, installing anything or importing the application.
- Agent Workflow parsed this compact record and baseline successfully, but returned blocking because required Redline evidence was absent. The actual reporter was then attempted on the selector's complete NUL-separated changed-path list. It refused because the configured import-boundary report was absent. No result was fabricated, no policy was weakened and no application/test execution was started to bypass that hold.
- The manager adopted the new emphasis under the direct user instruction. The standing architect read both draft guides and explicitly accepted reuse/deletion, minimal process, concrete justification and bounded follow-up while preserving authority and verification. This is observed session adoption, not merged, packaged or installed guidance. Private coordination evidence remains outside tracked files.

## Initial result review and next action (historical)

Self review found the source change meets the requested guidance scope without changing authority or required behavior. Verification remains incomplete: generate the genuine boundary/Redline evidence and run the selected governance checks only through an authorized execution path before publication. State is Blocked for those validation requirements, not for applying the user's simplification instruction or continuing independent product work. No commit, push or service operation has occurred. Retain this checkout for that specific unpublished change and validation follow-up.

Skill feedback trigger 2 dropped: the user's correction concerns this team's working emphasis, not an Agent Workflow defect. Missing launchers and local evidence prerequisites are environment/consumer state, not grounds for an upstream report.

## Real-use correction

Accepted implementation and review work later waited on already-sent coordination while Relay delivery was pending. Native session readback exposed the wait, and the authorized native channel carried the same approval/addendum without changing scope. Corrected the manager's existing approval-carrying rule to require that fallback and resumed-work verification rather than repeated status endings. This captures observed coordination friction, not a new permission, reviewer or exception to uncertain-operation safety. The draft guidance remains unpublished and its original validation limits remain.

The user also explicitly directed that unrelated or noncritical tests must not block the change. Corrected the existing manager acceptance rule to disclose and disposition those failures without adding delivery gates, weakening required checks or calling failed CI passed. This is failure-disposition guidance, not permission to skip protected assertions, bypass required platform checks or execute held tests.

Actual hosted execution later found a new test double whose positional target parameter was named the same as a real keyword flag. Static parsing and source review had missed the binding collision. Corrected the architect's existing caller-contract review rule to check doubles against actual positional/keyword calls and distinguish syntax evidence from runtime behavior. No new review stage, framework or execution permission is introduced.

The user then corrected repeated per-fix approval requests after authorizing the whole bounded fix queue. Clarified the manager's existing approval-carrying rule: drive routine fixes through review, approved testing, publication and merge under that queue authority. Preserve explicit execution limits, live-environment approvals and protected-behavior checkpoints. This removes duplicate requests; it grants no new permission and leaves this separate draft's validation/publication state unchanged.

The user also corrected continued use of a completed handoff packet as an active log. Clarified the manager's existing ownership rule: ongoing progress belongs in the owning Work Records and roadmap; handoff packets are transfer snapshots. Stop updating the completed packet. No new tracker or deletion is needed.

The user directed that Pallium/Relay dogfooding findings from any session or project reach the Pallium manager and enter the existing fix list. Extend only the manager's existing triage duty in this draft: deduplicate reports, generalize private reproductions, record expected/actual behavior and evidence in the owning Pallium roadmap item or Work Record, and keep suspected causes distinct from observed failures. This does not authorize public disclosure, cross-project data access, automatic fixes or live changes. Cross-project reporting requires shared session guidance outside this task's repository-only scope; no global configuration or maintained skill is changed here. Draft validation/publication remains incomplete as recorded above.

## Authorized publication continuation

The task owner's renewed whole-list instruction above supersedes the original source-only publication hold. The earlier failed checks remain historical evidence, not passed checks. Fast-forwarded this isolated branch to accepted main `479b9aa2db8fdd5ee872fdc9bfadf5c941bdb52e` while preserving all three existing dirty/untracked task files. The source scope and Routine/Simple classification remain unchanged. Reuse the previously observed architect adoption for unchanged guidance; review only the added manager clarifications. Complete genuine static/governance validation, normal publication and merge without an extra routine approval or reviewer. No application execution, maintained-package edit, client reload, cleanup or new tracker is part of this task.

Current result review: the exact three-path scope, whitespace and whole-change selector passed. The selector chooses governance only: `tests/test_test_plan.py`, `tests/test_ci_workflow.py` and `tests/test_agent_workflow_ci.py`. These tests were not run locally; ordinary hosted PR CI supplies them. Reused the genuine import-linter receipt SHA256 `341ee0af66997863e05ba32563dacef54980dfe6e64d7ce3e889973982b72103` from the accepted PR403 governance evidence, after checking every import root, policy and relevant configuration is identical. Redline and Workflow now return clean exit 0 with no blocking predicate. The original baseline is unchanged and the current constraint change has an exact task-owner authority chain. Local no-history checks are not commit-history evidence; run the supported adapter on the real publishing commit and retain any advisory. Self review confirms no changed model default, permission, independent-review rule, safety requirement or maintained package. Only source/static verification is claimed before hosted checks complete. State advances to Ready for review; normal publication/merge and separate manager-owned local alignment follow.
