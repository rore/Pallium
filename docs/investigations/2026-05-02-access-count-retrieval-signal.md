# Investigation: Access-Count / Retrieval Frequency as a Quality Signal

## Conclusion

**Not worth building as a positive scoring signal.** Early analysis (98 queries,
~1.5 days) shows injection frequency inversely correlates with feedback quality:
memories injected more often have *worse* ratings (39.5% relevant) than those rated
but never injected (54.4% relevant). Boosting by access count would amplify
problematic memories, not surface good ones.

**The useful signal is the inverse:** memories that keep getting injected but keep
getting rated not_relevant are candidates for auto-suppression. One such memory
already appears in the data (injected 4 times, rated not_relevant 3/3 times).

**Status:** Parked. The analysis script (`scripts/analyze_injection_frequency.py`)
can be re-run as data accumulates. If the inverse correlation holds at scale, the
actionable direction is auto-suppression detection (high injection + poor feedback
ratio), not positive access-count boosting.

### Early Empirical Findings (98 queries, 2026-05-01 to 2026-05-02)

| Injection frequency | Memories rated | Avg relevant% |
|---------------------|---------------|---------------|
| Never injected | 37 | 54.4% |
| Injected 1x | 40 | 39.4% |
| Injected 2-3x | 14 | 39.9% |
| Injected 4+x | 2 | 37.5% |

Key observations:
- 93% of active memories (989/1056) have never been injected
- Only `decision` and `investigation_outcome` get repeatedly injected
- `atomic_fact` (518) and `turn_summary` (251) are never injected — routing already
  deprioritizes them correctly
- The problem is topical mismatch (right type, wrong topic), not insufficient
  frequency signal — consistent with the recency investigation's conclusion

### What would be worth building (if data holds at scale)

Auto-suppression detection: surface memories where `injection_count >= N` AND
`not_relevant_ratio > 0.6` AND `total_feedback >= 3`. This catches memories that
keep matching queries but are consistently wrong — a problem the current 2-flag
manual suppression threshold is too slow to address.

---

## Current State

### What tracking already exists

| Table | What it captures | Limitation |
|-------|-----------------|------------|
| `query_audit_log` | Per-query: should_inject, decision_reason, injected_blocks_json (with memory_object_id), candidate_scores_json | Memory IDs require JSON parsing to aggregate; no materialized count per memory |
| `memory_feedback` | Per-injection rating: memory_object_id, "relevant"/"not_relevant", query context | Explicit signal from integrating agents; 138 entries across 91 unique memories |
| `memory_flags` | Suppression flags per memory | Only 3 flags in production |
| `memory_objects` | lifecycle, freshness_at, created_at | No access/injection counters |

### Key finding: injection tracking is already stored but not materialized

The `injected_blocks_json` column in `query_audit_log` stores which memories were
injected per query. Each entry includes `memory_object_id`. This means we can already
compute historical injection counts via:

```sql
-- Requires JSON parsing across all audit rows (slow for large tables)
SELECT json_extract(value, '$.memory_object_id') as mid, COUNT(*) as cnt
FROM query_audit_log, json_each(injected_blocks_json)
WHERE should_inject = 1
GROUP BY mid ORDER BY cnt DESC;
```

But this is a scan-per-query operation, not a denormalized lookup.

### Database reality (production data)

- **93 queries** in audit log (2026-05-01 to 2026-05-02)
- **58 queries** resulted in injection (62% injection rate)
- **66 unique memories** injected at least once
- **~1,020 active memories** total → 954 active memories have NEVER been injected
- Most-injected memory: 4 times (a `decision`)
- **memory_feedback**: 79 not_relevant, 59 relevant (57% not_relevant rate)

---

## Where Injection Happens (Code Flow)

```
POST /query (api/routes.py:338)
  → service.query() (core/service.py)
    → QueryExecutor.query() (core/query.py:50)
      → core.routing.route_query_results() (core/routing.py:40)
        → semantic routing pipeline (semantic/agent_conversation_memory_routing.py:131)
          → _build_injectable_blocks() (semantic/agent_conversation_memory_routing_selection.py:232)
              ← Returns: injectable_blocks list with memory_object_ids
  → _maybe_write_query_audit() (api/routes.py:210)
    → service.write_query_audit() (core/service.py:590)
      → storage.write_query_audit_row()
```

The **exact point where "injection happened" is known** is inside
`service.write_query_audit()` at line 612-623, where `blocks_json_list` is built
with `memory_object_id` for each injected block.

Note: `write_query_audit()` is called from `_maybe_write_query_audit()` in the
`/item-and-query` compound endpoint — it's not part of the bare `/query` path. If a
counter were ever materialized, it should live in the service layer's `query()` method
(where injection is decided), not in the audit log write (which is optional and
endpoint-specific).

---

## Recommended Approach

### Phase 1: Validate with existing data (no production code)

The audit log already contains the raw signal. After 2-4 weeks of accumulation,
run an analysis script:

```sql
-- Per-memory injection frequency
SELECT json_extract(j.value, '$.memory_object_id') as memory_id, COUNT(*) as injection_count
FROM query_audit_log, json_each(injected_blocks_json) AS j
WHERE should_inject = 1
GROUP BY memory_id ORDER BY injection_count DESC;

-- Correlate with feedback ratings
SELECT
    injection_freq.memory_id,
    injection_freq.cnt as injections,
    SUM(CASE WHEN mf.rating = 'relevant' THEN 1 ELSE 0 END) as relevant_count,
    SUM(CASE WHEN mf.rating = 'not_relevant' THEN 1 ELSE 0 END) as not_relevant_count
FROM (
    SELECT json_extract(j.value, '$.memory_object_id') as memory_id, COUNT(*) as cnt
    FROM query_audit_log, json_each(injected_blocks_json) AS j
    WHERE should_inject = 1
    GROUP BY memory_id
) injection_freq
LEFT JOIN memory_feedback mf ON mf.memory_object_id = injection_freq.memory_id
GROUP BY injection_freq.memory_id
ORDER BY injection_freq.cnt DESC;
```

Questions to answer:
- Do high-injection-count memories have better feedback ratios?
- Do zero-injection memories correlate with low-quality types or specific containers?
- Is there a cluster of "frequently injected but consistently not_relevant" memories
  that the auto-suppression signal would catch?

### Phase 2: Materialize counter (only if Phase 1 validates)

If the analysis shows frequency is a meaningful signal, add `injection_count` to
`memory_objects` and increment it in the service layer's `query()` method (not in
the audit log write path, which is optional and endpoint-specific).

```sql
ALTER TABLE memory_objects ADD COLUMN injection_count INTEGER DEFAULT 0;
```

Skip `last_injected_at` — it's derivable from the audit log via a simple indexed
query and doesn't justify a dedicated column.

### Phase 3: Use in scoring (only if Phase 2 data confirms utility)

Defer all scoring integration until accumulated data proves the signal is meaningful.

If validated, the cleanest integration would be a post-RRF multiplier:

```python
access_boost = 1 + log(1 + injection_count) / C  # C calibrated empirically
```

But Phase 2 might show:
- Access count only indicates "this memory matches common queries" (frequent topics),
  not "this memory is high quality"
- A feedback-loop risk: popular memories get boosted → get injected more → get boosted
  more, while new memories can't compete

In that case, Option D (pruning/observability only) is the right outcome.

An alternative worth considering: use `memory_feedback` ratio (relevant / total) as
the direct quality signal instead of injection count. Feedback is a *direct*
measurement of quality; injection count is an indirect proxy.

---

## Cold-Start Handling

New memories have `injection_count = 0`. Three mitigations (combine as needed):

1. **Grace period:** Don't apply any access-count boost until a memory is >7 days old.
   This lets it accumulate injection history before being compared to established memories.

2. **Floor of 1:** Treat `injection_count` as `max(1, injection_count)` in scoring
   formulas. This ensures the boost is multiplicative from a base of 1, meaning
   zero-injection memories aren't penalized — they just don't get a bonus.

3. **Tiebreaker only:** Use access count only when two candidates have nearly identical
   routing scores (within ±5 points). This prevents access count from overriding
   semantic relevance but lets it break ties in favor of proven-useful memories.

Recommendation: **Floor of 1 + tiebreaker only.** This is the simplest approach that
avoids both penalizing new memories and creating runaway feedback loops.

---

## Interaction with Existing Signals

| Existing signal | Relationship to access count |
|----------------|------------------------------|
| `memory_feedback` (rate_memory) | **Complementary.** Feedback is explicit quality; access count is implicit usage. A memory rated "relevant" 5 times is definitely good. A memory injected 50 times but never rated is probably useful (agents don't rate every injection). |
| Lifecycle supersession | **Orthogonal.** Superseded memories are excluded from retrieval entirely. Access count only matters for active memories. |
| Suppression (flag threshold) | **Compound signal opportunity.** A memory with high injection count BUT consistent not_relevant ratings = candidate for auto-suppression review. |
| Routing freshness ranking | **Separate concern.** Freshness ranks within-type by timestamp. Access count ranks by proven utility regardless of age. |
| Relevance floor | **No interaction.** Floor gates on retrieval quality (lexical/vector scores). Access count would be applied after floor filtering. |

### Auto-suppression opportunity

A compound signal for identifying problematic memories:

```
IF injection_count > 5
AND not_relevant_count / total_feedback_count > 0.75
AND total_feedback_count >= 3
THEN flag for suppression review
```

This surfaces memories that keep getting injected (high retrieval match) but are
consistently rated irrelevant (poor topical alignment). Currently these rely on the
manual flag threshold (2 unique flags), which is slow.

---

## Pruning Implications

### Zero-injection memories after N days

**Interpretation is ambiguous:**
- Could be genuinely irrelevant (dead weight)
- Could be dormant (no matching query has come in yet)
- Could be narrowly useful (only matches rare queries)

**Distinguishing signals:**
- If `injection_count = 0` AND `last 30 days had queries in same container` → likely
  irrelevant (queries happen but this memory never matches)
- If `injection_count = 0` AND `container has had <5 queries total` → insufficient data
- If `injection_count > 0` but `last_injected_at` is 60+ days ago → declining relevance

**Recommendation:** Don't auto-delete based on access count alone. Surface as
diagnostic data in a maintenance dashboard. The `purge-suppressed` command pattern
shows the project prefers explicit cleanup over automatic deletion.

---

## Performance Considerations

Not applicable for Phase 1 (analysis script only — no production code changes).

If Phase 2 materializes a counter:

| Operation | Cost | Concern? |
|-----------|------|----------|
| UPDATE per injection (1-5 rows) | ~1ms SQLite write in WAL mode | No. Queries happen 1-5 times per agent turn (seconds apart). Not hot-path. |
| Reading injection_count at routing time | Already fetching memory_objects row — free column | No |
| Batch increment vs per-row | Single UPDATE with IN clause — one write op | No |

**Important:** If materialized, the increment must live in the service layer's
`query()` method, not in `write_query_audit()`. The audit log write is called from
`_maybe_write_query_audit()` which is specific to the `/item-and-query` compound
endpoint — not all query paths invoke it.

---

## Schema Changes (Phase 2, contingent on Phase 1 validation)

```sql
ALTER TABLE memory_objects ADD COLUMN injection_count INTEGER DEFAULT 0;
```

Migration approach: add to `_MEMORY_OBJECT_MIGRATIONS` dict in
`storage/sqlite_schema.py` (same pattern as existing column migrations).

Backfill from existing audit data:

```sql
UPDATE memory_objects SET
    injection_count = (
        SELECT COUNT(*)
        FROM query_audit_log, json_each(query_audit_log.injected_blocks_json) AS j
        WHERE query_audit_log.should_inject = 1
          AND json_extract(j.value, '$.memory_object_id') = memory_objects.id
    )
WHERE lifecycle = 'active';
```

---

## Risks

1. **Feedback loop (Matthew effect):** High-count memories get boosted → injected more
   → boosted more. **Mitigation:** Use logarithmic scaling (`log(1 + count)`) and cap
   the boost. Or defer scoring integration entirely until Phase 2 validates the signal.

2. **Cold-start bias:** New memories can't compete with established ones.
   **Mitigation:** Floor of 1, grace period, tiebreaker-only mode.

3. **Conflating "matches queries" with "is high quality":** A memory that matches every
   query's keywords might just contain common terms. **Mitigation:** Only trust access
   count when combined with positive feedback ratios. Don't use it as a standalone
   quality signal. Consider whether `memory_feedback` ratio is a better direct signal.

4. **Premature schema changes:** Any new column is permanent API surface in a released
   product. **Mitigation:** Validate the hypothesis with existing audit log data first
   (Phase 1). Only materialize if the signal proves useful.

---

## Estimated Complexity

**Trivial for Phase 1 (analysis only).**

| Work item | Effort |
|-----------|--------|
| Analysis script (SQL queries against audit log) | 1 hour |
| Interpretation and correlation write-up | 1-2 hours |
| **Total Phase 1** | **~half a day** |

Phase 2 (materialize counter) is small if validated (~half a day for schema + storage
method + service call site + tests).

Phase 3 (scoring integration) would be small-medium if validated, but might never be
needed if access count turns out not to correlate with quality.

---

## Comparison with the Recency Investigation

The [recency signal investigation](./2026-05-02-recency-signal-in-retrieval.md)
concluded that memory age does NOT correlate with irrelevant injections — the problem
is topical mismatch, not temporal mismatch.

Access count is a different hypothesis: not "how old is this memory" but "how often
has this memory proven useful." These are independent signals:
- A 30-day-old memory with 20 injections is proven-useful (access count says: boost it)
- A 1-day-old memory with 0 injections is untested (access count says: neutral)
- The recency investigation showed both old and young memories are equally likely to be
  irrelevant

Access count could address what recency cannot: identifying memories that consistently
match queries and are consistently useful (or consistently injected but consistently
rated not_relevant — which is the auto-suppression signal).

---

## Decision

**Do not build anything yet.** The existing audit log contains the raw data needed
to validate the hypothesis. Apply the same empirical-validation-before-building
discipline that the recency investigation used:

1. Let audit log data accumulate for 2-4 weeks
2. Run the Phase 1 analysis script
3. If injection frequency correlates with feedback quality → materialize the counter
4. If it doesn't → close this investigation as "not a useful signal"

The auto-suppression compound signal (high injection + poor feedback ratio) is the
most promising direction if the data supports it. But it requires its own bounded
investigation with specific thresholds, policy decisions (auto-suppress vs surface
for review), and integration with the existing flag model.

This investigation is **parked pending data accumulation**, not concluded.
