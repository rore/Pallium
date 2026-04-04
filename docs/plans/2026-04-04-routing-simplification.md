# Routing Simplification Implementation Plan (Revised v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify Pallium's 17-stage routing pipeline to 10 stages by eliminating score cascade coupling, using raw retrieval scores instead of flat RRF integers, and reducing intent families from 6 to 4.

**Architecture:** Four phases, each independently validatable. Phase 1 builds new modules alongside existing code (no behavior change). Phase 2 rewires the orchestrator — the formula switch and shaping removal happen atomically in one task to avoid score scale mismatch. Phase 3 is a mechanical intent name rename across ~30 files. Phase 4 replaces QPP, removes dead code, and formalizes the new dict contract.

**Tech Stack:** Python 3.12+, pytest, existing eval harness (invariant runner, routing benchmark)

**Spec:** `docs/specs/2026-04-04-routing-simplification-design.md`

**Critical design decisions in this plan:**
- The formula change (`quality_score * QUALITY_WEIGHT` replacing `retrieval_score * 10`) happens atomically with shaping stage removal (Task 9). Never let old-scale penalties run against new-scale scores.
- `_score_routed_candidate` is modified in-place, producing the exact same 24-field dict shape. No separate v2 module.
- Multi-candidate logic (relative freshness, structured support ratio) is extracted into pre-computation annotations that run once over all candidates before per-candidate scoring.
- Suppression applies a boolean flag AND a modest score penalty (-50) as defense-in-depth, not just a flag.
- The `ScoredCandidate` TypedDict is created in Phase 4 after the dict shape is stable, not before.
- Intent rename is a separate mechanical phase (Phase 3) after scoring is validated stable.

---

## Phase 1: Foundation (no behavior change)

Build new modules alongside existing code. Nothing is wired in. All existing tests pass unchanged.

### Task 1: Add quality_score to scored candidates

Adds `quality_score` as a new field on every scored candidate dict. Does NOT change the scoring formula — `base_routing_score` still uses `retrieval_score * 10`.

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_constants.py`
- Modify: `semantic/agent_conversation_memory_routing_scoring.py:567-623`
- Test: `tests/test_routing_quality_score.py`

- [ ] **Step 1: Write failing test for `_compute_quality_score`**

Create `tests/test_routing_quality_score.py`:

```python
"""Tests for quality_score computation from raw retrieval scores."""
from semantic.agent_conversation_memory_routing_scoring import _compute_quality_score

def test_vector_dominant():
    assert abs(_compute_quality_score(lexical_score=2, vector_score=800) - 0.8) < 0.01

def test_lexical_dominant():
    assert abs(_compute_quality_score(lexical_score=5, vector_score=400) - 0.833) < 0.01

def test_clamps_lexical():
    assert abs(_compute_quality_score(lexical_score=8, vector_score=0) - 1.0) < 0.01

def test_zero_both():
    assert _compute_quality_score(lexical_score=0, vector_score=0) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_routing_quality_score.py -v`

- [ ] **Step 3: Add constant and implement**

In `semantic/agent_conversation_memory_routing_constants.py`:

```python
LEXICAL_NORM_SCALE = 6  # ~log(400); fixed for IDF→[0,1] normalization
QUALITY_WEIGHT = 100    # multiplier for quality_score in scoring formula (used in Phase 2)
```

In `semantic/agent_conversation_memory_routing_scoring.py`:

```python
def _compute_quality_score(lexical_score: int, vector_score: int) -> float:
    """Normalized quality from raw retrieval scores. Returns 0.0-1.0."""
    return max(min(lexical_score / LEXICAL_NORM_SCALE, 1.0), vector_score / 1000.0)
```

Wire into `_score_routed_candidate`: add `"quality_score": _compute_quality_score(...)` to the returned dict. Do NOT touch the `base_routing_score` formula.

- [ ] **Step 4: Run all tests, commit**

```bash
git commit -m "feat: add quality_score field to scored candidates (no formula change)"
```

---

### Task 2: Relevance floor module

**Files:**
- Create: `semantic/agent_conversation_memory_routing_floor.py`
- Test: `tests/test_routing_relevance_floor.py`

- [ ] **Step 1: Write failing test**

Test: strong vector passes, strong lexical passes, weak both filtered, empty input, custom thresholds via `FloorThresholds` dataclass.

- [ ] **Step 2: Implement**

Create `semantic/agent_conversation_memory_routing_floor.py` with `apply_relevance_floor()` function and `FloorThresholds` dataclass (thresholds as frozen dataclass, not module-level constants — swappable for testing).

Default thresholds: `min_vector=580` (cosine 0.58), `min_lexical=2` (IDF score).

Returns `FloorResult` with `survivors`, `filtered_count`, `filtered_score_ranges`.

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat: add relevance floor pre-filter module"
```

---

### Task 3: Suppression rules module

**Files:**
- Create: `semantic/agent_conversation_memory_routing_suppression.py`
- Test: `tests/test_routing_unified_suppression.py`

- [ ] **Step 1: Read existing suppression implementations**

Read the existing check functions to understand exact field access patterns:
- `_source_hit_matches_current_query_text` in `routing_scoring.py:918-935`
- `_is_low_value_meta_text` in `semantic/agent_conversation_memory_threads.py`
- `_summary_low_value_reason` in `routing_scoring.py:1006-1079`

- [ ] **Step 2: Write failing test**

Test all three rules. Test priority (echo beats meta-text). Test intent gating (weak summary skipped for work_resumption). Use strings known to match the existing `_is_low_value_meta_text` check. Test that suppressed candidates get both a boolean flag AND a score penalty.

```python
def test_suppressed_gets_flag_and_penalty():
    """Suppressed candidates get boolean flag AND modest score penalty."""
    candidate = _make_candidate(is_source_hit=True, excerpt="what is the status",
                                same_thread=True, role="user")
    candidate["base_routing_score"] = 400
    suppressed, reason = apply_suppression(candidate, query_text="what is the status",
                                           query_thread_ref="t1", intent="recall")
    assert suppressed is True
    assert candidate["suppressed"] is True
    assert candidate["base_routing_score"] < 400  # penalty applied
```

- [ ] **Step 3: Implement suppression module**

Composable rules list. Each rule has: `name`, `reason_code`, `intents` (None = all), and a check function. Rules evaluated in priority order, first match wins.

**Key difference from original plan:** `apply_suppression` applies BOTH:
- A boolean `suppressed = True` flag
- A modest score penalty `SUPPRESSION_SCORE_PENALTY = -50` to `base_routing_score`

The penalty is defense-in-depth: if any downstream path sorts by score without checking the flag, suppressed candidates still rank lower. The penalty is smaller than the old -260 (which was calibrated to bury candidates), keeping score relationships more interpretable.

- [ ] **Step 4: Run tests, commit**

```bash
git commit -m "feat: add composable suppression rules module"
```

---

### Task 4: Injection check module

**Files:**
- Create: `semantic/agent_conversation_memory_routing_injection.py`
- Test: `tests/test_routing_injection_check.py`

- [ ] **Step 1: Write failing test**

Test set-level gate and per-candidate eligibility. Key scenarios: weather query (high vector, zero lexical → blocked), strong lexical passes, empty candidates blocks. Use `InjectionThresholds` frozen dataclass for all thresholds (swappable for testing).

- [ ] **Step 2: Implement**

`InjectionThresholds` dataclass with all thresholds. `should_allow_injection(candidates, thresholds)` for set-level gate. `candidate_injection_eligible(candidate, thresholds)` for per-candidate check.

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat: add simplified injection check module"
```

---

### Task 5: Pre-computation annotations for multi-candidate logic

Several current shaping stages compute things across all candidates that a per-candidate scoring function can't access. Extract these as annotation functions that run once over all candidates before scoring.

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_scoring.py`
- Test: `tests/test_routing_annotations.py`

- [ ] **Step 1: Write failing tests**

```python
def test_freshness_ranks_per_type():
    """Assigns rank 1 to freshest candidate within each type."""
    candidates = [
        {"layer": "decision", "freshness_timestamp_value": 100},
        {"layer": "decision", "freshness_timestamp_value": 300},
        {"layer": "investigation_outcome", "freshness_timestamp_value": 50},
    ]
    annotate_freshness_ranks(candidates)
    assert candidates[0]["freshness_rank_in_type"] == 2  # ts=100, older
    assert candidates[1]["freshness_rank_in_type"] == 1  # ts=300, freshest
    assert candidates[2]["freshness_rank_in_type"] == 1  # only one of its type

def test_structured_support_ratio():
    """Computes whether structured candidates dominate source hits."""
    candidates = [
        {"layer": "decision", "support_grade": "strong"},
        {"layer": "decision", "support_grade": "supported"},
        {"layer": "source_evidence", "support_grade": "weak"},
    ]
    ratio = compute_structured_support_ratio(candidates)
    assert ratio["structured_dominates"] is True

def test_work_resumption_reference_timestamp():
    """Computes the most recent timestamp for freshness comparison."""
    candidates = [
        {"layer": "task_checkpoint", "freshness_timestamp_value": ts(100),
         "same_thread": True, "same_container": True},
        {"layer": "task_checkpoint", "freshness_timestamp_value": ts(300),
         "same_thread": True, "same_container": True},
    ]
    annotate_work_resumption_context(candidates, query_filters=mock_filters)
    # Reference is the freshest (300). Staleness computed relative to it.
    assert candidates[0]["work_resumption_stale"] is True
    assert candidates[1]["work_resumption_stale"] is False
```

- [ ] **Step 2: Implement three annotation functions**

```python
from datetime import datetime
from semantic.agent_conversation_memory_routing_constants import (
    ROUTING_SUPPORT_THRESHOLD,
    WORK_RESUMPTION_FRESHNESS_MARGIN_SECONDS,
)

STRUCTURED_LAYERS = frozenset({
    "decision", "investigation_outcome", "task_checkpoint",
    "pattern_memory", "continuity_memory", "interest", "constraint_memory",
    "thread_summary", "discussion_summary",
})


def annotate_freshness_ranks(scored_candidates: list[dict]) -> None:
    """Assign freshness_rank_in_type (1=freshest) to each candidate."""
    by_type: dict[str, list[dict]] = {}
    for c in scored_candidates:
        by_type.setdefault(c.get("layer", ""), []).append(c)
    for type_candidates in by_type.values():
        sorted_by_time = sorted(
            type_candidates,
            key=lambda c: (
                c["freshness_timestamp_value"].timestamp()
                if isinstance(c.get("freshness_timestamp_value"), datetime)
                else float(c.get("freshness_timestamp_value") or 0)
            ),
            reverse=True,
        )
        for rank, c in enumerate(sorted_by_time, start=1):
            c["freshness_rank_in_type"] = rank


def compute_structured_support_ratio(scored_candidates: list[dict]) -> dict:
    """Compute whether structured candidates dominate source hits.

    Returns {"structured_dominates": bool, "structured_supported_count": int,
             "source_count": int}.
    Used by _fresh_session_component to decide whether to prefer structured
    memory over source hits in fresh sessions.
    """
    structured_supported = 0
    source_count = 0
    supported_threshold = ROUTING_SUPPORT_THRESHOLD["supported"]
    for c in scored_candidates:
        layer = c.get("layer", "")
        if layer in STRUCTURED_LAYERS:
            if c.get("support_score", 0) >= supported_threshold:
                structured_supported += 1
        elif layer == "source_evidence":
            source_count += 1
    return {
        "structured_dominates": structured_supported > 0 and structured_supported >= source_count,
        "structured_supported_count": structured_supported,
        "source_count": source_count,
    }


def annotate_work_resumption_context(
    scored_candidates: list[dict], *, query_filters
) -> None:
    """Annotate checkpoint candidates with staleness relative to the freshest.

    Sets 'work_resumption_stale' (bool) on each task_checkpoint candidate.
    A checkpoint is stale if it's older than FRESHNESS_MARGIN_SECONDS relative
    to the freshest checkpoint in the same locality.
    """
    checkpoints = [c for c in scored_candidates if c.get("layer") == "task_checkpoint"]
    if not checkpoints:
        return
    # Find reference timestamp (freshest checkpoint in same locality)
    local_checkpoints = [c for c in checkpoints if c.get("same_container", False)]
    if not local_checkpoints:
        local_checkpoints = checkpoints
    def _ts(c):
        v = c.get("freshness_timestamp_value")
        if isinstance(v, datetime):
            return v.timestamp()
        return float(v or 0)
    reference_ts = max(_ts(c) for c in local_checkpoints)
    margin = WORK_RESUMPTION_FRESHNESS_MARGIN_SECONDS
    for c in checkpoints:
        c["work_resumption_stale"] = (reference_ts - _ts(c)) > margin
```

These are pre-computation steps. They add annotation fields to the candidate dict. The per-candidate scoring formula reads these annotations:
- `freshness_rank_in_type` → read by `_freshness_component`
- `structured_dominates` (from ratio dict) → read by `_fresh_session_component`
- `work_resumption_stale` → read by `_usefulness_bonus`

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat: add pre-computation annotations for multi-candidate scoring"
```

---

### Task 6: Baseline capture

- [ ] **Step 1: Run existing test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 2: Run routing benchmark, save output**

Run: `python -m pytest tests/test_memory_routing_benchmark.py -v --tb=short 2>&1 | tee evals/baselines/benchmark-before.txt`

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: capture baseline for routing simplification"
```

---

## Phase 2: Scoring refactor (behavior change, same intent names)

### Task 7: Wire relevance floor into orchestrator

**Files:**
- Modify: `semantic/agent_conversation_memory_routing.py:109`

- [ ] **Step 1: Add floor call before anchor prefilter**

Import `apply_relevance_floor`. Call before anchor prefilter. Handle empty-after-floor with `decision_reason="no_candidates_above_floor"`. Pass `floor_result.survivors` to anchor prefilter.

- [ ] **Step 2: Run tests, commit**

```bash
git commit -m "feat: wire relevance floor into routing orchestrator"
```

---

### Task 8: Wire unified suppression into orchestrator

Replace three separate suppression stage calls with the unified `apply_suppression` in the scoring loop.

**Files:**
- Modify: `semantic/agent_conversation_memory_routing.py`

- [ ] **Step 1: In the scoring loop, after `_score_routed_candidate`, call `apply_suppression`**

Set `candidate["suppressed"]` and `candidate["suppression_reason_code"]` from the result. The unified function applies the boolean flag + modest score penalty.

- [ ] **Step 2: Remove the three old suppression calls**

Remove calls to `_apply_current_query_source_suppression`, `_apply_recall_source_noise_suppression`, `_apply_recall_structured_summary_suppression`.

- [ ] **Step 3: Add safety test: suppressed candidate with highest score is never selected**

```python
def test_suppressed_candidate_never_selected():
    """Even if a suppressed candidate has the highest routing_score, it's not selected."""
    # Create candidates where the suppressed one has the best score
    # Run through selection
    # Assert suppressed candidate is not in final results
```

- [ ] **Step 4: Run tests, commit**

```bash
git commit -m "feat: replace 3 suppression stages with unified suppression"
```

---

### Task 9: Atomic scoring formula switch + shaping stage removal

**This is the highest-risk task.** The formula change and shaping removal happen together so old-scale penalties never run against new-scale scores.

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_scoring.py:567-623` (`_score_routed_candidate`)
- Modify: `semantic/agent_conversation_memory_routing.py` (remove shaping stage calls, add annotation calls)

- [ ] **Step 1: In the orchestrator, add pre-computation annotation calls**

After scoring all candidates but before focus selection, add:

```python
annotate_freshness_ranks(scored_candidates)
annotate_work_resumption_context(scored_candidates, query_filters=query_filters)
structured_support = compute_structured_support_ratio(scored_candidates)
```

Then pass `structured_support["structured_dominates"]` and `runtime_context` into a second scoring pass that adds the components that need cross-candidate data:

```python
for c in scored_candidates:
    # Add components that need cross-candidate annotations
    c["base_routing_score"] += (
        _freshness_component(c.get("freshness_rank_in_type"), intent)
        + _usefulness_bonus(c["item"], intent, c.get("work_resumption_stale"))
        + _fresh_session_component(runtime_context, c["layer"],
                                   structured_support["structured_dominates"])
    )
    c["routing_score"] = c["base_routing_score"]  # will be adjusted by focus boost later
```

**Why two passes:** `_score_routed_candidate` runs per-candidate during initial scoring. But freshness rank, work resumption staleness, and structured dominance are cross-candidate annotations that must be computed first. The initial scoring sets the base (layer weight + quality + specificity + anchor + locality + evidence richness). The second pass adds the components that depend on annotations.

- [ ] **Step 2: Modify `_score_routed_candidate` to use new formula**

Replace the `base_routing_score` computation:

```python
# OLD:
base_routing_score = layer_weight + retrieval_score * 10 + specificity_bonus + evidence_shape_score + higher_level_adj + locality_adj

# NEW:
base_routing_score = (
    layer_weight
    + int(quality_score * QUALITY_WEIGHT)
    + specificity_bonus
    + _anchor_component(anchor_prefilter_status)
    + _freshness_component(freshness_rank_in_type, intent)
    + _locality_component(same_thread, same_container, item_type, intent)
    + _evidence_richness(item)
    + _usefulness_bonus(item, intent, work_resumption_stale)
    + _fresh_session_component(runtime_context, layer, structured_dominates)
)
```

Add these component functions to `routing_scoring.py`:

```python
# --- Scoring component functions (pure, stateless) ---

# Carry forward from ANCHOR_SECONDARY_TIER_PENALTY
SECONDARY_TIERS = frozenset({
    "secondary_tier", "insufficient_retained", "legacy_fallback_retained",
    "insufficient_retained_demoted",
})

def _anchor_component(anchor_prefilter_status: str | None) -> int:
    """Aligned=0, secondary=-120. Carry forward from _apply_anchor_tier_penalty."""
    if anchor_prefilter_status in SECONDARY_TIERS:
        return -ANCHOR_SECONDARY_TIER_PENALTY  # -120
    return 0


# Carry forward from RECALL_MODE_FRESHNESS_BONUS and _apply_same_kind_freshness_shaping
FRESHNESS_BONUS_BY_INTENT: dict[str, int] = {
    "recall": 24,                # was: broad_recall=24, answer_continuity=0 → use broad value
    "structured_recall": 42,     # was: investigative_conclusion=42, precise_fact=24 → use higher
    "work_resumption": 18,       # was: WORK_RESUMPTION_FRESH_STATE_BONUS
    "evidence_trace": 0,
    # Legacy names for Phase 2 (before Phase 3 rename):
    "broad_recall": 24,
    "answer_continuity": 0,
    "precise_fact": 24,
    "investigative_conclusion": 42,
}
FRESHNESS_DECAY_PER_RANK = 12    # carry forward
FRESHNESS_MAX_PENALTY = 30       # carry forward

def _freshness_component(freshness_rank: int | None, intent: str) -> int:
    """Bonus for freshest candidate in type, penalty for stale ones."""
    bonus = FRESHNESS_BONUS_BY_INTENT.get(intent, 0)
    if bonus == 0 or freshness_rank is None:
        return 0
    if freshness_rank == 1:
        return bonus
    if freshness_rank == 2:
        return 0
    return -min(FRESHNESS_DECAY_PER_RANK * (freshness_rank - 2), FRESHNESS_MAX_PENALTY)


def _locality_component(same_thread: bool, same_container: bool,
                        item_type: str, intent: str) -> int:
    """Same-thread bonus for continuity, cross-container penalty."""
    if item_type == "continuity_memory":
        if same_thread:
            return 60   # carry forward from existing locality_adj
        if not same_container:
            return -60
    return 0


# Carry forward from _candidate_evidence_shape_score
EVIDENCE_RICHNESS_FIELDS = (
    "conclusion_text", "rationale", "decision_text", "investigation_summary",
    "blocker", "next_step", "progress_update", "key_finding",
)

def _evidence_richness(item) -> int:
    """Score based on payload field completeness. Carry forward from evidence_shape_score."""
    payload = getattr(item, "payload", None) or {}
    count = sum(1 for f in EVIDENCE_RICHNESS_FIELDS if payload.get(f))
    evidence = getattr(item, "evidence", []) or []
    if len(evidence) > 1:
        count += 1
    return min(count * 8, 64)


def _usefulness_bonus(item, intent: str, work_resumption_stale: bool | None) -> int:
    """Work resumption usefulness. Returns 0 for all other intents.

    Carry forward from _work_resumption_usefulness_score + stale penalty.
    """
    if intent not in ("work_resumption",):
        return 0
    from semantic.agent_conversation_memory_routing_signals import (
        _work_resumption_signal_types,
        _work_resumption_usefulness_score,
    )
    signal_types = _work_resumption_signal_types(item)
    usefulness = _work_resumption_usefulness_score(signal_types)
    # Stale penalty: carry forward from WORK_RESUMPTION_STALE_STATE_PENALTY
    if work_resumption_stale:
        usefulness -= 55  # WORK_RESUMPTION_STALE_STATE_PENALTY
    return usefulness


# Fresh-session preference: carry forward from _apply_fresh_thread_structured_recall_preference
FRESH_SESSION_SOURCE_PENALTY = -120
FRESH_SESSION_STRUCTURED_BONUS = 26

def _fresh_session_component(
    runtime_context, layer: str, structured_dominates: bool,
) -> int:
    """Prefer structured memory over source hits in fresh sessions.

    Fires when: turn_kind is new_thread/new_session AND
    session_has_sufficient_local_context is False AND
    structured candidates dominate source hits.

    Replaces _apply_fresh_thread_structured_recall_preference.
    """
    if runtime_context is None:
        return 0
    turn_kind = getattr(runtime_context, "turn_kind", None)
    if turn_kind not in ("new_thread", "new_session"):
        return 0
    if getattr(runtime_context, "session_has_sufficient_local_context", False):
        return 0
    if not structured_dominates:
        return 0
    if layer == "source_evidence":
        return FRESH_SESSION_SOURCE_PENALTY
    if layer in STRUCTURED_LAYERS:
        return FRESH_SESSION_STRUCTURED_BONUS
    return 0
```

**Calibration note:** The component values above carry forward from the current system's constants. Run benchmark comparison (Step 6) to verify the combined effect produces similar score distributions. If a specific component causes regressions, adjust its value — the advantage of the single-pass formula is that each component is independently tuneable without affecting others.

- [ ] **Step 3: Remove old shaping stage calls from orchestrator**

Remove calls to:
- `_apply_anchor_tier_penalty`
- `_apply_same_kind_freshness_shaping`
- `_apply_fresh_thread_structured_recall_preference`
- `_apply_work_resumption_packaging`

- [ ] **Step 4: Ensure the dict still has all required fields**

The removed shaping stages also SET some fields. These must still be set. Checklist:

| Field | Previously set by | Now set by |
|---|---|---|
| `work_signal_types` | `_apply_work_resumption_packaging` | `_score_routed_candidate` (call `_work_resumption_signal_types` unconditionally, default `()`) |
| `work_usefulness_score` | `_apply_work_resumption_packaging` | `_score_routed_candidate` (call `_work_resumption_usefulness_score`, default `0`) |
| `packaging_adjustment` | `_apply_work_resumption_packaging` | `_score_routed_candidate` (set to `0`; concept absorbed into `_usefulness_bonus`) |
| `packaging_reasons` | Multiple shaping stages | `_score_routed_candidate` (set to `[]`; suppression reasons go in `suppression_reason_code`) |
| `freshness_timestamp` | `_apply_work_resumption_packaging` | `_score_routed_candidate` (ISO string from `freshness_timestamp_value`) |
| `anchor_tier_penalty` | `_apply_anchor_tier_penalty` | `_score_routed_candidate` (compute from `_anchor_component`) |
| `freshness_rank_in_type` | (new) | `annotate_freshness_ranks` pre-computation |
| `work_resumption_stale` | (new) | `annotate_work_resumption_context` pre-computation |
| `suppressed` | (new) | `apply_suppression` in Task 8 |
| `quality_score` | (new, Task 1) | `_score_routed_candidate` (already added in Task 1) |

Verify each field exists by adding a test that creates a scored candidate and asserts all expected keys are present.

- [ ] **Step 5: Run tests — expect some assertion value changes**

Scores will change. Run full suite. For each failure, verify the new score is reasonable (not a bug), then update the assertion.

- [ ] **Step 6: Run routing benchmark, compare against baseline**

Run: `python -m pytest tests/test_memory_routing_benchmark.py -v --tb=short`
Compare against `evals/baselines/benchmark-before.txt`. Injection contract success must not decrease.

- [ ] **Step 7: Commit**

```bash
git commit -m "feat: atomic switch to single-pass scoring, remove 5 shaping stages"
```

---

### Task 10: Update trace for Phase 2 changes

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_trace.py`
- Modify: `semantic/agent_conversation_memory_routing.py` (trace assembly)

- [ ] **Step 1: Update trace**

- Remove `kind_prefilter` block (kind prefilter removed)
- Remove `family_inference` block — `_infer_query_intent` is no longer called in the hot path; its trace contribution (`selected_family`, `family_scores`, `candidate_signals`) was post-hoc and is no longer produced. Replace with a simpler `scoring_components` block that logs the new formula's component values for the top 3 candidates (for debuggability).
- Add `relevance_floor` block: `filtered_count`, `filtered_score_ranges`
- Add `quality_score`, `freshness_rank_in_type`, `suppressed` to per-candidate trace entries
- Add `structured_support` block: `structured_dominates`, `structured_supported_count`, `source_count`
- Remove `_build_kind_prefilter_trace_entry` (dead code)
- Remove `_build_anchor_prefilter_trace_entry` (already dead code per investigation)

- [ ] **Step 2: Run tests, commit**

```bash
git commit -m "feat: update routing trace for simplified pipeline"
```

---

### Task 11: Phase 2 validation checkpoint

**Do not proceed to Phase 3 until this passes.**

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 2: Run routing benchmark, compare against baseline**

Key metrics:
- Injection contract success: same or better
- No new regressions

- [ ] **Step 3: If regressions exist, fix them before proceeding**

Adjust scoring component values (freshness bonus, anchor penalty, quality weight) until benchmark results are acceptable. Each adjustment is a separate commit.

---

## Phase 3: Intent family merge (mechanical rename)

Only start this phase after Phase 2 validation checkpoint passes. This is a cross-cutting rename with no logic changes — if tests fail, the cause is always a missed rename, never a scoring bug.

### Task 12: Add V2 intent constants alongside V1

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_constants.py`

- [ ] **Step 1: Add V2 dicts alongside V1**

`ROUTING_LAYER_WEIGHTS_V2` (4 families), `ROUTING_PREFERRED_LAYERS_V2`, `ROUTING_SAFE_FALLBACK_LAYERS_V2`. Carry forward exact values for `work_resumption` and `evidence_trace`. Merge `broad_recall` + `answer_continuity` into `recall` (average weights). Merge `precise_fact` + `investigative_conclusion` into `structured_recall`.

- [ ] **Step 2: Run tests (no behavior change), commit**

```bash
git commit -m "feat: add V2 intent family constants (4 families)"
```

---

### Task 13a: Rename constants and config dicts

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_constants.py`

- [ ] **Step 1: Switch all config dicts to V2**

Replace `ROUTING_LAYER_WEIGHTS` with V2 version. Update `LANE_INTENT_MAPPING`, `QUERY_POLICY_FAMILY_ALLOWED_INTENTS`, `LATEST_STATUS_COLLAPSED_INTENTS`, `ROUTING_SAFE_FALLBACK_LAYERS`.

- [ ] **Step 2: Run tests — expect many failures. Commit.**

```bash
git commit -m "refactor: switch routing constants to 4-family intents"
```

---

### Task 13b: Update routing logic (if/in guards)

**Files:**
- Modify: `semantic/agent_conversation_memory_routing.py` — `_mode_intent_map`, intent assignments
- Modify: `semantic/agent_conversation_memory_routing_scoring.py` — `_specificity_bonus`, `_select_routing_focus`, freshness component
- Modify: `semantic/agent_conversation_memory_routing_selection.py` — selection path guards
- Modify: `semantic/agent_conversation_memory_routing_policy.py` — lane mappings, policy restriction
- Modify: `semantic/agent_conversation_memory_routing_suppression.py` — `SUPPRESSION_RECALL_INTENTS` (remove legacy names)

- [ ] **Step 1: Systematic rename**

In each file, replace:
- `"broad_recall"` → `"recall"` (where it's a standalone intent)
- `"answer_continuity"` → `"recall"`
- `"precise_fact"` → `"structured_recall"`
- `"investigative_conclusion"` → `"structured_recall"`
- `{"broad_recall", "answer_continuity"}` → `{"recall"}`
- `{"precise_fact", "investigative_conclusion"}` → `{"structured_recall"}`

- [ ] **Step 2: Run tests — fewer failures now. Commit.**

```bash
git commit -m "refactor: update routing logic for 4-family intents"
```

---

### Task 13c: Update trace labels

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_trace.py` — `_query_family_label`, `_routing_reason`

- [ ] **Step 1: Update `_query_family_label` mapping for new names**
- [ ] **Step 2: Update `_routing_reason` branches for new names**
- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "refactor: update trace labels for 4-family intents"
```

---

### Task 13d: Update test assertions

**Files:** All test files with intent name assertions (~15 files, ~200 assertions).

- [ ] **Step 1: Mechanical rename in test assertions**

Replace old intent name strings with new ones in all `assert` statements. Use the migration map from the investigation.

- [ ] **Step 2: Run full test suite — should pass now**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 3: Commit**

```bash
git commit -m "test: update assertions for 4-family intent names"
```

---

### Task 13e: Update eval scenarios and eval code

**Files:**
- Modify: `evals/continuity_common.py`
- Modify: `evals/memory_routing_benchmark.py`
- Modify: `evals/work_resumption_benchmark.py`
- Modify: `evals/memory_routing/scenarios.json`, `scenarios_longmemeval.json`
- Modify: `evals/work_resumption/scenarios.json`, `scenarios_noisy.json`, `scenarios_paraphrased.json`
- Modify: `evals/integration_readiness/scenarios.json`

- [ ] **Step 1: Update eval code** (vocabulary, mapping functions, intent guards)
- [ ] **Step 2: Update scenario JSON `expected_intent` values**
- [ ] **Step 3: Run benchmarks, commit**

```bash
git commit -m "refactor: update eval scenarios and code for 4-family intents"
```

---

### Task 14: Remove V1 constants

- [ ] **Step 1: Delete old 6-family dicts, rename V2 → primary names**
- [ ] **Step 2: Remove `_infer_query_intent` and `ROUTING_FAMILY_INFERENCE_PRIORITY` (post-hoc inference no longer needed)**
- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "chore: remove V1 intent constants and post-hoc intent inference"
```

---

## Phase 4: Injection replacement + cleanup

### Task 15: Replace QPP with simplified injection check

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_selection.py:202-341`
- Modify: `semantic/agent_conversation_memory_routing.py`

- [ ] **Step 1: Replace `compute_injection_signals` + `justify_injection_rules` with `should_allow_injection`**

- [ ] **Step 2: Add `candidate_injection_eligible` to `_candidate_is_injection_eligible`**

- [ ] **Step 3: Update `injection_decision` trace block**

Replace `justification_reason`, `justification_score`, `justification_signals` with: `injection_method: "simplified"`, `best_lexical`, `best_vector`, `gate_passed`.

- [ ] **Step 4: Run tests — rewrite QPP-specific tests for new check**

The off-topic scenarios (weather query, zero overlap) must still PASS. Rewrite `tests/test_routing_justification.py` to test `should_allow_injection` and `candidate_injection_eligible`.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: replace QPP 4-gate justification with simplified injection check"
```

---

### Task 16: Remove evidence trace resolver LLM call

**Files:**
- Modify: `semantic/agent_conversation_memory_routing.py`
- Modify: `semantic/agent_conversation_memory_routing_signals.py`
- Modify: `semantic/agent_conversation_memory_routing_policy.py`

- [ ] **Step 1: Replace resolver call with deterministic source ratio check**

Use `quality_score`-weighted source hit mass vs structured memory mass. If source dominates (ratio >= 0.5), set `evidence_request=True`.

- [ ] **Step 2: Remove `resolver_config` plumbing** from orchestrator, core/query.py, api/routes.py

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat: replace evidence trace resolver with deterministic source ratio"
```

---

### Task 17: Remove dead code

- [ ] **Step 1: Grep for all removed function names, verify no imports**

Dead functions: `_apply_anchor_tier_penalty`, `_apply_current_query_source_suppression`, `_apply_same_kind_freshness_shaping`, `_apply_fresh_thread_structured_recall_preference`, `_apply_recall_source_noise_suppression`, `_apply_recall_structured_summary_suppression`, `_apply_work_resumption_packaging`, `compute_injection_signals`, `justify_injection_rules`, `justify_injection_linear`, `_invoke_resolver_for_ambiguity`, `_check_evidence_trace_override`.

- [ ] **Step 2: Remove dead functions and their tests**
- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "chore: remove dead routing shaping stages, QPP, and resolver"
```

---

### Task 18: Add ScoredCandidate TypedDict

Now that the dict shape is stable, formalize it.

**Files:**
- Create: `semantic/agent_conversation_memory_routing_types.py`

- [ ] **Step 1: Define `ScoredCandidate` TypedDict matching the actual post-migration dict shape**

Include all fields that exist after Phase 2-4 changes. Exclude removed fields (`kind_prefilter_status`, etc.). Include new fields (`quality_score`, `freshness_rank_in_type`, `suppressed`).

- [ ] **Step 2: Add `InjectionThresholds` and `FloorThresholds` dataclasses** (move from inline definitions in floor/injection modules to shared types)

- [ ] **Step 3: Type-annotate key functions** with `ScoredCandidate` return/parameter types where it adds clarity (scoring, selection, trace builders)

- [ ] **Step 4: Run tests, commit**

```bash
git commit -m "feat: add ScoredCandidate TypedDict and shared routing types"
```

---

### Task 19: Final validation and docs

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q`

- [ ] **Step 2: Run routing benchmark, compare against Task 6 baseline**

- [ ] **Step 3: Update `docs/context/state.md`**

Note: 17 stages → 10, 6 intent families → 4, QPP replaced, resolver removed.

- [ ] **Step 4: Update `docs/context/architecture.md`**

Update routing description for simplified pipeline.

- [ ] **Step 5: Commit**

```bash
git commit -m "docs: update state and architecture for routing simplification"
```
