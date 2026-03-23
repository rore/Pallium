# Off-Topic Injection: QPP-Based Abstention Design

## Problem

Pallium injects memories into off-topic queries ("how's the weather?") because
retrieval always returns something, and the injection decision doesn't evaluate
whether the result set is trustworthy. Lexical overlap checks can't solve this
because legitimate recall queries ("what should I do next?") also have zero
overlap with the memories they should retrieve.

## Why Previous Approaches Failed

| Approach | Why it fails |
|---|---|
| Lexical-only floor activation | Breaks cross-thread recall — memory text views have generic wording, score too low |
| Per-candidate relevance gate | Same problem — blocks legitimate memories with weak lexical scores |
| Per-block content overlap check | Breaks vague recall — "what should I do next?" shares no words with "batch 417 blocked by stale handles" |
| Intent classification | Pallium is a stateless API — no conversation history, no agent-side intent hints |

## The Right Framing: Query Performance Prediction

The IR literature has an established field called QPP (Query Performance
Prediction): estimate whether retrieval produced a trustworthy result set,
without relevance labels, using only the query and the returned ranked list.

Key finding (SIGIR 2011): **score standard deviation across the top-k results**
outperforms prior QPP approaches without tuning. Flat distributions = noise.
Peaked distributions = real match.

This fits Pallium's stateless constraint perfectly: we don't need conversation
history, intent labels, or agent cooperation. We just look at what retrieval
gave us and decide if it's worth injecting.

## Signals Available at Injection Decision Time

All of these exist on the candidate dicts in `_build_injectable_blocks` without
any new data structures or agent-side changes:

### Score shape signals (QPP core)
- **Top score strength**: `ranked_candidates[0]["routing_score"]`
- **Score dispersion**: std dev of `routing_score` across top-k candidates
- **Top-1 to top-2 gap**: sharp peak = confident match, small gap = noisy tie
- **Score flatness**: are all candidates within a narrow band?

### Multi-channel agreement (composite mode)
- **Retrieval source distribution**: ratio of "both"/"lexical"/"vector" among
  top candidates. Strong agreement across channels = higher confidence.
- **Lexical-vector rank correlation**: do both retrieval paths point to the
  same candidates?

### Memory structure signals (Pallium-specific)
- **Memory type richness**: are there `task_checkpoint`, `decision`, or
  `investigation_outcome` candidates? These only exist when real work happened.
  Their presence is structural evidence the container has relevant content.
- **Support grade distribution**: `support_grade` on each candidate
  (weak/supported/strong). All-weak = low justification.
- **Work signal types**: `blocker`, `next_step` on candidates — evidence of
  actionable work state regardless of query wording.

### Temporal signals
- **Recency of best candidates**: fresh memories = higher justification for
  injection on vague queries. Stale memories + weak scores = suppress.
- **Container cadence**: normalize recency to the container's own tempo
  (a 3-day-old memory in a fast channel is stale; in a long project it's fresh).

## Proposed Injection Policy

**Default to abstention. Promote to injection only when justified.**

### Inject when ANY of these holds:
- Top candidate score is strong AND score distribution is peaked (clear winner)
- Multiple retrieval channels agree on the same candidate cluster
- Candidate set contains recent, well-supported work memories (task_checkpoint,
  decision, investigation_outcome with support_grade != "weak")
- Existing `work_resumption` lane selected AND active checkpoint exists

### Suppress when MOST of these hold:
- Score distribution is flat (low dispersion across top-k)
- Top-1 to top-2 gap is small (no clear winner)
- Only weak-support summaries or interests in candidate set
- Best candidates are stale relative to container cadence
- No active work artifacts (no task_checkpoints, no investigations)

## Implementation Shape

Replace the current binary relevance floor with a **justification score**
computed from the signals above. The justification score is a weighted
combination — not a single threshold on one signal.

```
justification = (
    w_score * normalized_top_score
    + w_dispersion * score_dispersion
    + w_gap * normalized_top_gap
    + w_type * memory_type_richness
    + w_support * support_grade_strength
    + w_recency * recency_factor
)

inject = justification >= INJECTION_THRESHOLD
```

The weights and threshold should be calibrated empirically on Pallium's own
scenarios (the existing benchmark suites + the new exploratory QA scenarios
provide the calibration set).

This replaces:
- `_any_candidate_passes_retrieval_relevance_floor` (current batch gate)
- The lexical-only bypass (`return True, "lexical_only_retrieval"`)
- The defensive passes for missing scores

## What This Handles

| Case | Score shape | Structure | Recency | Result |
|---|---|---|---|---|
| "how's the weather?" | Flat, weak | No work artifacts | N/A | **Suppress** |
| "what should I do next?" | May be flat | Active task_checkpoint | Recent | **Inject** (structure justifies) |
| "what did we decide about ordering?" | Peaked | Decision in candidates | Recent | **Inject** (score + structure) |
| "under the weather" (idiom) | Single peak on "weather" | No work artifacts | Mixed | **Suppress** (single peak + no structure) |
| "let's talk about something new" | Flat/none | May have old artifacts | Stale | **Suppress** (no score evidence) |
| "remind me about that thing" | May be weak | Has relevant memories | Recent | **Inject** (structure + recency) |

## Relationship to Existing Architecture

This builds on, not replaces, the existing routing pipeline:
- Lane narrowing (work_resumption, evidence_trace, residual_recall) stays
- Signal envelope (low_value, history_lookup, etc.) stays
- Scoring and ranking stays
- The justification score replaces only the final injection gate

The change is localized to `_build_injectable_blocks` in
`routing_selection.py`, replacing the floor check with the justification
computation.

## Calibration Strategy

Per Cohere's guidance: build a calibration set of ~50 representative queries
(mix of on-topic recall, off-topic noise, vague resumption, topic switch).
For each, label whether injection was correct. Derive weights and threshold
from that set.

Pallium already has the calibration data:
- Existing benchmark suites (memory_routing, work_resumption): known-good injection
- Exploratory QA seed scenarios: known-bad injection (off-topic)
- Generated scenarios: coverage expansion

## Next Steps

1. Implement the justification score computation as a function
2. Wire it into `_build_injectable_blocks` alongside (not replacing) the
   existing floor
3. Calibrate weights on existing benchmark + seed scenario results
4. Validate with full regression + invariant runner
5. Remove the lexical-only floor bypass once calibration confirms safety
