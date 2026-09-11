# Relay

Relay sends a bounded plain-text message from one existing agent session to
another. Pallium stores the message before attempting delivery, so a busy or
unavailable recipient can receive it later.

Pallium currently ships Relay integrations for Claude Code, Codex, and OpenCode.
Sessions must connect to the same local Pallium service. Cross-container routing is service-global; Session History and derived-memory scoping are unchanged. Routing uses explicit session identity; it does not use search,
embeddings, ranking, or an LLM.

## Hook identity for memory and history

PALLIUM_HOOK_ACTOR_REF remains attribution metadata for hook-provided memory and Session History records; raw history search does not filter by it unless the caller explicitly asks. Relay ignores this value: Relay sessions, names, messages, and wake state are global to the local Pallium service. The variable is not authentication and is separate from the paired MCP trusted-scope variables PALLIUM_ACTOR_REF and PALLIUM_CONTAINER_REF.

## Send a message

Tell an agent what to send and which session should receive it:

> Use Pallium Relay to send Codex: "The legacy endpoint is still used by mobile.
> Do not remove it."

If the target is ambiguous, ask the agent to list Relay recipients first.

Use Relay when another session should change its work because of what you
learned, when you need a decision from that session, when it is now unblocked,
or when you need a concrete review or action.

Avoid routine status, unrelated context, speculative “maybe useful” messages,
and open-ended chat. Regular sends reject a bare runtime selector; there is no broadcast send API yet. A delivered message can start a paid model turn on supported targets.

## Limits

Messages contain at most 16,000 Unicode code points. Omitted expiry is durable
until delivery; callers can opt into an explicit expiry from 60 seconds through
7 days. HTTP and hook turns claim three messages by default; a positive
`max_messages` sets an explicit cap, while `0` means unlimited. MCP receive
claims one delivery per call and keeps its compact JSON response within 2,000
characters.

Codex, Claude, and OpenCode hooks claim within 2,360 characters, reserving 40
characters for a compact backlog notice inside their 2,400-character output budget.
A long message is injected as an attributed prefix with the exact omitted count
and a `pallium_relay_status` continuation call. Status pages use Unicode
code-point offsets and reconstruct the complete stored redacted body; continue with `next_offset` until it is null. The unpaged HTTP status response remains a
full-body compatibility view. `has_more` and `remaining_count` report all
unclaimed work, and integrations acknowledge only blocks actually added to model
context.
Hook delivery appends a separately bounded exact-scope block so the same turn
can reply without a receipt. If trusted scope cannot be rendered safely, the hook
does not claim or acknowledge Relay work; the persisted delivery remains recoverable.

The HTTP turn request's `max_response_chars` is a pre-claim selection guard:
prospective delivery JSON must fit it before any claim is committed. It is not a
transport-size promise for an empty turn envelope. MCP receive removes session
metadata after that conservative check and separately guarantees its final tool
response budget.

## Select a recipient

`pallium_relay_recipients` returns a bounded envelope of recent sessions. Each item includes a canonical `exact_selector` and, when named, `alias_selector` (the internal wire-field name for its `@name`); when `has_more` is true, call it again with `next_offset`. The HTTP session-list response remains container-local and exposes each endpoint ID.
Legacy selectors have three forms:

- `codex` — legacy runtime-wide compatibility selector; regular sends reject it
- `codex:<session_ref>` — legacy runtime/session compatibility selector; it may be ambiguous
- `codex:@review` — compatibility name selector; use `@review` instead

The canonical exact selector is `relay-session-<32 lowercase hex>`. The service-global name form is `@name`. A `runtime:@name` selector is compatibility only; if it does not match, the error says to use `@name`. Regular sends do not broadcast; a separate broadcast API may be added later.

Legacy runtime-qualified forms apply to other supported runtimes.

`pallium_relay_name(name="…")` assigns or transfers a name. First try without takeover; if occupied, fail and ask the user. Retry with `replace_existing=true` only after explicit approval, or immediately when the original request explicitly says to take over. Transferring a name affects future sends; messages already queued remain addressed to the original session.

## Associate sessions with exact work

A session can retain up to three explicit work references alongside the two
structural references discovered from its branch and Agent Workflow record. Use
`pallium_relay_attach_work_ref(scope_ref, local_ref)` and
`pallium_relay_detach_work_ref(scope_ref, local_ref)` for the current session.
`pallium_relay_work_refs()` reads the current snapshot, and
`pallium_relay_participants(scope_ref, local_ref)` finds every active participant
for one exact reference; pass `include_closed=true` only when closed sessions matter.

Normal inputs are a readable `scope_ref` and `local_ref`. Pallium returns their
fixed-length `work:v1:<sha256>` exact key for advanced lookup and exact Session
History search. Repository-scoped producers use a credential-free canonical Git
identity, so the same repository is stable across worktrees and unrelated
repositories do not collide. Bare tracker keys are ambiguous: supply their tracker
project scope instead of letting an agent guess.

Association is not ownership, activity, completion, wake, routing permission, or
History access. Participant discovery never sends, claims, or wakes. Alias transfer
does not transfer associations; close/reopen retains them. Structural refresh
replaces only structural origins, while explicit references survive branch changes.
Future hook turns capture the then-current bounded snapshot into immutable History
metadata; detaching later never relabels older turns. If caller or structural refs
already fill History's five-reference cap, hook output reports which registry refs
were omitted rather than claiming they are searchable.

## Replies

A received message includes a `delivery_id`. `pallium_relay_reply` uses that ID
to address a reply to the original sender.

One delivery permits one idempotent reply. Repeating the same reply is safe;
changing its text conflicts. Use a new `pallium_relay_send` message for a separate
follow-up rather than treating Relay as a continuous conversation.

Delivery means that the message entered the recipient session's context. It
does not prove that the model acted on it.

## Delivery and wake behavior

Pallium persists first, then attempts the safest delivery supported by the
recipient runtime. If wake is unsupported, disabled, unsafe, or unavailable,
the same message remains pending for the recipient's next natural turn.

| Runtime | Current behavior |
|---|---|
| Claude Code on Windows and Linux | Exact-session wake is qualified. Linux qualification used the installed UDS path on Ubuntu 24.04. |
| Codex on Windows and Linux | Exact-session wake is qualified for tasks loaded by their Codex runtime. If a task is unloaded, the Pallium delivery stays pending for its next supported hook turn; native unloaded-queue persistence is not claimed. Windows also proves overtaken-wake suppression, and Linux requires the installed hook to be trusted. |
| OpenCode | Durable next-turn delivery; active wake is deferred. |
| Claude Code and Codex on macOS | Durable next-turn delivery; active wake is not yet qualified. |

This table follows the current
[wake roadmap](../roadmap/features/add-wake-first-relay-delivery.md). Recheck it
before making release claims.

Pallium can start a new turn in an existing supported session. It does not
create agents, assign work, restart sessions, or supervise a workflow.

There is no delayed or scheduled Relay product.

## Busy, unavailable, and dormant sessions

A busy or temporarily unavailable recipient keeps the delivery pending. Claims
that are interrupted become eligible again after their lease expires.

Recent sessions appear in recipient discovery by default. A session becomes
dormant after 24 hours without a turn but remains exactly addressable. A close
event marks it closed and releases its name; a later turn reactivates the same
session ID.

Sending to a known closed endpoint or unambiguous exact runtime/session returns
`409 recipient session is closed` before a message or delivery is stored. The
same error applies when replying after the original sender closes. A released
name and an unknown selector remain not found; an unreachable destination keeps
its existing `409 recipient session is unreachable` result.

## Project scope transitions

Claude Code and Codex keep the same Relay endpoint when a session deliberately moves to another Git project. The hooks persist and retry an exact source/destination intent, while the server accepts the move only for the supplied endpoint and scope generation. A confirmed move preserves the alias, manual work references, and pending or claimed deliveries. Historical delivery records keep their original container snapshots; follow-up wake routing resolves the endpoint's current container.

A stale, missing, closed, unreachable, or occupied transition fails without moving either endpoint. Pallium never searches globally for a source session or takes over a destination. OpenCode remains pinned to one project for the life of its current session.

## Limits and scope

- message and reply text: at most 16,000 Unicode code points
- omitted expiry: durable until delivery; explicit expiry range: 60 seconds to 7 days
- per-turn delivery: three messages by default; positive `max_messages` sets a
  cap and `0` means unlimited; the first oversized body may be a bounded preview
- MCP receive: one delivery and at most 2,000 serialized characters per call;
  `max_chars=0` selects that default, larger values clamp to it, and values from
  1 through 255 are rejected before claim
- storage: local persistent SQLite state
- security boundary: local single-user coordination

The generic secret redactor runs before persistence. `actor_ref` remains memory/history attribution metadata; Relay has no actor scope.

## Tools

Normal use:

- `pallium_relay_recipients`
- `pallium_relay_name`
- `pallium_relay_send`
- `pallium_relay_reply`
- `pallium_relay_status`
- `pallium_relay_work_refs`
- `pallium_relay_attach_work_ref`
- `pallium_relay_detach_work_ref`
- `pallium_relay_participants`

Normal hook delivery is automatic. `pallium_relay_receive` and
`pallium_relay_ack` are recovery or non-hook integration tools. A runtime that
claims with `receive` follows any `next_offset` through `status`, then must
acknowledge with `ack`, or use `reply` with the receipt to acknowledge and reply
atomically.

Do not mix automatic hook delivery and MCP receive in the same session; they
compete for the same pending delivery.
