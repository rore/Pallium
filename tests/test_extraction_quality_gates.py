"""Tests for extraction quality gates."""
import pytest
from core.models import SourceItem
from semantic.common import (
    SemanticExtraction,
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
