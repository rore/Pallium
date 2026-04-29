"""Tests for extraction quality gates."""
import pytest
from semantic.conversational_knowledge import _is_ephemeral_fact


class TestEphemeralFactFilter:
    def test_filters_port_number(self):
        assert _is_ephemeral_fact({"subject": "Pallium service", "statement": "Pallium service runs on port 19836", "category": "event"})

    def test_filters_test_count(self):
        assert _is_ephemeral_fact({"subject": "test suite", "statement": "All 1579 tests pass", "category": "event"})

    def test_filters_commit_hash(self):
        assert _is_ephemeral_fact({"subject": "service", "statement": "Service lifecycle feature was committed with commit hash 9e19594", "category": "event"})

    def test_filters_uptime(self):
        assert _is_ephemeral_fact({"subject": "Pallium", "statement": "Pallium service uptime is 4.5 seconds", "category": "event"})

    def test_filters_pid(self):
        assert _is_ephemeral_fact({"subject": "Pallium", "statement": "Pallium service was running as PID 36440", "category": "event"})

    def test_filters_process_count(self):
        assert _is_ephemeral_fact({"subject": "Pallium", "statement": "Pallium has 3 small wrapper processes each using 5MB memory", "category": "event"})

    def test_keeps_durable_preference(self):
        assert not _is_ephemeral_fact({"subject": "Pallium packages", "statement": "Demo packages should never be activated", "category": "preference"})

    def test_keeps_architecture_choice(self):
        assert not _is_ephemeral_fact({"subject": "dashboard", "statement": "dashboard uses vanilla HTML/CSS/JS with no framework dependencies", "category": "preference"})

    def test_keeps_named_model_choice(self):
        assert not _is_ephemeral_fact({"subject": "embedding", "statement": "multilingual-e5-small was chosen as the embedding model", "category": "preference"})

    def test_keeps_user_activity_without_numbers(self):
        assert not _is_ephemeral_fact({"subject": "user", "statement": "user requested a documentation pass covering install and dashboard docs", "category": "activity"})


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
    def test_suppresses_very_short_summary(self):
        source = _make_source("what?")
        extraction = _make_extraction("what?")
        assert not _should_create_discussion_summary(source, extraction)

    def test_suppresses_bare_user_question(self):
        source = _make_source("why is it like that?")
        extraction = _make_extraction("User asks why it is like that.")
        assert not _should_create_discussion_summary(source, extraction)

    def test_suppresses_user_instructs_short(self):
        source = _make_source("ok, delete it")
        extraction = _make_extraction("User instructs to confirm deletion.")
        assert not _should_create_discussion_summary(source, extraction)

    def test_suppresses_user_opened_file(self):
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

    def test_allows_long_user_asks_with_outcome(self):
        """Longer 'User asks...' summaries that also contain the answer should pass."""
        source = _make_source("Does the install create the directory structure?")
        extraction = _make_extraction(
            "User asking whether the install process creates the directory structure and files. The service install creates the full layout including config, logs, and run directories."
        )
        assert _should_create_discussion_summary(source, extraction)
