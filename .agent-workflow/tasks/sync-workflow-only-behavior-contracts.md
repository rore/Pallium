<!-- agent-workflow:start -->
**Outcome:**
Pallium vendors Agent Workflow's workflow-only behavior-contract support, and its roadmap accurately describes the solo-developer rollout without GitHub merge enforcement.

**Target:**
Pallium.

**Scope:**
Sync the pinned Agent Workflow consumer delta into the two skill trees and explicit schema/reporter/checker/checkpoint mirrors; update `roadmap/features/add-protected-behavioral-requirements-regression-suite.md`; add this Work Record.

**Constraints:**
Preserve Pallium application behavior and customized live CI. Do not change `agent-redline-policy.yaml`, CODEOWNERS, branch protection, tests, hooks/settings, application code, or activate a behavior contract before one candidate has an accepted public-surface regression witness.

**Completion criteria:**
Consumer assets match Agent Workflow `36bd34ca7dabc59ab2f8afcea1b5fd3ca8b342fc`; the roadmap specifies `protection: workflow`, existing PR verification, task-owner approval semantics, candidate admission, and a separate activation step; focused governance checks and the Pallium suite pass.

**Requirement baseline:**
{"source":"relay-msg-9a67c13e6bb0495284e481f83feaecce","outcome":"Pallium vendors Agent Workflow's workflow-only behavior-contract support, and its roadmap accurately describes the solo-developer rollout without GitHub merge enforcement.","scope":"Sync the pinned Agent Workflow consumer delta into the two skill trees and explicit schema/reporter/checker/checkpoint mirrors; update `roadmap/features/add-protected-behavioral-requirements-regression-suite.md`; add this Work Record.","constraints":"Preserve Pallium application behavior and customized live CI. Do not change `agent-redline-policy.yaml`, CODEOWNERS, branch protection, tests, hooks/settings, application code, or activate a behavior contract before one candidate has an accepted public-surface regression witness.","completion_criteria":"Consumer assets match Agent Workflow `36bd34ca7dabc59ab2f8afcea1b5fd3ca8b342fc`; the roadmap specifies `protection: workflow`, existing PR verification, task-owner approval semantics, candidate admission, and a separate activation step; focused governance checks and the Pallium suite pass."}

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Clean-context Redline classified the consumer sync GRAY because `.agents/skills/agent-workflow/**` and `.agent-redline/agent-policy.schema.json` are unclassified. The change spans mirrored governance assets and a roadmap contract, but no runtime code or live policy.

**Discovery:**
Upstream Agent Workflow PR #37 is merged at `36bd34ca`; its distributable delta adds explicit workflow protection while preserving repository protection as the default. Pallium already runs the combined Redline/Agent Workflow harness on every PR, and CI job `test` runs `tests/` on every PR. The current roadmap is stale because it assumes CODEOWNERS, a required status, and branch protection are mandatory. No candidate is yet accepted under the roadmap's public-surface and regression-witness criteria, so activating `behaviorContracts` in this sync would protect an empty or unqualified contract surface.

**Material assumptions:**
Agent Workflow `36bd34ca7dabc59ab2f8afcea1b5fd3ca8b342fc` is the intended source; any source mismatch or failed consumer verification stops the sync. Existing CI job `test` remains the named PR verification because it runs all of `tests/`; if a future contract is excluded or split out, activation must update the identifier or CI before policy configuration. A first contract candidate must be explicitly accepted with a public-surface regression witness; until then the policy block stays absent.

**Plan:**
1. Overlay pinned `C:\Dev\rore\agent-workflow\dist\agent-workflow/**` onto both `.agents/skills/agent-workflow/**` and `.claude/skills/agent-workflow/**`. Copy the changed explicit consumer mirrors only: Redline policy schema to `.agent-redline/agent-policy.schema.json`, reporter/checker to `scripts/`, and behavioral-integrity checkpoint to `docs/agent-workflow/checkpoints/`. Preserve the live `.github/workflows/agent-workflow.yml`, repository policy/config, settings/hooks, AGENTS marker, and runtime code. Stop on missing manifest entries, target extras, or unexplained non-owned diffs. 2. Rewrite every repository-protection claim across the queued roadmap, including Summary, Contract Layout, Which Tests Qualify item 6, Activation Sequence, Out of Scope, Done When, and Notes, for `behaviorContracts.protection: workflow`. Keep the dedicated `tests/behavior_contracts/**` catalog/test layout and evidence-first candidate rules; name existing CI job `test` as the non-required PR verification and the combined Redline/Agent Workflow harness as the PR integrity check; state that protected paths become red, every edit needs semantic classification and verification linkage, and only `requirement-change` needs exact task-owner/user approval. Explicitly remove CODEOWNERS, branch-required status, behavior checkpoint, authenticated repository-authority, and merge-block claims. Keep contract-test selection and policy activation as a later explicit PR. 3. Verify both skill trees and explicit mappings against pinned upstream, compile copied Python, validate policy schema compatibility, run focused Agent Workflow CI tests, fresh Redline and Agent Workflow checks, then the full Pallium suite once before review.

**Verification plan:**
When the sync completes, both skill trees and each explicit mirror shall match pinned upstream with no unrelated diff → manifest/hash comparison and `git diff --check`. When the roadmap is updated, it shall truthfully describe workflow protection and preserve evidence-first candidate selection → exact diff review against upstream behavioral-integrity documentation. Existing governance integration shall remain valid → Python compile, schema validation, `python -m pytest tests/test_agent_workflow_ci.py -q -n 0`, fresh Redline plus Agent Workflow checker. Existing Pallium behavior shall remain green → `python -m pytest tests/ -x -q` once before review.

**Plan review:**
Clean-context reviewer `/root/workflow_only_plan_review`: APPROVE after the roadmap-scope revision. See `## Plan review`.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Established context, immutable requirement baseline, and scope before repository edits.
- Clean-context Redline verdict: GRAY; no boundary finding, checkpoint, watch flag, or contract surface. `.claude/skills/**` is excluded from Redline visibility; exact source parity will compensate during verification.
- Clean-context plan review approved after expanding the roadmap rewrite to every repository-mode claim. Synced pinned upstream consumer assets into both skill trees and explicit mirrors; rewrote the queued roadmap for workflow protection while leaving live CI, policy, tests, and runtime code unchanged.
- Verification completed: exact upstream parity, compile/schema/focused governance checks, and the combined local workflow check passed. The default parallel suite exposed one Windows CRLF-only byte-budget failure plus two wake concurrency flakes that each passed serially; the complete serial remainder passed.
- apply_patch created the Work Record, then failed with Windows logon error 1327 on the next edit. All subsequent edits used exact deterministic replacements limited to the Work Record and roadmap, as allowed by the machine-local fallback.

## Plan review

The clean-context reviewer required the plan to remove repository-mode assumptions from the entire roadmap, specifically candidate rule 6 and Done When item 2, and to name `test` as non-required PR verification without CODEOWNERS or merge-block claims. Plan step 2 now makes those locations and limits explicit. Re-review verdict: APPROVE.

## Evidence

Verified on `feat/sync-workflow-only-behavior-contracts` against Agent Workflow `36bd34ca7dabc59ab2f8afcea1b5fd3ca8b342fc`:

- both skill trees contain 67 source files and 67 target files with no missing, extra, or SHA-256-different entries; all four explicit schema/reporter/checker/checkpoint mappings match upstream
- copied Python consumers compile; the new schema accepts Pallium's planned `{protection: workflow, paths: [tests/behavior_contracts/**], verification: test}` block
- `uv run python -m pytest tests/test_agent_workflow_ci.py -q -n 0`: 1 passed
- `& scripts/agent-workflow-runtime.ps1 codex check --repo-root . --slug sync-workflow-only-behavior-contracts`: clean, no boundary violation or checkpoint
- initial `uv run python -m pytest tests/ -x -q`: stopped at one unrelated Windows checkout issue in `tests/test_guidance_budget.py`; the tracked skill blob is exactly 2,800 bytes while CRLF checkout expansion is 2,836 bytes, and the task does not modify that file
- two later xdist runs encountered different wake concurrency timing failures; both exact nodes passed immediately with `-n 0`
- complete serial remainder, `uv run python -m pytest tests/ -x -q -n 0 --ignore=tests/test_guidance_budget.py`: 5249 passed, 34 skipped, 216 deselected, 2 xfailed in 847.58s
- `git diff --check`: passed before final Work Record evidence update; rerun before commit/review

## Result review

Independent reviewer `/root/workflow_only_plan_review` verified scope, 67/67 source parity, four explicit mirrors, roadmap accuracy, and `git diff --check`. Signoff is blocked until the accidental BEL is removed and one complete suite passes without excluding `test_guidance_budget.py`; both are being addressed before re-review.
