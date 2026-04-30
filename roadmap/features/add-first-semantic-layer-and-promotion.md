---
id: add-first-semantic-layer-and-promotion
title: Add the first semantic layer and promotion flow
status: done
priority: high
commitment: committed
milestone: Phase 2
---

## Summary

The first reference semantic layer now turns ingested source items into a summary annotation and a promoted durable memory object.

## Why

The generic core only becomes useful once it can host at least one semantic layer that demonstrates how meaning is added without collapsing the generic boundary.

## In Scope

- define the first semantic layer boundary against the generic core
- define the first typed annotation and memory-object schemas through schema metadata
- implement promotion rules from source items into durable memory objects
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

Status: completed with a deterministic demo plugin that creates summary annotations and turn_summary memory objects.

Sources: roadmap/scope.md, docs/context/vision.md, docs/context/architecture.md
