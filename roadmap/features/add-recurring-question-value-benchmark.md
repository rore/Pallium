---
id: add-recurring-question-value-benchmark
title: Add a recurring-question value benchmark
status: queued
priority: high
commitment: committed
milestone: Next
---

## Summary

Add a small benchmark that tests whether Pallium makes recurring questions easier for a downstream agent to answer by comparing compact memory-backed context against the current lower-level retrieval shape.

## Why

A value-based roadmap needs an explicit proof point for user benefit, not only more memory capabilities. Pallium becomes clearly worthwhile when it can help answer recurring questions with less noise, better consistency, and preserved evidence.

## In Scope

- define a small set of recurring-question scenarios such as "why did we do this?" and "have we seen this before?"
- capture the expected high-signal memory shape for those scenarios
- compare answers or context quality between:
  - lower-level retrieval only
  - memory-backed retrieval, and later
  - consolidated memory retrieval
- document the benchmark and its evaluation method in the repo

## Out of Scope

- full production benchmarking infrastructure
- a broad quantitative offline eval framework for every prompt/model dimension
- replacing the semantic regression set

## Done When

1. The repo contains at least one committed recurring-question benchmark scenario set.
2. The benchmark can show whether Pallium reduces low-level retrieval noise for those scenarios.
3. The benchmark is usable to judge whether the first tiered-memory feature creates real downstream value.

## Notes

Sources: `roadmap/scope.md`, `docs/context/architecture.md`, `evals/semantic/baseline.md`
