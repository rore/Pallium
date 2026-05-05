# Agent Work Trace Package Design

**Date:** 2026-05-05
**Status:** Draft — revised after architect review and product review
**Scope:** New parallel semantic package capturing agent discovery work for reuse across sessions

## Overview

Agents doing engineering work repeatedly pay to discover the same things: which files matter, which commands work, where a bug lives. Pallium currently captures what the agent *said* (via `agent_conversation_memory`), but not what it *did* — which files it read, which commands it ran, what exploration path it took.

`agent_work_trace` is a parallel semantic package that captures the structural trail of agent work per turn, aggregates it into a compact `task_trace` memory object per session, and injects it on session resume so the agent can skip the orientation phase and go directly to the relevant location.

**What it does not do:** duplicate findings extraction. `agent_conversation_memory` already extracts decisions and investigation outcomes from the agent's response text. `agent_work_trace` captures the file and command trail; findings come from the existing extraction.

---

## Hypothesis and Measurement

**Hypothesis:** injecting a compact task trace on session resume reduces orientation tool calls before first productive action.

**Why not "re-discovery rate":** a file re-read after trace injection can mean the trace worked (agent went directly to the right file) or that it was irrelevant. Raw duplicate reads are not a clean signal.

**Primary metric — orientation cost before first productive action:**
- Number of Read / Grep / Glob / Bash calls before the first Edit / Write / test command in a session
- Token volume from discovery tool results before first productive action
- Repeated broad commands (repo-wide grep, find, ls-tree, full test discovery)
- Tool calls until the agent first touches a file present in the injected `task_trace.productive_files`

**Measurement mechanism (v1):**
- The SessionStart hook writes the injected `task_trace` payload to `{STATE_DIR}/{session_id}.work_trace_state.json` when a trace is injected.
- Measurement analysis is done offline: compare orientation call counts between sessions where a trace was injected vs. sessions where none was available.
- The Stop-side per-turn accumulation loop is deferred — v1 relies on offline log analysis, not real-time metric computation.

**Measurement events (append-only):** at each thread rebuild, a lightweight metric event is appended to a local append-only log (`{STATE_DIR}/work_trace_metrics.jsonl`). This is separate from the superseded `task_trace` memory object. Supersession must not destroy the experiment history.

**Validation threshold:** measurable reduction in orientation call count across 15+ comparable sessions within the same repo over a few weeks of normal use.

---

## Data Capture: `agent_work_trace` Metadata

The Stop hook populates `metadata["agent_work_trace_turn"]` on the SourceItem it ingests. This keeps the generic `SourceItem` schema clean — no new first-class fields on the core contract.

`ToolUseResult` is an internal hook-side structure; it is not a public model type.

**Truncation rules by tool type:**

| Tool | Captured | Limit |
|------|----------|-------|
| `Read` | `tool_input.file_path` only — no content | path string |
| `Bash` | `tool_input.command` + exit code + last 600 chars of output + detected failure class | 600 chars output |
| `Grep` | pattern + path + first 20 matches | 20 matches |
| `Glob` | pattern + first 50 paths | 50 paths |
| `WebFetch` | excluded in v1 | — |

**Bash failure classification** (deterministic, keyword-based):
- `"test_failure"` — output contains pytest/jest/mocha failure markers
- `"build_error"` — output contains compiler error patterns
- `"command_error"` — non-zero exit code, no specific pattern
- `"success"` — zero exit code

**Tools excluded:** `Edit`, `Write`, `NotebookEdit`, `TodoWrite`, `Agent`, `Task*`. These represent work output, not discovery. Their presence in a turn is tracked only as a boolean flag for the exploratory/productive split (see payload below).

**Redaction (applied before any storage):** strip values matching these patterns from all captured fields:
- Bearer tokens, API keys, private keys (`Bearer `, `sk-`, `-----BEGIN`)
- Environment variable assignments containing `PASSWORD`, `SECRET`, `TOKEN`, `KEY`, `AUTH`
- Connection strings (`mongodb://`, `postgres://`, `mysql://`)
- `Authorization:` and `Cookie:` header values

---

## Stop Hook Extension

Both `integrations/claude-code/hooks/stop.py` and `integrations/codex/hooks/stop.py` are extended via a shared implementation in each `common.py` (both are standalone stdlib-only files — no shared import path between integrations; both copies must be kept in sync).

**Single-pass transcript read:** `read_last_assistant_turn()` is extended into `read_turn()` which returns both the assistant response text and the tool call pairs from the same JSONL scan. This replaces the current single-purpose function; the Stop hook calls it once.

**`read_turn(transcript_path) -> TurnData`** where `TurnData` contains:
- `assistant_text: str` — the final response text (existing behavior)
- `tool_calls: list[dict]` — tool_use/tool_result pairs since last user message, filtered and redacted
- `has_productive_action: bool` — True if any Edit/Write call is present in this turn

Extraction is best-effort and never ingestion-blocking. Partial results, nested subagent calls, compacted history, and failed tool calls are silently dropped; the hook never raises on parse errors.

The Stop hook then populates `metadata["agent_work_trace_turn"]` on the SourceItem:

```python
{
    "files_read": ["retrieval/lexical.py", "storage/sqlite_search.py"],
    "commands": [
        {"cmd": "python -m pytest tests/ -x -q", "exit_code": 1,
         "output_tail": "...5 failed, 20 passed...", "failure_class": "test_failure"}
    ],
    "grep_patterns": ["IDF"],
    "has_productive_action": False,   # no Edit/Write in this turn
}
```

If `tool_calls` is empty after filtering, `metadata["agent_work_trace_turn"]` is not set and ingestion proceeds unchanged.

---

## Package: `agent_work_trace`

### Registration

Parallel package (`parallel_processing = True`). Processes every ingested item but returns empty results for items without `metadata["agent_work_trace_turn"]`. Registered alongside `agent_conversation_memory` in `pallium.local.toml` and the service plugin registry.

### Item-Level Processing

**Activation condition:** `source_item.metadata.get("agent_work_trace_turn")` is present.

**Extraction (fully deterministic — no LLM):**

```python
turn = source_item.metadata["agent_work_trace_turn"]
turn_summary = {
    "files_read":            turn["files_read"],
    "commands":              turn["commands"],
    "grep_patterns":         turn["grep_patterns"],
    "has_productive_action": turn["has_productive_action"],
}
```

**Output:**
- `memory_objects`: empty — no MemoryObject at item level
- `source_item_metadata_updates`: stores `turn_summary` under `"agent_work_trace_turn"` (already set by hook; this confirms it is retained)
- `thread_rebuild_requested`: `True`

### Thread Rebuild

**Input:** `ThreadAggregate` — all SourceItems for the thread plus `memory_by_type` from other packages.

**Step 1 — Collect turn summaries (in thread order):**
```python
turns = [
    item.metadata["agent_work_trace_turn"]
    for item in aggregate.items
    if "agent_work_trace_turn" in (item.metadata or {})
]
```
If no turns found, skip rebuild.

**Step 2 — Exploratory vs. productive split:**

Files read before the first turn with `has_productive_action=True` are `exploratory_files`. Files read in turns where or after `has_productive_action=True` are `productive_files`. This split is the core signal for the orientation-cost metric.

```python
first_productive_turn = next(
    (i for i, t in enumerate(turns) if t["has_productive_action"]), None
)
exploratory_files = list(dict.fromkeys(
    f for t in turns[:first_productive_turn] for f in t["files_read"]
)) if first_productive_turn is not None else list(dict.fromkeys(
    f for t in turns for f in t["files_read"]
))
productive_files = list(dict.fromkeys(
    f for t in turns[first_productive_turn:] for f in t["files_read"]
)) if first_productive_turn is not None else []
```

**Step 3 — Collect turn source items and aggregate commands:**
```python
trace_items = [
    item for item in aggregate.items
    if "agent_work_trace_turn" in (item.metadata or {})
]
turn_source_item_ids = [item.id for item in trace_items]

commands_succeeded = [c for t in turns for c in t["commands"] if c["exit_code"] == 0]
commands_failed    = [c for t in turns for c in t["commands"] if c["exit_code"] != 0]
```

`turn_source_item_ids` enables **query-time correlation** with `investigation_outcome` objects produced by `agent_conversation_memory` from the same source items. No extraction-time dependency — the correlation is a secondary lookup at expand time, not a join during rebuild.

**Step 4 — Deterministic subject:**
Most common directory prefix across all files read. Example: if 4 of 6 files are under `retrieval/`, the subject is `retrieval/`. If no clear prefix, use the top 2 file paths. No LLM.

**Step 5 — Best-effort outcome extraction (LLM, may return null):**
One LLM call using the **agent's response texts** from the trace items — not file content, not command output.

```python
response_texts = [item.content for item in trace_items if item.content]
```

Prompt: *"Given these agent responses from a coding session, produce a 1-2 sentence summary of what was investigated and what if anything was found or resolved. If the responses contain only analysis, planning, or no clear conclusion, return null."*

The output is `outcome: str | None`. If null, the field is omitted from the payload. The task_trace is still valid and useful without it — the structural trail always has value. This failure mode is expected for sessions without clear narrated findings.

**Step 6 — Produce `task_trace` MemoryObject:**

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
        "investigation_subject": "retrieval/",          # deterministic dir prefix
        "outcome": "Investigated FTS retrieval. Found IDF weights not applied at lexical.py:89. Fixed.",  # may be null
        "repo_ref": aggregate.container_ref,
        "branch_ref": metadata.get("branch_ref"),       # from hook env if available
        "working_directory": metadata.get("cwd"),       # from hook payload
        "exploratory_files": exploratory_files,
        "productive_files": productive_files,
        "commands_succeeded": [c["cmd"] for c in commands_succeeded],
        "commands_failed":    [c["cmd"] for c in commands_failed],
        "bash_failure_fragments": [
            {"cmd": c["cmd"], "class": c["failure_class"], "tail": c["output_tail"]}
            for c in commands_failed
        ],
        "first_productive_action_at_turn": first_productive_turn,
        "turn_count": len(turns),
        "turn_source_item_ids": turn_source_item_ids,  # for query-time correlation
    }
)
```

The prior `task_trace` for this thread is superseded. A metric event is appended to the append-only log (separate from supersession).

**BM25 indexed text:** `investigation_subject` + all entries in `exploratory_files` + `productive_files` + `commands_succeeded` joined as a single string.

---

## Injection

### Rules by session context

Recency-only injection for new unrelated sessions produces noise and erodes trust. Injection is scoped:

| Context | Rule |
|---------|------|
| Session resume (same `thread_ref`) | Inject most recent `task_trace` for this thread — pure recency |
| PreCompact (Claude Code only) | Inject the current session's `task_trace` if one exists |
| New session, no `thread_ref` match | Do not inject via recency; rely on UserPromptSubmit BM25 match |
| UserPromptSubmit | Natural BM25 surfacing — no special handling |

**Session resume detection:** the SessionStart hook checks `source` field. `"resume"` or `"clear"` → inject. `"startup"` with no matching thread → skip trace injection.

### Injection card format

Hard cap: 400 characters. Task trace is injected **after** conversation memory blocks in priority order — conversation memory is proven higher-value and must not be crowded out.

```
[Task Trace — 2 days ago | ref:abc123]
Area: retrieval/ — IDF weights not applied at lexical.py:89. Fixed.
Explored: lexical.py, sqlite_search.py, composite.py
Tests passing: python -m pytest tests/test_retrieval.py
[+expand]
```

When `outcome` is null (no clear narrated finding), the second line is omitted:

```
[Task Trace — 2 days ago | ref:abc123]
Area: retrieval/
Explored: lexical.py, sqlite_search.py, composite.py
Tests passing: python -m pytest tests/test_retrieval.py
[+expand]
```

`[+expand]` returns the full payload including `bash_failure_fragments`, and performs a secondary lookup for `investigation_outcome` objects whose evidence `source_item_id` appears in `turn_source_item_ids`. This is the correct correlation — by the exact source items both packages processed, not by thread membership.

### Session state file

When a `task_trace` is injected at SessionStart, the hook writes its payload to `{STATE_DIR}/{session_id}.work_trace_state.json`. Used for offline measurement analysis only — not read by the Stop hook in v1.

---

## Privacy and Redaction

All `tool_input` fields and `output_fragment` / `output_tail` values are passed through the redaction filter before being stored in `metadata["agent_work_trace_turn"]`. The redaction runs in the hook, before any network call to Pallium. Redacted values are replaced with `[REDACTED]`. No post-hoc scrubbing.

Redaction patterns (all case-insensitive):
- `Bearer [^\s]+` → `Bearer [REDACTED]`
- `(PASSWORD|SECRET|TOKEN|KEY|AUTH)\s*=\s*\S+` → `KEY=[REDACTED]`
- `-----BEGIN [A-Z ]+ KEY-----.*?-----END` → `[REDACTED KEY BLOCK]`
- `(mongodb|postgres|mysql|redis)://[^\s]+` → `SCHEME://[REDACTED]`
- `(Authorization|Cookie):\s*.+` → `HEADER: [REDACTED]`

---

## Integration Scope

| Integration | SessionStart | UserPromptSubmit | Stop (capture) | PreCompact |
|-------------|-------------|-----------------|----------------|------------|
| Claude Code | ✓ scoped inject | ✓ BM25 natural | ✓ extended | ✓ current session |
| Codex       | ✓ scoped inject | ✓ BM25 natural | ✓ extended | — (no hook) |

Both integrations implement `read_turn()` in their own `common.py`. Both copies must be kept in sync; any change to the tool call extraction logic must be applied to both.

---

## Out of Scope

- **Read content fragments**: path only. No file content stored.
- **WebFetch capture**: excluded until a clear coding-agent use case is established.
- **LLM extraction**: one best-effort call at thread rebuild only, using agent response texts to produce `outcome`. Fully deterministic fallback (null) when quality is low. No per-item LLM calls.
- **Repo orientation type**: emerges from accumulated task traces via future consolidation. Payload fields (`productive_files`, `exploratory_files`, `commands_succeeded`) are designed to feed that layer.
- **PostToolUse hook**: not needed. Stop hook with single-pass transcript read provides turn-bounded data.
- **Graph construction**: no knowledge graph.
- **Stop-side real-time metric accumulation**: deferred. v1 uses offline log analysis.

---

## Files to Create / Modify

| File | Change |
|------|--------|
| `integrations/claude-code/hooks/common.py` | Replace `read_last_assistant_turn()` with `read_turn()` returning text + tool calls; add redaction |
| `integrations/claude-code/hooks/stop.py` | Use `read_turn()`, populate `metadata["agent_work_trace_turn"]` |
| `integrations/codex/hooks/common.py` | Same as Claude Code common.py |
| `integrations/codex/hooks/stop.py` | Same as Claude Code stop.py |
| `semantic/agent_work_trace.py` | New parallel package (item-level + thread rebuild, fully deterministic) |
| `pallium.local.toml` | Register `agent_work_trace` |
| `integrations/claude-code/hooks/session_start.py` | Scoped task_trace inject on resume; write state file |
| `integrations/codex/hooks/session_start.py` | Same |
| `integrations/claude-code/hooks/pre_compact.py` | Inject current session task_trace |
| `docs/context/state.md` | Add `task_trace` to memory type list |
| `roadmap/board.md` | Add feature entry |
