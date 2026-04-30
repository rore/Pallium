"""Tests for extraction quality gates."""
import pytest
from core.models import SourceItem
from semantic.common import (
    SemanticExtraction,
    _should_create_turn_summary,
    _looks_like_low_value_meta_update,
    build_process_result,
)


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


class TestTurnSummaryQualityGate:
    def test_suppresses_very_short_source(self):
        source = _make_source("what?")
        extraction = _make_extraction("what?")
        assert not _should_create_turn_summary(source, extraction)

    def test_suppresses_short_user_question(self):
        source = _make_source("why is it like that?")
        extraction = _make_extraction("User asks why it is like that.")
        assert not _should_create_turn_summary(source, extraction)

    def test_suppresses_short_instruction(self):
        source = _make_source("ok, delete it")
        extraction = _make_extraction("User instructs to confirm deletion.")
        assert not _should_create_turn_summary(source, extraction)

    def test_suppresses_short_ide_event(self):
        source = _make_source("User opened foo.py")
        extraction = _make_extraction("User opened the file foo.py in the IDE.")
        assert not _should_create_turn_summary(source, extraction)

    def test_allows_substantive_outcome(self):
        source = _make_source(
            "Root cause analysis: SQL race condition in the claim_next_source_item function caused duplicate processing of memory items in concurrent workers"
        )
        extraction = _make_extraction(
            "Root cause analysis and fixes for duplicate memory items: SQL race condition in claim_next_source_item, vector index corruption from killed process"
        )
        assert _should_create_turn_summary(source, extraction)

    def test_allows_summary_with_explicit_signal(self):
        source = _make_source("We fixed the race condition and all tests pass now.")
        extraction = _make_extraction(
            "Fixed race condition, tests passing.",
            progress_text="Race condition fixed in claim_next_source_item",
        )
        assert _should_create_turn_summary(source, extraction)

    def test_allows_substantive_question_with_context(self):
        source = _make_source(
            "Does the install process create the full directory structure including config files, log directories, run state, and the plugin extensions folder?"
        )
        extraction = _make_extraction(
            "User asking about directory structure creation during install including config, logs, run state, and plugins."
        )
        assert _should_create_turn_summary(source, extraction)

    def test_suppresses_19_token_source(self):
        source = _make_source(
            "Can you check whether the deployment pipeline handles the automatic rollback correctly when the health check endpoint fails unexpectedly?"
        )
        extraction = _make_extraction(
            "User asks about deployment pipeline rollback behavior on health check failure."
        )
        assert not _should_create_turn_summary(source, extraction)

    def test_allows_20_token_source_no_signal(self):
        source = _make_source(
            "Does the deployment process handle automatic rollback correctly when one of the configured health check endpoints returns any failure code?"
        )
        extraction = _make_extraction(
            "User asks about deployment rollback behavior when configured health check endpoints fail."
        )
        assert _should_create_turn_summary(source, extraction)


def test_interest_blocked_below_token_gate():
    """Interest extraction with <10 token source produces no interest memory."""
    source = _make_source("check redis", role="user")  # already visibility="private"
    extraction = _make_extraction("User mentions redis", candidate_type="interest", interest_text="redis")
    result = build_process_result(source, extraction, "test")
    interest_objects = [m for m in result.memory_objects if m.type == "interest"]
    assert len(interest_objects) == 0


def test_interest_allowed_above_token_gate():
    """Interest extraction with >=10 token source creates interest memory."""
    source = _make_source(
        "I want to explore using redis as a caching layer for our retrieval pipeline later",
        role="user",
    )  # already visibility="private"
    extraction = _make_extraction(
        "User interested in redis for caching",
        candidate_type="interest",
        interest_text="redis as caching layer",
    )
    result = build_process_result(source, extraction, "test")
    interest_objects = [m for m in result.memory_objects if m.type == "interest"]
    assert len(interest_objects) == 1


def test_low_value_meta_no_phrase_matching():
    """_looks_like_low_value_meta_update relies only on LLM flag, not phrases."""
    # Phrase that WOULD have matched old code but LLM says not low-value
    extraction = _make_extraction("Task complete and results saved", is_low_value_meta=False)
    assert not _looks_like_low_value_meta_update(extraction)
    # LLM says IS low-value
    extraction2 = _make_extraction("Task complete", is_low_value_meta=True)
    assert _looks_like_low_value_meta_update(extraction2)


def test_fact_extraction_blocked_below_gate():
    """Source items with <10 tokens are ineligible for fact extraction."""
    from semantic.conversational_knowledge import _is_eligible_for_fact_extraction

    source = SourceItem(
        source_type="test",
        source_id="fact-gate-1",
        content_type="text/plain",
        content="Hi there",
        role="user",
        artifact_kind="message",
        container_ref="test-container",
    )
    assert not _is_eligible_for_fact_extraction(source)
