---
id: add-vector-retrieval-provider
title: Add bounded vector retrieval for durable memory lanes
status: done
priority: high
commitment: committed
milestone: Done
lane: retrieval-semantic-substrate
---

## Summary

Add a bounded vector retrieval provider and semantic indexing for selected
durable-memory text views so retrieval can cover paraphrase and conceptual
similarity, not only exact lexical overlap.

The first slice treats vector retrieval as a diagnostic and benchmarkable
semantic candidate-generation layer for the durable memory lane, not as a
broad replacement for lexical search, policy lookup, or short-term local
state. Vector results appear in `/query/debug` trace and benchmark harnesses
only. The production `/query` path remains lexical-only until the follow-on
`add-hybrid-retrieval-fusion` feature activates fused results.

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
- support semantic indexing for selected `MemoryObject` text views inside the
  durable memory lane
- first-slice retrieval targets limited to durable memory kinds:
  - `decision`
  - `investigation_outcome`
  - `thread_summary`
  - `task_checkpoint`
  - `pattern_memory`
  - `continuity_memory`
- vector retrieval runs within scope and visibility filtering; typed-lane
  narrowing happens in the package-owned routing layer afterward (same as
  lexical retrieval today)
- prefer retrieval-oriented canonical text fields where available rather than
  embedding every possible raw text view by default
- record embedding provider/model/version metadata
- keep vector retrieval optional and additive to the existing lexical baseline
- preserve compatibility with local-first deployment and replaceable providers
- keep vector-only diagnostics available before fusion is added
- add benchmark proof that vector retrieval improves paraphrase or
  cross-thread recall in the durable memory lane

## Deferred to Later Slices

- `SourceItem` as a vector retrieval target — implemented as plugin-owned
  embedding in `add-hybrid-retrieval-fusion` (messages + assistant outputs
  >= 40 chars, persisted before semantic processing)
- fusion policy, composite retrieval, routing score integration (belongs in
  `add-hybrid-retrieval-fusion`)
- API-based embedding providers (first slice is local-only via fastembed)
- secondary enrichment vector entries
- `constraint_memory` as a vector retrieval target

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

1. Pallium can build and query semantic indexes for selected `MemoryObject`
   text views.
2. Embedding provider/model/version metadata is stored alongside semantic
   index entries.
3. The vector retrieval path can be exercised independently for diagnostics
   via `/query/debug` trace before fusion is added.
4. Vector retrieval is clearly bounded by scope and visibility filtering
   rather than operating as an unconstrained semantic fallback.
5. Benchmark coverage demonstrates improved paraphrase or cross-thread recall
   in the durable memory lane compared to lexical-only retrieval.
6. `SourceItem` vector targets remain architecturally valid but are deferred
   to a later slice.

## Notes

This slice adds semantic retrieval capability, but it does not replace the
current structured-plus-lexical foundation. Vector results are diagnostic-only
in this feature; production query-path benefit lands with
`add-hybrid-retrieval-fusion`.

Recommended sequencing:

1. land the write-time envelope, kind-aware filtering, first-class constraint
   lane, and subject/workstream anchors first
2. then add bounded vector retrieval for the durable memory lane
3. follow it quickly with hybrid fusion rather than leaving vector and lexical
   retrieval as separate long-lived diagnostic paths

Sources: `docs/designs/005-hybrid-retrieval-guidance.md`, `docs/context/vision.md`
