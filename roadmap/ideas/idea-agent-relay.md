---
id: idea-agent-relay
title: Agent Relay — durable context exchange between agent runtimes
status: in-progress
priority: high
commitment: committed
milestone: pallium-relay
---

## Summary

Test Pallium as a local durable context-exchange layer alongside, not after,
Pallium vNext. Agent Relay lets an agent explicitly send a bounded, scoped message
to one session or all sessions of a supported runtime. Pallium persists the message
and attempts to wake each resolved recipient immediately. If waking is unsupported,
unsafe, or unavailable, Pallium delivers it at that recipient's next applicable
natural turn with attribution.

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
- an explicit runtime-wide or session-specific recipient selector
- repository/container scope
- bounded payload
- expiry and delivery state

Pallium persists the message once and tracks an intended delivery independently
for every resolved recipient session. Reliability may use at-least-once delivery
with stable message and delivery identifiers; delivery means the message reached
that session's runtime context, not that the receiving agent understood or used it.

Replies use a received delivery ID. Pallium derives both endpoints and the
`in_reply_to` parent, so agents cannot accidentally impersonate either side; replies do
not create a continuously running conversation.

## Addressing Boundary

The first slice supports both runtime-wide and individual-session addressing
within a repository/container. Illustrative selectors are:

- `codex` — all eligible Codex sessions in the container
- `codex:<session_ref>` — one exact session by immutable harness session ID
- `codex:@migration-review` — one session by an explicit Pallium-managed alias

The immutable `session_ref` is the canonical delivery identity. A mutable title
shown by a harness is discovery metadata only and must not silently route a
message. An optional Relay alias is unique within its container and harness and
resolves to a `session_ref` when sending, so renaming it cannot redirect an already
queued delivery.

Pallium can address only sessions exposed by an integration as distinct delivery
endpoints. A delegated or child agent sharing its parent's session is not
independently addressable merely because the harness displays a name for it.

R1 design must explicitly settle whether a runtime-wide send snapshots the
currently registered sessions or also applies to matching sessions created before
expiry. It must not leave future-session membership implicit.

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
| OpenCode | `chat.message` claim plus model-bound `experimental.chat.messages.transform` injection |

The smallest viable R1 is a hook-time mailbox:

- send bounded text through one Pallium operation
- route by canonical `container_ref` plus an explicit runtime-wide, exact-session,
  or Relay-alias selector; do not route by `work_ref`
- resolve the selector to immutable session recipients and track delivery for each
  session independently; one session's acknowledgement must not consume another's
  delivery
- register observed harness sessions and allow an optional, unique Relay alias;
  retain mutable harness titles for discovery only
- provide at-least-once delivery with a stable message ID, claim lease, expiry,
  and idempotent acknowledgement
- treat acknowledgement as successful runtime injection, never as evidence that
  the receiving model used the message
- derive replies from a delivered delivery ID, with an idempotent retry and no
  model-supplied sender or recipient; do not add conversation state

Minimum persisted message state is the message ID, bounded payload, claimed sender
runtime and session, original recipient selector, container and actor scope,
creation and expiry times, and optional reply link. Each resolved session has its
own delivery ID, state, claim owner/lease, and delivery time. Its state machine is
`pending -> claimed -> delivered`, with `expired` and lease-based redelivery after
an interrupted claim.

Runtime attribution is convention-based rather than authenticated in the current
local integrations. R1 must describe it as claimed attribution and remain a
single-user local feature; cross-user delivery requires a later authorization and
revocation contract.

Do not base R1 on Claude Channels, OpenCode's beta V2 session inbox, or Codex App
Server injection. They are preview, session-addressed, or architecturally
asymmetric. Reconsider them only if real use demonstrates a need for known-session
or live delivery.

R0 decision: **go for R1**. Validate the contract end to end across all three
runtimes, including bounds, Unicode, scope isolation, runtime fan-out, exact-session
delivery, alias uniqueness and rename behavior, concurrent claims, lease recovery,
acknowledgement idempotence, expiry, retries, and absence of memory or retrieval
side effects.

### R1 — Explicit runtime and session relay — complete

Ship runtime-wide fan-out and individually addressed session delivery within a
repository/container. Include recipient discovery and optional Pallium-managed
session aliases, then measure real use:

- messages sent
- delivered messages judged useful
- manual copying still performed despite Relay
- wrong-recipient or wrong-scope delivery
- messages arriving too late to matter
- demand for delivery to a future worker rather than a named runtime

#### R1 implementation result — shipped for validation (2026-08-25)

R1 is implemented as the full scoped slice, not a disposable proof of concept:

- isolated SQLite session, message, and per-recipient delivery state
- runtime broadcast snapshots plus exact-session and transferable-alias addressing
- bounded, redacted send; delivery-derived idempotent replies; status; lease recovery; idempotent ack
- HTTP and MCP surfaces with bounded tool responses
- next-turn delivery in Claude Code, Codex, and OpenCode with Relay-first context budgets
- session discovery, dormancy, close/reactivation, and alias-release behavior
- public-surface E2E coverage for routing, bounds, lifecycle, concurrency, expiry, scope isolation, and absence of memory/retrieval side effects

Live Claude Code/Codex/OpenCode validation confirmed alias routing, next-turn delivery, acknowledgement, and round-trip messaging. It also exposed three R1 UX defects now covered by the contract: current identity must come from injected `agent_ref`/`thread_ref`, replies must derive endpoints from the received `delivery_id`, and Claude/Codex must follow deliberate Git-project changes while ignoring transient non-Git cwd drift. A project transition best-effort closes the old scoped Relay session and releases its alias; queued deliveries remain in the old project.

The track remains `in-progress` because the product hypothesis is not yet proven. The next work is real-use measurement against the R1 decision gate, not automatic expansion into R2.

#### R1 acceptance hardening — complete (2026-08-25)

A full caller-surface pass added one continuous MCP → HTTP → SQLite → hook lifecycle and closed the remaining smoke-test gaps:

- alias conflicts now tell agents to use `replace_existing=true`; alias transfer and release are covered
- stable message IDs reject changed expiry or redaction semantics and hide cross-scope collisions as not found
- every eligible Claude Code, Codex, and OpenCode turn exposes its current Relay runtime/session identity, even when the prompt is short, memory is empty, or OpenCode state was purged
- Relay envelopes require the agent to make the message origin visible to the user
- combined E2E coverage now exercises the per-turn cap, close/reactivate behavior, queued delivery preservation, idempotent acknowledgement, reply routing, Unicode, and full alias lifecycle

A live two-Codex run independently confirmed alias conflict/transfer, alias-addressed delivery on an unrelated natural turn, delivery-derived reply, visible Relay attribution, and consume-once behavior. A live resumed OpenCode run then confirmed repository actor pinning, Codex-to-OpenCode model-visible delivery, delivery-derived OpenCode reply, and Codex receipt. OpenCode acknowledges only after its model-bound message history is mutated; the earlier system-transform path could silently discard resumed-session context and is not used for Relay. Paid model runs remain release smoke checks, not substitutes for deterministic hook/plugin coverage.

#### R1 operational visibility - complete (2026-08-25)

The local dashboard now treats Relay as a peer operational subsystem. Its
read-only summary reports activity, effective pending/expired state,
send-to-delivery latency, retries, and recent/dormant/closed sessions for all three
supported runtimes without exposing payloads or session identifiers. Waiting
remains neutral because delivery is next-turn; expiry in the recent window is
the actionable failure signal. This is operational telemetry only and does not
claim that a delivered message was useful.

#### R1 retention and lifecycle hardening — queued

Relay expiry currently prevents further delivery and stops causing an operational
alert after the recent-failure window, but expired and old terminal records remain
stored indefinitely. Track the bounded cleanup slice in
`add-relay-retention-and-lifecycle-hardening`: reuse the existing cleaner, preserve
pending and active claims, delete terminal message/delivery state without orphans,
and keep dashboard metrics useful without turning Relay into a message archive.

### R1.5 — Wake-first delivery — active

Make wake the default delivery policy, without requiring sender syntax or an LLM
poll. Pallium must persist the message before attempting activation. An eligible
idle session starts a new turn; a busy session receives the message at a safe new
turn boundary; an unsupported, unavailable, stale, or explicitly passive session
retains the delivery for its next natural turn.

This applies independently to every resolved recipient, including runtime-wide
fan-out. A wake attempt is not delivery: Pallium marks a delivery complete only
after the runtime confirms that the message entered the recipient's context, and
the fallback must not inject a successfully admitted message twice. Wake failures
remain observable but do not turn a durable pending delivery into a failed message.

Use only qualified runtime-native mechanisms. Claude Code native Windows idle wake
and Codex `queue --thread` exact-session admission are proven candidates; Claude
Channels were unavailable and Codex App Server was rejected for this use. Pallium
must deduplicate before ingress, admit Claude only when verified idle, correlate
model-visible admission, and retain durable fallback for busy, stale, restart, or
ambiguous outcomes. OpenCode is deferred until Claude↔Codex handoff works. Track
implementation in `add-wake-first-relay-delivery`.

R1.5 does not restart exited processes, spawn agents, infer recipients, or supervise
work. Resuming an agent that is no longer running is a separate orchestration
hypothesis.

### R1.6 — Dependency-workflow validation and positioning — queued after R1.5

Turn the strongest observed Relay uses into durable E2E journeys: an unexpected
cross-workstream dependency, a blocked decision round trip, and a cross-model
review handoff. Use deterministic public-surface scenarios for regression and
budgeted live Claude Code and Codex runs first; add OpenCode after its wake adapter
is qualified. The
passing scenarios, not a generic multi-agent story, become the source for public
docs, quickstarts, and guidance about when agents should and should not send.

Track the complete research, evidence limits, scenario contracts, runtime coverage,
metrics, documentation outputs, and non-goals in
`validate-relay-dependency-workflows`. Do not begin it until wake-first delivery is
implemented and its adapter contract is stable.

### R2 — Future-recipient addressing investigation

Investigate only if R1 repeatedly exposes the need. Do not assume `work_ref` solves
the identity problem. The investigation may conclude that named runtime/session
delivery is the correct product boundary.

### R3 — Evidence-driven extensions

Add only capabilities repeatedly demanded by actual use, such as multiple explicit
selectors, arbitrary named groups, correction or cancellation, historical pointers,
or explicit dormant-session resumption.

## Design Invariants

- Relay routing and delivery never depend on search, embeddings, ranking, or an LLM.
- Sending is explicit and delivery is deterministic from recipient and scope.
- Relay records remain separate from semantic memory and retrieval.
- Delivery is not evidence of downstream use.
- Pallium may trigger a delivery turn, but it does not assign, supervise, or keep
  agent work running.

## Out of Scope Until Proven Otherwise

- spawning agents or assigning tasks
- autonomous agent-to-agent conversations
- wake-up loops or continuously running coordination
- semantic recipient inference or related-memory broadcasts
- arbitrary group membership and project-wide broadcast beyond one named runtime
- cross-user delivery without an explicit authorization and revocation contract
- general-purpose message-broker behavior

## Decision Gate

Advance beyond R1.6 into broader Relay capabilities only if real Claude Code,
Codex, and OpenCode use shows that targeted dependency messages materially reduce
manual context copying without unacceptable wrong, stale, noisy, or costly turns.
