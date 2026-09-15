<!-- agent-workflow:start -->
**Outcome:** Pallium's tracked Minimap and Agent Workflow consumers match the latest verified official distributions.

**Target:** Pallium repository on `feat/update-consumers-2026-09`.

**Scope:** Refresh `.claude/skills/minimap-roadmap/**` from Minimap 0.3.5 at `c65dfab31ec60ce5f7cad729916d62bf47a2f99e`; refresh Pallium's existing Agent Workflow skill mirrors and mapped consumer assets from `c355df09d27121826e2e19f05c005701f3034489`; add this Work Record.

**Constraints:** Preserve Pallium configuration and policies, instructions outside the Agent Workflow marker, roadmap content, unrelated hooks, and installed service state. Do not install new consumers, change application code, restart Pallium/Minimap/Desktop, merge, deploy, or approve host trust.

**Completion criteria:** Both Agent Workflow skill trees and the Minimap roadmap skill match their pinned upstream trees; mapped Agent Workflow assets match upstream; official settings installers are idempotent and preserve unrelated hooks; focused consumer checks and repository workflow/redline checks pass.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Clean-context Redline review classified the mixed scope GRAY because `.agents/**`, hooks/settings/plugin, AGENTS marker, and governance schema are unclassified governance surfaces; scripts/docs are blue and `.claude/skills/**` is excluded. No boundary or policy checkpoint applies.

**Discovery:** Pallium starts clean at `ac4698c4`. Minimap local and remote main are identical at security release `c65dfab3`, package 0.3.5; its official project install is the complete `package/minimap/skills/minimap-roadmap` subtree only. Agent Workflow remote main is `c355df09`; the source checkout is clean but behind, so the pinned distribution was exported from the fetched `origin/main` tree without changing its checkout. Existing completed refresh records define the consumer mapping and preservation rules.

**Material assumptions:** The two pinned committed distributions are authoritative; a tree/manifest mismatch or installer change outside its owned hook entries stops the update. Pallium's existing config, policy, CI, roadmap, non-owned instructions, and third-party hooks are authoritative; any required semantic edit returns the task to planning.

**Plan:** Key conventions: export committed source trees at the two exact verified SHAs; replace complete existing skill trees; map only already-installed consumer assets; use upstream merge/install helpers for owned marker/hook entries; preserve non-owned text and configuration; make no consumer-specific edits to vendored code. Target paths: `.claude/skills/minimap-roadmap/**`; `.agents/skills/agent-workflow/**`; `.claude/skills/agent-workflow/**`; `.claude/hooks/seed-workflow.sh`; `.opencode/plugins/agent-workflow.mjs`; `scripts/agent-workflow-check.py`; `scripts/agent-workflow-runtime.py`; `docs/agent-workflow/checkpoints/{establish-context,review-result}.md`; the marker-owned Agent Workflow span in `AGENTS.md`; `.claude/settings.json` and `.codex/hooks.json` only if the official installer changes owned registrations; this Work Record. Sequence: copy the pinned skill trees and listed byte-mapped assets, reconcile the owned AGENTS span, run both official settings-installer modes twice, inspect the exact diff, and verify. Stop on any other changed path, trust requirement, manifest mismatch, or non-owned settings/AGENTS change. Do not run the full Pallium suite for this consumer-only refresh.

**Verification plan:** When the refresh is complete, all three installed skill trees shall match their pinned upstream source trees and Minimap shall report 0.3.5 → SHA-256 inventories, file-list parity, and package-version assertion. When the official settings installer runs, Pallium shall retain every unrelated hook/config entry and a second run shall change zero bytes → before/after semantic inspection and byte hashes for `.claude/settings.json`, `.codex/hooks.json`, and guarded-path sidecars. When the updated consumers execute, the security fix and workflow seed/guard contracts shall pass → focused upstream Minimap security/runtime tests, Agent Workflow hook/runtime tests, and `tests/test_agent_workflow_ci.py`. When the final diff is classified, Pallium shall have no application, policy, CI, roadmap, unrelated instruction, or boundary drift → fresh Redline report, Agent Workflow checker, exact path inspection, and `git diff --check`.

**Plan review:** Clean-context review found two record-shape gaps; both were resolved below. Manager approved the underlying mechanical plan.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Established isolated worktree and pinned both official remote heads.
- Clean-context Redline classification: GRAY / Elevated / Moderate; no boundary violation or required policy checkpoint.
- Refreshed the three complete skill trees and six mapped Agent Workflow consumer assets from the pinned exports; reconciled only the owned AGENTS marker.
- Official Claude and Codex settings installers made no changes on either run; settings, Codex hooks, and guarded-path sidecar hashes remained identical.

## Plan review

Clean-context review confirmed the preservation boundaries and checks, and requested exact target mapping plus observable-outcome verification wording. Both are explicit in the final plan; the manager approved proceeding without a wording-only re-review.


## Evidence

- Verified remote pins: Minimap 0.3.5 at c65dfab31ec60ce5f7cad729916d62bf47a2f99e; Agent Workflow at c355df09d27121826e2e19f05c005701f3034489.
- SHA-256/file-list parity: both Agent Workflow trees 66/66 files; Minimap tree 38/38 files; six mapped Agent Workflow assets exact.
- Official installers: two no-op runs each for Claude/Codex; .claude/settings.json, .codex/hooks.json, and .claude/hooks/guarded-paths.json byte hashes unchanged. The bundled Python lacked PyYAML and reported its documented fallback, but did not rewrite the existing guarded-path sidecar.
- Minimap focused security/runtime tests: 136 passed, 2 Windows signal skips, 0 failed.
- Pallium focused Agent Workflow integration: 1 passed; the installed Python seed probe emitted the new read-only-scope guidance.
- Import boundary adapter passed; Redline classified GRAY / Elevated with no boundary violation or checkpoint; Agent Workflow checker passed; git diff --check passed.
- Full Pallium suite intentionally omitted for this consumer-only refresh per task budget constraint.

## Result review

Manager reviewed the functional consumer diff and preservation scope with no blockers. No roadmap item changed status or scope, so roadmap files remain untouched.
