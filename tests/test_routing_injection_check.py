"""Tests for simplified injection check."""
import pytest
from semantic.agent_conversation_memory_routing_injection import (
    should_allow_injection,
    candidate_injection_eligible,
    InjectionThresholds,
)
from semantic.agent_conversation_memory_routing_selection import (
    _candidate_is_injection_eligible,
)
from core.models import QueryResultItem


def _make_candidate(lexical_score=0, vector_score=0):
    return {"lexical_score": lexical_score, "vector_score": vector_score}


class TestSetLevelGate:
    def test_strong_lexical_allows(self):
        candidates = [_make_candidate(lexical_score=4, vector_score=0)]
        assert should_allow_injection(candidates) is True

    def test_zero_lexical_blocks(self):
        """High vector but zero lexical → blocked. This is the off-topic guard."""
        candidates = [_make_candidate(lexical_score=0, vector_score=600)]
        assert should_allow_injection(candidates) is False

    def test_strong_vector_with_some_lexical_allows(self):
        candidates = [_make_candidate(lexical_score=1, vector_score=780)]
        assert should_allow_injection(candidates) is True

    def test_strong_vector_without_lexical_blocks(self):
        candidates = [_make_candidate(lexical_score=0, vector_score=900)]
        assert should_allow_injection(candidates) is False

    def test_empty_candidates_blocks(self):
        assert should_allow_injection([]) is False

    def test_weather_query_scenario(self):
        """Weather query against DB memories: high vector, zero lexical → blocked."""
        candidates = [
            _make_candidate(lexical_score=0, vector_score=650),
            _make_candidate(lexical_score=0, vector_score=580),
        ]
        assert should_allow_injection(candidates) is False

    def test_custom_thresholds(self):
        # Thresholds are in normalized 0-1 space; raw score 1 normalizes to 1/6 ≈ 0.167.
        # A lenient threshold of 0.1 should allow a normalized score of 0.167.
        lenient = InjectionThresholds(set_lexical_threshold=0.1)
        candidates = [_make_candidate(lexical_score=1, vector_score=0)]
        assert should_allow_injection(candidates, thresholds=lenient) is True


class TestPerCandidateEligibility:
    def test_lexical_above_floor(self):
        assert candidate_injection_eligible(_make_candidate(lexical_score=2)) is True

    def test_lexical_below_floor_vector_below_override(self):
        assert candidate_injection_eligible(_make_candidate(lexical_score=0, vector_score=600)) is False

    def test_strong_vector_override(self):
        assert candidate_injection_eligible(_make_candidate(lexical_score=0, vector_score=850)) is True

    def test_both_zero(self):
        assert candidate_injection_eligible(_make_candidate(lexical_score=0, vector_score=0)) is False

    def test_custom_thresholds(self):
        # Thresholds are in normalized 0-1 space; raw score 2 normalizes to 2/6 ≈ 0.333.
        # A strict threshold of 0.5 (≈ raw 3) should block a normalized score of 0.333.
        strict = InjectionThresholds(candidate_lexical_floor=0.5)
        assert candidate_injection_eligible(
            _make_candidate(lexical_score=2), thresholds=strict
        ) is False


class TestCandidateIsInjectionEligible:
    def _make_fact_candidate(self):
        item = QueryResultItem(
            result_kind="memory_hit",
            result_id="fact-1",
            memory_object_id="mo-1",
            type="atomic_fact",
            payload={"statement": "Alice has 3 cats"},
            score=100,
            evidence=[],
        )
        return {
            "item": item,
            "layer": "atomic_fact",
            "retrieval_score": 100,
            "lexical_score": 80,
            "vector_score": 70,
            "suppression_reason_code": None,
        }

    def test_atomic_fact_is_injection_eligible(self):
        candidate = self._make_fact_candidate()
        assert _candidate_is_injection_eligible(
            candidate,
            intent="recall",
            query_text="how many cats does Alice have",
            allow_discussion_fallback=False,
            allow_source_companion=False,
        ) is True
