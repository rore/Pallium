"""Focused tests for deterministic retrieval excerpts."""

from __future__ import annotations

import pytest

from retrieval.common import build_excerpt


_TEXT = "start marker " + ("context " * 12) + "middle marker " + ("context " * 12) + "end marker"


@pytest.mark.parametrize("query", ["start", "middle", "end"])
def test_build_excerpt_centers_literal_match_at_each_position(query: str) -> None:
    excerpt = build_excerpt(_TEXT, max_length=40, query=query)
    assert len(excerpt) == 40
    assert query in excerpt


def test_build_excerpt_uses_unicode_casefold() -> None:
    text = ("prefix " * 12) + "Straße " + ("suffix " * 12)
    excerpt = build_excerpt(text, max_length=40, query="STRASSE")
    assert len(excerpt) == 40
    assert "Straße" in excerpt


def test_build_excerpt_uses_earliest_textual_match_across_query_tokens() -> None:
    text = ("early " * 8) + ("filler " * 12) + ("late " * 8)
    excerpt = build_excerpt(text, max_length=40, query="late early")
    assert len(excerpt) == 40
    assert excerpt.startswith("early")


def test_build_excerpt_no_literal_match_uses_exact_prefix_fallback() -> None:
    normalized = " ".join(("prefix " * 20).split())
    excerpt = build_excerpt(normalized, max_length=40, query="absent")
    assert len(excerpt) == 40
    assert excerpt.endswith("...")
    assert excerpt.startswith(normalized[:37].rstrip())