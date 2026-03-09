---
id: implement-source-item-persistence-and-primitives
title: Implement source-item persistence and base primitives
status: done
priority: high
commitment: committed
milestone: Phase 1
---

## Summary

The first persistence layer for source items and the base primitives for annotations, relations, index entries, and durable memory objects are implemented.

## Why

The project needed durable mechanics before the generic core could be proven in a working slice.

## In Scope

- persist normalized source items
- add the base persistence model for annotations, relations, index entries, and memory objects
- keep the implementation generic and deterministic
- keep the first code compatible with later semantic-layer and retrieval work

## Out of Scope

- connector implementations
- tiered-memory consolidation
- advanced retrieval logic beyond what the first slice requires

## Done When

1. Source items can be stored durably.
2. Base primitives exist for annotations, relations, index entries, and memory objects.
3. The storage model remains compatible with Pallium's generic-core direction.

## Notes

Status: completed with a SQLite-backed storage provider behind the storage abstraction.

Sources: roadmap/scope.md, docs/context/architecture.md
