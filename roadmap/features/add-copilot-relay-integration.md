---
id: add-copilot-relay-integration
title: Add GitHub Copilot Relay integration
status: queued
priority: high
commitment: committed
milestone: pallium-relay
lane: integration
---

## Summary

After wake-first Relay is working for Claude Code, Codex, and OpenCode, add GitHub
Copilot as another Relay runtime. Copilot support means a Copilot agent session can
register, receive an explicitly addressed message, wake or queue a distinct turn,
prove runtime admission, and send or reply through the common Relay surfaces.

This is a runtime integration, not a new product track and not a way for Pallium to
call a Copilot model as a generic inference provider.

## Sequencing

Do not start this item until the three primary runtime integrations satisfy
`add-wake-first-relay-delivery`. Copilot must adopt that proven contract rather
than changing it. Reuse the dependency, decision-round-trip, and cross-model
review journeys from `validate-relay-dependency-workflows` when judging value.

## Integration Strategy

Try the supported VS Code Agent Host / Agent Host Protocol (AHP) first. It exposes
host-owned persistent sessions, synchronized state, and client-driven turns, which
best match Relay's wake and admission requirements. AHP is evolving, so exact
actions and fields found during research are PoC hypotheses until verified against
the installed protocol version.

If AHP cannot satisfy the contract, try a Pallium-managed Copilot SDK session. This
is a distinct topology and must be labeled as such: it might not be the same chat
the user sees in VS Code. The SDK currently exposes persistent session IDs,
enqueue-mode prompts, history/events, and application-managed concurrency.

If neither wake-capable route is permitted but supported hooks can inject pending
Relay context on a later natural turn, expose Copilot as passive-only. Hooks are
not wake. If no supported route is permitted, report Copilot as unavailable. Never
fall back to UI automation or private editor commands.

## Capability and Identity Contract

Register capabilities per live session and integration mode, never globally for
the `copilot` runtime. The profile must distinguish at least passive delivery,
idle wake, busy queue, distinct-turn behavior, admission evidence, and validated
restart recovery.

The canonical recipient is an immutable host or SDK session/chat resource. Mutable
chat titles are discovery metadata only. A renamed chat or a new chat with the same
title must not inherit deliveries addressed to the original session. Preserve the
existing optional Pallium alias and container isolation rules.

Copilot must use the common Relay list, send, reply, and status contracts. Prefer
the existing MCP tools when effective policy permits them; do not create a
Copilot-specific message protocol merely for convenience.

## Wake and Admission Contract

For normal Relay delivery, queue a distinct future turn; never steer into an
active human-owned turn. Persist the Relay delivery before runtime submission and
carry its stable identifier across the runtime boundary.

The AHP PoC should test the currently researched queued-message path, including
whether a client can submit a queued item using the Relay delivery ID and whether
the resulting turn-start event exposes the same queued ID. Treat an accepted or
echoed action as submitted, not delivered. Mark Relay delivery only after positive
runtime evidence proves that the exact item initiated a turn.

For an SDK-managed session, use enqueue rather than immediate mode, serialize
access to the session, and correlate events/history with the Relay delivery ID.
Do not require the model to call an acknowledgement tool: transport correctness
must come from the runtime boundary, not model compliance.

Runtime admission proves only that the message entered the context. Turn
completion, semantic understanding, agreement, and useful downstream action are
separate observations.

## Enterprise Policy and Security

Capability detection must use effective behavior and policy, not assume that
Copilot Chat availability permits AHP, SDK, hooks, plugins, external tools, or MCP.
A benign startup smoke check should report the usable mode and downgrade reason.

The integration must:

- respect centrally managed Copilot and VS Code policy without bypasses
- bind Pallium-controlled endpoints to the local machine
- use supported Agent Host authentication and avoid retaining Copilot credentials
- preserve repository/container isolation and ordinary sandbox/approval behavior
- present Relay input as attributed, lower-authority peer-agent context
- reject Relay messages as permission or consent grants
- fail closed rather than silently using an unsupported surface

Keep roadmap, fixtures, logs, and public documentation free of organization names,
account identifiers, workstation names, tokens, internal repository names, and
other environment-specific terminology.

## Proof-of-Concept Gate

Run the first experiment on a supported, enterprise-managed Windows installation:

1. Detect the installed VS Code, Copilot, Agent Host, and AHP versions and effective
   policy without recording private environment identifiers.
2. Start or connect to a supported Agent Host and register one immutable Copilot
   session/chat identity.
3. Submit an idle queued message carrying a stable Relay delivery ID; prove that a
   new turn starts without human interaction and correlates to that ID.
4. During a deliberately long turn, submit another queued message; prove it does
   not steer or interrupt and starts as the following distinct turn.
5. Retry the same logical delivery; prove at most one turn admits it.
6. Disconnect and restart Pallium and the Agent Host at each ambiguous lifecycle
   point; reconcile before retrying and characterize what survives.
7. Delete or stale the target session; prove there is no title-based retargeting.
8. Verify the Copilot session can send and reply through an allowed common Pallium
   surface.
9. Repeat capability detection with relevant integration routes denied; prove the
   advertised downgrade or unavailable state.

Only proceed to a full adapter after this gate identifies a supported connection,
immutable identity, distinct-turn queue, admission correlation, and policy-safe
tool surface. If AHP fails but the SDK passes, document the managed-session
limitation. If only hooks pass, ship passive-only.

## Full-Lifecycle Validation

Public-surface E2E coverage must include idle wake, busy queue, concurrent human
input, duplicate submission, Pallium disconnect/restart, Agent Host or SDK restart,
uncertain admission recovery, stale/deleted session, renamed session, expiry,
permission denial, policy downgrade, Unicode payloads, replies, bounded queues,
and reciprocal-message loop protection.

Validate Windows paths, process behavior, connection/authentication handling, and
host persistence explicitly. A delivery with positive admission evidence must
never be retried. An uncertain delivery must be reconciled by stable ID before a
retry. Passive mode leaves the durable delivery pending for next-turn injection.

Operational telemetry must expose integration mode, advertised capabilities,
registered sessions, pending/submitted/admitted/expired counts, wake and busy-queue
latency, retries, reconnect recovery, and policy/capability failures. Do not label
admission or turn completion as usefulness.

## In Scope

- bidirectional Copilot participation through existing Relay operations
- AHP-first feasibility and adapter work, with SDK-managed or passive fallback
- immutable addressing, aliases, attribution, wake/fallback, replies, and lifecycle
- runtime-backed admission evidence and exactly-once logical delivery
- enterprise-policy-aware capability detection and Windows validation
- reuse of Relay's existing safety, expiry, queue, duplicate, and reply-hop bounds

## Out of Scope

- automating VS Code UI or undocumented/private editor APIs
- bypassing organizational policy or storing Copilot authentication material
- injecting into arbitrary legacy chats that expose no supported control surface
- spawning or assigning Copilot agents, steering busy turns, or supervising work
- autonomous conversations, automatic review loops, or semantic recipient inference
- treating Copilot as a generic model proxy or admission as proof of usefulness

## Done When

1. Copilot registers with immutable identity, integration mode, and verified
   per-session capabilities under effective policy.
2. A supported wake-capable mode admits idle and busy messages as distinct turns,
   correlates the exact delivery ID, and recovers without loss or duplication; or
   the item records why only passive mode is supportable.
3. Copilot sends and replies through a supported common Relay surface with normal
   attribution, isolation, and lower-authority treatment.
4. Full-lifecycle public-surface E2E passes on Windows, including downgrade and
   unavailable outcomes in managed environments.
5. The three established real-work Relay journeys include budgeted Copilot live
   evidence, and the verdict separates transport correctness from user value.
6. Public documentation states the supported topology, prerequisites, limitations,
   policy checks, wake/fallback behavior, and operational diagnostics without any
   private environment details.

## Research References

- [VS Code Agent Host architecture](https://code.visualstudio.com/docs/agents/concepts/agent-host)
- [Agent Host Protocol specification](https://microsoft.github.io/agent-host-protocol/)
- [Agent Host Protocol source](https://github.com/microsoft/agent-host-protocol)
- [Copilot SDK and CLI compatibility](https://docs.github.com/en/copilot/how-tos/copilot-sdk/troubleshooting/compatibility)
- [Copilot SDK session persistence](https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/session-persistence)
- [VS Code enterprise AI settings](https://code.visualstudio.com/docs/enterprise/ai-settings)
- [VS Code MCP configuration](https://code.visualstudio.com/docs/agent-customization/mcp-servers)
- [GitHub Copilot hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference)
- [VS Code agent hooks](https://code.visualstudio.com/docs/agent-customization/hooks)

These APIs and policies are evolving. Recheck primary documentation, installed
versions, entitlement, effective policy, and protocol schemas when this item starts.