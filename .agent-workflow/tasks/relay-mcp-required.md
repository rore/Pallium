# Relay MCP required startup

<!-- agent-workflow:start -->
**Outcome:** Codex waits for Pallium MCP startup instead of silently omitting Relay tools during a cold catalog build.

**Target:** Pallium Codex integration.

**Scope:** `app/cli/setup_codex.py` and `tests/test_codex_integration.py` only.

**Constraints:** Preserve all Pallium MCP tools, config idempotence, per-tool Relay approvals, and existing timeouts. Do not change global Codex timing, install configuration, restart Codex/Pallium, or merge.

**Completion criteria:** Generated Codex config marks Pallium required, retains the complete tool catalog, and remains idempotent; the focused Codex integration regression test passes.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Agent-redline classifies `app/cli/setup_codex.py` as a watched runtime/process path and the test as blue, with no boundary violation or extra checkpoint.

**Discovery:** The base installer writes `startup_timeout_sec = 10` but not `required = true`; the dedicated Relay profile already sets `required = true`. Official Codex MCP documentation gives optional servers a 1000 ms catalog grace, while a direct Pallium stdio initialization/list-tools probe completed in about 4.95 seconds and advertised all 27 tools. The observed task later lost every Pallium callable tool although the configured server, service, and direct MCP reply remained healthy. Existing integration coverage checks launch, environment, approvals, and idempotence but not required startup.

**Material assumptions:** Codex applies the configured startup timeout to required MCP servers, as documented; required-server initialization failure therefore fails Codex startup, a deliberate fail-visible tradeoff for this PR. Disproved by an official contract change, in which case stop and return to diagnosis. Marking Pallium required does not narrow its tool catalog because no base allowlist or denylist is added; disproved by generated config inspection, in which case stop and remove the narrowing source.

**Plan:** In `_ensure_mcp_server`, add the existing native Codex `required = true` setting beside the server environment and timeouts. Extend the existing config regression to assert required startup, absent `enabled_tools`/`disabled_tools`, and unchanged 10s/30s timeouts; existing assertions cover approvals and idempotence. Keep the change to those two files; stop if generated config narrows tools or loses idempotence. Run the focused test, the affected integration file, the required full suite once, and a smart-model result review before opening a PR.

**Verification plan:** When setup generates Codex MCP configuration, Pallium shall be required without narrowing the tool catalog or changing its timeouts, approvals, or idempotence → existing focused config regression with minimal assertions. When the coherent change is ready for review, existing Codex integration behavior shall remain intact → affected test file and repository-required full suite once. These checks validate generated configuration, not live Codex host startup.

**Plan review:** Approved by clean-context smart-model review; see `## Plan review`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

<!-- Ready to implement | Blocked | Ready for review -->
**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Discovery and pre-edit redline classification completed. No code changes yet.
- Clean-context Elevated-risk plan review completed; its catalog-preservation finding was incorporated before implementation.
- Implemented the shared base-config fix and regression assertions in the approved two-file scope.
- Verification exposed developer-profile leakage in unrelated hook tests; diagnosed it, delegated a separate isolated repair, and reran this branch in a clean CI-like home.

## Plan review

A clean-context smart-model review approved the revised two-file plan after requiring explicit coverage that base configuration has no tool allowlist/denylist and retains its 10s/30s timeouts. It confirmed the fail-visible startup tradeoff is deliberate and that config tests must not be presented as live-host validation.

## Evidence

- Observed Pallium stdio initialization/list-tools: about 4.95 seconds, 27 tools advertised.
- Official Codex MCP configuration: optional catalog grace defaults to 1000 ms; required servers use their startup timeout.
- Focused regression: 1 passed in 0.13s.
- Affected Codex integration file: 29 passed in 2.90s.
- Initial full suite: 2 unrelated deterministic failures caused by inherited `PALLIUM_HOOK_ACTOR_REF` and real `~/.pallium/hooks/state/sessions/session-test.json`; no changed code was implicated.
- Clean-home full suite: 4786 passed, 33 skipped, 2 xfailed in 241.78s.

## Result review

- Pending.
