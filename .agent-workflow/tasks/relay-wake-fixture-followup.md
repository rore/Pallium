<!-- agent-workflow:start -->
**Outcome:** Six CodeRabbit-identified defects in relay wake fixtures and tests corrected.

**Target:** `tests/relay/wake/fixtures/`, `tests/test_relay_wake_fixtures.py`, `tests/test_mcp_server.py`

**Scope:**
- `opencode/07_ambiguous_retry.json` — add `relay_id=` marker to payload; add `parts[]` to `prompt_async` step
- `codex/03_busy_queue.json` + `codex/06_restart_recovery.json` — add `expected_wake_state` per step/scenario entry
- `opencode/05_session_states.json` stale_session — replace inferred staleness with explicit `lease_expires_at`/`lease_duration_seconds`
- `claude_code/05_session_states.json` session_closed — set `inbox_registered: true`
- `test_mcp_server.py:157` — anonymize `git:github.com/rore/pallium` container_ref to generic placeholder
- `test_relay_wake_fixtures.py` — assert `ambiguous_retry` outcome == `"ambiguous"`; add outcome→wake-state contract mapping cross-check

**Constraints:** No production code. Fixture/test changes only. No new files.

**Completion criteria:** `pytest tests/test_relay_wake_fixtures.py tests/test_mcp_server.py -x -q` passes clean.

**Risk:** Routine

**Complexity:** Simple

**Reason:** —

**Approach:** Edit the 5 fixture files and 2 test files directly; extend contract.json with `outcome_wake_state_map` for the cross-check.

**Verification:** `pytest tests/test_relay_wake_fixtures.py tests/test_mcp_server.py tests/test_relay_wake_contract.py -x -q`

**State:** Ready to implement
<!-- agent-workflow:end -->
