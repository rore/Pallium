# Dynamic Injection Block Cap with Semantic Dedup

**Date:** 2026-04-09
**Status:** Draft
**Scope:** Injection block selection in `_build_injectable_blocks()`

## Problem

Injection is hardcoded to max 3 blocks (`agent_conversation_memory_routing_selection.py:335`). Two issues:

1. **Cross-package duplicate waste.** Multi-package processing (`agent_conversation_memory` + `conversational_knowledge`) independently extracts memory from the same source items. A `decision` ("DPP-360 deprioritized") and an `atomic_fact` ("DPP-360 not relevant") carry the same core information but occupy two of three injection slots.

2. **Static cap drops substantive content.** A rich thread covering 6 distinct topics (tool selection, Jira unavailability, DPP requirements, DPP-360 deferral, BTP architecture, journal refactoring) produces many relevant memories, but only 3 survive injection. The cap doesn't adapt to content diversity or relevance distribution.

Observed in live interaction: Thread 2 asked "what did we last talk about?" and received 3 blocks — 2 about DPP-360 (one decision, one atomic fact) and 1 about journal refactoring. The DPP requirements analysis, BTP/internal logging architecture, and Jira constraint were all dropped.

## Solution

Two-phase replacement for the static `[:3]` cap:

1. **Semantic dedup** — detect and remove content-duplicate candidates before selection
2. **Expand-only dynamic cap** — guaranteed minimum floor + score-driven expansion up to a ceiling

### Design Principles

- **Expand-only safety:** The relevance check governs blocks 4-5 only. Blocks 1-3 are always included (after dedup). Worst case = today's behavior but deduped.
- **Data-driven resolution:** Dedup keeps the candidate with the highest `routing_score` rather than using a hand-authored type priority table.
- **Two-gate dedup:** Cross-package duplicates arise from the same source items, but evidence overlap alone is too broad (thread-level extractions share all source items in the thread). Evidence lowers the text similarity bar; text similarity alone requires a higher bar.

## Phase 1: Semantic Dedup

### Detection — two-gate signals

Two signals contribute to duplicate detection. Evidence overlap alone is **not** sufficient — thread-level extractions (`atomic_fact`, `thread_summary`, `task_checkpoint`) link to every source item in the thread, so same-thread memories would nearly always share evidence regardless of topic. Evidence must be combined with text overlap to confirm actual content similarity.

**Evidence overlap:**

```
shared_evidence(A, B) = bool(
    {e.source_item_id for e in A.evidence}
    & {e.source_item_id for e in B.evidence}
)
```

**Text overlap (overlap coefficient):**

```
overlap_coeff(A, B) = |tokens_A ∩ tokens_B| / min(|tokens_A|, |tokens_B|)
```

Uses existing `content_tokens()` (stopword-filtered, plural-stem-aware) and `_candidate_content_surface()` (extracts comparable text from any memory type).

**Combined rule:**

```
is_duplicate(A, B) =
    (shared_evidence(A, B) AND overlap_coeff(A, B) >= 0.4)   # evidence corroborates loose text match
    OR (overlap_coeff(A, B) >= 0.7                             # text-only requires strict match
        AND min(|tokens_A|, |tokens_B|) >= 2)
```

The evidence signal lowers the text overlap threshold (0.4 vs 0.7) because shared source material increases confidence that even loose text overlap reflects actual semantic duplication. But evidence alone is too broad to be a standalone dedup signal — an `atomic_fact` about DPP-360 and an `atomic_fact` about BTP architecture from the same thread share all evidence despite being about different topics.

### Resolution

**Greedy dedup sweep, not transitive closure.** Process candidates in descending `routing_score` order. The first candidate is always retained. For each subsequent candidate, check if it is a duplicate of any already-retained candidate. If so, discard it. Otherwise, retain it.

Example: A (score 500), B (score 400), C (score 300). A~B and B~C but not A~C. A is retained. B is checked against {A} — duplicate, discarded. C is checked against {A} — not duplicate, retained. Both A and C survive.

Rationale for greedy over transitive: transitive closure can merge distinct memories that share a bridging candidate (e.g., "BTP logging architecture" ~ "internal logging refactoring" ~ "journal refactoring approach" — logging bridges the first two, refactoring bridges the last two, but BTP architecture and journal refactoring are distinct topics).

**Tie-break** (equal routing_score): prefer the candidate with more content tokens (richer information content).

### Scope

Runs in two places (shared helper function):

1. On `primary_eligible_candidates` inside `_build_injectable_blocks()`, after eligibility filtering, before cap selection.
2. As a lightweight check when adding companion/constraint candidates: `_is_duplicate_of_selected(candidate, already_selected)`.

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| Single candidate or empty list | No dedup needed |
| All candidates form pairwise duplicates | Keep the single best per pair; may reduce pool to 1-2 |
| Cross-script candidates (e.g., Hebrew + English) | Evidence gate may fire (shared source items); text overlap won't match tokens due to different scripts. If evidence-only with no text overlap → not duplicate. Text-only path also won't fire. Correctly preserved as non-duplicates unless evidence + cross-language text happens to overlap at 0.4+ |
| Same-thread different-topic memories | Evidence overlap fires (thread-level), but text overlap below 0.4 → not duplicate. This is the key safety property of the two-gate design |
| Candidate with no evidence references | Evidence signal not applicable; text overlap is sole signal |
| Candidates with < 2 content tokens | Text overlap skipped (unreliable); evidence overlap still applies |
| Source_hit vs memory_hit sharing evidence | Detected — source_hits carry their source_item_id as evidence, memory_hits carry evidence links to the same source |

## Phase 2: Dynamic Cap

### Constants

Defined at module level in `agent_conversation_memory_routing_selection.py`:

```python
INJECTION_MIN_FLOOR = 3           # guaranteed minimum (today's behavior)
INJECTION_EXPANSION_RATIO = 0.4   # score floor for expansion
INJECTION_HARD_CEILING = 5        # matches available pool from final_candidates (API limit=5)
```

### Algorithm

Replaces `selected_candidates = list(primary_eligible_candidates[:3])` (line 335):

```python
deduped = _dedup_eligible_candidates(primary_eligible_candidates)
floor = min(INJECTION_MIN_FLOOR, len(deduped))
selected = list(deduped[:floor])

if deduped and floor > 0:
    top_score = int(deduped[0].get("routing_score") or 0)
    if top_score > 0 and len(deduped) > floor:
        expansion_floor_score = top_score * INJECTION_EXPANSION_RATIO
        for candidate in deduped[floor:]:
            if len(selected) >= INJECTION_HARD_CEILING:
                break
            if int(candidate.get("routing_score") or 0) >= expansion_floor_score:
                selected.append(candidate)
```

### Companion and Constraint Fill (revised)

Same fill logic as today, but:
- Ceiling changes from `3` to `INJECTION_HARD_CEILING`
- Before adding each companion/constraint candidate, check `_is_duplicate_of_selected(candidate, selected)` — skip if duplicate

```python
# Companion fill (work_resumption only)
if intent == "work_resumption" and len(selected) < INJECTION_HARD_CEILING:
    ...
    for candidate in companion_candidates:
        if len(selected) >= INJECTION_HARD_CEILING:
            break
        if _is_duplicate_of_selected(candidate, selected):
            continue
        selected.append(candidate)

# Constraint supplement
if len(selected) < INJECTION_HARD_CEILING:
    ...constraint supplement logic, with dedup check...
```

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| `top_score <= 0` | No expansion; floor-only |
| All candidates same score | All qualify for expansion up to ceiling |
| Only 1-2 eligible after dedup | floor = 1 or 2; no expansion possible |
| Expansion adds 0 (all below threshold) | Behaves like today, but deduped |
| Empty eligible list | Same as today — no injection |
| Companion is duplicate of primary | Skipped by `_is_duplicate_of_selected` |
| Constraint supplement is duplicate of primary | Skipped by `_is_duplicate_of_selected` |
| `final_candidates` has fewer than 5 items | Ceiling naturally bounded by available pool |

## Injection Summary Changes

The injection summary dict already reports `"cap": 3`. Updated fields:

```python
{
    # Changed fields
    "cap": INJECTION_HARD_CEILING,            # always the configured ceiling (was hardcoded 3)

    # New fields
    "cap_config": {
        "floor": INJECTION_MIN_FLOOR,
        "expansion_ratio": INJECTION_EXPANSION_RATIO,
        "ceiling": INJECTION_HARD_CEILING,
    },
    "dedup_applied": bool,                # True if any duplicates detected
    "dedup_removed_count": int,           # number of candidates removed
    "dedup_removed_result_ids": list,     # which candidates were removed
    "expansion_applied": bool,            # True if blocks beyond floor were added
    "expansion_added_count": int,         # blocks beyond floor

    # Existing fields (unchanged)
    "should_inject": bool,
    "decision_reason": str,
    "returned_block_ids": list,
    "eligible_result_ids": list,
    "dropped_by_cap_result_ids": list,    # now relative to dynamic ceiling
    "same_thread_context_evaluation": dict,
}
```

**Important:** `_build_injectable_blocks()` has five early-return paths (same-thread suppression, no candidates, gate blocked, constraint-only supplement, no eligible after filter) that all currently report `"cap": 3`. All must be updated to report `"cap": INJECTION_HARD_CEILING` for consistency — the eval framework reads `cap` from whatever path returns.

The eval framework at `evals/continuity_common.py:312` reads `cap` dynamically (`cap_value = int(injection_summary.get("cap", 3) or 3)`) and checks `cap_obeyed = injected_block_count <= cap_value`. Reporting the constant ceiling means existing evals validate correctly without changes.

## Sharp Diagnostics Changes

In `_build_sharp_candidate_diagnostics()` (`agent_conversation_memory_routing_trace.py`):

- New `loss_stage: "dedup"` for candidates removed as semantic duplicates
- New field `dedup_kept_result_id` — which candidate was kept instead
- Existing `loss_stage: "injection_cap"` unchanged, now relative to dynamic ceiling

## Files Changed

1. **`semantic/agent_conversation_memory_routing_selection.py`**
   - New function: `_dedup_eligible_candidates(candidates) -> list` — pairwise dedup using evidence + text signals
   - New function: `_is_duplicate_of_selected(candidate, selected) -> bool` — shared helper for companion/constraint dedup
   - Modified: `_build_injectable_blocks()` — dedup + dynamic cap replaces `[:3]`; companion/constraint fill uses ceiling + dedup check
   - New constants: `INJECTION_MIN_FLOOR`, `INJECTION_EXPANSION_RATIO`, `INJECTION_HARD_CEILING`, `DEDUP_EVIDENCE_TEXT_THRESHOLD`, `DEDUP_TEXT_ONLY_THRESHOLD`, `DEDUP_MIN_TOKENS`
   - Updated: injection_summary dict with new fields (including all early-return paths)

2. **`semantic/agent_conversation_memory_routing_trace.py`**
   - Modified: `_build_sharp_candidate_diagnostics()` — dedup `loss_stage` and `dedup_kept_result_id`

3. **No changes to:** `core/models.py`, `core/contracts.py`, `agent_conversation_memory_routing.py` (orchestrator), `core/query.py`, `api/schemas.py`

## What Doesn't Change

- Injection gate (`should_allow_injection`) — still decides inject/don't-inject before this code
- Same-thread context suppression — still suppresses before cap selection
- Eligibility filtering (`_candidate_is_injection_eligible`) — unchanged
- Content-overlap grounding — unchanged
- Query result limit (`requested_limit`) — independent from injection cap
- The `_select_final_candidates` function — unchanged; injection draws from its output

## Validation Plan

1. **Existing tests pass.** Min floor=3 preserves today's behavior for scenarios with <= 3 eligible candidates. No eval scenario asserts `expected_cap_behavior="drop_extra_candidates"`.

2. **New unit tests:**
   - Cross-package duplicate: decision + atomic_fact from same source_item with overlapping text → dedup removes the lower-scored duplicate
   - Evidence + text two-gate: two atomic_facts from same thread about DIFFERENT topics → shared evidence but text overlap < 0.4 → both survive (critical safety test)
   - Evidence dedup: two memory_hits sharing source_item_id with text overlap >= 0.4 → detected
   - Text-only dedup fallback: two candidates with no shared evidence but 70%+ text overlap → detected
   - Greedy sweep correctness: A~B and B~C but not A~C → A and C both survive
   - Expansion: 5 eligible with scores [500, 400, 350, 250, 100], ratio=0.4 → 4 blocks (100 < 200 threshold)
   - Floor-only: top_score=0 → exactly min(3, eligible) blocks
   - Companion dedup: companion source_hit duplicates selected memory → skipped
   - Constraint dedup: constraint supplement duplicates selected memory → skipped

3. **Benchmark runs:** LoCoMo + work_resumption + memory_routing benchmarks before/after. Compare:
   - `gold_in_context` rate (should not decrease)
   - Injection block counts (expect modest increase for multi-topic threads)
   - `dropped_by_cap_result_ids` counts (expect decrease)

4. **Threshold calibration:** After implementation, run benchmarks logging score distributions of expanded vs. dropped candidates to validate 0.4 ratio.

## Known Limitations

- **No topic diversity mechanism.** Expansion favors score, not coverage breadth. If one topic dominates the score distribution, expansion adds more of the same topic. This is a retrieval/ranking concern for a separate design.
- **Pool bounded by `final_candidates` (max 5).** If 5 proves too few for rich work_resumption queries, a future iteration can draw expansion candidates from `ranked_candidates` beyond `final_candidates`.
- **Expansion ratio requires empirical calibration.** 0.4 is a conservative starting point. The `dropped_by_cap_result_ids` tracking enables measurement of what the threshold includes/excludes.
