# Session History replay procedure

Keep a delivered-page ledger across query repair: delivered search and expansion pages, their exact offsets and revisions, each page's `lookup_event_id`, source total length, and completion state.

- Advance the ledger only after successful caller delivery. For a failed page, retry the identical arguments: initial call plus at most two retries. Do not skip unread or re-expand delivered pages.
- Make at most two query repairs. Keep the ledger, then continue only at the exact unread result/content offset and revision. Expand with the `parent_lookup_id` from the page-specific `lookup_event_id` that supplied that source.
- When a completed source recurs, terminal-probe its recorded total length with its recorded content revision. An unchanged probe stays complete. A stale response resets and restarts that source; an offset-zero response with a changed revision is consumed as the first page of the new revision.
- Allow at most two stale restarts per query window and per source. On exhaustion, report unrecovered evidence rather than skipping it.
- A historical recap is evidence about the past, not live state. Verify current-state claims through the appropriate live source.
