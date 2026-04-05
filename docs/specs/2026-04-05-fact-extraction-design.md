# Fact Extraction Package & Multi-Package Architecture — Design Spec

**Date:** 2026-04-05
**Status:** Draft

---

## Problem

Pallium's `agent_conversation_memory` package extracts high-level memories — decisions, investigation outcomes, thread summaries, patterns. These serve agent continuity well but lose atomic factual details (names, dates, numbers, activities, preferences, relationships). The LoCoMo benchmark (61.2% accuracy) confirms this gap: 53% of failures are memories too abstract to answer specific factual questions.

## Goals

1. **Fact extraction package**: a new semantic package that extracts atomic facts from conversation threads.
2. **Multi-package processing**: all registered packages process every item — remove `use_case` routing.
3. **Routing as core**: extract query routing from the continuity package into a Pallium core responsibility.

## Architecture Decisions

### Packages process in parallel

All semantic packages receive every ingested item. Each package independently decides what to extract (or skip). The `use_case` field on items and `default_use_case` routing are removed. An integrating agent doesn't select a package — it just ingests and queries.

This supersedes the current single-package routing documented in `architecture.md` (line: "current async processing assigns exactly one semantic package (use_case) per source item; this is a deliberate current limitation"). The additive migration path documented there (`(source_item_id, use_case)` per-package tracking table) is the implementation approach — this spec confirms and activates that direction.

### Fact extraction uses the thread rebuild mechanism

A single conversation message often lacks context ("Yeah, I read it last year"). Fact extraction works at thread level — grouping all items in a thread and extracting facts from the group. This uses the existing thread rebuild infrastructure:

1. `process_item()` → lightweight (no per-item extraction), returns `thread_rebuild_requested=True`
2. Thread-level handler → receives all source items in the thread → extracts atomic facts

This runs automatically as part of the normal processing loop — no separate trigger or consolidation pass needed. When a new message arrives in a thread, facts for that thread are re-extracted and supersede the previous set.

### Cost is bounded by the thread rebuild scope mechanism

The thread rebuild scope (`ThreadProcessingLeaseRecord`) uses a `requested_at` / `has_pending` pattern that naturally debounces rapid message arrival. When multiple messages arrive while a rebuild is running, they collapse into a single pending request — the rebuild runs once more after the current one completes, not once per message. `_MAX_THREAD_REBUILD_ITERATIONS = 5` caps total iterations per processing pass.

This means fact extraction gets the same debounce behavior as thread summaries for free. No additional threshold, sweep, or trigger logic is needed. For a 50-message burst conversation, fact extraction runs 2-5 times (not 50). For slow conversations (one message per hour), each message triggers a rebuild — acceptable since the thread isn't growing fast.

The existing `len(thread_items) < 2` guard also means single-message threads skip processing entirely.

### Routing is a Pallium core responsibility

Query routing (intent classification, scoring, injection decisions) moves out of the continuity package into Pallium core. Packages register their memory types with routing at startup:

- Type name and layer name
- Weight hints per query intent (or a default)
- Block formatter (title, which payload field to render as block text)
- Whether the type is high-value for injection gating

Routing reads the type registry generically. It does not import or depend on any specific package.

---

## Part 1: Multi-Package Processing

### What changes

| Component | Current | New |
|---|---|---|
| `SourceItem.use_case` | Set during ingest, routes to one package | Removed from routing; per-package processing tracked separately |
| `AppConfig.default_use_case` | Selects default package | Removed as routing selector |
| Queue claim (`sqlite_queue.py`) | `WHERE use_case IS NOT NULL` | Per-package tracking table keyed by `(source_item_id, package_name)` |
| Processing loop (`processing.py`) | Calls one package's `process_item()` | Calls all packages' `process_item()` |
| Thread rebuild scope (`thread_rebuild.py`) | `use_case` in scope_key | Per-package scope (each package gets its own thread rebuild for the same thread) |
| Consolidation (`consolidation_runner.py`) | Per-package (unchanged) | Per-package (unchanged) |

### Processing tracking

Following the migration approach documented in `architecture.md`: add a per-package processing tracking table keyed by `(source_item_id, package_name)`. When a new item arrives:

1. All registered packages are listed as pending
2. The processing loop claims items and processes them through each pending package
3. As each package completes, it's marked done in the tracking table
4. The item is fully processed when all packages have completed (or skipped)

If a package fails for one item, other packages still process it. The failed package can retry independently.

### Design rule: packages must cheaply self-skip

With all packages receiving every item, fan-out cost is proportional to the number of packages. Each package's `process_item()` must be cheap when the item is irrelevant — a lightweight eligibility check returning an empty `ProcessResult`, no LLM calls. The expensive work (LLM extraction) only happens at thread rebuild level and only for eligible threads. This rule is critical for keeping multi-package processing viable as more packages are added.

### Thread rebuild per package

Each package gets its own thread rebuild scope for the same thread. The scope_key includes the package name so rebuilds are independent:

- Continuity package rebuilds `thread_summary` for that thread
- Fact package extracts `atomic_fact` objects for that thread

Both benefit from the same debounce behavior — rapid messages collapse into bounded rebuild iterations.

---

## Part 2: Fact Extraction Package

### Package identity

- **Name**: `conversational_knowledge` (or similar — open to naming discussion)
- **Responsibility**: extract atomic facts from conversation threads
- **Interface**: `SemanticPlugin` + `ThreadAggregationSemanticPlugin`

### Per-item processing

`process_item()` is lightweight:

- Check eligibility: `role` in ("user", "assistant"), `artifact_kind` in ("message", None). Skip tool outputs, notifications, snapshots.
- If eligible: return `ProcessResult(thread_rebuild_requested=True)` with no memory objects.
- If not eligible: return empty `ProcessResult(thread_rebuild_requested=False)`.

No per-item LLM calls. No per-item memory objects.

### Thread-level extraction

The thread-level handler receives all source items in a thread, ordered by `occurred_at`. It makes one LLM call to extract facts from the full conversation.

**Prompt principles:**
- Extract specific facts: names, dates, numbers, places, activities, preferences, relationships, events
- Skip greetings, filler, emotional reactions, generic encouragement
- Each fact must be independently useful for answering a future question
- Preserve the original language — do not translate
- Include who the fact is about (subject) and when if mentioned

**Schema:**
```json
{
  "facts": [
    {
      "subject": "who or what this fact is about",
      "statement": "the atomic fact, self-contained",
      "category": "personal | event | preference | relationship | activity"
    }
  ]
}
```

**Output:** one `atomic_fact` memory object per extracted fact:

```python
MemoryObject(
    type="atomic_fact",
    schema_id="conversational_knowledge.atomic_fact",
    schema_version="v1",
    payload={
        "subject": "Melanie",
        "statement": "Melanie has 3 children",
        "category": "personal",
    },
    visibility=thread_visibility,
    container_ref=container_ref,
    freshness_at=latest_occurred_at,
)
```

**Indexing** per fact:
- Lexical: the `statement` text
- Vector: embedding of `"{subject}: {statement}"`

**Evidence:** `supported_by` relations to all source items in the thread.

**Supersession:** when the thread is re-processed (new message arrived), the new fact set supersedes all previous `atomic_fact` objects for that `(container_ref, thread_ref)`.

### What the package does NOT do

- No per-item memory extraction
- No cross-thread fact merging or deduplication
- No fact importance scoring or decay
- No relation graph between facts
- No incremental delta extraction (re-extracts full thread each time)

---

## Part 3: Routing as Core

### Type registry

Packages register their memory types at startup. Each registration includes:

```python
TypeRegistration(
    type_name="atomic_fact",
    layer="atomic_fact",
    weight_by_intent={
        "recall": 120,           # below decision (150) and investigation_outcome
        "work_resumption": 60,   # low — facts rarely help with work resumption
        "evidence_trace": 100,   # moderate — facts are evidence
    },
    default_weight=80,
    block_title="Known Fact",
    block_text_field="statement",
    high_value=False,
)
```

The continuity package registers its existing types (decision, investigation_outcome, thread_summary, pattern_memory, continuity_memory, etc.) using the same mechanism — moving the current hardcoded constants into registrations.

### Routing logic stays in core

Intent classification, score computation, injection gating, and block assembly remain as they are — they just read from the type registry instead of hardcoded constants. The routing module does not import any package.

### Migration path

The current routing code in `semantic/agent_conversation_memory_routing*.py` moves to a core module (e.g., `core/routing.py` or `core/query_routing/`). The continuity package no longer implements `route_query_results()` — routing is called by the query executor directly.

This is a refactor of existing code, not new logic. The routing behavior stays the same; only its location and configuration source change.

---

## Language Considerations

- Extraction prompt instructs the LLM to preserve the original language — no translation
- Fact statements stored as-is in the content's language
- Lexical indexing uses raw statement text — no English stopwords or stemming in new code
- Vector embeddings work cross-lingually if a multilingual model is configured (current bge-small-en is a config choice, not an architectural assumption)
- Type registry, routing, and injection logic are language-agnostic

---

## Durable Truth Updates

When this spec is implemented, update these files to reflect the new state:

- `docs/context/architecture.md` — replace the "deliberate current limitation" language with the multi-package reality; update the core entities section; document the type registry and routing-as-core patterns; add the new package to the semantic behavior section
- `docs/context/decisions.md` — add decisions for: multi-package processing, routing as core, fact extraction package
- `roadmap/board.md` — move `idea-multi-package-source-item-processing` from Ideas to Done; add fact extraction package item

---

## Implementation Scope

### New files

| File | Purpose |
|------|---------|
| `semantic/conversational_knowledge.py` | Fact extraction package: process_item, thread-level handler |
| `core/type_registry.py` | Memory type registration and lookup |

### Files to modify

| File | Change |
|------|--------|
| `core/service.py` | Remove use_case routing from ingest; register packages at startup |
| `core/processing.py` | Process items through all packages; per-package tracking |
| `core/query.py` | Call routing from core instead of delegating to package |
| `core/thread_rebuild.py` | Per-package scopes (scope_key keeps package name for independence) |
| `storage/sqlite_queue.py` | Add per-package processing tracking table |
| `semantic/agent_conversation_memory.py` | Register types with type_registry; remove route_query_results |
| `semantic/agent_conversation_memory_routing*.py` | Move to core module; read from type_registry |
| `evals/locomo_benchmark.py` | Ensure both packages are active during benchmark |
| `docs/context/architecture.md` | Update multi-package, routing, and package documentation |
| `docs/context/decisions.md` | Add accepted decisions |
| `roadmap/board.md` | Update roadmap items |

### Files NOT modified

| File | Why |
|------|-----|
| `retrieval/` | Retrieval is already type-agnostic — surfaces any indexed memory object |
| `storage/sqlite.py` | Storage is already generic over memory types |
| `api/routes.py` | No new endpoints |
| `capabilities/consolidation.py` | Consolidation stays per-package, unchanged |

---

## What This Does NOT Include

Extension directions, not planned:

- **Cross-thread fact merging**: same fact in different threads produces separate objects; retrieval surfaces both
- **Fact importance/decay**: no scoring lifecycle; `freshness_at` exists if needed later
- **Relation graph between facts**: no cross-references; multi-hop relies on retrieval
- **Incremental extraction**: re-extracts full thread; no delta tracking
- **Custom routing per package**: packages register type metadata only; no package-specific routing logic
- **Per-fact evidence linking**: facts link to all thread source items, not to the specific turn that stated the fact; acceptable for v1, imprecise long-term

## Known Risks

**Fact-set instability across rebuilds.** Full-thread re-extraction with full supersession means the fact set is only as stable as the LLM's extraction consistency. If extraction run N finds facts A, B, C and run N+1 (one more message added) finds A, B, D because the LLM fluctuated, fact C is silently lost. This is accepted for v1 — LLM extraction is generally stable and the benchmark cache makes eval runs deterministic. If instability is observed in production, the mitigation direction is additive merge (compare new facts against existing, only supersede facts that conflict) rather than full supersession. Mark as a pressure point to monitor.

**Routing refactor regression.** Moving routing from `semantic/agent_conversation_memory_routing*.py` to core is mechanically straightforward but operationally risky — routing is the most heavily tuned and benchmarked subsystem. The existing benchmark suite (memory_routing, work_resumption, recurring_question, etc.) is the regression gate. This step should be implemented and validated independently before the fact extraction package is added, so any regression is attributable to the refactor, not to the new package.

---

## Validation

**LoCoMo benchmark** (`evals/locomo_benchmark.py`): run with both packages active, compare per-category accuracy against 61.2% baseline.

**Expected improvements:** single_hop (78.4% → higher) and multi_hop (43.8% → higher) should improve most. Facts preserve the specific details these categories test.

**Existing benchmarks** (memory_routing, work_resumption, etc.): must not regress. The routing refactor changes code location, not behavior. The continuity package produces the same memory types as before.

## Cost

**LoCoMo:** 19 threads × 1 LLM call = 19 fact extraction calls producing ~175 facts. Adds ~5% to total LLM cost (on top of 419 per-item calls).

**Production:** one extraction call per thread rebuild. The thread rebuild scope mechanism naturally debounces rapid message arrival — multiple messages in flight collapse into bounded rebuild iterations (typically 2-5, capped at `_MAX_THREAD_REBUILD_ITERATIONS = 5`). Cost scales with rebuild frequency, not message count. Thread rebuild already runs for summaries — fact extraction adds one more LLM call to the same trigger.
