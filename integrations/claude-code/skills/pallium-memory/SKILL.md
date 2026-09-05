---
name: pallium-memory
description: Use Pallium Relay, Session History, or optional derived memory.
---

# Pallium Workflow

## Relay

- Handle deliveries now; reply only after completion/blocker, never status-only.
- Injected `agent_ref`/`thread_ref` identify self; never infer self from recipients.
- Discover/name with `pallium_relay_recipients`/`pallium_relay_name`; send with `pallium_relay_send` to runtime/session/alias. Broadcast needs user intent.
- Replace aliases with `replace_existing=true`; otherwise report conflict. Ignore terminal ACK-only deliveries.
- Reply with `pallium_relay_reply`; inspect with `pallium_relay_status`. On `already_delivered=true` or conflict, only that delivery copy is stale: do not retry/reply/use its payload, but continue the surrounding user task and independently established work.

## Session History

- `pallium_search_history_by_work_ref`
  Narrow exact-ref continuity; Pallium normalizes a valid structural ref. It can miss another/no ref. Blank `query` returns newest eligible items.
- `pallium_search_history`
  Broad topic search across eligible history/work items. `work_refs` is compatibility-only.
- `pallium_expand_source`
  After a promising search hit, call `pallium_expand_source` with its `source_item_id` and pass the search result's `lookup_event_id` as `parent_lookup_id`.
- Use injected `container_ref` and active `thread_ref`; never derive, guess, or normalize scope. Pass `request_source_item_id` only to either history search. Values are context/telemetry, not authorization.

## Derived memory

- Search with `pallium_query`; debug/expand with `pallium_query_debug`/`pallium_expand`.
- Store notes with `pallium_ingest`, `artifact_kind: "note"`, injected `container_ref`, and `visibility: "private"`; `visibility: "global"` with `actor_ref` needs user intent.
- Flag bad cards with `pallium_flag_memory`. Do not ingest routine turns, repeat injected queries, or use forget as vote suppression.
- Writes: `pallium_remember`, `pallium_correct`, `pallium_supersede`, `pallium_forget`, `pallium_record_outcome`. Retrieval alone never updates accessibility/ranking.
- Remember, supersede, and record-outcome copy exact `container_ref`, `thread_ref`, `actor_ref`, `agent_ref`, and `visibility`. Never use cwd. Default private; correction/forget retain provenance.
