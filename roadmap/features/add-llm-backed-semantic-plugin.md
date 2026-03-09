---
id: add-llm-backed-semantic-plugin
title: Add an LLM-backed semantic plugin
status: done
priority: high
commitment: committed
milestone: Phase 3
---

## Summary

Add a second semantic plugin implementation that uses an LLM adapter to produce the same typed-memory contract as the deterministic demo plugin.

## Why

The typed-memory architecture is now proven. The next risk to reduce is semantic extraction quality when promoting reusable memory from unstructured evidence.

## In Scope

- an LLM provider abstraction for semantic extraction
- OpenAI-compatible and Claude provider adapters
- an LLM-backed plugin that can emit summary, typed_candidate, and promoted decision memory
- comparison of the LLM-backed path against the deterministic baseline on the same sample domain

## Out of Scope

- replacing the deterministic plugin
- embeddings or vector retrieval
- tiered memory or consolidation jobs

## Done When

1. Pallium can run with either the deterministic plugin or an LLM-backed plugin through the same core contract.
2. Decision-like inputs can produce typed decision memory through the LLM-backed path.
3. The system stays evidence-backed and the public API shape remains unchanged.

## Notes

Status: completed and verified with pytest, a live deterministic simulation, and a live LLM-backed simulation against a local fake OpenAI-compatible provider.

