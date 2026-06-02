---
id: add-work-ref-cross-surface-continuity
title: Work reference — cross-surface work continuity
status: done
priority: medium
commitment: committed
milestone: Done
---

## Summary

Add a `work_refs` structural signal — a multi-valued list of durable
external work identifiers (Jira keys, GitHub issue/PR numbers, incident
IDs) — extracted from item content and used as an additional affinity
signal at retrieval and packaging time. Lets memories from different
threads and containers be recognized as being about the same piece of
work without requiring a project management layer inside Pallium.

## Why

The existing scoping model (`container_ref`, `thread_ref`) works when a
piece of work lives in one thread. Real agent work spans surfaces:
discussions move between DMs and channels, investigations span days and
threads, ticket IDs appear in tool summaries. Without a structural
work-identity signal, the routing pipeline can only fall back to
semantic/lexical similarity, and packaging actively prevents
cross-thread surfacing unless `thread_ref`s overlap.

## In Scope

- `work_refs: list[str]` field on items, queries, and derived memory
- Language-neutral extraction from content; optional caller-provided
  hint
- Casefold + trim normalization (Unicode-safe, no ASCII assumption)
- Use as affinity signal in routing and cross-thread packaging,
  alongside (not replacing) container/thread scoping
- Public surfaces: `POST /items`, `/query`, `/item-and-query`,
  `pallium_work_refs` runtime hint

## Out of Scope

- A task graph or project management layer
- Replacing `container_ref` / `thread_ref` visibility rules
- Format-specific identifier handling for every external system

## Done When

1. Items, queries, and derived memories carry `work_refs`.
2. Routing and packaging use `work_refs` as an affinity signal for
   cross-thread continuity.
3. Public API and agent integration documents `work_refs` end-to-end.

## Notes

Shipped. Design lives in
[docs/designs/013-work-ref-cross-surface-continuity.md](../../docs/designs/013-work-ref-cross-surface-continuity.md).
This roadmap item was originally tracked only on the board; the file is
backfilled to keep the roadmap audit trail consistent with peer items.
