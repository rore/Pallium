<!-- agent-workflow:start -->
**Outcome:** Relay callers receive an actionable, fail-closed diagnostic when trusted container scope is missing, while standard Codex setup remains dynamically scoped across projects and the integration documentation accurately describes Relay routing versus History and memory scope.

**Target:** Pallium: `app/mcp/context.py`, `app/cli/setup_codex.py`, `tests/test_relay_mcp_tools.py`, `tests/test_codex_integration.py`, and `docs/codex-integration.md`.

**Scope:** Replace only the shared missing-Relay-scope message in `resolve_relay_context`; explain why standard Codex MCP setup deliberately omits a fixed `PALLIUM_CONTAINER_REF`; correct Relay routing and missing-scope troubleshooting documentation; add focused caller-surface regression coverage.

**Constraints:** Preserve distinct blank, invalid-configured, and conflicting-scope errors. Preserve fail-closed behavior and avoid HTTP side effects on validation failures. Never derive container scope from the working directory or session identifiers. Do not mix hook delivery with MCP receive or change runtime-owned receive identity. Do not redesign routing, add dependencies, or change the installed checkout.

**Completion criteria:** Missing scope tells the caller to copy the injected `container_ref` exactly. When no scope was injected, the diagnostic names enabled/trusted hooks and intentional hookless trusted configuration as checks, without claiming a detected cause. All seven Relay MCP tools return the shared missing diagnostic without HTTP; explicit blank, invalid configured, and conflicting scope retain their existing distinct errors without HTTP. Standard Codex setup continues to omit a global `PALLIUM_CONTAINER_REF`. Documentation states that Relay routes across containers on the same local service while History and derived memory retain container scope. Focused, affected-subsystem, last-failed, and full test checks pass before review.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** The intended production files are under the policy's `app/**` watch zone. Clean-context redline classification found no red-zone path, checkpoint, or boundary violation.

**Discovery:** All seven Relay MCP caller surfaces route scope validation through `app.mcp.context.resolve_relay_context`. `_mcp_env_toml` configures the local service and runtime identity but intentionally does not pin a container. Current integration documentation incorrectly tells missing Relay peers to use the same repository even though Relay routes across containers on one service. The observed failure is missing trusted scope, not evidence of a delivery or routing defect.

**Material assumptions:** (1) All Relay MCP callers continue to use the shared resolver; if implementation discovery finds a bypass, stop and re-plan before changing caller code. (2) One standard Codex MCP registration serves tasks across projects, so it must not set one fixed global container; if setup is actually per-project, stop and re-plan. (3) Valid injected scope continues to route successfully; if a valid-scope reproduction fails, stop rather than changing routing under this task. Clean-context review confirmed all three assumptions against current source and focused baseline tests.

**Plan:** 1. Update the shared missing-scope diagnostic without changing validation branches. 2. Document the dynamic-scope intent at `_mcp_env_toml` and assert setup still omits a fixed container. 3. Correct the integration guide's routing, setup, and troubleshooting text. 4. Expand focused caller-surface tests so missing scope is exercised through all seven Relay tools and blank, invalid-configured, and conflicting scope remain distinct without HTTP. 5. Run focused and required repository checks, review the diff, then ship through the normal branch and pull-request workflow.

**Verification plan:** Actionable missing-scope wording and no HTTP across all seven Relay MCP tools -> parameterized FastMCP caller-surface test. Distinct explicit-blank, invalid-configured, and conflict errors plus no HTTP -> exact-message FastMCP tests. Dynamic standard setup with no global container -> `_ensure_mcp_server` content assertion for absence of `PALLIUM_CONTAINER_REF`. Accurate cross-container Relay versus container-scoped History/memory guidance -> targeted documentation diff review against current routing and hook behavior. Regression -> focused test nodes, `tests/test_relay_mcp_tools.py tests/test_codex_integration.py`, `pytest --lf`, full `tests/ -x -q`, agent-workflow/redline checks, and final diff review.

**Plan review:** Clean-context reviewer `/root/plan_review_relay_scope_docs` initially blocked on Work Record markers/state, criterion-to-check mapping, and complete seven-tool caller coverage. Those findings were incorporated; after a fresh GRAY/watch redline verdict and a clean workflow check, the reviewer returned APPROVE with no remaining findings.

**Approvals:** User granted blanket approval for tasks received from the architect.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

2026-09-09 — Replaced only the shared missing-container branch in `resolve_relay_context` with actionable, non-diagnostic guidance; all other validation branches and every Relay caller remain unchanged.

2026-09-09 — Documented that standard Codex setup deliberately leaves project scope dynamic, corrected cross-container Relay versus History/memory scope guidance, and added all-seven-tool caller-surface coverage for missing, invalid-configured, explicit blank, and conflicting scope without HTTP.

2026-09-09 — `apply_patch` failed with the documented Windows `CreateProcessWithLogonW failed: 1327`; the change used deterministic exact replacements limited to the five planned files.

## Evidence

2026-09-09 — Focused validation/setup nodes: 30 passed. Complete affected files: 90 passed. Last-failed check: no selected failures. The first full run exposed two unrelated tests inheriting live `PALLIUM_HOOK_ACTOR_REF=Rotem Hermon`; both passed when that override was removed, and the clean full suite then passed 4,687 tests with 32 skips and 2 expected failures.

2026-09-09 — Import-boundary adapter passed with no violations; fresh redline verdict is GRAY/watch with no checkpoint or boundary violation; agent-workflow checker exits 0; `git diff --check` and Python compile checks pass. Ruff was unavailable in the existing repository environment.
