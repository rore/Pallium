<!-- agent-workflow:start -->
**Outcome:** Sensitive governance, MCP, and Relay paths receive explicit review checkpoints, and both native skill trees receive consistent gray/watch treatment.

**Target:** Pallium.

**Scope:** agent-redline-policy.yaml, focused reporter CLI coverage in tests/test_agent_workflow_ci.py, and this Work Record.

**Constraints:** Preserve all existing red rules, boundary contracts, protected behavior paths, shadow/binding modes, checkpoint satisfiers, size thresholds, and runtime behavior. No broad production-directory red rules, new infrastructure, dependencies, or unrelated cleanup.

**Completion criteria:** The six named governance/MCP/Relay paths classify red with their intended existing checkpoint; both native skill roots classify gray plus watch without being excluded; existing protected tests, ordinary blue paths, generated exclusions, and unrelated gray paths retain their classification; CLI regression, full selected validation, independent reviews, and CI pass.

**Requirement baseline:**
{"source":"Codex user approval 2026-09-27: Okay, go for it.","outcome":"Sensitive governance, MCP, and Relay paths receive explicit review checkpoints, and both native skill trees receive consistent gray/watch treatment.","scope":"agent-redline-policy.yaml, focused reporter CLI coverage in tests/test_agent_workflow_ci.py, and this Work Record.","constraints":"Preserve all existing red rules, boundary contracts, protected behavior paths, shadow/binding modes, checkpoint satisfiers, size thresholds, and runtime behavior. No broad production-directory red rules, new infrastructure, dependencies, or unrelated cleanup.","completion_criteria":"The six named governance/MCP/Relay paths classify red with their intended existing checkpoint; both native skill roots classify gray plus watch without being excluded; existing protected tests, ordinary blue paths, generated exclusions, and unrelated gray paths retain their classification; CLI regression, full selected validation, independent reviews, and CI pass."}

**Behavior changes:** []

**Risk:** Elevated

**Complexity:** Simple

**Reason:** The policy is already red with architecture-review. This is a bounded governance-routing change, not a change to the runtime, security/persistence contracts, or enforcement mode.

**Discovery:** Read-only calibration replayed 50 merged PRs from 2026-09-15 through 2026-09-25: 9 red, 29 gray, 12 blue under current policy; maximum existing red firing rate was 10%. Frequency alone does not establish correctness and zero-fired rules remain. Inspection found CI/test selection/checker underclassified and MCP/Relay contracts gray. Only Claude native skills were excluded; removing that exclusion and watching both roots preserves the existing Codex Elevated floor rather than demoting it. Applicability on the clean current-main checkout with exact intended paths returned a red verdict and required a Work Record. No applicable active roadmap item; existing self-protection item is unrelated completed history.

**Material assumptions:** Existing reporter schema and checkpoint labels support these exact-path additions; if not, stop rather than change reporter or CI. Tests can exercise the reporter CLI with temporary changed-path evidence and no service/model calls.

**Plan:** 1. Invoke /agent-workflow to create this Work Record and classify risk before any code edit. 2. Obtain independent clean-context plan review. 3. Add exact red rules: .github/workflows/ci.yml, scripts/test-plan.py, scripts/agent-workflow-check.py -> architecture-review; app/mcp/server.py -> api-review; core/relay.py -> architecture-review; storage/sqlite_relay.py -> persistence-review. Add watch rules for .agents/skills/** and .claude/skills/** and remove only the Claude skill exclusion, leaving both roots gray/watch. Refresh the policy's stale calibration comment. 4. Add one parameterized reporter CLI regression matrix to the existing governance test file, covering target paths, nonmatching siblings, both vendor roots, protected tests, blue paths, generated excludes, multiple checkpoints, and unchanged shadow behavior. 5. Run focused tests and whole-change test-plan; run required full non-slow suite once, fresh Redline/Workflow checks, independent result review, then PR CI and inline finding resolution. Stop on unexpected scope or semantic uncertainty; do not widen policy to unrelated gray paths.

**Verification plan:** When a named path changes, the reporter emits red and the exact checkpoint -> shipped reporter CLI matrix. When either native skill root changes, gray/watch appears without exclusion -> same CLI matrix for both roots. Existing blue/gray/excluded/protected paths retain behavior and shadow-mode labels satisfy only intended checkpoints -> positive/negative/mixed CLI cases plus preservation diff. Selected validation passes -> focused test file, test-plan, full non-slow suite, fresh local governance checks, independent review, and required PR CI.

**Plan review:** Agent technical review: /root/redline_plan_review, 2026-09-27; reviewed clean revision 79a68557a530c26b10556b8ed21ab8777792a226, exact routing plan, reporter, and source responsibilities; no blocking findings.

**Approvals:** Not required at Elevated. User approved the scoped policy-only change on 2026-09-27: "Okay, go for it."

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Checkpoint: architecture-review

What is changing: Six exact-path review routes and consistent gray/watch handling for both vendored native skill roots.
Why: Real changed-path evidence exposed underclassified governance and public/stateful surfaces; historical inactivity is not a reason to weaken existing rules.
Affected contract: Review routing only; application contracts, boundaries, enforcement modes, and checkpoint satisfiers are unchanged.
Compatibility risk: Low runtime risk; more explicit reviewer attention on future PRs. Both vendor copies retain Elevated treatment instead of adding an exclusion.
Verification: Reporter CLI regression matrix, selected local suite, independent technical reviews, and CI.

## Implementation

2026-09-27: Reused the clean completed-sync worktree at C:\Users\I347041\.codex\worktrees\update-agent-workflow-review\Pallium. New isolated branch feat/redline-calibration starts at deb471f40723794b8d65a23718f0eb36f8d76a2c. No policy or test edit yet. Independent plan review completed before implementation.

2026-09-27: Implemented only the approved policy routes/watch calibration, one parameterized reporter CLI matrix, and this record. The pre-edit workflow check reported Python 3.11+ unavailable (exit 2); after implementation, reran with the repository Python 3.13 executable and the fresh workflow check passed (exit 0). Focused regression initially surfaced incorrect expectations for existing app watch, docs blue, checkpoint ordering, and satisfied checkpoints retaining watch warnings; corrected the matrix against reporter output. `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest --noconftest -q -n 0 tests/test_agent_workflow_ci.py` passed: 19 passed.

## Plan review

Skill feedback trigger 3 dropped: the adapter failure was environment-owned (this worktree has no local virtual environment and Python is absent from PATH); its documented PYTHON override recovered the check. No upstream defect report.

Agent technical review: /root/redline_plan_review, 2026-09-27, revision 79a68557a530c26b10556b8ed21ab8777792a226. Approved with no blockers. Six exact routes are supported by existing reporter logic. Skill parity intentionally adds Claude files to size accounting without changing thresholds. Elevated/Simple fits this policy-only change; future API/persistence edits retain their higher floor. Verification is adequate with exact checkpoint/exit assertions and required full validation.

## Evidence

2026-09-27 CI repair: the first PR Linux jobs failed because the new CLI test implicitly consumed an ignored local boundary report. This was a test-isolation defect, not a policy/reporter failure. The matrix now passes an explicit temporary empty-violations report and runs from its temporary directory; missing verdicts expose subprocess diagnostics. Focused file passes again: 19 passed in 12.65s. Production boundary configuration and reporter code remain untouched. Full PR CI must rerun on the repaired revision; the earlier local full-suite record below applies only to its named revision.

Local verification against implementation revision 86ed20ce7ceb9f8826d14e125f8ec970ef96f281, Windows / Python 3.13.14, existing shared virtual environment. Focused reporter CLI file: 19 passed. Whole-change test-plan selected full. Structural YAML comparison preserved all pre-existing rules and non-approved fields. Fresh workflow checks passed all blocking predicates; the absent PR architecture-review label remained a shadow advisory.

The first full run with early-stop ended at 1 failed, 1911 passed, 2 skipped, 1 xfailed in 135.52s: unchanged test_codex_wake_evidence_is_bounded_and_definition_matched returned false on its fourth event. Its isolated rerun passed in 0.29s; no wake code or test was edited. A failure-only retry selected more tests because a stale cache entry named an obsolete parameter ID; that run was cancelled, not counted as evidence. The complete non-slow run without early-stop (`python -m pytest tests/ -q`, default four workers) then passed: 5346 passed, 34 skipped, 2 xfailed in 243.18s. The transient wake failure's cause remains unconfirmed; it is not represented as fixed.

## Result review

Agent technical review: /root/calibration_result_review, 2026-09-27.
Reviewed revision: 86ed20ce7ceb9f8826d14e125f8ec970ef96f281.
Verification adequacy: sufficient focused CLI coverage and exact structural preservation comparison; required full validation is now complete. Independent reviewer found no blocking implementation issues and approved subject to authoritative full-suite and CI results. Reviewer inspected the actual policy, reporter, checker, diff, baseline, and work record; did not rerun tests. Existing rules, boundaries, modes, checkpoint satisfiers, and thresholds are preserved. Elevated/Simple remains appropriate. No applicable active roadmap item or change-induced documentation drift. PR CI and final governance checks remain delivery gates.
