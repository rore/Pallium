"""Unit tests for QPP-based injection justification.

Tests signal extraction and both justification formulas (linear + rule-based)
with synthetic candidate dicts. No database or server needed.
"""

from __future__ import annotations

from semantic.agent_conversation_memory_routing_justification import (
    InjectionSignals,
    JustificationResult,
    LinearWeights,
    RuleThresholds,
    compute_injection_signals,
    justify_injection_linear,
    justify_injection_rules,
)


# ---------------------------------------------------------------------------
# Synthetic candidate builder
# ---------------------------------------------------------------------------

def _make_candidate(
    *,
    routing_score: int = 500,
    retrieval_score: int = 5,
    support_grade: str = "weak",
    layer: str = "thread_summary",
    work_signal_types: tuple[str, ...] = (),
    work_usefulness_score: int = 0,
    lexical_score: int | None = None,
    vector_score: int | None = None,
    freshness_timestamp_value: float | None = None,
) -> dict[str, object]:
    """Build a minimal candidate dict matching the structure from _score_routed_candidate."""
    # Use a stub instead of a real QueryResultItem to avoid pulling in the full model
    class _StubItem:
        def __init__(self) -> None:
            self.retrieval_source = "both" if (lexical_score is not None and vector_score is not None) else None
            self.lexical_score = lexical_score
            self.vector_score = vector_score
            self.type = layer
            self.result_kind = "memory_hit"

    return {
        "item": _StubItem(),
        "layer": layer,
        "routing_score": routing_score,
        "retrieval_score": retrieval_score,
        "support_grade": support_grade,
        "work_signal_types": work_signal_types,
        "work_usefulness_score": work_usefulness_score,
        "lexical_score": lexical_score,
        "vector_score": vector_score,
        "freshness_timestamp_value": freshness_timestamp_value,
    }


# ===========================================================================
# Signal extraction tests
# ===========================================================================

class TestComputeInjectionSignals:

    def test_empty_candidates(self) -> None:
        signals = compute_injection_signals([])
        assert signals.candidate_count == 0
        assert signals.top_routing_score == 0
        assert signals.score_dispersion == 0.0
        assert signals.best_support_grade == "weak"

    def test_single_candidate(self) -> None:
        c = _make_candidate(routing_score=700, retrieval_score=8, support_grade="strong", layer="decision")
        signals = compute_injection_signals([c])
        assert signals.candidate_count == 1
        assert signals.top_routing_score == 700
        assert signals.max_retrieval_score == 8
        assert signals.best_support_grade == "strong"
        assert signals.has_high_value_types is True
        assert signals.score_dispersion == 0.0  # single candidate
        assert signals.top_gap == 0

    def test_multiple_candidates_peaked(self) -> None:
        """Strong first candidate, weak second — peaked distribution."""
        candidates = [
            _make_candidate(routing_score=900, retrieval_score=10, support_grade="strong", layer="task_checkpoint"),
            _make_candidate(routing_score=300, retrieval_score=3, support_grade="weak", layer="thread_summary"),
        ]
        signals = compute_injection_signals(candidates)
        assert signals.candidate_count == 2
        assert signals.top_routing_score == 900
        assert signals.top_gap == 600
        assert signals.score_dispersion > 100  # high dispersion
        assert signals.has_high_value_types is True

    def test_multiple_candidates_flat(self) -> None:
        """All candidates similar scores — flat distribution."""
        candidates = [
            _make_candidate(routing_score=400, retrieval_score=3),
            _make_candidate(routing_score=395, retrieval_score=3),
            _make_candidate(routing_score=390, retrieval_score=2),
        ]
        signals = compute_injection_signals(candidates)
        assert signals.top_gap == 5
        assert signals.score_dispersion < 10  # very flat

    def test_active_work_signals(self) -> None:
        c = _make_candidate(
            routing_score=600,
            retrieval_score=5,
            layer="task_checkpoint",
            work_signal_types=("blocker", "next_step"),
        )
        signals = compute_injection_signals([c])
        assert signals.has_active_work_signals is True
        assert signals.has_high_value_types is True

    def test_no_active_work_signals(self) -> None:
        c = _make_candidate(routing_score=600, work_signal_types=())
        signals = compute_injection_signals([c])
        assert signals.has_active_work_signals is False

    def test_composite_retrieval_scores(self) -> None:
        c = _make_candidate(routing_score=600, lexical_score=8, vector_score=750)
        signals = compute_injection_signals([c])
        assert signals.max_lexical_score == 8
        assert signals.max_vector_score == 750

    def test_lexical_only_no_vector(self) -> None:
        c = _make_candidate(routing_score=600, lexical_score=5, vector_score=None)
        signals = compute_injection_signals([c])
        assert signals.max_lexical_score == 5
        assert signals.max_vector_score is None

    def test_recency_computation(self) -> None:
        c = _make_candidate(routing_score=600, freshness_timestamp_value=1000.0)
        signals = compute_injection_signals([c], now_timestamp=1060.0)
        assert signals.best_candidate_age_seconds == 60.0

    def test_recency_none_without_timestamp(self) -> None:
        c = _make_candidate(routing_score=600, freshness_timestamp_value=1000.0)
        signals = compute_injection_signals([c])
        assert signals.best_candidate_age_seconds is None

    def test_best_support_grade_picks_highest(self) -> None:
        candidates = [
            _make_candidate(support_grade="weak"),
            _make_candidate(support_grade="strong"),
            _make_candidate(support_grade="supported"),
        ]
        signals = compute_injection_signals(candidates)
        assert signals.best_support_grade == "strong"


# ===========================================================================
# Linear justification tests
# ===========================================================================

class TestJustifyInjectionLinear:

    def test_strong_candidate_justified(self) -> None:
        """High routing score + supported evidence → justified."""
        signals = InjectionSignals(
            top_routing_score=800,
            max_retrieval_score=9,
            candidate_count=2,
            best_support_grade="strong",
            has_high_value_types=True,
            has_active_work_signals=False,
            score_dispersion=200.0,
            top_gap=300,
            max_lexical_score=None,
            max_vector_score=None,
            best_candidate_age_seconds=None,
        )
        result = justify_injection_linear(signals)
        assert result.justified is True
        assert result.score > 0.35

    def test_weak_flat_not_justified(self) -> None:
        """Weak scores, flat distribution, no structure → not justified."""
        signals = InjectionSignals(
            top_routing_score=200,
            max_retrieval_score=1,
            candidate_count=3,
            best_support_grade="weak",
            has_high_value_types=False,
            has_active_work_signals=False,
            score_dispersion=5.0,
            top_gap=5,
            max_lexical_score=None,
            max_vector_score=None,
            best_candidate_age_seconds=None,
        )
        result = justify_injection_linear(signals)
        assert result.justified is False
        assert "low_justification" in result.reason

    def test_single_candidate_with_work_signals_justified(self) -> None:
        """Single candidate but with active work signals + high-value type → justified."""
        signals = InjectionSignals(
            top_routing_score=700,
            max_retrieval_score=6,
            candidate_count=1,
            best_support_grade="supported",
            has_high_value_types=True,
            has_active_work_signals=True,
            score_dispersion=0.0,
            top_gap=0,
            max_lexical_score=None,
            max_vector_score=None,
            best_candidate_age_seconds=None,
        )
        result = justify_injection_linear(signals)
        assert result.justified is True

    def test_custom_weights(self) -> None:
        """Custom weights shift the decision."""
        signals = InjectionSignals(
            top_routing_score=300,
            max_retrieval_score=2,
            candidate_count=1,
            best_support_grade="weak",
            has_high_value_types=False,
            has_active_work_signals=False,
            score_dispersion=0.0,
            top_gap=0,
            max_lexical_score=None,
            max_vector_score=None,
            best_candidate_age_seconds=None,
        )
        # Very low threshold makes it pass
        weights = LinearWeights(threshold=0.05)
        result = justify_injection_linear(signals, weights)
        assert result.justified is True


# ===========================================================================
# Rule-based justification tests
# ===========================================================================

class TestJustifyInjectionRules:

    def test_gate1_strong_retrieval_plus_support(self) -> None:
        """High retrieval score + supported evidence → gate 1a."""
        signals = InjectionSignals(
            top_routing_score=800,
            max_retrieval_score=6,
            candidate_count=2,
            best_support_grade="supported",
            has_high_value_types=True,
            has_active_work_signals=False,
            score_dispersion=100.0,
            top_gap=200,
            max_lexical_score=None,
            max_vector_score=None,
            best_candidate_age_seconds=None,
        )
        result = justify_injection_rules(signals)
        assert result.justified is True
        assert "gate1a" in result.reason

    def test_gate1a_fails_weak_support(self) -> None:
        """High retrieval but weak support → gate 1a does not fire, gate 1b fires in composite."""
        signals = InjectionSignals(
            top_routing_score=800,
            max_retrieval_score=6,
            candidate_count=1,
            best_support_grade="weak",
            has_high_value_types=False,
            has_active_work_signals=False,
            score_dispersion=0.0,
            top_gap=0,
            max_lexical_score=6,
            max_vector_score=None,
            best_candidate_age_seconds=None,
            is_lexical_only=False,
        )
        result = justify_injection_rules(signals)
        assert "gate1a" not in result.reason
        # gate 1b fires: max_lexical_score=6 >= 2 in composite mode
        assert result.justified is True
        assert "gate1b" in result.reason

    def test_gate2_active_work(self) -> None:
        """Active work + high-value types + sufficient routing → gate 2."""
        signals = InjectionSignals(
            top_routing_score=400,
            max_retrieval_score=1,
            candidate_count=1,
            best_support_grade="weak",
            has_high_value_types=True,
            has_active_work_signals=True,
            score_dispersion=0.0,
            top_gap=0,
            max_lexical_score=None,
            max_vector_score=None,
            best_candidate_age_seconds=None,
        )
        result = justify_injection_rules(signals)
        assert result.justified is True
        assert "gate2" in result.reason

    def test_gate2_needs_routing_score(self) -> None:
        """Active work but low routing score → gate 2 doesn't fire."""
        signals = InjectionSignals(
            top_routing_score=100,
            max_retrieval_score=1,
            candidate_count=1,
            best_support_grade="weak",
            has_high_value_types=True,
            has_active_work_signals=True,
            score_dispersion=0.0,
            top_gap=0,
            max_lexical_score=None,
            max_vector_score=None,
            best_candidate_age_seconds=None,
        )
        result = justify_injection_rules(signals)
        assert result.justified is False

    def test_gate3_peaked_distribution(self) -> None:
        """2+ candidates with peaked distribution → gate 3."""
        signals = InjectionSignals(
            top_routing_score=500,
            max_retrieval_score=1,
            candidate_count=3,
            best_support_grade="weak",
            has_high_value_types=False,
            has_active_work_signals=False,
            score_dispersion=120.0,
            top_gap=80,
            max_lexical_score=None,
            max_vector_score=None,
            best_candidate_age_seconds=None,
        )
        # Gate 3 requires min_retrieval_for_shape=2, so retrieval=1 won't pass gate 3
        result = justify_injection_rules(signals)
        assert result.justified is False

    def test_gate3_with_retrieval(self) -> None:
        """2+ candidates with peaked distribution + retrieval >= 2 → gate 3."""
        signals = InjectionSignals(
            top_routing_score=500,
            max_retrieval_score=1,
            candidate_count=3,
            best_support_grade="weak",
            has_high_value_types=False,
            has_active_work_signals=False,
            score_dispersion=120.0,
            top_gap=80,
            max_lexical_score=None,
            max_vector_score=None,
            best_candidate_age_seconds=None,
        )
        # With moderate_retrieval_score lowered to 1, gate 1b would fire instead.
        # Gate 3 is reached only when retrieval < moderate_retrieval_score (2).
        # Since we need retrieval >= 2 for gate 3 but gate 1b fires first at 2,
        # gate 3 only fires via custom thresholds or when gate 1b is disabled.
        thresholds = RuleThresholds(moderate_retrieval_score=99, min_retrieval_for_shape=1)
        result = justify_injection_rules(signals, thresholds)
        assert result.justified is True
        assert "gate3" in result.reason

    def test_gate3_needs_two_candidates(self) -> None:
        """Single candidate → gate 3 doesn't fire (and gate1b doesn't either with low retrieval)."""
        signals = InjectionSignals(
            top_routing_score=500,
            max_retrieval_score=1,
            candidate_count=1,
            best_support_grade="weak",
            has_high_value_types=False,
            has_active_work_signals=False,
            score_dispersion=0.0,
            top_gap=0,
            max_lexical_score=None,
            max_vector_score=None,
            best_candidate_age_seconds=None,
        )
        result = justify_injection_rules(signals)
        assert result.justified is False

    def test_gate4_vector_confidence(self) -> None:
        """High vector score → gate 4 (when retrieval is low)."""
        signals = InjectionSignals(
            top_routing_score=300,
            max_retrieval_score=1,
            candidate_count=1,
            best_support_grade="weak",
            has_high_value_types=False,
            has_active_work_signals=False,
            score_dispersion=0.0,
            top_gap=0,
            max_lexical_score=None,
            max_vector_score=750,
            best_candidate_age_seconds=None,
        )
        result = justify_injection_rules(signals)
        assert result.justified is True
        assert "gate4" in result.reason

    def test_no_gates_pass_suppressed(self) -> None:
        """All signals weak → no gates pass, suppressed."""
        signals = InjectionSignals(
            top_routing_score=200,
            max_retrieval_score=1,
            candidate_count=1,
            best_support_grade="weak",
            has_high_value_types=False,
            has_active_work_signals=False,
            score_dispersion=0.0,
            top_gap=0,
            max_lexical_score=None,
            max_vector_score=None,
            best_candidate_age_seconds=None,
        )
        result = justify_injection_rules(signals)
        assert result.justified is False
        assert "no_gate_passed" in result.reason

    def test_gate_priority_order(self) -> None:
        """When multiple gates could fire, gate 1 wins."""
        signals = InjectionSignals(
            top_routing_score=800,
            max_retrieval_score=8,
            candidate_count=3,
            best_support_grade="strong",
            has_high_value_types=True,
            has_active_work_signals=True,
            score_dispersion=200.0,
            top_gap=200,
            max_lexical_score=8,
            max_vector_score=800,
            best_candidate_age_seconds=None,
        )
        result = justify_injection_rules(signals)
        assert "gate1a" in result.reason

    def test_custom_thresholds(self) -> None:
        """Custom thresholds shift gate behavior."""
        signals = InjectionSignals(
            top_routing_score=300,
            max_retrieval_score=1,
            candidate_count=1,
            best_support_grade="weak",
            has_high_value_types=False,
            has_active_work_signals=False,
            score_dispersion=0.0,
            top_gap=0,
            max_lexical_score=None,
            max_vector_score=None,
            best_candidate_age_seconds=None,
        )
        # Default: retrieval=1 is below moderate_retrieval_score=2 → suppressed
        default_result = justify_injection_rules(signals)
        assert default_result.justified is False

        # Very low thresholds make it pass via gate 1a
        thresholds = RuleThresholds(high_retrieval_score=1, min_support_grade_for_retrieval="weak")
        result = justify_injection_rules(signals, thresholds)
        assert result.justified is True
        assert "gate1a" in result.reason


# ===========================================================================
# Off-topic scenario tests (the core problem)
# ===========================================================================

class TestOffTopicScenarios:
    """Scenarios from the analysis document — these are the cases that must suppress."""

    def test_weather_query_against_db_memories(self) -> None:
        """'how's the weather?' with library/DB memories → suppress in composite mode."""
        # Typical off-topic in composite mode: low lexical score, weak support
        candidates = [
            _make_candidate(routing_score=350, retrieval_score=1, support_grade="weak", layer="thread_summary", lexical_score=1, vector_score=500),
            _make_candidate(routing_score=340, retrieval_score=1, support_grade="weak", layer="interest", lexical_score=1, vector_score=480),
        ]
        signals = compute_injection_signals(candidates)
        linear_result = justify_injection_linear(signals)
        rules_result = justify_injection_rules(signals)
        assert linear_result.justified is False, f"Linear should suppress: {linear_result}"
        assert rules_result.justified is False, f"Rules should suppress: {rules_result}"

    def test_weather_query_zero_overlap_lexical_only(self) -> None:
        """'how's the weather?' with zero overlap in lexical-only → suppress."""
        # Zero retrieval score in lexical-only = no token overlap at all
        candidates = [
            _make_candidate(routing_score=200, retrieval_score=0, support_grade="weak", layer="thread_summary"),
        ]
        signals = compute_injection_signals(candidates)
        rules_result = justify_injection_rules(signals)
        assert rules_result.justified is False, f"Rules should suppress zero overlap: {rules_result}"

    def test_idiom_under_the_weather(self) -> None:
        """'under the weather' — rare-word IDF match but not topical."""
        # Idiomatic usage: IDF-weighted score is typically 1 (single bridging
        # word), not 3.  Real production data confirms retrieval_score=1.
        # Composite mode: lexical_score=1 (single word match)
        candidates = [
            _make_candidate(routing_score=400, retrieval_score=1, support_grade="weak", layer="thread_summary", lexical_score=1, vector_score=500),
        ]
        signals = compute_injection_signals(candidates)
        linear_result = justify_injection_linear(signals)
        rules_result = justify_injection_rules(signals)
        assert linear_result.justified is False, f"Linear should suppress idiom: {linear_result}"
        assert rules_result.justified is False, f"Rules should suppress idiom: {rules_result}"

    def test_topic_switch_something_new(self) -> None:
        """'let's talk about something new' — zero overlap, structured memory rides through."""
        # Zero lexical overlap in composite mode
        candidates = [
            _make_candidate(routing_score=300, retrieval_score=0, support_grade="weak", layer="interest", lexical_score=0, vector_score=450),
            _make_candidate(routing_score=280, retrieval_score=0, support_grade="weak", layer="thread_summary", lexical_score=0, vector_score=430),
        ]
        signals = compute_injection_signals(candidates)
        linear_result = justify_injection_linear(signals)
        rules_result = justify_injection_rules(signals)
        assert linear_result.justified is False, f"Linear should suppress topic switch: {linear_result}"
        assert rules_result.justified is False, f"Rules should suppress topic switch: {rules_result}"


class TestLegitimateRecallScenarios:
    """Scenarios that must NOT be suppressed — the cross-thread recall Pallium protects."""

    def test_vague_recall_with_active_checkpoint(self) -> None:
        """'what should I do next?' with active task_checkpoint → inject."""
        candidates = [
            _make_candidate(
                routing_score=700,
                retrieval_score=4,
                support_grade="supported",
                layer="task_checkpoint",
                work_signal_types=("next_step",),
            ),
            _make_candidate(routing_score=350, retrieval_score=2, support_grade="weak", layer="thread_summary"),
        ]
        signals = compute_injection_signals(candidates)
        linear_result = justify_injection_linear(signals)
        rules_result = justify_injection_rules(signals)
        assert linear_result.justified is True, f"Linear should inject work resumption: {linear_result}"
        assert rules_result.justified is True, f"Rules should inject work resumption: {rules_result}"

    def test_decision_recall_on_topic(self) -> None:
        """'what did we decide about ordering?' with matching decision → inject."""
        candidates = [
            _make_candidate(
                routing_score=850,
                retrieval_score=8,
                support_grade="strong",
                layer="decision",
            ),
            _make_candidate(routing_score=400, retrieval_score=3, support_grade="weak", layer="thread_summary"),
        ]
        signals = compute_injection_signals(candidates)
        linear_result = justify_injection_linear(signals)
        rules_result = justify_injection_rules(signals)
        assert linear_result.justified is True, f"Linear should inject decision recall: {linear_result}"
        assert rules_result.justified is True, f"Rules should inject decision recall: {rules_result}"

    def test_broad_recall_with_strong_evidence(self) -> None:
        """Broad recall with supported evidence → inject."""
        candidates = [
            _make_candidate(
                routing_score=600,
                retrieval_score=5,
                support_grade="supported",
                layer="investigation_outcome",
            ),
        ]
        signals = compute_injection_signals(candidates)
        linear_result = justify_injection_linear(signals)
        rules_result = justify_injection_rules(signals)
        assert linear_result.justified is True, f"Linear should inject broad recall: {linear_result}"
        assert rules_result.justified is True, f"Rules should inject broad recall: {rules_result}"
