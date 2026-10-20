# Session History replay

The Hermes Pallium package exposes `pallium_search_history`, `pallium_search_history_by_work_ref`, and `pallium_expand_source`. Use these tools from the current conversation's catalog. Hermes supplies the current container, session and private scope; `actor_ref` and `source_thread_ref` are optional historical filters. Completion-only capture provides no current `request_source_item_id`; never invent one.

Keep a delivered-page ledger across query repair: record exact offsets, revisions, each page's `lookup_event_id`, source length and completion state. Advance only after successful caller delivery. Retry a failed page with identical arguments at most twice; do not skip unread pages or re-expand delivered pages. Keep the ledger through at most two query repairs, expand with the page-specific `parent_lookup_id`, and revalidate completed sources by revision. A historical recap is evidence about the past, not live state.
