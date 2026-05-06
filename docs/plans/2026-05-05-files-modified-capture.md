# files_modified Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `files_modified` to the work trace pipeline so the `task_trace` payload records which files were actually written, rather than inferring them from the files-read-during-productive-phase proxy.

**Architecture:** Capture Edit/Write/NotebookEdit file paths in `read_turn()` during the `tool_use` pass (inputs are available before tool results), add `files_modified` to `TurnData`, propagate through `build_work_trace_metadata()`, and aggregate into the `task_trace` payload in `agent_work_trace.py`. Both `claude-code` and `codex` common.py copies must stay in sync.

**Tech Stack:** Python stdlib only in hook files (no Pallium core imports); pytest for tests.

---

## File Map

| File | Change |
|------|--------|
| `integrations/claude-code/hooks/common.py` | Add `files_modified` to `TurnData`; capture paths in `read_turn()`; include in `build_work_trace_metadata()` |
| `integrations/codex/hooks/common.py` | Identical changes — must stay in sync |
| `semantic/agent_work_trace.py` | Aggregate `files_modified` from turns; add to payload; include in BM25 index text |
| `tests/test_hook_common_parity.py` | Update behavioral parity test for new field |
| `tests/test_agent_work_trace.py` | Update turn fixtures and payload assertions |

---

### Task 1: Add `files_modified` to Claude Code `common.py`

**Files:**
- Modify: `integrations/claude-code/hooks/common.py`

Three changes in this file: (1) add `field` import, (2) add `files_modified` to `TurnData`, (3) capture paths in `read_turn()`, (4) include in `build_work_trace_metadata()`.

- [ ] **Step 1: Write failing test for `files_modified` capture in `build_work_trace_metadata`**

Add this to `tests/test_hook_common_parity.py` (temporary home before it moves to its own file in Task 4):

```python
def test_cc_build_work_trace_metadata_captures_files_modified():
    """Edit/Write tool calls produce files_modified in turn metadata."""
    import importlib.util, sys
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "cc_common_files_mod",
        Path(__file__).parent.parent / "integrations" / "claude-code" / "hooks" / "common.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cc_common_files_mod"] = mod
    spec.loader.exec_module(mod)

    turn = mod.TurnData(
        assistant_text="done",
        tool_calls=[{"tool": "Read", "file_path": "src/a.py"}],
        has_productive_action=True,
        files_modified=["src/b.py"],
    )
    result = mod.build_work_trace_metadata(turn)
    assert result is not None
    assert result["files_modified"] == ["src/b.py"]
```

- [ ] **Step 2: Run test to confirm it fails**

```
python -m pytest tests/test_hook_common_parity.py::test_cc_build_work_trace_metadata_captures_files_modified -v
```

Expected: `FAILED` — `TurnData.__init__() got an unexpected keyword argument 'files_modified'`

- [ ] **Step 3: Add `field` to dataclass import in `common.py`**

In `integrations/claude-code/hooks/common.py`, change line 17:

```python
from dataclasses import dataclass
```

to:

```python
from dataclasses import dataclass, field
```

- [ ] **Step 4: Add `files_modified` field to `TurnData`**

Replace the `TurnData` dataclass (currently lines 328–332):

```python
@dataclass
class TurnData:
    assistant_text: str
    tool_calls: list[dict]
    has_productive_action: bool
```

with:

```python
@dataclass
class TurnData:
    assistant_text: str
    tool_calls: list[dict]
    has_productive_action: bool
    files_modified: list[str] = field(default_factory=list)
```

- [ ] **Step 5: Capture file paths in `read_turn()` during `tool_use` processing**

In `read_turn()`, add `files_modified: list[str] = []` alongside the other pre-loop declarations:

```python
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    has_productive = False
    files_modified: list[str] = []
```

Then, in the `elif block_type == "tool_use":` branch, extend the `has_productive` check to also collect file paths. Replace:

```python
                if tool_name in PRODUCTIVE_TOOLS:
                    has_productive = True
```

with:

```python
                if tool_name in PRODUCTIVE_TOOLS:
                    has_productive = True
                    fp: str | None = None
                    if tool_name in ("Edit", "Write"):
                        fp = tool_input.get("file_path", "")
                    elif tool_name == "NotebookEdit":
                        fp = tool_input.get("notebook_path", "")
                    if fp:
                        fp = redact_sensitive(fp)
                        if fp not in files_modified:
                            files_modified.append(fp)
```

- [ ] **Step 6: Pass `files_modified` into the returned `TurnData`**

Replace the final `return TurnData(...)` in `read_turn()`:

```python
    return TurnData(
        assistant_text=assistant_text if assistant_text.strip() else "",
        tool_calls=tool_calls,
        has_productive_action=has_productive,
    )
```

with:

```python
    return TurnData(
        assistant_text=assistant_text if assistant_text.strip() else "",
        tool_calls=tool_calls,
        has_productive_action=has_productive,
        files_modified=files_modified,
    )
```

- [ ] **Step 7: Include `files_modified` in `build_work_trace_metadata()`**

Replace the return statement in `build_work_trace_metadata()`:

```python
    if not files_read and not commands and not grep_patterns:
        return None

    return {
        "files_read": files_read,
        "commands": commands,
        "grep_patterns": grep_patterns,
        "has_productive_action": turn_data.has_productive_action,
    }
```

with:

```python
    if not files_read and not commands and not grep_patterns and not turn_data.files_modified:
        return None

    result: dict = {
        "files_read": files_read,
        "commands": commands,
        "grep_patterns": grep_patterns,
        "has_productive_action": turn_data.has_productive_action,
    }
    if turn_data.files_modified:
        result["files_modified"] = turn_data.files_modified
    return result
```

- [ ] **Step 8: Run test to confirm it passes**

```
python -m pytest tests/test_hook_common_parity.py::test_cc_build_work_trace_metadata_captures_files_modified -v
```

Expected: `PASSED`

- [ ] **Step 9: Run full test suite to check for regressions**

```
python -m pytest tests/ -x -q
```

Expected: all passing.

- [ ] **Step 10: Commit**

```bash
git add integrations/claude-code/hooks/common.py tests/test_hook_common_parity.py
git commit -m "feat: capture files_modified in claude-code work trace turn"
```

---

### Task 2: Mirror changes to Codex `common.py`

**Files:**
- Modify: `integrations/codex/hooks/common.py`

The Codex `common.py` is structurally identical to Claude Code's except for the `read_last_assistant_turn` format handling and the `AGENT_REF`/`SOURCE_TYPE` constants. Apply the same four changes.

- [ ] **Step 1: Write the failing parity test**

Add to `tests/test_hook_common_parity.py`:

```python
def test_codex_build_work_trace_metadata_captures_files_modified():
    """Codex common.py also captures files_modified."""
    turn = codex_common.TurnData(
        assistant_text="done",
        tool_calls=[{"tool": "Read", "file_path": "src/a.py"}],
        has_productive_action=True,
        files_modified=["src/b.py"],
    )
    result = codex_common.build_work_trace_metadata(turn)
    assert result is not None
    assert result["files_modified"] == ["src/b.py"]
```

- [ ] **Step 2: Run test to confirm it fails**

```
python -m pytest tests/test_hook_common_parity.py::test_codex_build_work_trace_metadata_captures_files_modified -v
```

Expected: `FAILED`

- [ ] **Step 3: Apply the same four changes to Codex `common.py`**

1. Change `from dataclasses import dataclass` → `from dataclasses import dataclass, field`

2. Add `files_modified: list[str] = field(default_factory=list)` to `TurnData`:

```python
@dataclass
class TurnData:
    assistant_text: str
    tool_calls: list[dict]
    has_productive_action: bool
    files_modified: list[str] = field(default_factory=list)
```

3. In `read_turn()`, add `files_modified: list[str] = []` pre-loop, then extend the `tool_use` branch:

```python
                if tool_name in PRODUCTIVE_TOOLS:
                    has_productive = True
                    fp: str | None = None
                    if tool_name in ("Edit", "Write"):
                        fp = tool_input.get("file_path", "")
                    elif tool_name == "NotebookEdit":
                        fp = tool_input.get("notebook_path", "")
                    if fp:
                        fp = redact_sensitive(fp)
                        if fp not in files_modified:
                            files_modified.append(fp)
```

4. Pass `files_modified=files_modified` in the `return TurnData(...)` call.

5. Update `build_work_trace_metadata()` — same replacement as Task 1 Step 7.

- [ ] **Step 4: Run test to confirm it passes**

```
python -m pytest tests/test_hook_common_parity.py::test_codex_build_work_trace_metadata_captures_files_modified -v
```

Expected: `PASSED`

- [ ] **Step 5: Run full suite**

```
python -m pytest tests/ -x -q
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add integrations/codex/hooks/common.py
git commit -m "feat: capture files_modified in codex work trace turn (parity)"
```

---

### Task 3: Update parity tests

**Files:**
- Modify: `tests/test_hook_common_parity.py`

The existing behavioral parity test constructs `TurnData` without `files_modified`. Update it to also verify `files_modified` parity, and add a signature check for the new field.

- [ ] **Step 1: Update `test_build_work_trace_metadata_produces_same_output`**

Replace the existing test:

```python
    def test_build_work_trace_metadata_produces_same_output(self):
        """Behavioral parity: same input produces same output in both copies."""
        turn = cc_common.TurnData(
            assistant_text="test",
            tool_calls=[
                {"tool": "Read", "file_path": "src/x.py"},
                {"tool": "Bash", "command": "ls", "exit_code": 0, "output_tail": "", "failure_class": "success"},
            ],
            has_productive_action=False,
        )
        codex_turn = codex_common.TurnData(
            assistant_text="test",
            tool_calls=[
                {"tool": "Read", "file_path": "src/x.py"},
                {"tool": "Bash", "command": "ls", "exit_code": 0, "output_tail": "", "failure_class": "success"},
            ],
            has_productive_action=False,
        )
        assert cc_common.build_work_trace_metadata(turn) == codex_common.build_work_trace_metadata(codex_turn)
```

with:

```python
    def test_build_work_trace_metadata_produces_same_output(self):
        """Behavioral parity: same input produces same output in both copies."""
        for files_modified in [[], ["src/b.py", "src/c.py"]]:
            cc_turn = cc_common.TurnData(
                assistant_text="test",
                tool_calls=[
                    {"tool": "Read", "file_path": "src/x.py"},
                    {"tool": "Bash", "command": "ls", "exit_code": 0, "output_tail": "", "failure_class": "success"},
                ],
                has_productive_action=bool(files_modified),
                files_modified=files_modified,
            )
            codex_turn = codex_common.TurnData(
                assistant_text="test",
                tool_calls=[
                    {"tool": "Read", "file_path": "src/x.py"},
                    {"tool": "Bash", "command": "ls", "exit_code": 0, "output_tail": "", "failure_class": "success"},
                ],
                has_productive_action=bool(files_modified),
                files_modified=files_modified,
            )
            assert cc_common.build_work_trace_metadata(cc_turn) == codex_common.build_work_trace_metadata(codex_turn)
```

- [ ] **Step 2: Add a TurnData fields parity test**

```python
    def test_turn_data_fields_match(self):
        """TurnData dataclass fields are identical in both copies."""
        import dataclasses
        cc_fields = {f.name: f.type for f in dataclasses.fields(cc_common.TurnData)}
        codex_fields = {f.name: f.type for f in dataclasses.fields(codex_common.TurnData)}
        assert cc_fields == codex_fields
```

- [ ] **Step 3: Run parity tests**

```
python -m pytest tests/test_hook_common_parity.py -v
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add tests/test_hook_common_parity.py
git commit -m "test: update parity tests for files_modified in TurnData"
```

---

### Task 4: Aggregate `files_modified` in `agent_work_trace.py`

**Files:**
- Modify: `semantic/agent_work_trace.py`

Three changes: (1) add a cap constant, (2) aggregate `files_modified` from turns, (3) add to payload and BM25 index.

- [ ] **Step 1: Write the failing test**

In `tests/test_agent_work_trace.py`, add a test that passes turns with `files_modified` and asserts the payload contains them. Find the test class `TestThreadRebuild` (or equivalent) and add:

```python
    def test_payload_includes_files_modified(self):
        """files_modified from turns is aggregated into task_trace payload."""
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider(outcome=None))
        turns = [
            {
                "files_read": ["retrieval/lexical.py"],
                "commands": [],
                "grep_patterns": [],
                "has_productive_action": False,
                "files_modified": [],
            },
            {
                "files_read": ["retrieval/lexical.py"],
                "commands": [{"cmd": "python -m pytest tests/ -x -q", "exit_code": 0, "output_tail": "1 passed", "failure_class": "success"}],
                "grep_patterns": [],
                "has_productive_action": True,
                "files_modified": ["retrieval/lexical.py", "tests/test_retrieval.py"],
            },
        ]
        items = _make_trace_items(turns)
        aggregate = build_thread_aggregate(
            source_items=items,
            conclusions=[],
            container_ref="git:example.com/repo",
            thread_ref="session-1",
        )
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        assert len(result.memory_objects) == 1
        payload = result.memory_objects[0].payload
        assert payload["files_modified"] == ["retrieval/lexical.py", "tests/test_retrieval.py"]
```

- [ ] **Step 2: Run test to confirm it fails**

```
python -m pytest tests/test_agent_work_trace.py::TestThreadRebuild::test_payload_includes_files_modified -v
```

Expected: `FAILED` — `KeyError: 'files_modified'` or `AssertionError`

- [ ] **Step 3: Add cap constant and aggregate `files_modified` in `build_thread_summary()`**

After the existing cap constants at the top of `agent_work_trace.py`, add:

```python
MAX_FILES_MODIFIED = 20
```

In `build_thread_summary()`, after the line that collects `commands_failed`, add:

```python
        # Aggregate modified files (direct signal — not inferred from read phase)
        files_modified = list(dict.fromkeys(
            f for t in turns for f in t.get("files_modified", [])
        ))
        files_modified = files_modified[:MAX_FILES_MODIFIED]
```

- [ ] **Step 4: Add `files_modified` to the payload dict**

In the `payload: dict[str, Any] = { ... }` block, add the new field after `"commands_failed"`:

```python
            "files_modified": files_modified,
```

- [ ] **Step 5: Add `files_modified` to the BM25 index text**

Replace:

```python
        index_parts = [subject] + exploratory_files + productive_files + [c["cmd"] for c in commands_succeeded]
        if outcome:
            index_parts.append(outcome)
```

with:

```python
        index_parts = [subject] + exploratory_files + files_modified + productive_files + [c["cmd"] for c in commands_succeeded]
        if outcome:
            index_parts.append(outcome)
```

- [ ] **Step 6: Run the new test**

```
python -m pytest tests/test_agent_work_trace.py::TestThreadRebuild::test_payload_includes_files_modified -v
```

Expected: `PASSED`

- [ ] **Step 7: Run full suite**

```
python -m pytest tests/ -x -q
```

Expected: all passing.

- [ ] **Step 8: Commit**

```bash
git add semantic/agent_work_trace.py tests/test_agent_work_trace.py
git commit -m "feat: add files_modified to task_trace payload and BM25 index"
```

---

### Task 5: Update existing `agent_work_trace` test fixtures

**Files:**
- Modify: `tests/test_agent_work_trace.py`
- Modify: `tests/test_agent_work_trace_e2e.py`

Existing turn fixture dicts don't include `files_modified`. The package uses `.get("files_modified", [])` so they won't break, but add `files_modified` to fixtures that involve productive actions to make tests explicit about both paths.

- [ ] **Step 1: Audit existing turn fixtures in `test_agent_work_trace.py`**

Search for all `"has_productive_action": True` in the file. For each, add `"files_modified": [...]` with a representative path. For `"has_productive_action": False`, add `"files_modified": []`.

Example — find any turn fixture like:
```python
{
    "files_read": ["src/main.py"],
    "commands": [...],
    "grep_patterns": [],
    "has_productive_action": True,
}
```
and add:
```python
    "files_modified": ["src/main.py"],
```

- [ ] **Step 2: Do the same in `test_agent_work_trace_e2e.py`**

Same pattern — add `"files_modified": []` to all turn fixtures that don't have it.

- [ ] **Step 3: Run both test files**

```
python -m pytest tests/test_agent_work_trace.py tests/test_agent_work_trace_e2e.py -v
```

Expected: all passing.

- [ ] **Step 4: Run full suite one final time**

```
python -m pytest tests/ -x -q
```

Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add tests/test_agent_work_trace.py tests/test_agent_work_trace_e2e.py
git commit -m "test: add files_modified to agent_work_trace test fixtures"
```

---

## Self-Review

**Spec coverage:**
- ✅ `files_modified` captured from Edit/Write/NotebookEdit tool inputs in `read_turn()` (both integrations)
- ✅ Redaction applied before storage
- ✅ `build_work_trace_metadata()` gate updated to not drop turns that only have productive actions
- ✅ Aggregated with dedup and capped in `build_thread_summary()`
- ✅ Added to payload and BM25 index
- ✅ Parity between claude-code and codex enforced by updated parity tests

**Note — injection card format:** The task_trace injection card currently renders a placeholder text via the `/query` endpoint. The `Modified:` line described in the spec is not yet in the card renderer. That is a separate gap not addressed here — this plan only adds `files_modified` to the data pipeline so it's available in the payload when the card renderer is implemented.
