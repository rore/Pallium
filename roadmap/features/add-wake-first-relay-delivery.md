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
   invokes a wake command manually, or uses an app messaging tool to advance the test.
   Qualify the actual sessions used for work, not just disposable TUI substitutes.
2. **Claude↔Codex next:** add Claude's qualified idle-only adapter and validate the
   cross-runtime journey. Claude qualification does not block milestone 1.
3. **OpenCode later:** add its adapter after the first two milestones.

Milestone 1 includes the smallest persist-first coordinator needed by Codex,
dedupe, correlated admission, loss-safe active-writer fallback, wake/fallback claim-race protection,
restart/ambiguous-outcome recovery, expiry, bounded bursts/replies, and visible
fallback reasons. Exercise these through caller-surface regression tests plus a
live no-ping round trip; update local Codex integrations before acceptance.
Use the existing Relay developer session for implementation and architect review,
not a substitute subagent. Other runtimes retain next-turn delivery.

This is an independently acceptable dogfood milestone, not completion of the full
wake feature. Enable only qualified runtime/OS combinations; cross-platform
support remains required and unqualified combinations stay passive.

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
   same delivery pending for the existing next-natural-turn path. The immediate
   S2 contract gate below may add a terminal outcome only from separate,
   proven-terminal delivery evidence. Destination health never terminalizes an
   existing delivery; missing wake capability, ambiguous transport, and temporary
   runtime absence remain durable fallback, not failure.

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
| Codex | **Windows loaded and unloaded exact-session wake proven** | `codex exec resume` wakes an unloaded stored task. For a loaded Desktop-owned task, the post-August-2026 cross-process `codex queue --thread` watcher starts a real turn; Pallium queues a generic trigger; its installed UserPromptSubmit hook claims and injects the attributed delivery only after the target turn is admitted. | Windows live send → wake → atomic reply is proven. Qualify macOS/Linux, busy/interrupted/restart variants, correlation telemetry, and broader unattended dogfood before calling the runtime adapter complete. |
| OpenCode | Supported with a Pallium/OpenCode plugin coordinator | Server/plugin APIs expose stable sessions and async prompts. Agent Intercom demonstrates persist-first delivery, application metadata correlation, history verification before replay, safe busy deferral, and restart recovery. | A bare prompt_async 204 is transport acknowledgement only. Pallium needs the plugin-owned durable pending ledger and a Windows E2E proof. Deferred to after Claude Code wake is proven. |
| Claude Code | **Windows S1A+S1B qualified** | Installed Windows witness proved native peer Relay → exact restart-surviving capability → Stop claim/injection/ACK → Claude reply without another human prompt. | Installed UDS qualification on Linux/macOS remains S4. |

**Claude registration foundation:** Windows S1A+S1B are live-witness qualified: trusted-local exact-session persistence, write-ahead intents, fail-closed rehydration, and event-driven idle-pending reconciliation survived the installed restart witness. No DPAPI, silent time expiry, or lifetime redesign was added. Installed UDS qualification on Linux/macOS remains S4.
### Admission handshakes to preserve

**Codex:** Try hidden `codex exec resume` for an unloaded stored task. Only the exact active-writer conflict falls back to hidden `codex queue --thread` for the loaded Desktop owner. Pallium launches only a generic trigger. After the target turn is admitted, its installed UserPromptSubmit hook claims and injects the bounded backlog under the target's pinned scope, then acknowledges hook delivery. Launch failure leaves the delivery pending for ordinary next-turn recovery. No private App Server attachment is required.

**OpenCode:** the plugin persists the Relay item before broker acknowledgement,
checks recent session history for metadata.palliumRelayId, defers submission to a
safe boundary, calls the supported prompt API, and marks admission only when
session messages/events contain that exact ID. On restart it replays only items
not proven admitted. A server plugin can cover normal OpenCode sessions without
requiring every session to be launched by a Pallium wrapper.

**Claude Code:** Native peer frames start text turns but Claude 2.1.250 classifies them as internal `isMeta` events, so S0/S0.5 are misqualified for UserPromptSubmit admission. Claude reproduced S1A Stop continuation: every Stop registers idle; a non-recursive Stop makes one exact-scope `/relay/turn` with authoritative storage `max_chars=2360`, route admission marks busy, and renders the returned claimed set plus any compact backlog notice inside a fixed 2,400-character output budget before ACKing individually, and only the successful ACK subset is reformatted to stderr before exit 2 requests one continuation. Partial failure leaves unACKed claims lease-recoverable; all failure exits 0 and every non-continuing path re-registers idle after route admission. Storage budgets the exact emitted control template. `has_more` and `remaining_count` remain pending and are qualified under S1B rearm/continuation; the S1A witness historically proved one bounded batch. The `stop_hook_active` continuation Stop re-registers idle, ingests, and exits 0 without re-probing. No MCP/pin change belongs in S1A; durable state/reconciliation is S1B.

Each live session advertises only capabilities its integration actually proves:
passive, idle_wake, and busy_queue. Missing, expired, disabled, or lost capability
selects durable fallback. Runtime names are never global capability claims, and an
exited arbitrary process is not wakeable merely because its conversation can be
resumed by launching another process.

### Remaining production gates (priority updated 2026-09-05)

Gate each runtime independently. Claude Windows live wake and its deterministic
safety evidence are complete; only installed UDS qualification on Linux/macOS
remains for that adapter.

1. **Codex-first product gate:** Windows exact-session wake is now proven for
   unloaded tasks through `codex exec resume` and loaded Desktop-owned tasks
   through the cross-process queue watcher. A real `codex:@relaydev` run received
   two outstanding attributed deliveries in one wake batch and atomically replied
   to both without a user ping or approval prompt. Remaining gates are
   busy/interrupted/restart acceptance, sender-side reply admission on its queued
   turn, telemetry, macOS/Linux qualification, and a sustained
   implementation-review-remediation dogfood journey.

2. **Claude Code production gates:** Windows S1A+S1B live journey and deterministic
   caller-surface coverage are proven. Installed UDS qualification on Linux/macOS
   remains S4.
3. **MCP receive lifecycle foundation — code complete, runtime qualification pending:**
   `fix-relay-receive-mcp-lifecycle` is merged. The MCP path remains fail-closed
   and unqualified on Codex Desktop until a runtime-owned session handoff reaches
   the MCP child; hook-delivery wake does not depend on this recovery path.

### Next execution order (updated 2026-09-06)

The current work is RW-015 Codex admission hardening, followed by RW-010 restart
safety. RW-015's initial no-recovery diagnosis was corrected after durable status
and exact-task history showed both sends eventually admitted; the branch now fixes
only the genuine terminal-no-hook, exact-scope admission, and same-session
cross-scope ownership gaps. Both slices precede additional runtime and platform
expansion. Keep each numbered slice small
enough to implement, review, and report independently; use deterministic
clocks/events rather than wall-clock sleeps in the normal suite.

1. **S2 contract gate — complete in PR #98.** Delivery lifecycle
   (`pending`, `claimed`, `delivered`, `expired`; `failed` only on separate
   proven-terminal delivery evidence) remains independent from advisory destination
   health (`active` or `unreachable`). Destination-health transitions never
   change an existing delivery. Missing capability and recoverable or ambiguous
   transport leave it pending and retryable; advisory `unreachable` may reject new
   sends and clears on successful exact-session registration.
2. **S2 wake feedback and destination health — complete in PR #98.** Qualified
   Windows missing-pipe and POSIX missing-socket signals retain the durable
   registration as non-probed `unreachable`; the in-flight delivery remains
   pending. New exact/alias sends fail fast, strict timestamp CAS drops stale
   feedback, and successful exact registration restores both stores. Relay API
   status exposes delivery state and `destination_health` separately.
   Deterministic caller-surface review and installed Claude/Codex automatic-wake
   witnesses passed before merge.
3. **S2 Codex burst coalescing — complete in PR #95.** Per-session scheduling
   coalesces through admission, so several close sends cannot leave later empty
   generic wake turns. It rearms after admission and covers delivery completed by
   another turn, concurrent sends, active-writer fallback, failure, restart, and
   no lost pending work.
4. **S2 Codex MCP recovery and integration reload — complete in PR #99.**
   Runtime-owned per-call MCP metadata supplies exact task identity; inherited
   parent IDs and model arguments are ignored. Missing, malformed, or conflicting
   metadata fails closed before Relay HTTP with reload/upgrade guidance. Real
   stdio E2E and an installed fresh-session witness prove exact receive/ACK.
5. **S2 bounded backlog draining — complete in PR #101.** Default-three hook
   turns, continuation, new arrivals, ordering, oversized-first handling,
   duplicate-trigger loop prevention, and installed Codex plus Claude witnesses
   are complete. Keep the current three-message / 2,400-character limits until
   real burst measurement justifies a change.
6. **S3 Codex admission hardening — in progress (RW-015).** Preserve the native
   exact-session path with ownership qualified by container and actor scope, and
   distinguish blocking `exec resume` completion from an accepted asynchronous
   queue write or a timed-out exec/queue subprocess. A completed child without
   the exact session+scope hook callback releases its generation, marks only the
   still-current destination `unreachable` through strict CAS, and keeps delivery
   pending for the next real hook turn. Accepted queue writes and timed-out
   exec/queue subprocesses remain coalesced because native duplicate suppression
   is proven false. Require fast
   deterministic caller-surface E2E plus a post-merge no-manual-turn witness.
7. **Windows restart safety — then RW-010.** Preflight the stable checkout before
   stopping the healthy service, poll bounded readiness, verify `/health`,
   `/status`, and `/debug/queue/health`, and fail with actionable diagnostics.
   Tests inject process/HTTP outcomes and never sleep.
8. **S3 remaining Codex lifecycle gates.** After RW-015, qualify sender-side
   reply admission, correlation telemetry, and a sustained no-ping
   implementation/review/remediation journey.
9. **S4 additional platforms.** Qualify installed Claude UDS wake on Linux and
   macOS, then Codex wake on those platforms. Windows Claude S1A+S1B remains
   complete and must not be reopened without contrary evidence.
10. **OpenCode active wake.** Implement only after the Claude/Codex contract above
    is stable; retain its current passive next-turn delivery meanwhile.

### Wake dogfood defect ledger

Every confirmed dogfood failure stays here until a caller-surface regression and,
where the runtime exists locally, an installed witness close it.

| ID | Observed failure | State and owner |
|---|---|---|
| `RW-001` | A busy Codex wake claimed at scheduling time; queued execution after the 60-second lease produced a stale receipt conflict. A related Windows CP1252 write stranded a claimed Unicode delivery. | **Fixed.** Claim now occurs in the admitted UserPromptSubmit hook and subprocess input is UTF-8. Delayed deterministic caller-surface and Unicode regressions cover both paths. |
| `RW-002` | Several close sends queued later generic Codex turns after the first admitted turn had already drained the payload, producing empty conversational acknowledgement turns. | **Fixed in PR #95.** Per-session scheduling coalesces through admission and rearms afterward; concurrent, duplicate, failure, and restart acceptance is on `main`. |
| `RW-003` | An agent treated one stale/duplicate receipt conflict as a reason to stop the surrounding task, and terminal reports triggered wasteful status-only replies. | **Fixed.** Installed guidance says the stale rule applies only to that delivery, work continues independently, substantive replies wait for completion or blockage, and terminal ACK-only deliveries receive no reply. `test_guidance_budget.py` and hook guidance tests pin the contract. |
| `RW-004` | Pallium restart lost in-memory Claude wake capability, so pending Relay work required a manual Claude turn. | **Fixed and Windows-qualified.** Durable exact-session capabilities, write-ahead intents, event-driven reconciliation, restart recovery, and installed no-manual-wake evidence are on `main`; Linux/macOS UDS remains S4. |
| `RW-005` | Missing Claude endpoints were evicted while deliveries stayed pending; restart feedback was omitted, transient callback failure could diverge the two health stores, and a late-bound recovery callback could update the wrong session. | **Fixed in PR #98.** Retained non-probed `unreachable`, strict stale-feedback CAS, exception-safe retry, bound per-candidate callbacks, self-healing registration, status exposure, deterministic E2E, and installed witnesses are complete. |
| `RW-006` | A Codex MCP child can lack runtime-owned session identity or inherit another Codex task's forwarded identity and claim the wrong inbox. | **Fixed.** Per-request Codex transport metadata is authoritative; inherited `CODEX_*`, configured thread values, and model arguments are ignored. Missing/conflicting/malformed identity fails closed before HTTP. One-child real-stdio E2E covers exact ASCII/Unicode receive+ACK, max-boundary receive validation, and refusal paths; the installed synthetic witness returned the exact new Codex task ID instead of the outer ID. |
| `RW-007` | A bounded turn can report `has_more` and `remaining_count`, but integrations did not prove automatic bounded continuation until the eligible backlog was empty. | **Fixed in PR #101 and Windows-qualified.** Default-three hook turns, fixed character reservation, Codex post-ACK continuation, Claude Stop/recovery continuation, safe candidate selection, caller-surface edge coverage, and installed automatic 3+2 Codex plus Claude wake witnesses are complete. |
| `RW-008` | Crash after claim but before context injection recovers the lease, yet may wait for a natural turn instead of being re-woken automatically. | **Fixed in PR #102 and Windows-qualified.** A read-only exact-session sweep re-wakes eligible expired claims at startup and every 30 seconds through the existing adapters. Deterministic Codex/Claude restart E2E and an installed Codex witness prove automatic reclaim, single ACK, and terminal empty state after the 60-second lease expires. |
| `RW-009` | Wake E2E leaked synthetic memory into the live store; the observed `a043f627-...` object appeared under `other`. | **Fixed; reversible cleanup complete.** The unmocked live request is covered. The exact historical set was tagged `rw009-synthetic-wake-e2e-leak`: 23 source items were forgotten and 89 derived memories soft-deleted. The default dashboard read path now returns zero visible rows for the contaminated container; audit mode retains all 89 memories, including the cited object, for recovery. |
| `RW-010` | The Windows restart wrapper can stop a healthy service while a checkout is mid-edit and can print success before all required endpoints are ready; this recurred after PR #98. | **Open — near-term operations follow-up below.** Add preflight, bounded readiness polling, all three endpoint checks, actionable logs, and non-zero failure. |
| `RW-011` | A delegated agent can end or fail a model turn after hook delivery without the sender knowing whether requested work completed, causing manual polling or a stalled workflow. | **Optional product follow-up.** `idea-agent-relay.md` owns default-off `notify_on_turn_end`; it reports turn end/failure only and never reclassifies context delivery, infers task completion, or supervises work. |
| `RW-012` | A normal hook-injected delivery reached an agent without the trusted container and actor scope needed by `pallium_relay_reply`; reply failed closed and encouraged an out-of-band fallback. | **Fixed in PR #105; Windows-qualified.** Codex and every Claude hook delivery surface now append independently bounded exact scope before ACK; unsafe scope never claims. Real Codex queue and Claude UserPromptSubmit/Stop journeys parse that hook output and complete receiptless atomic replies, with wrong-scope, Unicode, maximum-boundary, backlog, and idempotence coverage. An installed Claude witness auto-woke, parsed the hook scope, and completed the exact receiptless reply without a manual turn or MCP receive. |
| `RW-013` | A Claude session reported its alias handle as `claude-code:claude_arch`, omitting the required `@`; the resulting exact-session selector returned 404 while the UUID worked. | **Fixed in PR #107; Windows-qualified.** Recipient pages now emit canonical `exact_selector` and `alias_selector` values. Existing routing was not rewritten: `codex:@relaydev` dogfood delivered and received `alias-ok`; caller-surface lifecycle coverage pins naming, transfer, close, exact fallback, alias send, filtering, and cross-scope isolation; Codex and Claude configs were reinstalled from clean main. |
| `RW-014` | `pallium_relay_recipients` can exceed the MCP response budget and return only a generic error instead of a usable bounded recipient result. | **Fixed in PR #107; Windows-qualified.** The MCP tool returns stable bounded pages with offset continuation and total count while preserving the HTTP list contract. Deterministic E2E covers all recorded boundaries without wall-clock waits. After reinstall and service restart from exact main, a fresh installed stdio child returned a 1,730-character page with all envelope fields, 5 of 89 recipients, canonical selectors, `has_more=true`, and `next_offset=5`. |
| `RW-015` | Two sends initially appeared stuck behind `destination_health=active`; later durable status and exact-task history proved both hook-delivered, including the vNext target after 57 seconds. The real latent gaps were boolean launch acceptance holding a generation after completed/no-hook exec, session-only admission, and session-only ownership suppressing another scope. | **In progress on `codex/fix-codex-unadmitted-wake`.** Wake ownership is keyed by session+container+actor, and blocking exec completion requires the matching hook callback; otherwise ownership releases, strict-CAS health becomes `unreachable`, and delivery stays pending. Accepted queue writes and timed-out exec/queue subprocesses stay coalesced because retry is unsafe without native idempotency. Deterministic HTTP→dispatch→real-hook E2E is green; close after PR review, merge, rollout, and a fresh installed no-manual-turn witness. |

The Windows Claude regression floor remains: idle text and zero-tool turns, empty
Stop rearm, busy delivery, ordered bursts, Unicode, recursive-Stop loop prevention,
duplicate send/trigger, arrivals during continuation, preservation of the original
human-owned turn, exact scope, and no manual prompt after a case begins. Deterministic
tests cover the contract; installed runtime witnesses stay opt-in to protect budget.

The following related work stays separate to keep ownership clear:

- `add-relay-retention-and-lifecycle-hardening` owns bounded cleanup of the final
  session/destination/delivery states defined here; it must not invent liveness or
  terminal-failure semantics independently.
- `idea-agent-relay.md` retains the optional default-off `notify_on_turn_end`
  proposal. Turn end is not task completion and is not a prerequisite for delivery
  correctness.
- `validate-relay-dependency-workflows` starts only after S2/S3 are stable.
- The local wake-test pollution repair is complete and reversible: the exact 23
  synthetic source items are forgotten and 89 derived memories are soft-deleted
  under one audit reason; the default dashboard read path exposes none of them.
  This was operational data repair, not Relay routing behavior.
- **Near-term operations follow-up (separate from S2):** harden the Windows
  restart wrapper after the dogfood incident: preflight syntax/imports before
  stopping a healthy service; bounded-poll readiness; verify `/health`, `/status`,
  and `/debug/queue/health`; emit actionable logs and a non-success result on
  failure; and never restart from a checkout that another agent is mutating.

The remaining S2 qualification is done only with caller-surface E2E for fresh
versus stale MCP hosts, bounded backlog, memory routing, Unicode, scope isolation,
restart, and idempotence. Existing unknown, passive, unreachable, self-healing
registration, retryable/qualified missing-endpoint transport, async status, burst
coalescing, and delivery-before-queued-execution regressions remain mandatory.
Tests must be fast and deterministic; installed-runtime witnesses remain opt-in
release gates.

**Core scope:** Derive the smallest coordinator from the Codex delivery trace.
Do not wait for a second adapter or build speculative multi-runtime machinery.
Choose bounded limits from Codex evidence; revisit only when adding another adapter.

### Implementation sequence — Codex first

**Codex (Windows candidate):** `codex exec resume T` handles unloaded stored tasks; the exact active-writer conflict falls back to `codex queue --thread T`, whose owning Desktop watcher starts the loaded task. Pallium supplies a generic trigger; the admitted UserPromptSubmit hook claims and injects the attributed batch under the target scope. MCP receive remains a separate fail-closed recovery path. Keep the adapter runtime/version-qualified until the remaining OS and lifecycle gates pass.

**Claude Code:** S0/S0.5 are misqualified because Claude 2.1.250 peer frames bypass `UserPromptSubmit` as internal `isMeta` events. Claude reproduced S1A Stop continuation; Codex architect review is clean, exact-scope bounded Stop `/relay/turn`, candidate render, successful-subset ACK/reformat, and one exit-2 continuation—not MCP—provide peer-wake admission. Do not treat generic native notice as delivery.
Keep Channels deferred and macOS/Linux passive until UDS E2E passes.

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

Current result: Codex exact-session wake uses hidden `codex exec resume` for an unloaded stored task. The Windows desktop app retains active writers, so the live adapter falls back to hidden `codex queue --thread` for that exact session; both launch paths are best-effort and retain durable natural-turn fallback on launch failure. The active-writer fallback explicitly encodes Relay prompts as UTF-8, and the pre-fix claim-before-queue behavior reproduced a 409 `claim lease has expired` when a delivery was claimed before queueing and the queued turn executed after the lease. The live adapter now queues a generic trigger and lets the installed UserPromptSubmit hook claim at admitted-turn execution; delayed busy-target caller-surface E2E proves no stale receipt, loss, or duplicate action. Hook-delivery wake and per-session burst coalescing are proven for the tested Windows paths. A Relay-wide read-only sweep now re-wakes eligible expired claims for active exact Codex and Claude sessions immediately at service startup and every 30 seconds, then the admitted hook reclaims and ACKs normally; controlled-clock real-hook E2E covers both runtimes and both full-app restarts. An installed Windows Codex witness deliberately abandoned a claimed delivery, then observed automatic hook delivery on attempt two after the 60-second lease expired, without a manual wake. Codex MCP receive and bounded automatic backlog drain are Windows-qualified; remaining interrupted admission, sender-side reply admission, telemetry, macOS/Linux, and sustained dogfood also remain. Claude Windows wake is complete, installed UDS is S4, and OpenCode remains deferred.

## Research References

Primary runtime sources:

- [Claude Code cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging)
- [Claude Code Channels](https://code.claude.com/docs/en/channels)
- [Claude Code v2.1.224 release](https://github.com/anthropics/claude-code/releases/tag/v2.1.224)
- [Claude Code native-Windows delivery issue history](https://github.com/anthropics/claude-code/issues/86603)
- [Codex App Server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
- [Codex queue integration tests](https://github.com/openai/codex/blob/main/codex-rs/app-server/tests/suite/v2/thread_queue.rs)
- [Codex Windows active-writer/no-attach limitation](https://github.com/openai/codex/issues/37450)
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

### Historical accepted Claude S1B restart-durability plan (Windows-qualified)

The critical outage window is Claude reaching Stop while Pallium is down: loopback registration fails and a restart would otherwise preserve stale busy. Canonical capability remains `~/.pallium/claude-wake/capabilities.json` (Windows `%USERPROFILE%\.pallium\claude-wake\capabilities.json`) with exact scope/socket/token/generation plus `busy`, `idle`, or `wake_inflight(delivery_id, utc_attempt_time)`. The existing registry lock serializes normal register, state changes, and same-session intent take/apply/removal. Add only `~/.pallium/claude-wake/intents/<sha256(session_ref)>.json`: before HTTP registration, the hook atomically writes the exact state with a random `intent_id` and sends that id in the request. Under lock, the request id must equal the currently stored intent before any canonical mutation; mismatch rejects/no-ops. Success writes canonical then consumes only that exact intent. Ambiguous responses retain/retry the same intent, never create/rewrite a later one; crashes and delayed old requests are deterministically idempotent.

Persistence is state-specific: failed idle registration does not publish idle and failed idle→inflight does not transport; ordinary idle/inflight writes precede publication/effect. Failed busy persistence immediately marks memory busy and must make stale durable idle unloadable before continuing. If that cannot be quarantined/deleted, persist one `store-unusable` marker checked before startup loads capabilities; no rehydration occurs until trusted registration/intent repair. If neither quarantine nor marker persists, startup refuses rehydration while stale file exists. POSIX directory/file `0700`/`0600`; Windows inherits user-profile ACL; no DPAPI/custom DACL. Bad data is ignored, but a valid capability is not discarded solely for permission-setting failure. No TTL/age cleanup: online SessionEnd removes its record; offline SessionEnd writes a closed/removal intent. At the 256 cap only, non-admitting endpoint-absence checks may reclaim provably missing endpoints. Never `registry.probe`, auth, write, or open; POSIX socket nodes and busy/timeout Windows pipes are uncertainty, retained, and new registration rejects. Only SessionEnd or a truly missing endpoint is terminal; all uncertain transport is retryable.

Use a minimum read-only exact-scope storage/service pending-candidate query before recovery dispatch; it never claims/ACKs. Claimed/delivered/expired clears inflight retry; pending waits bounded grace then can retry. One event-driven reconciler is signaled by readiness/new-send/registration/intent consumption; its capped Condition/Event wait periodically scans write-ahead intents. Signals coalesce and retries continue indefinitely while exact pending+eligible work remains, with capped backoff and no busy loop or finite retry count. Crash windows prefer an extra empty admission, never lost Relay work.

Required fast E2E includes delayed old intent mismatch, every write-ahead intent crash/response-loss boundary, busy failure→restart with stale file, offline SessionEnd, crash-without-SessionEnd capacity pressure, live endpoint at cap with zero native writes/admissions, post-start intent discovery, corrupt intent/capability, Unicode path, duplicate/concurrency, typed transport, indefinite capped retry, and non-claiming query. Windows no-manual-re-registration restart wake/Stop claim/inject/reply is qualified.
**Review status:** Windows S1B implementation and installed restart witness are accepted. Linux/macOS installed UDS qualification remains S4.
