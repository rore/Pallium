# Relay wake feasibility decision

**Status:** Superseded by deeper source review recorded in the roadmap (2026-08-26)
**Scope:** Initial probes used Claude Code 2.1.217, Codex CLI 0.149.1, and OpenCode 1.18.19 on Windows; Claude is now 2.1.246

> **Follow-up correction:** The original conclusion below was too conservative.
> Official Codex App Server queue integration tests prove idle auto-dispatch,
> busy distinct-turn queuing, exact client-ID admission, and cold-resume
> persistence. Codex managed App Server is therefore the first implementation
> target. OpenCode is viable with a durable plugin coordinator. Claude 2.1.246
> clears the native-Windows version requirement, but busy messages may enter the
> active turn at a tool boundary. The canonical current verdict and exact
> handshakes are in the
> [wake-first Relay roadmap item](../../roadmap/features/add-wake-first-relay-delivery.md).

## Decision

Wake support is a capability of a live integration instance, not a property of a
runtime name or saved conversation. Pallium may wake only when that instance
advertises a currently leased capability and exposes a positive, delivery-bound
admission signal through a race-free public operation. Otherwise the durable Relay
delivery remains pending.

| Runtime | Classification | Evidence | Missing gate |
|---|---|---|---|
| Claude Code | passive-only | Channels document external-event ingress for an open, configured session | No Channel is configured locally and no correlated admission was proven. |
| Codex | passive-only; managed App Server is the candidate | Installed schemas expose correlated queue add/start operations | A completed-thread queue acknowledgement did not admit a turn; no disposable managed App Server trace proved the full handshake. |
| OpenCode | passive-only; plugin/server is the candidate | An idle async prompt produced an assistant child correlated by parent ID | Status followed by prompt is not atomic, and a busy prompt interleaved with the active turn. |

A runtime can contain wakeable, passive, stale, and closed sessions. These results
authorize further ingress proofs, not production adapters.

## Evidence and candidate handshakes

### Claude Code

Version 2.1.217 is new enough for documented Channels. The healthy local
installation has no Channel configuration and its current authentication/traffic
policy disables Remote Control. No user session was targeted.

A future proof must launch a disposable Channel, submit a delivery ID, demonstrate
safe idle and busy admission, correlate a positive admission signal, and cover
close/restart/ambiguous response behavior. Until then it advertises passive only.

### Codex

The installed generated App Server schema provides a stable queued submission ID
tied to caller clientUserMessageId. The candidate handshake is queue/add with the
delivery ID, then queue/start for that exact submission, then correlation to the
returned/notified turn. Queue acknowledgement is not admission.

A disposable completed codex exec thread accepted the queue command but produced
no second turn. This negative control rules out ordinary completed sessions.
A disposable Pallium-managed App Server trace must still prove all seven Phase 0
cases before this candidate advertises wake.

### OpenCode

An isolated opencode serve probe established that idle prompt_async persists a
caller-controlled ID and produces an assistant child with matching parentID. HTTP
204 is only transport acknowledgement.

A second prompt submitted while busy was persisted beside the active tool turn.
More importantly, status then prompt has a time-of-check/time-of-use race. A
plugin-owned queue that serializes on the session-idle event, or an atomic public
idle-only operation, must be proven before advertising either idle_wake or
busy_queue.

## Normalized state contract

The executable fixture at tests/fixtures/relay_wake/contract.json is canonical for
Phase 2. It defines every required event for every wake state:

- not_eligible: natural-turn claim allowed;
- queued: durable work awaits dispatch;
- triggering: one adapter generation owns the reservation before external I/O;
- triggered: external I/O may have begun, admission unproven;
- admitted: correlated admission atomically completed delivery;
- fallback: wake ended, natural-turn claim allowed.

The matrix explicitly covers valid delivery/wake combinations plus capability disable/expiry, session close/reopen,
adapter replacement, trigger outcomes, deadline, message expiry, natural claim,
callback, and Pallium/runtime restart in all six states. Expiry is terminal;
admitted delivery never expires; old-generation and late callbacks are rejected.
Restart while a request is ambiguous waits for the deadline rather than risking
double delivery.

## Provisional Phase 2 safety ceilings

These are configurable starting ceilings, not runtime performance claims:

- 120-second admission deadline (the OpenCode probe took about 42 seconds);
- four concurrent local attempts;
- one attempt unless the runtime proves the supplied ID idempotent;
- six wake starts per recipient per minute;
- four reply hops; retain the existing 25-recipient fan-out bound;
- 15-second capability heartbeat and 45-second lease.

## Remaining estimate and next task

The next task is not the durable core. First prove one complete runtime ingress;
otherwise the core would be speculative.

| Task | Scope | Estimate |
|---|---|---:|
| 1.1 | OpenCode plugin-owned safe-boundary queue and seven-case disposable proof | 1-2 days |
| 1.2 | Codex managed App Server disposable queue/admission proof | 1-2 days |
| 1.3 | Claude Channel bootstrap/proof when local prerequisites are available | 1-3 days |
| 2 | Durable state, leases, races, dispatcher, fake-adapter E2E, telemetry after one proof passes | 3-5 days |
| 3-5 | Runtime adapters that individually pass the gate | 2-4 days each |
| 6 | Cross-runtime journeys, installers, dashboard and public UX | 2-3 days |

## Primary references

- [Claude Code Channels](https://code.claude.com/docs/en/channels)
- [Claude Code Channels reference](https://code.claude.com/docs/en/channels-reference)
- [Codex App Server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
- [OpenCode server API](https://opencode.ai/docs/server/)
