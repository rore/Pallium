# Agent Work Trace Package Design

**Date:** 2026-05-05
**Status:** Draft
**Scope:** New parallel semantic package capturing agent discovery work for reuse across sessions

## Overview

Agents doing engineering work repeatedly pay to discover the same things: which files matter, which commands work, where a bug lives. Pallium currently captures what the agent *said* (via `agent_conversation_memory`), but not what it *did* — which files it read, which commands it ran, what exploration path it took.

`agent_work_trace` is a parallel semantic package that captures the structural trail of agent work per turn, aggregates it into a compact `task_trace` memory object per session, and injects it at session start so future sessions — whether a context reset mid-task, a resume next day, or a teammate picking up the same area — can skip the orientation phase and go directly to the relevant location.

**What it does not do:** duplicate findings extraction. `agent_conversation_memory` already extracts decisions and investigation outcomes from the agent's response text. `agent_work_trace` captures the file and command trail; the finding comes from the existing extraction.

---

## Hypothesis and Measurement

**Hypothesis:** injecting a compact task trace at session start reduces the number of exploratory file reads before the agent reaches the correct location.

**Primary metric — re-discovery rate:** fraction of tool calls in a session that duplicate work already in an injected task trace. Specifically: `(Read calls for files in injected task_trace.files_explored) / (total Read calls in session)`.

**Measurement mechanism:**
- Each `task_trace` carries a structured `files_explored` list.
- The SessionStart hook stores the injected file set in session state (temp file alongside the session).
- The Stop hook (or a lightweight companion) compares each turn's tool calls against the stored set and logs matches to a local metrics file.
- Over time: compare re-discovery rate for sessions where a task_trace was injected vs. sessions where none was available.

**Validation threshold:** a meaningful reduction in re-discovery rate across 15+ comparable sessions justifies full productionisation. The experiment can be run within a single repo over a few weeks of normal usage.

---

## SourceItem Extension

Add a new first-class field to `SourceItem`:

```python
tool_use_results: list[ToolUseResult] | None = None
```

```python
@dataclass(frozen=True)
class ToolUseResult:
    tool_name: str           # "Read", "Bash", "Grep", "Glob", "WebFetch"
    tool_input: dict         # raw tool_input from Claude Code / Codex
    output_fragment: str     # truncated output (see truncation rules below)
```

This field is populated by the Stop hook when discovery tool calls are present in the turn. It is `None` for turns with no discovery calls, for pure conversation turns, and for all items ingested outside agent hook context. All existing packages ignore it.

**Truncation rules by tool type:**

| Tool | `output_fragment` content | Limit |
|------|--------------------------|-------|
| `Read` | First 150 chars of file content | 150 chars |
| `Bash` | Last 600 chars of stdout/stderr (where errors and summaries live) | 600 chars |
| `Grep` | Full result | — (compact by nature) |
| `Glob` | Full result | — (compact by nature) |
| `WebFetch` | First 300 chars (title + opening) | 300 chars |

Tools excluded from capture: `Edit`, `Write`, `NotebookEdit`, `TodoWrite`, `Agent`, `Task*`. These represent work output, not discovery input.

---

## Stop Hook Extension

Both `integrations/claude-code/hooks/stop.py` and `integrations/codex/hooks/stop.py` are extended via a shared function in `common.py`.

**New shared function: `extract_tool_use_results(transcript_path, session_id) -> list[ToolUseResult]`**

Implemented once in `integrations/claude-code/hooks/common.py` and copied to `integrations/codex/hooks/common.py` (both are standalone stdlib-only files — no shared import path between integrations).

1. Read the transcript JSONL
2. Locate the current turn boundary (all entries since the last user message)
3. Extract `tool_use` / `tool_result` pairs within that boundary
4. Filter to discovery tool types
5. Apply per-tool truncation
6. Return as `list[ToolUseResult]`

The existing `read_last_assistant_turn()` already handles multi-format transcripts (Claude Code and Codex formats). `extract_tool_use_results()` follows the same format detection logic.

The Stop hook populates `tool_use_results` on the SourceItem before calling `POST /items`. If the function returns an empty list, `tool_use_results` is set to `None` and ingestion proceeds unchanged.

---

## Package: `agent_work_trace`

### Registration

Parallel package (`parallel_processing = True`). Processes every ingested item but returns empty results for items without `tool_use_results`. Registered alongside `agent_conversation_memory` in `pallium.local.toml` and the service plugin registry.

### Item-Level Processing

**Activation condition:** `source_item.tool_use_results` is non-empty.

**Extraction (deterministic — no LLM):**

```python
turn_summary = {
    "files_explored": [
        r.tool_input["file_path"]
        for r in source_item.tool_use_results
        if r.tool_name == "Read"
    ],
    "commands_run": [
        r.tool_input.get("command", "")
        for r in source_item.tool_use_results
        if r.tool_name == "Bash"
    ],
    "search_patterns": [
        r.tool_input.get("pattern", "")
        for r in source_item.tool_use_results
        if r.tool_name in ("Grep", "Glob")
    ],
    "bash_fragments": [
        r.output_fragment
        for r in source_item.tool_use_results
        if r.tool_name == "Bash"
    ],
}
```

**Output:**
- `memory_objects`: empty — no MemoryObject at item level
- `source_item_metadata_updates`: stores `turn_summary` under key `"agent_work_trace_turn"`
- `thread_rebuild_requested`: `True`

### Thread Rebuild

**Input:** `ThreadAggregate` — all SourceItems for the thread, plus `memory_by_type` containing MemoryObjects already created by other packages for this thread.

**Step 1 — Collect turn summaries:**
```python
turns = [
    item.metadata["agent_work_trace_turn"]
    for item in aggregate.items
    if "agent_work_trace_turn" in (item.metadata or {})
]
```
If no turns found, skip rebuild (return empty ProcessResult).

**Step 2 — Deterministic aggregation:**
```python
files_explored = list(dict.fromkeys([f for t in turns for f in t["files_explored"]]))  # order-preserving dedup
commands_run   = list(dict.fromkeys([c for t in turns for c in t["commands_run"]]))
bash_fragments = [f for t in turns for f in t["bash_fragments"] if f]
```

**Step 3 — Collect related findings:**
Cross-reference `aggregate.memory_by_type` for `investigation_outcome` and `decision` objects from `agent_conversation_memory`. Store their IDs as `related_finding_ids`. These are not re-extracted — they are referenced.

**Step 4 — Generate investigation subject (LLM, one call):**
Compact prompt: given `files_explored` and `commands_run`, produce a 3-7 word subject phrase describing what was being worked on. Uses the cheapest available model (Haiku / equivalent). Falls back to the most common directory prefix if LLM unavailable.

**Step 5 — Produce `task_trace` MemoryObject:**

```python
MemoryObject(
    type="task_trace",
    schema_id="agent_work_trace.task_trace",
    schema_version="v1",
    lifecycle="active",
    visibility=source_item.visibility,
    container_ref=aggregate.container_ref,
    actor_ref=aggregate.actor_ref,
    freshness_at=utc_now(),
    payload={
        "investigation_subject": "FTS retrieval performance",
        "files_explored": ["retrieval/lexical.py", "storage/sqlite_search.py"],
        "commands_run": ["python -m pytest tests/test_retrieval.py -x -q"],
        "bash_output_fragments": ["...5 failed, 20 passed..."],
        "turn_count": 3,
        "related_finding_ids": ["abc123"],  # investigation_outcome IDs from same thread
    }
)
```

The prior `task_trace` for this thread (if any) is superseded.

The `task_trace` MemoryObject's indexed text (for BM25 retrieval) includes the `investigation_subject`, all entries in `files_explored`, and all entries in `commands_run` joined as a single string.

---

## Injection

### SessionStart and PreCompact

The hooks query for the most recent `task_trace` for the current container — pure recency, no semantic matching. This handles session resumption and context reset recovery, which are the primary use cases.

The SessionStart hook already calls `POST /query`. A dedicated `task_trace` query is added alongside the existing orientation query, or filtered from the same result if the routing layer surfaces it.

The injected `files_explored` set is written to `{tmpdir}/{session_id}.work_trace_state.json` for use by the measurement layer. The Stop hook reads this file to compare subsequent tool calls.

**Compact injection card:**
```
[Task Trace — 2 days ago | ref:abc123]
Working area: FTS retrieval performance
Explored: retrieval/lexical.py, storage/sqlite_search.py, retrieval/composite.py
Commands: python -m pytest tests/test_retrieval.py
[+expand]
```

`[+expand]` returns the full payload including `bash_output_fragments` and the referenced `investigation_outcome` / `decision` objects by ID.

### UserPromptSubmit

No special handling. Task traces participate in normal BM25 + vector retrieval. File paths and component names in `files_explored` are indexed and match naturally when the user prompt references the same area.

### PreCompact (Claude Code only)

Codex has no PreCompact hook. The Claude Code PreCompact hook re-injects the most recent task_trace for the container alongside the existing checkpoint re-query.

---

## Integration Scope

| Integration | SessionStart | UserPromptSubmit | Stop (capture) | PreCompact |
|-------------|-------------|-----------------|----------------|------------|
| Claude Code | ✓ inject | ✓ BM25 natural | ✓ extended | ✓ inject |
| Codex       | ✓ inject | ✓ BM25 natural | ✓ extended | — (no hook) |

Both integrations share `extract_tool_use_results()` from `common.py`. Transcript format differences are handled by the existing multi-format detection logic.

---

## Out of Scope

- **Per-file content summaries**: not stored. Files are tracked by path, not content.
- **Repo orientation as a separate type**: cross-task repo facts (build commands, test commands) emerge from accumulated task traces over time. No dedicated type in v1.
- **Cross-session semantic matching**: recency injection is the primary path. BM25 natural surfacing on UserPromptSubmit handles topical matching incidentally.
- **PostToolUse hook**: not needed. Stop hook with transcript parsing provides all the same data in the correct turn-bounded grouping.
- **Graph construction**: no knowledge graph. Hybrid retrieval on `files_explored` text is sufficient.

---

## Files to Create / Modify

| File | Change |
|------|--------|
| `core/models.py` | Add `ToolUseResult` dataclass and `tool_use_results` field to `SourceItem` |
| `integrations/claude-code/hooks/common.py` | Add `extract_tool_use_results()` |
| `integrations/claude-code/hooks/stop.py` | Call `extract_tool_use_results()`, populate `tool_use_results` |
| `integrations/codex/hooks/common.py` | Add `extract_tool_use_results()` (shared or imported) |
| `integrations/codex/hooks/stop.py` | Same as Claude Code stop |
| `semantic/agent_work_trace.py` | New parallel package (item-level + thread rebuild) |
| `pallium.local.toml` | Register `agent_work_trace` |
| `api/schemas.py` | Expose `tool_use_results` in ingest schema |
| `integrations/claude-code/hooks/session_start.py` | Add task_trace recency query + session state write |
| `integrations/codex/hooks/session_start.py` | Same |
| `integrations/claude-code/hooks/pre_compact.py` | Add task_trace re-injection |
