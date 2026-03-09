---
id: add-agent-event-contract-and-compact-query-results
title: Add the agent event contract and compact query results
status: done
priority: high
commitment: committed
milestone: Current
---

## Summary

Add a generic agent-event ingest contract with explicit correlation refs and compact source-hit query results for agent consumers.

## Why

Real agent runtimes emit atomic events and assistant artifacts, not clean thread-native documents. Pallium needs an explicit event contract and compact result shape before deeper memory features such as tiered consolidation.

## In Scope

- extend item ingest with explicit event refs such as thread, session, container, actor, source, role, and artifact kind
- store those refs as first-class source-item fields
- add structured query filters over the new refs
- return compact source-hit cards with excerpts and stable refs instead of raw full content
- validate the generic contract with message events and assistant artifacts in the simulation and tests

## Out of Scope

- collecting or hydrating threads from upstream systems
- full raw-content expansion endpoints
- connector-specific ingestion logic inside Pallium
- tiered memory or consolidation logic

## Done When

1. `POST /items` accepts atomic event metadata and stores it explicitly on source items.
2. `POST /query` can filter by thread, session, container, role, artifact kind, and source type.
3. `source_hit` results return compact excerpts plus stable refs, not full raw content.
4. End-to-end tests cover both message events and assistant artifact events.

## Notes

Sources: `docs/context/architecture.md`, `docs/context/lessons.md`, reference agent-runtime analysis (internal only)
