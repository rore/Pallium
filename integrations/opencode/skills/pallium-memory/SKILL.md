---
name: pallium-memory
description: Use Pallium Relay, Session History, or optional derived memory.
---

# Pallium Workflow

## Relay

- Complete actionable deliveries now; reply only after completion or a genuine blocker, never with a status-only acknowledgement.
- Injected `agent_ref`/`thread_ref` identify this runtime and session; never infer self from recipients.
- Discover or name sessions with `pallium_relay_recipients` and `pallium_relay_name`. Send with `pallium_relay_send` to a runtime, exact session, or alias. Broadcast needs user intent.
- Replace an alias with `replace_existing=true`; otherwise report the conflict. Do not reply to terminal ACK-only deliveries.
- Reply with `pallium_relay_reply`; inspect with `pallium_relay_status`. On `already_delivered=true` or conflict, only that delivery copy is stale: do not retry/reply/use its payload, but continue the surrounding user task and independently established work.

## Session History

- When prior work may matter, call `pallium_search_history`. After a promising search hit, call `pallium_expand_source` with its `source_item_id` and pass the search result's `lookup_event_id` as `parent_lookup_id`.
- `pallium_search_history` and `pallium_expand_source` use injected `container_ref` and active `thread_ref`; never derive, guess, or normalize them. Pass `request_source_item_id` only to history search. These values are context and telemetry, not authorization.

## Derived memory

- Search with `pallium_query`; debug or expand with `pallium_query_debug` and `pallium_expand`.
- Store deliberate notes with `pallium_ingest`, `artifact_kind: "note"`, injected `container_ref`, and `visibility: "private"`. `visibility: "global"` with `actor_ref` requires user intent.
- Flag bad cards with `pallium_flag_memory`. Do not ingest routine turns, repeat injected queries, or use forget as vote suppression.
- Writes: `pallium_remember`, `pallium_correct`, `pallium_supersede`, `pallium_forget`, `pallium_record_outcome`. Retrieval alone never updates accessibility or ranking.
- Remember, supersede, and record-outcome writes copy exact `container_ref`, `thread_ref`, `actor_ref`, `agent_ref`, and `visibility`. Never use cwd. Default private; correction and forget retain provenance.
