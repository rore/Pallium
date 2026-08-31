---
id: fix-relay-hook-reply-scope-resolution
title: Make hook-delivered Relay replies resolve injected scope
status: queued
priority: high
commitment: uncommitted
milestone: pallium-relay
lane: defect
---

## Summary

A hook-delivered Relay reply with only its delivery ID and message returned HTTP 422
because the MCP client omitted `container_ref` and `actor_ref`, despite the tool
contract treating them as integration-resolved optional scope. Retrying with the
injected scope succeeded. This makes the documented hook reply path unreliable.

## In Scope

- Trace scope resolution from the hook-delivered tool call through the MCP client
  and Relay reply endpoint.
- Make `pallium_relay_reply(delivery_id, message)` resolve injected scope without
  model-supplied identity when that scope is available.
- Keep explicit scope validation and atomic reply/ACK behavior unchanged.
- Add E2E coverage through the same hook/MCP surface: delivery-ID-only reply,
  missing injected scope fail-closed, explicit conflicting scope, retry/idempotence,
  and persisted delivery status.

## Out of Scope

- Changing Relay routing, receive identity, queue wake behavior, service
  configuration, or raw HTTP guidance.

## Done When

1. A hook-delivered reply succeeds with delivery ID and message only when its
   integration-owned scope is present.
2. Missing or conflicting scope fails closed without a partial reply or ACK.
3. The E2E test observes the reply and parent delivery through normal status
   reads, including retry/idempotence.

## Notes

Dogfood incident 2026-08-31: the first `pallium_relay_reply` call returned 422
for missing `container_ref` and `actor_ref`; the same reply succeeded when those
injected values were supplied. This is a generic MCP scope-resolution defect, not
an identity-binding or wake qualification result.