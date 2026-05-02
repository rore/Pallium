# Investigation: Semantic Deduplication at Storage Time

**Date:** 2026-05-02  
**Status:** Concluded — not worth building  

## Bottom Line

**Don't build this.** Empirical analysis of the live database (862 active memories, 965
vector entries) shows:

- True duplicate rate is ~6% (exact or near-exact text matches)
- Vector similarity alone has unacceptable false-positive rate — it cannot distinguish
  "same info, different extraction" from "same topic, different info"
- A safe dedup system would require vector similarity + textual overlap checking,
  making it non-trivial
- Injection-time dedup already prevents duplicate injection at query time
- The storage cost of ~50 redundant memories is negligible at current scale

The problem is real but small, and the existing mechanisms (injection-time dedup,
canonical_key supersession, fact consolidation) are adequate.

## Empirical Evidence

Analysis script: `scripts/analyze_duplicates.py`

### Raw numbers (live DB, 2026-05-02)

| Threshold | Duplicate pairs | Memories involved | % of active |
|-----------|----------------|-------------------|-------------|
| 0.92 | 4,743 | 600 | 69.7% |
| 0.96 | 318 | 266 | 30.9% |
| 0.98 | 45 | ~80 | ~9% |

### Why these numbers are misleading

Manual inspection of the top pairs at 0.96 threshold reveals:

| Category | Example | Should dedup? |
|----------|---------|---------------|
| True exact dupe | Same text extracted 20s apart | Yes |
| Same fact, updated | "$1.05 of $1.19" → "$1.09 of $1.16" | Maybe |
| Opposite facts | "80% when gold in context" vs "20% when NOT" (sim=0.997) | **No** |
| Same structure, different values | "failed metric" vs "completed metric" (sim=0.996) | **No** |
| Same topic, different events | 5 fact_summaries about "quality plan" with different info | **No** |
| Shared context embedding | Different decisions with same thread context vector (sim=1.0) | **No** |

**The false-positive rate at any usable threshold (0.92-0.98) is too high to safely
supersede memories automatically.**

### Root causes of false positives

1. **Structural similarity ≠ semantic equivalence.** The embedding model produces high
   similarity for text that follows the same pattern with different values (e.g.,
   "X achieved 80%" vs "X achieved 20%"). These carry opposite information.

2. **Topic clustering.** Memories about the same subject (e.g., "Memory quality
   improvement plan") cluster above 0.96 even when they carry distinct information
   about different events/decisions.

3. **Context embedding artifacts.** 243 memories have only shared context embeddings
   (e.g., `thread_summary_context.embedding`) — shared across all memories from the
   same source item. Any two from the same source appear identical by construction.

4. **Short text instability.** Short decisions (5-10 words) produce embeddings
   dominated by the template prefix rather than content, making unrelated short texts
   appear identical.

### True duplicates are rare and harmless

The genuinely redundant memories (~50 out of 862) are:
- Exact-text duplicates from race conditions or re-processing
- Progressive fact updates where the old version carries stale numbers

These are already handled:
- Injection-time dedup prevents showing both at query time
- Fact consolidation merges atomic_facts over time
- The storage cost is negligible (~50 extra rows in SQLite)

## What would be needed to make this safe

A viable dedup system would require **both** signals:
1. High vector similarity (≥0.96) as a candidate filter
2. High textual overlap (token Jaccard ≥0.7 or normalized edit distance ≤0.3) as confirmation

This is essentially what injection-time dedup already does — but at write time. The
added complexity is not justified given the low true-duplicate rate.

## Existing Mechanisms (Still Adequate)

1. **Source-level idempotency** — same `(source_type, source_id)` won't be processed twice
2. **Canonical_key supersession** — newer decision/investigation with same key supersedes older
3. **Fact extraction dedup** — token-normalized dedup within a single extraction call
4. **Injection-time dedup** — near-duplicate candidates collapsed before injection (text overlap ≥0.7)
5. **Fact consolidation** — groups atomic_facts into fact_summary, handles contradictions

## If the problem grows

If future scale makes duplicates problematic (e.g., >20% true duplicates or noticeable
retrieval degradation):

1. **Cheapest intervention:** Run `scripts/analyze_duplicates.py` periodically to
   measure. If the rate grows, tighten fact extraction dedup (seed from more existing facts).

2. **Next step if needed:** Add textual overlap check to the reconcile loop — embed new
   memory, find k=5 nearest same-type/container, check text overlap ≥0.7 before
   superseding. This is the two-signal approach described above.

3. **Integration point (if ever built):** `VectorEmbedder.reconcile()` in
   `core/vector_embed.py` — when embedding a new entry, search for near-duplicates,
   confirm with text overlap, then supersede. ~50-60 lines.

## Architecture Notes (for future reference)

- Worker process has `enable_vector=False` — no vector index or embedding provider
- Vector index lives exclusively in the server process
- Reconciliation thread runs every 2s, processes up to 50 entries per cycle
- The reconcile loop's fast-path (`if sqlite_count == index_count: return`) means
  already-reconciled entries are never re-examined
- Any dedup added to reconcile would only catch NEW entries, not retroactive cleanup
  (a separate sweep would be needed for existing data)
