---
id: add-vector-retrieval-provider
title: Add bounded vector retrieval for durable memory lanes
status: queued
priority: high
commitment: committed
milestone: Later
lane: retrieval-semantic-substrate
---

## Summary

Add a bounded vector retrieval provider and semantic indexing for selected
durable-memory text views so retrieval can cover paraphrase and conceptual
similarity, not only exact lexical overlap.

The first slice should treat vector retrieval as the semantic candidate-
generation layer for durable memory lanes, not as a broad replacement for
lexical search, policy lookup, or short-term local state.

## Why

Pallium will likely need to retrieve both exact technical evidence and fuzzier
prior reasoning across threads and sessions. Lexical retrieval already covers
the first part.

Recent research and roadmap shaping now point to a clearer position:

- vector retrieval is not the next stabilization bottleneck
- but once the write-time envelope, constraint lane, and subject/workstream
  filtering exist, it becomes the expected semantic retrieval substrate for the
  durable memory lane
- leaving it deferred too long would keep too much pressure on lexical
  heuristics, manual anchors, or query-time semantic escalation for ordinary
  paraphrase and concept recall

## In Scope

- add a vector retrieval provider boundary
- support semantic indexing for selected `SourceItem` and `MemoryObject` text
  views inside the durable memory lane
- limit the first retrieval targets to durable memory kinds such as:
  - `finding`
  - `episode`
  - `summary`
  - optional later `next_step`
- make vector retrieval run only after hard scope and typed-lane narrowing
- prefer retrieval-oriented canonical text fields where available rather than
  embedding every possible raw text view by default
- record embedding provider/model/version metadata
- keep vector retrieval optional and additive to the existing lexical baseline
- preserve compatibility with local-first deployment and replaceable providers
- keep vector-only diagnostics available before fusion is added
- add replay or benchmark proof that vector retrieval improves paraphrase or
  cross-thread recall in the durable memory lane

## Out of Scope

- making vector search the only retrieval path
- using vector retrieval as the primary mechanism for `constraint` or policy
  lookup
- using vector retrieval as the main path for short-term local-session recall
- fusion policy
- reranking
- broad automatic embedding of every possible artifact without selection rules
- using vector retrieval as a substitute for subject/workstream filtering

## Done When

1. Pallium can build and query semantic indexes for selected text views.
2. Both `SourceItem` and `MemoryObject` remain valid vector retrieval targets
   within the bounded durable memory lane.
3. Embedding provider/model/version metadata is stored alongside semantic index entries.
4. The vector retrieval path can be exercised independently for diagnostics before fusion is added.
5. Vector retrieval is clearly bounded by scope and typed-lane filtering rather
   than operating as an unconstrained semantic fallback.
6. Replay or benchmark coverage demonstrates improved paraphrase or cross-thread
   recall in the durable memory lane.

## Notes

This slice adds semantic retrieval capability, but it does not replace the
current structured-plus-lexical foundation.

Recommended sequencing:

1. land the write-time envelope, kind-aware filtering, first-class constraint
   lane, and subject/workstream anchors first
2. then add bounded vector retrieval for the durable memory lane
3. follow it quickly with hybrid fusion rather than leaving vector and lexical
   retrieval as separate long-lived diagnostic paths

Sources: `docs/designs/005-hybrid-retrieval-guidance.md`, `docs/context/vision.md`
