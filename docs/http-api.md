# HTTP API

This page documents the current HTTP surface for Pallium.

The examples below assume the current `agent_conversation_memory` package,
which is the main product focus today.

## Base Model

The API has three main operations:

- send selected evidence with `POST /items`
- ask for continuity context with `POST /query` or `POST /query/debug`
- do both in one call with `POST /item-and-query` or
  `POST /item-and-query/debug`

There are also two operational endpoints:

- inspect processing for one item with `GET /items/{source_item_id}/processing`
- inspect queue and background-worker state with `GET /debug/queue/health`

## POST /items

Use this endpoint to store source items. Always accepts an array, always
returns an array. Maximum 50 items per request.

```json
[
  {
    "source_type": "chat_message",
    "source_id": "msg-001",
    "content_type": "text/plain",
    "content": "We decided to use event timestamps for ordering."
  }
]
```

For multiple items in one call (e.g. assistant reply + tool summary + todo
snapshot after an agent turn):

```json
[
  { "source_type": "...", "source_id": "reply-1", "artifact_kind": "assistant_output", ... },
  { "source_type": "...", "source_id": "tools-1", "artifact_kind": "tool_use_summary", ... },
  { "source_type": "...", "source_id": "todo-1", "artifact_kind": "todo_snapshot", ... }
]
```

Required fields (per item):

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
- `visibility` — who can see this item: `"public"`, `"container"`, or
  `"private"`. Default: `"private"`. See [Common Shapes](#visibility)
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
[{
  "source_type": "chat_message",
  "source_id": "msg-001",
  "content_type": "text/plain",
  "content": "We decided to use event timestamps for ordering."
}]
```

Recommended example for `agent_conversation_memory`:

```json
[{
  "source_type": "chat_message",
  "source_id": "msg-001",
  "content_type": "text/plain",
  "content": "We decided to use event timestamps for ordering.",
  "artifact_kind": "assistant_output",
  "role": "assistant",
  "container_ref": "channel:C04ABC123",
  "visibility": "container",
  "thread_ref": "thread:1700000001"
}]
```

Response — always an array:

- `source_item_id` — internal ID assigned by Pallium
- `memory_object_ids` — IDs of any memory objects promoted immediately
- `relation_ids` — IDs of evidence relations created
- `index_entry_ids` — IDs of retrieval index entries created
- `processing_status` — `"pending"`, `"processing"`, `"completed"`,
  `"skipped"`, or `"failed"`
- `processing_attempts` — number of processing attempts so far
- `processing_error` — error message if processing failed (null otherwise)

Note: most items return with `processing_status: "pending"` because semantic
extraction runs asynchronously in the background. Use
`GET /items/{source_item_id}/processing` to inspect the result.

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
- produced memory, relation, and index ids
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
- `visibility` — visibility boundary for the query
- `thread_ref` — current thread within the container

Additional filters:

- `limit` — max results (default: 5, range: 1–50)
- `source_type` — filter by upstream system
- `role` — filter by `"user"` or `"assistant"`
- `artifact_kind` — filter by evidence shape
- `actor_ref` — filter by actor identity. When provided, only returns memories
  whose `actor_ref` matches or is null (shared). When omitted, no actor
  filtering is applied. See
  [privacy-and-visibility.md](privacy-and-visibility.md#actor-scoping) for
  details.
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
  "visibility": "container",
  "thread_ref": "thread:1700000001"
}
```

Current request rules:

- `limit` defaults to `5`
- `limit` must be between `1` and `50`
- for the current scoped package, missing `container_ref` causes
  fail-closed behavior rather than a broad fallback

Response:

```json
{
  "should_inject": true,
  "decision_reason": "carry_forward_available",
  "injectable_blocks": [
    {
      "result_id": "mem-abc123",
      "block_type": "memory_hit",
      "title": "decision",
      "text": "Use event timestamps for ordering — avoids timezone drift.",
      "memory_type": "decision",
      "evidence": [
        {
          "source_item_id": "si-001",
          "source_type": "chat_message",
          "source_id": "msg-001",
          "role": "assistant"
        }
      ]
    }
  ],
  "results": [
    {
      "result_id": "mem-abc123",
      "result_kind": "memory_hit",
      "score": 850,
      "type": "decision",
      "memory_object_id": "mo-001",
      "excerpt": null,
      "container_ref": "channel:C04ABC123",
      "thread_ref": "thread:1700000001",
      "visibility": "container",
      "retrieval_source": "lexical",
      "evidence": [
        {
          "source_item_id": "si-001",
          "source_type": "chat_message",
          "source_id": "msg-001",
          "role": "assistant",
          "container_ref": "channel:C04ABC123",
          "visibility": "container"
        }
      ]
    }
  ]
}
```

Response fields:

- `should_inject` — whether Pallium recommends injecting memory into the
  agent's prompt
- `decision_reason` — why: `"carry_forward_available"`,
  `"same_thread_context_sufficient"`, `"no_relevant_memory"`,
  `"only_low_value_candidates"`, `"low_injection_confidence"`,
  `"no_candidates_above_floor"`, `"constraint_supplement"`,
  `"low_value_query"`, `"lane_ambiguity"`, or `"no_lane_eligible"`
- `injectable_blocks` — ready-to-use blocks for prompt injection, each with
  `block_type`, `title`, `text`, optional `memory_type`, and `evidence` refs
- `results` — ranked result list (see below)

Each result in `results[]`:

- `result_id` — unique result identifier
- `result_kind` — `"memory_hit"` (derived memory) or `"source_hit"` (stored
  evidence)
- `score` — retrieval score (integer, higher is better)
- `type` — memory type for `memory_hit` results: `"decision"`,
  `"investigation_outcome"`, `"thread_summary"`, `"task_checkpoint"`,
  `"interest"`, `"constraint_memory"`, `"pattern_memory"`, `"continuity_memory"`, or `"discussion_summary"`
- `memory_object_id` — ID of the memory object (for `memory_hit`)
- `source_item_id` — ID of the source item (for `source_hit`)
- `excerpt` — text excerpt (for `source_hit`)
- `container_ref`, `thread_ref`, `visibility` — context refs
- `retrieval_source` — `"lexical"`, `"vector"`, or `"fused"` (when hybrid
  retrieval is enabled)
- `evidence` — supporting evidence refs (for `memory_hit` results)

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

## POST /item-and-query

Combines item ingest and memory query in a single call. This is the
recommended endpoint for the common pattern: store the user message, then
immediately query for relevant prior memory.

The request body is the same as `POST /items`, plus optional query fields:

- `query_text` — override query text (defaults to `content`)
- `query_limit` — max results (default: 5, range: 1–50)

Example:

```json
{
  "source_type": "chat_message",
  "source_id": "slack:C04ABC123:1700000001.000100",
  "content_type": "text/plain",
  "content": "Why did we choose event timestamps for ordering?",
  "role": "user",
  "artifact_kind": "message",
  "container_ref": "slack:channel:C04ABC123",
  "thread_ref": "slack:thread:C04ABC123:1700000001.000100",
  "visibility": "container",
  "actor_ref": "slack:user:U01XYZ789"
}
```

Response — same as `POST /query` plus `source_item_id`:

```json
{
  "source_item_id": "si-abc123",
  "should_inject": true,
  "decision_reason": "carry_forward_available",
  "injectable_blocks": [ ... ],
  "results": [ ... ]
}
```

The ingest runs first (async processing — the just-ingested message won't
appear in query results). The query then retrieves previously derived memory
relevant to the `content` (or `query_text` if provided).

`POST /item-and-query/debug` returns the same plus `trace` (same as
`POST /query/debug`).

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

### visibility

A simple string field:

- `"public"` — visible to queries from any container
- `"container"` — visible only within the same `container_ref` (group context)
- `"private"` — visible only within the same `container_ref` (personal context)

Default: `"private"`.

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

