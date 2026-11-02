# Refresh reviewed Agent Workflow guidance

<!-- agent-workflow:start -->
**Outcome:** Existing Pallium skill consumers have the reviewed task-ownership and implementation-handoff guidance, with a reviewable repository change and explicit safe-adoption or deferral evidence.
**Target:** Existing Agent Workflow skill mirrors and their guidance consumers.
**Scope:** operating-mode.md, templates/checkpoints/plan-and-review.md and manifest.txt in the existing .agents/skills/agent-workflow and .claude/skills/agent-workflow mirrors, plus this Work Record. Ignored local backups and verification evidence support scoped consumer adoption.
**Constraints:** Guidance-only refresh from upstream c0d69150ca05cdfab7951f741c16f7a477c7630a, including PR #62. Preserve newer/local edits, dirty work, active assignments and task identities. No hook, checker, runtime, service, configuration, dependency, protected-contract or retrospective Work Record changes. Do not create an absent global installation. Defer active qualified/frozen consumers until their owner has a safe window.
**Completion criteria:** Both mirrors include the settled caller-visible handoff instruction and reviewed ownership/identity rules; manifests match the changed guidance sizes without altering other entries. Required governance, whitespace, privacy and projection checks pass. Safe canonical/installed consumers are verified through their actual installed paths; deferred consumers and reasons are explicit. Deliver the isolated repository change through the normal branch/PR workflow.
**Requirement baseline:**
{"source":"direct-user-authorized-consumer-refresh","outcome":"Existing Pallium skill consumers have the reviewed task-ownership and implementation-handoff guidance, with a reviewable repository change and explicit safe-adoption or deferral evidence.","scope":"operating-mode.md, templates/checkpoints/plan-and-review.md and manifest.txt in the existing .agents/skills/agent-workflow and .claude/skills/agent-workflow mirrors, plus this Work Record. Ignored local backups and verification evidence support scoped consumer adoption.","constraints":"Guidance-only refresh from upstream c0d69150ca05cdfab7951f741c16f7a477c7630a, including PR #62. Preserve newer/local edits, dirty work, active assignments and task identities. No hook, checker, runtime, service, configuration, dependency, protected-contract or retrospective Work Record changes. Do not create an absent global installation. Defer active qualified/frozen consumers until their owner has a safe window.","completion_criteria":"Both mirrors include the settled caller-visible handoff instruction and reviewed ownership/identity rules; manifests match the changed guidance sizes without altering other entries. Required governance, whitespace, privacy and projection checks pass. Safe canonical/installed consumers are verified through their actual installed paths; deferred consumers and reasons are explicit. Deliver the isolated repository change through the normal branch/PR workflow."}
**Relationships:** {"schema_version":1,"sources":null,"pull_requests":[]}
**Risk:** Elevated
**Complexity:** Moderate
**Reason:** Vendored agent-skill paths are gray and not documentation-exempt. The reviewed guidance affects task coordination; consumer copies may contain local changes, requiring narrow projection and guarded adoption.
**Discovery:** Upstream PR #62 defines accountable task ownership and supplied-identity/branch-guard boundaries; PR #63 adds recording settled caller-visible decisions before implementation handoff. Their merged revisions are 29c508a350942d2127c337655907fb02cc8cfdb0 and c0d69150ca05cdfab7951f741c16f7a477c7630a. Existing consumers lack these changes. Runtime/checker/configuration updates are outside scope. Read-only inventory found dirty canonical work and active qualification consumers; the global skill directory is absent.
**Material assumptions:** The immutable reviewed dist is the source, not newer unreviewed working-tree bytes. A three-way comparison can preserve independent consumer changes; any overlapping semantic conflict stops that target. Active qualification source hashes and publication guards must remain stable.
**Plan:** Invoke Agent Workflow, establish this identity and classify before guidance edits. In an independent isolated branch from current main, project only the two reviewed guidance changes into both existing mirrors, preserving unrelated content, then update only corresponding manifest size entries. Reuse upstream technical reviews for unchanged guidance, verify destination projection, run selected governance checks and review the exact diff. Prepare byte-guarded backups for safe consumer adoption; explicitly defer active/frozen consumers. Publish the isolated reviewed repository contribution without unrelated changes.
**Verification plan:**
Reviewed identity -> immutable upstream dist at the merged revision and exact reviewed source/merge references.
Narrow composition -> three-way/projection comparison, six intended mirror paths, only corresponding manifest entries, preserved local deltas.
Guidance behavior -> inspect installed handoff wording, one accountable owner, shared contributions versus independent deliveries, identity preservation and branch-guard limits.
Repository delivery -> current-base selector, required governance checks, risk/workflow check, whitespace/privacy review and exact PR scope.
Consumer adoption -> fresh byte guards, recoverable backups, readback through both installed mirror paths; explicit deferral where active source/qualification must remain frozen.
**Plan review:** Agent technical review: reuse upstream independent plan/result review for unchanged PR #62 guidance at reviewed head fb4bdef2b5a5a11d4a3e6fde5ccf7ad0e3ae6e63 and PR #63 at reviewed head 41e14efb697a5b8d6e70fc21b6e59c0bcb2acaf6. The manager reviews exact consumer projection and destination compatibility; new semantics or conflicts require disposition before expanding scope.
**Approvals:** The human explicitly requested consumer refresh after PR #63, including PR #62 ownership guidance, preserving local work and excluding hook/runtime/service/configuration changes. This is authority for this scoped guidance refresh and safe consumer adoption, not unrelated upgrades or service operations.
**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- The manager created an independent checkout from current public main so no existing consumer Git refs or active source qualification changed. Read-only inventory is complete. All application and unrelated dirty work remains preserved.
- Projected only the reviewed PR #62 identity/delegation hunks and PR #63 handoff instruction into both existing skill mirrors. Per manager disposition, preserved the checkout's current source-item lifecycle row verbatim; no other local guidance was replaced.

## Evidence

- Upstream contributions: https://github.com/rore/agent-workflow/pull/62 and https://github.com/rore/agent-workflow/pull/63. Exact private destination inventory and backups remain in ignored local evidence.
- Immutable inputs: base `00cf3a4cee15f1a276933c159552ac2e123f56c9`; reviewed dist `c0d69150ca05cdfab7951f741c16f7a477c7630a`, with hashes recorded in ignored `build/upstream-guidance-inputs/identity.json`. Projection preserves the local lifecycle row and changes only ownership/identity/delegation and handoff passages plus their two manifest sizes per mirror.
- Governance: `scripts/test-plan.py --base origin/main` selected governance-only checks. The selected test run with task-local `--basetemp` passed 46 tests; its sole failure was `test_selection_step_uses_trusted_policy_and_full_fallback` because sandboxed Git Bash could not create its MSYS namespace. Retrying only that node outside the sandbox passed (1 passed), reusing the other 46 results.
- Redline evidence: existing import-linter reporter exited 0; the repository Redline reporter produced `GRAY` advisory with no boundary violations, no API/schema/security/runtime-config changes, and no behavior-contract paths changed. `scripts/agent-workflow-runtime.ps1 codex check --repo-root . --slug refresh-agent-workflow-guidance` exited 0 / clean using the provided qualification interpreter.
- Final checks: `git diff --check` passed; both mirrors are byte-identical, lifecycle guidance is unchanged, manifest sizes match UTF-8 bytes, and the tracked diff contains only the six scoped mirror files. No public-content privacy disclosures found.
- Safe consumer adoption: both canonical and installed mirrors passed fresh all-file preimage and backup guards, scoped writes, exact readback, manifest-size checks, and ownership/handoff assertions. The installed consumer's newer lifecycle wording is preserved. Twelve guidance files were verified; no hooks, runtime, configuration, service, database, or Git refs changed. Exact before/after hashes and guarded rollback bytes remain in ignored local evidence.
- Deferred consumers: the incident developer's pinned full-suite input set and the publisher's immutable diagnostic source guard remain unchanged. Their existing owners will adopt at a safe boundary, without invalidating active evidence. The absent global package was not created. Installed text is verified; subsequent real-use adoption is not yet observed.

## Recovery

- Task identity: agent-workflow:refresh-agent-workflow-guidance. Branch: feat/refresh-agent-workflow-guidance. Preserve this checkout for repository delivery, review follow-up and the two deferred consumer adoptions. Safe canonical/installed adoption is verified; independently active consumers remain deferred.

## Result review

Agent technical review: reuse the unchanged independent upstream PR #62 review at `fb4bdef2b5a5a11d4a3e6fde5ccf7ad0e3ae6e63` and PR #63 review at `41e14efb697a5b8d6e70fc21b6e59c0bcb2acaf6`, incorporated by `c0d69150ca05cdfab7951f741c16f7a477c7630a`.

Reviewed revision: six-file consumer projection of that immutable reviewed distribution, with only unrelated local lifecycle wording retained and matching manifest sizes. The manager inspected the exact projection and both destination variants. The installed consumer has a newer lifecycle row, which its candidate preserves verbatim; the canonical candidate preserves its own row. No new semantics, scope, or risk were introduced by these independent retained rows.

Verification adequacy: the selected 47 governance outcomes pass, including the isolated elevated retry of the sandbox-denied test. The real Redline and workflow checks pass their required gates. Mirror equality, exact upstream projection, manifest sizes, privacy, and whitespace checks cover this guidance-only change; application tests are not selected. Byte-guarded backups and exact post-write readback verify the two safe consumers. Active developer qualification and diagnostic inputs remain deferred until their owners have a safe boundary. Readback establishes installed text, while real-use adoption remains to be observed.

Skill feedback trigger dropped: the test's sandbox namespace denial was a machine-local execution constraint, not an upstream guidance defect.
