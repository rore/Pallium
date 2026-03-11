---
id: add-tiered-memory-extension
title: Add bounded tiered memory with strategy comparison
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Add the first reusable consolidation capability so Pallium can create a higher-level, evidence-backed `pattern_memory` over `thread_summary`, `decision`, and `investigation_outcome`, then compare multiple selection strategies on the same fixtures and recurring-question benchmark.

## Why

Pallium becomes more useful than lower-level retrieval alone when it can return one compact higher-level memory object that carries forward the conclusions of multiple related conversation memories without losing evidence.

## In Scope

- add a reusable consolidation capability between the core and semantic packages
- add one higher-level memory type: `pattern_memory`
- support three explicit bounded strategies:
  - `thread_local_carry_forward`
  - `container_topic_window`
  - `thread_summary_anchored`
- preserve evidence and lifecycle for higher-level memory
- compare strategies on consolidation fixtures and the recurring-question benchmark
- choose and record a default strategy for `agent_conversation_memory`

## Out of Scope

- global autonomous clustering of everything
- vector-assisted grouping in this slice
- public consolidation APIs
- deep multi-level hierarchy
- replacing lower-level memory with summaries only

## Done When

1. A reusable consolidation capability exists between the core and semantic packages.
2. `agent_conversation_memory` can produce evidence-backed `pattern_memory`.
3. At least three explicit selection/grouping strategies can be run against the same fixture set.
4. Pattern memory preserves evidence and lifecycle while remaining queryable as a normal memory hit.
5. At least one recurring-question scenario improves with higher-level memory present.
6. Strategy comparison records a meaningful tradeoff and justifies the package default.

## Notes

Implemented result:
- `pattern_memory` is now built over `thread_summary`, `decision`, and `investigation_outcome`
- strategy comparison is available through `evals/consolidation_strategy_runner.py`
- the current package default is `thread_summary_anchored`

Recorded strategy outcome on the deterministic comparison harness:
- `thread_local_carry_forward`
  - safest and strictly same-thread
  - produced broad pattern coverage but little cross-thread flexibility
- `container_topic_window`
  - most selective cross-thread strategy
  - avoided the same-container noise-merge case after stopword filtering
- `thread_summary_anchored`
  - kept thread summaries as the main unit while allowing bounded cross-thread carry-forward
  - matched the benchmark baseline while producing broader useful pattern coverage than the stricter container-only strategy

The current default was chosen because it produced conservative, interpretable groups without false merges while keeping room for cross-thread carry-forward. Hybrid retrieval remains a later retrieval-layer concern, not part of this consolidation slice.

Additional retained design understanding:
- the broader field validates consolidation from trusted intermediate semantic units rather than directly from raw events
- the main unresolved risk remains principled candidate selection and grouping
- `pattern_memory` should be treated as the first higher-level type, not the final ontology
- consolidation should remain explicit and bounded until retrieval-policy and product-value evidence are stronger

