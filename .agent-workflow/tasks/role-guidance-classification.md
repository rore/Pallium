# Classify persistent role guidance

<!-- agent-workflow:start -->
**Outcome:** Supported role guides and their exact mapping receive proportionate Blue risk classification and focused governance validation.
**Target:** Pallium Redline policy and test selector.
**Scope:** agent-redline-policy.yaml, scripts/test-plan.py, tests/test_test_plan.py, tests/test_agent_workflow_ci.py, and this Work Record.
**Constraints:** No broad documentation exemption, permissions change, CI workflow edits, runtime changes, live installations, or weakening of mixed/unknown-path validation. This classification change itself retains Elevated risk and full validation.
**Completion criteria:** Markdown role guides and roles/mapping.yaml classify Blue and select governance; unknown or executable role files and mixed application changes select full; policy and selector changes still select full; focused tests and independent review pass.
**Requirement baseline:**
{"source":"work-record-initial","outcome":"Supported role guides and their exact mapping receive proportionate Blue risk classification and focused governance validation.","scope":"agent-redline-policy.yaml, scripts/test-plan.py, tests/test_test_plan.py, and this Work Record.","constraints":"No broad documentation exemption, permissions change, CI workflow edits, runtime changes, live installations, or weakening of mixed/unknown-path validation. This classification change itself retains Elevated risk and full validation.","completion_criteria":"Markdown role guides and roles/mapping.yaml classify Blue and select governance; unknown or executable role files and mixed application changes select full; policy and selector changes still select full; focused tests and independent review pass."}
**Relationships:** {"schema_version":1,"sources":null,"pull_requests":[]}
**Behavior changes:** [{"target":"task-context.scope","classification":"coverage-only","before":"agent-redline-policy.yaml, scripts/test-plan.py, tests/test_test_plan.py, and this Work Record.","after":"agent-redline-policy.yaml, scripts/test-plan.py, tests/test_test_plan.py, tests/test_agent_workflow_ci.py, and this Work Record.","reason":"Reuse existing real-policy CLI calibration matrix instead of duplicating reporter test setup."}]
**Risk:** Elevated
**Complexity:** Simple
**Reason:** Policy and test-selector paths are red with architecture-review metadata. The change adjusts governance routing, not application/security/persistence contracts.
**Discovery:** PR360 introduced four role guidance files. The policy leaves roles/ gray and the selector treats them as unknown. Existing governance lane already runs focused selector/CI/workflow contract tests; role guides are consumed as agent guidance, not application code. Scope excludes the pending unrelated working tree edits.
**Material assumptions:** Only top-level Markdown roles/*.md and the exact roles/mapping.yaml are supported guidance. Nested paths, other YAML and executables remain unknown/full. If executable loaders or additional runtime formats are discovered, keep them out of this rule and return to planning. No semantic or permission exemption is implied by Blue classification; substantive authority changes still raise risk by judgment.
**Plan:** Add Blue policy entries for roles/*.md and exact roles/mapping.yaml. Add those same supported paths to the existing governance classifier without new abstractions. Extend existing selector tests with role-only, map-only, mixed application, unknown/executable role path, and policy/selector cases; add a real-policy classification assertion using the reporter's existing callable interface if available. Validate with focused contract tests and reporter. Parent reviews scope before the one required full validation run. No push/merge in this subtask.
**Verification plan:**
- Supported guidance gets proportional routing -> focused selector cases plus real policy reporter assertion.
- Unknown/mixed/self-policy edits remain full -> conservative classification cases.
- No unrelated behavior changes -> independent plan/result review and git diff --check.
- Governance compliance -> fresh changed-path Redline report, workflow check and whole-change selector; full validation once after parent scope review.
**Plan review:** Agent technical review: /root/roles_review, 2026-10-26 GO with no blockers. Preserve explicit nested-path negative case to prove nonrecursive Redline/selector parity. Parent approved scope and one full hosted CI run instead of repeating known local provenance-leakage failures.
**Approvals:** Not required at this risk level. User explicitly requested proper Redline categorization; parent supplied exact correction scope.
**Exceptions:** —
**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Created isolated branch feat/role-guidance-classification from current origin/main 9a1addd2. Work Record written before implementation. Independent plan review passed before edits. Existing reporter CLI calibration matrix is reused for policy tests.

Implemented two narrow Blue rules and matching governance-selector cases. Unknown, nested, executable and mixed paths retain conservative routing. No additive watch rule was needed. Parent approved scope and independent result review found no issues.

## Evidence

- Focused governance contracts: python -m pytest --noconftest -q -n 0 tests/test_test_plan.py tests/test_ci_workflow.py tests/test_agent_workflow_ci.py --basetemp build/role-classification-tests: 39 passed in 54.31s, Python 3.13.14 on Windows using the existing qualified interpreter. The first attempt had 24 fixture errors because the build/ parent directory was absent; corrected the test setup, with no product changes.
- Real-policy CLI cases verify supported role files are Blue and nested/unknown/executable files remain gray. Selector cases preserve full validation for mixed application, policy, selector and unknown paths.
- Import boundaries and git diff --check passed. Fresh Redline report classifies this policy/selector change red with architecture-review satisfied by the independent reviews.
- Whole-change selector still chooses full for this correction. Parent directed one hosted full CI run after publication; no duplicate local full suite. Full CI evidence remains pending and is required before delivery.

## Result review

Agent technical review: /root/roles_review, 2026-10-26, content GO with no findings; parent scope review also passed.
Reviewed revision: base 9a1addd2 plus the policy, selector and two focused test-file diff recorded here.
Verification adequacy: focused routing and real-policy caller-contract coverage passed; full hosted CI remains pending. No application surface or protected behavior contract was modified.

## Checkpoint: architecture-review

What is changing: narrow role-guidance path classification in the policy and validation selector.
Why: the new guidance files currently receive unknown-path treatment and unrelated application validation.
Affected contract: risk and test-lane selection only; policy/selector changes continue to require full validation.
Compatibility risk: incorrect path matching could reduce validation for executable files; explicit negative cases guard that boundary.
Verification: focused contract tests and independent review, then required full validation.

## Handoff

Worktree C:/Dev/rore/Pallium/build/role-guidance-classification; parent owns publication and required review. No live environment changes.
