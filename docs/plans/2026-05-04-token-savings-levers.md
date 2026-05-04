# Token Savings Levers — Design + Validation Findings

## Context

Research question: Can Pallium help agents work less expensively by reducing wasted
tokens (corrections, re-exploration, off-track work)?

Data: 28% correction rate overall. Memory-injected sessions: 23.7% vs no-memory: 36.6%.
78% of corrections are preventable with better memory surfacing.

## Architecture Flow (where the problem lives)

```
user types message
  → user_prompt_submit hook fires
    → POST /item-and-query (ingest + query in one call)
      → turn_inference.py: infers turn_kind + session_has_sufficient_local_context
        (item_count > 0 AND gap < 30 min → same_thread_continuation, local_context=True)
      → routing_selection.py: _evaluate_same_thread_local_context()
        if local_context=True AND candidates qualify → suppress injection
      → if not suppressed: score candidates → inject top blocks
    → format_injection() → inject into context as system-reminder
```

The problem: turn_inference.py says `local_context=True` for the entire session (turns
always < 30 min apart), so `_evaluate_same_thread_local_context` suppresses injection
whenever same-thread candidates look "good enough."

---

## Lever 1: Context Degradation Awareness

**File:** `core/turn_inference.py`

**Design:** After a configurable turn threshold, stop claiming local context is sufficient:

```python
LOCAL_CONTEXT_DEGRADATION_THRESHOLD = 16

if gap_seconds < CONTINUATION_THRESHOLD_SECONDS:
    local_context_sufficient = stats.item_count < LOCAL_CONTEXT_DEGRADATION_THRESHOLD
    return InferredRuntimeContext(
        turn_kind="same_thread_continuation",
        session_has_sufficient_local_context=local_context_sufficient,
    )
```

**Why 16:** Short threads (<20 msgs) have 5% correction rate, long threads (≥20) have 13%.

### VALIDATION FINDING (May 4 — injection replay simulation)

**Problem discovered:** Lifting suppression at ANY threshold gives only 56% precision.
The threshold doesn't matter — flat curve from 8 to 24 turns.

**Root cause:** The routing score cannot discriminate helpful from noise:
- Helpful avg score: 439
- Noise avg score: 458 (noise scores slightly HIGHER)
- Same memory is helpful in one context, noise in another (11 memories are both)
- Example: "i don't want to add a new process" is helpful 7x, noise 4x

**Conclusion:** Lever 1 alone is INSUFFICIENT. It needs a quality gate — either:
- Subject anchors on memories (topic matching)
- Type-scoped bypass (only specific types bypass, not all)
- Or combine with extraction cleanup to remove the worst offenders first

**Revised precision if extraction fixes are applied first:** ~65% (33% of noise
blocked by 515547a's length/containment checks on old memories).

---

## Lever 2: Task Checkpoint Forced Injection

**File:** `semantic/agent_conversation_memory_routing_selection.py` (~line 620)

**Design:** After suppression decision, check for active task_checkpoint in current
thread and force-inject regardless:

```python
if same_thread_context["suppress_injection"]:
    forced_blocks = _extract_forced_checkpoint_blocks(
        ranked_candidates, query_filters=query_filters
    )
    if forced_blocks:
        return _make_injection_result(
            forced_blocks, should_inject=True,
            decision_reason="forced_checkpoint_reinject", ...
        )
    return _make_injection_result([], should_inject=False, ...)
```

Conditions for forced injection:
- Type is task_checkpoint from same thread
- Has blocker_state or next_step (actionable content)
- Thread item_count > 12 (only in long sessions)
- At most 1 block (~200 tokens)

### VALIDATION FINDING

**Safe bet:** Only 2 of 60 noise cases involved task_checkpoints. Type-scoping
avoids the cross-topic noise problem that plagues decisions/investigations.

**Already partially addressed by 88a9c6a** (May 4): fixed 3 blockers preventing
task_checkpoints from surfacing (freshness_at propagation, 7d window, latest_status
branch). Status queries 0%→67% after fix.

---

## Lever 3: Widen Constraint Extraction

**File:** extraction prompt in `semantic/agent_conversation_memory.py`

**Design:** Extend constraint_memory to capture behavioral preferences ("always use X",
"prefer Y over Z", "don't explain, just do it").

**Impact:** 14 corrections + compounds over time. Leverages existing 170% injection
utilization of constraint_memory.

---

## Lever 4: Decision Retrieval at Session Start

**File:** `integrations/claude-code/hooks/session_start.py`

**Design:** Make two queries at session start:
1. General orientation (current) — 3 blocks, 800 chars
2. Recent decisions for this container (last 7 days) — 2 blocks, 600 chars

---

## Noise Analysis Summary (May 4)

- 141 suppressed queries replayed via Haiku classification
- 64 helpful (45%), 15 reinforcing (11%), 60 noise (43%), 2 redundant (1%)
- ALL 44 unique noise-causing memories predate extraction fixes (515547a)
- 33% of noise would be blocked by current extraction validation rules
- 65% of noise is valid memories injected into WRONG CONTEXT (topic mismatch)
- No existing signal (work_refs, subjects, envelope kind, source type) discriminates
- Duplicate memories amplify noise: "yes all three" 8x, "5% overhead" 7x

## Revised Priority

| Lever | Status | Confidence | Next Step |
|-------|--------|------------|-----------|
| 2. Checkpoint bypass | Safest | High | Implement (type-scoped, low noise risk) |
| 1. Turn threshold | Risky alone | Medium | Needs quality gate or extraction purge first |
| 3. Constraint widening | Ready | Medium | Prompt edit, low risk |
| 4. Session-start decisions | Ready | Medium | Small hook change |

**Blocking issue for Lever 1:** Need either subject anchors on memories OR a purge of
old low-quality memories before lifting suppression broadly.
