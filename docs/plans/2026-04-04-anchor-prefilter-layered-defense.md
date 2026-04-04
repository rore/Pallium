# Anchor Prefilter Layered Defense Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the anchor prefilter's single binary gate with a three-layer defense (aligned primary / secondary tier / never-retained) so extraction errors no longer cause hard-miss results.

**Architecture:** Three sequential, independently committable changes — (1) demote conflicting to insufficient so they survive the no-aligned fallback; (2) apply a calibrated score penalty to all secondary-tier candidates so aligned always rank higher; (3) retain the full secondary pool alongside aligned candidates so correctly-relevant but under-extracted memories fill remaining result slots. A fourth change (remove the dead `content_overlap_tokens` field) is bundled with change 2 as it touches the same files.

**Tech Stack:** Python 3.12, pytest (`python -m pytest tests/ -x -q`). All changes are within `semantic/` and `tests/`.

---

## File Map

| File | Change |
|---|---|
| `semantic/agent_conversation_memory_routing.py` | Change 1 (conflicting demotion) + Change 3 (secondary tier retention) |
| `semantic/agent_conversation_memory_routing_constants.py` | Change 2 (add `ANCHOR_SECONDARY_TIER_PENALTY = 120`) |
| `semantic/agent_conversation_memory_routing_scoring.py` | Change 2 (add `_apply_anchor_tier_penalty`) + Change 4 (remove `content_overlap_tokens`) |
| `semantic/agent_conversation_memory_routing_trace.py` | Change 2 (add `anchor_tier_penalty` to trace) + Change 4 (remove `content_overlap_tokens` parameter and block) |
| `semantic/agent_conversation_memory_routing_selection.py` | Change 4 (remove two dead-code reads of `content_overlap_tokens`) |
| `tests/test_agent_conversation_memory_routing_recall.py` | Change 1 (new test + update existing), Change 3 (update existing) |
| `tests/test_agent_conversation_memory_routing_resumption.py` | Change 3 (update existing) |

---

## Task 1 — Change 1: Demote `anchored_conflicting` → insufficient

**Files:**
- Modify: `semantic/agent_conversation_memory_routing.py:539-567`
- Modify: `tests/test_agent_conversation_memory_routing_recall.py:660-733`

**Context:** `_anchor_prefilter_candidates` (routing.py:510) classifies each memory into four buckets. Currently, `conflicting` candidates are hard-excluded and their count/entries written to `excluded_by_anchor_count`/`excluded_candidates`. Change 1 routes them into the `insufficient` bucket instead so they survive the fallback path when no aligned candidates exist. The `insufficient` bucket is still dropped when aligned exist — so existing result behavior is unchanged — but the trace fields change.

`ROUTING_FOCUS_BOOST = 120` (routing_constants.py:189).

---

- [ ] **Step 1.1: Write a new failing test for the no-aligned fallback path**

Add at the end of `tests/test_agent_conversation_memory_routing_recall.py`:

```python
def test_anchor_prefilter_retains_conflicting_in_no_aligned_fallback() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='slack:channel:CLOCAL001')
    conflicting_anchor = MemorySubjectAnchor(kind='workstream', value='payment processing')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-conflicting-only',
                type='decision',
                payload={
                    'decision': 'The payment processing queue should drain before the inventory batch runs.',
                    'rationale': 'Overlapping writes have caused duplicate entries in prior runs.',
                },
                score=14,
                evidence=[],
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:payments',
                envelope=_memory_envelope('finding', subjects=[conflicting_anchor]),
            ),
        ],
        trace=QueryTrace(
            query_text='What decisions were made about inventory batch digest?',
            query_tokens=('what', 'decisions', 'were', 'made', 'about', 'inventory', 'batch', 'digest'),
            limit=6,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What decisions were made about inventory batch digest?',
        requested_limit=6,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    anchor_prefilter = outcome.trace.routing['anchor_prefilter']
    # After Change 1: conflicting memory is demoted to insufficient and retained
    # (no aligned candidates exist, so insufficient fallback fires)
    assert any(r.memory_object_id == 'decision-conflicting-only' for r in outcome.results if r.result_kind == 'memory_hit')
    assert anchor_prefilter['query_anchor_status'] == 'clear'
    assert anchor_prefilter['excluded_by_anchor_count'] == 0
    assert anchor_prefilter['insufficient_candidate_count'] == 1
    # Per-candidate trace should carry the demoted status
    routing_candidates = outcome.trace.routing.get('routing_candidates', [])
    candidate_entry = next(
        (e for e in routing_candidates if e.get('result_id') == 'memory_object:decision-conflicting-only'),
        None,
    )
    assert candidate_entry is not None
    assert candidate_entry['anchor_prefilter_status'] == 'insufficient_retained_demoted'
```

- [ ] **Step 1.2: Run the new test to confirm it fails**

Run: `python -m pytest tests/test_agent_conversation_memory_routing_recall.py::test_anchor_prefilter_retains_conflicting_in_no_aligned_fallback -x -q`

Expected: FAIL — the memory is absent from results and `excluded_by_anchor_count` is 1 (current behavior keeps conflicting hard-excluded).

- [ ] **Step 1.3: Update the existing test's trace-level assertions**

In `test_workstream_anchor_prefilter_excludes_same_surface_off_topic_memory` (recall.py:718-732), replace the three failing anchor_prefilter assertions:

```python
# Before (lines 726-732):
    assert anchor_prefilter['fallback_mode'] == 'aligned_only'
    assert anchor_prefilter['excluded_by_anchor_count'] == 1
    assert any(
        item['result_id'] == 'memory_object:decision-wallet-off-topic'
        and item['reason_code'] == 'anchor_conflict'
        for item in anchor_prefilter.get('excluded_candidates', [])
    )

# After:
    assert anchor_prefilter['fallback_mode'] == 'aligned_only'
    assert anchor_prefilter['excluded_by_anchor_count'] == 0
    assert anchor_prefilter['insufficient_candidate_count'] == 1
    assert not anchor_prefilter.get('excluded_candidates')
```

The result assertions above those lines (`outcome.results[0].memory_object_id == 'decision-inventory-aligned'` and `all(...  != 'decision-wallet-off-topic')`) are unchanged — the wallet memory is still excluded from results because insufficient is still dropped when aligned exist.

- [ ] **Step 1.4: Implement Change 1 in `_anchor_prefilter_candidates`**

In `semantic/agent_conversation_memory_routing.py`, locate the loop body at line 549. Replace the `anchored_conflicting` branch so it routes into `insufficient` with a distinct status:

```python
# Before (lines 549-550):
        elif anchor_state == "anchored_conflicting":
            conflicting.append(item)

# After:
        elif anchor_state == "anchored_conflicting":
            insufficient.append(item)
            candidate_states[result_id] = {
                "anchor_prefilter_status": "insufficient_retained_demoted",
                "anchor_prefilter_reason_code": "anchor_conflict_demoted",
                "anchor_prefilter_reason": "Candidate conflicted with the selected query anchor and was demoted to the insufficient fallback tier.",
            }
```

Then update the summary block (lines 555-567) — `conflicting` is now always empty so remove its count and trace entries:

```python
# Before (lines 555-567):
    summary["aligned_candidate_count"] = len(aligned)
    summary["insufficient_candidate_count"] = len(insufficient)
    summary["excluded_by_anchor_count"] = len(conflicting)
    if conflicting:
        summary["excluded_candidates"] = [
            _build_anchor_prefilter_trace_entry(
                item,
                status="conflicting_excluded",
                reason_code="anchor_conflict",
                reason="Candidate conflicted with the selected query anchor.",
            )
            for item in conflicting[:5]
        ]

# After:
    summary["aligned_candidate_count"] = len(aligned)
    summary["insufficient_candidate_count"] = len(insufficient)
    summary["excluded_by_anchor_count"] = 0
```

Also remove the `conflicting: list[QueryResultItem] = []` variable declaration at line 537 since the list is no longer used.

- [ ] **Step 1.5: Run the full test suite**

Run: `python -m pytest tests/ -x -q`

Expected: all 758 tests pass.

- [ ] **Step 1.6: Commit**

```bash
git add semantic/agent_conversation_memory_routing.py tests/test_agent_conversation_memory_routing_recall.py
git commit -m "$(cat <<'EOF'
feat: demote anchored_conflicting to insufficient in anchor prefilter

Conflicting candidates now enter the insufficient fallback bucket instead
of being hard-excluded. When no aligned candidates exist, they survive the
fallback cascade. When aligned candidates exist, they are still dropped
(the existing insufficient-drops-when-aligned rule is unchanged). Change
1 of 4 in the layered-defense plan.
EOF
)"
```

---

## Task 2 — Changes 2 + 4: Tier penalty + remove `content_overlap_tokens`

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_constants.py` (add constant)
- Modify: `semantic/agent_conversation_memory_routing_scoring.py` (add `_apply_anchor_tier_penalty`, remove `content_overlap_tokens` field)
- Modify: `semantic/agent_conversation_memory_routing.py` (import + call site, remove `content_overlap_tokens` arg)
- Modify: `semantic/agent_conversation_memory_routing_trace.py` (add `anchor_tier_penalty` to trace, remove `content_overlap_tokens` parameter and block)
- Modify: `semantic/agent_conversation_memory_routing_selection.py` (remove two dead-code reads)

**Context:** `_score_routed_candidate` (scoring.py:566) returns a candidate dict with `base_routing_score` and `routing_score` (initially equal). Various `_apply_*` functions modify `base_routing_score` in place. At routing.py:347, `routing_score = base_routing_score + _routing_focus_adjustment(...)` where focus_adjustment is at most `ROUTING_FOCUS_BOOST = 120`. After scoring, `anchor_prefilter_states` are merged into the candidate dict at routing.py:304. So the penalty function must run *after* line 304. `ROUTING_FOCUS_BOOST = 120` — the penalty must be ≥ 120 to guarantee aligned outranks secondary even when secondary has max focus boost.

`content_overlap_tokens` was initialized to `[]` in `_score_routed_candidate` and never populated anywhere. It is referenced in `_routing_reason` (trace.py:95, used at line 100), `_build_routing_trace_entry` (trace.py:325-327), and two dead-code paths in `_source_candidate_has_quote_grade_support` and a same-thread source selection check in `agent_conversation_memory_routing_selection.py`.

---

- [ ] **Step 2.1: Write failing unit tests for `_apply_anchor_tier_penalty`**

Add a new test file `tests/test_anchor_tier_penalty.py`:

```python
from __future__ import annotations

import pytest
from semantic.agent_conversation_memory_routing_scoring import (
    _apply_anchor_tier_penalty,
)
from semantic.agent_conversation_memory_routing_constants import (
    ANCHOR_SECONDARY_TIER_PENALTY,
    ROUTING_FOCUS_BOOST,
)


def _make_candidate(status: str | None, base: int) -> dict:
    c: dict = {"base_routing_score": base}
    if status is not None:
        c["anchor_prefilter_status"] = status
    return c


def test_penalty_invariant_anchor_secondary_penalty_ge_focus_boost() -> None:
    assert ANCHOR_SECONDARY_TIER_PENALTY >= ROUTING_FOCUS_BOOST


def test_aligned_candidate_receives_zero_penalty() -> None:
    c = _make_candidate("aligned", 500)
    _apply_anchor_tier_penalty([c])
    assert c["anchor_tier_penalty"] == 0
    assert c["base_routing_score"] == 500


def test_no_status_candidate_receives_zero_penalty() -> None:
    c = _make_candidate(None, 400)
    _apply_anchor_tier_penalty([c])
    assert c["anchor_tier_penalty"] == 0
    assert c["base_routing_score"] == 400


def test_insufficient_retained_receives_full_penalty() -> None:
    c = _make_candidate("insufficient_retained", 600)
    _apply_anchor_tier_penalty([c])
    assert c["anchor_tier_penalty"] == ANCHOR_SECONDARY_TIER_PENALTY
    assert c["base_routing_score"] == 600 - ANCHOR_SECONDARY_TIER_PENALTY


def test_legacy_fallback_retained_receives_full_penalty() -> None:
    c = _make_candidate("legacy_fallback_retained", 550)
    _apply_anchor_tier_penalty([c])
    assert c["anchor_tier_penalty"] == ANCHOR_SECONDARY_TIER_PENALTY
    assert c["base_routing_score"] == 550 - ANCHOR_SECONDARY_TIER_PENALTY


def test_insufficient_retained_demoted_receives_full_penalty() -> None:
    c = _make_candidate("insufficient_retained_demoted", 620)
    _apply_anchor_tier_penalty([c])
    assert c["anchor_tier_penalty"] == ANCHOR_SECONDARY_TIER_PENALTY
    assert c["base_routing_score"] == 620 - ANCHOR_SECONDARY_TIER_PENALTY


def test_secondary_tier_receives_full_penalty() -> None:
    c = _make_candidate("secondary_tier", 580)
    _apply_anchor_tier_penalty([c])
    assert c["anchor_tier_penalty"] == ANCHOR_SECONDARY_TIER_PENALTY
    assert c["base_routing_score"] == 580 - ANCHOR_SECONDARY_TIER_PENALTY


def test_mixed_candidates_only_secondary_penalized() -> None:
    aligned = _make_candidate("aligned", 500)
    secondary = _make_candidate("insufficient_retained", 600)
    none_status = _make_candidate(None, 400)
    _apply_anchor_tier_penalty([aligned, secondary, none_status])
    assert aligned["base_routing_score"] == 500
    assert secondary["base_routing_score"] == 600 - ANCHOR_SECONDARY_TIER_PENALTY
    assert none_status["base_routing_score"] == 400
```

- [ ] **Step 2.2: Run the new tests to confirm they fail**

Run: `python -m pytest tests/test_anchor_tier_penalty.py -x -q`

Expected: FAIL — `_apply_anchor_tier_penalty` and `ANCHOR_SECONDARY_TIER_PENALTY` do not exist yet.

- [ ] **Step 2.3: Add `ANCHOR_SECONDARY_TIER_PENALTY` to constants**

In `semantic/agent_conversation_memory_routing_constants.py`, add after `ROUTING_FOCUS_BOOST = 120` (line 189):

```python
ANCHOR_SECONDARY_TIER_PENALTY = 120  # must be >= ROUTING_FOCUS_BOOST; ensures aligned always outranks secondary tier even at max focus boost
```

- [ ] **Step 2.4: Add `_apply_anchor_tier_penalty` to scoring module**

In `semantic/agent_conversation_memory_routing_scoring.py`, add the new constant to the imports block at the top (already importing from routing_constants):

```python
# Add to the existing import from routing_constants (around line 14-40):
    ANCHOR_SECONDARY_TIER_PENALTY,
```

Then add the function directly after the closing brace of `_score_routed_candidate` (after line 623):

```python
_ANCHOR_SECONDARY_STATUSES = frozenset({
    "insufficient_retained",
    "legacy_fallback_retained",
    "insufficient_retained_demoted",
    "secondary_tier",
})

def _apply_anchor_tier_penalty(scored_candidates: list[dict[str, object]]) -> None:
    """Deduct ANCHOR_SECONDARY_TIER_PENALTY from base_routing_score for secondary-tier candidates.

    Must be called after anchor_prefilter_states are merged into scored_candidates
    (i.e., after the candidate.update(anchor_prefilter_states...) loop in route_query_results).
    Sets anchor_tier_penalty on every candidate dict (0 for aligned/unclassified, penalty for secondary).
    """
    for candidate in scored_candidates:
        status = str(candidate.get("anchor_prefilter_status") or "")
        penalty = ANCHOR_SECONDARY_TIER_PENALTY if status in _ANCHOR_SECONDARY_STATUSES else 0
        candidate["anchor_tier_penalty"] = penalty
        if penalty:
            candidate["base_routing_score"] = int(candidate["base_routing_score"]) - penalty
```

- [ ] **Step 2.5: Wire `_apply_anchor_tier_penalty` into the routing pipeline**

In `semantic/agent_conversation_memory_routing.py`:

Add `_apply_anchor_tier_penalty` to the import block (around line 55 where scoring functions are imported):

```python
# Add to existing import:
    _apply_anchor_tier_penalty,
```

Then call it immediately after the anchor prefilter states are merged (after line 304):

```python
# After the loop at line 301-304:
        for candidate in scored_candidates:
            result_id = _routing_result_id(candidate["item"])
            candidate.update(kind_prefilter_states.get(result_id, {}))
            candidate.update(anchor_prefilter_states.get(result_id, {}))
        _apply_anchor_tier_penalty(scored_candidates)  # ADD THIS LINE
```

- [ ] **Step 2.6: Add `anchor_tier_penalty` to the routing trace entry**

In `semantic/agent_conversation_memory_routing_trace.py`, in `_build_routing_trace_entry` (line 306), add after the `anchor_prefilter_status` block (after line 337):

```python
# After:
    if candidate.get("anchor_prefilter_status"):
        entry["anchor_prefilter_status"] = candidate["anchor_prefilter_status"]
# Add:
    if "anchor_tier_penalty" in candidate:
        entry["anchor_tier_penalty"] = candidate["anchor_tier_penalty"]
```

- [ ] **Step 2.7: Run the unit tests to confirm they pass**

Run: `python -m pytest tests/test_anchor_tier_penalty.py -x -q`

Expected: all 8 tests PASS.

- [ ] **Step 2.8: Remove `content_overlap_tokens` from `_score_routed_candidate` return dict**

In `semantic/agent_conversation_memory_routing_scoring.py`, in `_score_routed_candidate` return dict (line 610):

```python
# Remove this line:
        "content_overlap_tokens": [],
```

- [ ] **Step 2.9: Remove `content_overlap_tokens` from `_routing_reason` signature and body**

In `semantic/agent_conversation_memory_routing_trace.py`:

Remove `content_overlap_tokens: list[str]` parameter from `_routing_reason` (line 95).

Update the `weak_match_suffix` computation at line 100 — since the list was always empty, `not content_overlap_tokens` was always True, so the condition simplifies:

```python
# Before (line 100):
    weak_match_suffix = " Weak higher-level overlap kept it below better-grounded candidates." if not content_overlap_tokens and layer in ROUTING_HIGHER_LEVEL_TYPES else ""

# After:
    weak_match_suffix = " Weak higher-level overlap kept it below better-grounded candidates." if layer in ROUTING_HIGHER_LEVEL_TYPES else ""
```

- [ ] **Step 2.10: Remove `content_overlap_tokens` arg from the `_routing_reason` call site**

In `semantic/agent_conversation_memory_routing.py` at line 354-361, remove the `content_overlap_tokens=...` argument:

```python
# Before:
        candidate["reason"] = _routing_reason(
            intent=intent,
            layer=str(candidate["layer"]),
            content_overlap_tokens=list(candidate["content_overlap_tokens"]),
            support_grade=str(candidate["support_grade"]),
            routing_focus=routing_focus,
            packaging_reasons=list(candidate["packaging_reasons"]),
        )

# After:
        candidate["reason"] = _routing_reason(
            intent=intent,
            layer=str(candidate["layer"]),
            support_grade=str(candidate["support_grade"]),
            routing_focus=routing_focus,
            packaging_reasons=list(candidate["packaging_reasons"]),
        )
```

- [ ] **Step 2.11: Remove `content_overlap_tokens` block from `_build_routing_trace_entry`**

In `semantic/agent_conversation_memory_routing_trace.py` at lines 325-327:

```python
# Remove these three lines:
    content_overlap_tokens = list(candidate["content_overlap_tokens"])
    if content_overlap_tokens:
        entry["content_overlap_terms"] = content_overlap_tokens
```

- [ ] **Step 2.12: Remove dead-code reads in `agent_conversation_memory_routing_selection.py`**

**Location 1** — in the same-thread source selection function (around line 596): remove the `overlap_tokens` read and the unreachable `if support_grade ... and len(overlap_tokens) >= 2:` block. Since `len(overlap_tokens) >= 2` was always False, the branch body `return True, ""` was never reached. The fallthrough `return False, "weak_same_thread_source"` is unchanged.

```python
# Before (lines 596, 606-608):
    overlap_tokens = list(candidate.get("content_overlap_tokens") or [])
    ...
        if support_grade in {"supported", "strong"} and len(overlap_tokens) >= 2:
            if item.role == "assistant" or intent in {"precise_fact", "evidence_trace", "investigative_conclusion"}:
                return True, ""
        return False, "weak_same_thread_source"

# After (remove lines 596 and 606-608):
    ...
        return False, "weak_same_thread_source"
```

**Location 2** — in `_source_candidate_has_quote_grade_support` (around line 692-704): remove the `overlap_tokens` read and simplify `quoted_evidence`. `bool(proof_overlap)` was always False since the token set was always empty, so `quoted_evidence` was always False.

```python
# Before (lines 692-704):
    overlap_tokens = {str(token) for token in candidate.get("content_overlap_tokens") or []}
    proof_overlap = overlap_tokens.intersection({"exact", "line", "log", "proof", "quote"})
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    excerpt = str(item.excerpt or "")
    excerpt_lower = excerpt.lower()
    if any(hedge in excerpt_lower for hedge in ("probably", "maybe", "somewhere", "did not keep", "don't have", "not sure")):
        return False
    proof_like_excerpt = any(
        cue in excerpt_lower
        for cue in ("investigation found", "exact log line", "smoking gun", "showed", "proved", "backed")
    )
    quoted_evidence = (excerpt.count("'") >= 2 or excerpt.count('"') >= 2) and bool(proof_overlap)
    support_grade = str(candidate.get("support_grade") or "weak")
    return (support_grade in {"supported", "strong"} and proof_like_excerpt) or quoted_evidence

# After:
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    excerpt = str(item.excerpt or "")
    excerpt_lower = excerpt.lower()
    if any(hedge in excerpt_lower for hedge in ("probably", "maybe", "somewhere", "did not keep", "don't have", "not sure")):
        return False
    proof_like_excerpt = any(
        cue in excerpt_lower
        for cue in ("investigation found", "exact log line", "smoking gun", "showed", "proved", "backed")
    )
    support_grade = str(candidate.get("support_grade") or "weak")
    return support_grade in {"supported", "strong"} and proof_like_excerpt
```

- [ ] **Step 2.13: Run the full test suite**

Run: `python -m pytest tests/ -x -q`

Expected: all 758 + 8 new = 766 tests pass.

- [ ] **Step 2.14: Commit**

```bash
git add semantic/agent_conversation_memory_routing_constants.py \
        semantic/agent_conversation_memory_routing_scoring.py \
        semantic/agent_conversation_memory_routing.py \
        semantic/agent_conversation_memory_routing_trace.py \
        semantic/agent_conversation_memory_routing_selection.py \
        tests/test_anchor_tier_penalty.py
git commit -m "$(cat <<'EOF'
feat: add anchor tier penalty and remove dead content_overlap_tokens field

Introduces ANCHOR_SECONDARY_TIER_PENALTY=120 (== ROUTING_FOCUS_BOOST) and
_apply_anchor_tier_penalty, which deducts the penalty from base_routing_score
for insufficient_retained, legacy_fallback_retained, insufficient_retained_demoted,
and secondary_tier candidates. anchor_tier_penalty is exposed in the routing
trace. content_overlap_tokens was always [] and is removed throughout. Changes
2 and 4 of 4 in the layered-defense plan.
EOF
)"
```

---

## Task 3 — Change 3: Retain a secondary tier alongside aligned candidates

**Files:**
- Modify: `semantic/agent_conversation_memory_routing.py:569-602`
- Modify: `tests/test_agent_conversation_memory_routing_recall.py:660-733`
- Modify: `tests/test_agent_conversation_memory_routing_resumption.py:419-496`

**Context:** Currently when aligned candidates exist, `retained_memory_ids` contains only aligned items (`fallback_mode = "aligned_only"`). Change 3 expands `retained_memory_ids` to also include the insufficient and legacy candidates, annotated with `anchor_prefilter_status = "secondary_tier"` so the tier penalty (Task 2) deducts their score. The `_select_final_candidates` call already respects `requested_limit`, so secondary candidates only appear in slots that aligned candidates do not fill.

The two existing tests that assert the off-topic/adjacent memory is absent must be updated: after Change 3, those memories surface as secondary-tier candidates ranked below the aligned winner.

---

- [ ] **Step 3.1: Update `test_workstream_anchor_prefilter_excludes_same_surface_off_topic_memory` to match new behavior**

In `tests/test_agent_conversation_memory_routing_recall.py` at lines 718-732, replace the assertion block.

> **Note:** The "Before" block below reflects the post–Task 1 state (after step 1.3 in Task 1 already changed `excluded_by_anchor_count` to 0 and removed the `excluded_candidates` assertion). The original file before Task 1 had `excluded_by_anchor_count == 1` — that is not the starting state here.

```python
# Before (post–Task 1 state):
    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    anchor_prefilter = outcome.trace.routing['anchor_prefilter']
    assert outcome.results[0].memory_object_id == 'decision-inventory-aligned'
    assert all(result.memory_object_id != 'decision-wallet-off-topic' for result in outcome.results if result.result_kind == 'memory_hit')
    assert anchor_prefilter['query_anchor_status'] == 'clear'
    assert anchor_prefilter['selected_query_anchor_kind'] == 'workstream'
    assert anchor_prefilter['selected_query_anchor'] == {'kind': 'workstream', 'value': 'inventory batch digest'}
    assert anchor_prefilter['fallback_mode'] == 'aligned_only'
    assert anchor_prefilter['excluded_by_anchor_count'] == 0
    assert anchor_prefilter['insufficient_candidate_count'] == 1
    assert not anchor_prefilter.get('excluded_candidates')

# After:
    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    anchor_prefilter = outcome.trace.routing['anchor_prefilter']
    # Aligned memory still ranks first
    assert outcome.results[0].memory_object_id == 'decision-inventory-aligned'
    # Previously-conflicting memory is now retained as secondary tier
    assert any(result.memory_object_id == 'decision-wallet-off-topic' for result in outcome.results if result.result_kind == 'memory_hit')
    assert anchor_prefilter['query_anchor_status'] == 'clear'
    assert anchor_prefilter['selected_query_anchor_kind'] == 'workstream'
    assert anchor_prefilter['selected_query_anchor'] == {'kind': 'workstream', 'value': 'inventory batch digest'}
    assert anchor_prefilter['fallback_mode'] == 'aligned_with_secondary'
    assert anchor_prefilter['aligned_candidate_count'] == 1
    assert anchor_prefilter['secondary_tier_count'] == 1
    assert anchor_prefilter['excluded_by_anchor_count'] == 0
    assert not anchor_prefilter.get('excluded_candidates')
```

- [ ] **Step 3.2: Update `test_work_resumption_anchor_prefilter_excludes_adjacent_workstream_checkpoint` to match new behavior**

In `tests/test_agent_conversation_memory_routing_resumption.py` at lines 486-495, replace the assertion block:

```python
# Before:
    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    anchor_prefilter = outcome.trace.routing['anchor_prefilter']
    assert outcome.results[0].memory_object_id == 'checkpoint-inventory-resume'
    assert all(result.memory_object_id != 'checkpoint-wallet-adjacent' for result in outcome.results if result.result_kind == 'memory_hit')
    assert anchor_prefilter['query_anchor_status'] == 'clear'
    assert anchor_prefilter['selected_query_anchor_kind'] == 'workstream'
    assert anchor_prefilter['selected_query_anchor'] == {'kind': 'workstream', 'value': 'inventory batch digest'}
    assert anchor_prefilter['fallback_mode'] == 'aligned_only'
    assert anchor_prefilter['excluded_by_anchor_count'] == 1

# After:
    assert outcome.trace is not None
    assert outcome.trace.routing is not None
    anchor_prefilter = outcome.trace.routing['anchor_prefilter']
    # Inventory checkpoint still ranks first (aligned + tier-penalty guarantee)
    assert outcome.results[0].memory_object_id == 'checkpoint-inventory-resume'
    # Adjacent wallet checkpoint is now retained as secondary tier
    assert any(result.memory_object_id == 'checkpoint-wallet-adjacent' for result in outcome.results if result.result_kind == 'memory_hit')
    assert anchor_prefilter['query_anchor_status'] == 'clear'
    assert anchor_prefilter['selected_query_anchor_kind'] == 'workstream'
    assert anchor_prefilter['selected_query_anchor'] == {'kind': 'workstream', 'value': 'inventory batch digest'}
    assert anchor_prefilter['fallback_mode'] == 'aligned_with_secondary'
    assert anchor_prefilter['aligned_candidate_count'] == 1
    assert anchor_prefilter['secondary_tier_count'] == 1
    assert anchor_prefilter['excluded_by_anchor_count'] == 0
```

- [ ] **Step 3.3: Write a failing test for secondary-absent-when-limit-is-filled**

This covers the spec acceptance criterion: "When aligned candidates alone reach `requested_limit`, no secondary candidates appear in final results." Neither of the updated tests above exercises this because both use `requested_limit=6` with only two candidates, so both always fit.

Add to `tests/test_agent_conversation_memory_routing_recall.py` after the updated tests:

```python
def test_anchor_prefilter_secondary_absent_when_aligned_fills_limit() -> None:
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='slack:channel:CLOCAL001')
    inventory_scope = MemorySubjectAnchor(kind='workstream', value='inventory batch digest')
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-inventory-aligned',
                type='decision',
                payload={
                    'decision': 'The inventory batch digest should continue on the local digest path.',
                    'rationale': 'The inventory batch digest already has a confirmed local rerun path.',
                },
                score=16,
                evidence=[],
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:inventory',
                envelope=_memory_envelope('finding', subjects=[inventory_scope]),
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-legacy-no-anchor',
                type='decision',
                payload={
                    'decision': 'Use event timestamps for ordering to avoid replay collisions.',
                    'rationale': 'Temporal ordering prevents duplicate entries after sync delays.',
                },
                score=14,
                evidence=[],
                container_ref='slack:channel:CLOCAL001',
                thread_ref='slack:thread:CLOCAL001:sync',
                envelope=None,
            ),
        ],
        trace=QueryTrace(
            query_text='What had we concluded about inventory batch digest?',
            query_tokens=('what', 'had', 'we', 'concluded', 'about', 'inventory', 'batch', 'digest'),
            limit=1,
            filters=query_filters,
            stages=(),
        ),
    )

    outcome = plugin.route_query_results(
        text='What had we concluded about inventory batch digest?',
        requested_limit=1,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        runtime_context=QueryRuntimeContext(turn_kind='new_thread', session_has_sufficient_local_context=False),
        include_trace=True,
    )

    memory_results = [r for r in outcome.results if r.result_kind == 'memory_hit']
    assert len(memory_results) == 1
    assert memory_results[0].memory_object_id == 'decision-inventory-aligned'
    assert all(r.memory_object_id != 'decision-legacy-no-anchor' for r in memory_results)
```

Run: `python -m pytest tests/test_agent_conversation_memory_routing_recall.py::test_anchor_prefilter_secondary_absent_when_aligned_fills_limit -x -q`

Expected: FAIL before implementation (secondary may surface), PASS after step 3.5.

- [ ] **Step 3.4: Run all three updated/new tests to confirm they fail before implementation**

Run: `python -m pytest tests/test_agent_conversation_memory_routing_recall.py::test_workstream_anchor_prefilter_excludes_same_surface_off_topic_memory tests/test_agent_conversation_memory_routing_resumption.py::test_work_resumption_anchor_prefilter_excludes_adjacent_workstream_checkpoint tests/test_agent_conversation_memory_routing_recall.py::test_anchor_prefilter_secondary_absent_when_aligned_fills_limit -x -q`

Expected: all three FAIL (wallet/adjacent still excluded, limit test may pass or fail depending on current behavior).

- [ ] **Step 3.5: Implement Change 3 in `_anchor_prefilter_candidates`**

In `semantic/agent_conversation_memory_routing.py`, replace the `retained_memory_ids` assignment block (lines 569-595):

```python
# Before (lines 569-595):
    retained_memory_ids: set[int]
    legacy_retained: list[QueryResultItem] = []
    if aligned:
        retained_memory_ids = {id(item) for item in aligned}
        summary["fallback_mode"] = "aligned_only"
    elif insufficient:
        legacy_retained = legacy
        retained_memory_ids = {id(item) for item in [*insufficient, *legacy_retained]}
        summary["fallback_mode"] = "insufficient_then_legacy"
        for item in insufficient:
            candidate_states[_routing_result_id(item)] = {
                "anchor_prefilter_status": "insufficient_retained",
                "anchor_prefilter_reason_code": "anchor_insufficient",
                "anchor_prefilter_reason": "Candidate lacked the selected query-anchor kind and remained as anchored fallback.",
            }
    else:
        legacy_retained = legacy
        retained_memory_ids = {id(item) for item in legacy_retained}
        summary["fallback_mode"] = "legacy_only"
    if legacy_retained:
        summary["legacy_fallback_count"] = len(legacy_retained)
        for item in legacy_retained:
            candidate_states[_routing_result_id(item)] = {
                "anchor_prefilter_status": "legacy_fallback_retained",
                "anchor_prefilter_reason_code": "anchor_missing_legacy_fallback",
                "anchor_prefilter_reason": "Candidate had no write-time anchors and remained only as legacy fallback.",
            }

# After:
    retained_memory_ids: set[int]
    legacy_retained: list[QueryResultItem] = []
    if aligned:
        secondary = [*insufficient, *legacy]
        retained_memory_ids = {id(item) for item in [*aligned, *secondary]}
        if secondary:
            summary["fallback_mode"] = "aligned_with_secondary"
            summary["secondary_tier_count"] = len(secondary)
            for item in secondary:
                candidate_states[_routing_result_id(item)] = {
                    "anchor_prefilter_status": "secondary_tier",
                    "anchor_prefilter_reason_code": "anchor_secondary_tier",
                    "anchor_prefilter_reason": "Candidate entered the secondary tier alongside aligned candidates; ranked below aligned via tier penalty.",
                }
        else:
            summary["fallback_mode"] = "aligned_only"
    elif insufficient:
        legacy_retained = legacy
        retained_memory_ids = {id(item) for item in [*insufficient, *legacy_retained]}
        summary["fallback_mode"] = "insufficient_then_legacy"
        for item in insufficient:
            candidate_states[_routing_result_id(item)] = {
                "anchor_prefilter_status": "insufficient_retained",
                "anchor_prefilter_reason_code": "anchor_insufficient",
                "anchor_prefilter_reason": "Candidate lacked the selected query-anchor kind and remained as anchored fallback.",
            }
    else:
        legacy_retained = legacy
        retained_memory_ids = {id(item) for item in legacy_retained}
        summary["fallback_mode"] = "legacy_only"
    if legacy_retained:
        summary["legacy_fallback_count"] = len(legacy_retained)
        for item in legacy_retained:
            candidate_states[_routing_result_id(item)] = {
                "anchor_prefilter_status": "legacy_fallback_retained",
                "anchor_prefilter_reason_code": "anchor_missing_legacy_fallback",
                "anchor_prefilter_reason": "Candidate had no write-time anchors and remained only as legacy fallback.",
            }
```

- [ ] **Step 3.6: Run all three tests after implementation**

Run: `python -m pytest tests/test_agent_conversation_memory_routing_recall.py::test_workstream_anchor_prefilter_excludes_same_surface_off_topic_memory tests/test_agent_conversation_memory_routing_resumption.py::test_work_resumption_anchor_prefilter_excludes_adjacent_workstream_checkpoint tests/test_agent_conversation_memory_routing_recall.py::test_anchor_prefilter_secondary_absent_when_aligned_fills_limit -x -q`

Expected: all three PASS.

- [ ] **Step 3.7: Run the full test suite and routing benchmarks**

Run: `python -m pytest tests/ -x -q`

Expected: all 767 tests pass (766 from Task 2 + 1 new). If any test about anchor prefilter fails with `fallback_mode == 'aligned_only'` or an absence assertion, update it using the same pattern as steps 3.1 and 3.2: change "not in results" to "ranked below aligned", add `fallback_mode == 'aligned_with_secondary'` and `secondary_tier_count` assertions.

> **Benchmark note:** The test suite includes the routing benchmark (`test_memory_routing_benchmark.py`) and work resumption benchmark — their passage satisfies two of the three spec acceptance criteria. The third criterion — "Typed-memory classification benchmark (`items.jsonl`) unchanged within ±1 per category" — is satisfied implicitly: Changes 1–4 are entirely in the query routing path and do not touch write-time extraction, so the semantic extraction eval is unaffected and no separate eval run is required.

- [ ] **Step 3.8: Commit**

```bash
git add semantic/agent_conversation_memory_routing.py \
        tests/test_agent_conversation_memory_routing_recall.py \
        tests/test_agent_conversation_memory_routing_resumption.py
git commit -m "$(cat <<'EOF'
feat: retain secondary tier alongside aligned in anchor prefilter

When aligned candidates exist, insufficient and legacy candidates now also
enter the retained pool as secondary_tier. The ANCHOR_SECONDARY_TIER_PENALTY
deduction (Task 2) ensures aligned always ranks higher. secondary_tier_count
and fallback_mode=aligned_with_secondary are exposed in the anchor_prefilter
trace. Change 3 of 4 in the layered-defense plan.
EOF
)"
```

---

## Self-Review

### Spec Coverage

| Spec requirement | Task covering it |
|---|---|
| Change 1: conflicting → insufficient, `insufficient_retained_demoted` status | Task 1, step 1.4 |
| Change 1: no effect when aligned exist | Task 1, existing test updated in step 1.3 |
| Change 1: `insufficient_retained_demoted` visible in debug trace | Task 1, step 1.4 (candidate_states carries status, merged at routing.py:304, exposed by trace.py:336) |
| Change 2: `ANCHOR_SECONDARY_TIER_PENALTY ≥ ROUTING_FOCUS_BOOST` invariant | Task 2, `test_penalty_invariant_anchor_secondary_penalty_ge_focus_boost` |
| Change 2: all four secondary statuses penalized | Task 2, four individual tests |
| Change 2: aligned unaffected | Task 2, `test_aligned_candidate_receives_zero_penalty` |
| Change 2: `anchor_tier_penalty` in debug trace | Task 2, step 2.6 |
| Change 2: penalty defined in constants, not hardcoded | Task 2, step 2.3 |
| Change 3: insufficient+legacy retained alongside aligned | Task 3, step 3.4 |
| Change 3: `fallback_mode = "aligned_with_secondary"` | Task 3, step 3.4 |
| Change 3: `secondary_tier_count` in summary | Task 3, step 3.4 |
| Change 3: aligned still ranks first | Task 3, steps 3.1 and 3.2 (result[0] assertion preserved) |
| Change 3: no secondary when aligned fills limit | Task 3, `test_anchor_prefilter_secondary_absent_when_aligned_fills_limit` (step 3.3) |
| Change 4: `content_overlap_tokens` removed from candidate dicts | Task 2, step 2.8 |
| Change 4: `content_overlap_tokens` removed from trace | Task 2, steps 2.9 and 2.11 |
| Change 4: no other code reads/writes the field | Task 2, steps 2.9–2.12 |

### Placeholder Scan

No TBD, TODO, or placeholder text present. All code blocks show exact changes.

### Type Consistency

- `ANCHOR_SECONDARY_TIER_PENALTY` defined as `int` in constants, used as `int` in `_apply_anchor_tier_penalty` arithmetic — consistent.
- `anchor_tier_penalty` set as `int` in `_apply_anchor_tier_penalty`, read as `int` in trace entry — consistent.
- `secondary_tier_count` set as `int` (`len(secondary)`) in summary — consistent with other `*_count` fields.
- `_apply_anchor_tier_penalty` imported from `scoring.py` and called with `list[dict[str, object]]` — matches the parameter type used by all other `_apply_*` functions.
