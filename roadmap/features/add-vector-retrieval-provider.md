---
id: add-vector-retrieval-provider
title: Add vector retrieval provider and semantic indexes
status: queued
priority: medium
commitment: committed
milestone: Later
---

## Summary

Add a vector retrieval provider and semantic indexing for selected Pallium text views so retrieval can cover paraphrase and conceptual similarity, not only exact lexical overlap.

## Why

Pallium needs to retrieve both exact technical evidence and fuzzier prior reasoning. Lexical retrieval already covers the first part; vector retrieval is the next required capability for the second.

## In Scope

- add a vector retrieval provider boundary
- support semantic indexing for selected `SourceItem` and `MemoryObject` text views
- record embedding provider/model/version metadata
- keep vector retrieval optional and additive to the existing lexical baseline
- preserve compatibility with local-first deployment and replaceable providers

## Out of Scope

- making vector search the only retrieval path
- fusion policy
- reranking
- broad automatic embedding of every possible artifact without selection rules

## Done When

1. Pallium can build and query semantic indexes for selected text views.
2. Both `SourceItem` and `MemoryObject` remain valid vector retrieval targets.
3. Embedding provider/model/version metadata is stored alongside semantic index entries.
4. The vector retrieval path can be exercised independently for diagnostics before fusion is added.

## Notes

This slice adds semantic retrieval capability, but it does not replace the current structured-plus-lexical foundation.

Sources: `docs/designs/005-hybrid-retrieval-guidance.md`, `docs/context/vision.md`
