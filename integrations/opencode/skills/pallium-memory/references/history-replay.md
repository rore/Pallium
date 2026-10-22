# Session History replay procedure

## Finding conversational decisions

- Use known topic anchors (the subject, action, or artifact), not only vague words such as "first items". For an agreed plan, omit `role` unless the user explicitly asks for one author's turns: the proposal may be an assistant turn and the qualification or approval a user turn.
- `role=user` is not a human-authorship filter; automated prompts can have that role. Do not silently override an explicit role restriction or treat a reminder as proof of a human decision.
- Expand promising sources with neighboring turns to distinguish proposals, qualifications, and acceptance. Preserve exact source references and wording; do not turn a suggested list into an agreed order.
- Changing query text or optional source filters counts toward the two query repairs below. Preserve the delivered-page ledger across those changes; never broaden an explicitly requested scope without permission.
- An unrecovered answer is not proof that the source was never stored. State which queries/pages were checked and what remains unread or unknown.

Keep a delivered-page ledger across query repair: delivered search and expansion pages, their exact offsets and revisions, each page's `lookup_event_id`, source total length, and completion state.

- Advance the ledger only after successful caller delivery. For a failed page, retry the identical arguments: initial call plus at most two retries. Do not skip unread or re-expand delivered pages.
- Make at most two query repairs. Keep the ledger, then continue only at the exact unread result/content offset and revision. Expand with the `parent_lookup_id` from the page-specific `lookup_event_id` that supplied that source.
- When a completed source recurs, terminal-probe its recorded total length with its recorded content revision. An unchanged probe stays complete. A stale response resets and restarts that source; an offset-zero response with a changed revision is consumed as the first page of the new revision.
- Allow at most two stale restarts per query window and per source. On exhaustion, report unrecovered evidence rather than skipping it.
- A historical recap is evidence about the past, not live state. Verify current-state claims through the appropriate live source.
