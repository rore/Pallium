<!-- agent-workflow:start -->
**Outcome:** Restarting the Pallium Windows service no longer disconnects active Codex MCP sessions.

**Target:** Pallium Windows service restart.

**Scope:** `scripts/restart-service.ps1`, a focused Codex integration regression, and this Work Record.

**Constraints:** Continue terminating every service-owned supervisor, API, processor, cleaner, and snapshot process so restarted code is fresh; do not change Codex MCP configuration or public contracts.

**Completion criteria:** When the service restart sweep runs, an independently launched `python -m app.run mcp` bridge shall survive while service-owned process signatures remain swept.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Pre-edit redline classifies all intended paths blue with no watch flags, checkpoints, or boundary findings.

**Approach:** Remove only the client-owned MCP signature from the existing sweep and correct its ownership comment. Add a regression tying Codex's stdio command to the restart script exclusion.

**Verification:** Focused Codex integration test, workflow checker, Windows CI smoke, and a live cross-agent MCP call before and after the canonical restart.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Discovery confirmed Codex launches `python -m app.run mcp` as its client-owned stdio bridge, while the Windows restart sweep kills that same command globally. The supervisor does not own an MCP subprocess; its HTTP MCP endpoint is mounted in the API process. Redline classified the planned scripts/tests-only change Routine/Simple.

## Evidence

The regression `test_windows_service_restart_preserves_codex_mcp_bridge` failed before the fix, then `python -m pytest tests/test_codex_integration.py tests/test_supervisor.py tests/test_supervisor_kill_tree.py -q` passed 52 tests with 6 platform skips. The workflow checker and PR Windows smoke passed. A fresh Codex agent called Pallium status before the canonical restart; the restart did not kill `app.run mcp`; after the API startup window, the same agent session called Pallium status successfully again.

## Result review

Self-review approved for Routine risk: the diff removes only the client-owned MCP signature, retains all six service-owned sweep signatures, changes no runtime contract, and satisfies the observable same-session restart criterion.