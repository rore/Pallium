# Processing Pipeline Latency Analysis

Date: 2026-03-23

## Problem Statement

When a user sends a message and then queries, the previous message's processing may not have completed. Memories aren't available for retrieval until processing finishes. In chat-lite testing, this manifests as `should_inject: False` on turns where relevant memories should exist.

Chat-lite correctly simulates the production latency gap. This is the same gap real integrations will experience.

## Architecture Overview

Pallium runs three separate OS processes (via `supervisor.py`):

1. **API server** (FastAPI/uvicorn) — handles `/items` POST and `/query` POST
2. **Processor** (background worker) — polls SQLite for pending items, processes them
3. **Cleaner** (background worker) — retention/cleanup passes

The API server and processor are **separate OS processes** sharing only the SQLite database file. There is no in-process signaling between them.

## Production Integration Pattern

In production, a consuming agent runtime (e.g., a Slack bot, Claude Code, a custom agent) calls Pallium:

```
Turn N:
  1. User sends message
  2. Agent calls POST /items (ingest user message) — returns instantly
  3. Agent calls POST /query (to get relevant memory for response)
  4. Agent generates response using memory + message
  5. Agent calls POST /items (ingest assistant response)

Turn N+1: (seconds to minutes later)
  1. User sends next message
  2. Agent calls POST /items (ingest user message)
  3. Agent calls POST /query — NOW needs memories from Turn N
```

**The critical latency question is**: will Turn N's items be fully processed by the time Turn N+1's query arrives?

### Production Timing Analysis

The gap varies by integration scenario:

**Scenario A: Interactive chat (Slack, Teams)**
- Turn gap: typically 5-30 seconds (human typing)
- Processing budget: 2-10 seconds (1 LLM call + possible thread rebuild)
- **Usually works** — human typing time absorbs processing latency
- **Fails on rapid-fire**: user sends 3 messages in 2 seconds, queries arrive before processing completes

**Scenario B: Agent-to-agent or automated pipelines**
- Turn gap: sub-second (agent generates and sends immediately)
- Processing budget: same 2-10 seconds
- **Consistently fails** — items ingested faster than they can be processed
- Queue builds up; memories from 2-3 turns ago might not be available yet

**Scenario C: Session resumption**
- Turn gap: minutes to hours (new session, different day)
- Processing budget: irrelevant — everything from prior session is processed
- **Always works** — this is Pallium's strongest scenario

**Scenario D: Same-turn self-reference**
- The `/item-and-query` endpoint ingests and queries in one HTTP call
- Query runs immediately after ingest — **processing has NOT happened**
- The just-ingested item is lexically searchable as raw source content
- But no memory objects, semantic signals, or vector embeddings exist for it yet
- This is by design — you're querying for *prior* memory, not the thing you just said

### What the Consumer Sees

When processing hasn't caught up:

1. **Raw source items are immediately available** via lexical search. The ingest path creates a lexical index entry on the source item content in the same HTTP call.
2. **Vector matches for source items are NOT available** — embedding happens in the processor.
3. **Memory objects (decisions, investigations, thread summaries) are NOT available** — the LLM extraction hasn't run yet.
4. **Thread summaries are stale** — they reflect the thread state at last rebuild, not the latest items.

For routing, this means:
- `should_inject` may be False when memories should exist but haven't been promoted yet
- The `decision_reason` won't distinguish "no memories exist" from "memories exist but aren't processed yet"
- Lane narrowing works on what's in the index — it can't route to memory that doesn't exist yet

## Step-by-Step Processing Pipeline

### Phase 1: Ingest (`service.ingest_item()`)
**Cost: ~1-5ms (SQLite only, synchronous in the API request)**

| Step | I/O | Cost | Notes |
|------|-----|------|-------|
| Dedupe check (source_type, source_id) | SQLite read | ~1ms | Idempotency |
| Create SourceItem record | SQLite write | ~1ms | status="pending" |
| Create lexical index entry | SQLite write | ~1ms | Normalized source content |

Item sits in the pending queue until a processor claims it.

### Phase 2: Source Item Processing (`_process_source_item()`)
**Cost: ~1-5 seconds per item (LLM-dominated)**

| Step | I/O | Cost | Depends on Previous | Notes |
|------|-----|------|---------------------|-------|
| 2a. Claim item | SQLite UPDATE...RETURNING | ~1ms | — | Lease-based, atomic |
| 2b. Plugin validation | in-memory | ~0ms | — | use_case, visibility checks |
| 2c. Source embedding text | in-memory | ~0ms | — | Plugin policy: embed messages + assistant outputs ≥40 chars |
| 2d. Create vector index entry metadata | SQLite write | ~1ms | — | Records the text_view, not the vector yet |
| **2e. LLM extraction** | **HTTP round-trip** | **~500ms-3s** | — | **Dominant cost.** 1 call to Sonnet (write_extraction role) |
| 2f. Reconcile result | in-memory + SQLite | ~5ms | 2e | Supersession check against existing memory |
| 2g. SQLite commit | SQLite write | ~5-10ms | 2f | Atomic: memory objects, relations, index entries, status→completed |
| 2h. Embed memory object vectors | ONNX inference | ~20-50ms | 2g | Batched for all vector entries in the result |
| 2i. **Save vector index to disk** | File I/O | ~5-20ms | 2h | Writes full index + idmap + meta |
| 2j. Embed source item vector | ONNX inference | ~20-50ms | 2g | Source content embedding |
| 2k. **Save vector index to disk** | File I/O | ~5-20ms | 2j | **Second save** for same item |
| 2l. Observability metadata | SQLite write | ~1ms | 2g | Provenance |

**Key**: After step 2g, the memory objects are committed and lexically searchable. Steps 2h-2k are post-commit — a crash here loses only vector embeddings, which reconciliation can recover.

### Phase 3: Thread Rebuild (inline, conditional)
**Cost: ~0.5-4 seconds (1-2 LLM calls to Haiku)**

Triggered when the plugin's `process_item()` returns `thread_rebuild_requested=True`. Runs **inline** — the same worker immediately claims and processes the thread scope.

| Step | I/O | Cost | Notes |
|------|-----|------|-------|
| 3a. Load all thread items | SQLite reads | ~5-10ms | All items for container+thread |
| 3b. Load active thread memory | SQLite reads | ~5ms × N items | `list_memory_objects_for_source_item` per thread item |
| 3c. Collect conclusions | SQLite reads | ~5ms × N items | Active decisions/investigations per thread item |
| 3d. Build thread aggregate | in-memory | ~0ms | Concatenate thread items, truncate at 4000 chars |
| **3e. LLM thread summary** | **HTTP round-trip** | **~300ms-2s** | **Haiku** (thread_aggregation role), not Sonnet |
| 3f. **LLM task checkpoint** (conditional) | **HTTP round-trip** | **~300ms-2s** | Haiku, only if work artifacts have progress/blocker/next_step signals |
| 3g. SQLite commit + supersession | SQLite write | ~10ms | Atomic: new summary, supersede old |
| 3h. Embed + save vectors | ONNX + File I/O | ~40-70ms | Thread summary + optional task checkpoint |

The thread rebuild has a **5-iteration cap** per lease claim. If new items arrive for the same thread during rebuild, the worker re-claims and rebuilds again (up to 5 times). Each iteration runs the full LLM call.

**N+1 storage queries**: `_find_active_thread_memory_ids` and `_collect_thread_conclusions` both iterate over every source item in the thread and make a separate `list_memory_objects_for_source_item` query each. For a 20-message thread, that's ~40 SQLite queries just to prepare the thread rebuild. This grows linearly with thread length.

### Phase 4: Worker Poll Loop
**Overhead: 0-1 seconds dead time per cycle**

```
while True:
    item = process_next_source_item(...)   # claim + process + inline thread rebuild
    if item:
        continue                            # immediately try next item
    thread = process_next_thread_rebuild(...)  # orphaned thread scopes
    if thread:
        continue
    sleep(1.0)                              # nothing pending, wait
```

The 1-second sleep only triggers when the queue is empty. When items are flowing, the worker processes continuously with no idle gap between items.

### Total Per-Item Cost Summary

| Scenario | LLM Calls | Model | Est. Latency |
|----------|-----------|-------|-------------|
| Item only (no thread rebuild) | 1 | Sonnet | ~1-4s |
| Item + thread rebuild | 1 Sonnet + 1 Haiku | mixed | ~2-6s |
| Item + thread rebuild + task checkpoint | 1 Sonnet + 2 Haiku | mixed | ~3-8s |
| Burst of N items, same thread | N Sonnet + ≤5 Haiku | mixed | Items serial, rebuilds coalesce |

## What's Expensive and What Isn't

### Expensive (seconds)
1. **LLM write_extraction call** (~1-3s): Sonnet, 14-field schema, unavoidable — this is the core semantic extraction
2. **LLM thread_summary call** (~0.3-2s): Haiku, but still a network round-trip
3. **LLM task_checkpoint call** (~0.3-2s): Conditional, but adds latency when triggered
4. **Queue-empty poll delay** (1s): Only matters for the first item after a quiet period

### Cheap (milliseconds)
1. **ONNX embedding** (~20-50ms): Model cached in process memory, CPU inference
2. **SQLite operations** (~1-10ms each): Local file, WAL mode
3. **Vector index save** (~5-20ms): But happens twice per item unnecessarily

### Not a Problem
1. **ONNX model loading**: Cached in `_SESSION_CACHE` at process startup, not per-call
2. **Vector index in-memory operations**: `add()` is microseconds
3. **In-memory processing** (normalization, aggregation, result building): negligible

## Safe Optimization Opportunities

All proposals below preserve: item ordering, exactly-once processing semantics, crash recovery via reconciliation, and the existing lease-based fault tolerance.

### O1. Reduce vector index save frequency
**Savings: ~10-40ms per item (eliminates one full save per item)**
**Risk: Minimal — index is in-memory, reconciliation catches gaps on restart**

Current behavior: `vector_index.save()` called **twice per item** — once after `_embed_vector_entries()` (line 203) and once after source item embedding (line 591). Each save writes the full usearch binary + JSON idmap + JSON meta to disk.

Proposed: Save once at the end of each item's processing (after both embedding phases), or once per worker loop iteration (after all pending items are drained).

Safety argument: The vector index lives in memory. `save()` is purely a durability checkpoint. If the process crashes between adds and save, the rebuild-vector-index command reconstructs from SQLite. The existing design already tolerates this — `_embed_vector_entries` wraps everything in try/except and logs "reconciliation will catch gaps."

### O2. Parallelize source item embedding with LLM call
**Savings: ~20-50ms hidden behind LLM latency (net: faster total item time)**
**Risk: Low — source embedding text depends only on source content, not LLM output**

Current flow:
```
1. Compute source_item_embedding_text (in-memory, ~0ms)
2. Create vector index entry metadata (SQLite, ~1ms)
3. LLM extraction call (~1-3s)                          ← BLOCKS
4. SQLite commit
5. Embed memory object vectors + save
6. Embed source item vector + save                      ← COULD HAVE BEEN DONE DURING STEP 3
```

The source item embedding text is computed from `source_item.content` alone (see `agent_conversation_memory_embedding.py:source_item_embedding_text`). It doesn't depend on LLM results. The ONNX `embed()` call could run in a thread while the LLM call is in flight.

Safety argument: The ONNX session is stateless after init and safe to call from any thread (it's already process-level cached). The embedding result would be held in memory until after SQLite commit, then added to the vector index — same as today, just computed earlier.

### O3. Batch thread rebuild storage queries
**Savings: Significant for long threads — from O(N) queries to O(1)**
**Risk: None — pure read-path optimization**

Current `_find_active_thread_memory_ids()` (line 1099) and `_collect_thread_conclusions()` (line 1115) both iterate every source item in the thread and call `list_memory_objects_for_source_item()` individually. For a 20-message thread, that's ~40 separate SQLite round-trips.

A single query like "list all active memory objects supported by any source item in this thread" would reduce this to 1-2 queries regardless of thread length.

Safety argument: Read-only optimization. Same data, fewer queries.

### O4. Reduce poll interval when queue is empty
**Savings: Up to 900ms on first item after quiet period**
**Risk: None — empty claim queries are cheap**

The worker sleeps 1.0s when no items are pending. Reducing to 200ms means a newly ingested item gets claimed ~800ms sooner in the worst case. The `claim_next_source_item` query is a single UPDATE...RETURNING with no expensive scans.

Safety argument: The lease-based claiming already handles contention correctly. More frequent polls don't change processing semantics.

### O5. Decouple thread rebuild from item processing
**Savings: Highly variable — decouples item-level latency from thread-level latency**
**Risk: Moderate — requires careful thought about ordering and consistency**

Currently, thread rebuild runs **inline** after item processing. This means:
- A single item takes 2-8s instead of 1-4s
- If 5 items arrive for the same thread, the worker processes item 1, rebuilds thread, processes item 2, rebuilds thread again, etc.
- The thread rebuild scope already has its own lease table — it's designed to be processable independently

The `drain_processing_queue` loop already handles this: it tries `process_next_source_item` first, and only falls back to `process_next_thread_rebuild` when no items are pending. But `_process_source_item` bypasses this by directly claiming and running the thread rebuild inline (lines 598-605).

If thread rebuilds were left as pending scopes (not inline-claimed), the worker's existing loop would naturally:
1. Process all pending source items first (getting them to "completed" fast)
2. Then process any pending thread rebuilds

This means individual items reach "completed" status faster, and thread rebuilds naturally coalesce — if items 1-5 all request rebuilds for the same thread, the scope's `requested_at` gets bumped each time, but only one rebuild runs after the last item.

Safety argument: The thread processing scope table already supports this pattern — `_upsert_thread_processing_scope_in_session` bumps `requested_at` when a newer request arrives. The `_process_thread_rebuild_lease` already handles the re-claim-if-pending pattern. The only change is removing the inline claim at lines 598-605 of `_process_source_item`.

Risk: Thread summaries would lag further behind item processing. A query arriving during the gap between "last item processed" and "thread rebuild done" would see stale thread summaries. But individual memory objects (decisions, investigations) would already be available.

### O6. Concurrent processor workers
**Savings: Proportional throughput gain for burst ingestion**
**Risk: Low for source items, moderate for thread rebuilds**

The supervisor already supports `--processors N`. The claim mechanism is atomic (UPDATE...RETURNING with WHERE conditions). Multiple workers can safely claim and process different source items concurrently.

The constraint is thread rebuilds — two workers could claim the same thread scope if they process items from the same thread simultaneously. The lease mechanism prevents double-execution, but one worker would fail to claim and skip the rebuild.

Safety argument: Already designed for this. The lease-based claiming handles contention correctly. SQLite's WAL mode allows concurrent reads, and the atomic UPDATE...RETURNING prevents double-claims.

### O7. Expose processing state in query response
**Savings: No processing speedup, but enables smart consumer behavior**
**Risk: None — additive API change**

The query response gives no signal about pending processing. Adding a field like `pending_in_scope: int` (count of pending/processing items in the queried container/thread) would let consumers:
- Distinguish "no relevant memory" from "memory not processed yet"
- Implement their own retry/wait logic
- Show UX indicators ("thinking..." / "memories loading")

This matters for production integrations where the consumer can choose to wait 1-2s and re-query if processing is in flight.

### O8. Merge thread summary + task checkpoint into one LLM call
**Savings: ~0.3-2s (eliminates one Haiku round-trip when task checkpoint is triggered)**
**Risk: Low-Medium — requires schema merge and post-processing split**

#### Current state: two separate calls

When a thread rebuild triggers and work artifacts qualify for a task checkpoint, two sequential Haiku calls are made:

**Call 1 — Thread summary** (always runs):
- Input: thread items (up to 4000 chars), carried conclusions, selected work artifacts
- Schema: `{"summary": "string", "retrieval_context": "string or null"}`
- Output used for: `thread_summary` memory object, then fed as input to call 2

**Call 2 — Task checkpoint** (conditional, runs when work artifacts have progress/blocker/next_step):
- Input: the `summary` from call 1, carried conclusions, selected work artifacts (up to 3200 chars)
- Schema: `{"summary", "task", "current_state", "key_findings", "blocker_state", "next_step", "evidence", "freshness_signal", "retrieval_context"}`
- Output used for: `task_checkpoint` memory object

#### The dependency

Call 2's user prompt includes `Thread summary: {summary}` — it consumes the summary produced by call 1. This is the sequential dependency that currently prevents parallelization.

However, the task checkpoint prompt uses the summary as **contextual grounding**, not as a strict derivation input. The checkpoint's own fields (`task`, `current_state`, `key_findings`, `blocker_state`, `next_step`) are extracted from the same underlying material (conclusions + work artifacts) that the thread summary was built from. The checkpoint code also has extensive fallback defaults (`_default_task_checkpoint_*` functions) that derive every field from conclusions and work artifacts directly, bypassing the LLM output when it returns weak values.

#### Merge proposal

A single LLM call with a combined schema:

```json
{
  "summary": "string",
  "retrieval_context": "string or null",
  "task_checkpoint": {
    "summary": "string",
    "task": "string",
    "current_state": "string",
    "key_findings": ["string"],
    "blocker_state": "string",
    "next_step": "string",
    "evidence": ["string"],
    "freshness_signal": "string",
    "retrieval_context": "string or null"
  }
}
```

The system prompt would combine both instructions. The LLM receives the same thread material and work artifacts once, and produces both outputs in one response.

#### Safety considerations

- **Schema complexity**: The combined schema has ~12 fields. The write_extraction schema already has 14 fields and works with Sonnet. Haiku handles the simpler thread summary and checkpoint schemas individually — a combined schema is within Haiku's capability but should be validated.
- **Fallback robustness**: The task checkpoint post-processing already handles weak/missing LLM output via `_default_task_checkpoint_*` functions. If the merged response produces a weak checkpoint section, the same fallbacks apply.
- **Conditional execution**: The checkpoint is only built when `_should_build_task_checkpoint(selected_work_artifacts)` is True. The merged call would always include the checkpoint schema fields but the post-processing would still skip building the memory object when the condition is False. Alternatively, the merged prompt could be used only when the condition is True, falling back to the current single-schema call otherwise.
- **Prompt provenance**: Each memory object currently records its own `prompt_schema_id` and `prompt_schema_version`. A merged call would need a new schema id (e.g., `thread_summary_and_checkpoint_extraction`) to maintain provenance accuracy.

#### Impact estimate

Thread rebuilds with task checkpoints go from 2 Haiku calls to 1. At ~0.3-2s per Haiku round-trip, this saves 0.3-2s per qualifying thread rebuild. This affects threads with active work artifacts (progress/blocker/next_step signals) — the exact scenario where latency matters most (resumed-work continuity).

#### Prior art

The MEMORY.md notes "LLM call consolidation: thread rebuild 4→1-2 calls, consolidation 2→1." The current 2-call design was already a consolidation from an earlier 4-call design. Merging to 1 call is the natural next step in that progression. The inline enrichment optimization (retrieval_context folded into the summary/checkpoint schemas instead of a separate enrichment call) is the same pattern.

## What NOT to Optimize

### Don't skip the LLM extraction call
The write_extraction call is the core of Pallium's value. It extracts typed memory, work-state signals (progress, blockers, next steps, constraints, key findings), and the `is_low_value_meta` signal. Every item needs this call — the semantic signals feed thread aggregation, consolidation, routing, and injection decisions downstream. Skipping it based on surface heuristics would break the pipeline.

### Don't batch LLM calls across items
Each source item is an independent extraction. The LLM prompt includes the source item's content, metadata, and type — there's no meaningful sharing between items. Batching would add complexity without reducing per-item latency.

### Don't move processing into the API request path
The async processing architecture is correct for production. Synchronous processing would block the API response, adding 2-8 seconds to every ingest call. The consumer would wait for processing on ingest instead of waiting for it on query — same total latency, worse UX.

## Recommended Priority

| Priority | Change | Item Latency Savings | Burst Throughput | Complexity |
|----------|--------|---------------------|------------------|------------|
| **P1** | O1: Batch vector saves | -10-40ms/item | better | Low |
| **P1** | O4: Reduce poll interval | -800ms first-item | same | Trivial |
| **P2** | O8: Merge thread summary + task checkpoint LLM calls | -0.3-2s per qualifying rebuild | better | Medium |
| **P2** | O5: Decouple thread rebuild | -0.5-4s per item (item status) | much better | Medium |
| **P2** | O3: Batch thread rebuild queries | -50-200ms per rebuild | better | Low |
| **P2** | O7: Processing state in query | enables consumer adaptation | n/a | Low |
| **P3** | O2: Parallel source embedding | -20-50ms hidden | marginal | Medium |
| **P3** | O6: Concurrent workers | proportional | much better | Config only |

## Appendix: LLM Call Map (Corrected)

| Processing Phase | LLM Role | Model | Calls | Notes |
|-----------------|----------|-------|-------|-------|
| Source item processing | write_extraction | **Sonnet** | 1 | Quality-critical, 14-field schema |
| Thread rebuild | thread_aggregation | **Haiku** | 1 | Simpler schema, benchmarked equal |
| Thread rebuild (conditional) | thread_aggregation | **Haiku** | 0-1 | Task checkpoint, only with work artifact signals |
| Consolidation | consolidation | **Haiku** | 1 per group | Pattern/continuity memory (either/or, never both) |
| Query (conditional) | query_ambiguity_resolution | **Haiku** | 0-1 | Only for bounded ambiguity pairs |

### LLM Call Merge Analysis

Prior consolidation (already shipped): thread rebuild went from 4 calls → 1-2 calls by folding retrieval enrichment into the thread summary and task checkpoint schemas as an inline `retrieval_context` field. The separate `write_enrichment` LLM call is no longer made during thread rebuild — `_apply_inline_enrichment()` is purely in-memory.

Remaining merge opportunity: **thread summary + task checkpoint → 1 call** (see O8 above). The task checkpoint's input is a strict subset of the thread summary's input (summary + conclusions + work artifacts). The sequential dependency (checkpoint uses thread summary text) is soft — the checkpoint's fallback defaults derive all fields from the same underlying material.

No other merge opportunities exist in the per-item path:
- **write_extraction** (Sonnet) cannot merge with thread rebuild (Haiku) — different models, different processing phases, item-level vs thread-level
- **Consolidation** is a separate background pass, not per-item
- **query_ambiguity_resolution** is on the read path, not the write path

## Appendix: Vector Embedding Details

- **ONNX model**: Loaded once at startup, cached in process-level `_SESSION_CACHE`. No per-call model loading.
- **ONNX inference**: ~20-50ms for single text, CPU-only (`CPUExecutionProvider`)
- **usearch index**: In-memory, exact cosine search (brute-force at current scale)
- **Save frequency**: Twice per item minimum — once for memory object vectors, once for source item vector
- **Durability model**: In-memory index is authoritative. Disk save is a checkpoint. `rebuild-vector-index` reconstructs from SQLite if needed.
- **Model**: BAAI/bge-small-en-v1.5 (384 dims, CLS pooling + L2 norm)

## Appendix: Ordering and Consistency Properties

The current pipeline preserves these properties that any optimization must maintain:

1. **Source items are claimed FIFO** by `created_at ASC` — ordering is deterministic
2. **Each item is processed exactly once** (or retried up to `max_attempts` with backoff)
3. **Thread rebuild sees all completed items** — it queries `list_source_items_for_thread` which reads committed rows
4. **Supersession is atomic** — old thread summaries are superseded in the same transaction as new ones are created
5. **Vector embedding is post-commit** — if embedding fails, the memory object is still in SQLite and lexically searchable; reconciliation can add the vector later
6. **Lease-based fault tolerance** — if a worker crashes mid-processing, the lease expires and another worker can re-claim the item
