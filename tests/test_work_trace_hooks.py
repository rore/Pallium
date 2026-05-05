"""Tests for hook-side agent_work_trace extraction and redaction."""
from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest

_common_path = str(Path(__file__).resolve().parent.parent / "integrations" / "claude-code" / "hooks" / "common.py")
_spec = importlib.util.spec_from_file_location("cc_common", _common_path)
cc_common = importlib.util.module_from_spec(_spec)
import sys as _sys
_sys.modules["cc_common"] = cc_common
_spec.loader.exec_module(cc_common)


def _write_transcript(tmp_path, lines: list[dict]) -> str:
    path = str(tmp_path / "transcript.jsonl")
    with open(path, "w") as f:
        for entry in lines:
            f.write(json.dumps(entry) + "\n")
    return path


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


class TestBuildWorkTraceMetadata:
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
