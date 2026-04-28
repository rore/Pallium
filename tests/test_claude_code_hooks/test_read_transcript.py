"""Tests for transcript reading logic."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "integrations" / "claude-code" / "hooks"))

from common import read_last_assistant_turn


class TestReadLastAssistantTurn:
    def _write_jsonl(self, lines: list[dict]) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
        for line in lines:
            f.write(json.dumps(line) + "\n")
        f.close()
        return f.name

    def test_wrapped_format(self):
        path = self._write_jsonl([
            {"message": {"role": "user", "content": "hello"}},
            {"message": {"role": "assistant", "content": "hi there"}},
        ])
        try:
            result = read_last_assistant_turn(path)
            assert result == "hi there"
        finally:
            os.unlink(path)

    def test_flat_format(self):
        path = self._write_jsonl([
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ])
        try:
            result = read_last_assistant_turn(path)
            assert result == "world"
        finally:
            os.unlink(path)

    def test_content_array_with_text(self):
        path = self._write_jsonl([
            {"role": "assistant", "content": [
                {"type": "text", "text": "part one"},
                {"type": "text", "text": "part two"},
            ]},
        ])
        try:
            result = read_last_assistant_turn(path)
            assert "part one" in result
            assert "part two" in result
        finally:
            os.unlink(path)

    def test_tool_result_truncated(self):
        long_result = "x" * 1000
        path = self._write_jsonl([
            {"role": "assistant", "content": [
                {"type": "text", "text": "summary"},
                {"type": "tool_result", "text": long_result},
            ]},
        ])
        try:
            result = read_last_assistant_turn(path)
            assert "summary" in result
            assert len(long_result) > 500
            assert "..." in result
            assert "x" * 501 not in result
        finally:
            os.unlink(path)

    def test_last_assistant_turn_used(self):
        path = self._write_jsonl([
            {"role": "assistant", "content": "first response"},
            {"role": "user", "content": "follow up"},
            {"role": "assistant", "content": "second response"},
        ])
        try:
            result = read_last_assistant_turn(path)
            assert result == "second response"
        finally:
            os.unlink(path)

    def test_no_assistant_turn(self):
        path = self._write_jsonl([
            {"role": "user", "content": "hello"},
        ])
        try:
            result = read_last_assistant_turn(path)
            assert result is None
        finally:
            os.unlink(path)

    def test_empty_file(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.close()
        try:
            result = read_last_assistant_turn(f.name)
            assert result is None
        finally:
            os.unlink(f.name)

    def test_file_not_exists(self):
        result = read_last_assistant_turn("/nonexistent/path/transcript.jsonl")
        assert result is None

    def test_malformed_jsonl_lines_skipped(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
        f.write("not valid json\n")
        f.write(json.dumps({"role": "assistant", "content": "valid"}) + "\n")
        f.write("{broken\n")
        f.close()
        try:
            result = read_last_assistant_turn(f.name)
            assert result == "valid"
        finally:
            os.unlink(f.name)

    def test_large_file_tail_reading(self):
        lines = []
        for i in range(100):
            lines.append({"role": "user", "content": f"msg {i}"})
            lines.append({"role": "assistant", "content": f"response {i}"})

        path = self._write_jsonl(lines)
        try:
            result = read_last_assistant_turn(path)
            assert result == "response 99"
        finally:
            os.unlink(path)
