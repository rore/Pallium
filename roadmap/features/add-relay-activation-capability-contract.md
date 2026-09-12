---
id: add-relay-activation-capability-contract
title: Define explicit Relay activation capabilities and outcomes
status: done
priority: high
commitment: committed
milestone: pallium-relay
lane: stabilization-safety
---

## Summary

Give agents, operators, and runtime integrations one precise contract for what a
destination can do and what an activation attempt actually established. Distinguish
reaching an existing session, starting a turn, queueing a distinct future turn,
requiring human input, and admitting the Relay payload into model context.

This formalizes the existing wake/fallback machinery. It does not introduce a new
activation engine, spawn agents, or turn transport acceptance into delivery.

## Why

A generic wake flag or successful native write cannot explain whether a session
will run, whether a busy session safely queued the request, or whether only text
was prefilled. Lost responses can leave a native submission uncertain. Replaying
that submission blindly can create duplicate paid turns even while message claim
and ACK are correctly idempotent.

Make these distinctions explicit before adding more integrations. Existing Claude,
Codex, and OpenCode behavior must remain truthful and compatible.

## Priority and Dependencies

- Follow the active correctness slices in `add-wake-first-relay-delivery` and
  `add-relay-retention-and-lifecycle-hardening`; do not delay incident fixes for
  this normalization work. Wake-first S2 owns terminal-versus-retryable transport
  decisions; this item represents and exposes those decisions consistently.
- Precede the adapter expansion in `add-copilot-relay-integration`. Copilot must
  consume this contract; protocol research can proceed independently.
- Define the outcome vocabulary before `add-relay-delivery-trace` persists and
  displays it. Trace design can proceed in parallel.
- Existing `validate-relay-dependency-workflows` journeys need not wait.

## Discovery Required Before Implementation

Inspect current main, not older comparative research. Inventory native capability
registries, registration/probe paths, scheduler/coalescing/recovery, typed transport
results, HTTP/MCP status and recipient projections, dashboard projections, and
platform qualification tests. Record a short table of existing fields, authority,
consumers, and missing distinctions in the implementation Work Record.

Start with `core/relay.py`, the actual wake modules found in `core/` and `app/`,
`api/schemas.py`, `api/routes.py`, `app/mcp/server.py`, runtime integrations,
`docs/agent-relay.md`, and the wake-first feature's S2 contract. Reuse existing
representations where equivalent; do not create a parallel registry.

At roadmap preparation, Claude's `core/claude_wake.py` has exact-session generation
and durable write-ahead capability/intent state; Codex's `app/codex_wake.py` has
coalescing and `exec_completed`, `queued`, `ambiguous`, and `failed` outcomes.
Claude transport uses `accepted`, `retryable`, and `unreachable`. Current public
session fields expose lifecycle/destination health, not a complete capability
vector. The phase-zero design `docs/designs/017-relay-wake-phase0.md` also names
outcomes: reconcile that design with code rather than adding a third vocabulary.
Recheck these anchors on pickup because active correctness work can change them.

## In Scope

### Capability snapshot

Define a small typed, bounded representation of the destination's qualified
behavior. Choose exact field names after the inventory. Cover:

- Whether the mechanism targets the exact existing session, a separately managed
  session, or neither. A managed/new-session topology must never silently replace
  an existing-session request.
- Whether it can start a turn without human action, safely queue a distinct turn
  while busy, or only deliver on a natural turn. Steering and prefill must not be
  advertised as distinct-turn queueing or autonomous wake.
- What evidence the mechanism can provide: attempted submission, native transport
  acceptance, correlated turn start, or payload context admission. Keep these
  evidence kinds distinct rather than assuming one universal strength ordering.
- Runtime, platform/integration mode, qualification provenance, and current
  availability/unknown state. Static support, observed readiness, and endpoint
  lifecycle are separate facts. Unknown or stale evidence cannot become support.

Do not add speculative dimensions for hypothetical integrations. Snapshot reads
must not claim messages, activate sessions, probe by sending text, or incur model
cost. Never expose native tokens, sockets with secrets, or credential material.

### Attempt outcomes and authority

Use the following canonical activation-attempt outcomes. Existing delivery state
and admission evidence remain separate:

| Outcome | Meaning |
|---|---|
| accepted | Native activation submission was positively accepted; payload admission is still separate. |
| deferred | No native submission occurred (not attempted or positively ruled out); destination is busy, unavailable, passive-only, or awaiting a natural turn. |
| uncertain | A side effect may have occurred, but confirmation is missing. Preserve correlation and suppress blind resubmission. |
| failed | This attempt definitively failed. A reason separately determines whether the destination is terminal or the attempt is retryable. |

Required mapping from the older phase-zero design:

- `admitted` remains a correlated authoritative admission/ACK fact, not another
  activation-attempt outcome. Preserve the existing delivery transition.
- `triggered` maps to `accepted` when native acceptance is positively established.
- `unavailable` maps to `deferred` only when no submission occurred; retain the
  busy/unsupported/closed/missing reason and existing destination-health rules.
- `rejected` maps to `failed` with the proven permanent rejection reason.
- Old `ambiguous` mixes two cases: positively accepted but not yet admitted maps
  to `accepted`; uncertain native submission maps to `uncertain`. Neither permits
  blind native resubmission merely because admission is not yet observed.

The implementation must update the phase-zero design, applicable contract
fixtures, and adapter mappings together. This roadmap chooses the target taxonomy;
existing shipped behavior remains authoritative until that coherent change lands.
Map Codex `exec_completed`/`queued` by their actual evidence (never infer payload
admission from process exit), `ambiguous` to `uncertain`, and `failed` by proven
reason. Map Claude `accepted` to `accepted`, and `retryable`/`unreachable` according
to whether native submission is ruled out or uncertain. Preserve strict stale-
feedback CAS and exact-registration self-healing. Keep `prepared` as a trace stage,
not an outcome or evidence of submission.

Preserve native reason detail only as bounded, redacted diagnostic data. Record
attempt correlation and destination generation where existing recovery needs them.
Resolve uncertain outcomes using existing authoritative signals; a timeout or
elapsed duration alone is not proof that no native submission happened.

The existing delivery claim/lease/ACK path remains authoritative for `delivered`.
Neither `accepted` nor a turn-start event proves that this payload entered context.
No reply is not a delivery failure. Capability updates cannot retroactively reroute
queued messages or change their delivery state. Preserve existing no-duplicate
native-write/coalescing protections across restart and late evidence.

### Caller surfaces and compatibility

Expose a compact common projection through existing recipient/status HTTP and MCP
surfaces and the Relay dashboard. Show supported behavior, current availability,
and the expected fallback in plain language. This slice defines normalized attempt
results at the adapter boundary but does not add an attempt ledger. Last-attempt
readback is optional only where existing state already supports it; durable history
and timeline readback belong to `add-relay-delivery-trace`. Use one projection, not
separate interpretations per surface.

Plan additive/backward-compatible handling of existing registrations and public
state/destination-health fields. Passive/idle-wake/busy-queue concepts in older
designs are not evidence that a public profile has shipped. Missing information
becomes unknown or the proven
legacy fallback, never optimistic support. Document malformed/conflicting values,
refresh, close/reactivation, generation changes, and runtime upgrade behavior.
Preserve current endpoint targeting and history/memory scope rules.

## Out of Scope

- Generic external-provider/plugin framework, new runtime integration, or new
  macOS/OpenCode qualification solely to populate this matrix.
- Work assignment, scheduling, model selection, automatic reviewer dispatch,
  semantic routing, or task completion inference.
- A new receipt authority, second delivery engine, or generalized telemetry bus.

## Verification and Done When

1. A documented mapping covers every existing adapter/runtime/qualified platform;
   current claims and fallbacks agree across API, MCP, dashboard, and docs.
2. Public-surface E2E covers passive-only, idle wake, busy distinct queue, unsupported
   or human-required paths, unknown/stale capabilities, and invalid/conflicting
   registration values, including empty/max/over-max and Unicode inputs.
3. Lost responses before/after native acceptance, late acceptance/admission,
   generation changes, concurrent sends, coalescing, restart, and recovery prove
   no blind duplicate native writes, no false delivered result, and no lost pending
   payload. Use controlled adapters/clocks through actual caller surfaces.
4. Exact-session identity, alias transfer, closed/unreachable/reactivated targets,
   legacy callers, scope checks, and applicable persisted-state compatibility are
   covered through registration -> send -> activation -> admission/ACK -> readback.
5. Read-only capability/status queries produce no delivery, native-write, or model
   side effects. Trace absence must not be represented as a successful attempt.
6. Run focused subsystem checks and the repository-required full suite once before
   review. Preserve existing installed qualification evidence; any newly claimed
   native behavior requires a bounded installed witness with explicit cost limits.

Update the board and applicable Relay/integration docs only after implementation
and verification. The implemented contract is the current source of truth; delivery tracing remains a separate follow-up.

## Implemented

Shipped with one pure bounded projection shared by HTTP, MCP, and dashboard;
canonical adapter attempt outcomes; durable current Claude Code and Codex
exact-delivery fences; ACK-authoritative release; fail-closed corruption, write,
and capacity behavior; and focused mapping, lifecycle, race, restart, Unicode,
budget, and caller-surface coverage. The stores retain no attempt history and
assume a single Pallium service process. Unresolved reservations intentionally
fall back to a later natural hook turn without blind native resubmission.