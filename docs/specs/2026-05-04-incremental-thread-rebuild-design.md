# Incremental Thread Rebuild

## Problem

Thread rebuild currently loads ALL items in a thread and truncates to the first 4000
characters. Live data shows:

- 71% of threads (41/58) exceed the 4000 char budget
- The largest threads lose 91-100% of their content to truncation
- Truncation is head-biased (takes oldest messages), so new content that triggered
  the rebuild is invisible to the LLM
- Thread summaries describe only the thread opener, not the actual thread evolution
- Thread-level investigation/decision extraction cannot ground findings from truncated
  messages (exact-quote validation fails on unseen text)

## Data-Driven Context

Analysis of live production data (1525 source items, 58 threads, 105 rebuilds):

| Metric | Value |
|--------|-------|
| Median thread size (oversized) | 20,006 chars |
| Max thread size | 150,707 chars |
| Threads exceeding budget | 71% |
| Rebuilds per thread (median) | 7 |
| Items per rebuild (median) | ~8 |
| Delta between rebuilds (p50) | 5,992 chars |
| Delta between rebuilds (p90) | 22,046 chars |
| Delta between rebuilds (max) | 28,683 chars |
| Investigations in truncated tail | 91-100% |

## Design

### Core Mechanism: Watermark + Chaining

Each rebuild processes a bounded window of items starting from a watermark position:

1. Load items from watermark (exclusive) to latest, ordered chronologically
2. If total content exceeds budget (16K chars), take as many items as fit
3. Process window with prior summary as context
4. Update watermark to last processed item
5. If unprocessed items remain, queue another rebuild immediately

This ensures:
- Every message goes through exactly one rebuild window (no gaps, no duplicates)
- Budget stays bounded (predictable cost and extraction precision)
- Long threads chain multiple rebuilds until caught up
- Natural conversation chunks are processed together

### Window Budget: 16K chars

Rationale:
- Covers p90 of observed deltas in a single pass
- Most rebuilds complete in 1 pass (2-10 items, typically 2-10K chars)
- Keeps the window focused enough for precise extraction (avoids noise from
  too much context causing false positives)
- Cost: ~$1.5/1500 items at Sonnet pricing — well within savings from Haiku switch

### Context Input

Each rebuild window receives:
- **Prior thread summary text** (~200-500 chars) — provides thread-wide context
  without re-reading old content
- **Carried conclusions** — existing decisions/investigations from prior windows
  (reference only, not for re-extraction)
- **New items** — the actual window content for extraction

The prompt must explicitly instruct the LLM: "The prior summary is context only.
Decisions and investigations must be exact quotes from the NEW thread items only.
Do not quote from the prior summary."

### Watermark Storage

Store watermark per (container_ref, thread_ref, use_case) using the existing
`collection_watermark_at` field on `ThreadProcessingScope`.

This mechanism already exists for container-scope incremental processing. Extending
it to thread scopes is the natural path — no new storage schema needed.

The watermark value is the timestamp of the last processed source item in the window.
On the next rebuild, items are loaded with `occurred_at > watermark`.

### Supersession Rules

| Memory type | Supersession | Rationale |
|---|---|---|
| `thread_summary` | Yes, one active | Rolling narrative of thread state |
| `task_checkpoint` | Yes, one active | Current work state |
| `decision` (thread-level) | No, accumulate | Each window has different decisions |
| `investigation_outcome` (thread-level) | No, accumulate | Each window has different findings |

Implementation: add a `non_superseding_types` property to `ThreadAggregationSemanticPlugin`
returning a `frozenset[str]` of memory types that should accumulate rather than supersede.
The supersession logic in `core/thread_rebuild.py` reads this from the plugin without
knowing semantic type names — preserving the core/semantic boundary.

### Chain Depth Cap

The existing `_MAX_THREAD_REBUILD_ITERATIONS = 5` is insufficient for catch-up on
large threads. A 150K thread at 16K budget needs ~10 windows. Raise to 15 or make
configurable per plugin. The cap prevents runaway loops but must accommodate the
observed max thread size.

### First Rebuild (No Prior Summary)

When no prior summary exists (new thread), the first window processes from the
beginning. If the thread already exceeds budget at first rebuild, it chains.
Prior summary context is empty string for the first window.

### Migration (Existing Threads)

Existing threads have no watermark. On first rebuild after this change:
- No watermark found → treat as "process from beginning"
- If thread exceeds budget, chain rebuilds until caught up
- After catch-up, watermark is current and incremental flow takes over

### Prompt Changes

The thread summary prompt needs an update to handle incremental mode:

**Current**: "Summarize the following thread items..."
**New**: "Here is a prior summary of earlier discussion: {prior_summary}.
Summarize the following NEW thread items, producing an updated summary that
incorporates both the prior context and new developments..."

Additional instruction for decisions/investigations: "The prior summary is context
only. decision_text, investigation_text, and evidence must be EXACT QUOTES from the
NEW thread items below. Do not quote from the prior summary."

Bump `THREAD_SUMMARY_PROMPT_SCHEMA_VERSION` from v7 to v8 (and merged schema
correspondingly) for provenance tracking.

### Scope: `conversational_knowledge` Package

The `conversational_knowledge` package also uses the thread rebuild mechanism.
The watermark is scoped by `use_case` in the scope key, so each package has an
independent watermark for the same `(container_ref, thread_ref)`. The two packages
do not interfere. The budget and chaining behavior apply to both, but each package's
`non_superseding_types` can differ.

## Implementation Phases

All phases are part of this work item. Phases represent implementation order,
not decision gates.

### Phase 1: Tail-biased truncation + budget increase

Immediate fix to stop the bleeding while Phase 2 is implemented:
- Change `THREAD_SUMMARY_MAX_TEXT_CHARS` from 4000 to 16000
- Flip truncation to tail-biased (most recent N chars)
- This alone fixes most "investigations in truncated tail" for threads under 16K

### Phase 2: Watermark and incremental windowing

The full design:
- Extend `collection_watermark_at` to thread scopes
- In `_maybe_rebuild_thread_summary`: load items after watermark, apply budget,
  chain if items remain
- Add `prior_summary: str | None` field to `ThreadAggregate`
- Thread prior summary into prompt
- Add `non_superseding_types()` plugin method, update supersession logic in core
- Update prompt with explicit "quote from new items only" instruction
- Bump prompt schema version to v8
- Raise `_MAX_THREAD_REBUILD_ITERATIONS` to 15

### Phase 3: Validation

- Run full test suite
- Run exploratory QA invariant runner
- Targeted tests for the new behavior (see Verification section)
- Confirm decisions/investigations extracted from thread tails in live data

## Non-Goals

- Hierarchical summarization (summarize summaries) — the rolling single summary
  with incremental updates is simpler and sufficient
- Signal-guided item selection — data shows 94% of items have signals, so filtering
  by signal doesn't meaningfully reduce volume
- Variable budget per window — fixed 16K is simple and covers the observed distribution

## Files to Modify

| File | Change |
|------|--------|
| `semantic/agent_conversation_memory_threads.py` | Budget constant, tail-biased truncation, window building, prompt update, schema version bump |
| `core/thread_rebuild.py` | Watermark tracking, item windowing, chain triggering, supersession exemption via plugin method, raise chain cap |
| `capabilities/thread_aggregation.py` | Add `prior_summary` to `ThreadAggregate`, add `non_superseding_types` to plugin interface |

## Risks

- **Chained rebuilds under load**: A thread catching up from 0 could trigger many
  sequential rebuilds. Mitigated by cap at 15 iterations.
- **Summary drift**: Rolling summarization may lose early detail over many windows.
  Acceptable — early content is captured by per-item extraction; the summary serves
  routing and retrieval context, not archival.
- **Grounding across windows**: A finding stated across two messages that land in
  different windows will fail grounding in both windows and be silently dropped.
  This is an accepted loss — per-item extraction is the safety net for single-message
  findings, and cross-message findings that truly span a window boundary are rare
  (most findings are self-contained in one assistant message).

## Verification

| Test | What it verifies |
|------|-----------------|
| Key finding in thread tail is extracted | Phase 1 tail-biased fix works |
| Watermark persists across rebuilds, survives mid-chain failure | Watermark correctness |
| Two successive window rebuilds produce two active decisions | Supersession exemption works |
| Chain cap handles max observed thread size (150K) | Cap is sufficient |
| `conversational_knowledge` watermark independent of `agent_conversation_memory` | Package isolation |
| Prompt schema version in provenance payloads | Provenance tracking |
| Finding spanning window boundary is cleanly dropped (not hallucinated) | Grounding safety |
