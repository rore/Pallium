---
id: fix-relay-receive-mcp-lifecycle
title: Add MCP relay receive and acknowledgement lifecycle
status: active
priority: high
commitment: committed
milestone: pallium-relay
lane: defect
---

## Summary

Agents have no supported MCP path for mid-turn or recovery mail handling. The
only available tools are passive (hook injection) or address-book queries
(`pallium_relay_recipients`). When hook delivery fails or a message arrives
mid-turn, agents fall back to raw HTTP `/relay/turn` and manual ACK, exposing
claim tokens and creating claimed-but-not-delivered state. This is a defect in
the MCP surface, confirmed by live transcript evidence (2026-08-27).

## What is missing

1. A `pallium_relay_receive` tool that claims and acknowledges pending
   deliveries using injected session scope — no model-supplied identity, no
   claim token exposure, no separate ACK step.
2. A safe reply path after manual receive: `pallium_relay_reply` must work on
   the `delivery_id` returned by `pallium_relay_receive`.
3. Corrected `pallium_relay_recipients` description: address book, not inbox.
4. Skill and AGENTS.md guidance distinguishing automatic hook/wake delivery
   from explicit MCP receive (recovery only) and prohibiting curl.

## Design

**`pallium_relay_receive(max_messages=1)`**
- Uses injected container_ref, actor_ref, agent_ref, thread_ref from Pallium
  session scope; no model-supplied identity accepted.
- Claims and immediately ACKs in one atomic step (same as hook admission);
  no claim tokens visible to the model.
- Returns: `[{delivery_id, sender_runtime, sender_session_ref, payload,
  in_reply_to, expires_at}]`, `has_more: bool`, `remaining_count: int`.
- Idempotent: already-delivered messages are never returned; double-delivery
  with hook or wake admission is impossible by design.
- `pallium_relay_reply(delivery_id, ...)` works immediately after receive
  because the delivery is already marked delivered.

**Recovery-only framing:** hook injection is the primary path; MCP receive is
the fallback for missed or mid-turn messages. It is not a polling loop and
must not substitute for wake.

## E2E required

Empty inbox; one message; many with backlog (max_messages cap); Unicode
payload; lease-recovery (prior expired claim returned to pending, receive
works again); duplicate receive/ACK (idempotent); restart (message stays
pending); wrong scope/session (authorization rejection); reply after receive;
no double delivery with hook/wake fallback.

## Done when

1. `pallium_relay_receive` is callable via MCP and returns pending deliveries
   using session-injected scope only.
2. `pallium_relay_reply` succeeds on a `delivery_id` returned by receive.
3. `pallium_relay_recipients` description says "address book, not inbox".
4. AGENTS.md and relay skill guidance prohibit curl and name hook vs receive.
5. All E2E cases above pass in CI without raw HTTP calls.
6. No claim tokens appear in MCP tool inputs, outputs, or documentation.
