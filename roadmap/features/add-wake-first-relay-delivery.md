---
id: add-wake-first-relay-delivery
title: Add wake-first Relay delivery
status: queued
priority: high
commitment: committed
milestone: pallium-relay
lane: capability
---

## Summary

Make immediate activation the default for every resolved Relay recipient while
preserving durable next-turn delivery as the automatic fallback. The sender does
not choose a delivery mode: Pallium persists first, uses the recipient runtime's
native wake mechanism when safe, and otherwise leaves the delivery pending.

## Why

Relay does not remove manual coordination if the user must prompt an idle recipient
merely to discover its mail. Claude Code, Codex, and OpenCode expose different
mechanisms for starting or queuing a turn, so Pallium needs small runtime-specific
adapters behind one observable delivery contract.

## Delivery Contract

1. Persist the message and immutable per-recipient deliveries before attempting
   activation.
2. For every resolved recipient, use its advertised wake capability by default;
   there is no sender-side `wake` option.
3. If idle, start a new turn. If busy, queue a distinct turn at the runtime's safe
   boundary; never steer Relay text into an active human-owned turn.
4. Mark the delivery complete only when the runtime confirms admission into the
   recipient context. A trigger request or transport acknowledgement is not enough.
5. If activation is unsupported, disabled, unavailable, stale, or fails, leave the
   same delivery pending for the existing next-natural-turn path.

Track activation separately from the durable delivery lifecycle. Operationally,
Pallium must distinguish `queued` (persisted, not activated), `triggered` (a runtime
turn was requested), and `delivered` (the runtime admitted the message). Never call
a message read, understood, or used. Stable message and delivery IDs must make wake
retries, runtime callbacks, and hook fallback idempotent.

## Runtime Feasibility and Constraints

These findings were current on 2026-08-26 and must be revalidated against the
installed runtime versions before implementation:

| Runtime | Supported direction | Constraint to settle before shipping |
|---|---|---|
| Claude Code | Native cross-session delivery starts a turn when idle and waits for a safe boundary when busy. Channels can push external MCP events into an open session. | Choose the smallest supported Pallium ingress. Channels are a research preview and require per-session launch/configuration; native delivery requires a live messaging-enabled session. Do not make an undocumented socket protocol a product dependency. Validate native Windows behavior. |
| Codex | Managed subagents already distinguish non-waking messages from waking follow-ups. App Server can resume threads and start turns; its experimental queue can run a follow-up when the thread becomes idle. | Arbitrary interactive threads are unsafe until admission cannot race with a human turn: `turn/start` is start-or-steer and the idle check is not atomic. Prove a safe public operation or constrain support to a Pallium-managed App Server configuration. |
| OpenCode | Its shared server exposes session status and synchronous/asynchronous session prompts, making live idle wake and background queuing natural. | Verify exact idle, busy, TUI-closed, permission, and service-restart behavior against the supported plugin/server API; do not promote automatic service startup or dormant resume into this contract. |

Each registered session should advertise only capabilities its integration can
actually provide, such as passive delivery, idle wake, and busy queueing. Missing
or lost capability automatically selects the durable fallback. An exited process
is not a wakeable recipient in R1.5 even if its conversation could technically be
resumed by launching a new runtime.

## In Scope

- wake every eligible resolved recipient by default, including runtime fan-out
- allow a recipient integration to explicitly disable wake and remain passive
- persist before attempting wake; retain next-natural-turn delivery as fallback
- queue busy recipients for a separate safe turn rather than steering an active
  human-owned turn
- confirm runtime admission before marking delivery complete
- make trigger attempts idempotent so wake and fallback cannot double-deliver
- expose wake attempts, admission, fallback reasons, failures, latency, and fan-out
  in Relay operational telemetry
- implement and validate the smallest supported native adapter for Claude Code,
  Codex, and OpenCode
- cover idle, busy, concurrent user input, unsupported capability, stale or closed
  sessions, runtime and Pallium restarts, duplicate triggers, permissions, fan-out,
  expiry, and reply-loop protection through public-surface E2E tests

## Safety and Cost Boundary

Wake changes Relay from passive information transport into an execution trigger:
the receiving model can consume tokens, invoke tools, and modify files. Therefore:

- Relay input is attributed peer input with lower authority than user instructions;
  it cannot grant consent, approve permissions, change runtime configuration, or
  bypass the recipient's sandbox and approval policy
- runtime-wide fan-out still wakes every resolved recipient by default, but the
  resulting turn count, failures, and observable usage must be visible
- bounded queues, duplicate/rate limits, and a finite reply-hop policy must prevent
  accidental wake storms and autonomous reply loops
- automatic replies are not implied by delivery; a reply remains an explicit Relay
  action derived from a received delivery ID
- an integration can explicitly disable wake, but passive delivery remains enabled
  unless Relay itself is disabled

## Out of Scope

- restarting an exited agent process or resuming a dormant harness automatically
- spawning agents, assigning work, or supervising completion
- sender-selected wake syntax or semantic wake decisions
- treating runtime admission as proof that the agent understood or used a message
- automatic agent conversations or unbounded reply chains

## Done When

1. A Relay send is persisted and wakes every eligible resolved recipient without a
   user turn or sender delivery flag.
2. Busy recipients process the message in a separate safe turn, never by accidental
   steering of an active human-owned turn.
3. Unsupported, unavailable, stale, or passive recipients receive the same durable
   message exactly once on their next natural turn.
4. Delivery state and dashboard telemetry distinguish wake attempt, runtime
   admission, fallback, and terminal expiry without claiming downstream use.
5. Full-lifecycle E2E coverage verifies the observable contract through each
   supported runtime's real integration surface.
6. Relay-triggered turns preserve attribution, lower-authority treatment, sandbox
   policy, and ordinary permission prompts.
7. Queue, duplicate, rate, and reply-hop bounds terminate replay or reply storms
   while leaving the original durable delivery diagnosable.

## Notes

Implementation plan: [wake-first Relay delivery](../../docs/plans/2026-08-26-wake-first-relay-delivery.md).

Phase 0 decision and installed-runtime evidence:
[Relay wake feasibility](../../docs/designs/016-relay-wake-feasibility.md).

Current result: no runtime cleared the complete wake-safety gate. OpenCode idle
admission and Codex managed App Server queues are promising candidate surfaces,
but both need race-free disposable-session proofs; the installed Claude Code
configuration is passive-only until a Channel ingress is proven. Capability is
registered per live session; runtime names are not global wake guarantees.

Claude Code already documents idle-session wake and safe busy-session delivery.
OpenCode exposes session status and asynchronous prompting. Codex App Server can
resume and start turns and has an experimental follow-up queue, but safe atomic
idle admission must be proven before its adapter ships. Do not depend on an
undocumented runtime socket when a supported integration surface exists.

## Research References

Primary runtime sources:

- [Claude Code cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging)
- [Claude Code Channels](https://code.claude.com/docs/en/channels)
- [Claude Code v2.1.224 release](https://github.com/anthropics/claude-code/releases/tag/v2.1.224)
- [Claude Code Windows wake failure report](https://github.com/anthropics/claude-code/issues/86212)
- [Codex App Server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
- [Codex atomic idle-only admission request](https://github.com/openai/codex/issues/38289)
- [OpenCode server API](https://opencode.ai/docs/server/)
- [OpenCode plugin API](https://opencode.ai/docs/plugins/)

Feasibility evidence, not dependencies or adoption evidence:

- [Agent Intercom Claude adapter](https://github.com/dataforxyz/agent-intercom-claude)
- [Agent Intercom Codex adapter](https://github.com/dataforxyz/agent-intercom-codex)
- [Agent Intercom OpenCode adapter](https://github.com/dataforxyz/agent-intercom-opencode)
- [Agent Mail](https://github.com/osteele/agent-mail)

The runtime APIs are evolving. Recheck the primary documentation, installed
versions, preview flags, and open-issue status rather than copying version-specific
adapter behavior from this roadmap item.
