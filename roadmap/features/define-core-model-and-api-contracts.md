---
id: define-core-model-and-api-contracts
title: Define the core model and API contracts
status: done
priority: high
commitment: committed
milestone: Phase 0
---

## Summary

The first walking skeleton now has an explicit core model and a minimal write and query contract implemented in code.

## Why

These decisions shaped the generic core before the scaffold spread into multiple implementation areas.

## In Scope

- define the minimal core entities and lifecycle-adjacent artifact model
- define write API contracts for normalized source-item ingestion
- define query API contracts for evidence-backed retrieval
- keep the core generic and semantic-layer meaning additive

## Out of Scope

- connector-first expansion
- domain-specific core tables for decisions, incidents, or requirements
- tiered-memory implementation itself

## Done When

1. The minimal core entities are explicit in the implementation.
2. The first write and query API contracts are implemented and exercised.
3. The contracts preserve Pallium's generic-core and evidence-backed retrieval principles.

## Notes

Status: completed in the first executable slice.

Sources: roadmap/scope.md, docs/context/architecture.md, docs/designs/002-memory-model.md
