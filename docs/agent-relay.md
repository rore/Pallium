# Relay

Relay sends a bounded plain-text message from one existing agent session to
another. Pallium stores the message before attempting delivery, so a busy or
unavailable recipient can receive it later.

Pallium currently ships Relay integrations for Claude Code, Codex, and OpenCode.
Sessions must connect to the same local Pallium service. Cross-container routing
applies only within the same actor; Session History and derived-memory scoping
are unchanged. Routing uses explicit session identity; it does not use search,
embeddings, ranking, or an LLM.

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

`pallium_relay_recipients` returns a bounded envelope of recent sessions. Each item includes a canonical `exact_selector` and, when named, `alias_selector`; when `has_more` is true, call it again with `next_offset`. The HTTP session-list response remains container-local and exposes each endpoint ID.
Legacy selectors have three forms:

- `codex` — legacy runtime-wide compatibility selector; regular sends reject it
- `codex:<session_ref>` — legacy runtime/session compatibility selector; it may be ambiguous
- `codex:@review` — compatibility alias selector; use `@review` instead

The canonical exact selector is `relay-session-<32 lowercase hex>`. The actor-global alias form is `@name`. A `runtime:@name` selector is compatibility only; if it does not match, the error says to use `@name`. Regular sends do not broadcast; a separate broadcast API may be added later.

Legacy runtime-qualified forms apply to other supported runtimes.

`pallium_relay_name` assigns or transfers an alias. First try without takeover; if occupied, fail and ask the user. Retry with `replace_existing=true` only after explicit approval, or immediately when the original request explicitly says to take over. Transferring an alias affects future sends; messages already queued remain addressed to the original session.

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
| Codex on Windows and Linux | Exact-session wake is qualified. Windows also proves loaded and unloaded tasks plus overtaken-wake suppression; Linux requires the installed hook to be trusted. |
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
event marks it closed and releases its alias; a later turn reactivates the same
session ID.

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

The generic secret redactor runs before persistence. `actor_ref` is claimed
scope, not authenticated cross-user authorization.

## Tools

Normal use:

- `pallium_relay_recipients`
- `pallium_relay_name`
- `pallium_relay_send`
- `pallium_relay_reply`
- `pallium_relay_status`

Normal hook delivery is automatic. `pallium_relay_receive` and
`pallium_relay_ack` are recovery or non-hook integration tools. A runtime that
claims with `receive` follows any `next_offset` through `status`, then must
acknowledge with `ack`, or use `reply` with the receipt to acknowledge and reply
atomically.

Do not mix automatic hook delivery and MCP receive in the same session; they
compete for the same pending delivery.
