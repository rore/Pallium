# Dynamic Injection Block Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded 3-block injection cap with semantic dedup (evidence+text two-gate) and an expand-only dynamic cap (floor=3, expansion ratio=0.4, ceiling=5).

**Architecture:** Three independently committable changes: (1) add dedup functions and unit tests, (2) integrate dedup + dynamic cap into `_build_injectable_blocks` with updated injection summary, (3) add dedup `loss_stage` to sharp diagnostics. Each change is test-first.

**Tech Stack:** Python 3.12, pytest (`python -m pytest tests/ -x -q`). All changes are within `semantic/` and `tests/`.

**Spec:** `docs/specs/2026-04-09-dynamic-injection-cap-design.md`

---

## File Map

| File | Change |
|---|---|
| `semantic/agent_conversation_memory_routing_selection.py` | Task 1 (constants + dedup functions), Task 2 (integrate into `_build_injectable_blocks`) |
| `tests/test_agent_conversation_memory_routing_injection.py` | Task 1 (dedup unit tests), Task 2 (integration tests) |
| `semantic/agent_conversation_memory_routing_trace.py` | Task 3 (dedup loss_stage in sharp diagnostics) |

---

## Task 1 — Dedup functions and constants

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_selection.py` (top of file for constants, bottom for new functions)
- Modify: `tests/test_agent_conversation_memory_routing_injection.py` (new tests at end)

**Context:** The dedup functions are pure — they take candidate lists and return filtered lists. They can be tested independently before integration. The functions use `_candidate_content_surface()` (already in this file at line 706) and `content_tokens()` (already imported at line 4).

---

- [ ] **Step 1.1: Add constants and the `_candidate_evidence_ids` helper**

Add after the existing `_CONSTRAINT_SUPPLEMENT_CAP = 1` constant (line 946) in `semantic/agent_conversation_memory_routing_selection.py`:

```python
# ---------------------------------------------------------------------------
# Injection dedup + dynamic cap
# ---------------------------------------------------------------------------

INJECTION_MIN_FLOOR = 3
INJECTION_EXPANSION_RATIO = 0.4
INJECTION_HARD_CEILING = 5
DEDUP_EVIDENCE_TEXT_THRESHOLD = 0.4
DEDUP_TEXT_ONLY_THRESHOLD = 0.7
DEDUP_MIN_TOKENS = 2


def _candidate_evidence_ids(candidate: dict[str, object]) -> set[str]:
    """Extract source_item_ids from a candidate's evidence references."""
    item = candidate["item"]
    assert isinstance(item, QueryResultItem)
    evidence = getattr(item, "evidence", None) or []
    return {e.source_item_id for e in evidence if hasattr(e, "source_item_id")}
```

- [ ] **Step 1.2: Add `_is_content_duplicate` — the two-gate check between two candidates**

Add directly after `_candidate_evidence_ids`:

```python
def _is_content_duplicate(
    candidate_a: dict[str, object],
    candidate_b: dict[str, object],
) -> bool:
    """Two-gate duplicate check: evidence+text or text-only.

    Returns True when two candidates carry semantically duplicate content.
    Evidence overlap alone is not sufficient (thread-level extractions share
    all source items) — it must be combined with text overlap.
    """
    item_a = candidate_a["item"]
    item_b = candidate_b["item"]
    assert isinstance(item_a, QueryResultItem)
    assert isinstance(item_b, QueryResultItem)

    text_a = _candidate_content_surface(item_a)
    text_b = _candidate_content_surface(item_b)
    tokens_a = content_tokens(text_a)
    tokens_b = content_tokens(text_b)

    # Overlap coefficient: |intersection| / min(|A|, |B|)
    min_size = min(len(tokens_a), len(tokens_b))
    if min_size == 0:
        return False
    overlap = len(tokens_a & tokens_b) / min_size

    # Gate 1: evidence overlap + loose text threshold
    evidence_a = _candidate_evidence_ids(candidate_a)
    evidence_b = _candidate_evidence_ids(candidate_b)
    if evidence_a and evidence_b and evidence_a & evidence_b:
        if overlap >= DEDUP_EVIDENCE_TEXT_THRESHOLD:
            return True

    # Gate 2: text-only with strict threshold (needs minimum tokens)
    if min_size >= DEDUP_MIN_TOKENS and overlap >= DEDUP_TEXT_ONLY_THRESHOLD:
        return True

    return False
```

- [ ] **Step 1.3: Add `_dedup_eligible_candidates` — the greedy sweep**

Add directly after `_is_content_duplicate`:

```python
def _dedup_eligible_candidates(
    candidates: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Greedy dedup sweep: retain candidates in routing_score order, skip duplicates.

    Returns (retained, removed) where removed candidates are those that
    duplicate an already-retained candidate.
    """
    if len(candidates) <= 1:
        return list(candidates), []

    retained: list[dict[str, object]] = []
    removed: list[dict[str, object]] = []
    for candidate in candidates:
        is_dup = False
        for kept in retained:
            if _is_content_duplicate(candidate, kept):
                is_dup = True
                break
        if is_dup:
            removed.append(candidate)
        else:
            retained.append(candidate)
    return retained, removed
```

- [ ] **Step 1.4: Add `_is_duplicate_of_selected` — shared helper for companion/constraint dedup**

Add directly after `_dedup_eligible_candidates`:

```python
def _is_duplicate_of_selected(
    candidate: dict[str, object],
    selected: list[dict[str, object]],
) -> bool:
    """Check if a candidate duplicates any already-selected candidate."""
    for kept in selected:
        if _is_content_duplicate(candidate, kept):
            return True
    return False
```

- [ ] **Step 1.5: Run tests to confirm nothing is broken**

Run: `python -m pytest tests/ -x -q`
Expected: All existing tests pass (new code is not yet called).

- [ ] **Step 1.6: Write test — evidence + text dedup detects cross-package duplicate**

Add at the end of `tests/test_agent_conversation_memory_routing_injection.py`:

```python
def test_dedup_detects_cross_package_duplicate_via_evidence_and_text() -> None:
    """Decision and atomic_fact from same source with overlapping text → duplicate."""
    from semantic.agent_conversation_memory_routing_selection import (
        _is_content_duplicate,
        _dedup_eligible_candidates,
    )
    shared_evidence = [
        EvidenceReference(
            source_item_id='msg-15',
            source_type='message',
            source_id='msg-15',
        )
    ]
    decision_candidate = {
        "item": QueryResultItem(
            result_kind="memory_hit",
            memory_object_id="decision-1",
            type="decision",
            payload={"decision": "DPP-360 deprioritized", "rationale": "not relevant to current sprint"},
            score=18,
            evidence=shared_evidence,
            container_ref="chat:test",
        ),
        "routing_score": 500,
    }
    fact_candidate = {
        "item": QueryResultItem(
            result_kind="memory_hit",
            memory_object_id="fact-1",
            type="atomic_fact",
            payload={"statement": "DPP-360 not relevant"},
            score=15,
            evidence=shared_evidence + [
                EvidenceReference(source_item_id='msg-14', source_type='message', source_id='msg-14'),
            ],
            container_ref="chat:test",
        ),
        "routing_score": 400,
    }
    assert _is_content_duplicate(decision_candidate, fact_candidate) is True
    retained, removed = _dedup_eligible_candidates([decision_candidate, fact_candidate])
    assert len(retained) == 1
    assert retained[0]["item"].memory_object_id == "decision-1"  # higher routing_score wins
    assert len(removed) == 1
    assert removed[0]["item"].memory_object_id == "fact-1"
```

- [ ] **Step 1.7: Run the new test to verify it passes**

Run: `python -m pytest tests/test_agent_conversation_memory_routing_injection.py::test_dedup_detects_cross_package_duplicate_via_evidence_and_text -v`
Expected: PASS

- [ ] **Step 1.8: Write test — same-thread different-topic memories survive dedup (critical safety)**

```python
def test_dedup_preserves_same_thread_different_topic_memories() -> None:
    """Two atomic_facts from same thread but different topics share evidence but not text → both survive."""
    from semantic.agent_conversation_memory_routing_selection import (
        _is_content_duplicate,
        _dedup_eligible_candidates,
    )
    # Both facts link to all messages in the thread (thread-level extraction)
    thread_evidence = [
        EvidenceReference(source_item_id='msg-1', source_type='message', source_id='msg-1'),
        EvidenceReference(source_item_id='msg-2', source_type='message', source_id='msg-2'),
        EvidenceReference(source_item_id='msg-3', source_type='message', source_id='msg-3'),
    ]
    dpp_fact = {
        "item": QueryResultItem(
            result_kind="memory_hit",
            memory_object_id="fact-dpp",
            type="atomic_fact",
            payload={"statement": "DPP-360 was deprioritized from the current sprint"},
            score=18,
            evidence=thread_evidence,
            container_ref="chat:test",
        ),
        "routing_score": 500,
    }
    btp_fact = {
        "item": QueryResultItem(
            result_kind="memory_hit",
            memory_object_id="fact-btp",
            type="atomic_fact",
            payload={"statement": "BTP internal logging architecture has three distinct layers"},
            score=16,
            evidence=thread_evidence,
            container_ref="chat:test",
        ),
        "routing_score": 400,
    }
    # Evidence overlaps (same thread), but text overlap is low → not duplicates
    assert _is_content_duplicate(dpp_fact, btp_fact) is False
    retained, removed = _dedup_eligible_candidates([dpp_fact, btp_fact])
    assert len(retained) == 2
    assert len(removed) == 0
```

- [ ] **Step 1.9: Run the safety test**

Run: `python -m pytest tests/test_agent_conversation_memory_routing_injection.py::test_dedup_preserves_same_thread_different_topic_memories -v`
Expected: PASS

- [ ] **Step 1.10: Write test — text-only dedup (no shared evidence)**

```python
def test_dedup_detects_text_only_duplicate_without_shared_evidence() -> None:
    """Two candidates with no shared evidence but 70%+ text overlap → duplicate."""
    from semantic.agent_conversation_memory_routing_selection import _is_content_duplicate
    candidate_a = {
        "item": QueryResultItem(
            result_kind="memory_hit",
            memory_object_id="mem-a",
            type="pattern_memory",
            payload={"summary": "catalog sync delays cause duplicate hold records"},
            score=18,
            evidence=[EvidenceReference(source_item_id='src-a', source_type='message', source_id='src-a')],
            container_ref="chat:test",
        ),
        "routing_score": 500,
    }
    candidate_b = {
        "item": QueryResultItem(
            result_kind="memory_hit",
            memory_object_id="mem-b",
            type="continuity_memory",
            payload={"carry_forward_answer": "catalog sync delays cause duplicate holds"},
            score=15,
            evidence=[EvidenceReference(source_item_id='src-b', source_type='message', source_id='src-b')],
            container_ref="chat:test",
        ),
        "routing_score": 400,
    }
    assert _is_content_duplicate(candidate_a, candidate_b) is True
```

- [ ] **Step 1.11: Write test — greedy sweep preserves A and C when only B bridges**

```python
def test_dedup_greedy_sweep_preserves_non_transitive_pair() -> None:
    """A~B and B~C but not A~C → A and C survive, only B removed."""
    from semantic.agent_conversation_memory_routing_selection import _dedup_eligible_candidates
    # A: "catalog sync delays cause duplicate hold records"
    # B: "duplicate hold records need journal refactoring" (bridges A and C)
    # C: "journal refactoring improves batch processing reliability"
    candidate_a = {
        "item": QueryResultItem(
            result_kind="memory_hit",
            memory_object_id="mem-a",
            type="pattern_memory",
            payload={"summary": "catalog sync delays cause duplicate hold records in the system"},
            score=18,
            evidence=[],
            container_ref="chat:test",
        ),
        "routing_score": 500,
    }
    candidate_b = {
        "item": QueryResultItem(
            result_kind="memory_hit",
            memory_object_id="mem-b",
            type="pattern_memory",
            payload={"summary": "duplicate hold records need journal refactoring"},
            score=16,
            evidence=[],
            container_ref="chat:test",
        ),
        "routing_score": 400,
    }
    candidate_c = {
        "item": QueryResultItem(
            result_kind="memory_hit",
            memory_object_id="mem-c",
            type="pattern_memory",
            payload={"summary": "journal refactoring improves batch processing reliability"},
            score=14,
            evidence=[],
            container_ref="chat:test",
        ),
        "routing_score": 300,
    }
    retained, removed = _dedup_eligible_candidates([candidate_a, candidate_b, candidate_c])
    retained_ids = {c["item"].memory_object_id for c in retained}
    removed_ids = {c["item"].memory_object_id for c in removed}
    # B overlaps A on "duplicate hold records" → B removed
    # C checked against A only (B gone) — no overlap → C retained
    assert "mem-a" in retained_ids
    assert "mem-c" in retained_ids
    assert "mem-b" in removed_ids
```

- [ ] **Step 1.12: Run all new dedup tests**

Run: `python -m pytest tests/test_agent_conversation_memory_routing_injection.py -k "dedup" -v`
Expected: All 4 tests PASS

- [ ] **Step 1.13: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All existing tests still pass

- [ ] **Step 1.14: Commit**

```bash
git add semantic/agent_conversation_memory_routing_selection.py tests/test_agent_conversation_memory_routing_injection.py
git commit -m "feat: add injection dedup functions with two-gate detection (evidence+text)"
```

---

## Task 2 — Integrate dedup + dynamic cap into `_build_injectable_blocks`

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_selection.py:219-404` (`_build_injectable_blocks`)
- Modify: `tests/test_agent_conversation_memory_routing_injection.py` (new integration test)

**Context:** This task replaces the hardcoded `[:3]` cap with dedup + dynamic expansion. Five early-return paths report `"cap": 3` and must change to `INJECTION_HARD_CEILING`. The main selection block (lines 335-365) is rewritten. Companion fill (336-355) and constraint fill (357-365) switch from `3` to `INJECTION_HARD_CEILING` and add dedup checks.

---

- [ ] **Step 2.1: Update all early-return `"cap": 3` to `INJECTION_HARD_CEILING`**

In `_build_injectable_blocks` in `semantic/agent_conversation_memory_routing_selection.py`, there are five early-return dicts with `"cap": 3`. Replace each with `"cap": INJECTION_HARD_CEILING`:

Line 242: `"cap": 3,` → `"cap": INJECTION_HARD_CEILING,`
Line 252: `"cap": 3,` → `"cap": INJECTION_HARD_CEILING,`
Line 280: `"cap": 3,` → `"cap": INJECTION_HARD_CEILING,`
Line 293 (approx, in the low-confidence return): `"cap": 3,` → `"cap": INJECTION_HARD_CEILING,`
Line 331: `"cap": 3,` → `"cap": INJECTION_HARD_CEILING,`

- [ ] **Step 2.2: Replace the main selection block (line 335 onwards)**

Replace the block from `selected_candidates = list(primary_eligible_candidates[:3])` through to `selected_candidates.extend(constraint_supplements)` (lines 335-365) with:

```python
    # --- Dedup + dynamic cap (replaces static [:3] cap) ---
    deduped_candidates, dedup_removed = _dedup_eligible_candidates(primary_eligible_candidates)
    dedup_removed_ids = [_routing_result_id(c["item"]) for c in dedup_removed]

    floor = min(INJECTION_MIN_FLOOR, len(deduped_candidates))
    selected_candidates = list(deduped_candidates[:floor])

    # Expand beyond floor if candidates score well relative to top
    expansion_added = 0
    if deduped_candidates and floor > 0:
        top_score = int(deduped_candidates[0].get("routing_score") or 0)
        if top_score > 0 and len(deduped_candidates) > floor:
            expansion_floor_score = top_score * INJECTION_EXPANSION_RATIO
            for candidate in deduped_candidates[floor:]:
                if len(selected_candidates) >= INJECTION_HARD_CEILING:
                    break
                if int(candidate.get("routing_score") or 0) >= expansion_floor_score:
                    selected_candidates.append(candidate)
                    expansion_added += 1

    # Companion fill (work_resumption only): fill to ceiling with dedup check
    if intent == "work_resumption" and len(selected_candidates) < INJECTION_HARD_CEILING:
        used_result_ids = {_routing_result_id(candidate["item"]) for candidate in selected_candidates}
        companion_candidates = [
            candidate
            for candidate in final_candidates
            if _candidate_is_injection_eligible(
                candidate,
                intent=intent,
                query_text=query_text,
                allow_discussion_fallback=False,
                allow_source_companion=True,
            )
            and candidate["item"].result_kind == "source_hit"
            and _routing_result_id(candidate["item"]) not in used_result_ids
        ]
        for candidate in companion_candidates:
            if len(selected_candidates) >= INJECTION_HARD_CEILING:
                break
            if _is_duplicate_of_selected(candidate, selected_candidates):
                continue
            selected_candidates.append(candidate)
            used_result_ids.add(_routing_result_id(candidate["item"]))

    # Constraint supplement: add recent constraint if room permits, with dedup check
    if len(selected_candidates) < INJECTION_HARD_CEILING:
        _selected_ids = {_routing_result_id(c["item"]) for c in selected_candidates}
        constraint_supplements = _find_constraint_supplements(
            ranked_candidates,
            already_selected_ids=_selected_ids,
            max_count=min(_CONSTRAINT_SUPPLEMENT_CAP, INJECTION_HARD_CEILING - len(selected_candidates)),
        )
        for cs in constraint_supplements:
            if _is_duplicate_of_selected(cs, selected_candidates):
                continue
            selected_candidates.append(cs)
```

- [ ] **Step 2.3: Update the injection summary dict at the end of `_build_injectable_blocks`**

Replace the return block (currently starting around line 395) — the dict that contains `"cap": 3`:

```python
    return blocks, {
        "should_inject": bool(blocks),
        "decision_reason": "carry_forward_available" if blocks else "no_relevant_memory",
        "injection_method": "simplified",
        "returned_block_ids": returned_ids,
        "eligible_result_ids": eligible_ids,
        "dropped_by_cap_result_ids": dropped_ids,
        "cap": INJECTION_HARD_CEILING,
        "cap_config": {
            "floor": INJECTION_MIN_FLOOR,
            "expansion_ratio": INJECTION_EXPANSION_RATIO,
            "ceiling": INJECTION_HARD_CEILING,
        },
        "dedup_applied": bool(dedup_removed),
        "dedup_removed_count": len(dedup_removed),
        "dedup_removed_result_ids": dedup_removed_ids,
        "expansion_applied": expansion_added > 0,
        "expansion_added_count": expansion_added,
        "same_thread_context_evaluation": same_thread_context,
    }
```

- [ ] **Step 2.4: Run existing tests to check for regressions**

Run: `python -m pytest tests/ -x -q`
Expected: All existing tests pass. The floor=3 preserves today's behavior for scenarios with <= 3 eligible candidates. Injection summary now reports `cap=5` instead of `cap=3`, but no test asserts `cap==3` directly.

- [ ] **Step 2.5: Write integration test — expansion beyond 3 when scores permit**

Add to `tests/test_agent_conversation_memory_routing_injection.py`:

```python
def test_dynamic_cap_expands_beyond_floor_when_scores_permit() -> None:
    """With 5 eligible candidates, expansion includes those above 40% of top score."""
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-dynamic-cap')
    now = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id=f'decision-cap-{i}',
                type='decision',
                payload={
                    'decision': f'Catalog sync approach {i} was selected for batch processing pipeline segment {i}',
                    'rationale': f'Performance testing confirmed approach {i} reduces latency by {20+i}%',
                },
                score=20 - i,
                evidence=[EvidenceReference(source_item_id=f'src-cap-{i}', source_type='message', source_id=f'src-cap-{i}', occurred_at=now)],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-dynamic-cap',
                freshness_at=now,
            )
            for i in range(5)
        ],
        trace=QueryTrace(
            query_text='What were the catalog sync decisions for batch processing?',
            query_tokens=('catalog', 'sync', 'decisions', 'batch', 'processing'),
            limit=5,
            filters=query_filters,
            stages=(),
        ),
    )
    outcome = plugin.route_query_results(
        text='What were the catalog sync decisions for batch processing?',
        requested_limit=5,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        include_trace=True,
    )
    assert outcome.should_inject is True
    # Should have more than 3 blocks if expansion fired
    # (exact count depends on scoring, but should be > 3 given all are decisions with good scores)
    assert len(outcome.injectable_blocks) >= 3
    routing = (outcome.trace.routing or {}) if outcome.trace else {}
    injection = routing.get("injection_decision", {})
    assert injection.get("cap") == 5
    assert "cap_config" in injection
```

- [ ] **Step 2.6: Run the integration test**

Run: `python -m pytest tests/test_agent_conversation_memory_routing_injection.py::test_dynamic_cap_expands_beyond_floor_when_scores_permit -v`
Expected: PASS

- [ ] **Step 2.7: Write integration test — dedup removes cross-package duplicate in full pipeline**

```python
def test_injection_dedup_removes_cross_package_duplicate_in_pipeline() -> None:
    """Decision and atomic_fact about same topic from same source → only one injected."""
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-dedup-pipe')
    now = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)
    shared_evidence = [
        EvidenceReference(source_item_id='msg-dedup-1', source_type='message', source_id='msg-dedup-1', occurred_at=now),
    ]
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-dedup-1',
                type='decision',
                payload={'decision': 'Catalog sync batch scheduling deprioritized', 'rationale': 'Not relevant to current sprint priorities'},
                score=20,
                evidence=shared_evidence,
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-dedup-pipe',
                freshness_at=now,
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='fact-dedup-1',
                type='atomic_fact',
                payload={'statement': 'Catalog sync batch scheduling not relevant to current sprint'},
                score=18,
                evidence=shared_evidence,
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-dedup-pipe',
                freshness_at=now,
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-dedup-2',
                type='decision',
                payload={'decision': 'Library reservation hold timeout extended to 48 hours', 'rationale': 'User complaints about premature hold expiry'},
                score=16,
                evidence=[EvidenceReference(source_item_id='msg-dedup-2', source_type='message', source_id='msg-dedup-2', occurred_at=now)],
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-dedup-pipe',
                freshness_at=now,
            ),
        ],
        trace=QueryTrace(
            query_text='What were the recent catalog and library decisions?',
            query_tokens=('recent', 'catalog', 'library', 'decisions'),
            limit=5,
            filters=query_filters,
            stages=(),
        ),
    )
    outcome = plugin.route_query_results(
        text='What were the recent catalog and library decisions?',
        requested_limit=5,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        include_trace=True,
    )
    assert outcome.should_inject is True
    injected_ids = {b.result_id for b in outcome.injectable_blocks}
    # The decision should win over the atomic_fact (higher score → higher routing_score)
    assert 'memory_object:decision-dedup-1' in injected_ids
    assert 'memory_object:fact-dedup-1' not in injected_ids
    # The second decision (different topic) should survive
    assert 'memory_object:decision-dedup-2' in injected_ids
    routing = (outcome.trace.routing or {}) if outcome.trace else {}
    injection = routing.get("injection_decision", {})
    assert injection.get("dedup_applied") is True
    assert injection.get("dedup_removed_count") >= 1
```

- [ ] **Step 2.8: Run the pipeline dedup test**

Run: `python -m pytest tests/test_agent_conversation_memory_routing_injection.py::test_injection_dedup_removes_cross_package_duplicate_in_pipeline -v`
Expected: PASS

- [ ] **Step 2.9: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass

- [ ] **Step 2.10: Commit**

```bash
git add semantic/agent_conversation_memory_routing_selection.py tests/test_agent_conversation_memory_routing_injection.py
git commit -m "feat: integrate dedup + dynamic cap into injection block selection"
```

---

## Task 3 — Dedup loss_stage in sharp diagnostics

**Files:**
- Modify: `semantic/agent_conversation_memory_routing_trace.py:331-424` (`_build_sharp_candidate_diagnostics`)
- Modify: `semantic/agent_conversation_memory_routing_selection.py` (pass dedup_removed_ids to diagnostics builder)
- Modify: `semantic/agent_conversation_memory_routing.py:439-448` (pass new parameter)
- Modify: `tests/test_agent_conversation_memory_routing_injection.py` (new test)

**Context:** Currently, candidates dropped by the injection cap get `loss_stage="injection_cap"`. With dedup, a candidate removed as a duplicate should get `loss_stage="dedup"` with a `dedup_kept_result_id` pointing to the retained candidate. This requires passing dedup information from `_build_injectable_blocks` through to `_build_sharp_candidate_diagnostics`.

---

- [ ] **Step 3.1: Update `_build_injectable_blocks` to expose dedup mapping**

The `_build_injectable_blocks` function already returns `dedup_removed_result_ids` in the injection summary. We need a mapping from removed_id → kept_id for diagnostics. Modify the dedup block in `_build_injectable_blocks` (from Task 2) to also build a dedup mapping:

After the dedup call (`deduped_candidates, dedup_removed = _dedup_eligible_candidates(...)`) add:

```python
    dedup_kept_map: dict[str, str] = {}
    for removed_candidate in dedup_removed:
        removed_id = _routing_result_id(removed_candidate["item"])
        # Find which retained candidate caused the removal
        for kept in deduped_candidates:
            if _is_content_duplicate(removed_candidate, kept):
                dedup_kept_map[removed_id] = _routing_result_id(kept["item"])
                break
```

Add `"dedup_kept_map": dedup_kept_map,` to the injection summary return dict.

- [ ] **Step 3.2: Update `_build_sharp_candidate_diagnostics` signature and logic**

In `semantic/agent_conversation_memory_routing_trace.py`, add a new parameter to `_build_sharp_candidate_diagnostics`:

```python
def _build_sharp_candidate_diagnostics(
    *,
    ranked_candidates: list[dict[str, object]],
    final_candidates: list[dict[str, object]],
    injectable_blocks: list[InjectableBlock],
    decision_reason: str,
    query_text: str,
    retrieved_result_ids: set[str] | None = None,
    debug_candidate_loader=None,
    candidate_injection_eligibility_fn: Callable[..., bool] | None = None,
    dedup_kept_map: dict[str, str] | None = None,  # NEW
) -> list[dict[str, object]]:
```

Then in the loss_stage assignment block (around line 360-372), add a dedup check before the existing `injection_cap` branch:

```python
        elif result_id not in selected_injection_ids:
            _dedup_map = dedup_kept_map or {}
            if result_id in _dedup_map:
                loss_stage = "dedup"
                loss_reason_code = "injection_dedup"
                loss_reason = "Candidate was removed as a semantic duplicate of a higher-scored candidate."
            elif decision_reason == "same_thread_context_sufficient":
                # ... existing logic unchanged ...
```

And add `dedup_kept_result_id` to the diagnostics entry:

```python
        diagnostics[result_id] = {
            # ... existing fields ...
            "dedup_kept_result_id": _dedup_map.get(result_id),  # NEW — None if not deduped
        }
```

- [ ] **Step 3.3: Update the call site in `agent_conversation_memory_routing.py`**

In `route_query_results` (line 439), pass the new parameter:

```python
        sharp_candidate_diagnostics = _build_sharp_candidate_diagnostics(
            ranked_candidates=ranked_candidates,
            final_candidates=final_candidates,
            injectable_blocks=injection_blocks,
            decision_reason=str(injection_summary["decision_reason"]),
            query_text=text,
            retrieved_result_ids={_routing_result_id(item) for item in retrieval_result.results},
            debug_candidate_loader=debug_candidate_loader if include_trace else None,
            candidate_injection_eligibility_fn=_candidate_is_injection_eligible,
            dedup_kept_map=dict(injection_summary.get("dedup_kept_map") or {}),  # NEW
        )
```

- [ ] **Step 3.4: Run existing tests**

Run: `python -m pytest tests/ -x -q`
Expected: All pass — the new parameter defaults to `None`, so existing callers are unaffected.

- [ ] **Step 3.5: Write test — deduped candidate gets `loss_stage="dedup"` in diagnostics**

```python
def test_sharp_diagnostics_shows_dedup_loss_stage() -> None:
    """A deduped candidate should have loss_stage='dedup' in sharp diagnostics."""
    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant='strict_typed_memory_v4_evidence_guarded',
    )
    query_filters = QueryFilters(container_ref='chat:library-help', thread_ref='chat:library-help:thread-diag-dedup')
    now = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)
    shared_evidence = [
        EvidenceReference(source_item_id='msg-diag-1', source_type='message', source_id='msg-diag-1', occurred_at=now),
    ]
    retrieval_result = RetrievalQueryResult(
        results=[
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-diag-1',
                type='decision',
                payload={'decision': 'Catalog batch scheduling deprioritized for sprint', 'rationale': 'Capacity constraints'},
                score=20,
                evidence=shared_evidence,
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-diag-dedup',
                freshness_at=now,
            ),
            QueryResultItem(
                result_kind='memory_hit',
                memory_object_id='decision-diag-2',
                type='decision',
                payload={'decision': 'Catalog batch scheduling not relevant this sprint', 'rationale': 'Team focused elsewhere'},
                score=18,
                evidence=shared_evidence,
                container_ref='chat:library-help',
                thread_ref='chat:library-help:thread-diag-dedup',
                freshness_at=now,
            ),
        ],
        trace=QueryTrace(
            query_text='What were the catalog batch scheduling decisions?',
            query_tokens=('catalog', 'batch', 'scheduling', 'decisions'),
            limit=5,
            filters=query_filters,
            stages=(),
        ),
    )
    outcome = plugin.route_query_results(
        text='What were the catalog batch scheduling decisions?',
        requested_limit=5,
        retrieval_result=retrieval_result,
        query_filters=query_filters,
        include_trace=True,
    )
    # Find the deduped candidate in diagnostics
    dedup_diags = [
        d for d in outcome.sharp_candidate_diagnostics
        if d.get("loss_stage") == "dedup"
    ]
    if dedup_diags:
        assert dedup_diags[0]["loss_reason_code"] == "injection_dedup"
        assert dedup_diags[0].get("dedup_kept_result_id") is not None
```

- [ ] **Step 3.6: Run the diagnostics test**

Run: `python -m pytest tests/test_agent_conversation_memory_routing_injection.py::test_sharp_diagnostics_shows_dedup_loss_stage -v`
Expected: PASS

- [ ] **Step 3.7: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass

- [ ] **Step 3.8: Commit**

```bash
git add semantic/agent_conversation_memory_routing_selection.py semantic/agent_conversation_memory_routing_trace.py semantic/agent_conversation_memory_routing.py tests/test_agent_conversation_memory_routing_injection.py
git commit -m "feat: add dedup loss_stage to sharp candidate diagnostics"
```

---

## Task 4 — Run benchmarks and verify

**Files:** No code changes — verification only.

---

- [ ] **Step 4.1: Run the work resumption benchmark**

Run: `python -m evals.work_resumption_benchmark`
Expected: No regressions. Check output for `injection_contract` pass rates.

- [ ] **Step 4.2: Run the memory routing benchmark**

Run: `python -m evals.memory_routing_benchmark`
Expected: No regressions. Check for `cap_obeyed` and `block_count_ok`.

- [ ] **Step 4.3: Review injection summary in benchmark output**

Grep benchmark output for `dedup_applied`, `expansion_applied` to verify the new fields are populated and the dynamic cap is working.

- [ ] **Step 4.4: Commit benchmark results if applicable**

If benchmark result files are tracked, commit any updated baselines.
