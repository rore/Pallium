# Session History replay

The Hermes Pallium package always exposes `pallium_search_history`, `pallium_search_history_by_work_ref`, and `pallium_expand_source`. Use these tools from the current conversation's catalog. The optional supported-memory expansion on `pallium_expand_source` is available only when setup enables the memory catalog. Hermes supplies the current container, session and private scope; `actor_ref` and `source_thread_ref` are optional historical filters. Completion-only capture provides no current `request_source_item_id`; never invent one.

Keep a delivered-page ledger across query repair: record exact offsets, revisions, each page's `lookup_event_id`, source length and completion state. Advance only after successful caller delivery. Retry a failed page with identical arguments at most twice; do not skip unread pages or re-expand delivered pages. Keep the ledger through at most two query repairs, expand with the page-specific `parent_lookup_id`, and revalidate completed sources by revision. A historical recap is evidence about the past, not live state.

## Capability and search outcomes

Use the tools available in the current host and respect its permissions. When you need to check derived memory and the host exposes pallium_status, read derived_memory.enabled and derived_memory.injection_enabled separately. A package can be available for explicit use while automatic injection is disabled. Session History remains the path for earlier work when derived memory is disabled.

Search within the current trusted scope. Expand relevant sources with the exact source_item_id and the search page's lookup_event_id as parent_lookup_id. If a successful search yields no relevant examples, say you found no useful examples in this scope. Report an unavailable, denied, or failed search as such. Label any fresh writing as a new draft. A write receipt confirms the reported write. Later recall needs evidence from the actual retrieval or injection.
