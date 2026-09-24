<!-- agent-workflow:start -->
**Outcome:**
Pallium's tracked Agent Workflow and Minimap consumer skills match the latest verified upstream distributions.

**Target:**
Pallium.

**Scope:**
Refresh both Agent Workflow skill trees, its mapped checker and behavioral-integrity reference, the tracked Minimap roadmap skill, and this Work Record.

**Constraints:**
Preserve Pallium's application code, policy, configuration, CI, roadmap content, unrelated hooks and instructions, and installed service state. Do not activate protected behavior contracts in this sync.

**Completion criteria:**
Both Agent Workflow skill trees and the Minimap roadmap skill match pinned upstream trees; the mapped checker/reference match upstream; focused consumer checks, the repository suite, and workflow/redline checks pass.

**Requirement baseline:**
{"source":"request_source_item_id:862874a4-cb22-45d2-967c-b4dff99808b0","outcome":"Pallium's tracked Agent Workflow and Minimap consumer skills match the latest verified upstream distributions.","scope":"Refresh both Agent Workflow skill trees, its mapped checker and behavioral-integrity reference, the tracked Minimap roadmap skill, and this Work Record.","constraints":"Preserve Pallium's application code, policy, configuration, CI, roadmap content, unrelated hooks and instructions, and installed service state. Do not activate protected behavior contracts in this sync.","completion_criteria":"Both Agent Workflow skill trees and the Minimap roadmap skill match pinned upstream trees; the mapped checker/reference match upstream; focused consumer checks, the repository suite, and workflow/redline checks pass."}

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Clean-context Redline classified the mixed consumer scope GRAY because `.agents/skills/agent-workflow/**` is unclassified; no boundary, checkpoint, watch, or contract-surface flag applies. Several mirrored consumers require coordinated parity checks.

**Discovery:**
Pallium began clean on `main` at `f39b30d7`. Agent Workflow upstream `origin/main` is pinned at `cef51bc9519ccb55dbd2a57fd8f3467b7b9e060c`; compared with Pallium's prior `36bd34ca` sync, only four packaged files changed: manifest, operating mode, checker, and behavioral-integrity reference. The checker now compares new Work Record baselines with their first committed version when PR refs are supplied. Minimap upstream `main` is pinned at `45d1b7ad7fd83d566e072f88374226a3fe7e5f46`; its bundled roadmap skill advances from 0.3.5 to 0.3.6 across 13 files. Prior consumer records define the tracked mapping. No canonical Pallium roadmap item owns this maintenance sync.

**Material assumptions:**
The two pinned committed distributions are authoritative; disprove with a missing/inconsistent manifest or package tree, then stop and repair the source rather than hand-editing vendored code. Existing Pallium configuration and live CI remain compatible; disprove with focused integration checks or an unexpected consumer diff, then return to planning.

**Plan:**
Use the existing consumer mapping: export Agent Workflow `dist/agent-workflow/**` at pinned `cef51bc` to both `.agents/skills/agent-workflow/**` and `.claude/skills/agent-workflow/**`, and Minimap `package/minimap/skills/minimap-roadmap/**` at pinned `45d1b7a` to `.claude/skills/minimap-roadmap/**`. Copy the changed Agent Workflow checker to `scripts/agent-workflow-check.py` and the changed behavioral-integrity reference to `docs/agent-workflow/checkpoints/behavioral-integrity.md`. Compare file inventories and hashes, inspect the exact changed paths, and stop on any required config, policy, CI, hook, AGENTS, application, or roadmap edit. Run upstream Agent Workflow `tests/checker/test_baseline_history_e2e.py` and Minimap `test/pallium-participants.test.js`, `test/roadmap.test.js`, and `test/ui-api.test.js`; check Pallium integration, then the repository suite and fresh workflow/redline checks. After committing the final change, run the new checker with real `origin/main` and branch `HEAD` refs so its baseline-history predicate does not skip; confirm PR CI repeats this mode. Keep protected behavior activation and candidate selection for the subsequent discussion/task.

**Verification plan:**
When the sync is complete, the three installed skill trees shall have no missing, extra, or mismatched files against their pinned source trees, and the two mapped Agent Workflow files shall match by hash → full inventory/hash comparison. When Pallium executes the new checker and Minimap runtime, baseline history and participant-count/restart behavior shall pass their focused upstream regressions, while the existing Pallium workflow integration remains valid → Agent Workflow `python -m pytest tests/checker/test_baseline_history_e2e.py -q`, Minimap `node --test test/pallium-participants.test.js test/roadmap.test.js test/ui-api.test.js`, and Pallium `python -m pytest tests/test_agent_workflow_ci.py -q -n 0`. When the final change is reviewed, no unrelated paths or broken Pallium behavior shall appear → exact diff review, `git diff --check`, fresh Redline and `scripts/agent-workflow-check.py --base-ref origin/main --head-ref HEAD`, PR CI with actual base/head refs, and one full Pallium `tests/` run.

**Plan review:**
Clean-context reviewer `/root/sync_plan_review`: APPROVE after PR-ref verification revision; see `## Plan review`.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Established task context, immutable requirement baseline, and pre-edit GRAY classification on `feat/update-agent-workflow-minimap-2026-09`. Clean-context plan review approved before file sync.
- Exported and manifest-validated the two pinned upstream trees, then copied their complete tracked skill contents and the two mapped Agent Workflow mirrors. Source parity is 67/67 for each Agent Workflow tree and 38/38 for Minimap; two ignored Python bytecode caches were excluded from package inventory. No config, policy, CI, hook, AGENTS, application, or roadmap path changed. `apply_patch` hit the documented Windows 1385 failure during the plan revision; exact-file deterministic replacement was used only for this Work Record.

- Verification complete on committed consumer revision `777a4c06`; focused upstream, browser E2E, Pallium full suite, fresh Redline, and PR-mode checker passed.

## Plan review

Clean-context reviewer `/root/sync_plan_review` returned REVISE because a local checker run without PR refs would skip the new baseline-history gate. The revised plan names its upstream E2E test, exact Minimap focused tests, and a final Pallium checker/CI run with real base/head refs. Final re-review verdict: APPROVE. Reviewer also requested `git diff origin/main...HEAD --check` after the final commit.

## Evidence

- Agent Workflow package manifest: 66/66 entries valid; both installed skill trees: 67/67 packaged files with zero name/hash mismatches; Minimap skill: 38/38; mapped checker and behavioral-integrity reference exact by SHA-256. Two ignored Python bytecode caches were excluded from package inventory.
- Agent Workflow baseline-history E2E: 16 passed using `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest tests/checker/test_baseline_history_e2e.py -q` from the source checkout.
- Minimap focused Node tests: 161 passed, 2 Windows signal skips; `playwright/board-participant-e2e.spec.js`: 1 passed.
- Pallium `tests/test_agent_workflow_ci.py`: 1 passed; full `uv run python -m pytest tests/ -x -q`: 5,295 passed, 34 skipped, 2 xfailed in 211.77 seconds.
- Fresh Redline on `origin/main...777a4c06`: GRAY, no boundary or checkpoint. Agent Workflow PR-mode checker: clean with `--base-ref origin/main --head-ref HEAD`; `requirements.baseline_unchanged` matched first committed baseline `f6238d59`, and detected/declared risk were both Elevated.
- Exact committed diff contains 23 consumer files and this Work Record, with no config, policy, CI, hook, AGENTS, application, or roadmap change. `git diff origin/main...HEAD --check` passed. No canonical Pallium roadmap item applies.

## Result review

Independent non-implementer `/root/sync_result_review`: APPROVE. Verified both Agent Workflow mirrors at 67/67, Minimap at 38/38, mapped files by hash, the exact 23-file consumer diff, full and focused evidence, immutable baseline, GRAY/Elevated classification, and no applicable Pallium roadmap state change. No BEL or formatting blocker. The local default `build/redline-verdict.json` was stale BLUE for an unrelated diff; the task verification used a freshly generated GRAY verdict and fed it explicitly to the PR-mode checker.
