---
id: add-conversation-thread-aggregate
title: Add conversation thread aggregate capability
status: done
priority: high
commitment: committed
milestone: Next
---

## Summary

Add a reusable thread-specific capability that groups atomic source items by `container_ref + thread_ref` and lets `agent_conversation_memory` produce a retrievable `thread_summary` memory object.

## Why

Threads are a natural conversation boundary for agent-mediated memory. Pallium needs a thread-level unit before tiered memory so later consolidation works over meaningful conversation summaries instead of only raw event fragments.

## In Scope

- keep ingest atomic at the `SourceItem` level
- add a reusable thread aggregation capability over `container_ref + thread_ref`
- let `agent_conversation_memory` use it to build `thread_summary`
- carry forward active `decision` and `investigation_outcome` conclusions into the thread summary
- supersede older thread summaries as the thread evolves
- keep thread summaries queryable through the normal memory path

## Out of Scope

- generic correlation-key aggregation for all future aggregate types
- session/container aggregates beyond the thread-specific capability
- new public APIs or result kinds
- tiered cross-thread clustering

## Done When

1. Multiple events in the same thread produce one active `thread_summary` memory object.
2. New thread events rebuild and supersede the previous thread summary.
3. Thread summaries are evidence-backed by all included source items.
4. Thread summaries can carry forward active `decision` and `investigation_outcome` conclusions.
5. At least one recurring-question scenario can return `thread_summary` as part of the useful memory context.

## Notes

This is the first reusable capability between Pallium's generic core and semantic packages. It is thread-specific by design; broader aggregate engines can come later if they are needed.
