---
id: investigate-thread-level-interest-and-threadless-aggregation
title: Investigate thread-level interest extraction and threadless aggregation
status: paused
priority: medium
commitment: uncommitted
milestone: Next
---

> **Paused 2026-06-27** pending outcome of the abstention-policy work in
> [`docs/specs/2026-06-27-injection-policy-abstention.md`](../../docs/specs/2026-06-27-injection-policy-abstention.md).
> The data analysis under that spec showed:
> 1. `interest` (where it still appears in data) and adjacent
>    aggregation-style types (`fact_summary`, `thread_summary`) have
>    poor score separability and high off-topic rates.
> 2. `fact_summary` will be suspended in Phase 3b for insufficient
>    signal; `thread_summary` becomes explicit on-demand only.
> 3. Investing in better thread-level interest extraction is unlikely
>    to pay off until proactive vs on-demand delivery for these classes
>    is settled.
>
> Resume gate: Phase 6 measurement results show a real demand for a
> thread-level aggregation memory class that the abstention policy
> can't satisfy.

## Summary

Investigate moving interest memory creation from per-item extraction to thread aggregation, and how to handle non-threaded sources (no `thread_ref`) for aggregation in general.

## Why

Per-item interest extraction has two structural limitations observed in chat-lite testing:

1. **Subject loss** — Messages like "is there something lite and easy to use?" lose the subject ("vector databases") because per-item extraction has no conversation context. The LLM produces `interest_text: "lightweight and easy-to-use open source software"` instead of referencing vector databases.

2. **Borderline over-promotion** — Present-tense topic statements ("I'm thinking about vector dbs") are classified as interest even though they're not future-oriented. Thread-level context would let the LLM make better judgments.

Thread aggregation already has full conversation context and follows an established pattern (task_checkpoint). Interest could follow the same pattern — the thread summary LLM call already sees everything.

## Key Design Questions

### 1. Thread-level interest extraction

The simplest approach: add an optional `interests` array to the thread summary response schema:

```json
{
  "summary": "string",
  "retrieval_context": "string or null",
  "interests": [{"subject": "string", "context": "string"}]
}
```

No additional LLM call — piggybacks on the existing thread summary call. The LLM has full thread context and can correctly identify "user expressed interest in Chroma as a lightweight vector database" even when the interest was spread across multiple messages.

Per-item `interest_text` extraction would still run as a signal (useful for the decision gate: "does this thread contain any interest signals?"), but the actual interest memory object would be created from the thread-level response.

### 2. Non-threaded sources (no thread_ref)

Many real-world sources don't have threading: Slack channels (main channel), flat chat streams, notification feeds. If `thread_ref` is null, thread aggregation never fires, and thread-level interest detection would miss those conversations.

**Proposed principle:** No `thread_ref` = main thread. All items without `thread_ref` in a container belong to one implicit "main thread" and should be aggregated.

**Scale concern:** A threaded conversation has natural boundaries (thread starts and ends). A flat channel's "main thread" grows indefinitely. The thread aggregation prompt truncates to `THREAD_SUMMARY_MAX_TEXT_CHARS` (4000 chars), so older messages would be missed.

**Windowing options to investigate:**
- **Time or count windows** — aggregate every N messages or every T minutes, producing a thread_summary per window
- **Gap-based boundaries** — time gaps (e.g., 30+ min silence) create implicit thread boundaries
- **Consolidation handles it** — periodic small aggregations feed into the existing tiered consolidation (thread_summary → pattern_memory / continuity_memory)

### 3. De-duplication

If both per-item and thread-level produce interest about the same subject, need a supersession rule. Options:
- Thread-level interest supersedes per-item interest for the same thread (cleanest)
- Per-item interest falls through to turn_summary when thread aggregation is available
- Deduplicate on subject+container at creation time

## Dependencies

- `add-interest-memory-kind` (committed, in-progress) — the basic interest type must land first
- The threadless aggregation question affects all thread-level memory types, not just interest — this is a broader architectural decision

## Out of Scope

- IDF-weighted lexical scoring (separate work, addresses off-topic injection independently)
- Interest aging or supersession by decisions/checkpoints
- Multi-language support for interest detection

## Investigation Deliverables

1. Prototype thread summary schema with `interests` field — test with real LLM
2. Evaluate non-threaded aggregation strategies (windowing vs gap-based vs consolidation-only)
3. Measure token budget impact of adding `interests` to thread summary prompt
4. Decision: move interest fully to thread aggregation, or keep per-item as fallback?
