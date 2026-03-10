---
id: add-retrieval-trace-and-text-view-model
title: Add retrieval trace and text-view modeling
status: queued
priority: medium
commitment: committed
milestone: Later
---

## Summary

Extend the retrieval layer so Pallium can model named text views and emit retrieval trace data that explains why a result appeared.

## Why

Hybrid retrieval will be difficult to trust or tune if Pallium cannot explain whether a hit came from lexical search, vector search, or fusion, and which text view actually matched.

## In Scope

- add richer text-view metadata to retrieval/index entries
- track index type and provider/version more explicitly
- add a retrieval trace or debug payload path for development and evaluation
- keep the trace generic across `SourceItem` and `MemoryObject` retrieval
- preserve compact default result packaging while allowing optional explainability

## Out of Scope

- vector retrieval itself
- fusion itself
- reranking
- changing the default compact query response into a verbose debug dump

## Done When

1. Pallium can identify which text view produced a retrieval candidate.
2. Retrieval traces can distinguish lexical-only, vector-only, and fused hits once those modes exist.
3. The debug/explain path is optional and does not break the current compact retrieval contract.
4. The retrieval model is ready for vector and fusion slices without redesigning `IndexEntry` again.

## Notes

This is the first retrieval slice that prepares Pallium for hybrid search without blocking current lexical-first behavior.

Sources: `docs/designs/005-hybrid-retrieval-guidance.md`, `docs/context/architecture.md`
