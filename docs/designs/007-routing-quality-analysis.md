# Routing Quality Analysis and Fix Direction

## Executive Summary

Benchmark testing with realistic query variants (paraphrased, noisy, LongMemEval) exposed that Pallium's routing layer produces harmful wrong-memory injections at 23-55% rate depending on query difficulty. The original benchmarks (clean domain-term queries, 3-6 events) masked this with 91-100% pass rates.

**Wrong memory is worse than no memory.** Pallium is a sidecar — if it injects nothing, the consuming agent lacks context but is safe. If it injects the WRONG memory, the agent makes decisions based on incorrect information. That is actively harmful.

---

## The Problem: Benchmark Results

### Original benchmarks (clean queries, 3-6 events) — FALSE CONFIDENCE

| Benchmark | Pass rate | Intent accuracy |
|---|---|---|
| Memory Routing (11 scenarios) | 91% | 100% |
| Work Resumption (13 scenarios) | "11/13 memory wins" | 100% |

### Paraphrased queries (same scenarios, casual phrasing) — REAL PERFORMANCE

| Benchmark | Pass rate | Intent accuracy | WRONG_MEMORY |
|---|---|---|---|
| Memory Routing | **45%** | **45%** | **6/11** |
| Work Resumption | **8%** | **69%** | **7/13** |

### Noisy conversations (25-30 events, distractors) — FURTHER DEGRADATION

| Benchmark | Pass rate | Intent accuracy | EXTRACTION_FAILURE |
|---|---|---|---|
| Memory Routing (5 scenarios) | **40%** | 60% | **3/5** |
| Work Resumption (5 scenarios) | **0%** | 100% | — |

### LongMemEval (46 real chat scenarios — temporal, multi-session, abstention)

| Metric | Value |
|---|---|
| scenarios_total | 46 |
| intent_matches | 27/46 (59%) |
| top_layer_matches | **15/46 (33%)** |
| answer_successes | 32/46 (70%) |
| policy_successes | **13/46 (28%)** |
| memory_backed_wins | 37/46 (80%) |
| false_merge | 0 |

**The system FINDS memory (80% memory-backed wins) but ROUTES it wrong (33% layer match). Retrieval works. Routing is the bottleneck.**

---

## Why Original Benchmarks Were Misleading

1. **Queries use exact domain terms** — "What did we conclude about the duplicate holds issue?" has direct token overlap with the stored memory. Real users say "what was the deal with that queue thing?"

2. **Conversations are too short** — 3-6 messages per scenario. Real conversations have 20-200+ messages with noise, tangents, and topic switches.

3. **Single topic per container** — No distractor memories from different topics competing for retrieval.

4. **Success criteria are too generous** — "Memory backed win" counts when ANYTHING is injected. It doesn't check whether the RIGHT thing was injected with the RIGHT content.

5. **No temporal distance** — Everything is same-session. No "what did we decide last week?" patterns.

6. **No abstention testing** — Only 2 no-value scenarios across all benchmarks. Real queries often have no memory-backed answer.

---

## Root Cause: The Pipeline Failure Cascade

Pallium's query pipeline:

```
1. RETRIEVAL     → lexical + vector search → candidate set
2. INTENT        → _classify_query_intent_from_text() → intent family
3. SCORING       → _score_routed_candidate() → per-candidate routing score
4. LAYER SELECT  → which memory layer/type wins the competition
5. SUPPORT GATE  → is the routing score high enough to inject?
6. PACKAGING     → build the injectable block for the consuming agent
```

**Stage 2 (INTENT) is the control plane.** When it's wrong, everything downstream is wrong — because Stage 3 selects layer weights based on intent, Stage 4 uses those weights to pick the winner, and Stage 5 trusts the result.

### How intent classification works (and fails)

`_classify_query_intent_from_text()` at line 902 of `semantic/agent_conversation_memory_routing.py`:

1. Check against cue phrase lists (`BROAD_RECALL_CUES`, `EVIDENCE_TRACE_CUES`, `WORK_RESUMPTION_CUES`, etc.)
2. If no cue matches → fall through to prefix defaults
3. Line 920: `lowered.startswith(("what ", "which ", "when "))` → return `"precise_fact"`
4. Line 922: default fallback → return `"broad_recall"`

When a paraphrased query like "What's the standing answer on notice batching?" doesn't match any cue phrase, it falls to the "what " prefix default → `precise_fact`. But it should be `answer_continuity`. The wrong intent → wrong layer weights → wrong memory selected → wrong injection.

### The synthetic cue inflation problem

`_matched_query_family_cues()` at line 924 appends synthetic `"wh*"` token for any "what/which/when" prefix. `_query_family_cue_score()` at line 967 treats this synthetic match as worth 52 points — the same as a real cue match. This inflated score drives wrong family selection in the family competition.

---

## Failure Type Classification (from benchmark_failure_analyzer.py)

### Type 1: WRONG_MEMORY (the harmful failure)
- Memory was injected but from wrong topic/type/layer
- **Root**: Intent misclassification → wrong layer weights → wrong candidate wins
- **Where it breaks**: Stage 2 → cascades through 3-4-5
- **Frequency**: 6/11 in paraphrased routing, 7/13 in paraphrased work resumption
- **Severity**: HIGH — actively harmful, agent acts on wrong information

### Type 2: MISSING_MEMORY (the safe failure)
- Memory should have been injected but wasn't
- **Root**: Support threshold too strict for compact memory types (task_checkpoint, thread_summary have lower evidence_shape_score than decisions)
- **Where it breaks**: Stage 5 (support gate)
- **Frequency**: 3-8 per variant in work resumption
- **Severity**: LOW — agent lacks context but is safe

### Type 3: EXTRACTION_FAILURE (write-path problem)
- Memory was never properly formed from source events
- **Root**: LLM extraction fails when conversation has 25+ messages with noise/distractors
- **Where it breaks**: Stage 0 (write path, before query pipeline)
- **Frequency**: 3/5 in noisy routing
- **Severity**: MEDIUM — memory doesn't exist, so can't be injected (safe miss, but systematic)

### Type 4: ABSTENTION_FAILURE (over-injection)
- System injected memory when it should have abstained
- **Root**: No general confidence/ambiguity gate before injection. `should_inject = bool(blocks)` at line 2993 — purely boolean, no margin check
- **Where it breaks**: Stage 5
- **Frequency**: 2 constant across all variants
- **Severity**: HIGH — injecting when answer isn't in memory is misleading

---

## External Research: What Other Systems Do

Surveyed LangGraph, Mem0, Zep/Graphiti, Letta. Key finding:

**No production system uses phrase-based intent routing as the control plane.**

| System | Approach |
|---|---|
| LangGraph | namespace filter → semantic search → inject. No intent classifier. |
| Mem0 | embedding → vector search → filter → rerank. No phrase lists. |
| Zep/Graphiti | entity+fact graph → graph traversal. Structure, not phrasing. |
| Letta | memory blocks (always visible) + archival (vector search). No routing. |

**The pattern**: Strong systems reduce the candidate space structurally so routing becomes trivial. They push complexity into write-time typing, namespaces, and store design. Query-time stays simple.

**Pallium does the opposite**: wide candidate set → complex routing → fragile classification.

---

## What Pallium Already Has (Structural Primitives)

Pallium is not starting from zero. It already has structural signals that are underused:

- **Scope/visibility filtering** — already narrows by container + visibility
- **Memory kind/type** — 7 distinct types, each with known retrieval characteristics
- **Workstream/subject anchors** — `container_ref`, `thread_ref`, subject-level metadata
- **Constraint lane separation** — constraint_memory has its own routing path
- **Same-thread context signals** — `turn_kind`, `session_has_sufficient_local_context`
- **Evidence shape** — decisions have rich evidence, summaries are compact

The problem is: these signals are consulted AFTER intent selects the weights. Intent should come AFTER structure narrows the candidates.

---

## Fix Direction: Three Horizons

### Horizon 1: Safety Patch (NOW — the approved plan)

**Goal**: Reduce harmful wrong injections immediately without deepening commitment to phrase-based routing.

Two mechanisms:
1. **Intent confidence flag** — detect when intent was a guess (synthetic prefix cue only, no real cue match). When low-confidence: require `support_grade="strong"` for injection, or a healthy candidate margin. Otherwise abstain.
2. **Candidate margin gate** — when top-1 barely beats top-2 from a different layer, abstain. Converts uncertain injections from WRONG_MEMORY (harmful) to MISSING_MEMORY (safe).

**Expected outcome**: wrong_memory_rate drops from 0.55 to <0.20 on paraphrased queries. missing_memory_rate may increase (accepted — safe failure mode).

### Horizon 2: Structural Lane Narrowing (NEXT FEATURE — on roadmap)

**Goal**: Demote intent from "switchboard" to "hint" by using structural signals to narrow eligible lanes BEFORE intent/weight-based scoring runs.

Proposed flow:
```
BEFORE (current):
  RETRIEVAL → INTENT(phrases) → SCORING(intent-selected weights) → LAYER → INJECT

AFTER:
  RETRIEVAL → LANE ELIGIBILITY(structure) → SCORING(lane-aware weights) → INTENT(hint) → INJECT
```

Lane eligibility uses existing structural signals:
- If `turn_kind="new_thread"` + recent `task_checkpoint` exists → work_resumption lane eligible
- If `decision` memory retrieved → factual recall lane eligible
- If `pattern_memory` retrieved → broad recall lane eligible
- If only `source_evidence` → evidence trace lane
- If no strong candidates → abstain lane

If only ONE lane is eligible, intent doesn't matter — that lane wins. If multiple lanes are eligible, intent acts as a tiebreaker (hint), not as the primary selector.

### Horizon 3: Entity-Anchored Routing (LATER)

Add explicit entity/subject extraction at write time. Route queries by entity match first, then by memory type. This is the pattern Zep/Graphiti use — but requires significant write-path changes.

---

## Key Code Locations

| Component | File | Lines | What it does |
|---|---|---|---|
| Intent classification | `semantic/agent_conversation_memory_routing.py` | 902-922 | Phrase-matching → intent family |
| Cue lists | same file | 197-299 | `BROAD_RECALL_CUES`, `PRECISE_FACT_CUES`, etc. |
| Synthetic cue scoring | same file | 967 | `wh*` token gets 52 points (should be ~18) |
| Family competition | same file | 829-900 | `_infer_query_intent()` — scores families, selects winner |
| Candidate scoring | same file | 1483-1550 | `_score_routed_candidate()` — layer_weight[intent][layer] + score*10 + bonuses |
| Support grading | same file | 4034-4040 | `_routing_support_grade()` — global threshold, not per-type |
| Support threshold | same file | 150 | `ROUTING_SUPPORT_THRESHOLD = {"weak": 0, "supported": 60, "strong": 110}` |
| Injection decision | same file | 2993 | `should_inject = bool(blocks)` — no margin check |
| Layer weights | same file | 84-91 | `ROUTING_LAYER_WEIGHTS[intent][layer]` — 6 intent families × 7+ layers |
| Fallback margin | same file | 175 | `ROUTING_FALLBACK_MARGIN = 35` |

---

## Benchmark Assets Available

| Scenario set | File | Count | Difficulty |
|---|---|---|---|
| Memory routing (original) | `evals/memory_routing/scenarios.json` | 11 | Easy (clean queries) |
| Memory routing (paraphrased) | `evals/memory_routing/scenarios_paraphrased.json` | 11 | Medium (casual phrasing) |
| Memory routing (noisy) | `evals/memory_routing/scenarios_noisy.json` | 5 | Hard (25+ events, distractors) |
| Work resumption (original) | `evals/work_resumption/scenarios.json` | 13 | Easy |
| Work resumption (paraphrased) | `evals/work_resumption/scenarios_paraphrased.json` | 13 | Medium |
| Work resumption (noisy) | `evals/work_resumption/scenarios_noisy.json` | 5 | Hard |
| LongMemEval (extended) | `evals/memory_routing/scenarios_longmemeval.json` | 46 | Hard (real chat histories) |
| Failure analyzer | `tools/benchmark_failure_analyzer.py` | — | Classifies failures by 6-type taxonomy |

---

## Existing Benchmark Results (Baseline for Comparison)

### Memory Routing

| Variant | Pass | WRONG_MEMORY | MISSING | EXTRACTION | Intent accuracy | recall@1 |
|---|---|---|---|---|---|---|
| Original | 91% | 1 | 0 | 0 | 100% | 1.00 |
| Fusion (RRF) | 100% | 0 | 0 | 0 | 100% | 1.00 |
| Paraphrased | **45%** | **6** | 0 | 0 | **45%** | 0.71 |
| Noisy | **40%** | 0 | 0 | **3** | 60% | 1.00 |
| LongMemEval | **28%** | — | — | — | **59%** | — |

### Work Resumption

| Variant | Pass | WRONG_MEMORY | MISSING | ABSTENTION | Intent accuracy |
|---|---|---|---|---|---|
| Original | 0% | 3 | **8** | 2 | 100% |
| Fusion (RRF) | 8% | 4 | **6** | 2 | 100% |
| Paraphrased | 8% | **7** | 3 | 2 | **69%** |
| Noisy | 0% | 1 | **4** | 0 | 100% |

### What works well (confirmed robust)
- **false_merge = 0** across ALL variants — no cross-topic contamination at result level
- **Retrieval recall@5 = 1.00** in almost all cases — correct memory IS in the candidate set
- **Inject decision (should_inject)** = correct in 100% of original scenarios
- **Vector fusion** genuinely helps retrieval (2 recall fixes in work resumption)

### What's broken
- **Intent classification** drops to 45-69% with paraphrasing
- **Layer selection** drops to 33-40% in noisy/LongMemEval scenarios
- **Wrong-memory injection** at 23-55% rate is actively harmful
- **Support threshold** is one-size-fits-all, penalizes compact memory types

---

## Severity Ordering (for Pallium as sidecar)

```
WRONG_MEMORY (harmful) > STALE_MEMORY > ABSTENTION(over_inject) >> MISSING_MEMORY (safe) > ABSTENTION(false_abstain)
```

**Priority**: Reduce wrong injections FIRST. Accept higher missing rate as the safe tradeoff. Only then recover recall.
