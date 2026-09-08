---
name: pallium-memory
description: Use Pallium Relay, Session History, or optional derived memory.
---

# Pallium Workflow

## Relay

- Handle deliveries now; reply on completion/blocker, never status-only.
- Injected `agent_ref`/`thread_ref` are self; never infer from recipients.
- Relay: `relay-session-…` or global `@name`; no broadcast/bare runtime; legacy may conflict.
- On conflict, ask before `replace_existing=true` unless takeover requested. Relay routes across containers; memory unchanged. Ignore ACK-only.
- Reply with `pallium_relay_reply`; inspect with `pallium_relay_status`. For previews, read `next_offset` pages until null. On `already_delivered=true` or conflict, only that delivery copy is stale: do not retry/reply/use its payload, but continue the surrounding user task and independently established work.

## Session History

- `pallium_search_history_by_work_ref`
  Current-work search. Copy injected `work_ref`; if absent, use broad search—never guess. Blank `query` resumes newest state; otherwise ask the question.
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
## Field feedback

For repeatable Pallium product/integration/contract/docs defects, load [field feedback](references/field-feedback.md). Memory-quality misses stay in existing feedback/replay.
