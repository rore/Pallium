# Session Memory QA — agent_work_trace design session

**Session thread:** `67d247fd-0a38-4850-9390-2837547312e8`  
**Date:** 2026-05-05  
**Purpose:** Document QA findings so we can act on them without re-reading the full session

---

## Thread Rebuild — Actual State (corrected)

Rebuild fired **6 times**, not zero. All task_checkpoints and thread_summaries supersede correctly:

```
11:29:20  → task_checkpoint (superseded), thread_summary (superseded), 2 decisions
11:47:04  → task_checkpoint (superseded), thread_summary (superseded), 2 decisions, 3 investigation_outcomes
12:02:59  → task_checkpoint (superseded), thread_summary (superseded), 6 decisions
12:05:15  → task_checkpoint (superseded), thread_summary (superseded), 7 decisions
12:20:06  → task_checkpoint (superseded), thread_summary (superseded), 7 decisions
13:00:10  → task_checkpoint (ACTIVE), thread_summary (ACTIVE), 7 decisions
```

Total source items in thread: 68  
Lease watermark after last rebuild: `2026-05-05 12:59:56`  
Items after watermark (not yet rebuilt): 2 (the "findings file" assistant response + this message)

---

## Good Extractions (keep, no action needed)

| ID | Type | Summary |
|----|------|---------|
| `488110c3-89b8-4d3b-9a70-4e65f0a89d31` | investigation_outcome | "The gap in Pallium is not retrieval quality, it's typed capture of agent work." Accurate and valuable cross-session. |
| `43493a81-fd98-497a-ace8-ec3c5ae7ed65` | investigation_outcome | "Cognee has raw tool call log in keyword-searchable cache, async graph on top." Factual, well-scoped. |
| `a6bf4136-ee0d-4095-9254-a0b3eedcce34` | task_checkpoint | **SUPERSEDED** — the 13:00 rebuild replaced it. |

The active task_checkpoint is now `a6bf4136`'s replacement (created 13:00:10, same ID query needed):

```sql
SELECT id FROM memory_objects WHERE type='task_checkpoint' AND lifecycle='active' 
AND created_at >= '2026-05-05 13:00:00'
```

---

## Bug 1: Decisions never supersede (confirmed, systematic)

**What's happening:** Every rebuild emits 7 decision objects. Old ones are never marked superseded. After 6 rebuilds we have **42 active decision objects** — 6 batches of 7, all near-identical.

**Contrast:** `task_checkpoint` and `thread_summary` supersede cleanly. Only `decision` objects accumulate.

**Decision batches (by rebuild timestamp):**

| Rebuild | Decision IDs (7 each) | Lifecycle |
|---------|----------------------|-----------|
| 11:29:20 | `...` | active (should be superseded) |
| 11:47:04 | `...` | active (should be superseded) |
| 12:02:59 | `...` | active (should be superseded) |
| 12:05:15 | `...` | active (should be superseded) |
| 12:20:06 | `8cff31a3`, `1832eb3a`, `2a3ab78f`, `4b6eed2e`, `0369dbdd`, `274b9189`, `dc219b76` | active (should be superseded) |
| 13:00:10 | 7 new IDs | active (CORRECT — keep these) |

**IDs flagged (done):** all 44 objects from the pre-13:00 batches have been manually flagged.

**Root cause (confirmed):** Two separate mechanisms exist for supersession:

1. **Thread rebuild supersession** (`thread_rebuild.py:511-523`) — builds a `supersede_plan` by `(type, schema_id)` pairs. `task_checkpoint` and `thread_summary` use this path, which is why they supersede correctly.

2. **Per-item supersession** (`build_supersession_hints` in `agent_conversation_memory_memory.py:289-312`) — uses `canonical_key` matching. Called only from `process_item()`, never from thread rebuild.

`decision` and `investigation_outcome` are in `non_superseding_types` (`agent_conversation_memory.py:58-59`):

```python
@property
def non_superseding_types(self) -> frozenset[str]:
    return frozenset({"decision", "investigation_outcome"})
```

This exempts them from the rebuild supersession plan (`supersede_plan[id] = []`). The design intent was that they use per-item `SupersessionHint` instead. But `build_supersession_hints()` is only called in `process_item()` — it never runs at thread rebuild time. Decisions produced by thread rebuild have **no supersession path**. Every rebuild emits a new batch that supersedes nothing.

**Fix direction:** Either remove `decision`/`investigation_outcome` from `non_superseding_types` so the rebuild supersession plan covers them by `(type, schema_id)`, or add a thread-rebuild-level canonical_key supersession pass for these types after `build_thread_summary` produces them.

---

## Bug 2: task_checkpoint doesn't converge on resolution

**What's happening:** The 13:00 rebuild saw all 68 items including the spec-completion turns, but its `summary` still says:
> "Pallium single-package design requires resolution of summary injection strategy, item reconstruction"

The spec is finished. Blockers are resolved. The checkpoint should reflect that.

**Root cause (confirmed):** The context fed to the checkpoint LLM (`agent_conversation_memory_threads.py:805-823`) is:
1. **Thread summary** (dominant signal) — pre-built from the full thread
2. Carried conclusions (decisions/investigation_outcomes)
3. Last 6 selected work artifacts

The thread summary is the dominant input, and it reflects the thread's dominant theme — ~50 items of "design uncertainty." It said "requires resolution" and that got baked in. The incremental rebuild carries forward the prior summary; once "requires resolution" is in the summary, it persists until a rebuild explicitly overwrites it. The 3-4 completion items are too small relative to 68 items to flip the thread summary's conclusion.

The last-6 work artifacts path (`_collect_selected_work_artifacts`, lines 1539-1551) is recency-favoring, but only has 3200 chars total budget and the thread summary with its "uncertainty" framing dominates it.

**Consequence:** A new session resuming this thread gets injected with a "blockers open" checkpoint that is factually wrong.

**Fix directions:**
- Prompt change: "what is the CURRENT state? Focus on the most recent items. If recent items indicate resolution, reflect that — override the earlier thread state."
- Feed most-recent N items explicitly as a "recent context" block before the thread summary in the prompt preamble
- Increase weight of `selected_work_artifacts` relative to thread summary in checkpoint context

---

## Bug 3 (already flagged): Inaccurate investigation_outcome from QA analysis

**ID:** `e4d9d97e-9a48-42c4-b1c1-c896d97e3705`  
**Flagged:** Yes (2026-05-05)

The investigation_outcome extracted my own erroneous QA diagnosis: "thread rebuild fired early and never re-fired." This is false — rebuild fired 6 times. The object was extracted from my QA analysis message (which contained speculative reasoning that turned out to be wrong). The extraction treated my diagnostic prose as a verified investigation outcome.

**Root cause (confirmed):** The investigation_outcome extraction prompt has no instruction to reject speculative, hedged, or hypothetical language. Phrases like "this could mean...", "I suspect...", "likely because..." are extracted the same as confirmed findings. No linguistic gate separates investigation vs. conclusion.

---

## Missing Decisions — Still Not Extracted

Even the 13:00 rebuild didn't capture these. They are in the session but not promoted to individual memory objects:

| Decision | Status |
|----------|--------|
| Spec finalized at `docs/specs/2026-05-05-agent-work-trace-design.md`, commit `13a1dba` | Not extracted |
| Scoped injection: task_trace only on session resume (`source="resume"`), not all SessionStart | Not extracted |
| `turn_source_item_ids` for query-time correlation (not extraction-time, avoids parallel race) | In decisions batch as "context correlation based on shared source items" — partial |
| `first_write_action_at_turn` (Edit/Write only, not test commands) | Not extracted |
| Payload caps: exploratory_files:30, productive_files:20, commands:10 each, fragments:5 | Not extracted |
| Path normalization relative to cwd | Not extracted |
| `outcome_source` field ("llm_from_agent_responses" \| "none") | Not extracted |
| Parity test `tests/test_hook_common_parity.py` | Not extracted |
| outcome included in BM25 index (after deliberation, override of initial reviewer suggestion) | Not extracted |

**Root cause:** These are late-session spec-refinement decisions. The task_checkpoint extraction is dominated by the larger earlier discussion. The per-item `decision` extractor also doesn't see these because they appear in my responses as implementation details inside spec update commits, not as explicitly stated decisions in assistant text.

**Action needed:** Ingest these as explicit `note` items (9 items above).

---

## Action Plan

### Step 1: Flag the stale/duplicate memory objects — DONE

Flagged all 44 decision objects from rebuilds before 13:00 (kept only the 7 from the 13:00 batch).  
Flagged `e4d9d97e` (inaccurate investigation_outcome).

### Step 2: Ingest missing decisions as notes — DONE

Ingested all 9 missing decisions as explicit `note` items via `pallium_ingest`.

### Step 3: File bugs

1. **`semantic/agent_conversation_memory.py:58-59` — Decisions don't supersede at thread rebuild**
   - Remove `decision`/`investigation_outcome` from `non_superseding_types`, or add a canonical_key-based supersession pass at thread rebuild time for these types.
   - The `SupersessionHint` mechanism (`build_supersession_hints`) only runs in `process_item()` — it never fires for thread-rebuild-produced decisions.

2. **`semantic/agent_conversation_memory_threads.py:805-823` — task_checkpoint doesn't converge on resolution**
   - Thread summary is the dominant context signal; once it captures "uncertainty," it persists across incremental rebuilds even after the thread resolves.
   - Fix: prompt change asking for CURRENT state from most recent items, or increase weight of the last-N items relative to the carried-forward thread summary.

3. **investigation_outcome extraction prompt — speculative prose extracted as confirmed finding**
   - Add a rejection gate for hedged/speculative language ("could", "suspect", "likely", "might").
   - Only extract findings stated as confirmed conclusions.
