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

1. `pallium_relay_receive` — claims pending deliveries using injected session
   scope, returns payload plus an opaque receipt/lease; no model-supplied
   identity, no raw claim token exposed.
2. `pallium_relay_ack` — idempotent confirmation after the caller has the
   result; if the caller crashes or never ACKs, the lease expires and the
   message is eligible for redelivery (at-least-once guarantee).
3. `pallium_relay_reply` atomically ACKs the parent receipt while creating the
   reply, so the normal receive→reply path needs no explicit ACK call.
4. Hook/wake and MCP recovery share the same claim primitive; concurrent
   attempts yield one active claim.
5. Corrected `pallium_relay_recipients` description: address book, not inbox.
6. Skill and AGENTS.md guidance distinguishing automatic hook/wake delivery
   from explicit MCP receive (recovery only) and prohibiting curl.

## Design

**`pallium_relay_receive(max_messages=1)`**
- Uses injected container_ref, actor_ref, agent_ref, thread_ref from Pallium
  session scope; no model-supplied identity accepted.
- Claims deliveries, returns payload + opaque receipt handle; holds a lease.
- Returns: `[{receipt, delivery_id, sender_runtime, sender_session_ref,
  payload, in_reply_to, expires_at}]`, `has_more: bool`, `remaining_count: int`.
- Does NOT mark delivered until ACK arrives or reply is sent.

**`pallium_relay_ack(receipt)`**
- Idempotent confirmation after the caller has the payload in context.
- Marks delivery as delivered; releases the lease.
- Safe to call multiple times.

**`pallium_relay_reply(delivery_id, message)`**
- Atomically ACKs the held receipt for delivery_id while creating the reply.
- Receive→reply path: no explicit ACK call required.
- Already exists; behavior extended to handle the receipt ACK.

**Lease / redelivery:** missing ACK within the lease window returns the
delivery to `pending`, eligible for redelivery by the next receive call.
Guarantees at-least-once delivery, not impossible exactly-once consumption.

**Recovery-only framing:** hook injection is the primary path; MCP receive is
the fallback for missed or mid-turn messages. It is not a polling loop and
must not substitute for wake.

## E2E required

Empty inbox; one message; many with backlog (max_messages cap); Unicode
payload; crash-after-claim (lease expires, redelivery succeeds); lease-expiry
redelivery; duplicate ACK (idempotent); reply-with-ACK (no separate ACK
needed); hook-vs-MCP race (one active claim, no double delivery); restart
(message stays pending); wrong scope/session (authorization rejection); no
message loss under any failure scenario.

## Done when

1. `pallium_relay_receive` is callable via MCP and returns pending deliveries
   using session-injected scope only, with an opaque receipt.
2. `pallium_relay_ack` confirms receipt idempotently; unclaimed lease →
   redelivery.
3. `pallium_relay_reply` atomically ACKs the parent receipt.
4. Hook/wake and MCP recovery share the same claim primitive.
5. `pallium_relay_recipients` description says "address book, not inbox".
6. AGENTS.md and relay skill guidance prohibit curl and name hook vs receive.
7. All E2E cases above pass in CI without raw HTTP calls.
8. No claim tokens appear in MCP tool inputs, outputs, or documentation.
