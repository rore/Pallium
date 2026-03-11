---
id: add-internal-intent-aware-memory-routing
title: Add internal intent-aware memory routing
status: queued
priority: medium
commitment: committed
milestone: Later
---

## Summary

Add an internal intent-aware retrieval policy for `agent_conversation_memory` so the package can rank `continuity_memory`, `pattern_memory`, lower-level memory, and source evidence by query shape without expanding the public API.

This slice should build on the existing retrieval trace work and on multiple already-proven higher-level memory kinds, rather than trying to invent new memory kinds and a routing layer at the same time.

## Why

Once Pallium has more than one higher-level memory kind, one global retrieval preference will be too blunt. Broad recurring why-questions, repeated-answer continuity, precise factual lookups, and evidence-heavy trace questions should not all prefer the same memory layer.

That does not require a public intent field yet, but it does require an explicit internal policy that can be inspected and benchmarked.

## In Scope

- add a small internal query-intent taxonomy for `agent_conversation_memory`, owned by the package rather than the public API
- map internal intent to retrieval preference across:
  - `continuity_memory`
  - `pattern_memory`
  - lower-level memory
  - source evidence
- extend retrieval trace and evaluation outputs so runs can explain:
  - classified query intent
  - preferred memory layer ordering
  - chosen or demoted higher-level memory hits
  - kind and strategy provenance on returned higher-level memory
- expand the recurring-question benchmark and tiered-memory validation benchmark so they score the routing policy rather than a single global higher-level-memory preference
- keep the public `/query` contract unchanged while the package-level policy is being validated

## Out of Scope

- adding new higher-level memory kinds in this slice
- making query intent a required public `/query` field
- exposing raw consolidation strategy names as the public retrieval interface
- cross-container consolidation or sharing changes
- vector-assisted consolidation selection
- replacing lower-level memory or source evidence with only higher-level memory

## Done When

1. `agent_conversation_memory` classifies queries into a small internal intent taxonomy without expanding the public API.
2. The package uses that intent to rank higher-level memory kinds versus lower-level memory and source evidence.
3. Broad recurring why-question scenarios prefer `pattern_memory` when it improves recall without false merges.
4. Repeated-answer continuity scenarios prefer `continuity_memory` over the broad recurring-pattern path.
5. Precise factual and evidence-heavy scenarios still prefer lower-level memory or source evidence over higher-level memory.
6. Retrieval trace and benchmark outputs record intent classification, preferred layer ordering, returned layers, and demotion reasons for non-winning higher-level memory.
7. The recurring-question benchmark and tiered-memory validation benchmark both show that the routed policy outperforms a single global higher-level-memory policy on the current scenario families.

## Notes

Initial package-level intent model should stay small and evidence-driven. The first candidate set is:

- `answer_continuity`
- `broad_recall`
- `precise_fact`
- `evidence_trace`

Design locks for this slice:

- keep intent internal until retrieval-policy evidence is stronger
- do not treat routing as a reason to expand the core query contract
- do not let intent classification hide retrieval behavior; traceability is part of the feature

Dependency note:

- this feature should follow `add-retrieval-trace-and-text-view-model`
- this feature should follow `add-continuity-memory-kind`
