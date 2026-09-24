<!-- agent-workflow:start -->
**Outcome:** Pallium's accepted behavior-contract directory is workflow-protected, so edits are visible and semantically classified without GitHub blocking a manual merge.

**Target:** Pallium.

**Scope:** In a separate policy PR after the dedicated RW-022 contract-test PR merges, add `behaviorContracts` in `agent-redline-policy.yaml` for `tests/behavior_contracts/**` with `protection: workflow` and `verification: test`. Reconcile the roadmap feature and board when activation is verified. Record evidence in this Work Record.

**Constraints:** No behavior checkpoint, CODEOWNERS, branch protection, branch-required status, dedicated CI job, production behavior change, or protection of broad existing test files. Do not claim unloaded Codex wake. Keep the contract path covered by the existing PR `test` job and combined Redline/Agent Workflow harness.

**Completion criteria:** The accepted contract directory exists from the preceding test PR; policy names only that directory, workflow protection, and the existing `test` verification; a protected-path edit is classified red with the expected workflow checks; hosted PR tests and the combined harness pass; roadmap state matches the activated policy.

**Requirement baseline:**
{"source":"roadmap/features/add-protected-behavioral-requirements-regression-suite.md","outcome":"Pallium's accepted behavior-contract directory is workflow-protected, so edits are visible and semantically classified without GitHub blocking a manual merge.","scope":"In a separate policy PR after the dedicated RW-022 contract-test PR merges, add `behaviorContracts` in `agent-redline-policy.yaml` for `tests/behavior_contracts/**` with `protection: workflow` and `verification: test`. Reconcile the roadmap feature and board when activation is verified. Record evidence in this Work Record.","constraints":"No behavior checkpoint, CODEOWNERS, branch protection, branch-required status, dedicated CI job, production behavior change, or protection of broad existing test files. Do not claim unloaded Codex wake. Keep the contract path covered by the existing PR `test` job and combined Redline/Agent Workflow harness.","completion_criteria":"The accepted contract directory exists from the preceding test PR; policy names only that directory, workflow protection, and the existing `test` verification; a protected-path edit is classified red with the expected workflow checks; hosted PR tests and the combined harness pass; roadmap state matches the activated policy."}

**Risk:** High

**Complexity:** Moderate

**Reason:** `agent-redline-policy.yaml` is a red-zone governance source with architecture-review. Activating workflow protection makes the chosen regression directory authoritative for future changes; a wrong path or verification linkage could silently undermine the desired protection. The config diff itself is small, but requires separate PR sequencing, synthetic classification checks, and roadmap reconciliation.

**Discovery:** The canonical roadmap specifies a dedicated test PR followed by a separate reviewed policy PR. The existing CI `test` job runs `tests/` on PRs, and the combined harness runs on PRs. Current Redline policy lists `tests/**` as blue and marks policy edits red with architecture-review; `behaviorContracts` overrides the protected directory. The initial selected RW-022 contract is in PR #242, with local tests and witness complete but hosted checks/review pending. No `.github/CODEOWNERS` file exists.

**Material assumptions:** PR #242 will merge with a catalog and standalone RW-022 regression. Actual PR merge and explicit task-owner selection of RW-022 are stop gates before activation; a rejected candidate returns this task to planning. The task owner will separately approve this High-risk policy change. Existing `test` job coverage and schema semantics will remain unchanged through merge. Roadmap completion will be recorded only after activation is verified.

**Plan:** 1. Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit. 2. Get clean-context plan review and explicit task-owner approval for this High-risk policy activation. 3. Confirm task-owner selection and merge/verify PR #242, synchronize this branch with its merged main commit, then add the minimal `behaviorContracts` policy block. 4. Verify schema and run a synthetic protected-path change through both Redline reporting and the Agent Workflow checker, asserting red classification, semantic classification, authorization, and `test` verification linkage; run the local combined checker for the real policy PR. 5. Reconcile the feature/board state only after verification, get clean-context result review, satisfy architecture-review with the `architecture-reviewed` label, run hosted PR checks, and merge this separate reviewed policy PR.

**Verification plan:** Protected suite edit is red with behavior-contract classification and `test` linkage → synthetic changed-file Redline report plus checker; assert `behavior_contracts.changed_paths_classified`, `behavior_contracts.requirement_changes_authorized`, and `behavior_contracts.verification_linked` pass. Normal policy PR is red with architecture-review and valid Work Record → local/hosted harness plus `architecture-reviewed` label. Existing protected test runs on PR → hosted `test (3.12)` and `test (3.13)`. Roadmap state reflects activation → feature and board inspection after policy checks.

**Plan review:** Clean-context review requested changes: exercise the protected-path checker predicates, hold State until approval, make candidate acceptance and merge stop gates, and satisfy the policy checkpoint. Revised plan independently re-reviewed: APPROVE (2026-09-24); the synthetic reporter/checker path and sequencing are sufficient. Optional completeness predicates will be checked if exposed by the harness.

**Approvals:** Approved by user 2026-09-24T19:05:33Z: "Approve". This followed the pending RW-022 selection and workflow-only policy activation questions; understood as approval of both. No approval for branch protection, CODEOWNERS, required status, or behavior checkpoint was requested or inferred.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->