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
Pallium began clean on main at f39b30d7. The first consumer sync used Agent Workflow cef51bc9519ccb55dbd2a57fd8f3467b7b9e060c and Minimap 45d1b7ad7fd83d566e072f88374226a3fe7e5f46. After review, upstream corrective PRs merged: Agent Workflow a940b84682ee270d8bec27732b3b90e6cacc6524 changes only the packaged manifest and checker; Minimap 74a5f4fd29bbc22df35e7932f4449aa9b22ee836 changes only its packaged server reference, runtime server, and restart script. These commits are now authoritative pins. No canonical Pallium roadmap item owns this maintenance sync.

**Material assumptions:**
The two pinned committed distributions are authoritative; disprove with a missing/inconsistent manifest or package tree, then stop and repair the source rather than hand-editing vendored code. Existing Pallium configuration and live CI remain compatible; disprove with focused integration checks or an unexpected consumer diff, then return to planning.

**Plan:**
Advance the existing consumer mapping to Agent Workflow a940b84682ee270d8bec27732b3b90e6cacc6524 and Minimap 74a5f4fd29bbc22df35e7932f4449aa9b22ee836. Export Agent Workflow dist/agent-workflow/** to both mirrored skill trees; mirror its checker into scripts/agent-workflow-check.py. Export Minimap package/minimap/skills/minimap-roadmap/** to the tracked roadmap skill. Compare complete inventories and hashes; inspect exact changed paths and stop on any required config, policy, CI, hook, AGENTS, application, or roadmap edit. Re-run Agent Workflow tests/checker/test_baseline_history_e2e.py, Minimap test/restart-race.test.js plus the earlier participant/roadmap/UI tests and browser E2E, Pallium focused integration and full suite, fresh Redline, and PR-mode workflow checker with real origin/main and HEAD refs. Preserve protected behavior activation for the later task. The new pins supersede the first-sync pins.

**Verification plan:**
When the resync is complete, both Agent Workflow skill trees and the Minimap skill shall match the two new pinned source trees exactly, with the mapped checker equal by hash → full inventory/hash comparison. When the reported upstream defects are fixed, the baseline-history merge-branch cases and restart-race regression shall pass alongside prior focused Minimap and Pallium integration tests → Agent Workflow tests/checker/test_baseline_history_e2e.py, Minimap test/restart-race.test.js and earlier focused/browser tests, and Pallium tests/test_agent_workflow_ci.py. When the final change is reviewed, no unrelated paths or broken Pallium behavior shall appear → exact committed diff, git diff origin/main...HEAD --check, fresh Redline, scripts/agent-workflow-check.py --base-ref origin/main --head-ref HEAD, PR CI, and one full Pallium tests/ run after this resync.

**Plan review:**
First sync and corrective-pin resync APPROVE; see Plan review prose.

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

Corrective-pin resync committed as 122ea66e: copied only the eight changed consumer files byte-for-byte from Agent Workflow a940b84682ee270d8bec27732b3b90e6cacc6524 and Minimap 74a5f4fd29bbc22df35e7932f4449aa9b22ee836. The first sync's Work Record baseline and its approval remain intact; the corrective plan was separately reviewed and committed before this copy. No application, policy, configuration, CI, hook, AGENTS, roadmap, or installed service file changed.

## Plan review

Clean-context reviewer `/root/sync_plan_review` returned REVISE because a local checker run without PR refs would skip the new baseline-history gate. The revised plan names its upstream E2E test, exact Minimap focused tests, and a final Pallium checker/CI run with real base/head refs. Final re-review verdict for the first sync: APPROVE. Reviewer also requested `git diff origin/main...HEAD --check` after the final commit. Clean-context reviewer `/root/sync_pin_plan_review` approved the corrective-pin resync before file changes: mapping, immutable baseline, protected-behavior deferral, and new upstream regression checks are sound.

## Evidence

- Agent Workflow package manifest: 66/66 entries valid; both installed skill trees: 67/67 packaged files with zero name/hash mismatches; Minimap skill: 38/38; mapped checker and behavioral-integrity reference exact by SHA-256. Two ignored Python bytecode caches were excluded from package inventory.
- Agent Workflow baseline-history E2E: 16 passed using `C:\Dev\rore\Pallium\.venv\Scripts\python.exe -m pytest tests/checker/test_baseline_history_e2e.py -q` from the source checkout.
- Minimap focused Node tests: 161 passed, 2 Windows signal skips; `playwright/board-participant-e2e.spec.js`: 1 passed.
- Pallium `tests/test_agent_workflow_ci.py`: 1 passed; full `uv run python -m pytest tests/ -x -q`: 5,295 passed, 34 skipped, 2 xfailed in 211.77 seconds.
- Fresh Redline on `origin/main...777a4c06`: GRAY, no boundary or checkpoint. Agent Workflow PR-mode checker: clean with `--base-ref origin/main --head-ref HEAD`; `requirements.baseline_unchanged` matched first committed baseline `f6238d59`, and detected/declared risk were both Elevated.
- Exact committed diff contains 23 consumer files and this Work Record, with no config, policy, CI, hook, AGENTS, application, or roadmap change. `git diff origin/main...HEAD --check` passed. No canonical Pallium roadmap item applies.

- Corrective-pin source parity: Agent Workflow .agents and .claude trees each 67/67 tracked Git blobs matched; Minimap roadmap skill 38/38; mapped root checker exact. The new upstream delta is eight consumer files only.
- At the exact upstream commits, Agent Workflow baseline-history E2E: 24 passed; Minimap restart-race plus prior participant/roadmap/UI focused tests: 163 passed, 2 Windows skips; Minimap browser participant E2E: 1 passed. Pallium tests/test_agent_workflow_ci.py: 1 passed.
- First parallel Pallium full run had one intermittent, unrelated Relay hook failure at 27%; its exact parametrized node passed 2/2 serially and the recorded last-failure set passed 195 with 2 skips. The second full tests/ run passed: 5,295 passed, 34 skipped, 2 xfailed in 254.49 seconds.
- Fresh Redline: GRAY, no boundary, watch, contract, or checkpoint. PR-mode Agent Workflow checker clean with real origin/main and HEAD; requirements.baseline_unchanged matched first commit f6238d59. Committed diff check passed.

## Result review

The first-sync approval below is superseded by the corrective-pin resync; a new result review is required.

Independent non-implementer `/root/sync_result_review`: APPROVE. Verified both Agent Workflow mirrors at 67/67, Minimap at 38/38, mapped files by hash, the exact 23-file consumer diff, full and focused evidence, immutable baseline, GRAY/Elevated classification, and no applicable Pallium roadmap state change. No BEL or formatting blocker. The local default `build/redline-verdict.json` was stale BLUE for an unrelated diff; the task verification used a freshly generated GRAY verdict and fed it explicitly to the PR-mode checker.
