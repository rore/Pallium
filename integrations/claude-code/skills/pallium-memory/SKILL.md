---
name: pallium-memory
description: Use Pallium memory or explicitly relay a message to another agent.
---

# Pallium Memory Workflow

Routine retrieval is automatic. Use tools for deliberate memory work or explicit agent communication.

## Memory

- Store notes with `pallium_ingest`: `artifact_kind: "note"`, `visibility: "private"`, and injected `container_ref`. `visibility: "global"` with `actor_ref` requires explicit user intent.
- Resume with `pallium_search_history`; use `pallium_query` for distilled memory. After a promising search hit, call `pallium_expand_source` with its `source_item_id` and pass the search result's `lookup_event_id` as `parent_lookup_id`.
- `pallium_search_history` and `pallium_expand_source` receive exact injected `container_ref` and active `thread_ref`; never derive, guess, or normalize it. `thread_ref` is telemetry, not authorization. Pass injected `request_source_item_id` only to history search.
- Debug with `pallium_query_debug`; expand a card with `pallium_expand`. Treat `outdated` as evidence and use only `current`.
- Flag bad cards with `pallium_flag_memory`; ratings are optional. Do not ingest routine turns, repeat injected queries, or use forget as vote suppression.
- Writes: `pallium_remember`, `pallium_correct`, `pallium_supersede`, `pallium_forget`, `pallium_record_outcome`. Retrieval alone never updates accessibility or ranking.
- Remember, supersede, and record-outcome copy all five exact scope values: `container_ref`, `thread_ref`, `actor_ref`, `agent_ref`, `visibility`. Never use cwd. Default private; correction/forget keep provenance.

## Relay

Use Relay only when another agent explicitly needs a message.

- Identity: injected `agent_ref` is current/sender runtime; `thread_ref` is current/sender session. Never discover self from recipients.
- Discover/name targets with `pallium_relay_recipients`/`pallium_relay_name`; send new messages with `pallium_relay_send`. Broadcast needs explicit user intent.
- Reply only with `pallium_relay_reply` and received `delivery_id`; Pallium derives endpoints. Inspect with `pallium_relay_status`.
