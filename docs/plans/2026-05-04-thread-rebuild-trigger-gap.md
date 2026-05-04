# Thread Rebuild Trigger Gap — Investigation & Fix Brief

## The Problem We Observed (live, May 4 2026)

In a long Claude Code session (thread `26155eaa-85ac-4852-b10b-f08abd85fb65`), the
thread rebuild ran at 15:18:59 and then **did not re-trigger for 50 minutes** despite
22 new source items arriving that contained:

- A full detailed design document (4 levers for token savings)
- An architect review with 4 structured findings
- A self-critique retracting 2 of those findings
- A complete noise analysis with quantitative results
- Multiple user decisions ("yes let's plan this data-driven", "review the review")

When the user asked "do you remember the points from the architect review?" at 16:10,
Pallium could not surface it because:
1. No memory object existed for it (thread rebuild hadn't run)
2. The raw source_hits that matched were too large (full assistant messages)
3. Unrelated investigation_outcomes about "boundary" scored higher via vocabulary match

A rebuild was finally triggered at 16:09:17 (by what appears to be a query-time or
supervisor check, NOT by per-item extraction). It was still processing when needed.

## Root Cause

The function `_should_request_thread_rebuild()` in `semantic/common.py` (line 580)
triggers a rebuild when per-item extraction produces:

```python
def _should_request_thread_rebuild(source_item, extraction, memory_objects) -> bool:
    if _looks_like_low_value_meta_update(extraction):
        return False
    has_supported_typed_memory = any(
        mo.type in {"decision", "investigation_outcome"}
        for mo in memory_objects
    )
    if has_supported_typed_memory:
        return True
    if _has_explicit_thread_signal(extraction):
        return True
    if _is_selected_assistant_work_artifact(source_item, extraction):
        return True
    if extraction.candidate_type in {"decision", "investigation_outcome"}:
        return False  # weak candidates that fail guards shouldn't churn
    return _is_substantive_summary(source_item, extraction)
```

All 22 post-watermark items had `mo=[none]` — per-item Haiku extraction produced
**zero memory objects** from any of them. Therefore none of the trigger conditions fired.

## Why Per-Item Extraction Produced Nothing

The items fall into two categories:

1. **Long assistant analytical messages** (detailed design, architect review, noise
   analysis results). Per-item Haiku likely classified these as "reporting/analysis"
   rather than committed decisions or resolved investigations. This is arguably
   correct — the VALUE is in the multi-turn arc (design → review → rejection → 
   revision), not in any single message.

2. **Short user directives** ("do an architect review", "review the review", "yes
   let's plan this data-driven"). These are instructions, not decisions in the
   extraction prompt's sense. Again arguably correct per-item.

The problem: the COMBINATION of these turns constitutes a decision arc (findings
accepted/rejected, direction chosen) that only thread-level extraction can capture.
But thread-level extraction never ran because per-item didn't flag the trigger.

## The Gap in the Trigger Logic

The current trigger logic assumes: "if per-item extraction found something valuable,
the thread probably has enough new material to warrant a rebuild." This fails when:

- The valuable content is **emergent from multi-turn interaction** (reviews, debates,
  design iterations) rather than contained in any single message
- Per-item extraction correctly produces nothing for analytical/directive messages
- The thread accumulates 20+ new substantive items without any individual one
  qualifying as a decision or investigation

This is not a rare edge case — it's the NORMAL pattern for design discussions,
code reviews, and planning sessions.

## Data From the Live Case

```
Thread: 26155eaa-85ac-4852-b10b-f08abd85fb65
Container: git:github.com/rore/pallium

Last successful rebuild: 2026-05-04 15:18:59.695598
Collection watermark: 2026-05-04 15:18:48.990807
Next rebuild requested: 2026-05-04 16:09:17.019050 (50 min gap)
Items after watermark: 22 (all completed, all mo=[none])

Items that SHOULD have triggered rebuild:
  15:33:35 [assistant] — detailed design doc with 4 implementation levers
  15:40:33 [user] — "do an architect review on these suggestions"
  15:42:04 [assistant] — structured architect review with 4 numbered findings
  15:43:30 [user] — "review the review. i don't think i agree to a lot of it"
  15:44:03 [assistant] — self-critique retracting findings 1 and 4
  15:44:57 [user] — "yes, let's plan how to do this in a very data driven way" (=decision)
```

## Suggested Fix Approaches

### Option A: Item-count threshold trigger (simplest)

If `N` items have been ingested since the last rebuild watermark, trigger a rebuild
regardless of per-item extraction results. This catches the "accumulated substantive
content" case.

```python
# In the supervisor/processor that checks thread rebuild eligibility:
items_since_watermark = count_items_since(thread_ref, collection_watermark_at)
if items_since_watermark >= REBUILD_ITEM_THRESHOLD:  # e.g., 10-15
    request_rebuild(thread_ref)
```

Where to implement: wherever the rebuild-request decision is made (likely in the
supervisor loop or after per-item processing completes).

### Option B: Time-based re-trigger

If `T` minutes have passed since the last rebuild AND new items exist, trigger.
This ensures rebuilds happen at bounded intervals during active sessions.

```python
time_since_rebuild = now - processing_completed_at
if time_since_rebuild > MAX_REBUILD_GAP and items_since_watermark > 0:
    request_rebuild(thread_ref)
```

### Option C: Substantive-content heuristic

Expand `_should_request_thread_rebuild` to trigger on content length alone for
messages that look like structured output (reviews, designs, analyses):

```python
# After existing checks, before returning _is_substantive_summary:
if source_item.role == "assistant" and len(source_item.content) > 2000:
    return True  # Long assistant messages likely contain extractable content
```

### Option D: User-directive pattern matching

Detect user messages that signal review/decision activity:
- "do an architect review"
- "review the review"
- "let's plan"
- "yes, let's do X"

These are decision-adjacent even if per-item extraction doesn't produce a memory.

### Recommendation

**Option A + B combined:** item-count threshold (e.g., 12 items) OR time threshold
(e.g., 30 min with ≥5 new items). This is:
- Simple (no new heuristics or pattern matching)
- Robust (catches all cases, not just specific patterns)
- Low risk (worst case: an extra rebuild that produces the same results)
- Consistent with the incremental rebuild design (9bade0d) which already supports
  re-running on partial new content

The cost of an unnecessary rebuild is one Sonnet call (~$0.01). The cost of NOT
rebuilding is a 50-minute gap where valuable decisions/investigations are invisible.

## Secondary Problem: Extraction Quality on Analytical Content

Even when the thread rebuild DOES run, there's a question of whether thread-level
extraction will correctly identify the valuable content. The thread_summary created
at 15:18:59 for this thread produced:

- Summary: 1 line (topic orientation only)
- Conclusions: 0
- Decisions: 0
- Investigations: 0

This was for a thread that already contained substantive decisions like "we disabled
facts for claude, it just added noise" and investigation outcomes from the efficiency
analysis. The thread-level extraction prompt may be under-extracting from threads
where the content is primarily analytical/investigative rather than task-oriented.

### What SHOULD have been extracted (from the 22 post-watermark items):

1. **Decision:** "Lever 1 (turn count threshold) is risky alone — produces 43% noise.
   Lever 2 (checkpoint bypass) is the safe starting point." (user accepted this)

2. **Investigation outcome:** "Injection replay simulation shows 56% precision at all
   thresholds. Routing score cannot discriminate helpful from noise (noise avg 458 vs
   helpful 437). Same memory is helpful in one context, noise in another."

3. **Investigation outcome:** "Architect review of 4 token-savings levers: findings 1
   and 4 retracted (turn_inference already makes heuristic assumptions; agent CAN'T
   fix its own context degradation). Findings 2 and 3 partially valid."

4. **Decision:** "Start implementation with Lever 2 (task checkpoint forced injection),
   not Lever 1, because data shows it's type-scoped and low noise risk."

5. **Investigation outcome:** "33% of noise would be blocked by current extraction
   validation rules (515547a). 65% of noise is valid memories injected into wrong
   context — requires topic-level matching, not extraction fixes."

### What to verify after the rebuild trigger fix ships:

Once the rebuild re-runs on this thread with the new items, check whether the
thread-level Sonnet extraction actually produces these memories. If it doesn't,
there's a second problem: the thread extraction prompt isn't tuned for
design-discussion / review-debate patterns (as opposed to task-execution patterns
it was optimized for).

## Files to Change

- `semantic/common.py` — `_should_request_thread_rebuild()` (add item-count awareness)
- OR: the supervisor/processor loop that evaluates thread rebuild eligibility
- Check: `9bade0d` (incremental thread rebuild with watermark windowing) — the
  mechanism for partial rebuilds already exists, just needs better triggering

## Verification

After implementing, verify with this thread's data:
1. With 22 items since watermark and a 50-min gap, the new logic should trigger
2. The resulting thread rebuild should extract the architect review findings as
   investigation_outcomes or decisions
3. Subsequent queries for "architect review findings" should return memory objects,
   not raw source_hits
