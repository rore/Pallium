---
id: add-relay-delivery-trace
title: Explain Relay delivery with bounded activation-attempt traces
status: queued
priority: high
commitment: committed
milestone: pallium-relay
lane: stabilization-safety
---

## Summary

Let an agent or human inspect one Relay message and understand its selected target,
activation attempts, deferrals or uncertain outcomes, claim/recovery, and eventual
payload admission. Add bounded persisted diagnostic evidence and a compact timeline
to the existing Relay dashboard, with an HTTP read path and an agent-facing
`pallium_relay_trace(message_id)` tool (exact signature finalized during design).

The trace explains delivery; it never controls or proves it independently of the
existing authoritative delivery records.

## Why

Current state and attempt counts cannot reconstruct every delayed-claim or
lost-response incident. In particular, a caller timeout may be followed by a late
server claim, and a native activation may be accepted before its response is lost.
Operators need to distinguish safely pending work from an uncertain activation
without resending the same request or mistaking transport acceptance for admission.

Use these generalized failure classes as reproductions. Confirm the current-main
evidence before attributing a particular field incident to a missing trace; do not
copy product-specific transcripts or secrets into fixtures.

## Priority and Dependencies

- Follow the active wake/lifecycle correctness fixes; tracing must not become a
  prerequisite for fixing delivery loss or duplicate paid turns.
- Consume `add-relay-activation-capability-contract` and wake-first S2's established
  outcomes. Reuse any equivalent typed outcome already shipped; do not wait for
  every future runtime integration.
- Coordinate persistence and cleanup with
  `add-relay-retention-and-lifecycle-hardening`. That feature owns delivery/session
  retention; this item owns bounded trace retention and diagnostic completeness.
  Do not create two cleaners or require broad payload-archive work.
- Place before Copilot expansion so new integrations can emit the same evidence.
  Existing dependency-workflow validation remains independently executable.

## Discovery Required Before Implementation

Inventory existing wake registries, accepted/ambiguous-write suppression,
message/delivery storage, scheduler recovery, logs, dashboard detail APIs, and
current test evidence. Identify exactly which questions cannot be answered today.
Document the chosen owning files and event producers in the implementation Work
Record. Inspect `core/relay.py`, `storage/sqlite_schema.py`, actual wake/storage
modules, `api/routes.py`, `app/mcp/server.py`, `app/dashboard.py`, and runtime hooks.
Reuse existing correlation and read models; do not create a second message store.

At roadmap preparation, `storage/sqlite_schema.py` and `storage/sqlite_relay.py`
persist delivery claims and `attempts`; that counter counts receiver claims, not
native wake attempts. `app/claude_wake.py` and `app/codex_wake.py` log partial
activation evidence; Claude's durable registry and Codex's coalescing state serve
correctness, not a queryable trace. The dashboard already has message/delivery
detail projections to extend. Never repurpose the existing `attempts` counter.

## In Scope

### Bounded evidence model

Persist only what is necessary to reconstruct an attempt:

- Stable event/attempt identity and relation to message, delivery, canonical
  destination endpoint and, when relevant, native-session generation.
- Timestamp plus stable ordering/tie-breaker; clock movement must not invent causal
  order. Preserve observed versus recorded times only where needed.
- Attempt type/stage (including prepared) and, when observed, a normalized outcome
  of accepted, deferred, uncertain, or failed; link authoritative claim, lease recovery, expiry and ACK
  transitions where available instead of duplicating their authority.
- The target resolved at send time. An alias transfer must not rewrite historical
  destinations; current endpoint location/state is a separately labeled view.

Never store message bodies, full prompts, raw provider responses, credentials,
claim tokens, MCP receipts, or native wake secrets in trace fields. Apply bounded
redaction to diagnostic reasons. Coalesced activations must be represented honestly:
one wake can serve several deliveries, not one invented attempt per message.

### Authority and failure behavior

The current delivery readback is authoritative. Trace rows are evidence and can be
incomplete. An activation accepted by a runtime is not payload admission; a delivered
message without a reply is not unfinished delivery.

Diagnostic recording failure must not prevent otherwise valid delivery, roll back
an ACK, cause native resubmission, or manufacture an outcome. Existing correctness-
critical write-ahead intents and ambiguous-write suppression remain mandatory;
they are not optional diagnostics and must not be weakened by this feature.

If a crash leaves only a prepared event, report an incomplete/unknown outcome rather
than assuming success or safe retry. Bound write latency, event volume, and repeated
deferrals; avoid an unbounded event for every recovery sweep. Design idempotency and
concurrent completion so duplicate instrumentation cannot inflate attempts.

### Read surfaces and useful explanation

Provide one bounded read projection for HTTP, MCP, and the dashboard. Return:

1. Original resolved target and current delivery state.
2. Ordered attempt/transition evidence with normalized reasons.
3. Whether evidence is missing, truncated, pruned, or predates trace support.
4. A deterministic explanation such as pending for natural turn, activation
   uncertain and resubmission suppressed, delivered, expired, or target unavailable.

Advice must come from current authoritative state plus qualified evidence, never
an LLM or guessed liveness. A pending message should normally tell the caller that
it remains stored and should not be resent; distinguish unsupported wake from loss.
Do not promise that the recipient will act or respond.

Use bounded pagination with a stable cursor/order, explicit continuation and
completeness. Define empty/unknown/deleted IDs, limit boundaries, redacted reasons,
and concurrent append behavior. Scope checks must match the current Relay access
contract, including cross-container routing, without expanding History/memory access.

The existing message detail UI gets a readable timeline and fallback explanation;
do not redesign the dashboard or add a searchable message archive. Tool output
must respect existing MCP budgets and avoid replaying payload text.

### Retention and compatibility

Choose and document concrete per-delivery/attempt and total-storage bounds plus a
diagnostic retention window during implementation. Justify defaults from existing
traffic/storage rather than adding administration UI. Reuse the existing cleaner.
Trace pruning must never delete or alter pending deliveries, active claims, alias
bindings, or correctness-critical activation intents. Avoid orphaned correlations;
if trace data is pruned while a message remains, readback must disclose the gap.

Older deliveries have no historical attempt detail: show unavailable evidence,
not fabricated backfill. Follow current repository persistence/migration policy;
test supported pre-feature state without reopening retired migration mechanisms.

## Out of Scope

- Payload archive, transcript search, semantic memory ingestion, general event bus,
  distributed tracing service, analytics warehouse, or external monitoring dependency.
- Automatic resend/chasing, reply deadlines, task supervision, cross-host transport,
  new runtime adapters, or changing delivery/ACK semantics.
- Separate recipient-resolution tooling beyond what this timeline needs.

## Verification and Done When

1. An operator can distinguish accepted-but-not-admitted, busy/passive deferral,
   uncertain native submission, lease recovery, expiry, and delivered-without-reply
   through the documented HTTP/MCP/dashboard surfaces using the same projection.
2. Public-surface E2E covers complete send -> wake -> claim -> ACK/reply -> status
   -> cleanup journeys, late claims after caller timeout, crash/restart between
   attempt stages, concurrent/coalesced sends, duplicate events, and late evidence.
3. Injected trace-store failure leaves delivery/ACK/recovery correct and produces
   no additional native writes. Correctness-critical intent failures retain their
   existing fail-closed behavior. Neither trace reads nor pruning can admit work.
4. Empty/max/over-max/invalid pagination, Unicode, ordering ties/clock rollback,
   unknown IDs, legacy rows, alias transfer, closed/reactivated endpoints, redaction,
   access isolation, and bounded retention are covered with observable assertions.
5. Retention/pruning and restart leave no orphan state or misleading completeness;
   attempt count meanings are documented separately from claim/recovery counts.
6. Focused checks and the repository-required full suite pass before review. A
   bounded installed delayed/uncertain-delivery witness demonstrates the explanation
   if the relevant runtime can reproduce it safely; deterministic fault-injection
   remains required and must not depend on paid model responses.

Document the resulting contract and update roadmap state only after evidence is
available. A trace is operational evidence, not a downstream-task-effect metric.
