---
id: add-tiered-memory-extension
title: Add the optional tiered-memory extension
status: queued
priority: medium
commitment: committed
milestone: Later
---

## Summary

Add the first bounded consolidation flow that periodically creates higher-level evidence-backed memory objects from lower-level memories.

## Why

Tiered memory is one of the most differentiated long-term ideas in Pallium, but it should arrive after the base memory engine and first semantic layer are stable.

## In Scope

- add a bounded consolidation path over lower-level memory objects
- produce at least one higher-level memory type such as `pattern_memory`
- keep consolidated objects evidence-backed and linked to lower-level support
- make consolidated objects queryable through the normal retrieval model

## Out of Scope

- global autonomous clustering of everything
- replacing lower-level memory with summaries
- deep multi-level hierarchy
- opaque synthesis without evidence links

## Done When

1. A bounded consolidation job produces at least one useful higher-level memory object type.
2. Consolidated objects link back to supporting lower-level evidence.
3. Retrieval can include consolidated memory without breaking direct-memory retrieval.

## Notes

Sources: `roadmap/scope.md`, `docs/context/architecture.md`, `docs/designs/003-tiered-memory-extension.md`
