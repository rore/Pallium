---
id: build-structured-retrieval-foundation
title: Build the structured retrieval foundation
status: queued
priority: high
commitment: committed
milestone: Phase 3
---

## Summary

Build the first retrieval foundation around structured filters, relations, and lexical search, keeping embeddings optional and additive.

## Why

Retrieval quality will determine whether Pallium is useful. The project direction is structured-first and evidence-backed, so the first retrieval layer should reflect that before any semantic enhancement is added.

## In Scope

- structured filtering over core entities and metadata
- relation-aware retrieval where applicable
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

Sources: `roadmap/scope.md`, `docs/context/vision.md`, `roadmap/ideas/idea-optional-embedding-provider-support.md`
