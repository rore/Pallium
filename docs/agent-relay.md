# Relay

Relay sends a bounded plain-text message from one existing agent session to
another. Pallium stores the message before attempting delivery, so a busy or
unavailable recipient can receive it later.

Pallium currently ships Relay integrations for Claude Code, Codex, and OpenCode.
Sessions must connect to the same local Pallium service. Routing uses explicit
session identity; it does not use search, embeddings, ranking, or an LLM.

## Send a message

Tell an agent what to send and which session should receive it:

> Use Pallium Relay to send Codex: "The legacy endpoint is still used by mobile.
> Do not remove it."

If the target is ambiguous, ask the agent to list Relay recipients first.

Use Relay when another session should change its work because of what you
learned, when you need a decision from that session, when it is now unblocked,
or when you need a concrete review or action.

Avoid routine status, unrelated context, speculative “maybe useful” messages,
open-ended chat, and broadcasts whose only purpose is to keep every session
informed. A delivered message can start a paid model turn on supported targets.

## Limits

Messages contain at most 1,500 Unicode code points and expire after 24 hours by
default. HTTP and hook turns claim at most three messages unless
`max_messages=0` is explicit; MCP receive uses that drain-all value.

Codex and Claude hooks claim within 2,360 characters, reserving 40 characters
for a compact backlog notice inside their 2,400-character output budget.
`has_more` and `remaining_count` report omitted eligible work, and integrations
acknowledge only blocks actually added to model context.

## Select a recipient

`pallium_relay_recipients` lists recent sessions and their optional aliases.
Selectors have three forms:

- `codex` — every currently recent Codex session in scope
- `codex:<session_ref>` — one immutable session
- `codex:@review` — the session currently holding the `review` alias

The same forms apply to other supported runtimes. Runtime-wide sends require
explicit user intent and resolve their recipients at send time. Sessions opened
later do not receive the message.

`pallium_relay_name` assigns or transfers an alias. Transferring an alias
affects future sends; messages already queued remain addressed to the original
session.

## Replies

A received message includes a `delivery_id`. `pallium_relay_reply` uses that ID
to address a reply to the original sender.

One delivery permits one idempotent reply. Repeating the same reply is safe;
changing its text conflicts. Use a new `pallium_relay_send` message for a longer
follow-up rather than treating Relay as a continuous conversation.

Delivery means that the message entered the recipient session's context. It
does not prove that the model acted on it.

## Delivery and wake behavior

Pallium persists first, then attempts the safest delivery supported by the
recipient runtime. If wake is unsupported, disabled, unsafe, or unavailable,
the same message remains pending for the recipient's next natural turn.

| Runtime | Current behavior |
|---|---|
| Claude Code on Windows | Existing-session wake is qualified. |
| Codex on Windows | Loaded and unloaded exact-session wake is proven; more lifecycle, telemetry, and sustained-use checks remain. |
| OpenCode | Durable next-turn delivery; active wake is deferred. |
| Other operating systems | Use next-turn delivery until that runtime/OS combination is qualified. |

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

- message and reply text: at most 1,500 Unicode code points
- default expiry: 24 hours; allowed range is 60 seconds to 7 days
- per-turn delivery: at most three complete messages within a 2,400-character
  Relay budget
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
claims with `receive` must acknowledge with `ack`, or use `reply` with the
receipt to acknowledge and reply atomically.

Do not mix automatic hook delivery and MCP receive in the same session; they
compete for the same pending delivery.
