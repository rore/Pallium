---
id: build-structured-retrieval-foundation
title: Build the structured retrieval foundation
status: done
priority: high
commitment: committed
milestone: Phase 3
---

## Summary

The retrieval layer now returns mixed results across promoted memory and raw source evidence while keeping evidence links explicit.

## Why

The first slice already proved lexical retrieval and evidence lookup. This step strengthened retrieval quality without breaking the generic-core and replaceable-provider direction.

## In Scope

- structured retrieval preparation through indexing both source and memory targets
- mixed lexical retrieval over source items and memory objects
- explicit result-kind packaging that stays compact and cited

## Out of Scope

- embedding-only retrieval
- provider lock-in through the retrieval foundation
- global fuzzy search as the only retrieval path

## Done When

1. The system can answer retrieval requests with mixed memory and source results.
2. The retrieval contract stays compatible with optional semantic enhancement later.
3. Results remain evidence-backed and compact enough for downstream agent use.

## Notes

Status: completed and verified with pytest and a live temporary-database HTTP run.

Sources: roadmap/scope.md, docs/context/vision.md, roadmap/ideas/idea-optional-embedding-provider-support.md
