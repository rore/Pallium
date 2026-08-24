<!-- pallium:start -->
# Memory (Pallium)

Use Pallium for deliberate memory work; automatic injection handles routine retrieval.

Picking up prior work? Call `pallium_search_history` first. After a promising search hit, call `pallium_expand_source` with its `source_item_id` and pass the search result's `lookup_event_id` as `parent_lookup_id`. Copy the injected `container_ref` exactly—never derive, guess, or normalize it. Pass the active `thread_ref` to both tools for telemetry; it is not authorization or the historical source identity.
- Search distilled memory with `pallium_query`; use `pallium_search_history` for raw turns and `pallium_expand_source` for bounded context.
- Store turns with `pallium_ingest` (`artifact_kind="note"`, `visibility: "private"`, and the injected `container_ref`). Use global visibility only when explicitly requested, with `actor_ref`.
- Use `pallium_query_debug` to distinguish filtered, missing, and low-relevance results; use `pallium_expand` when a memory card offers expansion.
- Use `pallium_flag_memory` for incorrect or obsolete memories. `pallium_rate_memory` is optional, non-blocking feedback; never require a rating for every injected block.
- Explicit writes are compact and deliberate: `pallium_remember` stores a durable fact; `pallium_correct` fixes it; `pallium_supersede` replaces an obsolete fact; `pallium_forget` hides it; `pallium_record_outcome` records a procedure result. Retrieval is not use: these writes do not update accessibility or ranking from retrieval alone.
- Do not ingest routine turns or re-query for something already in the injected block; use forget only for direct hiding, not vote suppression; use `pallium_flag_memory` for that.
- Explicit remember, supersede, and record-outcome writes must copy all five exact [Pallium scope] values: container_ref, thread_ref, actor_ref, agent_ref, and visibility. Never use cwd. Default private; use global only when requested. Correction and forget keep original provenance.
<!-- pallium:end -->
