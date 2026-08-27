<!-- agent-workflow:start -->
**Outcome:** Phase 0 of add-wake-first-relay-delivery documented and executable — decision record at docs/designs/017-relay-wake-phase0.md and sanitized adapter fixtures at tests/relay/wake/fixtures/; MCP relay error surface fixed in app/mcp/server.py.

**Target:** docs/designs/, tests/relay/wake/fixtures/, app/mcp/server.py

**Scope:** New files: docs/designs/017-relay-wake-phase0.md, tests/relay/wake/fixtures/ (21 JSON stubs + contract). Modified: app/mcp/server.py (_bounded_error fix). New: tests/test_mcp_server_utils.py.

**Constraints:** No internal names (xlm/pelican/clmia/sap-dev) in committed docs or fixtures. No external system names. No production wake behavior. MCP fix must not change relay tool signatures.

**Completion criteria:** 017 decision record written covering all three runtimes; fixture files cover 7 cases per runtime; _bounded_error preserves status_code and strips Pydantic input field; tests pass; CI passes.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** app/mcp/server.py is in the watch zone (app/**); redline detects Elevated. No red-zone paths touched; no checkpoint required.

**Discovery:** app/mcp/server.py MCP bug found during relay 422 debugging: _bounded_error dropped status_code (extracted only error+detail keys) and Pydantic 422 detail inflated past 2000-char budget due to input field echoing the full payload. Both fixed together.

**Material assumptions:**
- All fixture files are reference data only; no production behavior depends on them until adapter PRs (3–5).
- The _bounded_error fix is a pure error-surface improvement; it does not change relay semantics.

**Plan:** 1. Write 017 decision record synthesising Phase 0 findings. 2. Write per-runtime fixture stubs (7 cases × 3 runtimes + contract.json). 3. Fix _bounded_error in app/mcp/server.py. 4. Add unit tests in tests/test_mcp_server_utils.py. 5. Commit, open PR, send to relayarch.

**Verification plan:** pytest tests/ -x -q passes (minus pre-existing main failure); all 3 _bounded_error unit tests pass; fixture JSON files valid and present; 017 decision record covers all three runtimes.

**Plan review:** self — Elevated risk, Simple complexity; no red-zone touched, no checkpoint required.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Branch: feat/relay-wake-phase0-pr1

- Wrote docs/designs/017-relay-wake-phase0.md: corrected Phase 0 verdict, per-runtime admission handshakes, 7-case gate, state transition table, numeric bounds, open decisions.
- Wrote tests/relay/wake/fixtures/contract.json and 7 cases × 3 runtimes (codex, opencode, claude_code) as deterministic JSON protocol stubs.
- Fixed app/mcp/server.py: _bounded_error now includes status_code extraction and _strip_pydantic_input strips input/url fields before budget check.
- Added tests/test_mcp_server_utils.py — 3 unit tests, no mcp package dependency.
- Pre-existing failure confirmed: test_config.py::test_prompt_variants_legacy_fallback_unaffected fails on main before this branch.
- Risk re-classified Routine→Elevated post-commit: app/mcp/server.py is in watch zone (app/**).
