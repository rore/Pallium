---
id: add-task-checkpoint-memory-kind
title: Add task checkpoint memory kind
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Add one compact task-state memory kind for `agent_conversation_memory`, tentatively `task_checkpoint`, so Pallium can help a downstream agent resume interrupted work with current state, key findings, blockers, next step, evidence, and freshness.

## Why

Recurring-question recall and reusable conclusions are valuable, but they do not fully solve the main continuity problem in long-running developer work.

An agent often needs not only "what did we conclude before" but also "where were we, what failed, what do we do next". A bounded task checkpoint is the smallest new memory slice that addresses that resumption problem without turning Pallium into a workflow engine.

## In Scope

- add exactly one new compact memory kind for work resumption
- keep the memory bounded to high-signal task-state fields such as:
  - current task or goal
  - current state
  - key findings so far
  - blockers or failed attempts
  - next likely step
  - supporting evidence
  - freshness or lifecycle context
- derive task checkpoints from the current lower-level memory, thread summaries, and selected work artifacts rather than from raw transcript replay alone
- keep task checkpoints package-owned rather than moving workflow semantics into the generic core
- extend the internal package routing policy with a minimal resume-oriented path so continuation queries can prefer task checkpoints without changing the public `/query` contract
- expand evaluation coverage so task checkpoints are measured on interrupted and resumed work scenarios

## Out of Scope

- a full task graph or project-planning system
- raw todo management or workflow orchestration
- broad cross-container task sharing
- public `/query` API expansion
- replacing lower-level evidence with only task checkpoints

## Done When

1. `agent_conversation_memory` can create a compact task checkpoint with explicit evidence and provenance.
2. Resume-oriented queries can prefer task checkpoints while still allowing lower-level memory and source evidence to win when more precise grounding is needed.
3. Work-resumption benchmark scenarios show measurable improvement over the current conclusion-only memory layer.
4. The package remains bounded and does not collapse into transcript replay or workflow-engine behavior.

## Notes

Implemented result:

- `agent_conversation_memory` now emits package-owned `task_checkpoint` memory for compact resumed-work continuity.
- `task_checkpoint` stays additive and evidence-backed: it captures task, current state, key findings, blocker state, next step, evidence, and a freshness signal without widening the public query contract.
- internal routing now prefers `task_checkpoint` for resumed-work questions while still letting lower-level memory or source evidence win on precise factual and evidence-trace queries.
- the work-resumption benchmark and focused routing tests now exercise `task_checkpoint` directly alongside the existing bounded selected work-artifact support and lower-level evidence paths.

Design locks that remain true after implementation:

- do not move resumed-work semantics into the generic core contract
- do not ingest raw tool logs or raw MCP events
- do not turn `task_checkpoint` into a workflow engine or task graph
- keep bounded selected work-artifact support as the evidence source rather than replacing it
