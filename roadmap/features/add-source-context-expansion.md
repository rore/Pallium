---
id: add-source-context-expansion
title: Source-centric context expansion
status: done
priority: high
commitment: committed
milestone: pallium-vnext-p1
---

## Summary

Add a source-centric expansion path: given a raw `source_item_id` returned by a
historical lookup, fetch its surrounding thread context (neighbor raw turns) so an
agent can follow through on a promising hit. The linked derived memories the source
supports are available **only as an explicit opt-in**, kept separate from the raw
expansion payload.

## Why

The pull flow is `lookup → relevant prior work → optional source expansion →
continue`. Link-back exists today only from a `memory_object_id`
(`/memory/{id}/expand`); a raw `source_hit` gives a `source_item_id` that no tool
or endpoint accepts. Without source expansion, a raw hit is a dead-end excerpt —
the agent can't cheaply get enough surrounding context to act on it. The expansion
must stay *raw* by default: if it silently folds in derived memories, the RAW
production baseline gets contaminated by the very representation the continuous
eval (`idea-raw-derived-hybrid-shadow-eval`) is trying to measure against.

## In Scope

- a `GET /source/{id}/context` endpoint + `service.get_source_context` returning
  neighboring raw turns in the same `thread_ref`, visibility-enforced and
  redaction-aware (mirror `get_memory_expand`)
- **exclude forgotten source turns** (both the anchor `source_item_id` and each
  neighbor): `get_source_context` is a direct-fetch path that does NOT route
  through `matches_filters`, so — exactly like the `get_memory_expand` skip added
  in `add-raw-history-governance` — it must check the `forgotten` marker per turn
  and omit forgotten turns fail-closed; a forgotten anchor yields no context
- **per-neighbor visibility checks**: each neighbor turn is enforced individually
  (a thread can be mixed-visibility) — never widen to the whole thread
- a **bounded expansion window** (neighbor count + token limit) so expansion returns
  a bounded neighborhood of surrounding turns, not an unbounded walk of the transcript
  (the bound is a governance property, not just a UI limit)
- accept and record a `parent_lookup_id` so an expansion links back to the lookup
  that produced the `source_item_id` (feeds the measurement event chain)
- return the derived memories this source supports (reverse `supported_by`) only
  behind an explicit opt-in parameter, as a clearly separate field — never mixed
  into the raw-turn payload by default
- expose expansion to agents (accept a `source_item_id` from a lookup result)

## Out of Scope

- the lookup tool and retrieval mode (separate P1 items)
- summarizing/packaging the expanded context (Phase 2 continuity work)
- cross-thread / cross-container expansion beyond the source's own thread
- mixing derived memories into the default raw payload (they are opt-in + separate)

## Done When

1. Given a `source_item_id`, a caller can retrieve neighbor raw turns within a
   bounded window, with **per-neighbor** visibility enforcement; supported memories
   are returned only when explicitly requested and as a separate field.
2. The historical-lookup workflow can chain lookup → expand end to end, with
   `parent_lookup_id` linking expansion to its lookup.
3. Expansion honors visibility fail-closed (0 violations) per neighbor, and respects
   the expansion window/token bound.
4. Forgotten source turns (per `add-raw-history-governance`) are never returned by
   `get_source_context` — anchor or neighbor — verified fail-closed.

## Notes

Governance note (2026-08-13): the per-neighbor visibility, bounded window/token cap,
and redaction listed above ARE the P0 raw-history governance mechanics for the
expansion path — `add-raw-history-governance` was re-scoped to raw-turn forgetting and
delegates these to this item. In addition, this path must **carry forward the
forgotten-source gate**: `get_source_context` fetches turns directly (not via
`matches_filters`), so it must replicate the per-turn `forgotten` skip that
`add-raw-history-governance` added to `get_memory_expand`.

The raw-read access audit — recording *which source item ids* an expansion returned —
is the exposed-source-ids recording deferred from `add-historical-lookup-funnel-telemetry`
(build once; serves both the reuse funnel and the raw-read audit). Note this is NOT the
same as `parent_lookup_id`: `parent_lookup_id` only correlates an expansion to its
triggering lookup; it does not identify the source items returned. Reference the shared
telemetry contract for the exposed-source-ids audit rather than treating
`parent_lookup_id` as that audit.

Guarded paths: `api/`, `core/service.py` (red). Start with `/agent-workflow`.
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 1).
