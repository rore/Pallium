---
id: idea-explicit-relay-broadcast
title: Investigate an explicit Relay broadcast capability
status: queued
priority: low
commitment: uncommitted
milestone: pallium-relay
lane: investigation
---

## Summary

Broadcast is not a shorthand form of targeted Relay. Regular `relay_send` must require one exact endpoint or alias; omitting the target must never silently fan out.

Only investigate broadcast after actor-scoped cross-container targeted routing is shipped and real use demonstrates a recurring need. If built, expose it through a separately named API such as `relay_broadcast` so callers explicitly choose the larger audience and cost.

## Questions before commitment

- What concrete workflow needs broadcast rather than several explicit targeted sends?
- What explicit audience selector and authorization boundary prevents accidental actor-wide or cross-container delivery?
- Should the first audience be container-local, a caller-supplied endpoint set, or another bounded scope? No default may mean “every session.”
- How are recipients snapshotted at persistence time so later registration or alias changes cannot expand an accepted broadcast?
- What recipient cap, rate limit, confirmation, wake policy, and cost visibility are required before fan-out can start multiple model turns?
- How do per-recipient status, ACK, retry, expiry, close/unreachable handling, and restart recovery reuse the existing delivery engine?

## Product boundary

Broadcast remains attributed transport. It must not add semantic recipient selection, task assignment, workflow orchestration, shared project state, supervisor logic, completion inference, or autonomous loops.

## Validation if promoted

Caller-surface E2E must cover explicit opt-in, empty/exact-limit/over-limit audiences, duplicate recipients, actor isolation, container boundaries, immutable recipient snapshots, partial failure, idempotent retry, per-recipient status and ACK, expiry, restart recovery, wake-cost caps, unsupported runtimes, Unicode, and proof that regular `relay_send` still rejects missing targets.

## Done when

A written investigation either rejects broadcast for lack of demonstrated value or defines a separately named, bounded, explicit-audience contract with implementation and validation gates. This item must not block or expand targeted cross-container Relay.
