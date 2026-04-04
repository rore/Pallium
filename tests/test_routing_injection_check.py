"""Tests for simplified injection check."""
import pytest
from semantic.agent_conversation_memory_routing_injection import (
    should_allow_injection,
    candidate_injection_eligible,
    InjectionThresholds,
)


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

    def test_strong_vector_with_lexical_allows(self):
        candidates = [_make_candidate(lexical_score=2, vector_score=780)]
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
        lenient = InjectionThresholds(set_lexical_threshold=1)
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
        strict = InjectionThresholds(candidate_lexical_floor=3)
        assert candidate_injection_eligible(
            _make_candidate(lexical_score=2), thresholds=strict
        ) is False
