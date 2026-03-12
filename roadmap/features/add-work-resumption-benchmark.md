---
id: add-work-resumption-benchmark
title: Add work-resumption benchmark
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Add an explicit workflow-continuity benchmark for `agent_conversation_memory` so Pallium is evaluated on interruption, resumed investigation, partial progress carry-forward, blocker recovery, and no-value continuation cases rather than only recurring-question recall.

## Why

Current benchmarks prove recurring-question handling and increasingly realistic conversation shape, but the strongest downstream value is broader: helping an agent continue work without rediscovering orientation after a pause, retry, redirect, or tool failure.

Before Pallium expands retrieval sophistication again, it needs an acceptance benchmark that can expose whether the next missing capability is richer task-state representation, selected work-artifact support, routed layer choice, or retrieval recall.

## In Scope

- add a bounded benchmark and reviewed scenario set for work-resumption behavior within the current package
- cover scenario families such as:
  - resumed investigation after a pause
  - debugging continued from partial findings
  - ticket or implementation work resumed after interruption
  - recovery after auth or tool failure with partial progress preserved
  - no-value continuation cases where current thread context should already be sufficient
- score whether Pallium helps the downstream answer or continuation plan retain:
  - current task orientation
  - key findings so far
  - blockers or failed attempts
  - next-step guidance
  - evidence when available
- keep results comparable with the existing failure taxonomy where useful, while allowing explicit visibility into missing task-state representation
- reuse the current event and query contracts where possible rather than inventing a new public interface

## Out of Scope

- live coupling to any internal downstream runtime
- raw tool-call replay or runtime orchestration state capture
- adding a new memory kind in the same slice
- expanding the public `/query` contract
- making private downstream data a prerequisite for the benchmark

## Done When

1. Pallium has a reproducible benchmark that exercises workflow resumption rather than only recurring-question recall.
2. The benchmark includes both positive and no-value continuation cases.
3. Benchmark output makes it clear whether failures are mainly due to missing task-state representation, weak routing, weak evidence packaging, or retrieval recall.
4. The benchmark can guide the next memory and artifact slices without depending on private downstream traffic.

## Notes

This slice should build on the current scenario/eval approach and on the public-corpus lessons, but it should not assume that public chat corpora alone are a sufficient proxy for tool-mediated developer workflows. The gap rollup is intentionally hypothesis-driven: scenario-authored `dimension_gap_targets` contribute to it, so the benchmark should guide the next slice rather than claim fully neutral discovery.

Implemented in:

- `evals/work_resumption_benchmark.py`
- `evals/work_resumption/scenarios.json`
- `tests/test_work_resumption_benchmark.py`

