# Routing Simplification — Continuation Prompt

## What was done

A major routing simplification reduced Pallium's query routing pipeline from 17 stages to 10:

- **Scoring:** `retrieval_score * 10` (flat RRF) replaced with `quality_score * 200` (normalized raw lexical/vector). Layer weights compressed from 40-490 to 20-245 so retrieval quality matters ~1.5x vs type preference (was ~5x).
- **Suppression:** 3 cascading suppression stages replaced with 1 unified pass using composable `SuppressionRule` list in `routing_suppression.py`. Includes source echo, meta-text, weak summary, and discussion_summary echo rules.
- **Intent families:** 6 merged to 4: `recall`, `structured_recall`, `work_resumption`, `evidence_trace`.
- **Injection check:** QPP 4-gate justification replaced with simplified 2-level check in `routing_injection.py` (set-level gate + per-candidate eligibility). Type-aware: structured memory gets lower bar than source hits.
- **Resolver:** Evidence trace LLM resolver removed, replaced with deterministic source_ratio >= 0.75 check.
- **New modules:** `routing_floor.py` (relevance pre-filter), `routing_suppression.py`, `routing_injection.py`, `routing_annotations.py` (cross-candidate pre-computation).

Key files changed: `semantic/agent_conversation_memory_routing.py` (orchestrator), `semantic/agent_conversation_memory_routing_scoring.py` (formula + components), `semantic/agent_conversation_memory_routing_constants.py` (weights), plus 4 new modules and ~15 test/eval files.

## Current state

854 unit tests pass. Eval results compared to original code:

| Suite | Original | Current | Delta |
|---|---|---|---|
| Seed (20) | **20/20** | 19/20 (1 INV-03) | -1 regression |
| Cross-container (28) | 26/28 (2 INV-03) | 27/28 (0 INV-03, 1 quality) | +1 improvement |
| Interaction (12) | 9/12 (2 INV-03) | 7/12 (1 INV-03) | -2 quality regressions |

**3 regressions, 3 improvements.** Net neutral on hard invariants, but quality regressions in interaction scenarios.

## The specific regressions and their root causes

### 1. Weather query INV-03 (seed, P0)
**Scenario:** "how is the weather today?" against library catalog memories.
**What happens:** Set-level gate passes via condition 2 (`best_lex=1, best_vec=766`). The catalog sync source_hit gets injected instead of the weather-related decision.
**Data from verbose mode:** `best_lex=1` comes from the word "weather" matching a decision about weather forecasts (IDF=1 in small corpus). `best_vec=766` is the vector similarity. Condition 2 (`vec >= 750 AND lex >= 1`) fires.
**Root cause:** Condition 2's `set_lexical_low=1` is too permissive — "weather" (IDF=1) is a legitimate match but the WRONG candidate (catalog sync source_hit with lex=1, vec=766) gets injected via per-candidate check (lex=1 >= candidate_lexical_floor=1).
**Tension:** Raising `set_lexical_low` to 2 fixes this but breaks cross-container scenarios where `best_lex=1, best_vec=790+` is the only passing path for legitimate queries.

### 2. Resumed session (interaction, quality)
**Scenario:** "Let's pick up where I left off" with `turn_kind=resumed_session`.
**Data:** `best_lex=1, best_vec=0, has_hv=True`. No condition passes.
**Root cause:** Set-level gate blocks because `best_lex=1 < 2` (condition 1 fails) and `best_vec=0` (conditions 2-3 fail). The old QPP had Gate 2 which allowed injection based on work signals + high-value types regardless of lexical score.

### 3. Decision revision (interaction, quality)
**Scenario:** "How are we handling sessions?" — should inject revised sessions decision.
**Data:** `best_lex=1, best_vec=619, has_hv=True`. No condition passes.
**Root cause:** Same as #2 — single-token query with `best_lex=1` can't pass condition 1.

## What was tried and didn't work

1. **Condition 4 (type-aware set-level):** `has_high_value_memory AND best_lex >= 1` — fixed #2 and #3 but caused 2 NEW cross-container INV-03 regressions because off-topic decisions in cross-container sets also have `lex=1 + high_value=True`.
2. **Condition 4 with support_grade:** `has_supported_high_value AND best_lex >= 1` — same regressions because off-topic cross-container decisions have `support_grade="supported"` (they're well-formed, just off-topic).
3. **Tightening condition 2 to `set_lexical_low=2`:** Fixed weather INV-03 but broke 3 cross-container scenarios that relied on `lex=1 + vec >= 750`.
4. **Content word overlap check (stopwords):** Worked for INV-03 but violated the cue-free control plane principle — added English-specific language cues back into production code.

## The fundamental tension

`best_lexical=1` is the same score for both:
- "today" matching a date reference (false signal)
- "sessions" matching a real topic (true signal)

No threshold, type check, or support grade can distinguish them because the IDF signal is identical. The old QPP used composite normalized scores that encoded more context, but at the cost of the 4-gate complexity we simplified away.

## What to do next — data-driven investigation

### Step 1: Get actual data for all 3 regressions

Run with verbose mode enabled:
```bash
PALLIUM_INJECTION_VERBOSE=1 python -m evals.generated_exploratory.invariant_runner --composite-retrieval --workers 1 --cache-dir .local/llm-cache 2>&1 | tee injection-debug.log
```

This logs every injection decision with: candidate count, best scores, per-candidate scores with types and retrieval_source, which conditions fired, which candidates were eligible.

For the weather query specifically, the key questions are:
1. What is the weather-related decision's `lexical_score`, `vector_score`, `retrieval_source`?
2. What is the catalog sync source_hit's scores and `retrieval_source`?
3. If the per-candidate type-aware check blocks the source_hit (lex=0 for catalog sync), does the weather decision get injected instead?
4. Or does the source_hit have lex >= 1 too (matching on a shared word)?

### Step 2: Consider `retrieval_source` as the discriminating signal

The one signal we haven't tried at the per-candidate level: `retrieval_source` on `QueryResultItem`. In composite mode:
- `"both"` = appeared in lexical AND vector search (confirmed word overlap)
- `"vector"` = vector only (semantic similarity, no word overlap)
- `"lexical"` = lexical only (word overlap confirmed)

For the weather scenario: the catalog sync source_hit is likely `retrieval_source="vector"` (no shared words). The weather decision is likely `retrieval_source="both"` (shares "weather"). The per-candidate check could use this: source_hits with `retrieval_source="vector"` require `vec >= 800` instead of `lex >= 1`.

### Step 3: Design and validate fix with data

Once you have the actual scores from Step 1, you can make an informed decision about thresholds or conditions. The verbose mode gives you everything needed.

## Key files

- `semantic/agent_conversation_memory_routing_injection.py` — the injection check with verbose mode
- `semantic/agent_conversation_memory_routing_suppression.py` — unified suppression rules
- `semantic/agent_conversation_memory_routing_scoring.py` — scoring formula + components
- `semantic/agent_conversation_memory_routing.py` — orchestrator
- `semantic/agent_conversation_memory_routing_annotations.py` — cross-candidate pre-computation
- `semantic/agent_conversation_memory_routing_floor.py` — relevance floor
- `docs/specs/2026-04-04-routing-simplification-design.md` — the design spec
- `docs/plans/2026-04-04-routing-simplification.md` — the implementation plan

## How to run regression

```bash
# Unit tests
python -m pytest tests/ -x -q

# Seed invariants (composite mode = production)
python -m evals.generated_exploratory.invariant_runner --composite-retrieval --workers 4 --cache-dir .local/llm-cache

# Cross-container scenarios
python -m evals.generated_exploratory.invariant_runner --composite-retrieval --workers 4 --cache-dir .local/llm-cache --scenario-file evals/generated_exploratory/scenarios/cross_container_public_batch.json

# Interaction sequences
python -m evals.generated_exploratory.invariant_runner --composite-retrieval --workers 4 --cache-dir .local/llm-cache --scenario-file evals/generated_exploratory/scenarios/interaction_sequences.json

# With verbose injection debug:
PALLIUM_INJECTION_VERBOSE=1 python -m evals.generated_exploratory.invariant_runner --composite-retrieval --workers 1 --cache-dir .local/llm-cache 2>&1 | tee injection-debug.log
```

## Original code baseline (for comparison)

Captured by checking out `ee0716f` (last pre-simplification commit) and running the same eval suites. Results documented above.
