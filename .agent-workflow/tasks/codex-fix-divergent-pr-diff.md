<!-- agent-workflow:start -->
**Outcome:**
PR redline and agent-workflow checks classify only the pull request's own changed files even when `main` advances after the feature branch diverges.

**Target:**
Pallium's vendored agent-workflow GitHub Actions workflow.

**Scope:**
`.github/workflows/agent-workflow.yml`; one focused workflow-contract regression under `tests/`; this Work Record.

**Constraints:**
Do not weaken redline policy, checkpoints, or branch protection. Use the pull request head commit, not the synthetic merge commit, and compute changes from the Git merge base. Do not touch Relay/runtime code or integrations.

**Completion criteria:**
(1) Both changed-file jobs use the authoritative PR head and merge-base diff. (2) A divergent-history regression fails for two-dot/synthetic-merge behavior and passes for the configured workflow. (3) Existing workflow gates remain green and unrelated base-branch files no longer appear in the PR report.

**Risk:**
High

**Complexity:**
Simple

**Reason:**
Redline marks `.github/workflows/agent-workflow.yml` as a red-zone self-protection surface. High risk because an incorrect changed-file set can create false or missing governance checkpoints; the implementation is a small, coherent workflow correction.

**Discovery:**
After PR #104 advanced `main` from `585799b4` to `77018a03`, PR #105's authoritative GitHub file list remained 13 files, but its redline/workflow sticky comments included PR #104's API, model, retrieval, and history files. The workflow currently uses `github.sha` (the pull-request merge ref) and a two-dot `BASE_SHA HEAD_SHA` diff in both changed-file jobs.

**Material assumptions:**
Git's three-dot diff between the current base SHA and `github.event.pull_request.head.sha` is the repository's intended PR change set. Disproof: a deterministic divergent-history fixture includes base-only files or excludes head-only files; if so, use an explicit `git merge-base` command instead.

**Plan:**
Replace both changed-file jobs' synthetic `github.sha` input with `github.event.pull_request.head.sha`, and replace two-dot with three-dot diff syntax. Add one focused test that pins both workflow occurrences and demonstrates divergent Git history returns only head-side files. Stop if the regression shows three-dot semantics do not match GitHub's PR file list.

Key conventions: preserve the existing inline workflow; do not add a helper abstraction or dependency for two Git arguments.

Target files or classes: `.github/workflows/agent-workflow.yml`; `tests/test_agent_workflow_ci.py`.

**Verification plan:**
When `main` advances independently, changed-file computation shall contain only PR-head changes → temporary Git-history regression plus exact workflow contract assertion. When the workflow runs normally, existing governance shall remain enforced → local workflow checker, redline report, `git diff --check`, and PR CI.

**Plan review:**
Clean-context Luna review approved the plan with required regression details recorded below.

**Approvals:** Approved by user 2026-09-05T22:47:09.9831044Z: "you don't need to ask every time, you have a constant approval to get what you're working on to a done state"

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-09-06: Confirmed live PR-report contamination against GitHub's authoritative file list; initialized the High-risk Work Record before workflow edits.
- 2026-09-06: Clean-context architecture review approved three-dot semantics and required base-only/head-only fixture assertions plus exact checks for both changed-file jobs.

## Checkpoint: architecture-review

What is changing: changed-file computation in both agent-workflow jobs will use the exact pull-request head and Git merge-base semantics.
Why: divergent main updates currently contaminate redline/workflow classification with unrelated files.
Affected contract / model / boundary: governance changed-file input only; no policy or checkpoint rule changes.
Compatibility / migration risk: low — standard GitHub pull_request metadata and Git three-dot semantics, covered by a divergent-history regression.
Verification plan: focused workflow contract test, temporary Git history, local workflow/redline checks, PR CI.

## Plan review

Clean-context Luna verdict: approved with two required corrections. The deterministic regression must create divergent history with a merge base, one base-only file, and one head-only file; it must prove only the head-side change is selected and the old synthetic-merge/two-dot form fails. Exact contract assertions must cover both changed-file jobs and reject `github.sha` there, while preserving the checker's separate existing head-SHA inputs. No policy, checkpoint, fork-PR, or fetch-depth blocker was found.

## Evidence

Pending.

## Result review

Pending.
