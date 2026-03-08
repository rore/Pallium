---
id: define-core-model-and-api-contracts
title: Define the core model and API contracts
status: queued
priority: high
commitment: committed
milestone: Phase 0
---

## Summary

Refine the architecture notes into implementation-ready decisions for the minimal core entities, lifecycle states, and write and query API contracts.

## Why

Pallium is still at the point where the quality of the first model decisions will shape the entire generic core, so this needs to become explicit before code scaffolding spreads.

## In Scope

- define the minimal core entities and lifecycle states
- define write API contracts for normalized source-item ingestion
- define query API contracts for evidence-backed retrieval
- keep the core generic and semantic-layer meaning additive

## Out of Scope

- connector-first expansion
- domain-specific core tables for decisions, incidents, or requirements
- tiered-memory implementation itself

## Done When

1. The minimal core entities and lifecycle states are explicit.
2. The first write and query API contracts are documented clearly enough to scaffold against.
3. The contracts preserve Pallium's generic-core and evidence-backed retrieval principles.

## Notes

Sources: `roadmap/scope.md`, `docs/context/architecture.md`, `docs/designs/002-memory-model.md`
