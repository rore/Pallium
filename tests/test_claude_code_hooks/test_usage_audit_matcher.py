"""Tests for the Phase 5b usage-audit matcher (pure functions).

See: docs/specs/2026-06-27-injection-policy-abstention.md (Phase 5b).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent.parent / "integrations" / "claude-code" / "hooks"),
)

from usage_audit_matcher import (
    VERBATIM_SNIPPET_MIN_CHARS,
    WORD_TOKEN_MIN_ALPHA,
    classify_memory_reference,
    find_id_quote,
    find_verbatim_snippet,
)


# ---------------------------------------------------------------------------
# id_quote
# ---------------------------------------------------------------------------


class TestFindIdQuote:
    def test_exact_ref_match(self):
        assert find_id_quote("abc123", "earlier we saw [ref:abc123]") is True

    def test_no_match_when_id_only(self):
        # The matcher requires the literal "ref:" prefix, not just the id.
        assert find_id_quote("abc123", "we discussed abc123 earlier") is False

    def test_empty_inputs_return_false(self):
        assert find_id_quote("", "ref:abc") is False
        assert find_id_quote("abc", "") is False
        assert find_id_quote("", "") is False

    def test_partial_id_does_not_match(self):
        assert find_id_quote("abc123", "ref:abc12") is False


# ---------------------------------------------------------------------------
# verbatim_snippet
# ---------------------------------------------------------------------------


class TestFindVerbatimSnippet:
    def test_long_quote_with_real_words_matches(self):
        memory = (
            "We decided to use SQLite FTS5 because it gives us BM25 "
            "scoring out of the box and avoids an external dependency."
        )
        response = (
            "Looking at the prior decision: We decided to use SQLite FTS5 "
            "because it gives us BM25 scoring out of the box and avoids "
            "an external dependency. That's why we shipped this."
        )
        assert find_verbatim_snippet(memory, response) is True

    def test_short_memory_below_min_chars_does_not_match(self):
        memory = "Short note"  # <60 chars
        response = "We discussed: " + memory
        assert find_verbatim_snippet(memory, response) is False

    def test_long_quote_without_real_word_filtered_out(self):
        # Pure code identifier / path — should not count as a quote
        # of the memory even though the substring matches.
        memory = "C:/Dev/some/long/code/path/file.py::function_call_x(" + "x" * 80
        response = "Looking at " + memory
        # The 60-char window starting at any point is pure code chars;
        # filter rejects it.
        assert find_verbatim_snippet(memory, response) is False

    def test_no_match_when_text_differs(self):
        memory = (
            "We decided to use SQLite FTS5 because it gives us BM25 "
            "scoring out of the box and avoids an external dependency."
        )
        response = "Unrelated assistant response talking about something else."
        assert find_verbatim_snippet(memory, response) is False

    def test_whitespace_normalization_allows_match(self):
        memory = "We chose PostgreSQL because it handles concurrent writes very efficiently here."
        # Response with mangled whitespace — newlines, tabs, double spaces.
        response = "Quoting: We chose PostgreSQL\n\tbecause it handles  concurrent   writes very efficiently here. — done."
        assert find_verbatim_snippet(memory, response) is True

    def test_empty_inputs_return_false(self):
        assert find_verbatim_snippet("", "long response text here") is False
        assert find_verbatim_snippet("long memory text here", "") is False

    def test_min_chars_constant_locked(self):
        """Spec contract — the floor is 60 chars."""
        assert VERBATIM_SNIPPET_MIN_CHARS == 60

    def test_word_token_min_alpha_locked(self):
        """Spec contract — a 4-letter word qualifies."""
        assert WORD_TOKEN_MIN_ALPHA == 4

    def test_match_window_exactly_at_min_chars(self):
        """Boundary: exactly min_chars window matches."""
        memory = "a " * 30 + "decision " * 4 + "made"  # >= 60 chars w/ words
        # Response contains memory verbatim
        response = "Quoted text: " + memory
        # Memory normalized would be the same string; should match.
        assert find_verbatim_snippet(memory, response) is True

    def test_lowered_threshold_via_param(self):
        memory = "Short but meaningful sentence."
        response = "Quote: " + memory + " continued"
        # Pass a lower min_chars; should match.
        assert find_verbatim_snippet(memory, response, min_chars=20) is True


# ---------------------------------------------------------------------------
# classify_memory_reference (combined)
# ---------------------------------------------------------------------------


class TestClassifyMemoryReference:
    def test_id_quote_takes_priority_over_verbatim(self):
        memory_text = (
            "Decision: We chose PostgreSQL because it scales well and "
            "supports the workload we expect over the next year."
        )
        response = (
            "Per [ref:abc-xyz]: Decision: We chose PostgreSQL because "
            "it scales well and supports the workload we expect over "
            "the next year."
        )
        referenced, kind = classify_memory_reference(
            memory_object_id="abc-xyz",
            memory_text=memory_text,
            response_text=response,
        )
        assert referenced is True
        assert kind == "id_quote"

    def test_verbatim_when_no_id_quote(self):
        memory_text = (
            "Decision: We chose PostgreSQL because it scales well and "
            "supports the workload we expect over the next year."
        )
        response = (
            "We chose PostgreSQL because it scales well and supports "
            "the workload we expect over the next year — done."
        )
        referenced, kind = classify_memory_reference(
            memory_object_id="abc-xyz",
            memory_text=memory_text,
            response_text=response,
        )
        assert referenced is True
        assert kind == "verbatim_snippet"

    def test_no_match_returns_false_none(self):
        referenced, kind = classify_memory_reference(
            memory_object_id="abc-xyz",
            memory_text="Some old memory text that's quite long enough.",
            response_text="Unrelated text about something else entirely.",
        )
        assert referenced is False
        assert kind is None

    def test_empty_memory_text_short_circuits(self):
        # Memory has no text (some block types are title-only).
        referenced, kind = classify_memory_reference(
            memory_object_id="abc-xyz",
            memory_text="",
            response_text="Long response text that mentions nothing identifiable.",
        )
        assert referenced is False
        assert kind is None
