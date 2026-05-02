# Investigation: Adding a Recency Signal to Retrieval Scoring

## Conclusion

**Not worth building.** Empirical validation against production data shows that memory
age does not correlate with irrelevant injections. The not_relevant rate is flat across
age buckets (47-57%), with the youngest memories (1-6h) actually being the worst
performers (90% not_relevant). The real problem is topical mismatch, not temporal
mismatch.

Pallium's existing mechanisms — lifecycle supersession, typed memory, thread/container
scoping, and routing freshness ranking — already handle staleness effectively. Adding
time-based decay would penalize old-but-relevant memories without reducing noise from
young irrelevant ones.

## Original Hypothesis

Pallium's retrieval layer currently has no time signal — a memory from 6 months ago
scores the same as one from yesterday if lexical+vector match equally. The routing
layer downstream compensates with a relative freshness component, but this adds
complexity and means the retrieval layer returns a candidate set that doesn't reflect
temporal relevance.

This investigation traces how time is handled today, evaluates integration points,
proposes a decay function, and assesses interaction with existing routing stages.

---

## Current Temporal Handling

### Where time matters today

| Layer | Mechanism | What it does |
|-------|-----------|-------------|
| Retrieval | None | No time signal at all |
| Routing: annotations | `annotate_freshness_ranks()` | Groups candidates by type, ranks by timestamp (1=freshest) |
| Routing: scoring | `_freshness_component()` | Bonus for rank-1 within type (+24 recall, +42 structured_recall, +18 work_resumption), penalty for rank-3+ (-12/rank, max -30) |
| Routing: work resumption | `annotate_work_resumption_context()` | Marks task_checkpoints as "stale" if >2700s older than freshest local checkpoint |
| Routing: staleness penalties | `_usefulness_adjustment()` | -55 for stale checkpoints, -28 for stale source evidence |
| Lifecycle | Supersession | Old thread summaries/checkpoints are superseded when threads are rebuilt |
| Lifecycle | Contradiction | Superseded via `FactConsolidationStrategy` when cross-thread contradictions detected |

### Key observation

The routing layer's freshness handling is **relative within type**, not absolute time
decay. If three `decision` memories are candidates, the freshest gets +24 and the
oldest gets -6, but whether they're 1 day or 6 months old makes no difference. This
handles "which of these competing candidates is most current" but not "is this memory
still relevant given its age."

### Available timestamps on candidates

- `MemoryObject.created_at` — when the memory was created (always present)
- `MemoryObject.freshness_at` — currently equals `created_at` (not updated after creation)
- `QueryResultItem.occurred_at` — source item occurrence time
- Evidence `occurred_at` — per-evidence-item timestamps
- `_candidate_freshness_timestamp()` — takes max of all available timestamps

---

## Integration Point Analysis

### Option A: Third RRF signal (recency rank)

Add a third ranked list (sorted by `created_at` descending) to the RRF fusion.

**Pros:**
- Principled: RRF is designed to fuse ranked signals without score-scale alignment
- Self-documenting: recency becomes an explicit retrieval signal like lexical and vector

**Cons:**
- Changes the RRF balance: 2-signal → 3-signal means each individual signal contributes
  less to the final score. With 2 signals, a rank-1 hit scores `2 × 600/61 ≈ 19.7` max.
  With 3 signals, max is `3 × 600/61 ≈ 29.5` but a lexical-only hit drops from
  `600/61 ≈ 9.8` to `600/61 + 600/(60+N)` where N is its recency rank — diluted.
- Requires fetching all candidates sorted by time, even if most are irrelevant
- A memory created yesterday but semantically unrelated would get a high recency rank,
  potentially surfacing noise
- Breaks the existing contract where `fused_score` = lexical + vector quality only

**Verdict:** Too disruptive. RRF works well for signals that independently indicate
relevance. Recency alone doesn't indicate relevance — it modulates the relevance of
already-matched candidates.

### Option B: Post-RRF decay modifier (recommended)

After RRF fusion produces scored results, multiply each score by a type-specific
time-decay factor before results enter the routing pipeline.

**Pros:**
- O(1) per candidate — negligible performance cost
- Doesn't change the 2-signal RRF balance
- Works at the boundary between retrieval and routing — clean integration point
- Type-specific decay respects that `atomic_fact` should barely decay while
  `continuity_memory` should decay quickly
- The decay factor is transparent and debuggable (can include in trace)

**Cons:**
- Score modification after RRF means `fused_score` no longer represents pure
  retrieval quality — downstream consumers must understand this
- Interaction with `FloorThresholds` needs care: if decay drops a score below
  the relevance floor, it's filtered out

**Verdict:** Best fit. Clean, cheap, type-configurable, minimal architecture disruption.

### Option C: In routing scoring (existing approach, extended)

Extend `_freshness_component()` to use absolute time decay instead of relative ranks.

**Pros:**
- Builds on existing infrastructure
- Routing already has the timestamps and type information

**Cons:**
- Keeps retrieval "time-blind" — the top-N candidates entering routing are still
  selected without any time preference, meaning old irrelevant memories still
  consume candidate slots
- Makes routing even more complex (already 10 stages)
- The relative freshness ranking is useful for a different purpose (breaking ties
  between candidates of the same type) — absolute decay is a separate concern

**Verdict:** Partial solution. Doesn't address the core problem: retrieval candidate
selection is time-blind.

### Option D: Pre-retrieval time filter

Exclude memories older than X days unless they're high-value types.

**Pros:**
- Simple, aggressive noise reduction

**Cons:**
- Brittle: a decision from 3 months ago might be exactly what's needed
- No graceful degradation — binary in/out
- High-value cutoff is hard to define without context

**Verdict:** Too aggressive. A decay curve is strictly better than a hard cutoff.

---

## Recommended Approach: Post-RRF Decay Modifier

### Integration point

Apply decay inside `route_query_results()` in
`semantic/agent_conversation_memory_routing.py`, immediately after
`apply_relevance_floor()` (line ~149) and before anchor prefiltering and scoring.

This is the natural boundary:
- The relevance floor judges **retrieval quality** using raw `vector_score` and
  `lexical_score` fields (unaffected by decay since they're preserved independently).
- Decay modifies the fused `score` field to reflect **temporal relevance**.
- Routing scoring then uses `item.score` as `retrieval_score` input, while
  `_compute_quality_score()` still reads the undecayed `lexical_score` and
  `vector_score` — meaning quality assessment stays pure and only the ranking
  input reflects age.

The floor and decay operate on different score fields and cannot conflict:
- Floor checks: `item.vector_score >= 580` or `normalized(item.lexical_score) >= 0.33`
- Decay modifies: `item.score` (the RRF fused score)

`CompositeRetrievalProvider` stays untouched — it remains a pure retrieval-quality
fusion layer with no temporal logic.

### Decay function

**Proposed: Exponential decay with per-type half-life.**

```
decay(age_hours, half_life_hours) = 0.5 ^ (age_hours / half_life_hours)
```

Clamped to `[floor, 1.0]` where `floor` prevents old-but-relevant memories from
being completely suppressed (recommended floor: 0.3).

```
effective_decay = max(floor, 0.5 ^ (age_hours / half_life_hours))
```

### Per-type half-life parameters

| Memory Type | Half-life | Rationale |
|-------------|-----------|-----------|
| `atomic_fact` | ∞ (no decay) | Facts are stable: "Berlin is the capital of Germany" |
| `fact_summary` | ∞ (no decay) | Consolidated facts, already high-value |
| `decision` | 336h (14 days) | Decisions stay relevant for weeks; supersession handles conflicts |
| `investigation_outcome` | 168h (7 days) | Outcomes are time-sensitive but not ephemeral |
| `pattern_memory` | 504h (21 days) | Patterns represent durable recurring knowledge |
| `continuity_memory` | 72h (3 days) | Carry-forward context decays quickly |
| `task_checkpoint` | 48h (2 days) | Work state gets stale fast |
| `thread_summary` | 168h (7 days) | Summaries of conversations; moderate relevance window |
| `turn_summary` | 96h (4 days) | Individual turn summaries are noisy and ephemeral |
| `interest` | 120h (5 days) | User interests shift but not as fast as work state |
| `constraint_memory` | 336h (14 days) | User constraints tend to persist |

Note: Source hits (`result_kind="source_hit"`) have no `memory_type`. They use
`occurred_at` as their age reference and receive a default half-life (proposed: 96h).
The decay function must branch on `result_kind` before looking up type-specific
half-lives.

### Example decay curves

At the recommended floor of 0.3:

```
continuity_memory (half_life=72h):
  6h: 0.94    24h: 0.79    72h: 0.50    168h: 0.30 (floor)

decision (half_life=336h):
  24h: 0.95    168h: 0.71    336h: 0.50    672h: 0.30 (floor)

atomic_fact: always 1.0 (no decay)
```

### Score impact example

A `continuity_memory` with RRF score 15 (rank-1 on both lexical+vector):
- 6 hours old: `15 × 0.94 = 14` (negligible change)
- 3 days old: `15 × 0.50 = 7` (significant demotion)
- 7 days old: `15 × 0.30 = 4` (near floor, unlikely to be selected)

A `decision` with RRF score 12 (rank-3 lexical, rank-2 vector):
- 1 day old: `12 × 0.95 = 11` (barely changes)
- 7 days old: `12 × 0.71 = 8` (moderate demotion)
- 14 days old: `12 × 0.50 = 6` (significant but still viable)

---

## Interaction with Existing Routing Stages

### Can routing stages be simplified?

**`_freshness_component` (relative within-type ranking):** Cannot be removed. It
serves a different purpose — breaking ties between candidates of the same type when
multiple are retrieved. Recency decay in retrieval reduces old candidates' scores,
but doesn't eliminate the need to prefer the freshest among survivors.

**`annotate_work_resumption_context` (staleness annotation):** Could potentially be
simplified. If decay already demotes old checkpoints significantly, the explicit
`WORK_RESUMPTION_STALE_STATE_PENALTY = -55` might over-penalize. However, the
staleness check is relative (compares to freshest checkpoint), which decay doesn't
replicate. **Keep but monitor for double-penalization.**

**`_usefulness_adjustment` (stale checkpoint/source penalties):** Same concern.
After decay, a 2-day-old checkpoint already lost ~50% of its score. Adding -55
more might be excessive. **Consider reducing these penalties when decay is active.**

### Double-penalization risk

The main risk: a 3-day-old `task_checkpoint` currently gets:
1. No retrieval penalty (score ~15 from RRF)
2. Routing freshness: if it's rank-2 in its type, gets 0 (no bonus, no penalty)
3. Work resumption stale: if >2700s behind freshest, gets -55

With decay added:
1. Retrieval: score drops from 15 to ~7 (decay = 0.50 at 3 days, half_life=48h)
2. Routing freshness: same as before (rank-relative, unaffected)
3. Work resumption stale: still -55

The combined effect is much harsher. **Mitigation: when recency decay is enabled,
reduce `WORK_RESUMPTION_STALE_STATE_PENALTY` from 55 to ~25 and
`WORK_RESUMPTION_STALE_SOURCE_PENALTY` from 28 to ~12.**

---

## Interaction with Contradiction Supersession

Superseded memories are already excluded from retrieval by lifecycle filtering.
Recency decay is complementary, not redundant:

- **Supersession** handles explicit contradictions (memory A contradicts memory B →
  older one is marked superseded)
- **Recency decay** handles implicit staleness (memory not contradicted but no longer
  relevant because context has shifted)

Example: "User is interested in Chroma" from 2 weeks ago. Not contradicted by anything,
but the user hasn't mentioned it since. Without decay, it surfaces every time something
tangentially related is queried. With decay (interest half_life=5 days), it's at floor
(0.30) after ~12 days and unlikely to win against fresher candidates.

---

## Data Analysis (Local Database)

The current database has 917 active memories across 9 types. All memories are <4 days
old (dev environment), so empirical age-vs-injection analysis isn't meaningful at this
scale. However, structural observations:

- `freshness_at` currently equals `created_at` for all memory objects — the field exists
  but isn't updated post-creation. Future work could use `freshness_at` for
  "last confirmed still relevant" semantics, separate from creation time.
- Thread summaries and task checkpoints are superseded aggressively (1011 superseded vs
  917 active) — lifecycle handles rebuilds well, recency decay adds the long-tail case.
- Most injections use reason `carry_forward_available` — these are work-resumption
  scenarios where freshness already matters a lot.

---

## Performance Considerations

- **Decay computation:** `math.pow(0.5, age_hours / half_life_hours)` is O(1) per
  candidate. With typical candidate sets of 20-40 items, total cost is microseconds.
- **No additional I/O:** `created_at` is already loaded as part of candidate hydration
  (available via `freshness_at` or evidence timestamps).
- **No third ranked list:** By choosing post-RRF modifier over a third RRF signal, we
  avoid the cost of sorting all index entries by time.
- **Within 5% overhead budget:** A few microseconds of arithmetic per query is negligible
  against the existing embedding computation (~10-50ms) and FTS5 search (~1-5ms).

---

## Risks

1. **Over-penalizing stable facts:** Mitigated by ∞ half-life for `atomic_fact` and
   `fact_summary`. These types represent durable knowledge that doesn't decay.

2. **Double-penalization with routing staleness:** Mitigated by reducing routing
   staleness penalties when decay is active (see above).

3. **Relevance floor interaction:** Not a concern. The relevance floor operates on raw
   `vector_score` and `lexical_score` fields (preserved independently on each
   `QueryResultItem`), while decay modifies the fused `score` field. These are
   different fields — decay cannot cause a candidate to fail the floor. The
   integration point (decay applied after floor) is chosen for clean separation of
   concerns: floor judges retrieval quality, decay judges temporal relevance.

4. **Loss of old-but-correctly-relevant memories:** The floor parameter (0.3) ensures
   old memories are never completely invisible — they're just demoted. A 6-month-old
   decision at floor 0.3 × original score still has a chance if it's the only strong
   lexical match.

5. **Configuration complexity:** Per-type half-lives add configurable parameters.
   Mitigated by sensible defaults that work out-of-the-box. Advanced users can tune
   via `pallium.local.toml`.

---

## Estimated Complexity

**Small-to-medium.**

Core implementation:
- New module `retrieval/recency.py` (~50 lines): decay function + per-type config
- Modification to `QueryExecutor` or `CompositeRetrievalProvider`: ~10 lines to apply
  decay between retrieval and routing
- Configuration: add `[retrieval.recency]` section to TOML with per-type half-lives
- Trace: add decay factor to `QueryResultItem` or routing trace for debuggability

Routing adjustments:
- Reduce `WORK_RESUMPTION_STALE_STATE_PENALTY` and `WORK_RESUMPTION_STALE_SOURCE_PENALTY`
  when decay is active (conditional on config flag)

Testing:
- Unit tests for decay function (boundary cases, per-type config)
- Integration test verifying old memories score lower than fresh ones
- Regression check that `atomic_fact` and `fact_summary` are unaffected

**Estimated effort: 1-2 days for core + tests, with an additional day for routing
penalty calibration.**

---

## Comparison with Other Memory Systems

Some memory systems use a position-based recency bias in their short-term buffer
memory (e.g., `score = 0.7 × semantic + 0.3 × recency`). This makes sense for
their architecture because:

- Their buffer is a flat FIFO queue of raw messages with no type system or lifecycle
- All items are the same kind — recency is the only staleness signal available
- There's no supersession, no typed extraction, no routing
- "What did we just discuss?" genuinely needs positional recency to find recent turns

Their long-term memory typically uses pure semantic search with NO recency signal.

Pallium doesn't need buffer-style recency because it solves "active context" through
typed memory, lifecycle management (supersession), thread/container scoping, and
routing freshness ranking. The production data confirms this: irrelevant injections
are caused by topical mismatch, not temporal mismatch.

---

## Validation Plan: How to Test Assumptions Before Building

The design above contained several ungrounded assumptions. Before implementing anything,
the primary assumption was validated empirically against production data.

### Assumption 1: "Recency matters — old memories are a problem"

**What we're assuming:** That old memories surface when they shouldn't, degrading
injection quality.

**How validated:**
- Joined `memory_feedback` ratings (124 total: 68 not_relevant, 56 relevant) with
  memory age at query time. Checked whether older memories are disproportionately
  rated `not_relevant`.

**Result — FALSIFIED:**

| Age bucket | Total | Not relevant | Rate |
|-----------|-------|-------------|------|
| <1h | 17 | 8 | 47% |
| 1-6h | 10 | 9 | 90% |
| 6-24h | 21 | 12 | 57% |
| 24-48h | 43 | 20 | 47% |
| 48h+ | 23 | 13 | 57% |

Key findings:
- The not_relevant rate is flat across age buckets (47-57%)
- The **youngest** memories (1-6h) have the **highest** not_relevant rate (90%)
- Average age: not_relevant = 30.6h, relevant = 32.6h (nearly identical)
- By type: `investigation_outcome` and `decision` appear in both relevant and
  not_relevant sets at similar ages — the distinguishing factor is topical match,
  not recency

**Interpretation:** Irrelevant injections are caused by topical mismatch (the memory
doesn't match the query's subject), not temporal mismatch (the memory is too old).
Recency decay would not address the actual problem and would hurt old-but-relevant
memories.

Since Assumption 1 is falsified, Assumptions 2-7 (decay shape, per-type half-lives,
parameter values, integration point, floor, double-penalization) are moot — they all
depend on recency being a real problem signal. The validation plan worked as designed:
the first gate stopped unnecessary work.

---

## Why This Architecture Doesn't Need Recency Decay

Pallium already handles temporal relevance through other mechanisms:

1. **Lifecycle supersession:** When a thread is rebuilt, old summaries/checkpoints are
   superseded and excluded from retrieval. This handles "replaced by newer version."

2. **Contradiction detection:** Cross-thread fact contradictions are detected during
   consolidation and older versions superseded. This handles "no longer true."

3. **Routing freshness ranking:** Within candidates of the same type, the freshest
   gets a bonus (+24 for recall). This handles "which of these equally-relevant
   candidates is most current."

4. **Work resumption staleness:** Task checkpoints >45 minutes behind the freshest
   get a -55 penalty. This handles "stale work state."

5. **Thread/container scoping:** Queries are scoped to the current container, so
   memories from unrelated containers don't surface. This handles "wrong context."

These mechanisms address staleness structurally rather than with a blunt time-based
penalty. The data confirms they're sufficient: old memories that ARE relevant (same
topic, correct context) are correctly surfaced, while irrelevant ones are blocked by
topical mismatch — which decay wouldn't fix.

---

## Next Steps

This investigation is concluded. The data does not support adding recency decay.

Future directions if the problem profile changes:
- If `pallium_rate_memory` feedback over months shows age correlating with
  not_relevant ratings, revisit this conclusion with fresh data.
- If a specific memory type shows clear age-dependent relevance degradation,
  a targeted per-type mechanism might be warranted.
- The topical mismatch problem (the actual source of noise) is better addressed
  by improving retrieval precision — tighter content-overlap gates, better
  embedding discrimination, or query-time subject anchoring.
