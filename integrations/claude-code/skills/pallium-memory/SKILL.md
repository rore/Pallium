---
name: pallium-memory
description: Use Pallium memory or explicitly relay a message to another agent.
---

# Pallium Memory Workflow

Routine retrieval is automatic. Use tools for deliberate memory or explicit relay.

## Memory

- Store notes with `pallium_ingest`, `artifact_kind: "note"`, injected `container_ref`, and `visibility: "private"`. `visibility: "global"` with `actor_ref` requires explicit user intent.
- Use `pallium_search_history` to resume and `pallium_query` for distilled memory. After a promising search hit, call `pallium_expand_source` with its `source_item_id` and pass the search result's `lookup_event_id` as `parent_lookup_id`.
- `pallium_search_history` and `pallium_expand_source` use injected `container_ref` and active `thread_ref`; never derive, guess, or normalize them. Pass `request_source_item_id` only to history search. Scope is telemetry, not authorization.
- Debug/expand with `pallium_query_debug`/`pallium_expand`; use only `current`.
- Flag bad cards with `pallium_flag_memory`. Do not ingest routine turns, repeat injected queries, or use forget as vote suppression.
- Writes: `pallium_remember`, `pallium_correct`, `pallium_supersede`, `pallium_forget`, `pallium_record_outcome`. Retrieval alone never updates accessibility/ranking.
- Remember, supersede, and record-outcome copy exact `container_ref`, `thread_ref`, `actor_ref`, `agent_ref`, and `visibility`. Never use cwd. Default private; correction/forget retain provenance.

## Relay

Relay only explicit messages to another agent.

- Injected `agent_ref`/`thread_ref` identify this runtime/session. Never infer self from recipients.
- Discover/name with `pallium_relay_recipients`/`pallium_relay_name`. Send with `pallium_relay_send` to `codex`, `codex:<session_ref>`, or `codex:@alias` (likewise other runtimes). Broadcast requires user intent.
- If the user assigns this session an alias held by an older one, use `replace_existing=true`; otherwise report the conflict.
- Reply only with `pallium_relay_reply` and received `delivery_id`; Pallium derives endpoints. Inspect with `pallium_relay_status`.