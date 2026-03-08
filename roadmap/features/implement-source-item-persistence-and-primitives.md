---
id: implement-source-item-persistence-and-primitives
title: Implement source-item persistence and base primitives
status: queued
priority: high
commitment: committed
milestone: Phase 1
---

## Summary

Implement the first persistence layer for source items and the base primitives needed for annotations, relations, index entries, and durable memory objects.

## Why

The project cannot move from design to execution until the generic core has its first durable mechanics. This is the first code-bearing step that proves the model is real.

## In Scope

- persist normalized source items
- add the base persistence model for annotations, relations, index entries, and memory objects
- keep the implementation generic and deterministic
- keep the first code compatible with later semantic-layer and retrieval work

## Out of Scope

- connector implementations
- tiered-memory consolidation
- advanced retrieval logic beyond what the primitives require

## Done When

1. Source items can be stored durably.
2. Base primitives exist for annotations, relations, index entries, and memory objects.
3. The storage model remains compatible with Pallium's generic-core direction.

## Notes

Sources: `roadmap/scope.md`, `docs/context/architecture.md`
