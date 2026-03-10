---
id: idea-optional-reranker-support
title: Optional reranker support
status: queued
priority: low
commitment: uncommitted
milestone: Idea
---

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
