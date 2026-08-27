<!-- agent-workflow:start -->
**Outcome:** Phase 0 of add-wake-first-relay-delivery documented and executable — decision record at docs/designs/017-relay-wake-phase0.md and sanitized adapter fixtures at tests/relay/wake/fixtures/; MCP relay error surface fixed in app/mcp/server.py.

**Target:** docs/designs/, tests/relay/wake/fixtures/, app/mcp/server.py, tests/fixtures/relay_wake/contract.json

**Scope:** New files: docs/designs/017-relay-wake-phase0.md, tests/relay/wake/fixtures/ (21 JSON stubs + contract). Modified: app/mcp/server.py (_bounded_error fix), tests/test_mcp_server.py (+1 E2E test). New: tests/test_mcp_server_utils.py (6 tests), tests/test_relay_wake_fixtures.py (6 tests). Probe traces: .local/phase0-probes/ (gitignored).

**Constraints:** No internal names (xlm/pelican/clmia/sap-dev) in committed docs or fixtures. No external system names. No production wake behavior. MCP fix must not change relay tool signatures.

**Completion criteria:** 017 decision record written covering all three runtimes; fixture files cover 7 cases per runtime; all fixtures validated by tests/test_relay_wake_fixtures.py; _bounded_error preserves status_code and strips Pydantic input+sibling fields; tests pass; CI passes.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** app/mcp/server.py is in the watch zone (app/**); redline detects Elevated. No red-zone paths touched; no checkpoint required.

**Discovery:** app/mcp/server.py MCP bug found during relay 422 debugging: _bounded_error dropped status_code (extracted only error+detail keys), Pydantic 422 detail inflated past 2000-char budget due to input field echoing the full payload, and _strip_pydantic_input reconstructed detail as only {detail:[...]} silently dropping sibling fields. All three fixed together.

**Material assumptions:**
- All fixture files are reference data validated by tests/test_relay_wake_fixtures.py; no production behavior depends on them until adapter PRs (3–5).
- The _bounded_error fix is a pure error-surface improvement; it does not change relay semantics.
- Phase 0 probe traces were captured for Codex (Windows stdio 2026-08-27) and OpenCode (2026-08-27). Verdicts are transport-confirmed (partial) — full seven-case journeys are not yet observed; gates listed in 017 per runtime.

**Plan:** 1. Write 017 decision record synthesising Phase 0 findings. 2. Write per-runtime fixture stubs (7 cases × 3 runtimes + contract.json). 3. Fix _bounded_error in app/mcp/server.py. 4. Add unit tests in tests/test_mcp_server_utils.py. 5. Add fixture loader tests in tests/test_relay_wake_fixtures.py. 6. Commit, open PR, send to relayarch.

**Verification plan:**
- `pytest tests/test_mcp_server_utils.py tests/test_relay_wake_fixtures.py -q` → 12 passed, 1 skipped (test_mcp_server.py skips locally — mcp import fails on Windows pywintypes; E2E test runs in CI on Linux)
- `pytest tests/ -q` → 1171 passed, pre-existing failure: `test_config.py::test_prompt_variants_legacy_fallback_unaffected` fails on main before this branch (confirmed)

**Plan review:** self — Elevated risk, Simple complexity; no red-zone touched, no checkpoint required.

**Approvals:** Elevated risk requires clean architecture review. Architecture gate: relayarch via Relay. Second-pass blockers addressed 2026-08-27; PR #73 ready for merge.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Branch: feat/relay-wake-phase0-pr1

- Wrote docs/designs/017-relay-wake-phase0.md: Phase 0 decision record. Verdicts are transport-confirmed (partial) — Codex proves initialize + thread/queue/add transport; OpenCode proves 204 ACK + metadata-not-persisted. Full seven-case journeys unobserved; gates listed per runtime. Transition table uses atomic CAS model for idle/busy race. OpenCode admission correlation uses text-content search (metadata not persisted). Claim-race row replaced with two CAS rows.
- Wrote tests/relay/wake/fixtures/contract.json and 7 cases × 3 runtimes. All fixtures have top-level expected_outcome and capability field in busy_queue input. Fixtures consistent with probe findings: codex fixtures use input[]+queuedSubmission; opencode fixtures use parts[] and text-content search for correlation.
- Added tests/test_relay_wake_fixtures.py: 6 tests — fixture count, valid outcomes (with nested states[] validation), phase0 coverage, busy_queue capability-specific (asserts both idle_wake→unavailable and busy_queue→triggered for all runtimes), ambiguous retry_issued required, nested states/scenarios contract.
- Fixed app/mcp/server.py: _bounded_error preserves status_code; _strip_pydantic_input preserves sibling fields.
- Added tests/test_mcp_server_utils.py (6 tests, no mcp dependency): status_code preservation, input/url stripping, 422 budget fit, sibling-field preservation, binary-search status_code, _relay_text internal regression.
- Added tests/test_mcp_server.py E2E test (TestBoundedErrorSurface): oversized 422 through server.call_tool("pallium_relay_send") — asserts status_code, stripped input/url, preserved sibling metadata. Skips locally on Windows (mcp pywintypes import failure); runs in CI.
- Pre-existing failure confirmed: test_config.py::test_prompt_variants_legacy_fallback_unaffected fails on main before this branch.
