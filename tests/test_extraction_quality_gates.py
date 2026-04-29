"""Tests for extraction quality gates."""
import pytest
from core.models import SourceItem
from semantic.common import SemanticExtraction, _should_create_discussion_summary


def _make_source(content: str, role: str = "user") -> SourceItem:
    return SourceItem(
        source_type="test",
        source_id="test-gate-1",
        content_type="text/plain",
        content=content,
        role=role,
        container_ref="test",
        visibility="private",
    )


def _make_extraction(summary: str, **kwargs) -> SemanticExtraction:
    return SemanticExtraction(summary=summary, **kwargs)


class TestDiscussionSummaryQualityGate:
    def test_suppresses_very_short_source(self):
        source = _make_source("what?")
        extraction = _make_extraction("what?")
        assert not _should_create_discussion_summary(source, extraction)

    def test_suppresses_short_user_question(self):
        source = _make_source("why is it like that?")
        extraction = _make_extraction("User asks why it is like that.")
        assert not _should_create_discussion_summary(source, extraction)

    def test_suppresses_short_instruction(self):
        source = _make_source("ok, delete it")
        extraction = _make_extraction("User instructs to confirm deletion.")
        assert not _should_create_discussion_summary(source, extraction)

    def test_suppresses_short_ide_event(self):
        source = _make_source("User opened foo.py")
        extraction = _make_extraction("User opened the file foo.py in the IDE.")
        assert not _should_create_discussion_summary(source, extraction)

    def test_allows_substantive_outcome(self):
        source = _make_source(
            "Root cause analysis: SQL race condition in claim_next_source_item caused duplicate processing"
        )
        extraction = _make_extraction(
            "Root cause analysis and fixes for duplicate memory items: SQL race condition in claim_next_source_item, vector index corruption from killed process"
        )
        assert _should_create_discussion_summary(source, extraction)

    def test_allows_summary_with_explicit_signal(self):
        source = _make_source("We fixed the race condition and all tests pass now.")
        extraction = _make_extraction(
            "Fixed race condition, tests passing.",
            progress_text="Race condition fixed in claim_next_source_item",
        )
        assert _should_create_discussion_summary(source, extraction)

    def test_allows_substantive_question_with_context(self):
        source = _make_source(
            "Does the install process create the full directory structure including config, logs, and run directories?"
        )
        extraction = _make_extraction(
            "User asking about directory structure creation during install."
        )
        assert _should_create_discussion_summary(source, extraction)
