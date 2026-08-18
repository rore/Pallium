---
id: fix-vector-source-only-starvation
title: Vector source-only retrieval can be starved by derived memories
status: queued
priority: medium
commitment: uncommitted
---

> **Sequencing note 2026-08-18.** This is a *supporting* fix, not standalone urgent work: land it
> **before** any multilingual / lexically-cold corpus evaluation in the real-corpus decision experiment
> (where the lexical leg can't rescue source coverage). Absent that, the default hybrid stack's lexical
> push-down already guarantees source coverage, so it does not block measurement integrity.

## Summary

Source-only vector retrieval can return fewer than K raw results — or none — even when eligible raw
turns exist. The vector leg queries a **mixed** ANN index, overfetches by a **fixed** `limit*8`, then
discards non-source hits *after* truncation. If enough high-similarity derived objects fill the window,
raw turns just outside it are lost. The lexical leg does not have this problem (it filters `target_kind`
in SQL before the LIMIT), and the design deliberately relies on lexical for the source-coverage
guarantee — so pure-vector deployments or lexically-cold queries are exposed.

## Why

Verified against the code:
- `retrieval/vector.py:92` — `search_k = limit * 8 if target_kind is not None else limit * 4` (fixed); `:93` `index.search(..., k=search_k)` truncates before kind-filter; `:135-136` discards mismatched kinds inside hydration; `:239-240` stops at `limit`. Comment at `:87-91` admits it relies on the lexical leg.
- `retrieval/lexical.py:111-120` → `storage/sqlite_search.py:57-61` — `AND target_kind = :target_kind` applied in SQL WHERE before `ORDER BY score LIMIT` (starvation-proof; comment `:43-49`).

Especially matters for paraphrase/semantic/multilingual retrieval where lexical may not rescue results.

## In Scope

- A real source-coverage guarantee for vector source-only mode, preferred order: (1) filtered/namespaced
  ANN by target kind; (2) separate raw-source vector index; (3) adaptive overfetch until enough permitted
  raw results are found or the index is exhausted. Fixed-factor overfetch is not a correctness guarantee.

## Out of Scope

- Reranker work (`idea-optional-reranker-support`).
- Fusion weight tuning.

## Done When

1. Starvation test (must fail under current `limit*8`): ≥`8*K+1` high-ranked derived objects + ≥K eligible raw sources at slightly lower vector scores, lexical disabled → source-only vector search returns K raw results, no derived, correct raw ordering.
2. Backend parity: lexical-only, vector-only, hybrid — target-kind filtering enforced before effective top-K in all modes.
3. Boundaries: 0 / <K / =K / >K raw results; all raw filtered by visibility; forgotten raw; multilingual paraphrases; several containers sharing one embedding index.

## Notes

External-review register item 7 (Medium–High; verified Medium/P2 — mitigated by the lexical guarantee in
the default hybrid stack). Related: `add-vector-retrieval-provider`, `add-hybrid-retrieval-fusion`.
