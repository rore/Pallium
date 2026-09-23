---
description: Use Pallium Relay, Session History, or optional derived memory
---

Use the relevant Pallium capability for: $ARGUMENTS

- **Relay:** discover recipients with `pallium_relay_recipients`, then send useful context with `pallium_relay_send` when another session's work should change.
- `pallium_search_history_by_work_ref` — narrow exact normalized work-reference continuity; pass a raw valid structural ref and Pallium normalizes it. It can miss related work stored under another or no ref.
- `pallium_search_history` — broad topic search across eligible history/work items; old `work_refs` is compatibility-only, so use the explicit tool for one-work lookup.
- `pallium_expand_source` — expand a hit with its `source_item_id` and search `lookup_event_id` as `parent_lookup_id` for parent linkage.
- History retry: keep a delivered-page ledger across query repair; retry the same failed page at most twice, continue unread pages, and keep page-specific lookup lineage. Revalidate completed sources by content revision; use bounded retries. A historical recap is not live state; verify current state live. See [procedure](../../skills/pallium-memory/references/history-replay.md).
- **Derived memory:** use `pallium_query` for compact stored context, or the explicit remember/correct/supersede/forget tools when the user asks.

Use the injected `container_ref` and current scope values exactly. Default to `visibility: "private"`; global visibility requires explicit user intent.
