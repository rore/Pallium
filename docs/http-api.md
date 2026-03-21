# HTTP API

This page documents the current HTTP surface for Pallium.

The examples below assume the current `agent_conversation_memory` package,
which is the main product focus today.

## Base Model

The API has two main operations:

- send selected evidence with `POST /items`
- ask for continuity context with `POST /query` or `POST /query/debug`

There are also two operational endpoints:

- inspect processing for one item with `GET /items/{source_item_id}/processing`
- inspect queue and background-worker state with `GET /debug/queue/health`

## POST /items

Use this endpoint to store one source item.

Required fields:

- `source_type` — name of the upstream system (e.g. `"chat_message"`,
  `"ticket_update"`)
- `source_id` — stable unique ID from the upstream system, used for
  idempotency
- `content_type` — format of the content (use `"text/plain"` unless you have
  a specific reason not to)
- `content` — the text to store and reason over

Recommended fields for `agent_conversation_memory`:

- `container_ref` — which container this item belongs to (e.g. a channel ID
  or room ID). Used for scoping, thread grouping, and visibility enforcement
- `container_visibility` — who can see this item: `"public"`, `"limited"`, or
  `"private"`. Default: `"private"`. See [Common Shapes](#container_visibility)
- `thread_ref` — which conversation thread within the container
- `role` — who produced this: `"user"` or `"assistant"`
- `artifact_kind` — optional hint about the evidence shape (see below)

Additional context fields:

- `actor_ref` — who said it (the human user, e.g. a user ID)
- `agent_ref` — which agent instance produced it (e.g. an agent deployment ID)
- `source_ref` — a link or pointer back to the original source
- `occurred_at` — when the upstream event happened (ISO 8601)
- `metadata` — arbitrary key-value pairs for your own use

Minimal example:

```json
{
  "source_type": "chat_message",
  "source_id": "msg-001",
  "content_type": "text/plain",
  "content": "We decided to use event timestamps for ordering."
}
```

Recommended example for `agent_conversation_memory`:

```json
{
  "source_type": "chat_message",
  "source_id": "msg-001",
  "content_type": "text/plain",
  "content": "We decided to use event timestamps for ordering.",
  "artifact_kind": "assistant_output",
  "role": "assistant",
  "container_ref": "channel:C04ABC123",
  "container_visibility": "limited",
  "thread_ref": "thread:1700000001"
}
```

Response fields:

- `source_item_id`
- `annotation_ids`
- `memory_object_ids`
- `relation_ids`
- `index_entry_ids`
- `processing_status`
- `processing_attempts`
- optional `processing_error`

Notes:

- keep `source_id` stable if you want upstream idempotency
- for the current conversation package, always send `container_ref`
- `artifact_kind` helps Pallium route faster but is not required. Accepted
  values:
  - `message` — a user question or statement
  - `assistant_output` — a final assistant answer or decision
  - `tool_use_summary` — a compact summary of a tool run
  - `todo_snapshot` — an explicit next-step or progress note
  - `notification` — an external notification or alert

## GET /items/{source_item_id}/processing

Use this endpoint when you want to inspect what happened to one ingested item.

The response includes:

- processing state and attempts
- any processing error and failure category
- produced annotation, memory, relation, and index ids
- produced memory types
- whether thread rebuild was requested and completed
- compact provenance for produced memory

This is useful when ingest succeeds but the follow-up query does not return what
you expected.

## POST /query

Use this endpoint when the runtime needs continuity context before answering.

Required fields:

- `text` — the current user question or prompt

Recommended fields:

- `container_ref` — scope the query to this container
- `container_visibility` — visibility boundary for the query
- `thread_ref` — current thread within the container

Additional filters:

- `limit` — max results (default: 5, range: 1–50)
- `source_type` — filter by upstream system
- `role` — filter by `"user"` or `"assistant"`
- `artifact_kind` — filter by evidence shape
- `runtime_context` — optional runtime hints (see
  [Common Shapes](#runtime_context))

Minimal example:

```json
{
  "text": "Why did we choose event timestamps?"
}
```

Recommended example:

```json
{
  "text": "Why did we choose event timestamps?",
  "container_ref": "channel:C04ABC123",
  "container_visibility": "limited",
  "thread_ref": "thread:1700000001"
}
```

Current request rules:

- `limit` defaults to `5`
- `limit` must be between `1` and `50`
- for the current scoped package, missing `container_ref` causes
  fail-closed behavior rather than a broad fallback

Response fields:

- `results`
- `should_inject`
- `decision_reason`
- `injectable_blocks`

Result kinds:

- `memory_hit`
  - compact derived memory such as a prior decision, investigation outcome,
    thread summary, or task checkpoint
- `source_hit`
  - compact evidence card from a stored source item

Each result can include refs such as `container_ref`, `thread_ref`,
`source_ref`, and `container_visibility`. Each `memory_hit` also
includes supporting evidence refs.

## POST /query/debug

This endpoint has the same request shape as `POST /query` and returns the same
normal result fields.

It also returns `trace`, which currently includes:

- `query_text`
- `query_tokens`
- `limit`
- optional `filters`
- retrieval `stages`
- package routing information under `routing`
- visibility information under `visibility`
- a compact `result_summary`

Use this endpoint when you need to understand:

- why a result is missing
- why memory beat source evidence or vice versa
- which candidates were excluded by visibility rules
- what lexical matches were considered

## GET /debug/queue/health

This is the operational endpoint for the background pipeline.

The response includes:

- status counts for queued items
- oldest pending age
- pending items without a use case
- unclaimable pending reasons
- leased source items
- leased thread scopes
- recent failures
- retention-run state

This endpoint is mainly for local debugging, worker troubleshooting, and test
or benchmark setup checks.

## Common Shapes

### container_visibility

A simple string field:

- `"public"` — visible to queries from any container
- `"limited"` — visible only within the same `container_ref` (group context)
- `"private"` — visible only within the same `container_ref` (personal context)

Default: `"private"`.

### runtime_context

Current shape:

```json
{
  "turn_kind": "new_thread" | "same_thread" | "same_thread_continuation" | "resumed_session" | "new_session",
  "session_has_sufficient_local_context": true | false | null
}
```

This is optional query input. It is for runtime facts, not for telling Pallium
which memory type should win.

## Practical Notes

- the semantic package is selected by the server-side `default_use_case`
  configuration; callers do not normally need to send `use_case`
- `agent_conversation_memory` is the main package described by the current docs
- keep source content compact and explicit; the current semantic layer is
  text-oriented
- use `GET /items/{source_item_id}/processing` and `POST /query/debug` before
  changing prompts or retrieval heuristics blindly

## Read Next

- integration flow: [agent-integration.md](agent-integration.md)
- privacy rules: [privacy-and-visibility.md](privacy-and-visibility.md)

