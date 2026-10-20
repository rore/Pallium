# Relay work associations

A work association links a Relay session to one exact work item. It supports participant discovery and tags eligible future Hermes History snapshots only when capture verifies the current-session association. A failed association lookup omits the tags. It does not send or wake agents, grant routing permission or memory access, or prove History coverage.

On pickup or resume, use `pallium_relay_work_refs` and reconcile the current session's associations with its actual accepted substantive assignments. Obtain each exact `scope_ref` and `local_ref` from its authoritative source; never guess or reconstruct identifiers. Reuse an exact listed pair, or attach it with `pallium_relay_attach_work_ref`. Only successful mutation and readback prove attachment. A session may have at most three explicit references in addition to structural references; never evict an unrelated or active assignment to make room.

On completion, cancellation, handoff or supersession, detach an exact current-session explicit association with `pallium_relay_detach_work_ref` only when no other accepted assignment still needs it. For correction, compare a successful list against authoritative exact references; detach only a proven erroneous current-session explicit origin, then attach or reuse the correct pair and verify readback. Preserve unrelated assignments, other sessions, unknown origins and structural origins. Detachment may report `structural_remains`; do not claim that the structural association was removed. The Hermes plugin currently does not produce branch or Work Record structural origins automatically.

Invoke these MCP operations only when callable. Missing tools, errors or capacity limits do not justify shell/HTTP substitutes, guessed identifiers, unrelated detachment or a success claim. Continue ordinary work and report the limitation when relevant.

For explicitly assigned Minimap implementation, investigation, testing or substantive review, obtain the exact pair from its installed skill's authoritative command:

`node <skill>/runtime/cli.js roadmap item-ref <item-id> --repo <absolute-repo-path> --json`

Use only the returned exact `scope_ref` and `local_ref`; if the command is unavailable or returns invalid/missing references, skip attachment and continue ordinary work. Casual browsing, passive inspection and clerical edits do not qualify. Attachment does not backfill past turns or prove task ownership, acceptance, activity, completion or History coverage.

Find collaborators with `pallium_relay_participants(scope_ref, local_ref)`; this does not send or wake them. Search with `pallium_search_history_by_work_ref` using an exact known work reference. Missing capture tags can make that search incomplete, so broaden with `pallium_search_history` when needed. Expand returned sources with `pallium_expand_source` and the search page's lookup lineage; follow the [History replay procedure](history-replay.md).
