# Container-Level Extraction for Standalone Messages

**Date:** 2026-04-26
**Status:** Design

## Problem

Pallium extracts memory (atomic facts, thread summaries) from threads with 2+ items. In Slack-style integrations, every top-level message has its own unique `thread_ref` — only explicit thread replies share a parent's `thread_ref`. This means most DM channel messages are singleton threads that fall below the 2-item extraction minimum. Substantive conversations happening on the main channel level produce zero memory.

Additionally, integrations that send items with no `thread_ref` at all are rejected outright by the thread processing guard.

## Design

### Core concept

The container is the main conversation. Top-level messages form a coherent conversational flow at the container level, just as nested replies form a sub-conversation at the thread level. Both deserve extraction.

A new container-level processing scope (`thread_ref=None`) runs alongside existing thread scopes. It uses the same plugin interface, extraction prompts, watermark mechanism, and fact accumulation model. No new machinery — just a scope where `thread_ref` is `None` with different item collection logic.

Both semantic packages participate: `conversational_knowledge` extracts atomic facts from the main conversation, `agent_conversation_memory` extracts thread summaries / task checkpoints. Consolidation merges overlapping facts across thread and container scopes naturally.

### Routing

Every ingested item bumps both:
- Its **thread scope** (if it has a `thread_ref`) — unchanged behavior
- The **container scope** (`thread_ref=None`) — new

Two independent extraction paths running side by side. No conditional routing, no fallback logic.

### Item collection

| Scope | Collects |
|-------|----------|
| **Thread** (unchanged) | All items in thread_refs with 2+ items — the sub-conversation |
| **Container** (new) | First item of each thread_ref + all items with no thread_ref — the main conversation |

- **First item per thread_ref** (by `created_at`): this is the top-level message. For singleton thread_refs, it's the only item — the messages currently being dropped. For multi-item thread_refs, it's the thread parent — represents the topic as it appeared in the main channel.
- **Threadless items**: items with no `thread_ref` are by definition top-level. They go straight into the container scope.
- **Watermark-based incrementality**: the container scope tracks what it has processed. Each cycle extracts only from new top-level messages since the last watermark.

A thread parent may appear in both thread and container extraction. This is correct — different conversational contexts may yield different facts. Consolidation handles any overlap.

### Trigger timing

Immediate. No staleness delay. When a container scope is bumped, the worker picks it up on its next cycle. If a standalone message later gets a reply (becoming a 2+ item thread), thread-level extraction fires and produces its own facts. Both sets accumulate (`rebuild_supersedes_prior=False` for conversational_knowledge). Consolidation merges naturally.

### Schema and code changes

1. **`ThreadProcessingScope.thread_ref`** becomes `Optional[str]` (currently required). `ThreadProcessingLeaseRecord.thread_ref` becomes a nullable column. Scope key for container scope: JSON with `thread_ref: null` — e.g. `{"container_ref":"…","thread_ref":null,"use_case":"…","visibility":"private"}`.

2. **`thread_rebuild.py` guard removal** — the guard at line 168 that rejects items with no `thread_ref` is removed. Threadless items enter the system normally.

3. **2-item minimum becomes scope-aware** — the guard exists in two places: `thread_rebuild.py:370` (core) and `conversational_knowledge.py:337` (plugin). Both must be skipped for container scopes. Thread scopes keep the 2-item minimum unchanged.

4. **New storage method for container collection** — a new method on `StorageProvider` (not a modification of `list_source_items_for_thread`) that collects top-level messages for a container: first item per thread_ref (by `created_at`) plus all threadless items, filtered by watermark.

5. **`_maybe_rebuild_thread_summary()` branch** — for container scopes (`thread_ref is None`), this method calls the new container collection method instead of `list_source_items_for_thread()`.

### What stays unchanged

- Plugin interface (`build_thread_summary`) — container scope flows through the same method
- Extraction prompts — already designed for batch fact extraction from conversational content
- Watermark mechanism — same per-scope tracking, container scope gets its own watermark
- Fact accumulation — `rebuild_supersedes_prior=False`, facts from both scopes coexist
- Consolidation — groups by `(container_ref, subject, category, visibility)` across all scopes
- Supersession — consolidation supersedes input atomic_facts with fact_summary as before
- Thread-level extraction — completely unchanged, 2-item minimum stays for thread scopes

### Known limitation: container growth and truncation

`agent_conversation_memory` uses `rebuild_supersedes_prior=True` with a 4000-char input window (`THREAD_SUMMARY_MAX_TEXT_CHARS`). For sub-threads this is fine — threads are bounded. For the container scope, the "main thread" grows indefinitely, and each rebuild truncates older messages. This is the same limitation that exists at thread level, just more visible at container scale.

`conversational_knowledge` handles growth naturally — watermark-based incremental extraction only processes new items, and facts accumulate. No truncation issue.

The truncation means `agent_conversation_memory`'s container-level thread_summary reflects recent messages, not the full history. This is strictly better than the current state (zero extraction). A windowing strategy for container-scale summaries is a separate follow-up (see `roadmap/features/investigate-thread-level-interest-and-threadless-aggregation.md`).

## Reproduction test

`tests/test_standalone_message_extraction_gap.py` reproduces the gap with a 5-message design discussion (catalog sync shadow mode). Assertions currently confirm 0 facts from standalone messages. After implementation, assertions flip to expect facts.
