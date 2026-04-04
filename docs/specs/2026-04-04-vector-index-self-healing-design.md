# Vector Index Self-Healing — Design

**Date:** 2026-04-04
**Status:** Draft

## Problem

When the LLM provider has transient connection errors, items are ingested into SQLite but the
semantic processor fails to generate embeddings. This creates a count mismatch between SQLite
vector index entries and the usearch in-memory vector index. On the next startup, Pallium detects
the mismatch and disables the vector index entirely — meaning a transient upstream outage
permanently degrades retrieval (no vector search) until someone manually runs
`rebuild-vector-index`.

Additionally, retention deletes index entries from SQLite without touching the usearch index file,
creating the reverse mismatch (stale entries in usearch that SQLite no longer knows about).

A production sidecar must self-heal from transient failures without manual intervention.

## Root Cause Analysis

Three independent failure paths create SQLite ↔ usearch mismatches:

### Path A: Source item vector entry orphan

In `core/processing.py:177`, `build_source_item_vector_entry()` writes a vector IndexEntry to
SQLite **before** the LLM call. If the LLM fails at `plugin.process_item()`, the exception handler
returns early. The SQLite vector entry exists but was never embedded into usearch. On retry, the
duplicate check in `build_source_item_vector_entry` finds the existing entry and skips creation —
so the orphan persists even if the retry succeeds.

**Direction:** SQLite > usearch.

### Path B: Memory object embedding failure after commit

`embed_process_result()` runs after `commit_processed_source_item()`. If embedding fails (provider
error, OOM, etc.), the exception is caught and swallowed. Memory object vector entries exist in
SQLite (written during commit) but have no corresponding usearch vectors.

**Direction:** SQLite > usearch.

### Path C: Retention deletes SQLite entries without usearch cleanup

Retention deletes source items, memory objects, and their index entries from SQLite. The usearch
index file is not updated — stale vectors remain. The lazy cleanup in
`VectorRetrievalProvider.query()` removes stale entries when they appear in search results, but
low-similarity stale entries may never surface in top-k and persist indefinitely.

**Direction:** usearch > SQLite.

### Current behavior on mismatch

`app/dependencies.py:261-273` compares counts at startup. Any mismatch disables the vector index
entirely. The only recovery is the manual `rebuild-vector-index` CLI command.

## Design

Three complementary changes that eliminate each failure path and add ongoing self-healing.

### Change 1: Embed source item vector entry regardless of LLM outcome

**What:** Keep `build_source_item_vector_entry()` before the LLM call (preserving the accepted
decision at `docs/context/decisions.md` — "Decoupled from semantic processing success, persisted
before processing, survives extraction failures"). Fix the orphan by ensuring the usearch embedding
always runs, even when the LLM call fails.

**Why:** `source_item_embedding_text()` is a pure function of the source item content — it doesn't
need LLM output. During sustained LLM outages, source items ingested during the outage should
still be vector-searchable via their raw content. The original code creates the SQLite entry
pre-processing (correct) but only embeds into usearch post-success (the bug).

**Implementation:** Two small changes in `_process_source_item()`:

1. Initialize `memory_vectors_added = False` before the try block.
2. Remove the `return` at the end of the `except` block.

This lets the source vector embedding code (lines 263-268, currently after the try/except) run
regardless of whether processing succeeded or failed. On the failure path,
`memory_vectors_added` is `False` and only `source_vector_added` matters. All success-path logic
(provenance, observability emission) is inside the try block and unaffected.

**Current flow:**

```
build_source_item_vector_entry(...)     # creates SQLite entry (pre-LLM)
try:
    process_item(...)                   # LLM call
    commit(...)
    memory_vectors_added = embed_process_result(...)
    ... observability ...
except:
    fail_source_item_processing(...)
    return                              # ← BUG: skips source vector embedding

embed_and_persist_vector_entry(...)     # UNREACHABLE on failure
save_vector_index()
```

**Fixed flow:**

```
build_source_item_vector_entry(...)     # creates SQLite entry (pre-LLM)
memory_vectors_added = False            # ← NEW: initialize before try
try:
    process_item(...)                   # LLM call
    commit(...)
    memory_vectors_added = embed_process_result(...)
    ... observability ...
except:
    fail_source_item_processing(...)
                                        # ← FIXED: no return, fall through

embed_and_persist_vector_entry(...)     # ALWAYS reached
save_vector_index()
```

**Retry path:** If attempt 1 embeds the source vector into usearch (via this fix), the retry's
`build_source_item_vector_entry` finds the existing SQLite entry (duplicate check) and returns
`None` — correct, since the vector is already in usearch. The edge case where both the LLM call
and the local embedding fail on the same attempt is rare (ONNX is local) and covered by
reconciliation (Change 3).

**Decision doc update:** Update `docs/context/decisions.md` entry "Plugin-owned SourceItem
embedding" to note that the usearch embedding now runs regardless of LLM outcome, strengthening
the original "survives extraction failures" property.

**File:** `core/processing.py`

### Change 2: Startup — warn and continue (don't disable)

**What:** Replace the startup count mismatch check that disables the vector index with a warning
log that continues with the index enabled.

**Why:** A mismatch where SQLite > usearch means reduced recall, not crashes or wrong results —
usearch search only returns entries it has. A mismatch where usearch > SQLite is handled by the
existing lazy cleanup in `VectorRetrievalProvider.query()` (stale entries removed on access). In
both cases, continuing is safe and runtime reconciliation fills the gaps.

**Behavior:**

- Count mismatch detected: log `WARNING` with counts, continue startup.
- Vector index is enabled with whatever entries it has.
- Runtime reconciliation (Change 3) fixes gaps during normal operation.
- The `rebuild-vector-index` CLI command remains available for manual recovery if needed.

**File:** `app/dependencies.py`

### Change 3: Worker-integrated bidirectional reconciliation

The main self-healing mechanism. Runs as a third idle-time duty in the existing worker loop,
following the same pattern as thread rebuilds.

#### Reconciliation algorithm

The `VectorEmbedder` gains a `reconcile(batch_size=50) -> int` method:

1. **Fast-path count check.** Compare `storage.count_index_entries_by_type("vector")` vs
   `vector_index.entry_count()`. If equal, return 0. This makes the common case (no gaps) a
   single cheap SQLite count query + in-memory integer comparison.

2. **Load ID sets.** Get `sqlite_ids` from `storage.list_index_entries_by_type("vector")` and
   `usearch_ids` from `vector_index.known_entry_ids()` (new accessor).

3. **Forward direction — embed missing entries (SQLite > usearch).** Diff `sqlite_ids - usearch_ids`.
   Take up to `batch_size` missing entries. Embed them via the embedding provider. Add to the
   in-memory usearch index.

4. **Reverse direction — remove stale entries (usearch > SQLite).** Diff `usearch_ids - sqlite_ids`.
   Remove all stale entries from usearch. This is cheap (no embedding, just dict + index removal)
   so no batching needed.

5. **Save.** Persist the updated index to disk.

6. **Return** total number of entries changed (embedded + stale removed). Return 0 when no work
   was done or on error — failures are logged and swallowed, matching existing VectorEmbedder
   patterns.

#### New VectorIndex accessor

`known_entry_ids() -> frozenset[str]` — returns the set of entry IDs currently in the index.
Backed by `self._id_to_key.keys()`.

#### Worker loop integration

In `app/worker.py`, reconciliation is the third idle-time duty after source item processing and
thread rebuilds:

```
loop:
  1. process_next_source_item → if found, continue
  2. thread_rebuild → if found, continue
  3. reconcile_vector_index → if reconciled any, continue
  4. nothing to do → sleep(poll_interval)
```

When reconciliation returns > 0, the worker loops back immediately to check for higher-priority
work (source items, thread rebuilds) before continuing reconciliation. This means reconciliation
runs in batches, yielding to processing between batches.

#### PalliumService delegation

`PalliumService.reconcile_vector_index() -> int` — thin delegation to
`self._vector_embedder.reconcile()`.

#### Logging

Worker logs reconciliation activity the same way it logs processing and thread rebuilds:
```
worker_id=<id> vector_reconciliation embedded=<n> removed_stale=<n>
```

#### Properties

- **No new infrastructure.** Uses the existing worker loop pattern.
- **Cheap when healthy.** Fast-path count check avoids loading entries when counts match.
- **Batch-bounded.** Forward direction limited to `batch_size` per cycle. Reverse direction is
  unbounded but cheap (no embedding).
- **Yields to priority work.** Each batch loops back through source items and thread rebuilds
  before continuing reconciliation.
- **Idempotent.** Running reconciliation multiple times is safe — already-embedded entries are
  skipped by usearch `add` (which replaces), already-removed entries raise KeyError caught by
  VectorIndex.remove.
- **Single-writer assumption.** Matches the existing VectorIndex design (in-memory per process,
  single file on disk).

## Files Changed

| File | Change |
|---|---|
| `storage/vector_index.py` | Add `known_entry_ids()` accessor |
| `core/vector_embed.py` | Add `reconcile(batch_size)` method |
| `core/processing.py` | Remove early return on failure; init `memory_vectors_added` before try |
| `app/dependencies.py` | Mismatch: warn + continue instead of disable |
| `core/service.py` | Add `reconcile_vector_index()` delegation |
| `app/worker.py` | Add reconciliation as third idle-time duty |
| `docs/context/decisions.md` | Strengthen "Plugin-owned SourceItem embedding" entry |
| `tests/test_vector_startup.py` | Update mismatch test: expect warning, vector stays enabled |
| `tests/test_vector_reconciliation.py` | New: reconciliation forward, reverse, batch, no-op |
| `tests/test_processing.py` (or similar) | New: source vector embedded even when LLM fails |

## Out of Scope

- Multi-worker coordination (current VectorIndex assumes single-writer).
- Remote embedding provider cooldown (all current providers are local ONNX/fastembed).
- Periodic full reconciliation when counts match but IDs differ (unlikely edge case — both
  directions would have to cancel out exactly).
- Scaling beyond full-scan entry loading (known limitation, tracked separately on roadmap).
