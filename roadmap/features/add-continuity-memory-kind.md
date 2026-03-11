---
id: add-continuity-memory-kind
title: Add continuity memory kind
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Add a second higher-level memory kind for `agent_conversation_memory`, `continuity_memory`, aimed at repeated-answer continuity and compact carry-forward, without adding intent routing yet.

This slice should keep the current broad recurring-pattern behavior under `pattern_memory` and prove that a separate continuity-oriented higher-level memory object adds value on the scenario family where the current benchmark says local carry-forward wins.

## Why

The current tiered-memory validation benchmark established that repeated-answer continuity is better served by more local carry-forward than by one broad recurring-pattern path.

That is enough evidence to add one second higher-level memory kind, but not yet enough evidence to bundle that change together with internal query-intent classification and a new retrieval-policy layer.

## In Scope

- keep tiered memory as a reusable consolidation capability, not a core behavior
- generalize the consolidation path so a package can produce more than one higher-level memory kind
- for `agent_conversation_memory`, add exactly one new higher-level kind in this slice:
  - `continuity_memory` for repeated-answer continuity and concise carry-forward of a previously answered question
- keep the current lower-level inputs bounded to:
  - `thread_summary`
  - `decision`
  - `investigation_outcome`
- treat producer strategy as package-owned implementation detail rather than public retrieval policy:
  - `thread_local_carry_forward` should be the primary initial producer for `continuity_memory`
  - `thread_summary_anchored` should remain the conservative comparison/control path
- record explicit kind and strategy provenance on created higher-level memory
- expand the recurring-question benchmark and tiered-memory validation benchmark so repeated-answer continuity scenarios score `continuity_memory` separately from the existing `pattern_memory` path
- keep legacy `pattern_memory` readable without destructive migration or mandatory backfill

## Out of Scope

- internal query-intent taxonomy or intent-routed retrieval policy
- public `/query` API expansion
- broad higher-level ontology expansion beyond `pattern_memory` and `continuity_memory`
- cross-container consolidation changes beyond the current bounded within-container tiered-memory scope
- vector-assisted consolidation selection
- destructive migration or mandatory backfill of existing `pattern_memory`
- replacing lower-level memory or source evidence with only higher-level memory

## Done When

1. Pallium's consolidation capability can produce more than one package-declared higher-level memory kind without baking those kinds into the generic core contract.
2. `agent_conversation_memory` can produce `continuity_memory` with explicit kind and strategy provenance.
3. Repeated-answer continuity scenarios show `continuity_memory` beating the current single-higher-level-memory policy on the current scenario family.
4. Precise factual and evidence-heavy scenarios still prefer lower-level `decision` / `investigation_outcome` or source evidence over higher-level memory.
5. Retrieval traces and benchmark outputs can distinguish `pattern_memory` and `continuity_memory` and explain which kind was returned.

## Notes

Implemented result:

- `agent_conversation_memory` now emits `continuity_memory` as a second higher-level memory kind for bounded repeated-answer carry-forward.
- generic consolidation now persists whichever higher-level kinds the package emits without moving those kinds into the core contract.
- current package policy keeps broader or cross-thread groups on `pattern_memory`, while bounded same-thread carry-forward groups can emit `continuity_memory`.
- recurring-question and tiered-memory validation coverage now distinguish `continuity_memory` from `pattern_memory` explicitly.

Design locks that remain true after implementation:

- do not let public `/query` semantics depend on raw strategy names
- do not move higher-level memory kinds into the generic core domain model
- keep `continuity_memory` bounded within the current within-container memory scope
- use the retrieval trace and named text-view model for later routing/debug work rather than redesigning the query contract
