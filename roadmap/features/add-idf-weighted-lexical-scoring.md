---
id: add-idf-weighted-lexical-scoring
title: Add IDF-weighted lexical scoring
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Replace raw token-count scoring in lexical search with IDF (Inverse Document Frequency) weighting. Words that appear in most documents score near zero; words that appear in few documents score high. Language-independent — the corpus teaches itself what's common.

## Why

Lexical search scores by counting matching tokens — every word is worth 1 point. A query like "how is the weather today" matches a vector DB summary on the word "the" (score=1). The routing layer amplifies this (×10 + layer weight of 80-150), producing a high enough score to trigger injection of completely off-topic memories.

Observed in chat-lite: user asks about weather → 3 vector DB thread_summaries injected. User says "i'm a winter kind of guy" → vector DB constraint_memory + thread_summary + interest injected.

## In Scope

- IDF-weighted scoring in `storage/sqlite_search.py` using Lucene-smoothed formula
- Cold start guard: fall back to raw count when corpus < 5 entries
- Integer score preservation: IDF sums scaled by `_IDF_SCORE_SCALE = 1` and rounded
- Test for IDF scoring behavior
- Injection-level retrieval relevance floor: when composite retrieval is active, suppress injection if no candidate has `lexical_score >= INJECTION_RETRIEVAL_RELEVANCE_FLOOR` (default 2). This closes the gap where routing layer weights (70-490) drowned out low IDF scores via the scoring formula. The raw IDF score is now propagated through RRF fusion as `lexical_score` on `QueryResultItem`.

## Out of Scope

- Full BM25 (TF saturation, length normalization) — current matching is binary
- FTS5 migration — separate scaling investigation
- Container-ref pre-filtering in SQL — separate scaling investigation
- Stopword lists — IDF makes them unnecessary

## Done When

1. A query with only common-word overlap (e.g., "the") scores significantly lower than domain-specific overlap
2. Off-topic memories (vector DB summaries for a weather query) score near zero in lexical retrieval
3. With composite retrieval active, queries with zero lexical overlap cannot trigger injection regardless of routing layer weights
4. Existing test suite passes with no regressions
