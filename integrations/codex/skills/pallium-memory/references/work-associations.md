# Relay work associations

A work association says a Relay session participates in one exact work item. It supports participant discovery and tags subsequent History snapshots; it does not send or wake agents, grant routing permission or memory access, and registry membership does not prove Session History coverage.

- Branch and Agent Workflow references are structural. Hooks refresh them automatically; do not attach explicit duplicates.
- Call `pallium_relay_work_refs` before changing references. Use `pallium_relay_attach_work_ref(scope_ref, local_ref)` only when current work has a stable, known scope and reference not represented structurally, and shared-work discovery or exact current-work History will help. Never guess identifiers; a tracker key needs its project scope. A session may have three explicit references in addition to its structural references.
- Use `pallium_relay_detach_work_ref` when the session stops that work. A structural origin may remain.
- Find collaborators with `pallium_relay_participants(scope_ref, local_ref)`. This read does not send or wake. Set `include_closed=true` only when closed sessions matter; route with the returned canonical selector.
- In the dashboard, open Relay, select a session, then use Associated work references to inspect, add, remove, or look up the same associations.