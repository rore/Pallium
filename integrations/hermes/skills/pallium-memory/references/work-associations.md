# Relay work associations

A work association links a Relay session to one exact work item. It supports participant discovery and may tag eligible future History snapshots when that separate feature is available. It does not send or wake agents, grant routing permission or memory access, or prove History coverage.

For a known work item, use `pallium_relay_work_refs` first. Reuse an exact listed pair, or attach the exact supplied `scope_ref` and `local_ref` with `pallium_relay_attach_work_ref`. Do not guess identifiers. A session may have at most three explicit references in addition to structural references. Only a successful attach proves the mutation; never evict an existing association to make room.

Use `pallium_relay_detach_work_ref` only for an explicit association this workflow attached and only when the session leaves that work. Find collaborators with `pallium_relay_participants(scope_ref, local_ref)`; this does not send or wake them. This Hermes package does not expose History search tools, so an association does not make History operations available.
