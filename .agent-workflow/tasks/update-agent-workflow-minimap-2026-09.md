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
Use the existing consumer mapping: export Agent Workflow `dist/agent-workflow/**` at pinned `cef51bc` to both `.agents/skills/agent-workflow/**` and `.claude/skills/agent-workflow/**`, and Minimap `package/minimap/skills/minimap-roadmap/**` at pinned `45d1b7a` to `.claude/skills/minimap-roadmap/**`. Copy the changed Agent Workflow checker to `scripts/agent-workflow-check.py` and the changed behavioral-integrity reference to `docs/agent-workflow/checkpoints/behavioral-integrity.md`. Compare file inventories and hashes, inspect the exact changed paths, and stop on any required config, policy, CI, hook, AGENTS, application, or roadmap edit. Run focused upstream and Pallium consumer checks, then the repository suite and fresh workflow/redline checks. Keep protected behavior activation and candidate selection for the subsequent discussion/task.

**Verification plan:**
When the sync is complete, the three installed skill trees shall have no missing, extra, or mismatched files against their pinned source trees, and the two mapped Agent Workflow files shall match by hash → full inventory/hash comparison. When Pallium executes the new checker and Minimap runtime, baseline history and participant-count/restart behavior shall pass their focused upstream regressions, while the existing Pallium workflow integration remains valid → focused Agent Workflow and Minimap tests plus `tests/test_agent_workflow_ci.py`. When the final change is reviewed, no unrelated paths or broken Pallium behavior shall appear → exact diff review, `git diff --check`, fresh Redline/workflow checks, and one full `tests/` run.

**Plan review:**
Pending clean-context review; see `## Plan review`.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Established task context, immutable requirement baseline, and pre-edit GRAY classification on `feat/update-agent-workflow-minimap-2026-09`. Awaiting clean-context plan review before file sync.

## Plan review

Pending.

## Evidence

Pending.

## Result review

Pending.
