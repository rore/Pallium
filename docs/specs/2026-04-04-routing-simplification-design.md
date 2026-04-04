# Routing Simplification — Design

**Date:** 2026-04-04
**Status:** Draft

## Problem

Pallium's query routing pipeline has 17 stages, 6 intent families, 4 recall modes, 4 policy
families, and 3 lanes. Each stage was added to fix a specific failure, but the stages communicate
through shared mutable score fields (`base_routing_score`, `support_score`,
`suppression_reason_code`), creating cascading interactions. Fixing one failure mode shifts the
score landscape for another.

End-to-end integration tests consistently surface new failures in basic interactions. The root
cause is not individual stage logic — each stage is locally correct. The problem is three
structural mechanisms:

### A. Score cascade

Three suppression stages and two shaping stages modify `base_routing_score` and `support_score`
in sequence. QPP justification then reads the final modified values. A change in freshness
shaping shifts QPP inputs. A suppression false-positive in one stage cascades to all four
downstream consumers. Stages are coupled through shared mutable state, not through explicit
interfaces.

### B. RRF destroying quality signal

RRF fusion uses rank position only — actual retrieval scores are discarded during fusion. A
cosine-0.56 hit and a cosine-0.95 hit at the same rank contribute identically. The fused
`retrieval_score` falls in an 8–19 integer range with most candidates clustered at 9–11. Routing
receives a nearly-flat distribution and must reconstruct quality through indirect proxies (QPP's
4-gate system, score dispersion analysis, support grade inference).

### C. Category explosion

6 intent families produce a 6×N layer weight matrix, 6 sets of specificity bonuses, and
per-family selection logic. Several families share nearly identical behavior:

- `answer_continuity` and `broad_recall` use the same selection logic
- `precise_fact` and `investigative_conclusion` both seek specific structured memory
- Only `work_resumption` and `evidence_trace` have genuinely distinct composition needs

The 4 recall modes, 4 policy families, and mode-to-intent mapping add further combinatorial
surface. Many combinations are never exercised in practice.

## Investigation Findings

### Routing stage inventory

A full stage-by-stage audit classified each of the 17 routing stages:

| Stage | Purpose | Classification |
|---|---|---|
| Anchor prefilter | Topic scoping via subject hints | Retrieval compensation |
| Policy evidence + typed candidate evidence | Scan candidate types/signals | Genuinely needed |
| Signal envelope derivation | Query classification from structure | Mixed |
| Noise short-circuit | Empty/ultra-short query guard | Genuinely needed |
| Evidence trace override (resolver) | LLM-mediated disambiguation | Retrieval compensation |
| Lane narrowing | Route unambiguous queries fast | Mixed |
| Kind prefilter | Filter by memory envelope kind per intent | Retrieval compensation |
| Base scoring | Intent-weighted candidate ranking | Genuinely needed |
| Anchor tier penalty | Enforce anchor tier ordering | Retrieval compensation |
| Current query source suppression | Block self-echo | Retrieval compensation |
| Same-kind freshness shaping | Demote stale same-type candidates | Retrieval compensation |
| Fresh thread structured recall preference | Prefer structured over source in fresh sessions | Mixed |
| Recall source noise suppression | Block meta-text and duplicate echoes | Retrieval compensation |
| Recall structured summary suppression | Block weak thread summaries | Retrieval compensation |
| Work resumption packaging | Freshness + usefulness for checkpoints | Mixed |
| Routing focus selection + final score | Layer emphasis via boost | Genuinely needed |
| Final candidate selection | Result composition per intent | Genuinely needed |
| Injection eligibility + QPP justification | Off-topic guard + same-thread check | Mixed |
| Injectable block construction | Type-specific formatting | Genuinely needed |

8 stages exist primarily to compensate for retrieval imprecision. 6 are genuinely needed. 5 are
mixed. The 8 compensation stages are the primary source of cascading interactions.

### Retrieval precision analysis

Key findings from the retrieval layer audit:

- **RRF formula:** `fused = int((1/(60+rank_lex) + 1/(60+rank_vec)) * 600)`. An item at rank 50
  in both lists (score 10) outranks an item at rank 1 in one list only (score 9). Weak
  overlapping signals beat strong single signals.
- **IDF compression:** `_IDF_SCORE_SCALE = 1` produces scores in the 1–5 integer range. Many
  non-relevant items score 1 (the floor). Minimal discrimination for common-word queries.
- **Vector threshold:** `min_similarity = 0.55` is the only hard quality gate. Generic queries
  produce many items in the 0.55–0.65 range with no clean separation from relevant results.
- **No quality signal:** Retrieval provides no indication of whether its results are strong or
  weak. Routing must infer this indirectly.

### Invariant risk assessment

Of 13 invariants (INV-01 through INV-13), only INV-03 (no off-topic injection) and INV-05
(recall not routed as noise) exercise routing logic that would be affected by simplification.
INV-03 is the critical constraint — it requires that injected memory share lexical overlap with
the query, which the current QPP Gate 1b enforces.

### Clean separation assessment

A full discrimination layer with "no intent knowledge" was considered and rejected. Several
discrimination decisions are inherently intent-dependent:

- Weak summary suppression applies to recall intents but not work resumption (where a weak
  summary may be the only available context)
- Source hit demotion applies to fresh-session recall but not evidence trace
- Content quality thresholds vary by what the query is trying to accomplish

The practical approach is targeted simplification of specific brittleness mechanisms rather
than architectural re-layering.

## Design

### Overview

Seven changes that address the three brittleness mechanisms directly:

1. Use raw retrieval scores for quality decisions (fixes mechanism B)
2. Consolidate suppression into a single pass (fixes mechanism A)
3. Replace QPP 4-gate system with 2 direct checks (fixes mechanisms A and B)
4. Fold freshness and anchor tier into the base scoring formula (fixes mechanism A)
5. Reduce intent families from 6 to 4 (fixes mechanism C)
6. Remove the evidence trace resolver LLM call (simplifies, reduces cost)
7. Add a light relevance floor before routing (reduces candidate count)

### Change 1: Raw retrieval scores as quality signal

**Current state.** Routing's base scoring formula uses `retrieval_score * 10` where
`retrieval_score` is the RRF fused integer (8–19 range). Raw `lexical_score` and `vector_score`
are preserved on each result but only read by QPP, not by scoring.

**Change.** Introduce a `quality_score` computed from raw scores:

```
quality_score = max(
    lexical_score / LEXICAL_NORM_SCALE,   # fixed constant (6), gives 0–1 range
    vector_score / 1000                    # cosine * 1000 → back to 0–1 range
)
```

Replace `retrieval_score * 10` with `quality_score * QUALITY_WEIGHT` in the base scoring formula.
Keep `retrieval_score` (RRF) for ranking tiebreaks only.

`LEXICAL_NORM_SCALE = 6` is a fixed constant, not result-set-dependent. It represents the
approximate theoretical max IDF for corpora up to ~400 items (log(400) ≈ 6). IDF scores above 6
are possible for very rare terms in larger corpora but are clamped to 1.0 — these are already
the strongest possible signal, so clamping is correct.

**Why.** Routing needs to know "how strongly did retrieval match this candidate?" The current RRF
integer cannot answer this. Raw scores can. This makes downstream quality decisions (QPP, freshness,
suppression) more reliable because they operate on actual signal strength, not rank position.

### Change 2: Unified suppression pass

**Current state.** Three stages write `suppression_reason_code` in sequence:
1. Current query source suppression (stage 8)
2. Recall source noise suppression (stage 11)
3. Recall structured summary suppression (stage 12)

Four downstream stages read this field. Ordering between suppression stages matters because
later stages check `suppression_reason_code` to skip already-suppressed candidates.

**Change.** Replace the three stages with a single function `_apply_suppression(candidate, query_context, intent)`:

```python
def _apply_suppression(candidate, query_context, intent):
    """Returns (suppressed: bool, reason_code: str | None)."""
    # 1. Echo: same-thread source whose text matches query
    if _is_current_query_echo(candidate, query_context):
        return True, "current_query_source_echo"
    # 2. Meta-text: orchestration boilerplate (source hits only)
    if candidate.is_source_hit and _is_low_value_meta_text(candidate):
        return True, "low_value_meta_text"
    # 3. Weak summary: intent-gated (recall intents only)
    if intent in RECALL_INTENTS and _is_weak_summary(candidate):
        return True, "weak_summary"
    return False, None
```

Called once per candidate during scoring. No intermediate state. Priority order is intentional
(echo > meta-text > weak summary) — the function returns on first match. A candidate can only
have one suppression reason.

**Why.** Eliminates the cascade where a false positive in one suppression stage makes a candidate
invisible to all four downstream consumers with no recovery path.

### Change 3: Simplified injection check

**Current state.** QPP has 4 gates with weighted scoring:
- Gate 1a: strong retrieval + supported evidence
- Gate 1b: moderate IDF-weighted retrieval (the off-topic guard)
- Gate 2: active work signals + high-value types + routing score
- Gate 3/4: peaked score distribution with minimum retrieval / high vector confidence

These gates read `routing_score` (post-focus-boost), `support_grade` (modified by upstream
shaping), and composite retrieval scores through a normalized range (`routing_score_max = 700.0`).

**Change.** Two levels of injection gating:

**Set-level gate** — decides whether to inject at all:

```python
def _should_allow_injection(candidates, query_context):
    best_lexical = max(c.lexical_score for c in candidates)
    best_vector = max(c.vector_score for c in candidates)

    # Condition 1: meaningful lexical overlap somewhere in the set
    if best_lexical >= INJECTION_LEXICAL_THRESHOLD:
        return True
    # Condition 2: strong vector match WITH some lexical signal
    if best_vector >= INJECTION_VECTOR_HIGH and best_lexical >= INJECTION_LEXICAL_LOW:
        return True
    return False
```

**Per-candidate eligibility** — each candidate that will be injected must individually have
minimum lexical grounding:

```python
def _candidate_injection_eligible(candidate):
    # Must have at least one shared word with the query
    if candidate.lexical_score >= CANDIDATE_LEXICAL_FLOOR:
        return True
    # OR very strong vector match (semantic near-duplicate)
    if candidate.vector_score >= CANDIDATE_VECTOR_OVERRIDE:
        return True
    return False
```

This prevents a scenario where the set-level check passes (because candidate B has lexical
overlap) but the top-ranked candidate A (which will actually be injected) has zero lexical
overlap. Candidate A must independently qualify.

Initial thresholds (calibrated in validation phase):
- `INJECTION_LEXICAL_THRESHOLD`: IDF score 3 (at least one discriminating term in the set)
- `INJECTION_VECTOR_HIGH`: cosine 0.75 (strong semantic match)
- `INJECTION_LEXICAL_LOW`: IDF score 1 (at least one shared word in the set)
- `CANDIDATE_LEXICAL_FLOOR`: IDF score 1 (per-candidate minimum)
- `CANDIDATE_VECTOR_OVERRIDE`: cosine 0.80 (per-candidate: strong enough to inject without
  lexical signal — e.g., a paraphrase with different vocabulary)

**Why.** The essential QPP insight is "don't inject without lexical overlap" (Gate 1b). The other
gates are refinements that add complexity without proportional quality gain. The two-condition
check preserves INV-03 protection — a weather query with zero lexical overlap is blocked — without
the fragile dependency on post-shaping `routing_score` and `support_grade`.

### Change 4: Single-pass base scoring

**Current state.** Base scoring produces an initial `base_routing_score`, then 5 subsequent stages
modify it: anchor tier penalty, same-kind freshness shaping, fresh-thread preference, recall
source suppression, and work resumption packaging. Each stage reads the value set by previous
stages.

**Change.** Compute the final score in one pass with all components visible:

```python
def _compute_routing_score(candidate, intent, query_context, scoring_context):
    score = (
        LAYER_WEIGHTS[intent][candidate.layer]
        + candidate.quality_score * QUALITY_WEIGHT
        + _specificity_bonus(intent, candidate.type)
        + _anchor_component(candidate.topic_tier)
        + _freshness_component(candidate.freshness_rank, intent)
        + _locality_component(candidate, intent)
        + _evidence_richness(candidate)
        + _usefulness_bonus(candidate, intent)
    )
        + _locality_component(candidate, intent)
    )
    return score
```

Where:
- `_anchor_component`: aligned → 0, secondary → `-ANCHOR_PENALTY`
- `_freshness_component`: rank 1 in type → `+FRESHNESS_BONUS[intent]`, rank 2 → 0,
  rank 3+ → `-FRESHNESS_DECAY_PER_RANK * (rank - 2)`. Returns 0 for intents that don't use
  freshness shaping.
- `_locality_component`: same-thread bonus for continuity, cross-container penalty. Returns 0
  for intents that don't use locality.
- `_evidence_richness`: count of non-null payload fields (evidence count, thread/container
  match, conclusion text, rationale). Distinguishes thin candidates (one-liner decision) from
  rich ones (decision with full rationale and evidence chain). Carries forward the current
  `evidence_shape_score` logic, applied uniformly across intents.
- `_usefulness_bonus`: returns 0 for all intents except `work_resumption`. For work resumption,
  scores checkpoint candidates by operational signal presence (blocker, next_step,
  progress_update, key_finding, freshness). This is the current work resumption usefulness
  logic, now a visible component instead of a hidden shaping pass.

Pre-computation step before scoring: sort candidates by type and timestamp to assign
`freshness_rank` and `topic_tier` (from anchor prefilter). These are annotations, not score
modifications.

**Why.** No stage modifies scores that a later stage reads. All components are visible in one
place. Changing the freshness formula doesn't shift QPP inputs. Changing the anchor penalty
doesn't require checking a comment about focus boost magnitude.

### Change 5: Reduced intent families

**Current state.** 6 intent families: `answer_continuity`, `broad_recall`, `work_resumption`,
`precise_fact`, `evidence_trace`, `investigative_conclusion`.

**Change.** Merge to 4:

| New family | Merges | Rationale |
|---|---|---|
| `recall` | `answer_continuity` + `broad_recall` | Same selection logic, same candidate composition. Differences expressed through a `recall_mode` flag (continuity vs broad) that adjusts layer weight preferences. |
| `structured_recall` | `precise_fact` + `investigative_conclusion` | Both seek specific structured memory (decisions, investigations). Differences expressed through layer weight adjustments for investigation-specific freshness. |
| `work_resumption` | (unchanged) | Genuinely distinct: checkpoint + adjacent evidence composition, usefulness scoring, freshness gating. |
| `evidence_trace` | (unchanged) | Genuinely distinct: source hit preference, evidence-backed raw content. |

Layer weight matrix shrinks from 6×N to 4×N. Specificity bonus table shrinks proportionally.
Selection logic for `recall` and `structured_recall` unifies the currently-duplicated paths.

**Why.** Fewer families means fewer combinations to test and fewer surprising interactions. The
merged families had near-identical scoring and selection logic — the differences were in
thresholds, not behavior.

### Change 6: Remove evidence trace resolver LLM call

**Current state.** `_resolve_ambiguity` in `routing_policy.py` calls an LLM to disambiguate
between `evidence_trace` and a recall family when structural signals are ambiguous. It's the only
LLM call in the query-time routing path.

**Change.** Remove. When the evidence_trace lane has ambiguous signals, default to
`residual_recall` (the safe fallback). With raw quality scores available (Change 1), the
source-hit ratio signal becomes cleaner — if most high-quality candidates are source hits, the
lane narrowing logic can make the evidence_trace decision without LLM mediation.

Strengthen the structural signal: if `quality_score`-weighted source hit mass exceeds structured
memory mass by a configurable ratio, select evidence_trace deterministically.

**Why.** The resolver fires rarely, adds latency and cost, and is a complexity hotspot (it
interacts with the envelope derivation and lane narrowing). The quality-weighted source ratio is
a more reliable signal because it uses actual retrieval confidence, not rank position.

### Change 7: Light relevance floor

**Current state.** All candidates above `min_similarity = 0.55` (vector) or `IDF score >= 1`
(lexical) survive to routing. No pre-routing quality filter.

**Change.** Add a filter function before routing that drops candidates failing both:
- Vector cosine < `FLOOR_MIN_VECTOR` (initial: 0.58)
- IDF score < `FLOOR_MIN_LEXICAL` (initial: 2)

Candidates must pass at least one threshold. The floor is deliberately conservative — it removes
only the weakest tail of results. It's a safety net, not the primary quality mechanism.

**Why.** Reduces candidate count from up to 50 to a tighter set, which means every subsequent
stage (anchor, scoring, selection) operates on less noise. The floor's conservatism means it's
unlikely to cause recall loss, but it removes the long tail of barely-matching items that
create the most spurious interactions in scoring.

**Edge case: empty after floor.** If all candidates are filtered, routing receives an empty set.
This should produce `should_inject=False` with `decision_reason="no_candidates_above_floor"` —
distinct from the noise gate's `"low_value_query"` reason, since the query itself may be
substantive but nothing in memory matches it well enough. The trace should log how many
candidates were filtered and their score ranges.

### Stages absorbed by other changes

Two stages from the current pipeline are not listed as explicit changes but are absorbed:

**Kind prefilter** (currently filters candidates by write-time envelope kind per intent). Absorbed
into the single-pass scoring formula as part of `_specificity_bonus`. Instead of hard-excluding
candidates with the wrong envelope kind, the specificity bonus gives strong positive weight to
matching kinds and zero or negative weight to non-matching kinds. This preserves the preference
without the binary gate — a candidate with the wrong kind can still surface if it has very
strong quality and anchor scores, which is the right behavior when kind assignment is
probabilistic.

**Work resumption packaging** (freshness + usefulness scoring for checkpoints). The freshness
component is absorbed into `_freshness_component` in base scoring. The usefulness scoring
(counting work signal types: blocker, next_step, progress_update) is absorbed into
`_usefulness_bonus` — an explicit component of the scoring formula that returns 0 for
non-work-resumption intents.

### Recall mode within the merged `recall` family

The merged `recall` family uses a `recall_mode` flag derived from the signal envelope:
- `continuity` when the envelope indicates a history lookup or the dominant candidate layer
  is continuity/pattern memory
- `broad` otherwise (the default)

The flag adjusts layer weight preferences within the `recall` family's weight table (continuity
mode boosts continuity_memory and pattern_memory layers; broad mode uses the default weights).
This replaces the current 4-mode recall system with a single binary flag.

## Resulting Pipeline

```
1. Relevance floor          (pre-filter on raw scores)
2. Anchor prefilter          (topic scoping → tier annotation)
3. Signal envelope + noise gate
4. Lane narrowing            (no resolver LLM call)
5. Base scoring              (single formula: layer weight + quality + specificity
                              + anchor + freshness + locality + suppression)
6. Focus selection           (adds focus boost to winning layer)
7. Candidate selection
8. Injection check           (2-condition: lexical threshold OR vector+lexical)
9. Same-thread suppression
10. Block construction
```

10 stages, down from 17. Key structural properties:

- **Minimal score mutation.** Base scoring produces the primary score. Focus selection adds one
  boost to the winning layer's candidates. That is the only post-scoring adjustment — down
  from 5 sequential modifications. Suppression is a boolean flag set during scoring, not a
  score penalty. The injection check reads raw retrieval scores, not routing scores.
- **No mutable shared state.** Each stage reads annotations set by earlier stages (tier, freshness
  rank, suppression flag) but does not modify values that later stages depend on for scoring.
  The one exception (focus boost) is a single, well-defined additive step.
- **Fewer categories.** 4 intent families, 3 lanes (unchanged), 1 binary recall mode flag.
  The combinatorial surface is smaller.
- **Quality signal available.** Stages that need to know "is this a strong match?" read
  `quality_score` directly instead of inferring it from score distributions.

## Validation and Regression Strategy

### Baseline capture (before any changes)

Before starting implementation, capture the current system's behavior as a baseline:

1. **Run the full invariant suite** (`python -m evals.generated_exploratory.invariant_runner`)
   against the seed scenarios. Record pass/fail per invariant per scenario.
2. **Run the routing benchmark** (`evals/memory_routing_benchmark.py`). Record intent match rate,
   injection contract success, and policy success counts.
3. **Snapshot routing trace output** for a fixed set of 10–15 representative queries (covering
   each intent family, off-topic, greeting, work resumption, recall, fresh session). Save the
   full debug trace JSON. These become the regression reference.

Store baselines in `evals/baselines/` (gitignored for local iteration, committed when stable).

### Per-change validation

Each of the 7 changes is independently deployable and testable. After each change:

1. **Unit tests.** Each change modifies or replaces specific functions. The existing test suite
   covers these:
   - `tests/test_routing_justification.py` — QPP gates (Change 3)
   - `tests/test_agent_conversation_memory_routing_query_signals.py` — signal envelope (unchanged)
   - `tests/test_agent_conversation_memory_routing_lane_narrowing.py` — lanes (Change 6)
   - `tests/test_memory_routing_benchmark.py` — benchmark smoke test
   - New unit tests for: unified suppression function, single-pass scoring formula, simplified
     injection check, relevance floor

2. **Invariant suite.** Run after each change. All 13 invariants must pass. INV-03 (off-topic)
   is the canary — if it fails, the injection check thresholds need adjustment.

3. **Benchmark comparison.** Compare routing benchmark results against the baseline. Acceptable
   outcomes:
   - Same or better intent match rate
   - Same or better injection contract success
   - Policy success count may shift (families are merging) but should not decrease in aggregate

4. **Trace comparison.** For the 10–15 reference queries, compare debug trace output against
   baseline snapshots. Categorize differences as:
   - **Expected:** candidate scores changed due to quality_score (Change 1), suppression reasons
     consolidated (Change 2), intent family names changed (Change 5)
   - **Investigate:** a query that was previously injected is now suppressed, or vice versa
   - **Regression:** an invariant violation or a clearly worse result

### Integration validation

After all 7 changes are applied:

1. **Full invariant suite** with `--workers 4`. All 13 must pass.
2. **End-to-end interaction test** with the integrating agent. Run the same interaction sequences
   that originally surfaced failures (same-thread suppression race, off-topic injection, stale
   memory pollution). Verify improvements.
3. **Exploratory QA generation.** Generate P2 scenarios from taxonomy
   (`python -m evals.generated_exploratory.generator --high-risk-only --count 5`) to probe for
   new failure modes introduced by the simplification.

### Threshold iteration

Three sets of thresholds need calibration:

| Threshold | Initial value | What to watch |
|---|---|---|
| `FLOOR_MIN_VECTOR` | 0.58 | If recall drops (relevant memory filtered), lower toward 0.55 |
| `FLOOR_MIN_LEXICAL` | 2 | If recall drops, lower to 1. If noise persists, raise to 3 |
| `INJECTION_LEXICAL_THRESHOLD` | 3 | If off-topic injection (INV-03 fail), raise. If valid injection suppressed, lower |
| `INJECTION_VECTOR_HIGH` | 0.75 | If strong-vector-only matches are wrongly suppressed, lower to 0.70 |
| `INJECTION_LEXICAL_LOW` | 1 | Floor — should rarely need adjustment |
| `CANDIDATE_LEXICAL_FLOOR` | 1 | Per-candidate minimum. If legitimate paraphrases are blocked, lower or rely on vector override |
| `CANDIDATE_VECTOR_OVERRIDE` | 0.80 | Per-candidate: allows injection without lexical signal for near-duplicates |
| `LEXICAL_NORM_SCALE` | 6 | Fixed. Only adjust if corpus sizes regularly exceed ~400 items |
| `FRESHNESS_BONUS` (per intent) | Carry forward current values | If stale memory dominates fresh, increase. If recent-but-weak wins over old-but-strong, decrease |
| `ANCHOR_PENALTY` | 120 (carry forward) | Must be >= FOCUS_BOOST. If secondary candidates displace aligned, increase |

Iteration process for each threshold:
1. Run invariant suite + benchmark with current value
2. If a specific failure mode appears, adjust the relevant threshold
3. Re-run to verify fix doesn't introduce a regression
4. Log the adjustment and rationale in the threshold's code comment

All thresholds are defined in `routing_constants.py` with documentation of their purpose,
valid range, and what failure mode they protect against. No magic numbers in scoring functions.

### Rollback safety

Each change is a separate commit. If a change causes regressions that threshold tuning cannot
resolve, revert that single commit. The changes are designed to be independent:

- Changes 1–4 modify the scoring and suppression internals
- Change 5 modifies the intent taxonomy
- Change 6 removes the resolver
- Change 7 adds the floor pre-filter

A problem in Change 3 (injection check) can be reverted without affecting Change 1 (quality
score) or Change 4 (single-pass scoring). The one dependency: Change 3's simplified injection
check uses `quality_score` from Change 1, so reverting Change 1 requires also reverting Change 3.
This dependency should be documented in commit messages.

## Implementation Order

Recommended sequence, designed to validate incrementally and minimize risk:

1. **Change 1: Raw retrieval scores.** Foundation for other changes. Low risk — adds a field,
   doesn't remove anything. Validate: benchmark results should be similar (scoring formula still
   uses RRF as primary, quality_score as new secondary input).

2. **Change 7: Relevance floor.** Independent of other changes. Start with very conservative
   thresholds (0.56 vector, 1 lexical — barely above current minimums). Validate: invariant
   suite passes, candidate counts decrease slightly. Tighten thresholds once baseline is
   confirmed safe.

3. **Change 2: Unified suppression.** Behavior-preserving refactor — same checks, one function.
   Validate: trace output should show identical suppression decisions.

4. **Change 4: Single-pass scoring.** Behavior-preserving refactor — same score components,
   one formula. Validate: trace output should show identical or very similar final scores
   (small floating-point differences acceptable).

5. **Change 5: Reduced intent families.** Merges families with near-identical behavior.
   Validate: benchmark intent match rate adjusts for new family names. Injection decisions
   should be similar.

6. **Change 3: Simplified injection check.** Replaces QPP. This is the highest-risk change —
   validate extensively against INV-03 scenarios and the off-topic test cases in
   `test_routing_justification.py`. Run with threshold logging to verify calibration.

7. **Change 6: Remove resolver.** Final cleanup. Validate: evidence_trace queries still route
   correctly via structural signals. Check that the quality-weighted source ratio is
   sufficient.

## Scope and Non-Goals

**In scope:**
- The 7 changes described above
- Threshold calibration using existing eval infrastructure
- Updating routing trace output to reflect the new pipeline
- Updating unit tests for modified/replaced functions

**Out of scope:**
- Score-aware RRF fusion (possible future improvement — not needed for this work since raw
  scores are preserved and used directly)
- Changes to the retrieval layer itself (lexical search, vector search, IDF computation)
- Changes to write-time extraction or memory type taxonomy
- Changes to the storage layer or filter predicates
- New invariants (the existing 13 cover the risk surface)

## Key Code Locations

| Component | File | What changes |
|---|---|---|
| Base scoring + shaping passes | `semantic/agent_conversation_memory_routing_scoring.py` | Major: refactor to single-pass formula, remove 5 shaping stages |
| QPP justification | `semantic/agent_conversation_memory_routing_justification.py` | Replace 4-gate system with 2-condition check |
| Main orchestrator | `semantic/agent_conversation_memory_routing.py` | Simplify: remove stage calls, add floor, reorder |
| Constants | `semantic/agent_conversation_memory_routing_constants.py` | Reduce intent families, update weight matrices, add threshold constants |
| Lane narrowing | `semantic/agent_conversation_memory_routing_policy.py` | Remove resolver LLM call, add quality-weighted source ratio |
| Selection | `semantic/agent_conversation_memory_routing_selection.py` | Adjust for 4 intent families, same-thread suppression unchanged |
| Signals | `semantic/agent_conversation_memory_routing_signals.py` | Unchanged (signal envelope stays as-is) |
| Candidate selection | `semantic/agent_conversation_memory_routing_selection.py` | Unify recall selection paths |
| Query executor | `core/query.py` | Add relevance floor filter call |
