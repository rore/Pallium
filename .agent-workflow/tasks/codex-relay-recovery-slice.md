<!-- agent-workflow:start -->
**Outcome:** Relay MCP receive, acknowledge, and reply can use an exact injected container/actor pair when their integration configuration lacks Relay scope, without weakening runtime-owned session identity.

**Target:** Pallium Relay MCP context and lifecycle tools.

**Scope:** `app/mcp/context.py`, `app/mcp/server.py`, `tests/test_mcp_context.py`, and `tests/test_relay_mcp_tools.py`. Add paired trusted scope resolution for `pallium_relay_receive`, `pallium_relay_ack`, and `pallium_relay_reply`, plus focused configured-scope, explicit-pair, rejection, and atomic receive-to-reply coverage.

**Constraints:** Use `origin/codex/relay-batch-wake-b2` only as reference; do not cherry-pick. Preserve the existing runtime-owned session resolution exactly. Reject missing, partial, invalid, or conflicting scope before HTTP. Do not add request-metadata diagnostics, batching, schema/migrations, admission/coordinator, Claude/OpenCode, wake-path, API, or unrelated documentation changes.

**Completion criteria:** (1) A fully configured MCP Relay scope continues to work unchanged. (2) An unscoped integration can call receive, ACK, and reply with an exact paired `container_ref` and `actor_ref`. (3) partial or conflicting scope reaches no HTTP client call. (4) a receive followed by reply using that pair atomically acknowledges the delivery.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Pre-edit redline verdict is GRAY: `app/mcp/context.py` and `app/mcp/server.py` are app watch surfaces, while tests are blue. The change is scoped to an MCP identity boundary and needs rejection-path and lifecycle verification, but touches no red checkpoint or boundary rule.

**Discovery:** `resolve_context` already obtains `thread_ref` only from integration/runtime sources. The Relay client consumes its `PalliumContext`, so a single paired-scope resolver can feed all three tools without changing storage or HTTP contracts. The reference branch contains this resolver alongside excluded metadata and batching work; only the resolver and tool parameter usage belong here.

**Material assumptions:** (1) `PalliumMcpClient` forwards its context scope to all three Relay calls; disprove with focused tool lifecycle tests and stop rather than changing HTTP. (2) resolving scope via `resolve_context(container_ref=..., actor_ref=...)` leaves runtime session resolution unchanged; disprove with the existing runtime session tests and stop rather than accepting model-supplied identity. (3) configured scope must remain authoritative; disprove with a canonical-equivalence or conflict test and reject the conflicting input.

**Plan:** Add a small `resolve_relay_context` helper in `app/mcp/context.py` that accepts only a validated pair, validates configured scope as a pair, canonicalizes the container value, and rejects explicit conflict with configured scope. Route only receive, ACK, and reply through it and expose paired optional scope inputs on those MCP tools. Reuse current client calls and serializers. Add focused context/tool tests, including the one receive-to-reply atomic journey. Stop and reclassify if implementation needs a different production surface or any request-metadata path.

**Verification plan:** When configured scope is present, each scoped MCP tool shall call the existing client with it unchanged -> mocked tool tests. When configuration lacks scope and a valid exact pair is supplied, receive then reply shall retrieve and atomically deliver the message -> ASGI-backed FastMCP lifecycle test. When either supplied/configured pair is partial, invalid, or conflicts, no client call shall occur -> parametrized mocked rejection tests. Run the focused tests, full affected test files, redline report, and workflow checker.

**Plan review:** Clean-context review `/root/relay_recovery_plan_review` (2026-09-01): approved. It verified that `PalliumMcpClient` applies context container/actor scope to receive, ACK, and reply, while receive alone derives runtime/session identity; delegating the accepted pair to `resolve_context` preserves that boundary.

**Approvals:** Not required at this risk level; the user has authorized the architect's bounded implementation direction.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-01: Discovery and pre-edit redline classification complete. Redline reports GRAY `app/**` watch paths, blue tests, and no boundary violation or checkpoint. Clean-context plan review approved the shared context-resolver approach; implementation may proceed.

## Evidence

- 2026-09-01: Focused paired-scope MCP regressions: 11 passed, 10 deselected.
- 2026-09-01: Full affected MCP context, Relay tool, and server files: 93 passed.
- 2026-09-01: Import-linter adapter reported no boundary violations; redline classified `app/mcp/context.py` and `app/mcp/server.py` as GRAY watch paths and tests as BLUE; `agent-workflow-check.py --slug codex-relay-recovery-slice` exited clean.

## Delivered changes

- 2026-09-01: Added the paired Relay scope resolver and routed only MCP receive, ACK, and reply through it. It validates both supplied and configured pairs, preserves configured scope authority, and leaves runtime session identity with `resolve_context`. Added tool-level rejection coverage and one unconfigured receive-to-atomic-reply lifecycle journey.