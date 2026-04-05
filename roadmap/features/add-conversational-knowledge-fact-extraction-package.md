---
id: add-conversational-knowledge-fact-extraction-package
title: Conversational knowledge fact extraction package
status: done
priority: medium
commitment: committed
milestone: Done
---

## Summary

Add a second production semantic package that extracts atomic factual knowledge
from conversation threads, running in parallel alongside
`agent_conversation_memory`.

## Why

`agent_conversation_memory` focuses on agent continuity: decisions, findings,
checkpoints, and work state. But conversations also contain factual knowledge
that doesn't fit those types — domain facts, technical details, stated
preferences. A separate package can extract these without overloading the
continuity package's extraction schema.

LoCoMo benchmark baseline (61.2% on conv-26) confirmed that fact extraction
alongside agent continuity improves recall for factual questions that
continuity memory alone misses.

## In Scope

- `conversational_knowledge` semantic package implementation
- Atomic fact extraction from conversation threads via thread rebuild
- `parallel_processing = True` — processes every incoming item
- Runs alongside `agent_conversation_memory` using multi-package processing
  infrastructure

## Out of Scope

- Replacing agent_conversation_memory's extraction
- Broad knowledge graph construction
- Cross-container fact merging or deduplication

## Done When

1. Package extracts atomic facts from conversation threads.
2. Package runs in parallel with agent_conversation_memory.
3. Extracted facts are retrievable through normal query path.

## Notes

Shipped. Uses the thread rebuild mechanism for extraction. Configured in TOML
under `[semantic_packages.conversational_knowledge]`.
