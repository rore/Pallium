# Relay work associations

A work association links a Relay session to one exact work item. It supports participant discovery and tags eligible future Hermes History snapshots only when capture verifies the current-session association. A failed association lookup omits the tags. It does not send or wake agents, grant routing permission or memory access, or prove History coverage.

For a known work item, use `pallium_relay_work_refs` first. Reuse an exact listed pair, or attach the exact supplied `scope_ref` and `local_ref` with `pallium_relay_attach_work_ref`. Do not guess identifiers. A session may have at most three explicit references in addition to structural references. Only a successful attach proves the mutation; never evict an existing association to make room.

Use `pallium_relay_detach_work_ref` only for an explicit association this workflow attached and only when the session leaves that work. Find collaborators with `pallium_relay_participants(scope_ref, local_ref)`; this does not send or wake them. Search with `pallium_search_history_by_work_ref` using an exact known work reference. Missing capture tags can make that search incomplete, so broaden with `pallium_search_history` when needed. Expand returned sources with `pallium_expand_source` and the search page's lookup lineage; follow the [History replay procedure](history-replay.md).
