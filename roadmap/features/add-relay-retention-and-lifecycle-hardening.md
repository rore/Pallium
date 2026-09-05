---
id: add-relay-retention-and-lifecycle-hardening
title: Harden Relay session and message lifecycle
status: queued
priority: high
commitment: committed
milestone: pallium-relay
lane: stabilization-safety
---

## Summary

Make session addressing and message outcomes honest when a recipient is inactive,
closed, unavailable, or never responds. Bound old terminal records through the
existing cleaner after preserving enough evidence to diagnose delivery behavior.

This item consumes the destination and delivery outcomes defined by
`add-wake-first-relay-delivery` S2. It does not decide whether a native transport
failure is terminal, and it must not use age alone to turn a resumable recipient
or durable pending delivery into failure.

## Why

Relay currently retains discovered sessions and terminal messages indefinitely.
An old named session can therefore remain addressable after its working directory
or runtime is gone. A sender can intentionally address that exact session, but the
result must not look like a healthy wake or a lost message.

Delivery and response are also separate contracts. `delivered` means the message
entered the recipient's context and was acknowledged; it does not promise that the
agent replied or completed the request. Undelivered messages must remain durable
for next-turn fallback until expiry, while acknowledged messages must never be
resent merely because no reply followed.

## In Scope

- define observable session states and transitions for recent, inactive, explicitly
  closed, and obsolete discovery records; `last_seen_at` is evidence, not liveness
- preserve deterministic exact-session and alias addressing while warning when the
  resolved target is inactive, closed, or has no usable wake capability
- define explicit retention windows for expired and old terminal messages,
  deliveries, and obsolete session-discovery records
- keep `pending`, `claimed`, `delivered`, and `expired` distinct, plus any
  separately accepted proven-terminal `failed` outcome; recover abandoned claims
  after their lease and retain next-turn fallback until expiry
- retain sender-visible `unreachable` destination evidence for the bounded
  diagnostic window accepted by S2; an exact successful registration self-heals
  the destination before ordinary cleanup considers it obsolete
- treat replies as separate linked messages: delivery alone never implies a reply,
  and absence of a reply never causes automatic redelivery
- use the existing cleaner process rather than adding another worker
- delete message and delivery state transactionally without leaving orphan rows
- preserve pending or actively claimed deliveries until they become terminal
- return and display enough target state, wake/fallback disposition, expiry, and
  terminal outcome for a sender to distinguish waiting from failure
- keep dashboard totals operationally honest after cleanup and expose the last
  cleanup result without retaining payloads for metrics
- cover inactive and closed aliases, unavailable wake, a recipient that never
  resumes, late resume before and after expiry, abandoned claims, ACK without
  reply, linked and unlinked replies, alias transfer/reuse, repeated cleanup,
  Unicode payloads, and scope isolation through public-surface E2E tests

## Out of Scope

- a searchable Relay message archive
- retaining payload history as semantic memory
- user-configurable retention administration in the first slice
- inferring from message text that a response is required
- supervising task completion or automatically chasing an acknowledged recipient
- adding a scheduler or general job system

## Done When

1. Addressing an inactive or closed session produces a deterministic result and a
   sender-visible warning without falsely reporting wake success.
2. A recipient that does not ACK remains eligible for bounded wake attempts and
   next-turn fallback until expiry; lease recovery cannot lose or duplicate it.
3. An acknowledged delivery is never resent solely because the recipient did not
   reply, and status does not describe delivery as understanding or completion.
4. Expired and sufficiently old terminal records are removed automatically after
   a documented bounded window; pending and active claims are never deleted early.
5. Cleanup leaves no orphan messages, deliveries, reply links, aliases, or
   misleading dashboard alerts.
6. Full-lifecycle E2E coverage verifies create → address/wake/fallback → ACK or
   expiry → cleanup through HTTP, MCP, hook, and dashboard read surfaces.

## Notes

This is R1 operational hardening immediately after wake-first delivery, not
evidence for moving to R2. Choose concrete inactivity and retention windows when
implementation starts, based on observed wake recovery and dashboard diagnostic
needs. A future explicit response-deadline contract can be considered separately
if real usage needs it; ordinary Relay must not infer one.
