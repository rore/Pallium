---
id: idea-multi-vector-long-text-embedding
title: Multi-vector embedding for long texts
status: queued
priority: low
commitment: uncommitted
milestone: Idea
---

## Summary

Store multiple vector embeddings per memory object when the embedding text exceeds the model's 512-token limit, so that tail content is retrievable via vector search instead of silently truncated.

## Why

The ONNX embedding provider now truncates texts to 512 tokens (commit 57158c6). This prevents crashes but loses information — the truncated tail is invisible to vector retrieval. The lexical index (no token limit) partially compensates via RRF fusion, but vector-only matches on tail content are missed.

Affected types (most likely to exceed 512 tokens):

- **fact_summary** — consolidates up to 50 grouped facts into `f"{subject}: {summary}"`. Long enumerations lose tail facts from the embedding.
- **source_item** — raw user messages (pasted documents, code blocks) have no upper length bound.
- **thread_summary** — summary + all conclusion texts concatenated. Usually within budget but can exceed it for long threads.
- **task_checkpoint** — multiple fields concatenated (task + current_state + blocker + next_step + key_findings).

## Research

All comparable systems in `C:\Dev\others` that handle long texts use multi-vector storage, not mean-pooling:

- **MemPalace** — chunks at 800 chars with 100-char overlap, each chunk gets its own embedding in ChromaDB.
- **ClawMem** — semantic fragment splitting at 2000 chars, per-fragment embeddings with parent linking.

Mean-pooling (averaging chunk embeddings into one vector) was not used by any system — it dilutes retrieval specificity, which is the opposite of what fact retrieval needs.

Industry consensus (sentence-transformers, Pinecone, Weaviate docs) is that multi-vector with parent linking is the correct approach for retrieval over short-context models.

## In Scope

- Chunking strategy for embedding texts that exceed `max_tokens` — split into overlapping segments at natural boundaries.
- Multiple vector `IndexEntry` rows per parent object, all linked to the same `target_id`.
- Retrieval deduplication — when multiple chunks from the same object match a query, collapse them into one result (highest score wins).
- Warning metric: log how often truncation occurs today (already implemented) to size the actual impact before building this.

## Out of Scope

- Changing the embedding model to a longer-context one (e.g., bge-m3 at 8192 tokens). That's a separate consideration — multi-vector works regardless of model max length.
- Chunking source items at ingest time for non-embedding purposes. This is vector-retrieval-only.
- Changing the lexical index — it already handles arbitrary length texts.

## Open Questions

1. **Chunk granularity for fact_summary.** Should we chunk at comma boundaries (one vector per fact or fact-group), or use a fixed token-budget chunking strategy? Fact-level chunks would give precise retrieval but multiply storage.
2. **Overlap.** MemPalace uses 100-char overlap. Is overlap necessary for our use case, or do the memory object types have enough natural structure (facts are self-contained sentences) that zero-overlap works?
3. **Scope.** Most derived memory types (decisions, investigations, thread summaries, patterns) are already char-budgeted by LLM prompt design and unlikely to exceed 512 tokens. The types that realistically need multi-vector are **fact_summary** (50 consolidated facts) and **source_item** (unbounded user input). The truncation warning log will confirm this empirically — the solution may only need to target those two types.

## Done When

1. Truncation frequency data from production logs confirms whether the information loss is material.
2. If material: multi-vector storage works for all affected types, retrieval correctly deduplicates, and no regression in existing retrieval benchmarks.

## Notes

- Current mitigation: tokenizer truncation (commit 57158c6) + lexical index as fallback via RRF fusion.
- Sources: `docs/designs/005-hybrid-retrieval-guidance.md`, MemPalace chunking at `mempalace/miner.py`, ClawMem splitting at `ClawMem/src/splitter.ts`.
