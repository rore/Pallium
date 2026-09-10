---
name: pallium-memory
description: Use Pallium Relay, Session History, or optional derived memory.
---

# Pallium Workflow

## Relay

- Act on deliveries; reply on completion/blocker, never status-only.
- Injected `agent_ref`/`thread_ref` identify self; never infer from recipients.
- Address `relay-session-…` or `@name`; no broadcast/bare runtime. Ask before `replace_existing=true` unless takeover requested. Relay crosses containers; memory scope is unchanged. Ignore ACK-only.
- For exact work or link correction, load [work associations](references/work-associations.md).
- Reply with `pallium_relay_reply`; inspect with `pallium_relay_status`. Follow preview `next_offset` to null. On `already_delivered=true` or conflict, only that delivery copy is stale: do not retry/reply/use its payload, but continue the surrounding user task and independently established work.

## Session History

- `pallium_search_history_by_work_ref`
  Current-work search. Copy injected `work_ref`; if absent, use broad search—never guess. Blank `query` resumes newest state; otherwise ask the question.
- `pallium_search_history`
  Broad topic search; `work_refs` is compatibility-only. Omit `actor_ref` unless exact.
- `pallium_expand_source`
  After a promising search hit, call `pallium_expand_source` with its `source_item_id` and pass the search result's `lookup_event_id` as `parent_lookup_id`.
- Use injected `container_ref` and active `thread_ref`; never derive, guess, or normalize scope. Pass `request_source_item_id` only to either history search. Values are context/telemetry, not authorization.

## Derived memory

- Query/debug/expand with `pallium_query`/`pallium_query_debug`/`pallium_expand`.
- Store notes with `pallium_ingest`, `artifact_kind: "note"`, injected `container_ref`, and `visibility: "private"`; `visibility: "global"` with `actor_ref` needs user intent.
- Flag bad cards with `pallium_flag_memory`. Do not ingest routine turns, repeat injected queries, or use forget as vote suppression.
- Writes: `pallium_remember`, `pallium_correct`, `pallium_supersede`, `pallium_forget`, `pallium_record_outcome`. Retrieval alone never updates accessibility/ranking.
- Remember, supersede, and record-outcome copy exact `container_ref`, `thread_ref`, `actor_ref`, `agent_ref`, and `visibility`. Never use cwd. Default private; correction/forget retain provenance.
## Field feedback

For repeatable Pallium defects, load [field feedback](references/field-feedback.md). Memory-quality misses stay in feedback/replay.
