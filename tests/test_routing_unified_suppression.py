"""Tests for the unified suppression rules module."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from semantic.agent_conversation_memory_routing_suppression import (
    DEFAULT_RULES,
    SUPPRESSION_SCORE_PENALTY,
    apply_suppression,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _source_hit_item(excerpt: str = "", role: str = "user") -> MagicMock:
    item = MagicMock()
    item.result_kind = "source_hit"
    item.role = role
    item.excerpt = excerpt
    item.type = None
    item.payload = {}
    return item


def _memory_hit_item(item_type: str = "decision", payload: dict | None = None) -> MagicMock:
    item = MagicMock()
    item.result_kind = "memory_hit"
    item.role = "assistant"
    item.excerpt = ""
    item.type = item_type
    item.payload = payload or {}
    return item


def _make_candidate(item: MagicMock, *, same_thread: bool = False, base_routing_score: int = 300) -> dict:
    return {
        "item": item,
        "same_thread": same_thread,
        "base_routing_score": base_routing_score,
        "suppressed": False,
        "suppression_reason_code": None,
        "packaging_reasons": [],
    }


# ---------------------------------------------------------------------------
# 1. Echo suppression
# ---------------------------------------------------------------------------

def test_echo_suppression_same_thread_matching_excerpt():
    query = "What is the deployment status?"
    item = _source_hit_item(excerpt=query, role="user")
    candidate = _make_candidate(item, same_thread=True, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="recall", query_text=query)

    assert suppressed is True
    assert reason == "current_query_source_echo"
    assert candidate["suppressed"] is True
    assert candidate["suppression_reason_code"] == "current_query_source_echo"


def test_echo_suppression_different_thread_not_suppressed():
    """Echo suppression only fires when same_thread is True."""
    query = "What is the deployment status?"
    item = _source_hit_item(excerpt=query, role="user")
    candidate = _make_candidate(item, same_thread=False, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="recall", query_text=query)

    assert suppressed is False
    assert reason is None


def test_echo_suppression_normalizes_whitespace():
    """Normalization means case and extra spaces shouldn't block echo detection."""
    item = _source_hit_item(excerpt="What IS the  deployment STATUS?", role="user")
    candidate = _make_candidate(item, same_thread=True, base_routing_score=300)

    suppressed, reason = apply_suppression(
        candidate, intent="recall", query_text="what is the deployment status?"
    )

    assert suppressed is True
    assert reason == "current_query_source_echo"


def test_echo_suppression_assistant_role_not_suppressed():
    """Echo rule requires role in (user, '', None). Assistant role bypasses it."""
    query = "What is the deployment status?"
    item = _source_hit_item(excerpt=query, role="assistant")
    candidate = _make_candidate(item, same_thread=True, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="recall", query_text=query)

    assert suppressed is False
    assert reason is None


# ---------------------------------------------------------------------------
# 2. Meta-text suppression
# ---------------------------------------------------------------------------

def test_meta_text_suppression_task_complete():
    """'task complete' matches LOW_VALUE_ASSISTANT_META_PATTERNS."""
    item = _source_hit_item(excerpt="task complete", role="user")
    candidate = _make_candidate(item, same_thread=False, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="recall", query_text="something else")

    assert suppressed is True
    assert reason == "low_value_meta_text"


def test_meta_text_suppression_nothing_new_to_report():
    """'nothing new to report' is a known boilerplate pattern."""
    item = _source_hit_item(excerpt="nothing new to report", role="assistant")
    candidate = _make_candidate(item, same_thread=False, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="work_resumption", query_text="something else")

    assert suppressed is True
    assert reason == "low_value_meta_text"


def test_meta_text_suppression_no_response_needed():
    """'no response needed' is a known boilerplate pattern."""
    item = _source_hit_item(excerpt="No response needed", role="assistant")
    candidate = _make_candidate(item, same_thread=False, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="recall", query_text="something else")

    assert suppressed is True
    assert reason == "low_value_meta_text"


def test_meta_text_suppression_not_source_hit():
    """Meta-text rule only fires for source_hit items."""
    item = _memory_hit_item(item_type="decision")
    item.excerpt = "task complete"
    candidate = _make_candidate(item, same_thread=False, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="recall", query_text="something else")

    assert suppressed is False
    assert reason is None


# ---------------------------------------------------------------------------
# 3. Weak summary suppression — recall intents
# ---------------------------------------------------------------------------

def test_weak_summary_suppressed_for_recall():
    """thread_summary with content_quality=query_only is suppressed for 'recall'."""
    item = _memory_hit_item(item_type="thread_summary", payload={"content_quality": "query_only"})
    candidate = _make_candidate(item, same_thread=False, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="recall", query_text="any query")

    assert suppressed is True
    assert reason == "weak_summary"


def test_weak_summary_suppressed_for_structured_recall():
    """thread_summary with content_quality=weak is also suppressed for 'structured_recall'."""
    item = _memory_hit_item(item_type="thread_summary", payload={"content_quality": "weak"})
    candidate = _make_candidate(item, same_thread=False, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="structured_recall", query_text="any query")

    assert suppressed is True
    assert reason == "weak_summary"


def test_weak_summary_suppressed_discussion_summary():
    """discussion_summary type is also covered."""
    item = _memory_hit_item(item_type="discussion_summary", payload={"content_quality": "unresolved"})
    candidate = _make_candidate(item, same_thread=False, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="recall", query_text="any query")

    assert suppressed is True
    assert reason == "weak_summary"


# ---------------------------------------------------------------------------
# 4. Weak summary NOT suppressed for non-recall intent
# ---------------------------------------------------------------------------

def test_weak_summary_not_suppressed_for_work_resumption():
    """Weak summary rule only fires for RECALL_INTENTS; work_resumption bypasses it."""
    item = _memory_hit_item(item_type="thread_summary", payload={"content_quality": "query_only"})
    candidate = _make_candidate(item, same_thread=False, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="work_resumption", query_text="any query")

    assert suppressed is False
    assert reason is None


def test_weak_summary_not_suppressed_for_grounding():
    item = _memory_hit_item(item_type="thread_summary", payload={"content_quality": "weak"})
    candidate = _make_candidate(item, same_thread=False, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="grounding", query_text="any query")

    assert suppressed is False
    assert reason is None


def test_weak_summary_good_quality_not_suppressed():
    """A thread_summary with good content_quality is not suppressed."""
    item = _memory_hit_item(item_type="thread_summary", payload={"content_quality": "strong"})
    candidate = _make_candidate(item, same_thread=False, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="recall", query_text="any query")

    assert suppressed is False
    assert reason is None


# ---------------------------------------------------------------------------
# 5. Normal candidate passes through
# ---------------------------------------------------------------------------

def test_normal_decision_memory_hit_not_suppressed():
    """A regular decision memory_hit with no special signals is not suppressed."""
    item = _memory_hit_item(item_type="decision", payload={"text": "We decided to use SQLite"})
    candidate = _make_candidate(item, same_thread=False, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="recall", query_text="what was decided?")

    assert suppressed is False
    assert reason is None
    assert candidate["suppressed"] is False
    assert candidate["suppression_reason_code"] is None


# ---------------------------------------------------------------------------
# 6. Priority order: echo takes precedence over meta-text
# ---------------------------------------------------------------------------

def test_echo_takes_priority_over_meta_text():
    """A source_hit that matches BOTH echo and meta-text should report echo reason."""
    # "task complete" is both a meta-text pattern and happens to equal the query
    query = "task complete"
    item = _source_hit_item(excerpt=query, role="user")
    candidate = _make_candidate(item, same_thread=True, base_routing_score=300)

    suppressed, reason = apply_suppression(candidate, intent="recall", query_text=query)

    assert suppressed is True
    # Echo rule is listed first in DEFAULT_RULES, so it wins
    assert reason == "current_query_source_echo"


# ---------------------------------------------------------------------------
# 7. Score penalty applied on suppression
# ---------------------------------------------------------------------------

def test_score_penalty_applied_when_suppressed():
    """Suppressed candidate gets base_routing_score reduced by SUPPRESSION_SCORE_PENALTY."""
    initial_score = 300
    query = "What is the deployment status?"
    item = _source_hit_item(excerpt=query, role="user")
    candidate = _make_candidate(item, same_thread=True, base_routing_score=initial_score)

    suppressed, _ = apply_suppression(candidate, intent="recall", query_text=query)

    assert suppressed is True
    assert candidate["base_routing_score"] == initial_score - SUPPRESSION_SCORE_PENALTY


def test_no_score_penalty_when_not_suppressed():
    """Non-suppressed candidate keeps its original score."""
    initial_score = 300
    item = _memory_hit_item(item_type="decision")
    candidate = _make_candidate(item, same_thread=False, base_routing_score=initial_score)

    suppressed, _ = apply_suppression(candidate, intent="recall", query_text="what was decided?")

    assert suppressed is False
    assert candidate["base_routing_score"] == initial_score


def test_score_penalty_applied_to_meta_text_suppression():
    """Meta-text suppression also applies the score penalty."""
    initial_score = 400
    item = _source_hit_item(excerpt="nothing new to report", role="assistant")
    candidate = _make_candidate(item, same_thread=False, base_routing_score=initial_score)

    suppressed, _ = apply_suppression(candidate, intent="recall", query_text="any query")

    assert suppressed is True
    assert candidate["base_routing_score"] == initial_score - SUPPRESSION_SCORE_PENALTY


def test_score_penalty_applied_to_weak_summary_suppression():
    """Weak summary suppression also applies the score penalty."""
    initial_score = 200
    item = _memory_hit_item(item_type="thread_summary", payload={"content_quality": "weak"})
    candidate = _make_candidate(item, same_thread=False, base_routing_score=initial_score)

    suppressed, _ = apply_suppression(candidate, intent="recall", query_text="any query")

    assert suppressed is True
    assert candidate["base_routing_score"] == initial_score - SUPPRESSION_SCORE_PENALTY


# ---------------------------------------------------------------------------
# 8. Custom rules override DEFAULT_RULES
# ---------------------------------------------------------------------------

def test_custom_rules_override_defaults():
    """Passing a custom rules list replaces DEFAULT_RULES entirely."""
    from semantic.agent_conversation_memory_routing_suppression import SuppressionRule

    # An empty rules list should never suppress anything
    item = _source_hit_item(excerpt="task complete", role="user")
    candidate = _make_candidate(item, same_thread=True, base_routing_score=300)

    suppressed, reason = apply_suppression(
        candidate, intent="recall", query_text="task complete", rules=[]
    )

    assert suppressed is False
    assert reason is None


def test_single_custom_rule_fires():
    """A single-rule custom list fires only that rule."""
    from semantic.agent_conversation_memory_routing_suppression import SuppressionRule

    only_meta = [SuppressionRule(name="meta_text", reason_code="low_value_meta_text", intents=None)]
    item = _source_hit_item(excerpt="nothing new to report", role="user")
    candidate = _make_candidate(item, same_thread=False, base_routing_score=300)

    suppressed, reason = apply_suppression(
        candidate, intent="recall", query_text="something else", rules=only_meta
    )

    assert suppressed is True
    assert reason == "low_value_meta_text"


# ---------------------------------------------------------------------------
# 9. Missing base_routing_score — no KeyError
# ---------------------------------------------------------------------------

def test_suppression_without_base_routing_score_key():
    """If base_routing_score is absent, suppression still works without raising."""
    query = "What is the deployment status?"
    item = _source_hit_item(excerpt=query, role="user")
    candidate = {
        "item": item,
        "same_thread": True,
        "suppressed": False,
        "suppression_reason_code": None,
        "packaging_reasons": [],
        # no base_routing_score key
    }

    suppressed, reason = apply_suppression(candidate, intent="recall", query_text=query)

    assert suppressed is True
    assert reason == "current_query_source_echo"
    # No KeyError — no penalty applied either
    assert "base_routing_score" not in candidate
