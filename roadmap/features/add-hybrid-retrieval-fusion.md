---
id: add-hybrid-retrieval-fusion
title: Add hybrid retrieval with RRF fusion
status: queued
priority: high
commitment: committed
milestone: Later
---

## Summary

Combine Pallium's lexical and vector retrieval paths with explicit hybrid fusion so technical exact matches and paraphrased prior reasoning can be ranked together in one result set.

## Why

Technical memory corpora need both lexical precision and semantic recall. Once Pallium has both retrieval modes, it needs an explicit fusion step so they reinforce each other instead of competing as separate diagnostic paths.

## In Scope

- run lexical and vector retrieval over the same structured candidate space
- fuse ranked results using Reciprocal Rank Fusion (RRF) as the initial strategy
- surface enough retrieval trace data to explain whether a result came from lexical retrieval, vector retrieval, or fusion
- preserve compact evidence-backed result packaging for downstream callers
- leave room for plugin-specific weighting and filtering policies later

## Out of Scope

- weighted raw-score blending as the initial fusion strategy
- reranking
- removing the ability to inspect lexical-only or vector-only behavior in diagnostics
- replacing tiered memory as the main product-value lever

## Done When

1. Pallium can run lexical and vector retrieval together and return one fused result set.
2. Fusion uses RRF rather than naive score blending.
3. Both `SourceItem` and `MemoryObject` remain retrievable through the fused path.
4. Retrieval traces make it possible to explain which retrieval modes contributed to a returned hit.

## Notes

RRF is the intended starting point because it is robust to mismatched lexical and vector score scales and needs less tuning than weighted fusion.

Sources: `docs/designs/005-hybrid-retrieval-guidance.md`, `docs/context/architecture.md`
