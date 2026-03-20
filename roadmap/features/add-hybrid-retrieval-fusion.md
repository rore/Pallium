---
id: add-hybrid-retrieval-fusion
title: Add hybrid retrieval with RRF fusion
status: done
priority: high
commitment: committed
milestone: Done
lane: retrieval-semantic-substrate
---

## Summary

Combine Pallium's lexical and vector retrieval paths with explicit hybrid fusion
so technical exact matches and paraphrased prior reasoning can be ranked
together in one result set for the bounded durable memory lane.

## Why

Technical memory corpora need both lexical precision and semantic recall. Once
Pallium has bounded vector retrieval for durable memory, it needs an explicit
fusion step so lexical and vector paths reinforce each other instead of
competing as separate diagnostic paths.

The first production-quality hybrid path should stay tightly bounded:

- scope filtering first
- kind filtering first
- subject/workstream filtering when anchors exist
- policy and constraint lookup still handled separately and deterministically

## In Scope

- run lexical and vector retrieval over the same already-bounded candidate
  space after scope, kind, and subject/workstream narrowing
- fuse ranked results using Reciprocal Rank Fusion (RRF) as the initial strategy
- surface enough retrieval trace data to explain whether a result came from lexical retrieval, vector retrieval, or fusion
- preserve compact evidence-backed result packaging for downstream callers
- leave room for plugin-specific weighting and filtering policies later
- treat the first hybrid path as the production retrieval shape for the durable
  memory lane once vector retrieval exists
- preserve lexical precision for exact identifiers, jargon, repo names,
  ticket-like IDs, and auth/tool surfaces while vectors add concept and
  paraphrase recall
- add validation that pressure-tests exact-match plus paraphrase coexistence in
  the same bounded retrieval path

## Out of Scope

- weighted raw-score blending as the initial fusion strategy
- reranking
- removing the ability to inspect lexical-only or vector-only behavior in diagnostics
- replacing tiered memory as the main product-value lever
- using hybrid fusion as the main path for constraint or policy lookup
- relaxing scope/kind/subject boundaries just because a semantic hit exists

## Done When

1. Pallium can run lexical and vector retrieval together and return one fused
   result set over the same bounded durable-memory candidate space.
2. Fusion uses RRF rather than naive score blending.
3. Both `SourceItem` and `MemoryObject` remain retrievable through the fused path.
4. Retrieval traces make it possible to explain which retrieval modes contributed to a returned hit.
5. The first hybrid path preserves deterministic policy/constraint lookup
   outside the fused durable-memory lane.
6. Validation shows the fused path improves exact-term plus paraphrase recall
   together rather than only semantic similarity in isolation.

## Notes

RRF is the intended starting point because it is robust to mismatched lexical and vector score scales and needs less tuning than weighted fusion.

Recommended sequencing:

1. land bounded vector retrieval for the durable memory lane first
2. then add hybrid fusion quickly so lexical and vector retrieval stop acting as
   separate long-lived retrieval modes
3. keep vector-only and lexical-only diagnostics available even after fusion is
   added

Sources: `docs/designs/005-hybrid-retrieval-guidance.md`, `docs/context/architecture.md`
