---
id: add-fact-consolidation-strategy-for-conversational-knowledge
title: Fact consolidation strategy for conversational_knowledge
status: done
priority: medium
commitment: committed
milestone: Done
---

## Summary

Add a `FactConsolidationStrategy` to the `conversational_knowledge`
package that consolidates per-thread `atomic_fact` memories into
cross-thread `fact_summary` memory objects, including LLM-driven
contradiction detection and supersession.

## Why

`conversational_knowledge` extracts `atomic_fact` memories per thread.
Without a consolidation step, the same fact recurs across threads and
contradicting facts coexist with no winner. Cross-thread factual recall
on benchmarks (LoCoMo) hit a ceiling that thread-local fact extraction
alone could not move. Consolidation closes the loop: one durable
`fact_summary` per fact identity, with stale or contradicted versions
superseded.

## In Scope

- `FactConsolidationStrategy` inside the `conversational_knowledge`
  package
- Cross-thread merge of `atomic_fact` into `fact_summary`
  (high-value, durable)
- LLM-driven contradiction detection with supersession
- Documented behavior in `architecture.md`, `state.md`, `decisions.md`
  and the fact extraction design doc
- `fact_consolidation_eval` runner for retrieval quality

## Out of Scope

- Broad knowledge graph construction
- Cross-container fact merging
- Replacing thread-local `atomic_fact` extraction

## Done When

1. Strategy promotes `atomic_fact` to `fact_summary` across threads.
2. Contradictions are detected and superseded; the surviving
   `fact_summary` is the one returned by query.
3. Retrieval quality eval (`fact_consolidation_eval`) runs and reports.

## Notes

Shipped. Cross-thread contradiction supersession landed in commit
`7d8f0e0`; sonnet recommended for the consolidation LLM call. Design
context in
[docs/specs/2026-04-05-fact-extraction-design.md](../../docs/specs/2026-04-05-fact-extraction-design.md)
(the "does NOT do" section was updated when this strategy took over
cross-thread consolidation). Runner: `python -m evals.fact_consolidation_eval`.
This roadmap item was originally tracked only on the board; the file is
backfilled to keep the roadmap audit trail consistent with peer items.
