---
name: pallium-memory
description: Relay, Session History, optional derived memory.
---

# Pallium
## Relay
- [Waiting](references/wait.md).

- Reconcile work/state; keep late findings. Skip completed actions/routine replies; follow authorized work. Reply on completion/blocker.
- Send=saved, not started; pending unconfirmed. `busy_queue`=capability, not observed busyness. Urgent: open task, let work finish, ordinary turn if needed; do not resend.
- Self: injected `agent_ref`/`thread_ref`; never infer.
- Role target: current `@name`; rediscover before endpoint reuse. Check returned admission session/container if scope matters. Aliases/endpoints move; neither proves scope. No broadcast/bare runtime; takeover by request; ignore ACK-only.
- Cross-project: `pallium_relay_recipients` is container-local. For unknown containers, load [global discovery](references/global-relay-discovery.md) before sending.
- For exact work/link correction, load [work associations](references/work-associations.md). For explicitly assigned Minimap implementation, investigation, testing, or substantive review, use it when continuity helps; casual browsing, passive inspection, and clerical edits do not qualify.
- MCP: reply/ACK before source TTL or 60s lease ends; ACK permits later reply. Use `pallium_relay_reply`; page to `next_offset=null`. On `already_delivered=true` or conflict, only that delivery copy is stale: do not retry/reply/use its payload, but continue the surrounding user task and independently established work.

## History

- `pallium_search_history_by_work_ref`
  Current-work search. Copy injected `work_ref`; if absent, broaden; never guess.
- `pallium_search_history`
  Broad topic search; `work_refs` is compatibility-only. Omit `actor_ref` normally.
- `pallium_expand_source`
  After a promising search hit, call `pallium_expand_source` with its `source_item_id` and pass the search result's `lookup_event_id` as `parent_lookup_id`.
- History retry [procedure](references/history-replay.md): delivered-page ledger; query repair; retry the same failed page max twice; unread pages; page-specific lookup lineage; Revalidate completed sources by content revision; bounded retries. A historical recap is not live state; verify current state live.
- Use injected `container_ref`/active `thread_ref`; never derive, guess, or normalize scope. `request_source_item_id`: only to either history search.

## Derived memory

- Query: `pallium_query`/`pallium_query_debug`/`pallium_expand`.
- `pallium_ingest`: default `visibility: "private"`; `visibility: "global"` with `actor_ref` needs user intent.
- Flag bad cards with `pallium_flag_memory`. Do not ingest routine turns or use forget as vote suppression.
- Write: `pallium_remember`/`pallium_correct`/`pallium_supersede`/`pallium_forget`/`pallium_record_outcome`; retrieval never updates accessibility/ranking.
- Exact provenance; no cwd. Private default; correction/forget retain it.

## Field feedback

Repeatable defect: [field feedback](references/field-feedback.md). Memory-quality miss: feedback/replay.
