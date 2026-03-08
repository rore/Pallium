---
id: add-first-semantic-layer-and-promotion
title: Add the first semantic layer and promotion flow
status: queued
priority: high
commitment: committed
milestone: Phase 2
---

## Summary

Add the first reference semantic layer that turns base annotations into durable memory objects and makes those objects retrievable as evidence-backed agent memory.

## Why

The generic core only becomes useful once it can host at least one semantic layer that demonstrates how meaning is added without collapsing the generic boundary.

## In Scope

- define the first semantic layer boundary against the generic core
- define the first typed annotation and memory-object schemas through schema metadata
- implement promotion rules from annotations or candidates into durable memory objects
- support retrieval packaging for the first semantic layer

## Out of Scope

- multi-use-case plugin framework maturity beyond what v1 needs
- broad connector expansion
- tiered-memory consolidation itself

## Done When

1. The first semantic layer can process base source items and produce durable memory objects.
2. The promoted objects remain evidence-backed and queryable through the core retrieval path.
3. The semantic layer stays additive and does not force domain-specific core tables.

## Notes

Sources: `roadmap/scope.md`, `docs/context/vision.md`, `docs/context/architecture.md`
