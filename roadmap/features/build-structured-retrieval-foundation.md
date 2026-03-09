---
id: build-structured-retrieval-foundation
title: Build the structured retrieval foundation
status: in_progress
priority: high
commitment: committed
milestone: Phase 3
---

## Summary

Build the next retrieval layer around structured filters, explicit relation-aware retrieval, and lexical search, keeping embeddings optional and additive.

## Why

The first slice already proves lexical retrieval and evidence lookup. The next step is to strengthen retrieval quality without breaking the generic-core and replaceable-provider direction.

## In Scope

- structured filtering over core entities and metadata
- relation-aware retrieval beyond basic evidence resolution
- lexical retrieval over selected text views
- retrieval packaging that stays compact and cited

## Out of Scope

- embedding-only retrieval
- provider lock-in through the retrieval foundation
- global fuzzy search as the only retrieval path

## Done When

1. The system can answer retrieval requests with structured and lexical signals alone.
2. The retrieval contract stays compatible with optional semantic enhancement later.
3. Results remain evidence-backed and compact enough for downstream agent use.

## Notes

Status: next active engineering focus after the first executable slice.

Sources: roadmap/scope.md, docs/context/vision.md, roadmap/ideas/idea-optional-embedding-provider-support.md
