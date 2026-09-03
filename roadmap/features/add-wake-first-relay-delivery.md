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
| Codex | **Windows loaded and unloaded exact-session wake proven** | `codex exec resume` wakes an unloaded stored task. For a loaded Desktop-owned task, the post-August-2026 cross-process `codex queue --thread` watcher starts a real turn; Pallium queues a generic trigger; its installed UserPromptSubmit hook claims and injects the attributed delivery only after the target turn is admitted. | Windows live send → wake → atomic reply is proven. Qualify macOS/Linux, busy/interrupted/restart variants, correlation telemetry, and broader unattended dogfood before calling the runtime adapter complete. |
| OpenCode | Supported with a Pallium/OpenCode plugin coordinator | Server/plugin APIs expose stable sessions and async prompts. Agent Intercom demonstrates persist-first delivery, application metadata correlation, history verification before replay, safe busy deferral, and restart recovery. | A bare prompt_async 204 is transport acknowledgement only. Pallium needs the plugin-owned durable pending ledger and a Windows E2E proof. Deferred to after Claude Code wake is proven. |
| Claude Code | **S1A complete; S1B restart durability blocked** | Installed Windows witness proved native peer Relay → Stop claim → attributed stderr/exit-2 injection → Claude reply without another human prompt. | Restart erases the memory-only exact-session registration, leaving delivery pending until manual re-registration. S1B plan now requires durable busy/idle/wake_inflight state, outage-time hook intent handoff, a read-only pending query, and indefinite bounded-backoff reconciliation; no runtime change before plan review. |

**Claude registration foundation:** S1A is live-witness complete. The restart incident proves that the existing loopback-only, memory-only exact-session registry is not a restart contract: service restart loses the registration and natural delivery remains pending. S1B is plan-only trusted-local capability persistence, rehydration, and event-driven idle-pending reconciliation; no DPAPI, silent time expiry, or lifetime redesign.
### Admission handshakes to preserve

**Codex:** Try hidden `codex exec resume` for an unloaded stored task. Only the exact active-writer conflict falls back to hidden `codex queue --thread` for the loaded Desktop owner. Pallium launches only a generic trigger. After the target turn is admitted, its installed UserPromptSubmit hook claims and injects the bounded backlog under the target's pinned scope, then acknowledges hook delivery. Launch failure leaves the delivery pending for ordinary next-turn recovery. No private App Server attachment is required.

**OpenCode:** the plugin persists the Relay item before broker acknowledgement,
checks recent session history for metadata.palliumRelayId, defers submission to a
safe boundary, calls the supported prompt API, and marks admission only when
session messages/events contain that exact ID. On restart it replays only items
not proven admitted. A server plugin can cover normal OpenCode sessions without
requiring every session to be launched by a Pallium wrapper.

**Claude Code:** Native peer frames start text turns but Claude 2.1.250 classifies them as internal `isMeta` events, so S0/S0.5 are misqualified for UserPromptSubmit admission. Claude reproduced S1A Stop continuation: every Stop registers idle; a non-recursive Stop makes one exact-scope `/relay/turn` with authoritative storage `max_chars=2400`, route admission marks busy, and renders the returned claimed set without a competing formatter cap before ACKing individually, and only the successful ACK subset is reformatted to stderr before exit 2 requests one continuation. Partial failure leaves unACKed claims lease-recoverable; all failure exits 0 and every non-continuing path re-registers idle after route admission. Storage budgets the exact emitted control template. `has_more` and `remaining_count` remain pending and are unqualified until S1B. The `stop_hook_active` continuation Stop re-registers idle, ingests, and exits 0 without re-probing. No MCP/pin change belongs in S1A; durable state/reconciliation is S1B.

Each live session advertises only capabilities its integration actually proves:
passive, idle_wake, and busy_queue. Missing, expired, disabled, or lost capability
selects durable fallback. Runtime names are never global capability claims, and an
exited arbitrary process is not wakeable merely because its conversation can be
resumed by launching another process.

### Remaining production gates (priority updated 2026-09-02)

Gate each runtime independently. Claude Windows live qualification is next;
enabling live wake still requires the relevant safety evidence.

1. **Codex-first product gate:** Windows exact-session wake is now proven for
   unloaded tasks through `codex exec resume` and loaded Desktop-owned tasks
   through the cross-process queue watcher. A real `codex:@relaydev` run received
   two outstanding attributed deliveries in one wake batch and atomically replied
   to both without a user ping or approval prompt. Remaining gates are
   busy/interrupted/restart acceptance, sender-side reply admission on its queued
   turn, telemetry, macOS/Linux qualification, and a sustained
   implementation-review-remediation dogfood journey.

2. **Claude Code production gates:** S1A's complete Windows live journey and deterministic caller-surface coverage are proven. Production is blocked on S1B trusted-local restart durability—rehydration, idle-only pending reconciliation, and a no-manual-re-registration restart witness—then macOS/Linux UDS qualification.
3. **MCP receive lifecycle foundation — code complete, runtime qualification pending:**
   `fix-relay-receive-mcp-lifecycle` is merged. The MCP path remains fail-closed and unqualified on Codex Desktop until a runtime-owned session handoff reaches the MCP child; hook-delivery wake does not depend on this recovery path.

### Next execution order

1. **Claude S1B restart durability:** plan review only. Reuse the existing registry/storage/dispatch to persist user-private exact capabilities, rehydrate valid records before dispatch, and reconcile idle pending delivery once. Do not implement before Codex plan review; final gate is the no-manual-re-registration Windows restart witness.
2. **Claude S1A Stop admission:** COMPLETE — Architect re-review and installed no-human witness are PASS: every non-continuing Stop re-registers idle after route admission; UTF-8 stderr buffer fallback emits before exit 2; storage budgets the exact emitted template. The non-recursive authoritative-storage `/relay/turn` uses `max_chars=2400`, then returned-set candidate-render/individual-ACK/success-subset-reformat/exit-2 continuation. Module-form real-hook HTTP coverage passes for empty rearm, max/over-budget-skip-then-fitting-render/`has_more`/`remaining_count`/Unicode, scope/failure, recursion, partial/all ACK, duplicate, continuation ingest/rearm, and lease recovery.
3. **Codex remaining lifecycle gates:** qualify busy/interrupted/restart admission,
   sender-side reply admission, correlation telemetry, and sustained no-ping
   implementation/review/remediation dogfood.
4. **Codex MCP recovery:** keep receive fail-closed unless Codex Desktop supplies a
   runtime-owned session identity to the MCP child; this is not a blocker for the
   qualified hook-delivery path.
   S3 dogfood regression: a parent `CODEX_THREAD_ID` does not prove the MCP child inherited it; absent child identity must fail closed rather than borrow parent process context.
5. **Additional platforms:** qualify Claude UDS and Codex wake on macOS/Linux only
   after their Windows lifecycle gates pass.
6. **Optional correlated turn-end notification:** retain the default-off proposal
   in `roadmap/ideas/idea-agent-relay.md`; it improves supervision but is not a
   prerequisite for Claude wake correctness.

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

Current result: Codex exact-session wake uses hidden `codex exec resume` for an unloaded stored task. The Windows desktop app retains active writers, so the live adapter falls back to hidden `codex queue --thread` for that exact session; both launch paths are best-effort and retain durable natural-turn fallback on launch failure. The active-writer fallback explicitly encodes Relay prompts as UTF-8, and the pre-fix claim-before-queue behavior reproduced a 409 `claim lease has expired` when a delivery was claimed before queueing and the queued turn executed after the lease. The live adapter now queues a generic trigger and lets the installed UserPromptSubmit hook claim at admitted-turn execution; delayed busy-target caller-surface E2E proves no stale receipt, loss, or duplicate action. Hook-delivery wake is proven for the tested Windows paths. Codex MCP receive remains fail-closed and unqualified on Desktop because no runtime-owned identity handoff reaches its child. Codex wake remains unqualified only for interrupted/restart admission, sender-side reply admission, telemetry, macOS/Linux, and sustained dogfood; Claude idle-only work follows the Codex-first milestone, and OpenCode remains deferred.

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

### Claude S1B restart-durability plan (amended; plan only)

The critical outage window is Claude reaching Stop while Pallium is down: loopback registration fails and a restart would otherwise preserve stale busy. Canonical capability remains `~/.pallium/claude-wake/capabilities.json` (Windows `%USERPROFILE%\.pallium\claude-wake\capabilities.json`) with exact scope/socket/token/generation/UTC `updated_at` ordering value plus `busy`, `idle`, or `wake_inflight(delivery_id, utc_attempt_time)`. Add only `~/.pallium/claude-wake/intents/<sha256(session_ref)>.json`: the hook atomically writes/replaces it only after HTTP registration failure. After readiness the service atomically takes/validates it, accepts only a newer intent, durably writes canonical state before registry publication, and then removes the taken intent. Thus outage Stop can override stale busy without another hook/human/send; older intent cannot override later canonical state.

Every canonical registration, busy/idle mutation, and idle→inflight is durable before publish/effect; persistence failure blocks transport and emits only sanitized observability, never Relay mutation. POSIX directory/file `0700`/`0600`; Windows inherits user-profile ACL; no DPAPI/custom DACL. Permission setting is hygiene: bad data is ignored, but a valid capability is not discarded solely for permission-setting failure. No TTL/age cleanup: SessionEnd or a truly missing endpoint alone deletes. Typed transport is accepted/inflight, retryable/idle, or terminal/delete only for missing endpoint; uncertainty is retryable.

Use a minimum read-only exact-scope storage/service pending-candidate query before recovery dispatch; it never claims/ACKs. Claimed/delivered/expired clears inflight retry; pending waits bounded grace then can retry. One event-driven reconciler is signaled by readiness/new-send/registration/intent consumption; signals coalesce and retry indefinitely while exact pending+eligible work remains, with capped interval but no finite retry count. Crash windows prefer an extra empty admission, never lost Relay work.

Required fast E2E includes outage Stop then restart with no later hook/human/send, idle/busy/pending/send restarts, all persistence write boundaries, corrupt/stale intent/capability, permission/persistence failure observability, Unicode path, duplicate/concurrency, typed transport, indefinite capped retry, and non-claiming query. Final gate is real Windows no-manual-re-registration restart wake/Stop claim/inject/reply.

**Review status:** NOT CLEAN. Codex must accept this amended S1B plan before runtime edits.