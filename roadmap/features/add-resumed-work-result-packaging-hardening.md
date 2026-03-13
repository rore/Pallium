---
id: add-resumed-work-result-packaging-hardening
title: Add resumed-work result packaging hardening
status: queued
priority: medium
commitment: committed
milestone: Next
---

## Summary

Harden how Pallium presents resumed-work memory so retrieved state is not only relevant, but operationally useful. Focus on compact orientation for task, current state, key findings, blockers, next step, evidence, and freshness.

## Why

Pallium can now preserve resumed-work state through `task_checkpoint`, but practical value depends on how clearly that state is surfaced. A system can retrieve the right memory and still feel weak if the result packaging does not make the task orientation, blocker state, and next step obvious enough for the downstream agent.

This slice should sharpen the returned memory and benchmark scoring before the project claims stronger real-interaction readiness.

## In Scope

- improve package-owned resumed-work result shaping without expanding the public API broadly
- keep `task_checkpoint` compact and operationally useful
- sharpen how resumed-work retrieval favors:
  - task orientation
  - current state
  - key findings
  - blocker or failed-attempt state
  - next-step guidance
  - evidence and freshness
- add stronger benchmark checks that distinguish:
  - right memory found
  - useful resumed-work packaging
- improve evidence-heavy follow-up behavior where sharper provenance should still beat compressed summaries

## Out of Scope

- turning `task_checkpoint` into a workflow engine or task graph
- replacing source evidence on exact evidence-trace questions
- changing the privacy model
- adding vector retrieval or fusion in the same slice

## Done When

1. Resumed-work answers clearly preserve task, blocker, next-step, and evidence state when `task_checkpoint` is the right layer.
2. Benchmark output can distinguish packaging failures from routing and retrieval failures.
3. The developer-work continuity harness shows fewer `result_packaging_evidence_failure` and `compact_task_state_failure` cases.
4. Exact evidence-trace and precise factual questions still prefer sharper grounding where appropriate.

## Notes

This slice is about making the current memory layers more useful in practice, not about adding broader new memory ontology.
