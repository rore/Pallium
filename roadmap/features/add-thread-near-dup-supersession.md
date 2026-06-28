---
id: add-thread-near-dup-supersession
title: Thread + per-item near-duplicate supersession
status: done
priority: high
commitment: committed
milestone: Done
shipped_at: 2026-06-28
---

## Summary

Close the byte-equality blind spot in the supersession path that left
near-paraphrased `decision` and `investigation_outcome` memories
piling up. T2 (commit f9af592, 2026-06-04) anchored `canonical_key` on
`normalize_for_index(decision_text|investigation_text)` and widened
supersession to container scope, but kept exact-equality matching.
LLM paraphrases on later rebuilds produced different canonical_keys →
no supersession hint → duplicates accumulated.

The fix adds `difflib.SequenceMatcher.ratio >= 0.85` as the second
similarity gate, in two layers:

1. **Thread-aggregation writer** ([`semantic/agent_conversation_memory_threads.py`](../../semantic/agent_conversation_memory_threads.py))
   — `_supersedes_prior` walks same-thread prior `conclusions`,
   emits a hint carrying the OLD record's canonical_key so the
   resolver's existing exact-equality lookup matches without any
   resolver change.
2. **Resolver** ([`storage/sqlite_queue.py`](../../storage/sqlite_queue.py))
   — `_SIMILARITY_ELIGIBLE_TYPES` branch in
   `_resolve_supersession_pairs_in_session` catches per-item
   (`source_type='claude-code'`/`'codex'`) paraphrases that the thread
   writer can't see (no shared `conclusions` list). Runs after the
   existing exact-CK and constraint-Jaccard branches.

## Why

Live dashboard observation showed threads with dozens of active
near-paraphrased investigations (one thread had 48 active
`investigation_outcome` memories, several of them paraphrases of the
same finding). Validated against the live DB on 2026-06-28: 467
active near-dup pairs at sim≥0.85 across the corpus pre-fix.

This was a write-path bug, not a retrieval bug — but the dup
accumulation makes injection/measurement noisier and the dashboard
harder to read.

## Spec

[`docs/specs/2026-06-28-thread-near-dup-supersession.md`](../../docs/specs/2026-06-28-thread-near-dup-supersession.md)

## What shipped

- [x] Thread-aggregation writer: `_supersedes_prior` helper +
      similarity-driven hint emission (commit `d078462`)
- [x] Idempotent backfill script
      (`scripts/backfill_thread_near_dups.py`) with `--scope`
      thread / per-item / both — converges in one execute
- [x] Read-only measurement eval
      (`evals/injection_policy_2026_06/near_dup_measure.py`) reporting
      per-bucket counts, fix-C simulation at multiple thresholds, and
      noisy-thread top-N
- [x] Phase 5b match-text source-of-truth: shared
      `build_memory_match_text` in
      `semantic/agent_conversation_memory_embedding.py`, surfaced via
      `MemoryExpandResponse.match_text`. Closes a code-review finding
      that the usage-audit populator's 7-key scalar coalesce
      undercounted real memory references (commit `aebec85`)
- [x] Resolver-side container-scoped similarity branch in
      `storage/sqlite_queue.py` for per-item supersession (commit
      `741eb0c`)
- [x] Code-review P1/P2 follow-ups: `(container_ref, source_id, type)`
      bucket key in backfill `_plan`; same shape in eval simulator
      and noisy-thread reporting

## Live-DB outcome

| Source type | Active near-dup pairs (sim≥0.85), pre-fix | Post-backfill |
|---|---|---|
| `thread_detection` | 467 same-source pairs | 5 (all cross-source — out of scope) |
| `claude-code` (per-item) | 4 | 0 |
| `codex` (per-item) | 0 | 0 |

Backfill applied 282 + 14 = 296 supersessions across two rounds. Same
runtime fix prevents future accumulation.

## Out of scope / future

- Cross-source (different threads, same container) same-canonical_key
  pairs — 5 active residual at sim≥0.85. Would require broadening the
  thread writer's `conclusions` collection or a separate background
  sweep.
- Constraint-memory near-dup similarity — constraints have their own
  Jaccard branch (`_JACCARD_ELIGIBLE_TYPES`) at threshold 0.5 and are
  intentionally excluded from `_SIMILARITY_ELIGIBLE_TYPES`.
