---
id: add-relay-retention-and-lifecycle-hardening
title: Add Relay retention and lifecycle hardening
status: queued
priority: medium
commitment: committed
milestone: pallium-relay
lane: stabilization-safety
---

## Summary

Bound the storage lifetime of expired and old terminal Relay records so R1 does
not accumulate messages and deliveries indefinitely. Keep recent operational
evidence long enough to diagnose delivery behavior, then remove it through the
existing cleaner lifecycle.

## Why

Relay expiry currently stops delivery and ages out of the dashboard's actionable
window, but the expired message and delivery records remain in SQLite forever.
That is acceptable for initial validation, not for a durable local service whose
sessions and messages continuously accumulate.

## In Scope

- define explicit retention windows for expired and terminal Relay messages,
  deliveries, and obsolete session-discovery records
- use the existing cleaner process rather than adding another worker
- delete message and delivery state transactionally without leaving orphan rows
- preserve pending or actively claimed deliveries until they become terminal
- keep dashboard totals operationally honest after cleanup and expose the last
  Relay cleanup result without retaining message payloads for metrics
- cover expiry to cleanup, mixed delivery states, active claims, replies, alias
  reuse, repeated cleanup, and scope isolation through public-surface E2E tests

## Out of Scope

- a searchable Relay message archive
- retaining payload history as semantic memory
- user-configurable retention administration in the first slice
- changing next-turn delivery, addressing, or acknowledgement semantics

## Done When

1. Expired and sufficiently old terminal Relay records are removed automatically
   after a documented bounded window.
2. Pending and actively claimed deliveries cannot be deleted prematurely.
3. Cleanup leaves no orphan messages, deliveries, replies, aliases, or misleading
   dashboard alerts.
4. Full-lifecycle E2E coverage verifies send or expiry through cleanup using the
   same HTTP, MCP, hook, and dashboard read surfaces callers use.

## Notes

This is R1 operational hardening, not evidence for moving to R2. Choose concrete
retention windows when implementation starts, based on the diagnostic window the
dashboard actually needs.
