"""Tests for IDE context tag stripping in user_prompt_submit hook."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "integrations" / "claude-code" / "hooks"))

from user_prompt_submit import _strip_ide_context


class TestStripIdeContext:
    def test_strips_opened_file_tag(self):
        text = "<ide_opened_file>src/main.py</ide_opened_file>\nfix the bug"
        assert _strip_ide_context(text) == "fix the bug"

    def test_strips_selection_tag(self):
        text = "<ide_selection>def foo():\n    pass</ide_selection>\nrefactor this"
        assert _strip_ide_context(text) == "refactor this"

    def test_strips_multiple_tags(self):
        text = (
            "<ide_opened_file>a.py</ide_opened_file>"
            "<ide_selection>code</ide_selection>"
            "\ndo something"
        )
        assert _strip_ide_context(text) == "do something"

    def test_preserves_plain_text(self):
        text = "implement the auth feature"
        assert _strip_ide_context(text) == "implement the auth feature"

    def test_returns_empty_for_only_ide_tags(self):
        text = "<ide_opened_file>foo.py</ide_opened_file>"
        assert _strip_ide_context(text) == ""

    def test_handles_multiline_selection(self):
        text = (
            "<ide_selection>line1\nline2\nline3</ide_selection>\n"
            "explain what this does"
        )
        assert _strip_ide_context(text) == "explain what this does"
