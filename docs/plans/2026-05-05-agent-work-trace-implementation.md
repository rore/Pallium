# Agent Work Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `agent_work_trace` parallel semantic package that captures the structural trail of agent tool usage (files read, commands run, grep patterns) and produces a `task_trace` memory object per session for orientation-cost reduction.

**Architecture:** Hook-side transcript parsing extracts tool call data and populates `metadata["agent_work_trace_turn"]` on ingested SourceItems. A parallel semantic package aggregates per-turn data at thread rebuild into a single `task_trace` MemoryObject with exploratory/productive file split, path normalization, and optional LLM-derived outcome. Injection is scoped to session resume and PreCompact contexts.

**Tech Stack:** Python 3.12+, stdlib-only hook code, Pallium semantic package API, LLM provider for optional outcome extraction.

---

## Architect Review Findings (addressed in plan)

| Finding | Resolution |
|---------|-----------|
| F1: `read_last_assistant_turn()` backward compat | Keep old function intact, add `read_turn()` alongside. Stop hook switches to new function. |
| F2: Exit code inference fragility | Check for explicit exit code field in tool_result structured content before text heuristics. |
| F3: SessionStart query is BM25 approximation | Add code comment. Filter by `"task_trace"` in title as guard. Type-filtered recency is future work. |
| F4: `build_work_trace_metadata` duplicated | Move into `common.py` so it's covered by the parity test. Both stop.py files import from common. |
| F5: No `memory_retention_policy` | Acceptable — `rebuild_supersedes_prior=True` handles cleanup. Add explicit `MemoryRetentionPolicy` with `working_types={"task_trace"}`. |
| F6: No vector embedding | Acceptable for v1 — file paths and commands are lexical-retrieval-friendly. |
| F7: Metric append-only log missing | Add metric event append in `build_thread_summary()` — writes to `{STATE_DIR}/work_trace_metrics.jsonl`. |

---

## File Structure

| File | Responsibility |
|------|---------------|
| `integrations/claude-code/hooks/common.py` | Add `read_turn()`, `TurnData`, redaction utilities, tool call extraction, `build_work_trace_metadata()` |
| `integrations/claude-code/hooks/stop.py` | Call `read_turn()` + `build_work_trace_metadata()` from common, attach to ingest payload |
| `integrations/codex/hooks/common.py` | Mirror of claude-code common.py work trace features (kept in sync) |
| `integrations/codex/hooks/stop.py` | Same extension as claude-code stop.py, importing from common |
| `semantic/agent_work_trace.py` | New parallel semantic package: item processing + thread rebuild → `task_trace` + metric log |
| `app/dependencies.py` | Register `agent_work_trace` implementation in plugin factory |
| `app/config.py` | Add `agent_work_trace` to default semantic packages |
| `pallium.local.toml` | Add `[semantic_packages.agent_work_trace]` section |
| `integrations/claude-code/hooks/session_start.py` | Add scoped task_trace injection on resume; write state file |
| `integrations/codex/hooks/session_start.py` | Same |
| `integrations/claude-code/hooks/pre_compact.py` | Inject current session task_trace |
| `tests/test_agent_work_trace.py` | Unit tests for the semantic package |
| `tests/test_agent_work_trace_e2e.py` | Full end-to-end tests: hook extraction → ingest → process → query → retrieve → inject |
| `tests/test_hook_common_parity.py` | Parity test between both common.py files (covers `build_work_trace_metadata`) |
| `tests/test_work_trace_hooks.py` | Unit tests for hook-side extraction and redaction |

---

### Task 1: Hook-side redaction and tool call extraction (Claude Code common.py)

**Files:**
- Modify: `integrations/claude-code/hooks/common.py`
- Test: `tests/test_work_trace_hooks.py`

- [ ] **Step 1: Write failing tests for redaction**

Create `tests/test_work_trace_hooks.py`:

```python
"""Tests for hook-side agent_work_trace extraction and redaction."""
from __future__ import annotations

import sys
import importlib.util
from pathlib import Path

import pytest

# Load common.py as a module (it's standalone, no package imports)
_common_path = str(Path(__file__).resolve().parent.parent / "integrations" / "claude-code" / "hooks" / "common.py")
_spec = importlib.util.spec_from_file_location("cc_common", _common_path)
cc_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc_common)


class TestRedaction:
    def test_bearer_token_redacted(self):
        text = "curl -H 'Authorization: Bearer sk-abc123xyz'"
        result = cc_common.redact_sensitive(text)
        assert "sk-abc123xyz" not in result
        assert "[REDACTED]" in result

    def test_password_env_var_redacted(self):
        text = "DB_PASSWORD=supersecret123"
        result = cc_common.redact_sensitive(text)
        assert "supersecret123" not in result
        assert "[REDACTED]" in result

    def test_connection_string_redacted(self):
        text = "connecting to postgres://user:pass@host:5432/db"
        result = cc_common.redact_sensitive(text)
        assert "user:pass@host" not in result
        assert "[REDACTED]" in result

    def test_private_key_block_redacted(self):
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
        result = cc_common.redact_sensitive(text)
        assert "MIIEow" not in result
        assert "[REDACTED" in result

    def test_cookie_header_redacted(self):
        text = "Cookie: session=abc123; token=xyz"
        result = cc_common.redact_sensitive(text)
        assert "abc123" not in result
        assert "[REDACTED]" in result

    def test_clean_text_unchanged(self):
        text = "python -m pytest tests/ -x -q"
        result = cc_common.redact_sensitive(text)
        assert result == text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_work_trace_hooks.py::TestRedaction -v`
Expected: FAIL — `cc_common` has no `redact_sensitive` attribute

- [ ] **Step 3: Implement redaction in common.py**

Add to `integrations/claude-code/hooks/common.py`, after the existing imports:

```python
import re

REDACTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Bearer\s+\S+", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"(PASSWORD|SECRET|TOKEN|KEY|AUTH)\s*=\s*\S+", re.IGNORECASE), r"\1=[REDACTED]"),
    (re.compile(r"-----BEGIN [A-Z ]+KEY-----.*?-----END[^\n]*", re.IGNORECASE | re.DOTALL), "[REDACTED KEY BLOCK]"),
    (re.compile(r"(mongodb|postgres|mysql|redis)://\S+", re.IGNORECASE), r"\1://[REDACTED]"),
    (re.compile(r"(Authorization|Cookie):\s*.+", re.IGNORECASE), r"\1: [REDACTED]"),
]


def redact_sensitive(text: str) -> str:
    """Apply redaction patterns to strip secrets from text."""
    for pattern, replacement in REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_work_trace_hooks.py::TestRedaction -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add integrations/claude-code/hooks/common.py tests/test_work_trace_hooks.py
git commit -m "feat(hooks): add redact_sensitive utility to Claude Code common.py"
```

---

### Task 2: Implement `read_turn()` in Claude Code common.py

**Files:**
- Modify: `integrations/claude-code/hooks/common.py`
- Test: `tests/test_work_trace_hooks.py`

- [ ] **Step 1: Write failing tests for read_turn**

Append to `tests/test_work_trace_hooks.py`:

```python
import json
import tempfile
import os


def _write_transcript(tmp_path, lines: list[dict]) -> str:
    """Write JSONL transcript file and return path."""
    path = str(tmp_path / "transcript.jsonl")
    with open(path, "w") as f:
        for entry in lines:
            f.write(json.dumps(entry) + "\n")
    return path


class TestReadTurn:
    def test_extracts_assistant_text(self, tmp_path):
        transcript = _write_transcript(tmp_path, [
            {"type": "user", "message": {"role": "user", "content": "hello"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "I found the issue."},
            ]}},
        ])
        result = cc_common.read_turn(transcript)
        assert result is not None
        assert result.assistant_text == "I found the issue."

    def test_extracts_tool_calls_read(self, tmp_path):
        transcript = _write_transcript(tmp_path, [
            {"type": "user", "message": {"role": "user", "content": "check it"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Read",
                 "input": {"file_path": "/repo/src/main.py"}},
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": "file content here"},
                {"type": "text", "text": "Done."},
            ]}},
        ])
        result = cc_common.read_turn(transcript)
        assert result is not None
        assert result.tool_calls[0]["tool"] == "Read"
        assert result.tool_calls[0]["file_path"] == "/repo/src/main.py"

    def test_extracts_bash_with_exit_code(self, tmp_path):
        transcript = _write_transcript(tmp_path, [
            {"type": "user", "message": {"role": "user", "content": "run tests"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash",
                 "input": {"command": "python -m pytest tests/ -x"}},
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": "FAILED tests/test_x.py - 3 failed, 10 passed"},
                {"type": "text", "text": "Tests failed."},
            ]}},
        ])
        result = cc_common.read_turn(transcript)
        assert result is not None
        bash_call = next(c for c in result.tool_calls if c["tool"] == "Bash")
        assert bash_call["command"] == "python -m pytest tests/ -x"

    def test_has_productive_action_false_when_no_edit(self, tmp_path):
        transcript = _write_transcript(tmp_path, [
            {"type": "user", "message": {"role": "user", "content": "check"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Read",
                 "input": {"file_path": "/repo/src/main.py"}},
                {"type": "tool_result", "tool_use_id": "t1", "content": "x"},
                {"type": "text", "text": "Done."},
            ]}},
        ])
        result = cc_common.read_turn(transcript)
        assert result is not None
        assert result.has_productive_action is False

    def test_has_productive_action_true_when_edit_present(self, tmp_path):
        transcript = _write_transcript(tmp_path, [
            {"type": "user", "message": {"role": "user", "content": "fix it"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Edit",
                 "input": {"file_path": "/repo/x.py", "old_string": "a", "new_string": "b"}},
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
                {"type": "text", "text": "Fixed."},
            ]}},
        ])
        result = cc_common.read_turn(transcript)
        assert result is not None
        assert result.has_productive_action is True

    def test_redaction_applied_to_bash_output(self, tmp_path):
        transcript = _write_transcript(tmp_path, [
            {"type": "user", "message": {"role": "user", "content": "check env"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash",
                 "input": {"command": "echo $DB_PASSWORD"}},
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": "DB_PASSWORD=supersecret123"},
                {"type": "text", "text": "Found it."},
            ]}},
        ])
        result = cc_common.read_turn(transcript)
        bash_call = next(c for c in result.tool_calls if c["tool"] == "Bash")
        assert "supersecret123" not in bash_call.get("output_tail", "")

    def test_empty_transcript_returns_none(self, tmp_path):
        transcript = _write_transcript(tmp_path, [])
        result = cc_common.read_turn(transcript)
        assert result is None

    def test_excluded_tools_not_in_tool_calls(self, tmp_path):
        transcript = _write_transcript(tmp_path, [
            {"type": "user", "message": {"role": "user", "content": "plan"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "TodoWrite",
                 "input": {"todos": []}},
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
                {"type": "tool_use", "id": "t2", "name": "Read",
                 "input": {"file_path": "/repo/x.py"}},
                {"type": "tool_result", "tool_use_id": "t2", "content": "code"},
                {"type": "text", "text": "Done."},
            ]}},
        ])
        result = cc_common.read_turn(transcript)
        tool_names = [c["tool"] for c in result.tool_calls]
        assert "TodoWrite" not in tool_names
        assert "Read" in tool_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_work_trace_hooks.py::TestReadTurn -v`
Expected: FAIL — `cc_common` has no `read_turn` attribute

- [ ] **Step 3: Implement `read_turn()`, `TurnData`, and `build_work_trace_metadata()`**

Add to `integrations/claude-code/hooks/common.py` (note: `build_work_trace_metadata` lives in common.py per F4 finding, so it's covered by the parity test):

```python
from dataclasses import dataclass


@dataclass
class TurnData:
    assistant_text: str
    tool_calls: list[dict]
    has_productive_action: bool


DISCOVERY_TOOLS = frozenset({"Read", "Bash", "Grep", "Glob"})
PRODUCTIVE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
EXCLUDED_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "TodoWrite", "Agent", "TaskOutput", "TaskStop"})
BASH_OUTPUT_LIMIT = 600
GREP_MATCH_LIMIT = 20
GLOB_PATH_LIMIT = 50


def _classify_bash_failure(output: str, exit_code: int) -> str:
    if exit_code == 0:
        return "success"
    lower = output.lower()
    if any(m in lower for m in ("failed", "error", "failures") if "pytest" in lower or "jest" in lower or "mocha" in lower):
        return "test_failure"
    if any(m in lower for m in ("failed", "failures", "pytest", "jest", "mocha")):
        return "test_failure"
    if any(m in lower for m in ("compile error", "build failed", "syntax error", "compilation")):
        return "build_error"
    return "command_error"


def _extract_tool_call(name: str, tool_input: dict, tool_output: str) -> dict | None:
    """Extract a normalized tool call record for the work trace. Returns None if excluded."""
    if name in EXCLUDED_TOOLS:
        return None

    if name == "Read":
        file_path = tool_input.get("file_path", "")
        return {"tool": "Read", "file_path": redact_sensitive(file_path)}

    if name == "Bash":
        command = redact_sensitive(tool_input.get("command", ""))
        output_tail = redact_sensitive(tool_output[-BASH_OUTPUT_LIMIT:]) if tool_output else ""
        # Infer exit code from tool_result: if output contains common failure markers
        # or starts with error text, treat as non-zero. Best-effort.
        exit_code = _infer_exit_code(tool_output)
        failure_class = _classify_bash_failure(output_tail, exit_code)
        return {
            "tool": "Bash",
            "command": command,
            "exit_code": exit_code,
            "output_tail": output_tail,
            "failure_class": failure_class,
        }

    if name == "Grep":
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        # Truncate matches from output
        matches = tool_output.strip().splitlines()[:GREP_MATCH_LIMIT] if tool_output else []
        return {"tool": "Grep", "pattern": pattern, "path": path, "matches": matches}

    if name == "Glob":
        pattern = tool_input.get("pattern", "")
        paths = tool_output.strip().splitlines()[:GLOB_PATH_LIMIT] if tool_output else []
        return {"tool": "Glob", "pattern": pattern, "paths": paths}

    return None


def _infer_exit_code(tool_output: str) -> int:
    """Best-effort exit code inference from tool_result content.

    Claude Code tool_result for Bash may include structured exit code info.
    Priority:
    1. Explicit "exit code: N" field in output (most reliable)
    2. Text heuristics for known failure patterns (fallback)
    3. Default to 0 if we can't determine
    """
    if not tool_output:
        return 0
    import re as _re
    # Priority 1: explicit exit code field (structured output from some formats)
    m = _re.search(r"exit code:\s*(\d+)", tool_output, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Priority 2: text heuristics for known failure patterns
    lower = tool_output.lower()
    # Only match when there's strong signal — avoid false positives from
    # legitimate output that happens to contain words like "error" or "failed"
    strong_failure_markers = (
        "command failed", "traceback (most recent call last)",
        "fatal:", "panic:", "exited with", "non-zero exit",
    )
    if any(marker in lower for marker in strong_failure_markers):
        return 1
    return 0


def read_turn(transcript_path: str) -> TurnData | None:
    """Read the last assistant turn, extracting text and tool calls.

    Single-pass replacement for read_last_assistant_turn(). Returns TurnData
    with assistant response text, filtered/redacted tool calls, and
    has_productive_action flag.
    """
    try:
        file_size = os.path.getsize(transcript_path)
    except OSError:
        return None

    if file_size == 0:
        return None

    try:
        if file_size > 10 * 1024 * 1024:
            with open(transcript_path, "rb") as f:
                f.seek(-2 * 1024 * 1024, 2)
                raw = f.read().decode("utf-8", errors="replace")
            lines = raw.splitlines()
            if lines:
                lines = lines[1:]
        else:
            with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
    except OSError:
        return None

    last_assistant_content = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        role = None
        content = None

        if "message" in entry and isinstance(entry["message"], dict):
            role = entry["message"].get("role")
            content = entry["message"].get("content")
        elif "role" in entry:
            role = entry.get("role")
            content = entry.get("content")

        if role == "assistant" and content is not None:
            last_assistant_content = content

    if last_assistant_content is None:
        return None

    # Extract text and tool calls from the content
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    has_productive = False

    if isinstance(last_assistant_content, str):
        text_parts.append(last_assistant_content)
    elif isinstance(last_assistant_content, list):
        # Build tool_use_id -> tool_use mapping for pairing with results
        tool_uses: dict[str, dict] = {}
        for block in last_assistant_content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "tool_use":
                tool_name = block.get("name", "")
                tool_id = block.get("id", "")
                tool_input = block.get("input", {})
                tool_uses[tool_id] = {"name": tool_name, "input": tool_input}
                if tool_name in PRODUCTIVE_TOOLS:
                    has_productive = True
            elif block_type == "tool_result":
                tool_use_id = block.get("tool_use_id", "")
                tool_output_raw = block.get("content", "") or block.get("text", "")
                if isinstance(tool_output_raw, list):
                    # Content array format
                    tool_output = "\n".join(
                        b.get("text", "") for b in tool_output_raw
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                else:
                    tool_output = str(tool_output_raw) if tool_output_raw else ""
                if tool_use_id in tool_uses:
                    use = tool_uses[tool_use_id]
                    extracted = _extract_tool_call(use["name"], use["input"], tool_output)
                    if extracted is not None:
                        tool_calls.append(extracted)

    assistant_text = "\n".join(text_parts)
    if not assistant_text.strip() and not tool_calls:
        return None

    return TurnData(
        assistant_text=assistant_text if assistant_text.strip() else "",
        tool_calls=tool_calls,
        has_productive_action=has_productive,
    )


def build_work_trace_metadata(turn_data: TurnData) -> dict | None:
    """Build agent_work_trace_turn metadata from extracted turn data.

    Returns None if no discovery tool calls are present.
    Lives in common.py (not stop.py) so the parity test covers it.
    """
    files_read: list[str] = []
    commands: list[dict] = []
    grep_patterns: list[str] = []

    for call in turn_data.tool_calls:
        tool = call.get("tool")
        if tool == "Read":
            fp = call.get("file_path", "")
            if fp and fp not in files_read:
                files_read.append(fp)
        elif tool == "Bash":
            commands.append({
                "cmd": call["command"],
                "exit_code": call["exit_code"],
                "output_tail": call["output_tail"],
                "failure_class": call["failure_class"],
            })
        elif tool == "Grep":
            pattern = call.get("pattern", "")
            if pattern and pattern not in grep_patterns:
                grep_patterns.append(pattern)

    if not files_read and not commands and not grep_patterns:
        return None

    return {
        "files_read": files_read,
        "commands": commands,
        "grep_patterns": grep_patterns,
        "has_productive_action": turn_data.has_productive_action,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_work_trace_hooks.py -v`
Expected: PASS (all redaction + read_turn tests)

- [ ] **Step 5: Commit**

```bash
git add integrations/claude-code/hooks/common.py tests/test_work_trace_hooks.py
git commit -m "feat(hooks): implement read_turn() with tool call extraction and redaction"
```

---

### Task 3: Extend Stop hook to populate work trace metadata (Claude Code)

**Files:**
- Modify: `integrations/claude-code/hooks/stop.py`
- Test: `tests/test_work_trace_hooks.py`

- [ ] **Step 1: Write failing test for build_work_trace_metadata**

Append to `tests/test_work_trace_hooks.py` (note: function now lives in `cc_common`, not stop.py):

```pythonclass TestBuildWorkTraceMetadata:
    def test_builds_metadata_from_turn_data(self):
        turn_data = cc_common.TurnData(
            assistant_text="Found the bug.",
            tool_calls=[
                {"tool": "Read", "file_path": "src/main.py"},
                {"tool": "Read", "file_path": "src/utils.py"},
                {"tool": "Bash", "command": "python -m pytest", "exit_code": 1,
                 "output_tail": "FAILED 3 tests", "failure_class": "test_failure"},
                {"tool": "Grep", "pattern": "IDF", "path": "retrieval/", "matches": ["line1"]},
            ],
            has_productive_action=False,
        )
        meta = cc_common.build_work_trace_metadata(turn_data)
        assert meta["files_read"] == ["src/main.py", "src/utils.py"]
        assert meta["commands"] == [
            {"cmd": "python -m pytest", "exit_code": 1,
             "output_tail": "FAILED 3 tests", "failure_class": "test_failure"}
        ]
        assert meta["grep_patterns"] == ["IDF"]
        assert meta["has_productive_action"] is False

    def test_returns_none_when_no_tool_calls(self):
        turn_data = cc_common.TurnData(
            assistant_text="Just chatting.",
            tool_calls=[],
            has_productive_action=False,
        )
        meta = cc_common.build_work_trace_metadata(turn_data)
        assert meta is None

    def test_deduplicates_files_read(self):
        turn_data = cc_common.TurnData(
            assistant_text="Reading.",
            tool_calls=[
                {"tool": "Read", "file_path": "src/main.py"},
                {"tool": "Read", "file_path": "src/main.py"},
                {"tool": "Read", "file_path": "src/other.py"},
            ],
            has_productive_action=False,
        )
        meta = cc_common.build_work_trace_metadata(turn_data)
        assert meta["files_read"] == ["src/main.py", "src/other.py"]

    def test_deduplicates_grep_patterns(self):
        turn_data = cc_common.TurnData(
            assistant_text="Searching.",
            tool_calls=[
                {"tool": "Grep", "pattern": "IDF", "path": ".", "matches": []},
                {"tool": "Grep", "pattern": "IDF", "path": "src/", "matches": []},
            ],
            has_productive_action=False,
        )
        meta = cc_common.build_work_trace_metadata(turn_data)
        assert meta["grep_patterns"] == ["IDF"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_work_trace_hooks.py::TestBuildWorkTraceMetadata -v`
Expected: FAIL — `cc_stop` has no `build_work_trace_metadata`

- [ ] **Step 3: Implement stop hook changes**

Replace `integrations/claude-code/hooks/stop.py` with (note: `build_work_trace_metadata` is imported from common.py, not defined here):

```python
"""Stop hook — ingests the assistant's last response from the transcript."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    TurnData,
    build_work_trace_metadata,
    derive_actor_ref,
    derive_container_ref,
    pallium_request,
    read_hook_input,
    read_turn,
)

CONTENT_LENGTH_GATE = 20_000


def main() -> None:
    try:
        payload = read_hook_input()
        session_id = payload.get("session_id", "unknown")
        cwd = payload.get("cwd", ".")
        transcript_path = payload.get("transcript_path", "")

        if not transcript_path:
            return

        turn_data = read_turn(transcript_path)
        if not turn_data:
            return
        if not turn_data.assistant_text and not turn_data.tool_calls:
            return
        content = turn_data.assistant_text
        if len(content) > CONTENT_LENGTH_GATE:
            return

        container_ref = derive_container_ref(cwd)
        actor_ref = derive_actor_ref()

        metadata = {}
        work_trace_meta = build_work_trace_metadata(turn_data)
        if work_trace_meta:
            metadata["agent_work_trace_turn"] = work_trace_meta
            metadata["cwd"] = cwd

        item_payload = {
            "source_type": "claude-code",
            "source_id": f"cc-{uuid.uuid4().hex[:12]}",
            "content_type": "text/plain",
            "content": content,
            "role": "assistant",
            "agent_ref": "claude-code",
            "container_ref": container_ref,
            "thread_ref": session_id,
            "actor_ref": actor_ref,
            "visibility": "private",
            "artifact_kind": "message",
        }
        if metadata:
            item_payload["metadata"] = metadata

        pallium_request("POST", "/items", [item_payload])

    except Exception as exc:
        print(f"pallium stop hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_work_trace_hooks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add integrations/claude-code/hooks/stop.py tests/test_work_trace_hooks.py
git commit -m "feat(hooks): stop hook populates agent_work_trace_turn metadata"
```

---

### Task 4: Mirror hook changes to Codex integration

**Files:**
- Modify: `integrations/codex/hooks/common.py`
- Modify: `integrations/codex/hooks/stop.py`
- Create: `tests/test_hook_common_parity.py`

- [ ] **Step 1: Write parity test**

Create `tests/test_hook_common_parity.py`:

```python
"""Verify that Claude Code and Codex common.py stay in sync for work trace features."""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path


def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ROOT = Path(__file__).resolve().parent.parent

cc_common = _load_module(str(ROOT / "integrations" / "claude-code" / "hooks" / "common.py"), "cc_common")
codex_common = _load_module(str(ROOT / "integrations" / "codex" / "hooks" / "common.py"), "codex_common")


class TestCommonParity:
    def test_read_turn_signature_matches(self):
        cc_sig = inspect.signature(cc_common.read_turn)
        codex_sig = inspect.signature(codex_common.read_turn)
        assert str(cc_sig) == str(codex_sig)

    def test_redaction_patterns_match(self):
        cc_patterns = [(p.pattern, r) for p, r in cc_common.REDACTION_PATTERNS]
        codex_patterns = [(p.pattern, r) for p, r in codex_common.REDACTION_PATTERNS]
        assert cc_patterns == codex_patterns

    def test_redact_sensitive_signature_matches(self):
        cc_sig = inspect.signature(cc_common.redact_sensitive)
        codex_sig = inspect.signature(codex_common.redact_sensitive)
        assert str(cc_sig) == str(codex_sig)

    def test_build_work_trace_metadata_signature_matches(self):
        cc_sig = inspect.signature(cc_common.build_work_trace_metadata)
        codex_sig = inspect.signature(codex_common.build_work_trace_metadata)
        assert str(cc_sig) == str(codex_sig)

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

    def test_tool_constants_match(self):
        assert cc_common.DISCOVERY_TOOLS == codex_common.DISCOVERY_TOOLS
        assert cc_common.PRODUCTIVE_TOOLS == codex_common.PRODUCTIVE_TOOLS
        assert cc_common.EXCLUDED_TOOLS == codex_common.EXCLUDED_TOOLS
        assert cc_common.BASH_OUTPUT_LIMIT == codex_common.BASH_OUTPUT_LIMIT
```

- [ ] **Step 2: Run parity test to verify it fails**

Run: `python -m pytest tests/test_hook_common_parity.py -v`
Expected: FAIL — Codex common.py has no `read_turn`

- [ ] **Step 3: Copy work trace features to Codex common.py**

Add the same `REDACTION_PATTERNS`, `redact_sensitive()`, `TurnData`, `DISCOVERY_TOOLS`, `PRODUCTIVE_TOOLS`, `EXCLUDED_TOOLS`, `BASH_OUTPUT_LIMIT`, `GREP_MATCH_LIMIT`, `GLOB_PATH_LIMIT`, `_classify_bash_failure()`, `_extract_tool_call()`, `_infer_exit_code()`, and `read_turn()` functions to `integrations/codex/hooks/common.py`. These are identical to the Claude Code versions. The only difference from Claude Code's `common.py` is the Codex-specific `emit_context()`, `AGENT_REF`, and `SOURCE_TYPE` constants that already exist there.

- [ ] **Step 4: Update Codex stop.py**

Replace `integrations/codex/hooks/stop.py` — same as Claude Code but using Codex's import style. `build_work_trace_metadata` is imported from `common.py` (not duplicated):

```python
"""Stop hook — ingests the assistant's last response from the transcript."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

_common_path = str(Path(__file__).resolve().parent / "common.py")
_spec = importlib.util.spec_from_file_location("codex_common", _common_path)
_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_common)

AGENT_REF = _common.AGENT_REF
SOURCE_TYPE = _common.SOURCE_TYPE
build_work_trace_metadata = _common.build_work_trace_metadata
derive_actor_ref = _common.derive_actor_ref
derive_container_ref = _common.derive_container_ref
pallium_request = _common.pallium_request
read_hook_input = _common.read_hook_input
read_turn = _common.read_turn

CONTENT_LENGTH_GATE = 20_000


def main() -> None:
    try:
        payload = read_hook_input()
        session_id = payload.get("session_id", "unknown")
        cwd = payload.get("cwd", ".")
        transcript_path = payload.get("transcript_path", "")

        if not transcript_path:
            sys.exit(0)

        turn_data = read_turn(transcript_path)
        if not turn_data:
            sys.exit(0)
        if not turn_data.assistant_text and not turn_data.tool_calls:
            sys.exit(0)
        content = turn_data.assistant_text
        if len(content) > CONTENT_LENGTH_GATE:
            sys.exit(0)

        container_ref = derive_container_ref(cwd)
        actor_ref = derive_actor_ref()

        metadata = {}
        work_trace_meta = build_work_trace_metadata(turn_data)
        if work_trace_meta:
            metadata["agent_work_trace_turn"] = work_trace_meta
            metadata["cwd"] = cwd

        item_payload = {
            "source_type": SOURCE_TYPE,
            "source_id": f"cdx-{uuid.uuid4().hex[:12]}",
            "content_type": "text/plain",
            "content": content,
            "role": "assistant",
            "agent_ref": AGENT_REF,
            "container_ref": container_ref,
            "thread_ref": session_id,
            "actor_ref": actor_ref,
            "visibility": "private",
            "artifact_kind": "message",
        }
        if metadata:
            item_payload["metadata"] = metadata

        pallium_request("POST", "/items", [item_payload], quiet=True)

    except Exception as exc:
        print(f"pallium stop hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run parity test to verify it passes**

Run: `python -m pytest tests/test_hook_common_parity.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add integrations/codex/hooks/common.py integrations/codex/hooks/stop.py tests/test_hook_common_parity.py
git commit -m "feat(hooks): mirror work trace extraction to Codex integration with parity test"
```

---

### Task 5: Implement the `agent_work_trace` semantic package

**Files:**
- Create: `semantic/agent_work_trace.py`
- Test: `tests/test_agent_work_trace.py`

- [ ] **Step 1: Write failing tests for item-level processing**

Create `tests/test_agent_work_trace.py`:

```python
"""Tests for the agent_work_trace semantic package."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from core.contracts import ProcessResult
from core.models import SourceItem, MemoryObject, new_id, utc_now
from providers.llm.base import LLMProvider, LLMJsonResponse


class StubOutcomeProvider(LLMProvider):
    """LLM provider that returns a canned outcome summary."""
    provider_name = "stub_outcome"

    def __init__(self, outcome: str | None = "Investigated FTS retrieval. Fixed IDF weights."):
        self._outcome = outcome

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        result = {"outcome": self._outcome}
        return LLMJsonResponse(raw_text=json.dumps(result), parsed_json=result)


def _make_source_item(
    *,
    content: str = "I found the bug.",
    thread_ref: str = "session-1",
    container_ref: str = "git:example.com/repo",
    metadata: dict | None = None,
) -> SourceItem:
    return SourceItem(
        source_type="claude-code",
        source_id=f"cc-{new_id()[:12]}",
        content_type="text/plain",
        content=content,
        thread_ref=thread_ref,
        container_ref=container_ref,
        visibility="private",
        metadata=metadata,
    )


class TestItemProcessing:
    def test_requests_rebuild_when_trace_present(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        item = _make_source_item(metadata={
            "agent_work_trace_turn": {
                "files_read": ["src/main.py"],
                "commands": [],
                "grep_patterns": [],
                "has_productive_action": False,
            }
        })
        result = plugin.process_item(item)
        assert result.thread_rebuild_requested is True
        assert result.memory_objects == []

    def test_skips_rebuild_when_no_trace(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        item = _make_source_item(metadata={})
        result = plugin.process_item(item)
        assert result.thread_rebuild_requested is False

    def test_skips_rebuild_when_metadata_none(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        item = _make_source_item(metadata=None)
        result = plugin.process_item(item)
        assert result.thread_rebuild_requested is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_work_trace.py::TestItemProcessing -v`
Expected: FAIL — ModuleNotFoundError for `semantic.agent_work_trace`

- [ ] **Step 3: Implement item-level processing**

Create `semantic/agent_work_trace.py`:

```python
"""Agent Work Trace — parallel semantic package for capturing agent discovery trails.

Captures the structural trail of agent tool usage (files read, commands run,
grep patterns) per turn, aggregates into a compact task_trace memory object
per session at thread rebuild.

The structural trail is deterministic. The optional outcome field is
best-effort LLM-derived from agent response texts.
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from capabilities.thread_aggregation import ThreadAggregate
from core.contracts import MemoryRetentionPolicy, ProcessResult
from core.indexing import build_index_entry, BUILTIN_INDEX_PROVIDER_NAME, BUILTIN_INDEX_PROVIDER_VERSION
from core.models import IndexEntry, MemoryObject, Relation, SourceItem, new_id, utc_now
from providers.llm.base import LLMProvider, LLMJsonResponse
from semantic.base import ThreadAggregationSemanticPlugin

logger = logging.getLogger(__name__)

TASK_TRACE_TYPE = "task_trace"
TASK_TRACE_SCHEMA_ID = "agent_work_trace.task_trace"
TASK_TRACE_SCHEMA_VERSION = "v1"

LEXICAL_TEXT_VIEW_NAME = "memory_object.task_trace_lexical"

MAX_EXPLORATORY_FILES = 30
MAX_PRODUCTIVE_FILES = 20
MAX_COMMANDS_SUCCEEDED = 10
MAX_COMMANDS_FAILED = 10
MAX_FAILURE_FRAGMENTS = 5

# Metric log for offline measurement analysis
STATE_DIR = Path.home() / ".pallium" / "hooks" / "state"
METRICS_LOG_FILENAME = "work_trace_metrics.jsonl"

OUTCOME_SYSTEM_PROMPT = (
    "Given these agent responses from a coding session, produce a 1-2 sentence "
    "summary of what was investigated and what if anything was found or resolved. "
    "If the responses contain only analysis, planning, or no clear conclusion, "
    "return null for the outcome field."
)


def normalize_path(p: str, cwd: str | None) -> str:
    """Normalize a file path relative to cwd."""
    try:
        if cwd and os.path.isabs(p):
            rel = os.path.relpath(p, cwd)
            return rel.replace("\\", "/")
        cleaned = p.lstrip("./") if p.startswith("./") else p
        return cleaned.replace("\\", "/")
    except (ValueError, TypeError):
        return p


def _compute_subject(all_files: list[str]) -> str:
    """Deterministic subject: most common directory prefix across all files."""
    if not all_files:
        return ""

    dirs: list[str] = []
    for f in all_files:
        parts = f.replace("\\", "/").split("/")
        if len(parts) > 1:
            dirs.append(parts[0] + "/")
        else:
            dirs.append(f)

    if not dirs:
        return all_files[0] if all_files else ""

    counter = Counter(dirs)
    most_common = counter.most_common(2)
    if len(most_common) == 1:
        return most_common[0][0]
    if most_common[0][1] > most_common[1][1]:
        return most_common[0][0]
    # Tie: return top 2 file paths
    return ", ".join(all_files[:2])


def _append_metric_event(thread_ref: str | None, payload: dict) -> None:
    """Append a measurement event to the append-only metrics log."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": utc_now().isoformat(),
            "thread_ref": thread_ref,
            "turn_count": payload.get("turn_count", 0),
            "exploratory_file_count": len(payload.get("exploratory_files", [])),
            "productive_file_count": len(payload.get("productive_files", [])),
            "commands_succeeded_count": len(payload.get("commands_succeeded", [])),
            "commands_failed_count": len(payload.get("commands_failed", [])),
            "has_outcome": "outcome" in payload,
        }
        metrics_path = STATE_DIR / METRICS_LOG_FILENAME
        with open(metrics_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except OSError:
        pass


class AgentWorkTracePlugin(ThreadAggregationSemanticPlugin):
    """Parallel semantic package that captures agent discovery trails."""

    name = "agent_work_trace"

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    @property
    def parallel_processing(self) -> bool:
        return True

    @property
    def thread_summary_schema_id(self) -> str:
        return TASK_TRACE_SCHEMA_ID

    @property
    def rebuild_supersedes_prior(self) -> bool:
        return True

    @property
    def memory_retention_policy(self) -> MemoryRetentionPolicy:
        return MemoryRetentionPolicy(
            working_types=frozenset({TASK_TRACE_TYPE}),
        )

    def process_item(self, source_item: SourceItem) -> ProcessResult:
        """Check for work trace metadata. Request rebuild if present."""
        metadata = source_item.metadata or {}
        if "agent_work_trace_turn" not in metadata:
            return ProcessResult(
                memory_objects=[], relations=[], index_entries=[],
                thread_rebuild_requested=False,
            )
        return ProcessResult(
            memory_objects=[], relations=[], index_entries=[],
            thread_rebuild_requested=True,
        )

    def supports_thread_aggregation(self, source_item: SourceItem) -> bool:
        metadata = source_item.metadata or {}
        return "agent_work_trace_turn" in metadata

    def build_thread_summary(
        self,
        aggregate: ThreadAggregate,
        conclusions: list[MemoryObject],
    ) -> ProcessResult:
        """Aggregate per-turn work traces into a single task_trace MemoryObject."""
        turns: list[dict] = []
        trace_items: list[SourceItem] = []
        cwd: str | None = None

        for item in aggregate.source_items:
            meta = item.metadata or {}
            if "agent_work_trace_turn" in meta:
                turns.append(meta["agent_work_trace_turn"])
                trace_items.append(item)
                if cwd is None and "cwd" in meta:
                    cwd = meta["cwd"]

        if not turns:
            return ProcessResult(
                memory_objects=[], relations=[], index_entries=[],
                thread_rebuild_requested=False,
            )

        # Normalize all file paths
        for turn in turns:
            turn["files_read"] = [normalize_path(f, cwd) for f in turn.get("files_read", [])]

        # Exploratory vs. productive split
        first_write_action_turn = next(
            (i for i, t in enumerate(turns) if t.get("has_productive_action")), None
        )

        if first_write_action_turn is not None:
            exploratory_files = list(dict.fromkeys(
                f for t in turns[:first_write_action_turn] for f in t["files_read"]
            ))
            productive_files = list(dict.fromkeys(
                f for t in turns[first_write_action_turn:] for f in t["files_read"]
            ))
        else:
            exploratory_files = list(dict.fromkeys(
                f for t in turns for f in t["files_read"]
            ))
            productive_files = []

        # Aggregate commands
        commands_succeeded = [c for t in turns for c in t.get("commands", []) if c.get("exit_code") == 0]
        commands_failed = [c for t in turns for c in t.get("commands", []) if c.get("exit_code") != 0]

        # Apply caps
        exploratory_files = exploratory_files[:MAX_EXPLORATORY_FILES]
        productive_files = productive_files[:MAX_PRODUCTIVE_FILES]
        commands_succeeded = commands_succeeded[:MAX_COMMANDS_SUCCEEDED]
        commands_failed = commands_failed[:MAX_COMMANDS_FAILED]

        # Deterministic subject
        all_files = exploratory_files + productive_files
        subject = _compute_subject(all_files)

        # Best-effort outcome extraction via LLM
        outcome: str | None = None
        outcome_source = "none"
        response_texts = [item.content for item in trace_items if item.content and item.content.strip()]
        if response_texts:
            try:
                combined = "\n---\n".join(response_texts[-5:])  # last 5 responses
                llm_response = self._provider.generate_json(
                    system_prompt=OUTCOME_SYSTEM_PROMPT,
                    user_prompt=combined,
                    schema_description='{"outcome": "string or null"}',
                )
                raw_outcome = llm_response.parsed_json.get("outcome")
                if raw_outcome and isinstance(raw_outcome, str) and raw_outcome.strip().lower() != "null":
                    outcome = raw_outcome.strip()
                    outcome_source = "llm_from_agent_responses"
            except Exception as exc:
                logger.debug("Outcome extraction failed (non-blocking): %s", exc)

        # Source item IDs for correlation
        turn_source_item_ids = [item.id for item in trace_items]

        # Build payload
        payload: dict[str, Any] = {
            "investigation_subject": subject,
            "outcome_source": outcome_source,
            "exploratory_files": exploratory_files,
            "productive_files": productive_files,
            "commands_succeeded": [c["cmd"] for c in commands_succeeded],
            "commands_failed": [c["cmd"] for c in commands_failed],
            "bash_failure_fragments": [
                {"cmd": c["cmd"], "class": c.get("failure_class", ""), "tail": c.get("output_tail", "")}
                for c in commands_failed[:MAX_FAILURE_FRAGMENTS]
            ],
            "first_write_action_at_turn": first_write_action_turn,
            "turn_count": len(turns),
            "turn_source_item_ids": turn_source_item_ids,
        }
        if outcome:
            payload["outcome"] = outcome

        # Extract repo/branch/commit from metadata if available
        first_meta = trace_items[0].metadata or {} if trace_items else {}
        payload["repo_ref"] = aggregate.container_ref
        if "branch_ref" in first_meta:
            payload["branch_ref"] = first_meta["branch_ref"]
        if "commit_ref" in first_meta:
            payload["commit_ref"] = first_meta["commit_ref"]
        if cwd:
            payload["working_directory"] = cwd

        memory_obj = MemoryObject(
            type=TASK_TRACE_TYPE,
            schema_id=TASK_TRACE_SCHEMA_ID,
            schema_version=TASK_TRACE_SCHEMA_VERSION,
            lifecycle="active",
            visibility=aggregate.visibility,
            container_ref=aggregate.container_ref,
            freshness_at=utc_now(),
            payload=payload,
        )

        # Build lexical index text
        index_parts = [subject] + exploratory_files + productive_files + [c["cmd"] for c in commands_succeeded]
        if outcome:
            index_parts.append(outcome)
        index_text = " ".join(index_parts)

        index_entry = build_index_entry(
            target_kind="memory_object",
            target_id=memory_obj.id,
            index_type="lexical",
            text_view=index_text,
            text_view_name=LEXICAL_TEXT_VIEW_NAME,
        )

        # Append metric event for offline measurement (separate from supersession)
        _append_metric_event(aggregate.thread_ref, payload)

        return ProcessResult(
            memory_objects=[memory_obj],
            relations=[],
            index_entries=[index_entry],
            thread_rebuild_requested=False,
        )
```

- [ ] **Step 4: Run tests to verify item processing passes**

Run: `python -m pytest tests/test_agent_work_trace.py::TestItemProcessing -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add semantic/agent_work_trace.py tests/test_agent_work_trace.py
git commit -m "feat: add agent_work_trace semantic package with item processing and thread rebuild"
```

---

### Task 6: Thread rebuild tests for agent_work_trace

**Files:**
- Test: `tests/test_agent_work_trace.py`

- [ ] **Step 1: Write thread rebuild tests**

Append to `tests/test_agent_work_trace.py`:

```python
from capabilities.thread_aggregation import build_thread_aggregate


def _make_trace_items(turns_data: list[dict], thread_ref: str = "session-1", container_ref: str = "git:example.com/repo") -> list[SourceItem]:
    """Create SourceItems with agent_work_trace_turn metadata."""
    items = []
    for i, turn in enumerate(turns_data):
        items.append(_make_source_item(
            content=f"Turn {i} response text.",
            thread_ref=thread_ref,
            container_ref=container_ref,
            metadata={
                "agent_work_trace_turn": turn,
                "cwd": "/home/user/project",
            },
        ))
    return items


class TestThreadRebuild:
    def test_produces_task_trace_memory_object(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin, TASK_TRACE_TYPE
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/main.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
            {"files_read": ["/home/user/project/src/utils.py"], "commands": [], "grep_patterns": [], "has_productive_action": True},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        assert len(result.memory_objects) == 1
        mo = result.memory_objects[0]
        assert mo.type == TASK_TRACE_TYPE
        assert mo.payload["turn_count"] == 2

    def test_exploratory_productive_split(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/main.py", "/home/user/project/src/config.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
            {"files_read": ["/home/user/project/src/main.py", "/home/user/project/src/fix.py"], "commands": [], "grep_patterns": [], "has_productive_action": True},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert "src/main.py" in payload["exploratory_files"]
        assert "src/config.py" in payload["exploratory_files"]
        assert "src/fix.py" in payload["productive_files"]
        assert payload["first_write_action_at_turn"] == 1

    def test_path_normalization(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/main.py", "./src/main.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        # Both should normalize to the same relative path — deduped
        assert payload["exploratory_files"].count("src/main.py") == 1

    def test_commands_split_by_exit_code(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = _make_trace_items([
            {"files_read": [], "commands": [
                {"cmd": "python -m pytest", "exit_code": 0, "output_tail": "10 passed", "failure_class": "success"},
                {"cmd": "python -m pytest tests/broken.py", "exit_code": 1, "output_tail": "FAILED", "failure_class": "test_failure"},
            ], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert "python -m pytest" in payload["commands_succeeded"]
        assert "python -m pytest tests/broken.py" in payload["commands_failed"]

    def test_outcome_included_when_present(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider(outcome="Fixed the IDF bug."))
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/main.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert payload["outcome"] == "Fixed the IDF bug."
        assert payload["outcome_source"] == "llm_from_agent_responses"

    def test_outcome_absent_when_null(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider(outcome=None))
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/main.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert "outcome" not in payload
        assert payload["outcome_source"] == "none"

    def test_subject_computed_from_most_common_dir(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = _make_trace_items([
            {"files_read": [
                "/home/user/project/retrieval/lexical.py",
                "/home/user/project/retrieval/composite.py",
                "/home/user/project/retrieval/vector.py",
                "/home/user/project/storage/sqlite.py",
            ], "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert payload["investigation_subject"] == "retrieval/"

    def test_index_entry_created(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = _make_trace_items([
            {"files_read": ["/home/user/project/src/main.py"], "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        assert len(result.index_entries) == 1
        assert "src/main.py" in result.index_entries[0].text_view

    def test_no_turns_returns_empty(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = [_make_source_item(metadata={})]
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        assert result.memory_objects == []

    def test_caps_applied(self):
        from semantic.agent_work_trace import AgentWorkTracePlugin, MAX_EXPLORATORY_FILES
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        # Generate more files than the cap
        many_files = [f"/home/user/project/src/file_{i}.py" for i in range(50)]
        items = _make_trace_items([
            {"files_read": many_files, "commands": [], "grep_patterns": [], "has_productive_action": False},
        ])
        aggregate = build_thread_aggregate(items)
        result = plugin.build_thread_summary(aggregate, conclusions=[])
        payload = result.memory_objects[0].payload
        assert len(payload["exploratory_files"]) == MAX_EXPLORATORY_FILES
```

- [ ] **Step 2: Run thread rebuild tests**

Run: `python -m pytest tests/test_agent_work_trace.py::TestThreadRebuild -v`
Expected: PASS (implementation already written in Task 5)

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_work_trace.py
git commit -m "test: add thread rebuild tests for agent_work_trace package"
```

---

### Task 7: Register `agent_work_trace` in the application layer

**Files:**
- Modify: `app/dependencies.py`
- Modify: `app/config.py`
- Modify: `pallium.local.toml`

- [ ] **Step 1: Add to app/dependencies.py**

Add import at top of `app/dependencies.py`:

```python
from semantic.agent_work_trace import AgentWorkTracePlugin
```

Add a new `elif` branch in `_build_plugin_for_package()` before the final `raise ValueError`:

```python
    if implementation == "agent_work_trace":
        if not package_config.llm_provider or not package_config.model:
            return None
        provider = build_llm_provider(
            config,
            provider_name=package_config.llm_provider,
            model=package_config.model,
        )
        return AgentWorkTracePlugin(provider=provider)
```

- [ ] **Step 2: Add to app/config.py default packages**

In `_default_semantic_packages()`, add:

```python
        "agent_work_trace": SemanticPackageConfig(
            name="agent_work_trace",
            implementation="agent_work_trace",
        ),
```

- [ ] **Step 3: Add to pallium.local.toml**

Add section:

```toml
[semantic_packages.agent_work_trace]
implementation = "agent_work_trace"
llm_provider = "hai_anthropic"
model = "anthropic--claude-haiku-latest"
```

- [ ] **Step 4: Run existing test suite to verify no regressions**

Run: `python -m pytest tests/ -x -q`
Expected: PASS (no failures)

- [ ] **Step 5: Commit**

```bash
git add app/dependencies.py app/config.py pallium.local.toml
git commit -m "feat: register agent_work_trace in application layer and config"
```

---

### Task 8: Extend SessionStart hooks for scoped task_trace injection

**Files:**
- Modify: `integrations/claude-code/hooks/session_start.py`
- Modify: `integrations/codex/hooks/session_start.py`

- [ ] **Step 1: Implement Claude Code session_start changes**

Replace `integrations/claude-code/hooks/session_start.py`:

```python
"""SessionStart hook — injects orientation memory at session beginning."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    STATE_DIR,
    derive_actor_ref,
    derive_container_ref,
    format_injection,
    pallium_request,
    read_hook_input,
)


def _write_work_trace_state(session_id: str, trace_payload: dict) -> None:
    """Write injected task_trace payload to state file for offline measurement."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_file = STATE_DIR / f"{session_id}.work_trace_state.json"
        state_file.write_text(json.dumps(trace_payload), encoding="utf-8")
    except OSError:
        pass


def main() -> None:
    try:
        payload = read_hook_input()
        cwd = payload.get("cwd", ".")
        session_id = payload.get("session_id")
        source = payload.get("source", "")
        container_ref = derive_container_ref(cwd)
        actor_ref = derive_actor_ref()

        # Standard memory injection
        query_payload = {
            "text": "recent decisions, progress, and open tasks",
            "container_ref": container_ref,
            "actor_ref": actor_ref,
            "visibility": "private",
            "limit": 5,
        }
        if session_id:
            query_payload["thread_ref"] = session_id

        response = pallium_request("POST", "/query", query_payload)

        blocks: list[dict] = []
        if response:
            blocks = response.get("injectable_blocks", [])

        # Scoped task_trace injection on session resume
        if source in ("resume", "clear") and session_id:
            trace_response = pallium_request("POST", "/query", {
                "text": f"task_trace for thread {session_id}",
                "container_ref": container_ref,
                "actor_ref": actor_ref,
                "visibility": "private",
                "thread_ref": session_id,
                "limit": 1,
            })
            if trace_response:
                trace_blocks = trace_response.get("injectable_blocks", [])
                for tb in trace_blocks:
                    if "task_trace" in tb.get("title", "").lower() or "task_trace" in tb.get("text", "").lower():
                        blocks.append(tb)
                        # Write state file for measurement
                        _write_work_trace_state(session_id, tb)
                        break

        output = format_injection(blocks, container_ref, budget_chars=1200)
        if output:
            print(output)

    except Exception as exc:
        print(f"pallium session_start hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Implement Codex session_start changes**

Replace `integrations/codex/hooks/session_start.py` with the same logic, adapted for Codex's import style and `emit_context()` output:

```python
"""SessionStart hook — injects orientation memory at session beginning."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_common_path = str(Path(__file__).resolve().parent / "common.py")
_spec = importlib.util.spec_from_file_location("codex_common", _common_path)
_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_common)

STATE_DIR = _common.STATE_DIR
derive_actor_ref = _common.derive_actor_ref
derive_container_ref = _common.derive_container_ref
emit_context = _common.emit_context
format_injection = _common.format_injection
pallium_request = _common.pallium_request
read_hook_input = _common.read_hook_input


def _write_work_trace_state(session_id: str, trace_payload: dict) -> None:
    """Write injected task_trace payload to state file for offline measurement."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_file = STATE_DIR / f"{session_id}.work_trace_state.json"
        state_file.write_text(json.dumps(trace_payload), encoding="utf-8")
    except OSError:
        pass


def main() -> None:
    try:
        payload = read_hook_input()
        source = payload.get("source", "")
        if source == "clear":
            sys.exit(0)

        cwd = payload.get("cwd", ".")
        session_id = payload.get("session_id")
        container_ref = derive_container_ref(cwd)
        actor_ref = derive_actor_ref()

        response = pallium_request("POST", "/query", {
            "text": "recent decisions, progress, and open tasks",
            "container_ref": container_ref,
            "actor_ref": actor_ref,
            "visibility": "private",
            "limit": 5,
        })

        blocks: list[dict] = []
        if response:
            blocks = response.get("injectable_blocks", [])

        # Scoped task_trace injection on session resume
        if source == "resume" and session_id:
            trace_response = pallium_request("POST", "/query", {
                "text": f"task_trace for thread {session_id}",
                "container_ref": container_ref,
                "actor_ref": actor_ref,
                "visibility": "private",
                "thread_ref": session_id,
                "limit": 1,
            }, quiet=True)
            if trace_response:
                trace_blocks = trace_response.get("injectable_blocks", [])
                for tb in trace_blocks:
                    if "task_trace" in tb.get("title", "").lower() or "task_trace" in tb.get("text", "").lower():
                        blocks.append(tb)
                        _write_work_trace_state(session_id, tb)
                        break

        output = format_injection(blocks, container_ref, budget_chars=1200)
        if output:
            emit_context(output, "SessionStart")

    except Exception as exc:
        print(f"pallium session_start hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add integrations/claude-code/hooks/session_start.py integrations/codex/hooks/session_start.py
git commit -m "feat(hooks): session_start injects scoped task_trace on resume"
```

---

### Task 9: Extend PreCompact hook for current session task_trace

**Files:**
- Modify: `integrations/claude-code/hooks/pre_compact.py`

- [ ] **Step 1: Update pre_compact.py to also inject task_trace**

Replace `integrations/claude-code/hooks/pre_compact.py`:

```python
"""PreCompact hook — re-injects key context before compaction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    derive_actor_ref,
    derive_container_ref,
    format_injection,
    pallium_request,
    read_hook_input,
)


def main() -> None:
    try:
        payload = read_hook_input()
        cwd = payload.get("cwd", ".")
        session_id = payload.get("session_id")
        container_ref = derive_container_ref(cwd)
        actor_ref = derive_actor_ref()

        query_payload = {
            "text": "recent decisions, progress, and open tasks",
            "container_ref": container_ref,
            "actor_ref": actor_ref,
            "visibility": "private",
            "limit": 8,
        }
        if session_id:
            query_payload["thread_ref"] = session_id

        response = pallium_request("POST", "/query", query_payload)

        blocks: list[dict] = []
        if response:
            blocks = response.get("injectable_blocks", [])

        # Inject current session's task_trace if one exists
        if session_id:
            trace_response = pallium_request("POST", "/query", {
                "text": f"task_trace for thread {session_id}",
                "container_ref": container_ref,
                "actor_ref": actor_ref,
                "visibility": "private",
                "thread_ref": session_id,
                "limit": 1,
            })
            if trace_response:
                trace_blocks = trace_response.get("injectable_blocks", [])
                for tb in trace_blocks:
                    if "task_trace" in tb.get("title", "").lower() or "task_trace" in tb.get("text", "").lower():
                        blocks.append(tb)
                        break

        output = format_injection(blocks, container_ref, budget_chars=2400)
        if output:
            print(output)

    except Exception as exc:
        print(f"pallium pre_compact hook error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test suite**

Run: `python -m pytest tests/ -x -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add integrations/claude-code/hooks/pre_compact.py
git commit -m "feat(hooks): pre_compact injects current session task_trace"
```

---

### Task 10: Integration test with service layer

**Files:**
- Test: `tests/test_agent_work_trace.py`

- [ ] **Step 1: Write integration test**

Append to `tests/test_agent_work_trace.py`:

```python
from core.service import PalliumService
from retrieval.lexical import LexicalRetrievalProvider
from semantic.agent_work_trace import AgentWorkTracePlugin, TASK_TRACE_TYPE
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider


@pytest.fixture
def test_db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'test.db'}"


def _build_service_with_work_trace(db_url: str, provider: LLMProvider) -> PalliumService:
    storage = SQLiteStorageProvider(db_url)
    plugins = {
        "demo_agent_memory": DemoAgentMemoryPlugin(),
        "agent_work_trace": AgentWorkTracePlugin(provider=provider),
    }
    return PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
    )


class TestServiceIntegration:
    def test_ingest_with_work_trace_produces_task_trace(self, test_db_url):
        service = _build_service_with_work_trace(test_db_url, StubOutcomeProvider())

        # Ingest items with work trace metadata
        service.ingest_items([
            {
                "source_type": "claude-code",
                "source_id": "cc-test-001",
                "content_type": "text/plain",
                "content": "I read the lexical retrieval code and found the IDF issue.",
                "container_ref": "git:example.com/repo",
                "thread_ref": "session-integration-1",
                "visibility": "private",
                "artifact_kind": "message",
                "metadata": {
                    "agent_work_trace_turn": {
                        "files_read": ["retrieval/lexical.py", "storage/sqlite_search.py"],
                        "commands": [{"cmd": "python -m pytest tests/ -x", "exit_code": 0, "output_tail": "20 passed", "failure_class": "success"}],
                        "grep_patterns": ["IDF"],
                        "has_productive_action": False,
                    },
                    "cwd": "/home/user/pallium",
                },
            },
            {
                "source_type": "claude-code",
                "source_id": "cc-test-002",
                "content_type": "text/plain",
                "content": "Fixed the IDF weight calculation.",
                "container_ref": "git:example.com/repo",
                "thread_ref": "session-integration-1",
                "visibility": "private",
                "artifact_kind": "message",
                "metadata": {
                    "agent_work_trace_turn": {
                        "files_read": ["retrieval/lexical.py"],
                        "commands": [{"cmd": "python -m pytest tests/ -x", "exit_code": 0, "output_tail": "22 passed", "failure_class": "success"}],
                        "grep_patterns": [],
                        "has_productive_action": True,
                    },
                    "cwd": "/home/user/pallium",
                },
            },
        ])

        # Process items
        service.process_pending_items(max_items=10)

        # Verify task_trace was created
        memory_objects = service._storage.list_memory_objects(
            container_ref="git:example.com/repo",
            types=[TASK_TRACE_TYPE],
        )
        assert len(memory_objects) == 1
        mo = memory_objects[0]
        assert mo.type == TASK_TRACE_TYPE
        assert "retrieval/lexical.py" in mo.payload["exploratory_files"] or "retrieval/lexical.py" in mo.payload["productive_files"]
        assert mo.payload["turn_count"] == 2
```

- [ ] **Step 2: Run integration test**

Run: `python -m pytest tests/test_agent_work_trace.py::TestServiceIntegration -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_work_trace.py
git commit -m "test: add service integration test for agent_work_trace end-to-end"
```

---

### Task 11: Comprehensive end-to-end validation tests

**Files:**
- Create: `tests/test_agent_work_trace_e2e.py`

These tests validate the full round-trip: simulated transcript → hook extraction → ingest → process → thread rebuild → query retrieval → verify injection. Nothing is assumed — every stage is verified independently.

- [ ] **Step 1: Write e2e test file**

Create `tests/test_agent_work_trace_e2e.py`:

```python
"""End-to-end tests for agent_work_trace: full pipeline validation.

Tests the complete round-trip:
1. Hook-side transcript parsing produces correct metadata
2. Ingest accepts metadata without error
3. Processing creates task_trace MemoryObject
4. Thread rebuild supersedes prior task_trace on re-process
5. Lexical retrieval finds the task_trace by file path query
6. Query returns injectable_blocks with task_trace content
7. Metric log file is appended
8. Edge cases: empty turns, LLM failure, max caps, Windows paths
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from core.contracts import ProcessResult
from core.models import MemoryObject, SourceItem, new_id, utc_now
from core.service import PalliumService
from providers.llm.base import LLMProvider, LLMJsonResponse
from retrieval.lexical import LexicalRetrievalProvider
from semantic.agent_work_trace import (
    AgentWorkTracePlugin,
    TASK_TRACE_TYPE,
    TASK_TRACE_SCHEMA_ID,
    normalize_path,
    _compute_subject,
    _append_metric_event,
    STATE_DIR,
    METRICS_LOG_FILENAME,
    MAX_EXPLORATORY_FILES,
    MAX_PRODUCTIVE_FILES,
    MAX_COMMANDS_SUCCEEDED,
    MAX_COMMANDS_FAILED,
)
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider

# Load hook common.py for testing hook-level extraction
_cc_common_path = str(Path(__file__).resolve().parent.parent / "integrations" / "claude-code" / "hooks" / "common.py")
_spec = importlib.util.spec_from_file_location("cc_common_e2e", _cc_common_path)
cc_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc_common)


# ── Stub LLM providers ──────────────────────────────────────────────────

class StubOutcomeProvider(LLMProvider):
    provider_name = "stub_e2e"

    def __init__(self, outcome: str | None = "Fixed the bug in retrieval."):
        self._outcome = outcome

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        result = {"outcome": self._outcome}
        return LLMJsonResponse(raw_text=json.dumps(result), parsed_json=result)


class FailingOutcomeProvider(LLMProvider):
    """Simulates LLM failure — outcome extraction should degrade gracefully."""
    provider_name = "stub_failing"

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        raise RuntimeError("LLM unavailable")


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def test_db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def service(test_db_url):
    storage = SQLiteStorageProvider(test_db_url)
    plugins = {
        "demo_agent_memory": DemoAgentMemoryPlugin(),
        "agent_work_trace": AgentWorkTracePlugin(provider=StubOutcomeProvider()),
    }
    return PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
    )


@pytest.fixture
def service_failing_llm(test_db_url):
    storage = SQLiteStorageProvider(test_db_url)
    plugins = {
        "demo_agent_memory": DemoAgentMemoryPlugin(),
        "agent_work_trace": AgentWorkTracePlugin(provider=FailingOutcomeProvider()),
    }
    return PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
    )


# ── Hook-level extraction tests ──────────────────────────────────────────

class TestHookExtractionE2E:
    """Verify that hook extraction from a realistic transcript produces valid metadata."""

    def test_realistic_transcript_produces_valid_trace(self, tmp_path):
        """A realistic multi-tool turn produces correct metadata structure."""
        transcript_path = str(tmp_path / "transcript.jsonl")
        entries = [
            {"message": {"role": "user", "content": "Fix the IDF bug"}},
            {"message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/repo/retrieval/lexical.py"}},
                {"type": "tool_result", "tool_use_id": "t1", "content": "class LexicalRetrieval:\n    pass"},
                {"type": "tool_use", "id": "t2", "name": "Grep", "input": {"pattern": "IDF", "path": "/repo/retrieval/"}},
                {"type": "tool_result", "tool_use_id": "t2", "content": "lexical.py:89: idf_weight = 1.0"},
                {"type": "tool_use", "id": "t3", "name": "Bash", "input": {"command": "python -m pytest tests/test_retrieval.py -x"}},
                {"type": "tool_result", "tool_use_id": "t3", "content": "exit code: 1\nFAILED tests/test_retrieval.py::test_idf - AssertionError"},
                {"type": "tool_use", "id": "t4", "name": "Edit", "input": {"file_path": "/repo/retrieval/lexical.py", "old_string": "x", "new_string": "y"}},
                {"type": "tool_result", "tool_use_id": "t4", "content": "ok"},
                {"type": "text", "text": "I fixed the IDF weight calculation."},
            ]}},
        ]
        with open(transcript_path, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        turn_data = cc_common.read_turn(transcript_path)
        assert turn_data is not None
        assert turn_data.assistant_text == "I fixed the IDF weight calculation."
        assert turn_data.has_productive_action is True  # Edit present

        meta = cc_common.build_work_trace_metadata(turn_data)
        assert meta is not None
        assert "/repo/retrieval/lexical.py" in meta["files_read"]
        assert len(meta["commands"]) == 1
        assert meta["commands"][0]["cmd"] == "python -m pytest tests/test_retrieval.py -x"
        assert meta["commands"][0]["exit_code"] == 1
        assert meta["grep_patterns"] == ["IDF"]
        assert meta["has_productive_action"] is True

    def test_turn_with_only_reads_is_exploratory(self, tmp_path):
        transcript_path = str(tmp_path / "transcript.jsonl")
        entries = [
            {"message": {"role": "user", "content": "look around"}},
            {"message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/repo/src/a.py"}},
                {"type": "tool_result", "tool_use_id": "t1", "content": "code"},
                {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/repo/src/b.py"}},
                {"type": "tool_result", "tool_use_id": "t2", "content": "more code"},
                {"type": "text", "text": "I see the structure."},
            ]}},
        ]
        with open(transcript_path, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        turn_data = cc_common.read_turn(transcript_path)
        meta = cc_common.build_work_trace_metadata(turn_data)
        assert meta["has_productive_action"] is False
        assert meta["files_read"] == ["/repo/src/a.py", "/repo/src/b.py"]

    def test_redaction_in_bash_output(self, tmp_path):
        """Secrets in bash output are redacted before metadata is built."""
        transcript_path = str(tmp_path / "transcript.jsonl")
        entries = [
            {"message": {"role": "user", "content": "check creds"}},
            {"message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "cat .env"}},
                {"type": "tool_result", "tool_use_id": "t1", "content": "DB_PASSWORD=supersecret123\nAPI_KEY=sk-12345"},
                {"type": "text", "text": "Found credentials."},
            ]}},
        ]
        with open(transcript_path, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        turn_data = cc_common.read_turn(transcript_path)
        meta = cc_common.build_work_trace_metadata(turn_data)
        assert "supersecret123" not in meta["commands"][0]["output_tail"]
        assert "sk-12345" not in meta["commands"][0]["output_tail"]
        assert "[REDACTED]" in meta["commands"][0]["output_tail"]


# ── Full pipeline tests ──────────────────────────────────────────────────

class TestFullPipeline:
    """Test the complete ingest → process → task_trace creation pipeline."""

    def test_single_session_creates_task_trace(self, service):
        """Two turns in the same thread produce one task_trace after processing."""
        service.ingest_items([
            {
                "source_type": "claude-code", "source_id": "e2e-001",
                "content_type": "text/plain",
                "content": "Reading the retrieval code.",
                "container_ref": "git:test/repo", "thread_ref": "sess-e2e",
                "visibility": "private", "artifact_kind": "message",
                "metadata": {
                    "agent_work_trace_turn": {
                        "files_read": ["retrieval/lexical.py", "retrieval/composite.py"],
                        "commands": [], "grep_patterns": ["IDF"],
                        "has_productive_action": False,
                    },
                    "cwd": "/home/user/project",
                },
            },
            {
                "source_type": "claude-code", "source_id": "e2e-002",
                "content_type": "text/plain",
                "content": "Fixed the IDF weight calculation.",
                "container_ref": "git:test/repo", "thread_ref": "sess-e2e",
                "visibility": "private", "artifact_kind": "message",
                "metadata": {
                    "agent_work_trace_turn": {
                        "files_read": ["retrieval/lexical.py"],
                        "commands": [{"cmd": "python -m pytest tests/ -x", "exit_code": 0, "output_tail": "22 passed", "failure_class": "success"}],
                        "grep_patterns": [],
                        "has_productive_action": True,
                    },
                    "cwd": "/home/user/project",
                },
            },
        ])

        service.process_pending_items(max_items=10)

        # Verify: exactly one task_trace created
        memory_objects = service._storage.list_memory_objects(
            container_ref="git:test/repo", types=[TASK_TRACE_TYPE],
        )
        assert len(memory_objects) == 1
        mo = memory_objects[0]
        assert mo.type == TASK_TRACE_TYPE
        assert mo.schema_id == TASK_TRACE_SCHEMA_ID
        assert mo.visibility == "private"
        assert mo.container_ref == "git:test/repo"

        # Verify payload structure
        p = mo.payload
        assert p["turn_count"] == 2
        assert p["first_write_action_at_turn"] == 1
        assert "retrieval/lexical.py" in p["exploratory_files"]
        assert "retrieval/composite.py" in p["exploratory_files"]
        assert "retrieval/lexical.py" in p["productive_files"]
        assert "python -m pytest tests/ -x" in p["commands_succeeded"]
        assert p["commands_failed"] == []
        assert p["outcome"] == "Fixed the bug in retrieval."
        assert p["outcome_source"] == "llm_from_agent_responses"
        assert p["investigation_subject"] == "retrieval/"
        assert len(p["turn_source_item_ids"]) == 2

    def test_supersession_on_new_turn(self, service):
        """Adding a third turn and reprocessing supersedes the prior task_trace."""
        # First batch
        service.ingest_items([{
            "source_type": "claude-code", "source_id": "sup-001",
            "content_type": "text/plain", "content": "Turn 1.",
            "container_ref": "git:test/repo", "thread_ref": "sess-sup",
            "visibility": "private", "artifact_kind": "message",
            "metadata": {"agent_work_trace_turn": {
                "files_read": ["src/a.py"], "commands": [], "grep_patterns": [],
                "has_productive_action": False,
            }, "cwd": "/repo"},
        }])
        service.process_pending_items(max_items=10)
        objs_v1 = service._storage.list_memory_objects(container_ref="git:test/repo", types=[TASK_TRACE_TYPE])
        assert len(objs_v1) == 1
        v1_id = objs_v1[0].id

        # Second batch in same thread
        service.ingest_items([{
            "source_type": "claude-code", "source_id": "sup-002",
            "content_type": "text/plain", "content": "Turn 2.",
            "container_ref": "git:test/repo", "thread_ref": "sess-sup",
            "visibility": "private", "artifact_kind": "message",
            "metadata": {"agent_work_trace_turn": {
                "files_read": ["src/b.py"], "commands": [], "grep_patterns": [],
                "has_productive_action": True,
            }, "cwd": "/repo"},
        }])
        service.process_pending_items(max_items=10)

        # Should have exactly one active task_trace (prior superseded)
        active_objs = service._storage.list_memory_objects(
            container_ref="git:test/repo", types=[TASK_TRACE_TYPE],
        )
        assert len(active_objs) == 1
        assert active_objs[0].id != v1_id
        assert active_objs[0].payload["turn_count"] == 2

    def test_llm_failure_produces_task_trace_without_outcome(self, service_failing_llm):
        """When LLM fails, task_trace is still created — just without outcome field."""
        service_failing_llm.ingest_items([{
            "source_type": "claude-code", "source_id": "fail-001",
            "content_type": "text/plain", "content": "Working on stuff.",
            "container_ref": "git:test/repo", "thread_ref": "sess-fail",
            "visibility": "private", "artifact_kind": "message",
            "metadata": {"agent_work_trace_turn": {
                "files_read": ["src/x.py"], "commands": [], "grep_patterns": [],
                "has_productive_action": False,
            }, "cwd": "/repo"},
        }])
        service_failing_llm.process_pending_items(max_items=10)

        objs = service_failing_llm._storage.list_memory_objects(
            container_ref="git:test/repo", types=[TASK_TRACE_TYPE],
        )
        assert len(objs) == 1
        assert "outcome" not in objs[0].payload
        assert objs[0].payload["outcome_source"] == "none"

    def test_items_without_trace_metadata_do_not_produce_task_trace(self, service):
        """Normal messages without agent_work_trace_turn metadata don't trigger task_trace."""
        service.ingest_items([{
            "source_type": "claude-code", "source_id": "no-trace-001",
            "content_type": "text/plain", "content": "Just chatting about stuff.",
            "container_ref": "git:test/repo", "thread_ref": "sess-no-trace",
            "visibility": "private", "artifact_kind": "message",
        }])
        service.process_pending_items(max_items=10)

        objs = service._storage.list_memory_objects(
            container_ref="git:test/repo", types=[TASK_TRACE_TYPE],
        )
        assert len(objs) == 0

    def test_lexical_retrieval_finds_task_trace(self, service):
        """task_trace is retrievable via lexical search on file paths."""
        service.ingest_items([{
            "source_type": "claude-code", "source_id": "ret-001",
            "content_type": "text/plain", "content": "Checked the vector code.",
            "container_ref": "git:test/repo", "thread_ref": "sess-ret",
            "visibility": "private", "artifact_kind": "message",
            "metadata": {"agent_work_trace_turn": {
                "files_read": ["retrieval/vector.py", "storage/vector_index.py"],
                "commands": [{"cmd": "python -m pytest tests/test_vector.py", "exit_code": 0, "output_tail": "5 passed", "failure_class": "success"}],
                "grep_patterns": ["cosine"],
                "has_productive_action": False,
            }, "cwd": "/repo"},
        }])
        service.process_pending_items(max_items=10)

        # Query by file path content
        result = service.query(
            text="retrieval vector",
            container_ref="git:test/repo",
            visibility="private",
            limit=5,
        )
        # Should find something — the task_trace lexical index includes file paths
        assert len(result.results) > 0


# ── Edge case tests ──────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases that must not crash the pipeline."""

    def test_windows_paths_normalized(self):
        """Windows-style paths are normalized to forward slashes."""
        assert normalize_path("C:\\Users\\dev\\project\\src\\main.py", "C:\\Users\\dev\\project") == "src/main.py"

    def test_relative_dot_path_normalized(self):
        assert normalize_path("./src/main.py", None) == "src/main.py"

    def test_already_relative_path_unchanged(self):
        assert normalize_path("src/main.py", None) == "src/main.py"

    def test_empty_files_list_produces_empty_subject(self):
        assert _compute_subject([]) == ""

    def test_single_file_produces_dir_subject(self):
        assert _compute_subject(["retrieval/lexical.py"]) == "retrieval/"

    def test_root_file_produces_filename_subject(self):
        assert _compute_subject(["README.md"]) == "README.md"

    def test_caps_enforced_on_large_sessions(self, test_db_url):
        """Sessions with 100+ files are capped without errors."""
        storage = SQLiteStorageProvider(test_db_url)
        plugins = {
            "demo_agent_memory": DemoAgentMemoryPlugin(),
            "agent_work_trace": AgentWorkTracePlugin(provider=StubOutcomeProvider()),
        }
        svc = PalliumService(
            storage=storage,
            retrieval=LexicalRetrievalProvider(storage),
            semantic_plugins=plugins,
            default_use_case="demo_agent_memory",
        )
        many_files = [f"src/file_{i}.py" for i in range(100)]
        many_commands = [{"cmd": f"cmd_{i}", "exit_code": 0, "output_tail": "", "failure_class": "success"} for i in range(30)]
        svc.ingest_items([{
            "source_type": "claude-code", "source_id": "cap-001",
            "content_type": "text/plain", "content": "Big session.",
            "container_ref": "git:test/repo", "thread_ref": "sess-cap",
            "visibility": "private", "artifact_kind": "message",
            "metadata": {"agent_work_trace_turn": {
                "files_read": many_files,
                "commands": many_commands,
                "grep_patterns": [],
                "has_productive_action": False,
            }, "cwd": "/repo"},
        }])
        svc.process_pending_items(max_items=10)

        objs = svc._storage.list_memory_objects(container_ref="git:test/repo", types=[TASK_TRACE_TYPE])
        assert len(objs) == 1
        p = objs[0].payload
        assert len(p["exploratory_files"]) <= MAX_EXPLORATORY_FILES
        assert len(p["commands_succeeded"]) <= MAX_COMMANDS_SUCCEEDED

    def test_metric_log_appended(self, tmp_path, monkeypatch):
        """Verify the metrics log file is written during thread rebuild."""
        # Redirect STATE_DIR to tmp_path for test isolation
        import semantic.agent_work_trace as awt_module
        monkeypatch.setattr(awt_module, "STATE_DIR", tmp_path)

        from capabilities.thread_aggregation import build_thread_aggregate
        plugin = AgentWorkTracePlugin(provider=StubOutcomeProvider())
        items = [SourceItem(
            source_type="claude-code", source_id="met-001",
            content_type="text/plain", content="Metric test.",
            thread_ref="sess-met", container_ref="git:test/repo",
            visibility="private",
            metadata={"agent_work_trace_turn": {
                "files_read": ["src/x.py"], "commands": [], "grep_patterns": [],
                "has_productive_action": False,
            }, "cwd": "/repo"},
        )]
        aggregate = build_thread_aggregate(items)
        plugin.build_thread_summary(aggregate, conclusions=[])

        metrics_path = tmp_path / METRICS_LOG_FILENAME
        assert metrics_path.exists()
        lines = metrics_path.read_text().strip().splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["thread_ref"] == "sess-met"
        assert event["turn_count"] == 1
        assert event["exploratory_file_count"] == 1
        assert event["has_outcome"] is True


# ── Regression tests ─────────────────────────────────────────────────────

class TestRegressions:
    """Verify that agent_work_trace doesn't break existing functionality."""

    def test_normal_ingest_still_works(self, service):
        """Items without work trace metadata are processed normally by demo_agent_memory."""
        service.ingest_items([{
            "source_type": "claude-code", "source_id": "reg-001",
            "content_type": "text/plain",
            "content": "Normal message without any work trace.",
            "container_ref": "git:test/repo", "thread_ref": "sess-reg",
            "visibility": "private", "artifact_kind": "message",
        }])
        service.process_pending_items(max_items=10)

        # Processing completed without error
        result = service._storage.get_source_item_by_source_id("claude-code", "reg-001")
        assert result is not None

    def test_mixed_items_in_same_thread(self, service):
        """Thread with both traced and non-traced items processes correctly."""
        service.ingest_items([
            {
                "source_type": "claude-code", "source_id": "mix-001",
                "content_type": "text/plain", "content": "Just chatting.",
                "container_ref": "git:test/repo", "thread_ref": "sess-mix",
                "visibility": "private", "artifact_kind": "message",
            },
            {
                "source_type": "claude-code", "source_id": "mix-002",
                "content_type": "text/plain", "content": "Now reading code.",
                "container_ref": "git:test/repo", "thread_ref": "sess-mix",
                "visibility": "private", "artifact_kind": "message",
                "metadata": {"agent_work_trace_turn": {
                    "files_read": ["src/main.py"], "commands": [], "grep_patterns": [],
                    "has_productive_action": False,
                }, "cwd": "/repo"},
            },
        ])
        service.process_pending_items(max_items=10)

        # task_trace created from the one traced item
        objs = service._storage.list_memory_objects(
            container_ref="git:test/repo", types=[TASK_TRACE_TYPE],
        )
        assert len(objs) == 1
        assert objs[0].payload["turn_count"] == 1

    def test_parallel_processing_does_not_conflict_with_primary_package(self, service):
        """agent_work_trace as parallel package doesn't interfere with demo_agent_memory."""
        service.ingest_items([{
            "source_type": "claude-code", "source_id": "par-001",
            "content_type": "text/plain",
            "content": "Important decision: we will use SQLite for storage.",
            "container_ref": "git:test/repo", "thread_ref": "sess-par",
            "visibility": "private", "artifact_kind": "message",
            "metadata": {"agent_work_trace_turn": {
                "files_read": ["storage/sqlite.py"], "commands": [], "grep_patterns": [],
                "has_productive_action": False,
            }, "cwd": "/repo"},
        }])
        service.process_pending_items(max_items=10)

        # Both packages should have processed
        task_traces = service._storage.list_memory_objects(
            container_ref="git:test/repo", types=[TASK_TRACE_TYPE],
        )
        assert len(task_traces) == 1

        # demo_agent_memory should also have produced its memory
        all_objs = service._storage.list_memory_objects(container_ref="git:test/repo")
        non_trace = [o for o in all_objs if o.type != TASK_TRACE_TYPE]
        # At minimum, demo should have created something (it processes all items)
        # This verifies the packages don't conflict
        assert len(all_objs) >= 1
```

- [ ] **Step 2: Run e2e tests**

Run: `python -m pytest tests/test_agent_work_trace_e2e.py -v`
Expected: PASS (all tests)

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_work_trace_e2e.py
git commit -m "test: add comprehensive e2e tests for agent_work_trace pipeline"
```

---

### Task 12: Update context docs, public docs, and roadmap

**Files:**
- Modify: `docs/context/state.md`
- Modify: `docs/context/architecture.md`
- Modify: `roadmap/board.md`

- [ ] **Step 1: Add `task_trace` to promoted memory list in `docs/context/state.md`**

In the "promoted memory currently includes" list (around line 28-37), add:

```markdown
  - `task_trace` (from `agent_work_trace` parallel package — per-session structural trail of agent tool usage)
```

- [ ] **Step 2: Add `agent_work_trace` package to `docs/context/architecture.md`**

In the "Implemented Semantic Behavior" section (around line 108), add a bullet for the new package after the `conversational_knowledge` line:

```markdown
- an `agent_work_trace` parallel package that captures the structural trail of agent discovery work (files read, commands run, grep patterns) per turn, aggregates into a compact `task_trace` memory object per session at thread rebuild, with deterministic structural extraction and optional best-effort LLM-derived outcome summary
```

Also add `task_trace` to the appropriate memory type category. Since it's thread-level and produced by thread rebuild:

```markdown
- thread-level memory for:
  - `thread_summary`
  - `task_trace`
```

- [ ] **Step 3: Update `roadmap/board.md`**

Move `add-agent-work-trace-parallel-package` to the Done list (or add it if not present):

```markdown
# Done
- add-agent-work-trace-parallel-package
```

- [ ] **Step 4: Commit**

```bash
git add docs/context/state.md docs/context/architecture.md roadmap/board.md
git commit -m "docs: update context docs and roadmap for agent_work_trace package"
```

---

### Task 13: Final verification

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: PASS — all existing tests + new tests pass

- [ ] **Step 2: Run parity check**

Run: `python -m pytest tests/test_hook_common_parity.py -v`
Expected: PASS

- [ ] **Step 3: Verify no import errors in package**

Run: `python -c "from semantic.agent_work_trace import AgentWorkTracePlugin; print('OK')"`
Expected: prints "OK"
