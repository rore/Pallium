<!-- agent-workflow:start -->
**Outcome:** Phase 0 of add-wake-first-relay-delivery documented and executable — decision record at docs/designs/017-relay-wake-phase0.md and sanitized adapter fixtures at tests/relay/wake/fixtures/; MCP relay error surface fixed in app/mcp/server.py.

**Target:** docs/designs/, tests/relay/wake/fixtures/, app/mcp/server.py

**Scope:** New files: docs/designs/017-relay-wake-phase0.md, tests/relay/wake/fixtures/ (21 JSON stubs + contract). Modified: app/mcp/server.py (_bounded_error fix). New: tests/test_mcp_server_utils.py.

**Constraints:** No internal names (xlm/pelican/clmia/sap-dev) in committed docs or fixtures. No external system names. No production wake behavior. MCP fix must not change relay tool signatures.

**Completion criteria:** 017 decision record written covering all three runtimes; fixture files cover 7 cases per runtime; all fixtures validated by tests/test_relay_wake_fixtures.py; _bounded_error preserves status_code and strips Pydantic input+sibling fields; tests pass; CI passes.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** app/mcp/server.py is in the watch zone (app/**); redline detects Elevated. No red-zone paths touched; no checkpoint required.

**Discovery:** app/mcp/server.py MCP bug found during relay 422 debugging: _bounded_error dropped status_code (extracted only error+detail keys), Pydantic 422 detail inflated past 2000-char budget due to input field echoing the full payload, and _strip_pydantic_input reconstructed detail as only {detail:[...]} silently dropping sibling fields. All three fixed together.

**Material assumptions:**
- All fixture files are reference data validated by tests/test_relay_wake_fixtures.py; no production behavior depends on them until adapter PRs (3–5).
- The _bounded_error fix is a pure error-surface improvement; it does not change relay semantics.
- Phase 0 verdicts are based on official documentation and integration tests; installed-runtime probes are listed as unmet gates in 017.

**Plan:** 1. Write 017 decision record synthesising Phase 0 findings. 2. Write per-runtime fixture stubs (7 cases × 3 runtimes + contract.json). 3. Fix _bounded_error in app/mcp/server.py. 4. Add unit tests in tests/test_mcp_server_utils.py. 5. Add fixture loader tests in tests/test_relay_wake_fixtures.py. 6. Commit, open PR, send to relayarch.

**Verification plan:**
- `pytest tests/test_mcp_server_utils.py tests/test_relay_wake_fixtures.py -x -q` → 9 passed (observed 2026-08-27)
- `pytest tests/ -x -q` passes minus pre-existing main failure: `test_config.py::test_prompt_variants_legacy_fallback_unaffected` fails on main before this branch (confirmed by checking out main and running the test)

**Plan review:** self — Elevated risk, Simple complexity; no red-zone touched, no checkpoint required.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Branch: feat/relay-wake-phase0-pr1

- Wrote docs/designs/017-relay-wake-phase0.md: corrected Phase 0 verdict, per-runtime admission handshakes, 7-case gate, state transition table, numeric bounds, open decisions. Updated: verdicts marked unconfirmed (probe gates listed), numeric bounds marked provisional with measurement gates, Case 3 clarified as capability-specific, transition table expanded to cover capability-disable split, expiry per state, claim race, late callbacks, and canonical matrix reference.
- Wrote tests/relay/wake/fixtures/contract.json (adapter outcome contract, no duplicate wake_states) and 7 cases × 3 runtimes (codex, opencode, claude_code) as deterministic JSON protocol stubs.
- Added tests/test_relay_wake_fixtures.py: 5 tests validating all 21 fixtures parse, all adapter outcomes are valid, all phase0_cases covered per runtime, busy_queue is capability-specific, and ambiguous retry is not issued without idempotency proof.
- Fixed app/mcp/server.py: _bounded_error preserves status_code in all paths; _strip_pydantic_input now preserves sibling fields via {**detail, "detail": stripped_items} instead of reconstructing only {detail:[...]}.
- Added tests/test_mcp_server_utils.py — 5 unit tests (no mcp package dependency), including sibling-field preservation test.
- Pre-existing failure confirmed: test_config.py::test_prompt_variants_legacy_fallback_unaffected fails on main before this branch.
