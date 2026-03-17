---
id: add-write-time-contextual-enrichment-and-background-consolidation
title: Write-time contextual enrichment and background consolidation
status: queued
priority: high
commitment: committed
milestone: Later
lane: stabilization-enrichment
---

## Summary

Add a bounded write-time enrichment and background consolidation layer so
Pallium can improve retrieval quality and memory lifecycle behavior without
pushing more semantic work into the query hot path.

This feature should enrich already-typed memory records with small retrieval-
helpful context and lightweight lifecycle links, and should prefer background
execution where latency-sensitive ingest paths would otherwise suffer.

The goal is to prepay reusable semantic work once at write time instead of
recomputing or inferring the same context repeatedly at query time.

## Why

The stabilization lane now assumes a deterministic query hot path with optional
semantic escalation only for unresolved ambiguity.

That makes the write path more important.

After Pallium has:

- typed memory envelopes
- typed constraints
- subject/workstream anchors
- bounded selective query ambiguity resolution

there is still a later opportunity to improve quality further by enriching what
gets stored and consolidated, so later retrieval can stay cheap.

Research across stronger systems points to a recurring pattern:

- stable semantics are often attached at ingest or in background jobs
- query-time retrieval then operates over richer stored objects
- expensive semantic work is reused rather than repaid on every query

This feature is the smallest generic version of that idea that fits Pallium's
current scope.

## In Scope

- add bounded write-time contextual enrichment for derived memory objects,
  such as:
  - compact retrieval-oriented canonical text
  - lightweight contextual enrichment that improves later matching without
    replacing provenance-backed content
  - small lifecycle hints such as supersession or consolidation links when they
    are available deterministically
- add background consolidation hooks where enrichment or reconciliation does not
  need to block the primary ingest path
- make background jobs prefer incremental updates over broad thread-wide
  re-synthesis where possible
- preserve typed memory envelopes, provenance, and current evidence-backed
  product boundaries
- expose enrichment and consolidation provenance in debug trace or memory
  inspection surfaces
- add deterministic tests for:
  - retrieval improvement from enriched write-time fields
  - background consolidation preserving the same bounded memory decision
    contract
  - supersession or consolidation hints not breaking existing retrieval or
    replay behavior
- add verification that measures whether enrichment reduces query-time semantic
  escalation or improves bounded retrieval quality

## Out of Scope

- a full graph platform
- broad ontology management
- unconstrained summary rewriting of stored memory
- replacing lower-level evidence with only enriched higher-level text
- a global contradiction engine across all memory
- broad workspace knowledge extraction outside the current product slice

## Done When

1. Pallium can enrich stored memory records with bounded retrieval-helpful
   context without changing the current evidence-backed product boundary.
2. Background consolidation or enrichment can run without forcing the same work
   into the primary query hot path.
3. Debug or inspection paths can explain which enriched fields or lifecycle
   hints were attached and where they came from.
4. Focused regressions show that enrichment improves retrieval quality or
   reduces semantic escalation without causing opaque behavior.
5. The feature remains clearly smaller than a graph platform and clearly scoped
   to the current agent-conversation-memory product slice.

## Notes

Recommended sequencing:

1. land the write-time envelope, constraint lane, subject anchors, and bounded
   selective query ambiguity resolution first
2. then add this enrichment layer so the deterministic hot path already has a
   stable structure to enrich
3. keep Pallium-native scenario/replay coverage active so enrichment changes are
   validated through the same memory-decision contract
4. after this, live miss-capture and external pressure can evaluate a richer
   write path instead of a still-minimal one

Implementation defaults:

- prefer bounded enrichment fields over broad rewritten summaries
- prefer background execution for heavier enrichment work where possible
- keep enrichment additive over typed memory records rather than replacing the
  canonical evidence-backed memory payload
- use prompt or model improvements only behind bounded schemas, versioning, and
  replay-backed review
