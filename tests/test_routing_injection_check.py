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
from core.models import MemoryEnvelope, MemoryEnvelopeDerivation, MemoryEnvelopeScope, MemorySubjectAnchor, QueryResultItem


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

    def _make_fact_summary_candidate(
        self,
        *,
        visibility: str = "private",
        anchor_prefilter_status: str | None = None,
    ):
        item = QueryResultItem(
            result_kind="memory_hit",
            result_id="fact-summary-1",
            memory_object_id="mo-summary-1",
            type="fact_summary",
            payload={
                "subject": "Alice",
                "category": "travel",
                "summary": "Alice's travel: planning trips to Rome and Madrid this summer.",
            },
            score=100,
            evidence=[],
            visibility=visibility,
            envelope=MemoryEnvelope(
                schema_id="core.memory_envelope",
                schema_version="v1",
                kind="finding",
                scope=MemoryEnvelopeScope(container_ref="slack:channel:CLOCAL001"),
                derivation=MemoryEnvelopeDerivation(
                    producer_kind="consolidation",
                    producer_schema_id="conversational_knowledge.fact_summary",
                    producer_schema_version="v1",
                ),
                subjects=[MemorySubjectAnchor(kind="surface", value="Alice")],
                confidence="medium",
            ),
        )
        candidate = {
            "item": item,
            "layer": "fact_summary",
            "retrieval_score": 100,
            "lexical_score": 80,
            "vector_score": 700,
            "suppression_reason_code": None,
        }
        if anchor_prefilter_status is not None:
            candidate["anchor_prefilter_status"] = anchor_prefilter_status
        return candidate

    def test_fact_summary_is_injection_eligible_for_recall(self):
        candidate = self._make_fact_summary_candidate()
        assert _candidate_is_injection_eligible(
            candidate,
            intent="recall",
            query_text="what do we know about Alice's travel plans",
            allow_discussion_fallback=False,
            allow_source_companion=False,
        ) is True

    @pytest.mark.parametrize("intent", ["structured_recall", "work_resumption", "evidence_trace"])
    def test_fact_summary_is_not_injection_eligible_for_non_recall_intents(self, intent: str):
        candidate = self._make_fact_summary_candidate()
        assert _candidate_is_injection_eligible(
            candidate,
            intent=intent,
            query_text="what do we know about Alice's travel plans",
            allow_discussion_fallback=False,
            allow_source_companion=False,
        ) is False

    def test_shared_fact_summary_requires_anchor_alignment(self):
        candidate = self._make_fact_summary_candidate(
            visibility="public",
            anchor_prefilter_status="secondary_tier",
        )
        assert _candidate_is_injection_eligible(
            candidate,
            intent="recall",
            query_text="what do we know about Alice's travel plans",
            allow_discussion_fallback=False,
            allow_source_companion=False,
        ) is False

    def test_shared_fact_summary_allows_anchor_aligned_recall(self):
        candidate = self._make_fact_summary_candidate(
            visibility="public",
            anchor_prefilter_status="aligned",
        )
        assert _candidate_is_injection_eligible(
            candidate,
            intent="recall",
            query_text="what do we know about Alice's travel plans",
            allow_discussion_fallback=False,
            allow_source_companion=False,
        ) is True
