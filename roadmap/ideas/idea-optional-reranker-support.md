---
id: idea-optional-reranker-support
title: Optional reranker support
status: superseded
priority: low
commitment: uncommitted
milestone: Idea
resolved_by: improve-session-history-search-quality
---

> **Superseded 2026-09-22 -> `improve-session-history-search-quality`.**
> The local cross-encoder/late-interaction exploration makes reranking concrete
> enough for a candidate-preserving experiment, but does not justify a separate
> implementation item. The committed search-quality investigation now owns the
> preflight, fixed-candidate comparison, downstream gate, and any later promotion
> of the smallest optional reranking seam.

## Summary

Add reranking as an optional second-stage retrieval capability after hybrid retrieval is in place.

## Why

Reranking may improve the top of the fused candidate set, but it should remain optional and should not block the first hybrid retrieval slices.

## In Scope

- reranker extension point in the retrieval layer
- reranking of top fused candidates only
- keeping reranking explainable and optional

## Out of Scope

- making reranking a requirement for base retrieval quality
- introducing a heavy second-stage model before hybrid retrieval exists
- hiding the underlying lexical/vector/fusion behavior

## Done When

1. The idea is concrete enough to become a committed feature if hybrid retrieval proves the need.
2. The retrieval architecture leaves room for reranking without redesign.

## Notes

Sources: `docs/designs/005-hybrid-retrieval-guidance.md`
