---
id: idea-agent-relay
title: Agent Relay — durable context exchange between agent runtimes
status: queued
priority: high
commitment: uncommitted
milestone: pallium-relay
---

## Summary

Test Pallium as a local durable context-exchange layer alongside, not after,
Pallium vNext. Agent Relay lets an agent explicitly send a bounded, scoped message
to another supported runtime. Pallium persists the message and delivers it at the
recipient's next applicable natural turn with attribution.

Initial consumers are Claude Code, Codex, and OpenCode.

## Product Hypothesis

Pallium's durable local service and cross-runtime integration position may remove
enough manual context transfer to be valuable independently of semantic memory.

Primary question:

> Does cross-agent relay remove enough manual context transfer to be worth using?

This is a parallel product track. It neither replaces nor depends on vNext's
historical-work hypothesis.

## Minimum Contract

An agent explicitly sends a message with:

- sender identity and provenance
- a named supported recipient runtime
- repository/container scope
- bounded payload
- expiry and delivery state

Pallium persists it and attempts one intended delivery at the recipient's next
applicable turn. Reliability may use at-least-once delivery with a stable message
identifier and deduplication; delivery means the message reached the runtime, not
that the receiving agent understood or used it.

Replies reuse the same send operation, optionally linked with `in_reply_to`; they
do not create a continuously running conversation.

## Addressing Boundary

The first slice targets a named runtime within a repository/container. A specific
session may be targeted only when its identifier is already known.

Extracted `work_refs` must not route Relay messages. They are optional retrieval
hints, may be absent, and two agents cannot be assumed to derive the same value.
"Whoever next continues this work" is therefore a later addressing investigation,
not a promised mechanism. It requires a reliable shared identity supplied by an
integration or external system; Pallium must not infer one semantically.

## Roadmap

### R0 — Contract

Confirm Claude Code, Codex, and OpenCode can support deterministic next-turn
delivery and define only the required send, scope, expiry, delivery, attribution,
and deduplication semantics.

#### R0 result — feasible; proceed to R1 (2026-08-25)

All three initial consumers have a supported pre-model turn boundary that can
claim and inject persisted Relay messages without polling or waking an agent:

| Runtime | R1 delivery boundary |
|---|---|
| Claude Code | `UserPromptSubmit` hook |
| Codex | `UserPromptSubmit` hook using `additionalContext` |
| OpenCode | existing `chat.message` and system-transform plugin path |

The smallest viable R1 is a hook-time mailbox:

- send bounded text through one Pallium operation
- route by exact recipient runtime plus canonical `container_ref`; do not route
  by `work_ref`
- let the first applicable session of that runtime in the container atomically
  claim the message
- provide at-least-once delivery with a stable message ID, claim lease, expiry,
  and idempotent acknowledgement
- treat acknowledgement as successful runtime injection, never as evidence that
  the receiving model used the message
- represent replies as another send with optional `in_reply_to`, without adding
  conversation state

Minimum persisted state is the message ID, bounded payload, claimed sender runtime
and session, recipient runtime, container and actor scope, creation and expiry
times, delivery state, claim owner/lease, delivery time, and optional reply link.
The initial state machine is `pending -> claimed -> delivered`, with `expired` and
lease-based redelivery after an interrupted claim.

Runtime attribution is convention-based rather than authenticated in the current
local integrations. R1 must describe it as claimed attribution and remain a
single-user local feature; cross-user delivery requires a later authorization and
revocation contract.

Do not base R1 on Claude Channels, OpenCode's beta V2 session inbox, or Codex App
Server injection. They are preview, session-addressed, or architecturally
asymmetric. Reconsider them only if real use demonstrates a need for known-session
or live delivery.

R0 decision: **go for R1**. Validate the contract end to end across all three
runtimes, including bounds, Unicode, scope isolation, concurrent claims, lease
recovery, acknowledgement idempotence, expiry, retries, and absence of memory or
retrieval side effects.

### R1 — Explicit point-to-point relay

Ship named-runtime delivery within a repository/container and measure real use:

- messages sent
- delivered messages judged useful
- manual copying still performed despite Relay
- wrong-recipient or wrong-scope delivery
- messages arriving too late to matter
- demand for delivery to a future worker rather than a named runtime

### R2 — Future-recipient addressing investigation

Investigate only if R1 repeatedly exposes the need. Do not assume `work_ref` solves
the identity problem. The investigation may conclude that named runtime/session
delivery is the correct product boundary.

### R3 — Evidence-driven extensions

Add only capabilities repeatedly demanded by actual use, such as session targeting,
multiple explicit recipients, correction or cancellation, historical pointers, or
safe live delivery.

## Design Invariants

- Relay routing and delivery never depend on search, embeddings, ranking, or an LLM.
- Sending is explicit and delivery is deterministic from recipient and scope.
- Relay records remain separate from semantic memory and retrieval.
- Delivery is not evidence of downstream use.
- Pallium moves bounded information; it does not manage or execute agent work.

## Out of Scope Until Proven Otherwise

- spawning agents or assigning tasks
- autonomous agent-to-agent conversations
- wake-up loops or continuously running coordination
- semantic recipient inference or related-memory broadcasts
- group membership and project-wide broadcast
- cross-user delivery without an explicit authorization and revocation contract
- general-purpose message-broker behavior

## Decision Gate

Continue beyond R1 only if real Claude Code, Codex, and OpenCode use shows that
Relay materially reduces manual context copying without unacceptable wrong, stale,
or noisy delivery.
