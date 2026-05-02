# Investigation: Adding a Recency Signal to Retrieval Scoring

## Summary

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

A well-known open-source memory system uses a simple position-based hybrid formula for
its short-term buffer memory:

```python
combined_score = (1 - recency_bias) * semantic_score + recency_bias * recency_score
# where recency_score = 1.0 - (position / buffer_size), default recency_bias = 0.3
```

For their long-term memory, they use pure semantic search with no recency signal.

Pallium's situation is different:
- Memories are inherently time-sensitive (decisions get superseded, interests shift)
- The memory types have very different temporal characteristics
- We already have lifecycle management (supersession, suppression) for explicit staleness

The proposed per-type exponential decay is more principled than a flat linear bias
because it reflects the actual half-life of different knowledge types.

---

## Validation Plan: How to Test Assumptions Before Building

The design above contains several ungrounded assumptions. Before implementing anything,
each assumption needs empirical validation.

### Assumption 1: "Recency matters — old memories are a problem"

**What we're assuming:** That old memories surface when they shouldn't, degrading
injection quality.

**How to validate:**
- Join `memory_feedback` ratings with memory age at query time. If older memories are
  disproportionately rated `not_relevant`, there's a real signal. If `not_relevant`
  ratings distribute evenly across ages, recency isn't the problem.
- Examine the query audit log: for injected memories, compute age at injection time.
  Manually review the oldest injected memories — were they correctly injected or noise?
- **Blocker:** The live database only spans ~4 days. This analysis requires either
  waiting for more data to accumulate, or using a synthetic/benchmark dataset with
  temporal spread.

**LoCoMo approach:** LoCoMo conversations span multiple sessions with temporal gaps.
Ingest all sessions, then query from the perspective of the latest session. Check
whether old memories from early sessions are correctly surfaced or incorrectly injected.
This gives us ground truth for "should this old memory appear?"

### Assumption 2: "Exponential decay is the right shape"

**What we're assuming:** That relevance decays exponentially with time, not linearly,
not as a step function, not logarithmically.

**How to validate:**
- Build a parameterized decay eval: replay the same query set with linear, exponential,
  and step-function decay. Measure precision/recall against ground-truth judgments.
- If the curves produce similar results, the shape doesn't matter much and we should
  pick the simplest (linear). If exponential clearly separates, it's justified.
- **Minimum viable test:** Take 10-20 queries where we know the correct injection set.
  Score candidates under each decay shape. See which shape matches ground truth best.

### Assumption 3: "Per-type half-lives are necessary"

**What we're assuming:** That different memory types decay at different rates
(continuity_memory fast, decision slow, atomic_fact never).

**How to validate:**
- Start with a single uniform half-life across all types (except facts which get no
  decay). Measure impact on retrieval quality.
- Then test per-type half-lives. If per-type doesn't meaningfully improve over uniform,
  the extra complexity isn't justified.
- Use LoCoMo: facts should always be retrievable regardless of age (ground truth from
  the benchmark). Decisions from early sessions should still surface for "what did we
  decide about X?" queries. Measure whether per-type decay preserves fact recall while
  suppressing stale context.

### Assumption 4: "The proposed half-life values are correct"

**What we're assuming:** 72h for continuity, 48h for checkpoints, 14d for decisions, etc.

**How to validate:**
- These numbers should NOT be guessed. They should be derived from data:
  - What's the median age of memories that get rated `relevant` vs `not_relevant`?
  - At what age does a memory type's injection precision drop below 50%?
  - What's the natural "useful window" for each type based on supersession patterns?
    (If most thread_summaries get superseded within 24h, a 7-day half-life is too long.)
- **Calibration approach:** Set up a sweep — try half-lives at 1h, 6h, 24h, 72h, 168h,
  336h, 720h for each type. Measure eval metrics at each point. Pick the value that
  maximizes precision without hurting recall below a threshold.
- **Supersession as a proxy:** For types with active supersession (thread_summary,
  task_checkpoint), the median time-to-supersession is an empirical upper bound on
  useful lifetime. A memory that would have been superseded "soon" is already stale.

### Assumption 5: "Post-RRF decay is better than the alternatives"

**What we're assuming:** That applying decay after RRF fusion (Option B) is superior
to a third RRF signal (Option A) or routing-only (Option C).

**How to validate:**
- Build the eval harness with a pluggable decay application point.
- Implement all three options (they're all simple) and measure on the same query set.
- Key metric: does Option B give strictly better precision@k than Option C (which is
  roughly what routing does today)? If routing-only handles it well enough, we don't
  need retrieval-level decay at all.

### Assumption 6: "Decay floor of 0.3 is the right minimum"

**What we're assuming:** That old memories should never be fully suppressed, just
demoted to 30% of their original score.

**How to validate:**
- Test floors at 0.0 (full suppression possible), 0.1, 0.3, 0.5.
- The right floor is the one where old-but-correctly-relevant memories still surface.
  Use known queries where an old memory IS the right answer (e.g., "what did we decide
  about X?" where X was decided weeks ago).
- If floor=0.0 never causes a missed correct injection in the eval set, we can be more
  aggressive. If floor=0.5 still lets noise through, we need it higher.

### Assumption 7: "This won't cause double-penalization with routing"

**What we're assuming:** That retrieval decay + routing freshness penalties are
complementary, not destructive when combined.

**How to validate:**
- Run the full pipeline (decay + routing) on the eval set and compare against
  routing-only. Look specifically for cases where a candidate that SHOULD be injected
  gets killed by the combination.
- Check: does any correctly-relevant candidate receive both decay demotion AND routing
  staleness penalty? If so, the combined penalty is the sum — is that sum ever large
  enough to suppress a correct candidate below a wrong one?

### Proposed Eval Harness Design

```
Input:  A set of (query, expected_injections, expected_non_injections) triples
        with memories spanning a realistic time range (days to weeks)

Method: For each (query, expected) triple:
        1. Retrieve candidates (existing pipeline)
        2. Apply decay with parameterized config
        3. Run routing
        4. Compare injected set against expected
        5. Compute precision@k and recall@k

Sweep:  Run across parameter grid:
        - decay_shape: [none, linear, exponential]
        - half_life_uniform: [24h, 72h, 168h, 336h]
        - floor: [0.0, 0.1, 0.3, 0.5]
        - per_type: [uniform, per_type_proposed]
        - integration_point: [post_rrf, routing_only]

Output: Table showing (config → precision, recall, F1)
        Identify Pareto-optimal configs
```

### Data Sources for the Eval

1. **LoCoMo (primary):** Multi-session conversations with known correct answers.
   Each question has a ground-truth answer derivable from specific conversation turns.
   We can determine which memories SHOULD surface for each question.

2. **Synthetic aging:** Take current Pallium memories, duplicate with timestamps
   shifted to simulate aging. Re-run queries. Judge whether the injection changes
   are improvements.

3. **Production feedback (future):** As `pallium_rate_memory` data accumulates over
   weeks/months, correlate `not_relevant` ratings with memory age to empirically
   measure the actual decay curve of relevance by type.

### Order of Operations

1. **First: Prove the problem exists.** Analyze LoCoMo injection results — are there
   cases where old memories are incorrectly injected over fresher, more relevant ones?
   If not, stop here.
2. **Second: If problem exists, build the eval harness.** Design the sweep grid.
3. **Third: Run the sweep.** Find parameters empirically.
4. **Fourth: Implement with validated parameters.** Not guessed ones.

---

## Next Steps (if pursued)

1. **Validate Assumption 1** — analyze LoCoMo for temporal injection errors
2. If validated: build parameterized eval harness with sweep grid
3. Run sweep to find optimal parameters empirically
4. Implement with data-derived parameters
5. Regression check against existing evals
6. Monitor with `pallium_rate_memory` feedback loop post-deployment
