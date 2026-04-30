---
id: add-first-typed-memory-decision
title: Add the first typed-memory path for decision
status: done
priority: high
commitment: committed
milestone: Phase 3
---

## Summary

Add deterministic typed decision memory so the semantic layer can promote `decision` objects instead of only generic `turn_summary` objects.

## Why

The mixed retrieval foundation proved the retrieval shape. The next value step was to improve memory quality by making at least one memory type semantically meaningful.

## In Scope

- deterministic decision detection in the demo plugin
- typed_candidate annotations for decision-like inputs
- promoted `decision` memory objects with evidence links
- fallback `turn_summary` promotion for non-decision inputs

## Out of Scope

- LLM-backed extraction
- embeddings or vector retrieval
- tiered memory and consolidation jobs
- lifecycle state expansion

## Done When

1. Decision-like source items produce typed candidate annotations and promoted decision memory.
2. Non-decision inputs still promote discussion summaries.
3. Mixed retrieval returns decision memory hits and source evidence together.

## Notes

Status: completed and verified with pytest plus a live temporary-database HTTP run through the simulation flow.
