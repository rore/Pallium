# Retained reconnect readiness retry

<!-- agent-workflow:start -->
**Outcome:** Recover an already authenticated retained Codex connection when a replacement's read-only READY exchange has a resolved transient failure, within the existing recovery budget.

**Target:** app/mcp/codex_desktop_bridge.py InventoryWorker._auto_reconnect and the existing retained connection recovery tests.

**Scope:** The existing reconnect loop, focused tests in tests/test_codex_retained_connection_recovery.py, the matching operations retry-contract paragraph, and this Work Record.

**Constraints:** Keep the 12-attempt/300-second episode, backoff, exact runtime-owned identity, continuity, bootstrap and exit-witness checks. Never retry a failed REGISTER exchange, unresolved I/O, changed authority, terminal errors or shutdown. No live service, installation, configuration, database, restart or synthetic traffic changes.

**Completion criteria:** A focused regression fails before the fix because a second clean transient READY failure stops recovery, then passes with bounded automatic recovery and no replay. Affected controls preserve register/uncertainty fencing, terminal outcomes, identity changes, shutdown and budget exhaustion. Independent review and required validation are recorded separately from installed acceptance.

**Requirement baseline:**
{"source":"pallium-manager implementation dispatch 2026-10-27 under Rotem's local-service fix authority","outcome":"Recover an already authenticated retained Codex connection when a replacement's read-only READY exchange has a resolved transient failure, within the existing recovery budget.","scope":"The existing reconnect loop, focused tests in tests/test_codex_retained_connection_recovery.py, and this Work Record.","constraints":"Keep the 12-attempt/300-second episode, backoff, exact runtime-owned identity, continuity, bootstrap and exit-witness checks. Never retry a failed REGISTER exchange, unresolved I/O, changed authority, terminal errors or shutdown. No live service, installation, configuration, database, restart or synthetic traffic changes.","completion_criteria":"A focused regression fails before the fix because a second clean transient READY failure stops recovery, then passes with bounded automatic recovery and no replay. Affected controls preserve register/uncertainty fencing, terminal outcomes, identity changes, shutdown and budget exhaustion. Independent review and required validation are recorded separately from installed acceptance."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Runtime watch/gray path sets the Elevated floor. Reuse existing authenticated reconnect lifecycle; no authority or persistence contract change.

**Discovery:** _auto_reconnect retries constructor startup-unavailable and explicit busy but currently returns immediately for any candidate READY or REGISTER exception. Existing MCP recovery tests fault the initial idle READY and then supply a healthy replacement. Actual incident at 12:22 Jerusalem lost registration after resolved source close; its final reconnect exception was not logged, so this source-derived mechanism is not its proven historical cause.

**Material assumptions:** READY is read-only and its source I/O can be conclusively disposed without unresolved operations; otherwise fence and stop. Reuse exact authority and bounded episode checks; any proposed REGISTER replay or changed identity returns this task to planning.

**Plan:** Extend the existing actual-MCP/native-client recovery fixture to fault a replacement READY after the first idle retirement, preserve the original failure, and retain focused terminal/identity/budget controls. Only after RED, distinguish READY from REGISTER in the existing reconnect loop and allow resolved transient READY failures to take the existing bounded backoff path after clean disposal. Keep authority checks and fail-closed paths. Obtain existing Astra review; prepare rollout details only after demonstrated reviewed correction.

**Verification plan:** RED then GREEN on the exact MCP regression; affected recovery/native worker controls assert no tool or REGISTER replay, continuity/identity/exit-witness preservation, shutdown and exhaustion. Run the existing whole-change selector and mandatory checks; retain source-bound logs. No installed recovery claim from simulation.

**Plan review:** Agent technical review: astra-reviewer turn 01a17cf2-927b-72c2-bae9-68cc6993cad0, PLAN GO against base1594cf999554fa76e65d272fdebcd4f0aef92d4b. Retry only ShadowUnavailable deadline/transport-failed from READY itself; capture source I/O before disposal and retain all pre/post-cleanup authority, uncertainty and shutdown fences. Do not include response validation or REGISTER failures.

**Approvals:** Not required at this risk level; manager explicitly authorized isolated reproduction and smallest repository fix. Live rollout requires its own exact scope.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Created the record before test or application edits. Branch feat/retained-ready-retry starts at origin/main 1594cf999554fa76e65d272fdebcd4f0aef92d4b; prior trace observation branch retained unchanged. No installed mutation.

Astra approved the bounded plan before test/code implementation; result review remains pending.

RED: existing actual-MCP fixture with replacement READY deadline and transport-failed both failed before application edits (2 failed, 4.09s). The recovery callback returned but no healthy replacement appeared. Command, source hash, full log and JUnit are retained in build/retained-ready-retry/red*. The first attempted command was blocked by sandbox temporary-directory permissions before pytest; the isolated elevated command used only private build HOME/data paths.

GREEN: both positive regressions passed (2 passed, 1.40s). The affected recovery, worker reconnect and MCP/Desktop files then passed all 338 cases (105.47s), including failed REGISTER after commit without replay, pre/post-cleanup uncertainty and identity changes, terminal response, shutdown, attempt exhaustion and elapsed episode budget. Native transport remains simulated; there is no installed recovery claim.

Aligned the existing operations paragraph with the demonstrated READY-only retry contract; this is documentation of the same bounded fix, not an additional runtime change. The initial requirement baseline above remains preserved. Application/source changes are limited to the existing reconnect loop; no changes to hooks, API deadlines, native identity fencing or live installation.
