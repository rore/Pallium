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
historical lookup, fetch its surrounding thread context (neighbor turns) and the
derived memories it supports, so an agent can follow through on a promising hit.

## Why

The pull flow is `lookup → relevant prior work → optional source expansion →
continue`. Link-back exists today only from a `memory_object_id`
(`/memory/{id}/expand`); a raw `source_hit` gives a `source_item_id` that no tool
or endpoint accepts. Without source expansion, a raw hit is a dead-end excerpt —
the agent can't cheaply get enough surrounding context to act on it.

## In Scope

- a `GET /source/{id}/context` endpoint + `service.get_source_context` returning
  neighboring turns in the same `thread_ref` and the memories this source supports
  (reverse `supported_by`), visibility-enforced and redaction-aware (mirror
  `get_memory_expand`)
- expose expansion to agents (accept a `source_item_id` from a lookup result)

## Out of Scope

- the lookup tool and retrieval mode (separate P1 items)
- summarizing/packaging the expanded context (Phase 3 continuity work)
- cross-thread / cross-container expansion beyond the source's own thread

## Done When

1. Given a `source_item_id`, a caller can retrieve neighbor turns + supported
   memories, visibility-enforced.
2. The historical-lookup workflow can chain lookup → expand end to end.
3. Expansion honors visibility fail-closed (0 violations).

## Notes

Guarded paths: `api/`, `core/service.py` (red). Start with `/agent-workflow`.
Execution context: `docs/designs/015-vnext-historical-work-execution.md` (Phase 1).
