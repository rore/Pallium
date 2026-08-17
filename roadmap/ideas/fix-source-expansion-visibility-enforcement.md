---
id: fix-source-expansion-visibility-enforcement
title: Source-context expansion must enforce caller visibility per neighbor
status: queued
priority: high
commitment: uncommitted
---

## Summary

`pallium_expand_source` exposes a `visibility` control that is a **no-op**: the MCP client resolves it
but drops it before calling the service, so neighbor authorization runs with `query_visibility=None`
and falls into the permissive "same-container ⇒ visible" branch. A public lookup can land on a public
anchor and receive **private same-container neighbor turns**. Advertised privacy scoping is not
enforced on expansion.

## Why

Verified against the code (external review + independent confirmation):
- `core/service.py:1456-1467` — `get_source_context(...)` has **no `query_visibility` parameter**; all three `is_visible()` calls (anchor `:1504-1507`, neighbor `:1532-1535`, supported-memories `:1580-1583`) pass `query_visibility=None`.
- `app/mcp/server.py:187, 200-204` resolves `visibility` into `PalliumContext`, but `app/mcp/client.py:138-178` forwards only `container_ref` and `query_actor_ref` — `visibility` is dropped (contrast `_scope_params()` at `client.py:25-32`, which the `/query` path uses).
- `api/routes.py:672-693` — HTTP route also omits it.
- `core/visibility.py:51-53` — with `query_visibility` unset, any candidate in the same container is visible regardless of its own `private` flag.

Cross-container is still blocked (`core/service.py:1500`, `core/visibility.py:54-56`), so the defect is
"visibility scoping non-functional **within** the anchor's container," not "any container reads any
other." This is the Phase-0 governance requirement "per-neighbor visibility" shipped incomplete.

## In Scope

- Thread resolved query visibility through client → HTTP route → `get_source_context`, and pass it into
  every `is_visible()` call (anchor, each neighbor, supported memories).
- Each neighbor authorized independently on the full current query context (actor, visibility,
  container, sharing rules, forgotten/lifecycle state). An authorized anchor never confers access on
  adjacent records. Window/order stays correct after unauthorized neighbors are removed.

## Out of Scope

- Cross-container sharing/grant semantics (Phase 3).
- Redaction rules already applied on search (only extend to expansion where missing).

## Done When

1. Visibility-matrix E2E over an ordered public/private/actor-A/actor-B sequence: a public query never returns private neighbors; actor-A private query never returns actor-B private turns; an authorized public anchor does not widen neighbor access.
2. Identical authorization behavior verified on **both** MCP `pallium_expand_source` and direct HTTP expansion.
3. Lifecycle neighbors (forgotten, superseded, deleted-between-lookup-and-expansion) handled correctly; window size/order preserved after removals.
4. The "zero visibility violations" metric would now catch a same-container private leak (coordinate with `idea-visibility-violation-metric-completeness`).

## Notes

External-review register item 4 (severity High, privacy). Touches red `core/service.py` — clean-context
plan review required. Related: `add-source-context-expansion`, `add-raw-history-governance`.
