<!-- agent-workflow:start -->
**Outcome:** Pallium's installed Agent Workflow consumers match upstream main at fbe6c768b05a9afe60c623d2dfbb42db2ce6ff72 without changing Pallium-specific governance decisions.

**Target:** Pallium repository.

**Scope:** Refresh both installed Agent Workflow skill trees, their existing vendored scripts/schema, and the owned Agent Workflow AGENTS marker from the pinned upstream distribution; preserve existing Workflow doc mirrors and refresh the one changed Redline reference mirror; add this Work Record.

**Constraints:** Preserve agent-workflow.yaml, agent-redline-policy.yaml, the live CI workflow, CODEOWNERS, unrelated hooks/settings, Work Record history, and application behavior. No re-bootstrap or new dependency.

**Completion criteria:** Both skill installs and mapped consumer assets match the pinned upstream package; unrelated configuration is unchanged; focused workflow/Redline checks and PR CI pass.

**Requirement baseline:**
{"source":"source_item_id:5686f4fa-37de-41c8-b40f-26f449b52d68","outcome":"Pallium's installed Agent Workflow consumers match upstream main at fbe6c768b05a9afe60c623d2dfbb42db2ce6ff72 without changing Pallium-specific governance decisions.","scope":"Refresh both installed Agent Workflow skill trees, their existing vendored scripts/schema/doc mirrors, and the owned Agent Workflow AGENTS marker from the pinned upstream distribution; add this Work Record.","constraints":"Preserve agent-workflow.yaml, agent-redline-policy.yaml, the live CI workflow, CODEOWNERS, unrelated hooks/settings, Work Record history, and application behavior. No re-bootstrap or new dependency.","completion_criteria":"Both skill installs and mapped consumer assets match the pinned upstream package; unrelated configuration is unchanged; focused workflow/Redline checks and PR CI pass."}

**Behavior changes:**
[{"alternatives":"Refresh the Workflow mirror contrary to upstream upgrade guidance, or defer the upstream sync.","authority":{"name":"task-owner","scope":"task"},"reason":"Upstream upgrade guidance requires leaving the existing docs/agent-workflow mirror intact; the changed advertised Redline reference must remain aligned.","impact":"The docs/agent-workflow mirror remains at its existing revision; installed skill guidance is updated and authoritative. No application behavior changes.","before":"Refresh both installed Agent Workflow skill trees, their existing vendored scripts/schema/doc mirrors, and the owned Agent Workflow AGENTS marker from the pinned upstream distribution; add this Work Record.","target":"task-context.scope","approval":{"by":"user","reference":"2026-09-25 reply to the exact scope-change request in this task","verbatim":"I approve."},"after":"Refresh both installed Agent Workflow skill trees, their existing vendored scripts/schema, and the owned Agent Workflow AGENTS marker from the pinned upstream distribution; preserve existing Workflow doc mirrors and refresh the one changed Redline reference mirror; add this Work Record.","classification":"requirement-change"}]

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Clean-context Redline review classified the consumer sync GRAY because installed skill trees, the governance schema, and AGENTS marker are unclassified; scripts/docs are blue and the Claude skill tree is excluded. Several mapped consumers and compatibility checks make this Moderate.

**Discovery:** Upstream origin/main is fbe6c768 (2026-09-25), newer than Pallium's last verified Agent Workflow sync at c355df09. The source archive matches all 67 blobs of that exact commit and its 66-entry manifest. The package adds proportionality and behavior-integrity guidance. Pallium already has the reporter, runtime adapters, schema, and hooks; normalized deltas remain in both skill trees, the checker, and the owned marker. Upstream explicitly preserves existing docs/agent-workflow mirrors on upgrade. The advertised docs/agent-redline/skills mirror has one changed source page, gray-zone-change.md, and needs refresh. Pallium's live CI workflow has local adaptations and is not a byte-copy target. The sole open PR (#236) first committed its Work Record with a Requirement baseline, satisfying the new checker migration rule.

**Material assumptions:** The committed dist/agent-workflow tree at fbe6c768 is authoritative; a manifest/blob mismatch stops the sync. Existing Pallium config/policy/CI remain compatible; a required semantic change outside the mapped consumer scope returns to planning. Existing Workflow docs mirrors, unrelated settings/hooks, and non-owned AGENTS text must remain unchanged; the changed Redline reference mirror must stay aligned.

**Plan:** 1. Invoke /agent-workflow to create this Work Record and classify risk before any code edit. 2. Export pinned upstream dist; replace both complete existing skill trees and only the changed existing mapped scripts/schema. Keep existing docs/agent-workflow mirrors intact per upstream upgrade guidance; refresh only the changed Redline gray-zone reference mirror. Reconcile only the owned AGENTS marker using the upstream helper; run official settings installers only if a changed hook registration requires them. 3. Inspect exact diff; stop on unexpected files, manifest mismatch, or config/CI incompatibility. 4. Verify source parity after Git newline normalization, script syntax, schema compatibility, focused consumer tests, fresh Redline/Workflow checks, independent result review, and PR CI. Preserve existing live CI rather than copying its template.

**Verification plan:** When synced, both skill trees and mapped assets shall match the pinned upstream package after Git newline normalization → file-list and content parity. When helpers run, unrelated settings/hooks/instructions shall remain unchanged → before/after diff and idempotence. When the new checker/reporter run on Pallium, existing config and policy shall remain valid and gates shall pass → focused tests, local Redline/Workflow checks, and PR CI.

**Plan review:** Clean-context Sol review found no CI incompatibility and requested exact-commit archive provenance plus preservation of the docs mirror; both are addressed below.

**Approvals:** Task owner approved the exact Scope change in this task on 2026-09-25; no separate risk-level approval required.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Discovery and pre-edit Redline classification complete. Upstream source archive verified against all 67 commit blobs; schemas accept Pallium config/policy. Clean-context review conditions are resolved before consumer edits. Dual skill trees and mapped checker copied from the pinned archive; owned AGENTS marker reconciled with its upstream helper. Source/file-list parity and marker idempotence pass; existing Workflow docs mirrors, config, policy, CI, and hook registrations remain untouched; the single changed Redline reference mirror is aligned.


Task owner approved the exact baseline-to-current Scope change on 2026-09-25 (verbatim: "I approve."); the Work Record now classifies it as requirement-change.

Trigger 2 dropped: independent reviewer corrected my overbroad initial Scope; no upstream skill defect.

## Plan review

Reviewer checked the mapped consumer scope and CI CLI compatibility. The archive has no Git metadata, so all 67 files were verified against upstream commit blobs; Windows core.autocrlf=true requires newline-normalized destination comparisons. Upstream bootstrap guidance says to preserve existing docs/agent-workflow mirrors. Result review caught the changed Redline gray-zone reference, so its advertised docs mirror was updated. Local checks will use the repository's existing Python 3.11+ executable via PYTHON.

## Evidence

Pinned upstream provenance: 67/67 Git blobs and 66 manifest entries verified. Both installed skill trees and the vendored checker match the pinned source after newline normalization. All eight advertised Redline checkpoint mirrors match their installed sources; the owned AGENTS marker is idempotent. Pallium workflow/policy schemas accept the unchanged config.

Local checks: `python -m py_compile scripts/agent-workflow-check.py` passed; `pytest tests/test_agent_workflow_ci.py -q -n 0` passed (1); import linter passed; fresh Redline result is GRAY advisory, with no boundary violations or checkpoints; Agent Workflow check is clean, including the approved requirement-change chain.

The required one-shot parallel `pytest tests/ -x -q` run was not green: 1,673 passed, 1 xfailed, and two failures at `tests/test_claude_code_hooks/test_session_pin.py::TestResolveContainerRef::test_deliberate_git_project_switch_updates_pin` and `tests/test_codex_wake.py::test_busy_queue_recovery_stays_single_flight_and_competing_hook_blocks_overtaken_wake`. Both exact nodes passed when rerun serially (`-q -n 0`). No changed subsystem overlaps those nodes. The later `--lf --lfnf=none` selected zero tests, so it is not a passing full-suite signal. Action: open the PR and require a fresh passing PR CI `test` job before review completion; investigate if it reproduces either failure. Current branch: `feat/update-agent-workflow-upstream` in the isolated worktree. Final commit and PR CI remain pending.
PR #247 provided the fresh full-run signal on source commit `c16bbc38`: Python 3.12 and 3.13 `test` jobs, Windows smoke, Redline, and Agent Workflow all passed. See https://github.com/rore/Pallium/actions/runs/36137736258 and https://github.com/rore/Pallium/actions/runs/36137736187. The earlier local parallel failures did not reproduce in PR CI. Independent result review verified source parity and the diff, raised the documentation Scope classification, and that finding was resolved by the task owner's exact approval and the Redline mirror correction. No dedicated roadmap item owns this upstream maintenance sync.

## Skill feedback (unsent)

**Affected surface:** `agent-workflow/operating-mode.md` step 7 at `fbe6c768`; GitHub CLI 2.86.0.

**Expected:** The documented `gh pr view --json reviews,reviewThreads` command returns review summaries and thread state.

**Actual:** The CLI rejects `reviewThreads` as an unknown JSON field.

**Minimal reproduction:** Run that command on any PR with `gh` 2.86.0.

**Evidence:** `Unknown JSON field: "reviewThreads"`; GraphQL `pullRequest.reviewThreads` works.

**Suggested owner:** Upstream `operating-mode.md` step 7 should use a supported GraphQL query for thread state.