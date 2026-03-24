# 012 — Ingest Contract Simplification

## Motivation

The current `POST /items` and `POST /query` contracts carry fields that are
redundant, unused, or leaking agent implementation details into Pallium's API.
This was surfaced during a public docs review.

Specific problems:

1. `visibility_context` (`{kind, id}`) is almost always redundant with
   `container_ref` — the id is the container, the kind is always the same for a
   given container.
2. `session_ref` is an agent-runtime concept. Pallium's
   retrieval model is `container > thread > item`. Sessions are not Pallium's
   concern.
3. No field for agent identity. If two instances of the same agent serve the
   same channel, their items are indistinguishable.

## Changes

### Remove `session_ref`

`session_ref` is used in exactly one behavioral path: query filter widening for
`resumed_session`. That logic should use `thread_ref` instead. Everywhere else,
`session_ref` is passthrough plumbing.

Removal scope:

- `ItemCreateRequest.session_ref`
- `QueryRequest.session_ref`
- `QueryFilters.session_ref`
- filter narrowing logic in `core/contracts.py`
- passthrough in retrieval, storage, consolidation
- SourceItem and MemoryObject storage columns (migration: drop or ignore)

### Replace `visibility_context` with `visibility`

Current model:

```json
{
  "visibility_context": {
    "kind": "container",
    "id": "channel:C04ABC123"
  }
}
```

New model:

```json
{
  "visibility": "container"
}
```

Values: `"public"` | `"container"` | `"private"`. Default: `"private"`.

Mapping to Slack:

| Context | `container_ref` | `visibility` |
|---|---|---|
| Public channel | `"channel:C04ABC123"` | `"public"` |
| Private channel | `"channel:C07XYZ456"` | `"container"` |
| DM with agent | `"channel:D09USER789"` | `"private"` |

Retrieval behavior:

- `public` items are visible to queries from any container.
- `limited` and `private` items are visible only to queries from the same
  container.
- The label difference between `limited` and `private` is descriptive. It may
  matter later for consolidation or sharing policy, but retrieval treats them
  the same today.

### Add `agent_ref`

New optional field on ingest. Identifies which agent (or agent instance)
produced this item.

Examples:

- `"my-agent"` — single-instance deployment
- `"my-agent:prod-eu-1"` — multi-instance, distinguishable

Use cases:

- Traceability: which agent produced this memory.
- Future filtering: "show me what this agent instance remembered."
- Future sharing: agents can read each other's memory by querying across
  `agent_ref` values within the same container.

`agent_ref` is not `actor_ref`. `actor_ref` is the human user. `agent_ref` is
the AI agent.

### Replaces `use_case` in the caller contract

`use_case` (the semantic package selector) was already moved to server-side
config in the docs pass. This design confirms: callers do not send `use_case`.
Pallium selects the package from `default_use_case` in configuration.

## Resulting Ingest Contract

Required:

- `source_type`
- `source_id`
- `content_type`
- `content`

Optional:

- `container_ref`
- `visibility` (default: `"private"`)
- `thread_ref`
- `actor_ref`
- `agent_ref`
- `source_ref`
- `role`
- `artifact_kind`
- `occurred_at`
- `metadata`

## Resulting Query Contract

Required:

- `text`

Optional:

- `container_ref`
- `visibility`
- `thread_ref`
- `limit`
- `source_type`
- `role`
- `artifact_kind`
- `runtime_context`

## Migration

This is a breaking API change. The codebase is pre-1.0 with no external
consumers yet. Options:

- **Clean break**: change the contract, update all code, update all tests. No
  backward compatibility layer.
- **Transitional**: accept both `visibility_context` and `visibility`
  for one release, warn on the old shape, then remove.

Recommendation: clean break. We're early enough.

## Impact

### Code changes

- `api/schemas.py` — request/response models
- `core/models.py` — `SourceItem`, `MemoryObject` fields
- `core/contracts.py` — filter narrowing (remove session logic)
- `storage/sqlite.py` — schema, column mapping
- `storage/sqlite_codec.py` — encode/decode
- `retrieval/lexical.py`, `retrieval/vector.py` — result construction
- `capabilities/consolidation.py` — candidate model, session_ref usage
- `semantic/agent_conversation_memory*.py` — visibility checks
- All test files that reference `session_ref` or `visibility_context`

### What stays the same

- `container_ref + thread_ref` grouping for thread aggregation
- Fail-closed retrieval for missing visibility
- Evidence-backed memory model
- Debug trace path
