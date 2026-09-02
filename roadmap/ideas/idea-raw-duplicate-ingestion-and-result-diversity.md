---
id: idea-raw-duplicate-ingestion-and-result-diversity
title: Duplicate raw turns consume top-K capacity
status: superseded
priority: medium
commitment: uncommitted
---

> **Superseded 2026-09-02 -> `fix-real-corpus-memory-access-and-evaluation`.**
> The real-corpus audit supplied the material duplicate-slot evidence this idea
> required. Its provenance-preserving result-diversity scope and edge cases now ship
> as ordered work inside the committed measurement-integrity item rather than as a
> separate speculative optimization.

> **Sequencing note 2026-08-18.** Split this: **measure duplicate prevalence FIRST** (cheap — count
> identical-content, distinct-id results in real top-K). Only build ingest idempotency / result collapsing
> if duplicates *materially* waste top-K slots or tokens in the real-corpus experiment. Don't build the
> collapser on spec.

## Summary

Raw history search can return adjacent pairs of identical content under distinct source IDs, so a few
top slots represent only one or two unique pieces of information. Ingest idempotency is keyed on
`(source_type, source_id)` only — no content hash — and retrieval dedups on `(target_kind, target_id)`
only, so identical content under a new id survives as a separate candidate.

## Why

Verified against the code:
- `core/service.py:280-282` (and retry `:371-373`) — idempotency via `find_source_item(source_type, source_id)` (`storage/sqlite.py:169`); no content-hash column or content-equality check anywhere in ingest.
- `retrieval/lexical.py:124,136-139` and `retrieval/vector.py:123,181-184` — `seen` keyed on `(kind, id)`; two ids with identical text never collide, so both emit. No near-duplicate collapse.

Reduces diversity, candidate recovery, and usable context per token, and undercuts perceived retrieval
quality. First identify the duplicate class (same event re-ingested / dual-hook / legitimate repetition
/ storage retry / near-duplicate) before choosing a fix.

## In Scope

- Ingestion idempotency for actual duplicate *events* (content hash or external event id).
- Retrieval-time exact/near-duplicate collapsing that preserves aggregated provenance (all contributing
  source ids), without erasing legitimately repeated decisions from different dates/actors/contexts.

## Out of Scope

- Semantic supersession of derived memories (`add-thread-near-dup-supersession`, Done — that is
  writer-side derived collapse, not raw-result diversity).

## Done When

1. Ingest idempotency: same payload twice with the same external event id → one logical source item, one retrievable result, retry observable in audit.
2. Dual-hook: if transcript+stop hooks can observe one message, the real sequence yields one source item.
3. Retrieval diversity: exact duplicates under separate ids → duplicates don't occupy multiple visible positions; freed slots fill with distinct results; provenance records all contributing ids.
4. Legitimate repetition (two sessions / two actors / different times) is NOT wrongly merged; the contract states whether collapsing is per event, per session, or per result page.
5. Near-duplicate variants (whitespace/formatting/punctuation) handled; if semantic dedup is added, false-positive cases (similar wording, different decision) are tested.

## Notes

External-review register item 8 (Medium). Related: `add-async-ingest-queue-and-worker-processing`,
`add-thread-near-dup-supersession`.
