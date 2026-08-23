---
name: pallium-memory
description: Search, store, expand, or debug Pallium memory when explicit context work is needed.
---

# Pallium Memory Workflow

Use this skill for deliberate memory work; automatic injection handles routine retrieval.

- Store with `pallium_ingest`, using `artifact_kind: "note"`, `visibility: "private"`, and the injected `container_ref`. Use `visibility: "global"` with `actor_ref` only when explicitly requested.
- Search distilled memory with `pallium_query`; use `pallium_search_history` and `pallium_expand_source` to resume prior work and inspect bounded raw context. After a promising search hit, call `pallium_expand_source` with its `source_item_id` and pass the search result's `lookup_event_id` as `parent_lookup_id`. Copy the injected `container_ref` exactly—never derive, guess, or normalize it—and pass the active `thread_ref` with `visibility: "private"`. The thread ref is requester telemetry only — never authorization or the historical source identity.
- Use `pallium_query_debug` to distinguish filtered, missing, and low-relevance results. Use `pallium_expand` when a memory card offers expansion.
- Use `pallium_flag_memory` for incorrect or obsolete memories. Ratings via `pallium_rate_memory` are optional, non-blocking feedback.
- Explicit writes stay compact and deliberate: `pallium_remember` stores a fact, `pallium_correct` fixes it, `pallium_supersede` replaces an obsolete fact, `pallium_forget` hides it, and `pallium_record_outcome` records a procedure result. Retrieval is not use: retrieval alone never updates accessibility or ranking.
- Do not ingest routine turns or re-query for something already in the injected block; use forget only for direct hiding, not vote suppression; use `pallium_flag_memory`.
