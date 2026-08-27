<!-- agent-workflow:start -->
**Outcome:** Agents can receive and acknowledge pending Relay deliveries via MCP without raw HTTP, claim tokens, or model-supplied identity. pallium_relay_receive claims and returns deliveries using integration-injected scope only; pallium_relay_ack idempotently ACKs after the caller has the payload; pallium_relay_reply ACKs parent receipt; pallium_relay_recipients description says "address book, not inbox"; AGENTS.md distinguishes hook delivery from MCP receive. Automatic hook injection drains the complete eligible pending set in one envelope; no backlog paging or UX.

**Target:** app/mcp/server.py, app/mcp/client.py, api/routes.py, api/schemas.py, storage/sqlite_relay.py, core/relay.py, AGENTS.md, integrations/claude-code/hooks/, integrations/codex/hooks/, tests/

**Scope:** New: relay_acknowledge_by_scope in storage/sqlite_relay.py; RelayMcpAckRequest in api/schemas.py; POST /relay/deliveries/mcp-ack in api/routes.py; relay_receive + relay_mcp_ack in app/mcp/client.py; pallium_relay_receive + pallium_relay_ack tools in app/mcp/server.py; tests/test_relay_mcp_lifecycle.py (15 cases including RF-008 drain-all regression). Modified: pallium_relay_recipients docstring; pallium_relay_reply docstring; AGENTS.md relay guidance section. RF-008: max_chars=0 (unlimited) default in relay_turn; removed RELAY_TURN_MAX_MESSAGES=3 hard cap; removed backlog-notice reserve in storage; removed backlog UX from claude-code + codex hooks; updated format_relay default; updated test expectations.

**Constraints:** No claim tokens in MCP tool inputs, outputs, or docstrings. pallium_relay_receive must use only integration-injected env vars (PALLIUM_AGENT_REF as runtime, PALLIUM_THREAD_REF as session_ref); if absent, fail with clear error. No model-supplied runtime/session identity accepted. No change to /relay/turn, /relay/deliveries/ack, or existing relay contract. Additive schema changes only.

**Completion criteria:** pallium_relay_receive returns pending deliveries with opaque delivery_id; pallium_relay_ack confirms idempotently; lease expiry causes redelivery; pallium_relay_reply atomically ACKs; all listed E2E cases pass; no claim token in any MCP surface; pallium_relay_recipients description corrected; AGENTS.md guidance added.

**Risk:** High

**Complexity:** Moderate

**Reason:** Touches app/ (watch zone), api/ (public contract), storage/ (relay persistence). Reclassified High after architect review: `relay_reply_atomic` adds a new atomic path through the write-ahead log; receipt validation uses constant-time compare; MCP overflow protection changes _relay_text behavior. All changes are additive but the atomic reply + receipt path required non-trivial storage changes.

**Discovery:** resolve_context() uses PALLIUM_AGENT_REF (runtime) and PALLIUM_THREAD_REF (session_ref) from env — exactly the integration-bound identity gate. /relay/turn already claims deliveries and returns claim_token; /relay/deliveries/ack requires claim_token. New scope-based ACK endpoint bypasses claim_token by validating (delivery_id, runtime, session_ref, container_ref, actor_ref) match and delivery is claimed+unexpired. RelayTurnResponse already has has_more and remaining_count. pallium_relay_reply already works on delivery_id; atomic ACK can be added to the reply storage path.

**Material assumptions:**
- PALLIUM_AGENT_REF is a valid RelayRuntime literal (claude-code/codex/opencode) — if not, receive fails with a clear error. Disproved if: PALLIUM_AGENT_REF is missing or not a valid runtime. Action: fail at tool entry with message explaining which env var is absent.
- Scope-based ACK (delivery_id + runtime + session_ref + container_ref + actor_ref) is sufficient to uniquely identify the claimant without the raw claim_token — holds because the relay session registered with those exact values when it claimed. Disproved if: the storage model allows a single delivery to be claimed by two distinct sessions with the same scope (impossible by design — claim is atomic). Action: none expected.
- pallium_relay_reply atomic ACK: idempotent if delivery is already delivered (hook path already ACKed). Disproved if: there is a side effect on double-ACK. Action: verify storage acknowledge is idempotent on delivered state.

**Plan:**
1. storage/sqlite_relay.py: add relay_acknowledge_by_scope — finds delivery by delivery_id, validates recipient runtime+session_ref+container_ref+actor_ref match, state=claimed, lease not expired; marks delivered. Idempotent: if already delivered, return without error.
2. api/schemas.py: add RelayMcpAckRequest(delivery_id, runtime, session_ref, container_ref, actor_ref). Reuse RelayAckResponse.
3. api/routes.py: add POST /relay/deliveries/mcp-ack calling relay_acknowledge_by_scope.
4. app/mcp/client.py: add relay_receive(runtime, session_ref, max_chars) calling /relay/turn; add relay_mcp_ack(delivery_id, runtime, session_ref) calling /relay/deliveries/mcp-ack.
5. app/mcp/server.py: add pallium_relay_receive — resolves runtime from ctx.agent_ref, session_ref from ctx.thread_ref; fails if absent; calls relay_receive; strips claim_token from all deliveries before returning. Add pallium_relay_ack(delivery_id) — uses same injected scope, calls relay_mcp_ack. Update pallium_relay_recipients docstring. Update pallium_relay_reply docstring to note atomic ACK.
6. AGENTS.md: add relay section distinguishing hook delivery (automatic, no agent action) from pallium_relay_receive (recovery only); prohibit curl.
7. tests/test_relay_mcp_lifecycle.py: empty inbox; one message; many/backlog; Unicode; crash-after-claim (lease expiry → redelivery); duplicate ACK (idempotent); reply-with-ACK; hook-vs-MCP race (one active claim); restart; wrong scope/session; no double delivery.

**Verification plan:**
- pytest tests/test_relay_mcp_lifecycle.py -q → all cases pass
- pytest tests/ -q → no regressions
- grep -n "claim_token" app/mcp/server.py → zero matches in new code
- grep -n "PALLIUM_AGENT_REF\|PALLIUM_THREAD_REF" app/mcp/server.py → present in pallium_relay_receive guard

**Plan review:** Elevated risk, Moderate complexity. Architecture approved 2026-08-27 by relayarch (relay-reply-6a1fa006, delivery relay-delivery-23a044aba4c24fcb838aa14f504b422e). Self-review sufficient at this risk level per agent-workflow spec; relayarch approval obtained.

**Approvals:** relayarch approved 2026-08-27 (delivery relay-delivery-8f8def128cc54b658164f257038a8e5d). Corrections applied: constant-time compare_digest, receipt optional for delivered-state (backward compat), MCP overflow never truncates delivery handles, two-session isolation test added.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Branch: fix/relay-receive-mcp-lifecycle
PR: https://github.com/rore/Pallium/pull/76

### Changes delivered

- **RF-008**: `max_chars=0` (unlimited) default; complete pending set drained per turn; backlog UX removed from claude-code + codex hooks
- **P0 1**: Receipt-based MCP ACK — `receipt = sha256(claim_token)[:32]`; new `/relay/deliveries/mcp-ack`; `pallium_relay_ack` uses receipt
- **P0 2**: `PALLIUM_AGENT_REF="codex"` in codex `.mcp.json`; AGENTS.md documents trusted per-session `PALLIUM_THREAD_REF` binding
- **P0 3**: `relay_delivery_context` accepts `claimed` state atomically (validate receipt + mark delivered); `pallium_relay_reply` ACKs in one step
