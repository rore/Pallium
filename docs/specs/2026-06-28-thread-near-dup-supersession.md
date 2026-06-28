# Thread-rebuild near-duplicate supersession

**Date:** 2026-06-28
**Status:** Shipped (writer fix + per-item resolver branch + match-text follow-up)
**Last updated:** 2026-06-28 (per-item resolver-side similarity branch in `storage/sqlite_queue.py`)
**Owner:** Rotem Hermon
**Roadmap:** [`roadmap/features/add-thread-near-dup-supersession.md`](../../roadmap/features/add-thread-near-dup-supersession.md)
**Touches:** `semantic/agent_conversation_memory_threads.py` (writer), `storage/sqlite_queue.py` (resolver similarity branch), `core/service.py` + `api/schemas.py` + `api/routes.py` + integrations stop hooks (Phase 5b match-text)
**Companion:** commit f9af592 (T2, 2026-06-04) — preserved, not rolled back.

## Problem

The Pallium dashboard surfaced threads with dozens of active
near-paraphrased `investigation_outcome` / `decision` memories that
never got superseded. Validated against `~/.pallium/data/pallium.db`
on 2026-06-28:

- Thread `thread:d003c082-0823-4e46-afef-7fead144eb2f` had **48 active
  `investigation_outcome` memories**, several of which were paraphrases
  of "Pallium session is waiting for approval; context graph session is
  not in the same blocking state."
- Thread `thread:67d247fd-0a38-4850-9390-2837547312e8` had 38 active
  decisions producing 91 near-dup pairs (sim ≥ 0.85).
- Active near-dup pair count across all thread-derived decisions /
  investigations: 464 at sim ≥ 0.85.

99.93% of these pairs share the same `source_id` (= same thread). The
bug is purely a thread-rebuild write-path issue.

## Root cause (validated)

`build_thread_summary` in
[`semantic/agent_conversation_memory_threads.py`](../../semantic/agent_conversation_memory_threads.py)
emitted supersession hints via a comprehension that required **byte
equality** on `canonical_key`:

```python
# pre-fix:
...
for old_obj in conclusions
if old_obj.type == new_obj.type
   and old_obj.id != new_obj.id
   and str(old_obj.payload.get("canonical_key") or "").strip() == ck
```

T2 (commit f9af592, 2026-06-04) anchored `canonical_key` on
`normalize_for_index(decision_text|investigation_text)`. When the LLM
paraphrased the same conclusion on a later rebuild ("Pallium session
is waiting for **user** approval" vs "Pallium session is waiting for
approval **while** the context-graph session is not"), the
canonical_keys differed at the byte level. The comprehension produced
zero hints, the old row stayed active, and duplicates accumulated.

## Fix

Replace the byte-equality match with a `SequenceMatcher` ratio
threshold over the normalized `canonical_key`. A helper:

```python
def _supersedes_prior(new_canonical_key, old_memory_object, *, threshold=NEAR_DUP_THRESHOLD) -> bool:
    if not new_canonical_key: return False
    old_ck = str(old_memory_object.payload.get("canonical_key") or "").strip()
    if not old_ck: return False
    if old_ck == new_canonical_key: return True   # exact-equality fast path preserved
    return SequenceMatcher(None, old_ck, new_canonical_key).ratio() >= threshold
```

The hint emission was rewritten as an imperative loop so that:

1. It walks `conclusions` (this thread's prior active rows) for each
   new decision/investigation_outcome.
2. It emits the hint carrying the **OLD** record's `canonical_key`, not
   the new one. This matches the resolver's exact-equality lookup at
   [`storage/sqlite_queue.py:864`](../../storage/sqlite_queue.py#L864)
   (`existing_key == hint.canonical_key`) — no resolver change is
   required.
3. It records `already_paired` so one old record only supersedes once,
   preventing reciprocal A→B / B→A pairs.

### Properties preserved

- **Same-type only.** Hint emission iterates only when
  `new_obj.type == old_obj.type`.
- **Same-thread only.** `conclusions` is built from this thread's
  source items in [`core/thread_rebuild.py`](../../core/thread_rebuild.py#L687).
- **Container-scoped resolver path.** Hints still emit `thread_ref=None`,
  preserving f9af592's container-scoped supersession property for
  cross-thread duplicates that happen to share an exact canonical_key.
- **Newer supersedes older.** Each thread rebuild flips prior rows to
  `superseded`; on the next rebuild they're no longer in `conclusions`.
- **No dependency on the resolver.** Hint carries `old_ck`, so the
  resolver's `existing_key == hint.canonical_key` branch finds the old
  record. The fix is contained to `semantic/`.

### Threshold

`NEAR_DUP_THRESHOLD = 0.85`. Measured against the live database on
2026-06-28:

| Threshold | Demoted (active) | Kept (active) |
|---|---|---|
| 0.70 | 374 | 776 |
| 0.75 | 344 | 806 |
| 0.80 | 302 | 848 |
| **0.85** | **251** | **899** |
| 0.90 | 197 | 953 |
| 1.00 (exact-only) | 24 | 1126 |

A lower threshold over-merges legitimate distinct findings; a higher
threshold leaves most near-dups uncollapsed. 0.85 lands in the elbow
where the same-source/threshold rate drops fast.

To change the threshold:

1. Run `python -m evals.injection_policy_2026_06.near_dup_measure` to
   see how the candidate threshold affects demoted/kept counts.
2. Update `NEAR_DUP_THRESHOLD` in
   [`semantic/agent_conversation_memory_threads.py`](../../semantic/agent_conversation_memory_threads.py).
3. Update the threshold assertion in
   [`tests/test_thread_near_dup_supersession.py`](../../tests/test_thread_near_dup_supersession.py)
   (`test_supersedes_prior_threshold_is_0_85`).
4. Update this spec.

## Tradeoff

Legitimate small distinct findings could theoretically be merged if
they share most of their wording (e.g. two findings differing only by
one word). The test suite includes a regression case
(`test_distinct_findings_from_same_thread_not_merged`) and a
representative pre-existing test
(`test_new_canonical_key_accumulates_without_spurious_supersession`)
that uses dissimilar topic phrasing so its intent survives both pre-
and post-fix regimes. The realistic frequency in real corpora is
captured by the noise-thread output of the eval script — at 0.85, the
demotion preserves 78% of active rows.

## What this fix does NOT touch

- **Retrieval / routing.** Write-path only.
- **Per-item (`source_type='claude-code'`) extraction path.** 91% of
  observed near-dup pair members are `source_type='thread_detection'`;
  only 9% are per-item. Per-item duplicates are a separate, smaller
  issue and out of scope here.

  **Update (2026-06-28, follow-up):** the per-item case landed via a
  resolver-side branch in
  [`storage/sqlite_queue.py`](../../storage/sqlite_queue.py) —
  `_SIMILARITY_ELIGIBLE_TYPES = {"decision", "investigation_outcome"}`
  with `_CONTAINER_SCOPED_SIMILARITY_THRESHOLD = 0.85`. The per-item
  writer was already emitting container-scoped hints via
  `build_supersession_hints` in
  [`semantic/agent_conversation_memory_memory.py`](../../semantic/agent_conversation_memory_memory.py);
  it now triggers the resolver's similarity branch after the existing
  exact-equality and constraint-Jaccard branches miss. Same threshold
  as the thread writer (0.85). Tests:
  [`tests/test_resolver_similarity_branch.py`](../../tests/test_resolver_similarity_branch.py).
- **Resolver in `storage/sqlite_queue.py`.** ~~Unchanged.~~
  **Updated 2026-06-28 follow-up** to add the similarity branch
  described above.
- **`canonical_key` of any existing record.** The backfill uses the
  existing `canonical_key` field as-is and only flips lifecycle.
- **`core/contracts.py::SupersessionHint`.** The hint carries `old_ck`
  in the `canonical_key` field — within the existing contract.

## Eval / measurement / backfill

| Artifact | Path |
|---|---|
| Measurement script | [`evals/injection_policy_2026_06/near_dup_measure.py`](../../evals/injection_policy_2026_06/near_dup_measure.py) |
| Idempotent backfill | [`scripts/backfill_thread_near_dups.py`](../../scripts/backfill_thread_near_dups.py) |
| Tests | [`tests/test_thread_near_dup_supersession.py`](../../tests/test_thread_near_dup_supersession.py) |

Run order after the fix lands:

```bash
# 1. Measure current state
python -m evals.injection_policy_2026_06.near_dup_measure --output before.json

# 2. Backfill existing dups (dry-run first)
python -m scripts.backfill_thread_near_dups --db-path ~/.pallium/data/pallium.db
python -m scripts.backfill_thread_near_dups --db-path ~/.pallium/data/pallium.db --execute

# 3. Re-measure
python -m evals.injection_policy_2026_06.near_dup_measure --output after.json
```

## Future work (NOT in scope here)

- ~~Per-item paraphrase supersession (~9% of the active near-dup
  population). Requires a different mechanism since per-item hints
  emit at write time without seeing prior conclusions; would need
  either a read-back step or a queue-side similarity probe. Track
  separately.~~ **Landed 2026-06-28 (resolver similarity branch).**
- Cross-thread (cross-`source_id`) paraphrase collapse. The 9 / ~13
  active pairs with exact canonical_key match seen pre-fix already
  belong to f9af592's container-scoped Jaccard branch (constraints
  only); broadening to decisions/investigations would risk merging
  unrelated decisions that share nouns and was explicitly rejected in
  f9af592.

  **2026-06-28 note:** the resolver similarity branch is
  character-similarity, not noun-overlap. SequenceMatcher.ratio is
  much stricter than Jaccard for short token sets (sim>=0.85 over
  100-char canonical_keys means the texts are near-identical, not
  just topical neighbours). The branch operates at container scope
  but in practice paraphrases concentrate within the same source_id
  (live-DB measurement: 99.93% of sim>=0.85 pairs share source_id).
  Cross-thread paraphrase collapse is thus a real but tightly-bounded
  consequence of the per-item fix.

## Code-review follow-ups (2026-06-28)

Two findings from external code review on the initial spec, both fixed
in the per-item follow-up:

- **P1 — backfill bucket missing `container_ref`.** Original
  [`scripts/backfill_thread_near_dups.py`](../../scripts/backfill_thread_near_dups.py)
  grouped candidates by `(source_id, type)`. If two containers reused
  the same source_id (rare in production, possible with synthetic test
  sources), the backfill could plan cross-container supersessions.
  Bucket key now `(container_ref, source_id, type)`. Regression:
  [`tests/test_resolver_similarity_branch.py::TestBackfillBucketIncludesContainer`](../../tests/test_resolver_similarity_branch.py).
- **P2 — eval measurement mirror.** Same issue in
  [`evals/injection_policy_2026_06/near_dup_measure.py`](../../evals/injection_policy_2026_06/near_dup_measure.py)
  `_simulate_fix_c` and `_per_source_top_noise`. Fixed to the same
  bucket shape. Regression:
  [`tests/test_resolver_similarity_branch.py::TestEvalBucketIncludesContainer`](../../tests/test_resolver_similarity_branch.py).

## Reference

- Bug surface: live-validation step of the abstention plan
  (`docs/specs/2026-06-27-injection-policy-abstention.md`).
- Prior art: commit `f9af592` "T2: text-anchored canonical_key +
  container-scoped supersession + merge-not-collapse" (2026-06-04).
- Data ground truth: ~/.pallium/data/pallium.db as of 2026-06-28.
