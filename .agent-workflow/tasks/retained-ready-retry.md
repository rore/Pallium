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

**Behavior changes:**
[{"target":"task-context.scope","classification":"equivalent","before":"The existing reconnect loop, focused tests in tests/test_codex_retained_connection_recovery.py, and this Work Record.","after":"The existing reconnect loop, focused tests in tests/test_codex_retained_connection_recovery.py, the matching operations retry-contract paragraph, and this Work Record.","reason":"Align the existing retry documentation with the same demonstrated READY-only fix; no additional behavior or authority."}]

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Runtime watch/gray path sets the Elevated floor. Reuse existing authenticated reconnect lifecycle; no authority or persistence contract change.

**Discovery:** _auto_reconnect retries constructor startup-unavailable and explicit busy but currently returns immediately for any candidate READY or REGISTER exception. Existing MCP recovery tests fault the initial idle READY and then supply a healthy replacement. Actual incident at 12:22 Jerusalem lost registration after resolved source close; its final reconnect exception was not logged, so this source-derived mechanism is not its proven historical cause.

**Material assumptions:** READY is read-only and its source I/O can be conclusively disposed without unresolved operations; otherwise fence and stop. Reuse exact authority and bounded episode checks; any proposed REGISTER replay or changed identity returns this task to planning.

**Plan:** Extend the existing actual-MCP/native-client recovery fixture to fault a replacement READY after the first idle retirement, preserve the original failure, and retain focused terminal/identity/budget controls. Only after RED, distinguish READY from REGISTER in the existing reconnect loop and allow resolved transient READY failures to take the existing bounded backoff path after clean disposal. Keep authority checks and fail-closed paths. Obtain existing Astra review; prepare rollout details only after demonstrated reviewed correction.

**Verification plan:** Recovery and safety -> RED/GREEN actual-MCP regression and affected native worker controls, including no REGISTER/tool replay, authority/uncertainty fences, shutdown and budgets. Whole change -> existing selector, full non-slow suite, boundary and workflow checks with source-bound logs. Installed acceptance -> separately approved rollout and original-delivery evidence; not inferred from simulation.

**Plan review:** Agent technical review: astra-reviewer turn 01a17cf2-927b-72c2-bae9-68cc6993cad0, PLAN GO against base1594cf999554fa76e65d272fdebcd4f0aef92d4b. Retry only ShadowUnavailable deadline/transport-failed from READY itself; capture source I/O before disposal and retain all pre/post-cleanup authority, uncertainty and shutdown fences. Do not include response validation or REGISTER failures.

**Approvals:** Not required at this risk level; manager explicitly authorized isolated reproduction and smallest repository fix. Live rollout requires its own exact scope.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Created the record before test or application edits. Branch feat/retained-ready-retry starts at origin/main 1594cf999554fa76e65d272fdebcd4f0aef92d4b; prior trace observation branch retained unchanged. No installed mutation.

Astra approved the bounded plan before test/code implementation; result review remains pending.

RED: existing actual-MCP fixture with replacement READY deadline and transport-failed both failed before application edits (2 failed, 4.09s). The recovery callback returned but no healthy replacement appeared. Command, source hash, full log and JUnit are retained in build/retained-ready-retry/red*. The first attempted command was blocked by sandbox temporary-directory permissions before pytest; the isolated elevated command used only private build HOME/data paths.

GREEN: both positive regressions passed (2 passed, 1.40s). The affected recovery, worker reconnect and MCP/Desktop files then passed all 338 cases (105.47s), including failed REGISTER after commit without replay, pre/post-cleanup uncertainty and identity changes, terminal response, shutdown, attempt exhaustion and elapsed episode budget. Native transport remains simulated; there is no installed recovery claim.

Aligned the existing operations paragraph with the demonstrated READY-only retry contract; this is documentation of the same bounded fix, not an additional runtime change. The initial requirement baseline above remains preserved. Application/source changes are limited to the existing reconnect loop; no changes to hooks, API deadlines, native identity fencing or live installation.

## Result review

Agent technical review: astra-reviewer turn 01a17cfc-de70-7661-be63-d5a1ccd09284, SOURCE/RESULT GO conditional on remaining required validation.

Reviewed revision: c7017cd78625c3843664046c6bfbde49e9c7c738. Production SHA256 3b696b922e5193ead32c7fb0bcb606d7c3f5cb7f4d91f92c971d874ccf996b27; test SHA256 1f3e24bf3eeb6401390205fee6adfbb3857afdc87a9a0dad9d6298e7a6d9c8ca match the affected-control manifest.

Verification adequacy: reviewer inspected the actual production/test/docs diff, cleanup, identity and exit-witness paths plus native RED/GREEN/control receipts. No blocking source finding. Shortened test budgets prove bounds mechanically, not a real five-minute installed journey. Historical 12:22 exception and separate live two-second Relay request failures remain unresolved.

## Validation and rollout preparation

The complete-change selector selects FULL. Boundary report has zero violations; Redline is GRAY for app/mcp/codex_desktop_bridge.py with no required checkpoints, matching Elevated risk. Agent Workflow passes (clean, exit 0) after recording the equivalent operations-documentation scope alignment.

The first full serial run failed the unchanged protected busy-wake test because the runner placed TEMP inside this Git checkout, causing its hook's temporary cwd to inherit the real repository identity. This was a runner setup error, not a demonstrated product failure. No protected test was edited. With private TEMP outside Git, the recorded failure alone passed unchanged (1 passed, 2.24s); the required full run is continuing with that corrected setup. Preserve both attempts and the correction receipts in build/retained-ready-retry/.

The exact installed module was only read and copied to the isolated build/retained-ready-retry/installed-before.py. Its SHA256 is 1ab44db410a8d0439b0f2250ea7230a3be0f7ddd2cda0f1446edeeeb7d0c33d0; LF-normalized content matches the reviewed base. rollout-proposal.json names the target, candidate, backup and rollback. Existing MCP children keep loaded old code, so a separately approved supported idle MCP connection reload would be required for effect. No installation/reload, service/app/gateway restart, configuration/credential/data change or desktop control occurred. This preparation and simulated tests do not close installed delivery acceptance or the hook request-deadline incident.

The subsequent full serial attempt stopped after 3,039 passes at an unchanged health test's setup write: its generated atomic filename was 269 characters while its parent existed. A short outside-Git pytest basetemp made that exact unchanged failure pass (1 passed, 1.55s); no health/transport/drain assertion was edited or bypassed. This was distinct from the historical cleanup-wait incident.

Final complete validation on unchanged reviewed production/test source c7017cd78625c3843664046c6bfbde49e9c7c738 used the repository's normal four-worker full non-slow command with a short private outside-Git basetemp: 8,227 passed, 42 skipped, 2 xfailed, zero failures/errors, 530.61s. Full command, exact source fingerprint, runtime/private paths, complete log and JUnit are in build/retained-ready-retry/full-short*. This is Windows CPython 3.13.14 qualification in the existing private runtime; required hosted platform CI and installed acceptance remain separate. Source/focused-review conditions are satisfied locally; no new application edit followed review.
