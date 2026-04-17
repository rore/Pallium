---
id: idea-operational-scale-hardening
title: Operational scale hardening
status: queued
priority: low
commitment: uncommitted
milestone: Idea
---

## Summary

Capture the main later-stage scale improvements for Pallium's current
write-amplifying, evidence-backed memory model without changing the near-term
product direction.

The goal is to keep the current local-first, selected-artifact, derived-memory
shape while leaving room for operational hardening once real downstream traffic
proves where the pressure actually is.

## Why

The current `agent_conversation_memory` slice intentionally produces more than a
raw append-only log:

- source items
- direct memory objects
- rebuilt thread-level memory
- explicit evidence relations
- lexical index entries
- vector embeddings

That is acceptable for the current bounded use case, but it creates predictable
future pressure in:

- ingest latency
- LLM cost
- thread rebuild amplification
- index growth
- SQLite concurrency and write contention

These are real future concerns, but they should be addressed as operational
optimizations after integration learning, not as premature redesign now.

## In Scope

- selective or debounced thread rebuild triggers
- moving higher-level synthesis off the request path when justified
- bounded or incremental thread recomputation
- artifact gating to reduce low-value ingest fan-out
- background consolidation scheduling
- more selective active-set indexing and retrieval focus
- later backend upgrades if SQLite becomes a real operational bottleneck

## Out of Scope

- redesigning the core evidence-backed memory model now
- broad raw runtime-event ingestion
- replacing the current local-first storage choice before traffic justifies it
- changing product direction away from compact derived memory

## Done When

1. The repo keeps a concrete record of the main later scale levers.
2. These improvements remain available for future prioritization without being
   mistaken for current blockers.

## Notes

2026-04-16 update:

An initial operational-hardening slice has shipped without changing Pallium's
core evidence-backed memory model:

- additive SQLite indexes for queue, thread, relation, and index-entry hot paths
- batch vector hit hydration on the retrieval path
- summary-only worker result construction for runtime logging
- aligned processor/worker poll defaults
- bounded incremental vector reconciliation
- package claim ordering via denormalized `source_item_created_at`

The remaining value of this idea is now in later follow-on work and remeasurement,
not in proving these first-line optimizations are still hypothetical.

The highest-value likely future levers are:

1. selective/debounced thread rebuilds
2. async/off-request higher-level synthesis
3. stricter artifact gating
4. bounded or incremental recomputation
5. backend upgrades only if real usage justifies them
