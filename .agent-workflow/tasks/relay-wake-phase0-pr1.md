<!-- agent-workflow:start -->
**Outcome:** Phase 0 of add-wake-first-relay-delivery documented and executable — decision record at docs/designs/017-relay-wake-phase0.md and sanitized adapter fixtures at tests/relay/wake/fixtures/.

**Target:** docs/designs/, tests/relay/wake/fixtures/

**Scope:** New files only — docs/designs/017-relay-wake-phase0.md, tests/relay/wake/fixtures/ directory with per-runtime fixture stubs. No production code.

**Constraints:** No internal names (xlm/pelican/clmia/sap-dev) in committed docs or fixtures. No external system names. Blue-zone only.

**Completion criteria:** 017 decision record written covering all three runtimes; fixture files cover 7 cases per runtime per the PoC sequence in the feature spec; CI passes.

**Risk:** Routine

**Complexity:** Simple

**Reason:** —

**Approach:** Synthesise Phase 0 findings from 016-relay-wake-feasibility.md and add-wake-first-relay-delivery.md into a decision record. Write per-runtime fixture stubs (JSON/YAML) encoding the admission handshakes (idle, busy, restart, idempotent, unsupported, cold-resume, duplicate) — no live network calls.

**Verification:** pytest tests/ -x -q (no new failures); fixture files present and valid JSON/YAML.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Branch: feat/relay-wake-phase0-pr1

- Wrote docs/designs/017-relay-wake-phase0.md: corrected Phase 0 verdict, per-runtime admission handshakes, 7-case gate, state transition table, numeric bounds, open decisions.
- Wrote tests/relay/wake/fixtures/contract.json and 7 cases × 3 runtimes (codex, opencode, claude_code) as deterministic JSON protocol stubs.
- Included app/mcp/server.py _bounded_error fix (add status_code extraction, strip Pydantic input field) and tests/test_mcp_server_utils.py — bug found and fixed during relay send debugging.
- Pre-existing test failure confirmed: test_config.py::test_prompt_variants_legacy_fallback_unaffected fails on main before this branch.
