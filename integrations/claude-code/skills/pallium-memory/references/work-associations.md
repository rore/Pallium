# Relay work associations

## Generic exact-work workflow

A work association says a Relay session participates in one exact work item. It supports participant discovery and can tag eligible subsequent History snapshots when per-turn association lookup succeeds; it does not send or wake agents, grant routing permission or memory access, and registry membership does not prove Session History coverage.

For exact work or link correction, supply a stable, known `scope_ref`/`local_ref` pair. A tracker key needs its project scope; never guess identifiers. Call `pallium_relay_work_refs` first, reuse an exact listed pair, or attach the supplied pair with `pallium_relay_attach_work_ref(scope_ref, local_ref)`. A session may have at most three explicit references in addition to its structural references. Branch and Agent Workflow references are structural; hooks refresh them automatically, so do not attach explicit duplicates. Invoke each named Pallium MCP operation only when that operation is callable; only its successful result is authoritative. This applies to `pallium_relay_work_refs`, `pallium_relay_attach_work_ref`, `pallium_relay_detach_work_ref`, `pallium_relay_participants`, `pallium_search_history_by_work_ref`, and `pallium_search_history`. A successful list is authoritative; only a successful attach proves mutation. If a required tool is unavailable or fails, or capacity prevents attach, skip attachment, continue ordinary work, and never evict an existing explicit reference. A listed absent exact pair is the normal attach condition; an attempted or failed call proves nothing.

Use `pallium_relay_detach_work_ref` when the session stops that exact work, only when the operation is callable. Detach only the explicit association this flow successfully attached; a structural origin may remain. Only a successful detach result proves mutation. Find collaborators with `pallium_relay_participants(scope_ref, local_ref)`. This read does not send or wake agents. Set `include_closed=true` only when closed sessions matter, and route with the returned canonical selector.

In the dashboard, open Relay, select a session, then use Associated work references to inspect, add, remove, or look up the same associations.

## Explicit Minimap workflow

passive browsing, inspection, and clerical edits do not qualify for Minimap participation.

For an explicit Minimap implementation or substantive-review assignment where exact association or History continuity would help, run the authoritative command, then follow the generic workflow above for callable-tool, successful-result, fallback, and capacity semantics:


`node <skill>/runtime/cli.js roadmap item-ref <item-id> --repo <absolute-repo-path> --json`

Use the returned exact `scope_ref` and `local_ref`; never reconstruct, normalize, or derive either value. If the CLI/tool is unavailable or errors, or the CLI returns missing or invalid scope/local refs, do not supply a pair and continue ordinary work. If the exact pair is absent from a successful list, attach the exact CLI-returned pair with `pallium_relay_attach_work_ref(scope_ref, local_ref)`; the generic workflow governs result authority and capacity. Use broad History only when `pallium_search_history` is callable.

A successful attach does not backfill untagged prior turns. Older eligible items already carrying the same canonical key remain searchable; eligible later turns can carry it only when per-turn association lookup succeeds. Association implies no task ownership, activity, acceptance, completion, receipt, or History/memory access.

Detach only the exact pair this flow successfully attached, identified by the current session's explicit origin, and only when the session actually leaves that work. The API removes only the current session's explicit origin and may report `structural_remains`; only a successful detach is authoritative. Never attempt to remove a structural origin or detach merely because an optional provider is absent. Existing default Agent Workflow structural behavior remains, and the custom/resumed scope gap is not solved here.