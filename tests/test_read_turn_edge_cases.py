"""Edge-case tests for the read_turn() turn-bracket pipeline.

Each test pins one algorithmic edge case from design §4.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ROOT = Path(__file__).resolve().parent.parent

cc_common = _load_module(
    str(ROOT / "integrations" / "claude-code" / "hooks" / "common.py"),
    "cc_common_edge",
)
codex_common = _load_module(
    str(ROOT / "integrations" / "codex" / "hooks" / "common.py"),
    "codex_common_edge",
)


def _write(path: Path, entries: list[dict]) -> str:
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return str(path)


# ---------------------------------------------------------------------------
# Claude Code edge cases
# ---------------------------------------------------------------------------


class TestClaudeCodeEdgeCases:
    def test_empty_file_returns_none(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        assert cc_common.read_turn(str(path)) is None

    def test_no_user_lines_returns_whole_file_as_turn(self, tmp_path):
        """A file with only assistant lines is treated as one turn (legacy
        synthetic shape)."""
        path = _write(tmp_path / "no_user.jsonl", [
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Read",
                 "input": {"file_path": "x.py"}},
                {"type": "tool_result", "tool_use_id": "t1", "content": "x"},
                {"type": "text", "text": "Done."},
            ]}},
        ])
        turn = cc_common.read_turn(path)
        assert turn is not None
        assert any(c["tool"] == "Read" for c in turn.tool_calls)

    def test_in_progress_turn_returns_partial(self, tmp_path):
        """Final tool_use without a matching tool_result: parser returns
        the turn with productive_action reflecting the tool but tool_calls
        empty for that unpaired use (Read is not productive)."""
        path = _write(tmp_path / "in_progress.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "Do X"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "Reading."},
            ]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Read",
                 "input": {"file_path": "x.py"}},
            ]}},
            # No tool_result for t1 — turn is "in progress"
        ])
        turn = cc_common.read_turn(path)
        assert turn is not None
        # Read is not productive, so has_productive_action stays False.
        # Unpaired Read tool_use yields no tool_call entry.
        assert turn.has_productive_action is False
        assert len(turn.tool_calls) == 0
        assert "Reading." in turn.assistant_text

    def test_mixed_user_line_treated_as_boundary(self, tmp_path):
        """A user line with mixed content (real text + tool_result) is a
        turn boundary, dropping its tool_result blocks from this turn."""
        path = _write(tmp_path / "mixed.jsonl", [
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t_old", "name": "Read",
                 "input": {"file_path": "old.py"}},
            ]}},
            # Mixed user line: a real text block AND a tool_result block.
            # Per _is_real_user_prompt, this becomes a turn boundary.
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t_old", "content": "old content"},
                {"type": "text", "text": "Now read new.py instead."},
            ]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t_new", "name": "Read",
                 "input": {"file_path": "new.py"}},
            ]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t_new", "content": "new content"},
            ]}},
        ])
        turn = cc_common.read_turn(path)
        assert turn is not None
        reads = [c for c in turn.tool_calls if c["tool"] == "Read"]
        assert len(reads) == 1
        assert reads[0]["file_path"] == "new.py"

    def test_truncated_tail_handled_gracefully(self, tmp_path):
        """Parser tolerates lines whose tool_result references a tool_use_id
        we don't have (simulates tail-truncation dropping early tool_uses).
        Unpaired tool_results are silently dropped, no crash."""
        path = _write(tmp_path / "truncated.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "do it"}},
            # tool_result with no matching tool_use in this turn — simulates
            # tail-read having cut the original tool_use line.
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "missing_id",
                 "content": "stranded result"},
            ]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "Continuing."},
            ]}},
        ])
        # Should not crash, should return a turn with the assistant text.
        turn = cc_common.read_turn(path)
        assert turn is not None
        assert "Continuing." in turn.assistant_text
        # Stranded tool_result: not in tool_calls.
        assert len(turn.tool_calls) == 0


# ---------------------------------------------------------------------------
# Codex edge cases (same algorithm, applied through the translator)
# ---------------------------------------------------------------------------


class TestCodexEdgeCases:
    def test_empty_file_returns_none(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        assert codex_common.read_turn(str(path)) is None

    def test_unknown_top_level_types_dropped(self, tmp_path):
        """Lines like session_meta, turn_context, compacted, and unknown
        types are dropped without affecting decoding."""
        path = _write(tmp_path / "unknown_types.jsonl", [
            {"type": "session_meta", "payload": {"id": "x"}},
            {"type": "turn_context", "payload": {"settings": "..."}},
            {"type": "compacted", "payload": {}},
            {"type": "future_unknown_type_v99", "payload": {}},
            {"type": "response_item", "payload": {"type": "message",
                                                    "role": "user",
                                                    "content": [{"type": "input_text", "text": "Run"}]}},
            {"type": "response_item", "payload": {
                "type": "function_call", "name": "shell_command",
                "call_id": "c1",
                "arguments": '{"command": "echo hi"}'}},
            {"type": "response_item", "payload": {
                "type": "function_call_output", "call_id": "c1",
                "output": "Exit code: 0\nOutput:\nhi"}},
        ])
        turn = codex_common.read_turn(path)
        assert turn is not None
        assert any(c.get("command") == "echo hi" for c in turn.tool_calls)

    def test_function_call_without_call_id_dropped(self, tmp_path):
        """Malformed function_call without call_id is silently dropped."""
        path = _write(tmp_path / "no_call_id.jsonl", [
            {"type": "response_item", "payload": {"type": "message",
                                                    "role": "user",
                                                    "content": [{"type": "input_text", "text": "Run"}]}},
            {"type": "response_item", "payload": {
                "type": "function_call", "name": "shell_command",
                # missing call_id
                "arguments": '{"command": "echo hi"}'}},
        ])
        turn = codex_common.read_turn(path)
        # No tool calls; turn may still be returned with empty tool_calls,
        # or None if all signals are empty. Either way, no crash.
        if turn is not None:
            assert len(turn.tool_calls) == 0

    def test_invalid_json_arguments_dropped(self, tmp_path):
        """Function_call.arguments that is not valid JSON for shell_command
        is dropped (returned input would be empty)."""
        path = _write(tmp_path / "invalid_json.jsonl", [
            {"type": "response_item", "payload": {"type": "message",
                                                    "role": "user",
                                                    "content": [{"type": "input_text", "text": "Run"}]}},
            {"type": "response_item", "payload": {
                "type": "function_call", "name": "shell_command",
                "call_id": "c1",
                "arguments": "{this is not valid json"}},
        ])
        turn = codex_common.read_turn(path)
        if turn is not None:
            assert all(c["tool"] != "Bash" or c.get("command") for c in turn.tool_calls)
