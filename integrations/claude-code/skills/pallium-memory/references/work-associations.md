# Relay work associations

## Generic exact-work workflow

A work association says a Relay session participates in one exact work item. It supports participant discovery and can tag eligible subsequent History snapshots when per-turn association lookup succeeds; it does not send or wake agents, grant routing permission or memory access, and registry membership does not prove Session History coverage.

On pickup or resume, call `pallium_relay_work_refs` and reconcile the current session's associations against its actual accepted substantive assignments. Obtain each assignment's stable, exact `scope_ref`/`local_ref` pair from its authoritative source; a tracker key needs its project scope, and identifiers must never be guessed. Reuse an exact listed association, including a current-session explicit origin successfully attached in an earlier turn. Attach an absent exact assigned pair with `pallium_relay_attach_work_ref(scope_ref, local_ref)`. A session may have at most three explicit references in addition to its structural references; never evict an unrelated reference to make room.

Keep each explicit association throughout its assignment, including ordinary waits. When that assignment ends, is cancelled, or transfers away, call `pallium_relay_detach_work_ref(scope_ref, local_ref)` for its exact current-session explicit origin, even if the feature remains unfinished. Preserve unrelated references and other sessions' links; unknown assignment state is not permission to detach. The API removes only the current session's explicit origin and may report `structural_remains`.

For exact link correction, compare a successful list with the assignment's authoritative exact pair. Detach only a proven erroneous current-session explicit origin not required by another current accepted assignment with `pallium_relay_detach_work_ref(scope_ref, local_ref)`; unknown or structural origins are not correction targets. After successful detachment, attach or reuse the authoritative pair. Preserve active assignments, unrelated references, other sessions' links, and structural origins. If detachment fails, report the limitation and do not claim correction; claim correction only after successful mutation results and readback confirming the authoritative pair is present and the erroneous explicit origin is absent.

Branch and Agent Workflow references are hook-owned structural origins: do not attach explicit duplicates or attempt to detach structural origins manually. Producers refresh them from the current branch and matching Work Record; ending an assignment alone does not clear them while that structural context remains. This procedure does not resolve custom/resumed Work Record discovery gaps.

Invoke each named Pallium MCP operation only when callable; only its successful result is authoritative. This applies to list, attach, detach, participants, and History operations named here. A successful list proves observed state; only a successful mutation proves attachment or detachment. If a required tool is unavailable or fails, or capacity prevents attach, continue ordinary work and report the limitation when relevant. Do not claim success, invent references, use shell/HTTP substitutes, or detach merely because an optional provider is absent.

Find collaborators with `pallium_relay_participants(scope_ref, local_ref)`. This read does not send or wake agents. Set `include_closed=true` only when closed sessions matter, and route with the returned canonical selector.

In the dashboard, open Relay, select a session, then use Associated work references to inspect, add, remove, or look up the same associations.

## Explicit Minimap workflow

Casual browsing, passive inspection, and clerical edits do not qualify for Minimap participation.

For every accepted explicitly assigned Minimap implementation, investigation, testing, or substantive review, run the authoritative command and follow the generic workflow above:


`node <skill>/runtime/cli.js roadmap item-ref <item-id> --repo <absolute-repo-path> --json`

Use the returned exact `scope_ref` and `local_ref`; never reconstruct, normalize, or derive either value. If the CLI/tool is unavailable or errors, or the CLI returns missing or invalid scope/local refs, do not supply a pair and continue ordinary work. If the exact pair is absent from a successful list, attach the exact CLI-returned pair with `pallium_relay_attach_work_ref(scope_ref, local_ref)`; the generic workflow governs result authority and capacity. Use broad History only when `pallium_search_history` is callable.

A successful attach does not backfill untagged prior turns. Older eligible items already carrying the same canonical key remain searchable; eligible later turns can carry it only when per-turn association lookup succeeds. Association implies no task ownership, activity, acceptance, completion, receipt, or History/memory access.
