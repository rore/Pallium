---
id: add-tiered-memory-validation-benchmark
title: Add tiered-memory validation benchmark
status: queued
priority: high
commitment: committed
milestone: Next
---

## Summary

Build a dedicated validation benchmark for tiered memory so Pallium can compare consolidation strategies on usefulness, safety, and retrieval behavior rather than only on construction success.

The benchmark should answer two product questions:

1. Does higher-level `pattern_memory` improve downstream recurring-question handling over lower-level memory alone?
2. Which consolidation strategy gives the best safety/value balance for `agent_conversation_memory`?

It should also answer one architecture question:

3. When should higher-level memory win, and when should lower-level memory or source evidence still be preferred?

## Why

Tiered memory is now implemented, but it is not yet fully product-proven.

The current comparison harness validates that strategies can build conservative `pattern_memory`, but it does not yet fully validate:

- false-merge rate across harder scenarios
- when `pattern_memory` should help
- when `pattern_memory` should stay out of the way
- whether higher-level memory is being retrieved in the right situations

The main unresolved risk remains principled consolidation policy and retrieval policy.

## In Scope

- add a dedicated benchmark layer for tiered-memory usefulness and safety
- expand consolidation fixtures beyond the current happy-path scenarios
- compare at least these modes:
  - baseline current-thread context only
  - lower-level memory without tiered memory
  - tiered memory with `thread_local_carry_forward`
  - tiered memory with `container_topic_window`
  - tiered memory with `thread_summary_anchored`
- record per-strategy tradeoffs such as:
  - false merges
  - missed useful merges
  - answer improvement over lower-level memory only
  - context reduction / compression
  - evidence preservation
- add explicit retrieval-policy cases where:
  - `pattern_memory` should win
  - lower-level memory should win
  - raw/source evidence should still remain necessary
- add richer consolidation trace in eval output, including:
  - grouping signals that fired
  - anchor memory where applicable
  - merge rationale / confidence summary

## Out of Scope

- public API changes
- vector-assisted consolidation selection
- global autonomous clustering over the full store
- new higher-level ontology beyond `pattern_memory`
- changing the current package default before the benchmark results justify it

## Done When

1. Pallium has a dedicated tiered-memory validation benchmark separate from construction-only tests.
2. The benchmark compares lower-level memory against multiple tiered-memory strategies on the same recurring-question scenarios.
3. The benchmark includes both value and non-value cases.
4. The benchmark includes explicit false-merge guard scenarios.
5. The benchmark includes retrieval-policy cases where `pattern_memory` should not dominate.
6. Per-strategy outputs record useful trace data explaining why a consolidation group formed.
7. The package default strategy is justified by recorded benchmark results rather than only by qualitative judgment.

## Notes

Scenario families to cover:

- cross-thread repeated why-question where a prior finding plus decision should become one useful `pattern_memory`
- repeated-answer consistency case where higher-level memory should stabilize a later answer
- same-thread low-value case where current thread is already sufficient
- precise factual question where lower-level `decision` or `investigation_outcome` should beat `pattern_memory`
- evidence-heavy question where source evidence should still be necessary
- same-container unrelated-topic case that should not merge
- similar-wording different-issue case that should not merge
- changed decision over time where stale higher-level carry-forward must be avoided
- unresolved thread cluster that should not become an overclaimed pattern
- one-off issue with no recurrence where tiered memory should add little or nothing

This feature should turn the current consolidation strategy comparison into a product-validation layer, not just an engineering harness.
