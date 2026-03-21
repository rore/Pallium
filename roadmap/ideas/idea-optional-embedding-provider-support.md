---
id: idea-optional-embedding-provider-support
title: Optional embedding provider support
status: done
priority: low
commitment: uncommitted
milestone: Idea
resolved_by: add-vector-retrieval-provider, add-hybrid-retrieval-fusion
---

## Summary

Support embeddings as an optional retrieval layer instead of the whole retrieval model.

## Why

Embeddings may be useful, but Pallium's intended shape is structured-first and local-first, so this should stay additive and optional.

## In Scope

- optional provider abstraction for embeddings
- hybrid retrieval where embeddings sit behind structured and lexical signals
- preserving the ability to swap model choices without reshaping the core

## Out of Scope

- embedding-only retrieval
- provider lock-in
- making semantic retrieval the only foundation of the system

## Done When

1. The idea is concrete enough to commit as a roadmap feature.
2. The provider abstraction stays compatible with Pallium's generic-core and local-first principles.

## Notes

Sources: `docs/context/vision.md`, `docs/designs/002-memory-model.md`
