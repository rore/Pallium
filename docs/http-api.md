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

- `source_type`
- `source_id`
- `content_type`
- `content`

Useful optional fields:

- `use_case`
- `occurred_at`
- `actor_ref`
- `role`
- `container_ref`
- `thread_ref`
- `session_ref`
- `source_ref`
- `artifact_kind`
- `metadata`
- `visibility_context`

Minimal example:

```json
{
  "source_type": "chat_message",
  "source_id": "msg-001",
  "content_type": "text/plain",
  "content": "Decision: use item event time for reservation ordering.",
  "use_case": "agent_conversation_memory",
  "artifact_kind": "assistant_output",
  "role": "assistant",
  "container_ref": "room:ops",
  "thread_ref": "thread-42",
  "visibility_context": {
    "kind": "limited",
    "id": "room:ops"
  }
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
- for the current conversation package, always send `visibility_context`
- `artifact_kind` is currently validated against:
  - `message`
  - `assistant_output`
  - `tool_use_summary`
  - `todo_snapshot`
  - `notification`

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

- `text`

Optional filters and context:

- `limit`
- `source_type`
- `role`
- `artifact_kind`
- `container_ref`
- `thread_ref`
- `session_ref`
- `visibility_context`
- `runtime_context`

Minimal example:

```json
{
  "text": "Why did we choose item event time?",
  "thread_ref": "thread-42",
  "container_ref": "room:ops",
  "visibility_context": {
    "kind": "limited",
    "id": "room:ops"
  },
  "runtime_context": {
    "turn_kind": "same_thread_continuation",
    "session_has_sufficient_local_context": false
  }
}
```

Current request rules:

- `limit` defaults to `5`
- `limit` must be between `1` and `50`
- for the current scoped package, missing `visibility_context` causes
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
`session_ref`, `source_ref`, and `visibility_context`. Each `memory_hit` also
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

### visibility_context

Current shape:

```json
{
  "kind": "public" | "limited" | "user",
  "id": null | "..."
}
```

Rules:

- `public` requires `id = null`
- `limited` requires a non-empty `id`
- `user` requires a non-empty `id`

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

- `use_case` is how the caller selects a semantic package during ingest
- `agent_conversation_memory` is the main package described by the current docs
- keep source content compact and explicit; the current semantic layer is
  text-oriented
- use `GET /items/{source_item_id}/processing` and `POST /query/debug` before
  changing prompts or retrieval heuristics blindly

## Read Next

- integration flow: [agent-integration.md](agent-integration.md)
- privacy rules: [privacy-and-visibility.md](privacy-and-visibility.md)

