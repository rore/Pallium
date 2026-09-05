# HTTP API

This page documents Pallium's local HTTP surface. Most coding-tool users use the
MCP tools and installed integrations instead of calling these routes directly.

## Capability map

### Session History

- `POST /items` records governed turns and other source evidence.
- `POST /query` with `source_only: true` searches raw historical sources.
- `GET /source/{source_item_id}/context` returns a bounded surrounding window.
- `POST /historical-access/{attempt_id}/delivery` records which returned history
  was exposed to the requesting session.
- `POST /source/forget` applies governed raw-source forgetting.

The MCP wrappers `pallium_search_history` (broad topic search),
`pallium_search_history_by_work_ref` (narrow exact-reference search), and
`pallium_expand_source` provide the normal agent-facing safeguards and compact result
shape.

### Relay

| Route | Purpose |
|---|---|
| `POST /relay/turn` | Register or update a session and claim eligible deliveries. |
| `POST /relay/sessions/close` | Close a session and release its alias. |
| `GET /relay/sessions` | List addressable sessions. |
| `POST /relay/sessions/name` | Assign or transfer an alias. |
| `POST /relay/messages` | Persist and send a new message. |
| `POST /relay/replies` | Reply to one received delivery. |
| `GET /relay/messages/{message_id}` | Read delivery status. |
| `POST /relay/deliveries/ack` | Acknowledge automatic hook delivery. |
| `POST /relay/deliveries/mcp-ack` | Acknowledge MCP recovery delivery. |

### Optional derived memory

- `POST /query` and `POST /query/debug` retrieve memory.
- `POST /item-and-query` and its debug form combine source ingest and memory
  query.
- `/memory/...` routes expand, flag, rate, correct, supersede, forget, or record
  outcomes for derived memory.

The examples below mainly cover this derived-memory API because its request and
response shapes require the most integration detail.

### Operations

- `GET /health` reports process reachability.
- `GET /status` reports configured subsystem status.
- `GET /debug/queue/health` reports ingestion queue health.
- dashboard and retry routes support local operation and debugging.

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
  - `note` — explicit "remember this" from the user. Uses a dedicated
    extraction prompt that preserves content verbatim and extracts only a
    title for retrieval. Use this when the user explicitly asks to save
    something.

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

> **Required for visibility-enforcing packages.** With a package that enforces
> visibility (the conversation packages), a query missing **either**
> `container_ref` **or** `visibility` fails closed: it returns no results with
> `decision_reason: "visibility_context_required"`. Pass both. Packages that
> don't require a visibility context (e.g. the demo package) still accept
> `text` alone.

Additional filters:

- `limit` — max results (default: 5, range: 1–50)
- `source_type` — filter by upstream system
- `role` — filter by `"user"` or `"assistant"`
- `artifact_kind` — filter by evidence shape
- `work_refs` — optional list of external work identifiers. When provided,
  memories with matching work_refs are prioritized. Format: normalized strings
  (casefold, separator-canonical). "PROJ-123", "PROJ 123", "proj_123" all match.
- `request_source_item_id` — optional measurement link for a
  `source_only=true` historical lookup. It must reference a live user source
  item with the same container, thread, actor, and visibility as the request.
  Invalid links return HTTP 422 on both `/query` and `/query/debug`; omission
  remains supported. This field is telemetry, not authorization.
- `actor_ref` — filter by actor identity. When provided, only returns memories
  whose `actor_ref` matches or is null (shared). When omitted, no actor
  filtering is applied. See
  [privacy-and-visibility.md](privacy-and-visibility.md#actor-scoping) for
  details.
Minimal example (accepted only by packages that don't enforce visibility):

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
- for a visibility-enforcing package, a request missing **either**
  `container_ref` or `visibility` fails closed (empty results,
  `decision_reason: "visibility_context_required"`) rather than a broad fallback

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
  - `"visibility_context_required"` — retrieval did **not** run: the request lacked a visibility context. Pass both `container_ref` and `visibility` (see `trace.visibility.fail_closed_reason`)
  - `"only_low_value_candidates"` — matches found but too low-value to inject
  - `"low_injection_confidence"` — candidates exist but confidence is below the injection threshold
  - `"no_candidates_above_floor"` — all candidates scored below the minimum retrieval floor
  - `"low_value_query"` — the query is a greeting, acknowledgement, or meta-conversation that won't benefit from memory
  - `"lane_ambiguity"` — the query didn't clearly map to a retrieval strategy; Pallium chose silence over a guess
  - `"no_lane_eligible"` — no structural retrieval lane (work resumption, evidence trace, residual recall) matched the query shape
- `injectable_blocks` — ready-to-use blocks for prompt injection, each with
  `block_type`, `title`, `text`, optional `memory_type`, optional
  `memory_object_id`, and `evidence` refs. `memory_object_id` can be used
  with `GET /memory/{id}/expand` to retrieve the structured payload and source conversation items
  that the memory was derived from. Injection blocks also carry an `expand_available` flag
  indicating whether the expand endpoint will return useful content
- `results` — ranked result list (see below)

Each result in `results[]`:

- `result_id` — unique result identifier
- `result_kind` — `"memory_hit"` (derived memory) or `"source_hit"` (stored
  evidence)
- `score` — retrieval score (integer, higher is better)
- `type` — memory type for `memory_hit` results: `"decision"`,
  `"investigation_outcome"`, `"thread_summary"`, `"task_checkpoint"`,
  `"atomic_fact"`, `"fact_summary"`, `"constraint_memory"`,
  `"pattern_memory"`, `"continuity_memory"`, or `"note"`
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

## Explicit Memory Writes

Five endpoints let an agent shape memory directly, alongside the automatic
extraction path. Every write records an `origin ∈ {agent_explicit,
agent_inferred, user_requested}`. Use these when a fact deserves
preservation and automatic extraction may miss it — not on every turn.

Creation endpoints (remember, supersede, and record-outcome) require
container_ref, actor_ref, thread_ref, agent_ref, and visibility. Visibility
must be private, container, or global. Raw absolute filesystem paths are
rejected as container identifiers. Deprecated origin_session_id and
origin_agent_id aliases may populate their canonical fields, but must match
when both forms are sent. These values are attribution, not authentication.
Correction and forget preserve the memory's original creation provenance.

### POST /memory/remember

Durable fact write. Body fields: text, type, the required creation provenance
above, and optional confidence (audit only — does NOT influence retrieval
ranking) and evidence list.

Response: `{memory_object_id, origin, created_at}`.

Errors: 400 on unknown `type`, 422 on validation (text length, confidence
range).

### POST /memory/{memory_object_id}/correct

In-place fix of a wrong memory (extraction was mislabeled or partial).
Body: `corrected_text`, `reason`. Returns `{corrected: true}`.

Returns 409 if the memory is already superseded — walk the chain via
`GET /memory/{id}/expand` and correct the head.

For fully obsolete memories, use `/memory/supersede` instead.

### POST /memory/supersede

Replace an obsolete memory. Body: new_text, supersedes_id, the required
creation provenance above, and optional type and reason. Both rows persist;
retrieval hides the old.

Response: `{new_memory_object_id, superseded_memory_object_id}`.

Returns 409 on double-supersede.

### POST /memory/{memory_object_id}/forget

Soft-delete. Retrieval hides the row; audit trail preserved. Body: `reason`.
Idempotent — repeated calls on an already-forgotten memory return
`{forgotten: false}` without error.

Use `/memory/{id}/flag` instead when you're one voter among many;
`/memory/forget` is agent-decisive and immediate.

### POST /memory/record-outcome

Record success / failure / inconclusive for an operational-fact procedure.
Body: procedure_id, outcome, the required creation provenance above, and
optional evidence and note. Response: {recorded: true}.

Counters live under `payload["use_counters"]` on the target memory — a
nested sub-blob that retrieval paths cannot read (Invariant 1: retrieval
does not update ranking). This endpoint is the only writer of those
counters.

## GET /memory/{memory_object_id}/expand

Use this endpoint to retrieve the structured payload fields and source conversation items
that a memory object was derived from. This enables drill-down from a compact memory card
to the complete structured data and full original context.

An injection block sets `expand_available: true` when the memory has payload fields
worth expanding (evidence text, key findings, conclusions, etc.).

Required query parameter:

- `container_ref` — the container to validate access against. The endpoint
  returns 404 if the memory object doesn't belong to this container.

Example:

```
GET /memory/63119911-e39d-4b51-b804-8cbecd0522b3/expand?container_ref=slack:channel:C123
```

Response:

```json
{
  "memory_object_id": "63119911-e39d-4b51-b804-8cbecd0522b3",
  "payload": {
    "decision": "Use event timestamps for ordering",
    "rationale_text": "Avoids timezone drift issues seen in prior incident",
    "decision_evidence_text": "We decided to use event timestamps..."
  },
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

## POST /debug/queue/retry-failed

Loopback-only recovery for terminal processing failures after their root cause
has been fixed.

```json
{
  "failure_category": "llm_failure",
  "limit": 1000
}
```

Only exact-category matches are requeued. Completed package tasks are preserved;
failed package tasks are reset to pending so already-created memory is not
duplicated. Bounds are `1..1000`. Non-loopback callers receive HTTP 403.

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

