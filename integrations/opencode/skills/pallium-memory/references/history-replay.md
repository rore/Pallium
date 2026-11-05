# Session History replay procedure

Keep a delivered-page ledger across query repair: delivered search and expansion pages, their exact offsets and revisions, each page's `lookup_event_id`, source total length, and completion state.

- Advance the ledger only after successful caller delivery. For a failed page, retry the identical arguments: initial call plus at most two retries. Do not skip unread or re-expand delivered pages.
- Make at most two query repairs. Keep the ledger, then continue only at the exact unread result/content offset and revision. Expand with the `parent_lookup_id` from the page-specific `lookup_event_id` that supplied that source.
- When a completed source recurs, terminal-probe its recorded total length with its recorded content revision. An unchanged probe stays complete. A stale response resets and restarts that source; an offset-zero response with a changed revision is consumed as the first page of the new revision.
- Allow at most two stale restarts per query window and per source. On exhaustion, report unrecovered evidence rather than skipping it.
- A historical recap is evidence about the past, not live state. Verify current-state claims through the appropriate live source.

## Capability and search outcomes

Use the tools available in the current host and respect its permissions. When you need to check derived memory and the host exposes pallium_status, read derived_memory.enabled and derived_memory.injection_enabled separately. A package can be available for explicit use while automatic injection is disabled. Session History remains the path for earlier work when derived memory is disabled.

Search within the current trusted scope. Expand relevant sources with the exact source_item_id and the search page's lookup_event_id as parent_lookup_id. If a successful search yields no relevant examples, say you found no useful examples in this scope. Report an unavailable, denied, or failed search as such. Label any fresh writing as a new draft. A write receipt confirms the reported write. Later recall needs evidence from the actual retrieval or injection.
