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
- `visibility` — who can see this item: `"public"`, `"container"`,
  `"private"`, or `"global"`. Default: `"private"`. See [Common Shapes](#visibility)
- `thread_ref` — which conversation thread within the container
- `work_refs` — optional list of external work identifiers for cross-thread
  work continuity (e.g. ticket IDs, PR numbers)
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
- `work_refs` — optional list of external work identifiers. When provided,
  memories with matching work_refs are prioritized. Format: normalized strings
  (casefold, separator-canonical). "PROJ-123", "PROJ 123", "proj_123" all match.
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
      "memory_object_id": "mo-001",
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
- `decision_reason` — why injection was approved or declined:
  - `"carry_forward_available"` — relevant memory found and approved for injection
  - `"constraint_supplement"` — a user-stated constraint was found and injected
  - `"same_thread_context_sufficient"` — the agent already has this context in the current thread
  - `"no_relevant_memory"` — retrieval ran but nothing matched well enough
  - `"only_low_value_candidates"` — matches found but too low-value to inject
  - `"low_injection_confidence"` — candidates exist but confidence is below the injection threshold
  - `"no_candidates_above_floor"` — all candidates scored below the minimum retrieval floor
  - `"low_value_query"` — the query is a greeting, acknowledgement, or meta-conversation that won't benefit from memory
  - `"lane_ambiguity"` — the query didn't clearly map to a retrieval strategy; Pallium chose silence over a guess
  - `"no_lane_eligible"` — no structural retrieval lane (work resumption, evidence trace, residual recall) matched the query shape
- `injectable_blocks` — ready-to-use blocks for prompt injection, each with
  `block_type`, `title`, `text`, optional `memory_type`, optional
  `memory_object_id`, and `evidence` refs. `memory_object_id` can be used
  with `GET /memory/{id}/evidence` to retrieve the source conversation items
  that the memory was derived from
- `results` — ranked result list (see below)

Each result in `results[]`:

- `result_id` — unique result identifier
- `result_kind` — `"memory_hit"` (derived memory) or `"source_hit"` (stored
  evidence)
- `score` — retrieval score (integer, higher is better)
- `type` — memory type for `memory_hit` results: `"decision"`,
  `"investigation_outcome"`, `"thread_summary"`, `"task_checkpoint"`,
  `"atomic_fact"`, `"fact_summary"`, `"interest"`, `"constraint_memory"`,
  `"pattern_memory"`, or `"continuity_memory"`
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
- `query_actor_ref` — actor identity for query-time visibility filtering. When
  provided, enables retrieval of `global` memories belonging to this actor.
  Defaults to the item's `actor_ref` if not set explicitly.
- `work_refs` — optional list of external work identifiers (same behavior as
  in `POST /query`)

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

## GET /memory/{memory_object_id}/evidence

Use this endpoint to retrieve the source conversation items that a memory
object was derived from. This enables drill-down from a compact memory card
to the full original context.

Required query parameter:

- `container_ref` — the container to validate access against. The endpoint
  returns 404 if the memory object doesn't belong to this container.

Example:

```
GET /memory/63119911-e39d-4b51-b804-8cbecd0522b3/evidence?container_ref=slack:channel:C123
```

Response:

```json
{
  "memory_object_id": "63119911-e39d-4b51-b804-8cbecd0522b3",
  "items": [
    {
      "source_item_id": "si-001",
      "source_type": "chat_message",
      "source_id": "slack-message:C123:1700000001.000100",
      "content": "We decided to use event timestamps for ordering because of timezone drift.",
      "role": "user",
      "actor_ref": "slack:user:U01XYZ789",
      "occurred_at": "2026-04-09T10:30:00Z",
      "thread_ref": "slack:thread:C123:1700000001"
    }
  ]
}
```

Security:

- The memory object must belong to the requested `container_ref`, or have
  `visibility: "global"` with a matching `actor_ref` (404 otherwise)
- Each evidence item is filtered through visibility rules — private items from
  other containers are excluded
- Returns 404 (not 403) for both missing and unauthorized access to avoid
  confirming ID existence

## POST /memory/{memory_object_id}/flag

Flag a memory as incorrect, outdated, or low quality. After enough independent
flags from different sources, the memory is suppressed and excluded from
retrieval.

Request body:

```json
{
  "reason": "Outdated: PR was merged hours ago",
  "source_ref": "agent-session:f890d298",
  "immediate": false
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `reason` | string | yes | — | Why the memory is bad |
| `source_ref` | string | yes | — | Identifies who flagged it (used for dedup) |
| `immediate` | bool | no | `false` | When `true`, suppress immediately without waiting for threshold |

Response (200):

```json
{
  "memory_object_id": "a8efd630-2a64-497f-a80d-c238825981d3",
  "flag_count": 2,
  "unique_sources": 2,
  "suppressed": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `flag_count` | int | Total flags on this memory (all time) |
| `unique_sources` | int | Distinct `source_ref` values within the 30-day window |
| `suppressed` | bool | Whether the memory is now suppressed |

Suppression rules:

- **Threshold mode** (default): 2 independent sources (distinct `source_ref`
  values) within 30 days triggers suppression. Multiple flags from the same
  source count as one voice.
- **Immediate mode** (`immediate: true`): suppress without threshold. Use for
  confirmed-bad memories from human review.
- Flagging an already-suppressed or superseded memory is accepted and recorded
  for audit but doesn't change lifecycle.
- The endpoint is idempotent — repeated calls return current state.

Error responses:

| Status | Condition |
|--------|-----------|
| 404 | Unknown `memory_object_id` |
| 422 | Missing required fields |

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

## GET /health

Operational readiness check. Returns whether the service is ready to handle
requests.

```json
{
  "status": "ok",
  "vector_index_ready": true
}
```

- `status` — `"ok"` when ready, `"initializing"` during startup
- `vector_index_ready` — whether the vector index reconciliation has completed

Returns HTTP 200 when ready, 503 when still initializing. Use this for
container health probes and startup checks.

## Common Shapes

### visibility

A simple string field:

- `"public"` — visible to queries from any container
- `"container"` — visible only within the same `container_ref` (group context)
- `"private"` — visible only within the same `container_ref` (personal context)
- `"global"` — visible to queries from any container where the query's
  `actor_ref` matches the item's `actor_ref` (actor-scoped cross-container
  memory)

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

