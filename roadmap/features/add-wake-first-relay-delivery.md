---
id: add-wake-first-relay-delivery
title: Add wake-first Relay delivery
status: active
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

## Primary Product Outcome

After one user instruction, a developer session and an architect/reviewer session
can carry a bounded implementation-review-remediation exchange through explicit
Relay messages without the user prompting either recipient to check for mail. Each
send wakes the addressed live session, enters its model-visible context exactly
once, and can receive an explicit delivery-derived reply. The user re-enters only
for a permission, product decision, unresolved failure, or requested final result.

This is the main wake validation journey, not a later demo. It does not make
Pallium a team manager: the user still starts the work, agents explicitly choose
when and whom to message, and Pallium only persists, addresses, activates, and
reports delivery. `fix-relay-claim-before-context-emission` (`RF-005`) is a release
prerequisite because both wake and fallback must be loss-safe.

### Milestone order (user priority, 2026-08-31)

1. **Codex↔Codex dogfood first:** the existing Codex architect and developer
   sessions exchange a bounded task → result → review → remediation/verdict
   sequence through Relay alone. Send and reply activate the exact recipient in
   both directions; neither the user nor either agent sends a separate ping,
   invokes the queue manually, or uses an app messaging tool to advance the test.
   Qualify the actual sessions used for work, not just disposable TUI substitutes.
2. **Claude↔Codex next:** add Claude's qualified idle-only adapter and validate the
   cross-runtime journey. Claude qualification does not block milestone 1.
3. **OpenCode later:** add its adapter after the first two milestones.

Milestone 1 includes the smallest persist-first coordinator needed by Codex,
dedupe, correlated admission, safe busy queuing, wake/fallback claim-race protection,
restart/ambiguous-outcome recovery, expiry, bounded bursts/replies, and visible
fallback reasons. Exercise these through caller-surface regression tests plus a
live no-ping round trip; update local Codex integrations before acceptance.
Use the existing Relay developer session for implementation and architect review,
not a substitute subagent. Other runtimes retain next-turn delivery.

This is an independently acceptable dogfood milestone, not completion of the full
wake feature. Enable only qualified runtime/OS combinations; cross-platform
support remains required and unqualified combinations stay passive.

### Batch and fallback design review (2026-08-31)

Canonical proposed milestone-1 design:
[Relay batches and Codex-first wake](../../docs/designs/relay-batch-codex-wake.md).
It adds atomic multipart send/reply, whole-batch regular-turn delivery, retry
identities, bounded backlog drainage, and MCP/skill usability as release criteria.
The proposed Codex wake is notification-only; batch payloads use the same inbox
path as regular user turns. Queue-triggered hook/admission/fencing evidence and
independent review by `claude-code:@claude_arch` remain mandatory before coding.
This revision supersedes conflicting older state/timeout rules and unconditional
exactly-once language below: uncertain batch publication is not proof of failure and needs reconciliation
before replay. Uncertain notification-only wake does not reserve payloads or
prevent a regular turn from claiming still-pending batches.
Production batch delivery and wake are not enabled. The B1 foundation is accepted;
B2 candidate code has been implemented in disposable environments. Its final
hardening (starting at `7621ab4`, plus the count-range review correction) passes
296 combined Relay tests and the import-boundary
check; independent final candidate review is accepted. This is not runtime qualification.
See [candidate review and qualification order](../../docs/designs/relay-batch-b2-candidate-review.md)
and [B2 Work Record](../../.agent-workflow/tasks/codex-relay-batch-wake-b2.md).
G2/G3 gate the new passive batch path as well as wake. Next is full-envelope
Codex context/admission and backlog-headroom qualification, then reviewed migration
and compatible integration rollout before activation. Claude remains deferred.

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

Deeper source review on 2026-08-26 corrected the initial Phase 0 verdict. The
installed versions are Claude Code 2.1.250, Codex CLI 0.149.1, and OpenCode
1.18.19 on native Windows.

| Runtime | Current verdict | Proven mechanism | Remaining qualification |
|---|---|---|---|
| Codex | **Passive-only; partial Phase 0** | `codex queue --thread` proved exact-session admission while idle and at a safe busy boundary with correlated model-visible evidence. The separately launched App Server remains rejected. Native queue idempotency failed. | Production is gated by cases 5, 6, and 7 plus coordinator-owned idempotency/fallback and `fix-relay-receive-mcp-lifecycle`. |
| OpenCode | Supported with a Pallium/OpenCode plugin coordinator | Server/plugin APIs expose stable sessions and async prompts. Agent Intercom demonstrates persist-first delivery, application metadata correlation, history verification before replay, safe busy deferral, and restart recovery. | A bare prompt_async 204 is transport acknowledgement only. Pallium needs the plugin-owned durable pending ledger and a Windows E2E proof. Deferred to after Claude Code wake is proven. |
| Claude Code | **Passive-only; partial Phase 0 via native Windows idle wake** | On 2.1.250, the existing memory-only `SessionStart` registration enabled an isolated same-process transport to start a distinct turn in one exact verified-idle disposable session; a simultaneous non-target session was untouched. Channels remained unavailable with the documented hidden flag. | Production must be `idle_wake` only: direct busy ingress joined the active turn, duplicate message IDs were admitted twice, and closed pipes failed. Add coordinator dedupe, verified-idle dispatch, correlated `Stop` admission, restart/error fallback, and macOS/Linux UDS E2E. |

**Claude registration foundation (2026-08-28):** `SessionStart` and `Stop` now
refresh an exact-session credential through a loopback-only, memory-only
registration endpoint with fixed 900-second expiry. The endpoint has no public
probe, status, or clear operation; the service has no named-pipe transport in this
slice, and restart falls back because credentials are not persisted. This is a
security handoff only, not evidence of target admission or coordinator readiness.

### Admission handshakes to preserve

**Codex:** `codex queue --thread` is the evidenced exact-session ingress candidate, but no production handshake is selected. It reached the exact existing session while idle and at a safe busy boundary with correlated model-visible admission. A future coordinator must own one stable delivery/wake attempt, dedupe, admission observation, and fallback. The managed App Server path remains rejected because it does not reach the exact already-running session addressed by Relay.

**OpenCode:** the plugin persists the Relay item before broker acknowledgement,
checks recent session history for metadata.palliumRelayId, defers submission to a
safe boundary, calls the supported prompt API, and marks admission only when
session messages/events contain that exact ID. On restart it replays only items
not proven admitted. A server plugin can cover normal OpenCode sessions without
requiring every session to be launched by a Pallium wrapper.

**Claude Code:** `SessionStart` and `Stop` register/refresh the per-session native inbox in Pallium's loopback-only, memory-only registry. `Stop` is the primary verified-idle boundary; `user_prompt_submit` exit is not. On qualified native Windows 2.1.250, an authenticated named-pipe write to an exact idle disposable session started a distinct model-visible turn, while a non-target session was untouched. The adapter must advertise only `idle_wake`: a write during a 25-second tool call joined the active turn and was not handled as a distinct request. Claude also admitted two identical frames carrying one message ID twice, so Pallium must deduplicate and suppress ambiguous retries before transport. A closed pipe is stale/unavailable and releases durable next-turn fallback. Admission is correlated only when the receiving session's `Stop` hook reports the exact `delivery_id`; pipe acceptance never completes Relay delivery. Channels remain a future opt-in alternative, but were unavailable with the documented hidden development flag in the qualified environment.

Each live session advertises only capabilities its integration actually proves:
passive, idle_wake, and busy_queue. Missing, expired, disabled, or lost capability
selects durable fallback. Runtime names are never global capability claims, and an
exited arbitrary process is not wakeable merely because its conversation can be
resumed by launching another process.

### Remaining production gates (priority updated 2026-08-31)

Gate each runtime independently. Codex-first work may proceed without waiting for
Claude or OpenCode; enabling live wake still requires the relevant safety evidence.

1. **Codex-first product gate:** The first outcome is unattended Codex↔Codex.
   Phase 0 proves `codex queue --thread <T>` for idle and safe busy-boundary
   admission in the tested sessions. Qualify the actual architect/developer pair,
   close cases 5, 6, and 7, and implement coordinator-owned dedupe and fallback
   before enabling wake. The proven subset is not a production-ready adapter.

2. **Claude Code production gates:** Native Windows exact-session idle wake is
   proven on 2.1.250; Channels is unavailable in the qualified environment.
   Production remains blocked on persist-first coordinator dedupe, verified-idle
   dispatch, exact `Stop`-hook admission, stale/restart/error fallback, and
   macOS/Linux UDS E2E. Never send native ingress while busy and never retry an
   ambiguous write without coordinator proof that no admission occurred.

3. **MCP receive lifecycle foundation — complete:**
   `fix-relay-receive-mcp-lifecycle` is merged. Wake can reuse receipt-based
   recovery without raw HTTP or model-visible claim tokens.

**Core scope:** Derive the smallest coordinator from the Codex delivery trace.
Do not wait for a second adapter or build speculative multi-runtime machinery.
Choose bounded limits from Codex evidence; revisit only when adding another adapter.

### Implementation sequence — Codex first

**Codex (partial Phase 0):** `codex queue --thread T` proved exact-session idle
and safe busy-boundary admission in the existing TUI. The remaining safe evidence
gates are closed/stale/permission handling, outstanding-trigger and already-admitted
restart recovery, and ambiguous-response fallback. Native duplicate suppression
failed, so any future coordinator must dedupe before invoking the queue. App Server
path remains rejected.

**Claude Code (after Codex dogfood):** Extend the coordinator only
for verified-idle native delivery: persist/dedupe before write, exact delivery-ID
admission from `Stop`, and fallback on busy/stale/error/restart. Add deterministic
Windows E2E for the observed exact-target, duplicate, busy, and closed boundaries.
Keep Channels deferred and keep macOS/Linux passive until UDS E2E passes.

**OpenCode:** Deferred until after Claude Code AND Codex are both proven.

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
- launching or managing a parallel runtime/session as a substitute for the
  existing session addressed by the sender
- spawning agents, assigning work, or supervising completion
- sender-selected wake syntax or semantic wake decisions
- treating runtime admission as proof that the agent understood or used a message
- automatic agent conversations or unbounded reply chains
- Pallium deciding that another review or implementation pass should happen; the
  participating agent must explicitly send each handoff or reply

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

8. A live Claude Code developer → Codex architect → Claude Code remediation →
   Codex verdict journey completes after one initial user instruction and no
   intermediate user prompts. Repeat with the runtime roles reversed where the
   installed integrations support it.
9. That journey remains exact-once and model-visible when either recipient is
   idle or busy, and across a Pallium or recipient-integration restart. If wake
   cannot be admitted, the delivery remains durable and the dashboard/status
   exposes the fallback or actionable failure rather than silently stalling.

## Notes

Implementation plan: [wake-first Relay delivery](../../docs/plans/2026-08-26-wake-first-relay-delivery.md).

Phase 0 decision and installed-runtime evidence:
[Relay wake Phase 0 decision record](../../docs/designs/017-relay-wake-phase0.md).

Current result: exact-session ingress is proven for Codex through `codex queue
--thread` and for verified-idle Claude Code on native Windows through its registered
named-pipe inbox. Claude Channels were unavailable in the qualified environment;
busy native Claude ingress is unsafe, and neither transport provides sufficient
deduplication. The next production slice is the smallest persist-first coordinator
plus Codex queue adapter and a live Codex↔Codex no-ping acceptance run. Claude's
idle-only adapter follows; OpenCode remains deferred until the automatic
Claude↔Codex handoff works. None of these claims changes passive next-turn fallback.

## Research References

Primary runtime sources:

- [Claude Code cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging)
- [Claude Code Channels](https://code.claude.com/docs/en/channels)
- [Claude Code v2.1.224 release](https://github.com/anthropics/claude-code/releases/tag/v2.1.224)
- [Claude Code native-Windows delivery issue history](https://github.com/anthropics/claude-code/issues/86603)
- [Codex App Server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
- [Codex queue integration tests](https://github.com/openai/codex/blob/main/codex-rs/app-server/tests/suite/v2/thread_queue.rs)
- [Codex atomic idle-only admission request](https://github.com/openai/codex/issues/38289)
- [OpenCode server API](https://opencode.ai/docs/server/)
- [OpenCode plugin API](https://opencode.ai/docs/plugins/)
- [OpenCode prompt acceptance without wake issue](https://github.com/anomalyco/opencode/issues/21524)
- [Claude Agent SDK session resume](https://code.claude.com/docs/en/agent-sdk/sessions)

Feasibility evidence, not dependencies or adoption evidence:

- [Agent Intercom Claude adapter](https://github.com/dataforxyz/agent-intercom-claude)
- [Agent Intercom Codex adapter](https://github.com/dataforxyz/agent-intercom-codex)
- [Agent Intercom OpenCode adapter](https://github.com/dataforxyz/agent-intercom-opencode)
- [Agent Mail](https://github.com/osteele/agent-mail)

The runtime APIs are evolving. Recheck the primary documentation, installed
versions, preview flags, and open-issue status rather than copying version-specific
adapter behavior from this roadmap item.
