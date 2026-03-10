---
id: add-recurring-question-value-benchmark
title: Add a recurring-question value benchmark
status: done
priority: high
commitment: committed
milestone: Next
---

## Summary

Add a small benchmark that tests whether Pallium makes recurring questions easier for a downstream agent to answer by comparing final downstream answers from current-thread context alone versus current-thread context plus compact memory-backed retrieval.

## Why

A value-based roadmap needs an explicit proof point for user benefit, not only more memory capabilities. Pallium becomes clearly worthwhile when it can help answer recurring questions with less noise, better consistency, and preserved evidence.

## In Scope

- define a small recurring-question scenario set over the agent-conversation memory package
- compare two answer paths per scenario:
  - baseline current-thread context only
  - memory-backed current-thread context plus Pallium retrieval
- generate both answers with the configured real OpenAI-compatible model
- score both answers with a human-readable rubric in repo code
- document the benchmark and its evaluation method in the repo

## Out of Scope

- full production benchmarking infrastructure
- a broad quantitative offline eval framework for every prompt/model dimension
- replacing the semantic regression set
- LLM-as-judge scoring

## Done When

1. The repo contains a committed recurring-question benchmark scenario set.
2. The benchmark emits machine-readable run artifacts with baseline answer, memory-backed answer, rubric scores, and winner per scenario.
3. The benchmark can show at least one value case where memory-backed wins and one non-value case where it correctly does not win.
4. The benchmark is usable to judge whether the first tiered-memory feature creates real downstream value.

## Notes

Completed on 2026-03-10.

Current committed recurring-question scenarios:
- cross-thread prior conclusion recall
- repeated-answer consistency
- same-thread low-value case

Live smoke run with the configured OpenAI-compatible model:
- `evals/recurring_question/output/local-recurring-question-smoke`
- `2` value scenarios where memory-backed won
- `1` non-value scenario where memory-backed correctly did not win

Sources: `roadmap/scope.md`, `docs/context/architecture.md`, `evals/semantic/baseline.md`, `evals/agent_conversation/scenarios.json`
