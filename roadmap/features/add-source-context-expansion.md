---
id: add-source-context-expansion
title: Source-centric context expansion
status: queued
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
- **per-neighbor visibility checks**: each neighbor turn is enforced individually
  (a thread can be mixed-visibility) — never widen to the whole thread
- a **bounded expansion window** (neighbor count + token limit) so expansion can't
  return unbounded raw context
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

## Notes

Guarded paths: `api/`, `core/service.py` (red). Start with `/agent-workflow`.
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 1).
