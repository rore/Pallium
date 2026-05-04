"""Tests for format_injection logic."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "integrations" / "claude-code" / "hooks"))

from common import format_injection


class TestFormatInjection:
    def test_empty_blocks_returns_empty(self):
        assert format_injection([], "git:github.com/user/repo", 2400) == ""

    def test_single_block(self):
        blocks = [{"title": "Decision", "memory_object_id": "abc123", "text": "Use PostgreSQL"}]
        result = format_injection(blocks, "git:github.com/user/repo", 2400)
        assert "[Pallium memory — container: git:github.com/user/repo]" in result
        assert "[Decision | ref:abc123] Use PostgreSQL" in result
        assert "[End Pallium memory]" in result

    def test_multiple_blocks(self):
        blocks = [
            {"title": "Decision A", "memory_object_id": "id1", "text": "text one"},
            {"title": "Decision B", "memory_object_id": "id2", "text": "text two"},
        ]
        result = format_injection(blocks, "container", 2400)
        assert "[Decision A | ref:id1] text one" in result
        assert "[Decision B | ref:id2] text two" in result

    def test_flag_footer_present_when_blocks(self):
        blocks = [{"title": "T", "memory_object_id": "x", "text": "y"}]
        result = format_injection(blocks, "c", 2400)
        assert "pallium_flag_memory" in result
        assert "pallium_expand" in result

    def test_budget_exceeded_drops_blocks(self):
        blocks = [
            {"title": "A", "memory_object_id": "1", "text": "x" * 200},
            {"title": "B", "memory_object_id": "2", "text": "y" * 200},
            {"title": "C", "memory_object_id": "3", "text": "z" * 200},
        ]
        result = format_injection(blocks, "c", budget_chars=500)
        assert len(result) <= 500 or result == ""

    def test_budget_too_small_for_any_block(self):
        blocks = [{"title": "Long Title", "memory_object_id": "longid123", "text": "x" * 1000}]
        result = format_injection(blocks, "container_ref_value", budget_chars=100)
        assert result == ""

    def test_blocks_with_special_characters(self):
        blocks = [{"title": "Fix [bug]", "memory_object_id": "id", "text": "line1\nline2"}]
        result = format_injection(blocks, "c", 2400)
        assert "[Fix [bug] | ref:id] line1\nline2" in result

    def test_missing_fields_handled(self):
        blocks = [{"title": "", "memory_object_id": "", "text": ""}]
        result = format_injection(blocks, "c", 2400)
        assert result == "" or "[ | ref:]" in result

    def test_source_expanded_flag_appended_when_true(self):
        blocks = [{"title": "Prior Investigation", "memory_object_id": "mo-1",
                   "text": "found X", "expand_available": True}]
        result = format_injection(blocks, "c", 2400)
        assert "[Prior Investigation | ref:mo-1] found X [+expand]" in result

    def test_source_expanded_flag_absent_when_false(self):
        blocks = [{"title": "T", "memory_object_id": "x", "text": "y",
                   "expand_available": False}]
        result = format_injection(blocks, "c", 2400)
        assert "[+expand]" not in result

    def test_source_expanded_flag_absent_when_key_missing(self):
        blocks = [{"title": "T", "memory_object_id": "x", "text": "y"}]
        result = format_injection(blocks, "c", 2400)
        assert "[+expand]" not in result
