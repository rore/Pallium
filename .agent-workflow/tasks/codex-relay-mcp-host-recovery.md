<!-- agent-workflow:start -->
**Outcome:** Codex Relay MCP recovery is demonstrably exact-session on a fresh MCP child and fails closed with an explicit host-restart instruction on a stale child that predates integration setup.

**Target:** Pallium Codex setup and Relay MCP runtime-identity boundary.

**Scope:** `app/mcp/context.py`, `app/mcp/server.py`, `app/cli/setup_codex.py` only if discovery disproves the shipped env allowlist, focused MCP/setup caller-surface tests, `docs/codex-integration.md`, and Relay roadmap/Work Record state. Do not touch Codex hooks unless the separate vnext workstream confirms sequencing and a test proves they are required.

**Constraints:** Preserve runtime-owned identity and fail closed; never accept model-supplied session identity, scrape an unverified parent, or mix hook delivery with MCP receive in one session. Reuse the shipped `env_vars = ["CODEX_THREAD_ID", "CODEX_SESSION_ID"]`. Keep deterministic tests fast and avoid host restarts in the normal suite. Coordinate any integration/hook edit with `vnext-dev` through Relay.

**Completion criteria:** (1) A newly launched MCP child receiving `CODEX_THREAD_ID`, and separately the compatibility `CODEX_SESSION_ID`, can claim and ACK only its exact pending delivery through the real MCP tool surface. (2) A child launched without runtime identity before setup/reload claims nothing and returns an explicit restart/reload instruction. (3) Restarting/relaunching the child with runtime-owned identity succeeds without any model-supplied identity. (4) Existing hook-delivery behavior and identity/scope isolation remain unchanged. (5) The roadmap marks RW-006 complete only after deterministic caller-surface coverage and an isolated live witness.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Pre-edit redline verdict is GRAY because `app/**` runtime paths are watch surfaces; tests/docs are blue and no boundary or checkpoint applies. Moderate complexity covers process-lifecycle qualification, fail-closed messaging, and an isolated live witness across stale/fresh children.

**Discovery:** Commit `50b8ad89` already ships the supported Codex `env_vars` allowlist. `app/mcp/context.py` resolves only `PALLIUM_THREAD_REF` or runtime-owned `CODEX_THREAD_ID`/`CODEX_SESSION_ID`; `pallium_relay_receive` refuses missing identity. Existing tests cover resolver units but do not launch the real MCP child before/after setup or require actionable stale-host restart guidance. The remaining defect is lifecycle qualification plus error clarity, not a new identity mechanism.

**Material assumptions:** (1) Codex forwards allowlisted `CODEX_THREAD_ID`/`CODEX_SESSION_ID` to a newly launched stdio MCP child; disprove with the caller-surface child test/live witness and stop before inventing another identity path. (2) The stale child cannot reload its environment; disprove if a supported Codex reload API exists, then use it instead of restart guidance. (3) The installed MCP SDK can drive the real `python -m app.run mcp` stdio child deterministically without a model or external network; disprove if the child cannot be exercised through stdio, then return to planning rather than substituting an in-process FastMCP test. (4) Hooks are not required; disprove only with a failing fresh-child lifecycle test and coordinate with `vnext-dev` before expanding scope.

**Plan:** 1. Reuse the existing setup allowlist and runtime resolver. 2. Add one shared actionable missing-Codex-identity error that names restart/reload while retaining the generic fail-closed contract for other runtimes. 3. Add a mandatory fast subprocess/stdio lifecycle test that launches the real `python -m app.run mcp` child for stale identity, fresh `CODEX_THREAD_ID`, compatibility `CODEX_SESSION_ID`, exact-session isolation, receive/ACK, and relaunch recovery. An inability to drive that surface returns the task to planning; in-process FastMCP tests cannot substitute. 4. Run focused setup/context/MCP suites plus workflow/redline/diff checks. 5. Update docs/roadmap only after the deterministic gate passes, then run one isolated fresh-host live witness without mixing with hook delivery. Stop and return to planning if Codex does not forward either allowlisted variable to a fresh child.

**Verification plan:** When a fresh MCP child inherits `CODEX_THREAD_ID` or `CODEX_SESSION_ID`, Relay shall claim and ACK only that session's delivery -> real MCP caller-surface lifecycle tests. When a child lacks runtime identity, Relay shall make no HTTP/claim call and shall instruct restart/reload -> stale-child regression. When the child is relaunched with identity, the same pending delivery shall become claimable once -> stale-to-fresh lifecycle regression. Existing scope conflicts and hook/MCP isolation shall remain fail-closed -> affected existing suites. Installed Codex fresh-host witness shall confirm runtime forwarding without manual/model identity.

**Plan review:** Approved clean-context re-review (`/root/mcp_plan_review`): prior real-stdio caller-surface blocker resolved.

**Approvals:** Not required at this risk level; the user explicitly requested closing all open bugs and has standing approval for managed PRs.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

- 2026-09-05: Established scope, completed discovery, and classified the intended diff GRAY/Elevated with no boundary or checkpoint. No production code edited.

## Evidence

- Pre-edit redline review `/root/mcp_redline`: GRAY `app/**` watch paths, blue tests/docs/Work Record, no boundary risk or required checkpoint.
- Discovery `/root/mcp_discovery`: shipped allowlist/resolver are correct; remaining gap is stale/fresh child lifecycle qualification and actionable restart guidance.

## Plan review

Initial verdict: Blocked pending one plan correction.

The identity boundary and scope are consistent with the existing code: context.py already prefers integration-owned PALLIUM_THREAD_REF and Codex-owned CODEX_THREAD_ID/CODEX_SESSION_ID, server.py fails closed before calling Relay, and setup_codex.py already emits the two-variable allowlist. The proposed actionable Codex-only error is appropriately scoped and must not weaken the generic fail-closed behavior for other runtimes.

Material blocker: the completion criteria require a newly launched MCP child to claim and ACK through the real MCP tool surface, but Plan step 3 says to use subprocess/stdio “only if the existing harness supports it cleanly.” That conditional permits a direct in-process FastMCP test to pass while the actual Codex-launched stdio child still drops the runtime environment. Revise the plan and verification to require a deterministic subprocess/stdio caller-surface test for both allowlisted variables, stale-child failure/restart guidance, exact-session isolation, receive/ACK, and relaunch recovery. A harness limitation should return the task to planning, not downgrade the gate; the isolated installed-host witness remains a separate check. No production, test, hook, or documentation change was made during this review.

Correction applied; re-review completed.

Re-review verdict: Approved. The material blocker is resolved: the material assumptions now require the installed SDK to drive the real python -m app.run mcp stdio child, and the plan explicitly requires a mandatory subprocess/stdio lifecycle test covering stale identity, both Codex variables, isolation, receive/ACK, and relaunch recovery. Harness inability returns the task to planning, so no weaker in-process substitute can satisfy the gate. The plan is ready for implementation within the recorded scope; no production, test, hook, or documentation change was made during review.
