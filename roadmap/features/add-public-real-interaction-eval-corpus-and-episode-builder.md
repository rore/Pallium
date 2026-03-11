---
id: add-public-real-interaction-eval-corpus-and-episode-builder
title: Add public real-interaction eval corpus and episode builder
status: queued
priority: high
commitment: committed
milestone: Next
---

## Summary

Add a public-corpus-backed evaluation path that converts real user-assistant conversations into Pallium event episodes so the current `agent_conversation_memory` slice can be tested against messy interaction shape without depending on private downstream traffic.

## Why

Pallium's current benchmarks prove the intended product shape, but they are still curated. Before expanding retrieval sophistication again, Pallium needs a realistic evaluation layer that can answer whether the next limiting factor is recall, routing, or result packaging on real interaction data.

## In Scope

- add a small corpus adapter layer for public user-assistant conversation datasets
- support one primary real-interaction source first, with additional sources optional and additive
- normalize selected conversations into Pallium's current event contract for user messages and final assistant outputs
- build reproducible within-conversation and later-session episode generation for evaluation
- filter aggressively for a narrow first slice:
  - English
  - non-toxic or otherwise safe subsets when available
  - multi-turn interactions that can plausibly exercise recurring-question memory value
- define a reviewed benchmark set over generated episodes with labels for:
  - whether memory should help
  - which result layer should win
  - whether higher-level memory would be overreach
- produce summary reporting that can compare lexical-only, current routed retrieval, and later retrieval variants on the same episode set
- keep raw third-party corpora external to the repo and commit only durable code, manifests, and reviewed evaluation assets

## Out of Scope

- live integration with any internal downstream system
- broad training or fine-tuning over the downloaded corpora
- committing large raw third-party conversation dumps into this repo
- adding vector retrieval or hybrid fusion in the same slice
- broad workspace or tool-use memory beyond the current agent-conversation scope

## Done When

1. Pallium can ingest at least one public real-interaction corpus into its current event shape through a bounded offline adapter.
2. Pallium can generate reproducible evaluation episodes for both within-conversation recall and later-session carry-forward.
3. A reviewed benchmark slice exists with enough episodes to expose routing overreach, no-value cases, and paraphrase/continuity pressure beyond the current synthetic set.
4. Benchmark output makes it possible to compare whether failures come mainly from retrieval recall, routed layer choice, or result packaging.
5. The repo documents the external corpus expectation and keeps licensed raw data out of version control.

## Notes

Recommended starting source:

- use WildChat as the first primary corpus because it provides real user-assistant conversations at useful scale and includes metadata that can support later-session episode construction

Secondary sources can be added later only if the first corpus leaves obvious coverage gaps.

Sources: `roadmap/scope.md`, `docs/context/state.md`
