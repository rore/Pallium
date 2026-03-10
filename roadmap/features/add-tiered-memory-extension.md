---
id: add-tiered-memory-extension
title: Prove user value with the first tiered-memory layer
status: queued
priority: high
commitment: committed
milestone: Next
---

## Summary

Add the first bounded consolidation flow that creates a higher-level evidence-backed memory object from lower-level memories so recurring questions can be answered from one compact pattern instead of many raw items.

## Why

Pallium starts to become clearly more valuable than raw retrieval-and-synthesis when it can return a learned higher-level pattern that a downstream agent would not reliably or efficiently reconstruct from source search every time.

## In Scope

- add a bounded consolidation path over lower-level memory objects
- produce at least one higher-level memory type such as `pattern_memory`
- keep consolidated objects evidence-backed and linked to lower-level support
- make consolidated objects queryable through the normal retrieval model
- show at least one recurring-question flow where consolidated memory reduces noisy low-level retrieval

## Out of Scope

- global autonomous clustering of everything
- replacing lower-level memory with summaries
- deep multi-level hierarchy
- opaque synthesis without evidence links
- broad productization of many consolidation types in one step

## Done When

1. A bounded consolidation job produces at least one useful higher-level memory object type.
2. Consolidated objects link back to supporting lower-level evidence.
3. Retrieval can include consolidated memory without breaking direct-memory retrieval.
4. At least one concrete recurring-question example is documented where the downstream agent can use one consolidated memory object plus evidence instead of many low-level items.

## Notes

Sources: `roadmap/scope.md`, `docs/context/architecture.md`, `docs/designs/003-tiered-memory-extension.md`
