---
name: pallium-memory
description: Search, store, expand, or debug Pallium memory when explicit context work is needed.
---

# Pallium Memory Workflow

Use for deliberate memory work; injection handles routine retrieval.

- Store with `pallium_ingest`, using `artifact_kind: "note"`, `visibility: "private"`, and the injected `container_ref`. Use `visibility: "global"` with `actor_ref` only when explicitly requested.
- When resuming work, call `pallium_search_history` first. Use `pallium_query` for distilled memory. After a promising search hit, call `pallium_expand_source` with its `source_item_id` and pass the search result's `lookup_event_id` as `parent_lookup_id`. `pallium_search_history` and `pallium_expand_source` receive the exact injected `container_ref` and active `thread_ref`; never derive, guess, or normalize the container. Default private; explicit global needs `actor_ref`. `thread_ref` is telemetry only—not authorization or historical identity. Pass injected `request_source_item_id` only to `pallium_search_history`.
- Use `pallium_query_debug` to distinguish filtered, missing, and low-relevance results. Use `pallium_expand` when a memory card offers expansion.
- `recorded_at_source` labels dates. Treat `outdated` as evidence; use only a `current` replacement.
- Flag incorrect or obsolete cards with `pallium_flag_memory`; ratings are optional.
- Explicit writes: `pallium_remember` stores a fact; `pallium_correct` fixes it; `pallium_supersede` replaces it; `pallium_forget` hides it; `pallium_record_outcome` records a result. Retrieval alone never updates accessibility or ranking.
- Do not ingest routine turns or re-query for something already in the injected block; use forget only for direct hiding, not vote suppression; use `pallium_flag_memory`.

- Explicit remember, supersede, and record-outcome writes must copy all five exact [Pallium scope] values: container_ref, thread_ref, actor_ref, agent_ref, and visibility. Never use cwd. Default private; use global only when requested. Correction and forget keep original provenance.
