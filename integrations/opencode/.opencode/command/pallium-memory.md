---
description: Deliberate Pallium memory work — search history, store a fact, or debug retrieval
---

Do deliberate Pallium memory work for: $ARGUMENTS

Automatic injection already handles routine retrieval, so use the tools only when explicit context work is needed:
- Resuming prior work: call `pallium_search_history` first, then `pallium_expand_source` with the hit's `source_item_id` and the search result's `lookup_event_id` as `parent_lookup_id`.
- Search distilled memory with `pallium_query`; use `pallium_query_debug` to tell filtered vs. missing vs. low-relevance apart.
- Store a durable fact with `pallium_remember`; fix one with `pallium_correct`; replace an obsolete one with `pallium_supersede`; hide one with `pallium_forget`.
- Flag an incorrect or outdated injected memory with `pallium_flag_memory` (pass its `ref` id and a brief reason).

Always pass the injected `container_ref` and `visibility: "private"` unless the user explicitly asks for global visibility.
