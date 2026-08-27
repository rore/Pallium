---
id: idea-deferred-relay
title: Deferred Relay — scheduled messages
status: queued
priority: low
commitment: uncommitted
milestone: pallium-relay
lane: capability
---

## Summary

Allow an agent to schedule one explicit Relay message to itself or another
addressed agent. Pallium persists the message immediately, makes it eligible at
the requested time, attempts normal wake-first delivery when due, and retains
next-natural-turn delivery as the fallback.

This is delayed explicit communication, not semantic memory, task assignment, or
a general job scheduler.

## Sequencing

Keep this as the final queued Relay idea. Do not start it until wake delivery,
dependency-workflow validation, the planned integration work, and Relay retention
are stable. A scheduled message is useful only after ordinary Relay can activate
the addressed session reliably and explain failures.

## Product Surface

Keep the conceptual surface small:

- `relay_send(...)` — immediate Relay, unchanged
- `relay_send_at(..., deliver_at | deliver_after)` — persist now and defer eligibility
- `relay_cancel(message_id)` — cancel a deferred message before admission

Cancellation must be scoped to the original sender/actor and be idempotent. Status
must distinguish scheduled, due, admitted, cancelled, expired, and failed without
claiming that the recipient used the message.

## Smallest Valuable Slice

- one-time `deliver_at` or `deliver_after`; store and compare canonical UTC
- persist at creation, but exclude the delivery from claims and wake until due
- use a small due-message scan in Pallium's existing service loop rather than a
  general scheduler framework
- when due, use the ordinary Relay wake/admission path and its durable fallback
- expose scheduled status and allow cancellation before admission
- after Pallium downtime, process an overdue message once on restart
- make future model-turn cost and the pending schedule visible operationally

The delivery keeps ordinary Relay attribution, scope, payload bounds, expiry,
reply, ACK, deduplication, permission, and lower-authority rules. Expiry semantics
must be defined relative to the due time so a valid future message cannot expire
merely because it was scheduled early.

## Addressing Decision Required

Exact-session and alias scheduling have different expectations. An exact
`session_ref` should never silently retarget if that session becomes stale. An
alias may mean either "the session owning this alias now" or "whoever owns this
role when the message becomes due." Before implementation, choose and expose one
deterministic rule; do not let a mutable alias redirect a scheduled message by
accident.

Future-worker or work-addressed reminders remain out of scope until Relay has a
reliable shared work identity. Pallium must not infer a recipient semantically.

## Safety and Cost Boundary

A due message can wake a model and cause token or tool cost after the scheduling
turn has ended. Therefore schedules must be attributable, inspectable, bounded,
and cancellable. Scheduled peer input cannot grant permission, approve an action,
or raise its authority. Rate, queue, fan-out, and reply-hop protections must also
apply when many messages become due together.

## Out of Scope for the First Slice

- recurrence, cron expressions, calendars, or timezone-rule engines
- arbitrary callbacks, shell commands, or general background jobs
- inferred reminders or reminders created from semantic memory
- spawning, restarting, assigning, or supervising agents
- automatic conversations or self-perpetuating reminder chains
- retargeting an obsolete exact session without an explicit addressing contract

## Validation Gate

Public-surface E2E must cover self and peer scheduling, before/due/overdue
boundaries, cancellation races, restart before and after due time, clock rollback,
expiry, stale recipients, alias replacement, duplicate due scans, concurrent due
messages, wake failure with next-turn fallback, Unicode and maximum payloads, and
cost/operational visibility. Every accepted schedule must be delivered at least
once or remain visibly pending/failed; it must never disappear silently.

Advance beyond the one-shot slice only if real use shows repeated value that
cannot be met by an ordinary immediate Relay message.
