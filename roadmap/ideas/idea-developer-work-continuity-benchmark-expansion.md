---
id: idea-developer-work-continuity-benchmark-expansion
title: Developer-work continuity benchmark expansion
status: queued
priority: medium
commitment: uncommitted
milestone: Idea
---

## Summary

Expand Pallium's evaluation layer from the current bounded work-resumption
benchmark into a broader developer-work continuity benchmark program.

The target is to tune Pallium for interrupted investigation, resumed
implementation, blocker recovery, and realistic continuation behavior using both
authored scenarios and reviewed open-data slices.

## Why

The current benchmark stack is strong enough to guide the first product slice,
but not yet broad enough to make Pallium fully trustworthy for Pelican-like
developer workflows.

Pallium now needs a benchmark program that can separate:

- routing and layer-choice failures
- result packaging failures
- compact task-state failures
- retrieval recall failures
- no-value overreach
- later privacy-leak failures

and do so across both authored scenarios and realistic public interaction data.

## In Scope

- expand the authored work-resumption benchmark into a broader developer-work
  continuity suite
- create reviewed WildChat continuation/paraphrase slices for tuning realism
- use WildBench as a complementary task-pressure acceptance layer
- keep a shared failure taxonomy across these evaluation layers
- use the combined benchmark program to justify later routing, packaging, or
  retrieval tuning work

## Out of Scope

- replacing the current privacy or integration-readiness queue
- treating raw public corpora as the product benchmark without review
- turning the benchmark program into a generic workflow-engine simulator
- committing large third-party datasets into the repo

## Done When

1. Pallium has a broader developer-work continuity benchmark suite than the
   current bounded work-resumption benchmark alone.
2. Reviewed WildChat continuation slices and a bounded WildBench acceptance pack
   exist under the same failure taxonomy.
3. The benchmark program can justify whether the next real bottleneck is
   routing, packaging, compact task-state memory, or retrieval recall.

## Notes

Design source:

- `docs/designs/010-developer-work-continuity-benchmark-and-open-corpus-tuning.md`

This should remain an idea until the current privacy and integration-readiness
queue is further along.
