"""QPP-based injection justification for off-topic suppression.

Replaces the binary relevance floor with a multi-signal justification score
that combines score shape (QPP), memory structure, and recency to decide
whether a candidate set is trustworthy enough to inject.

See docs/designs/off-topic-injection-qpp-design.md for the design rationale.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence

from core.models import QueryResultItem


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InjectionSignals:
    """All signals available at the injection decision point."""

    # Score shape (QPP core) — always available
    top_routing_score: int
    max_retrieval_score: int
    candidate_count: int

    # Support / structure
    best_support_grade: str               # "weak" | "supported" | "strong"
    has_high_value_types: bool            # task_checkpoint, decision, investigation_outcome
    has_active_work_signals: bool         # blocker, next_step in work_signal_types

    # Score shape — requires 2+ candidates
    score_dispersion: float               # std dev of routing_score (0.0 if <2)
    top_gap: int                          # [0].routing_score - [1].routing_score (0 if <2)

    # Composite retrieval — may be None
    max_lexical_score: int | None
    max_vector_score: int | None

    # Recency
    best_candidate_age_seconds: float | None  # seconds since freshest candidate

    # Retrieval mode
    is_lexical_only: bool = False         # True when no composite retrieval candidates


@dataclass(frozen=True)
class JustificationResult:
    """Outcome of the justification decision."""

    justified: bool
    score: float
    reason: str


# ---------------------------------------------------------------------------
# High-value memory types that indicate real work happened in the container
# ---------------------------------------------------------------------------

_HIGH_VALUE_TYPES = frozenset({"task_checkpoint", "decision", "investigation_outcome"})

_ACTIVE_WORK_SIGNAL_TYPES = frozenset({"blocker", "next_step"})

_SUPPORT_GRADE_RANK = {"weak": 0, "supported": 1, "strong": 2}


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------

def compute_injection_signals(
    final_candidates: Sequence[dict[str, object]],
    *,
    now_timestamp: float | None = None,
) -> InjectionSignals:
    """Extract injection decision signals from the candidate set.

    ``final_candidates`` is the list of candidate dicts as produced by the
    routing/scoring pipeline — each dict has keys like ``routing_score``,
    ``retrieval_score``, ``support_grade``, ``layer``, ``work_signal_types``,
    ``lexical_score``, ``vector_score``, ``freshness_timestamp_value``, etc.

    ``now_timestamp`` is the reference time for recency computation.  When
    ``None``, recency is not computed (``best_candidate_age_seconds`` is None).
    """
    if not final_candidates:
        return InjectionSignals(
            top_routing_score=0,
            max_retrieval_score=0,
            candidate_count=0,
            best_support_grade="weak",
            has_high_value_types=False,
            has_active_work_signals=False,
            score_dispersion=0.0,
            top_gap=0,
            max_lexical_score=None,
            max_vector_score=None,
            best_candidate_age_seconds=None,
            is_lexical_only=False,
        )

    routing_scores = [int(c["routing_score"]) for c in final_candidates]
    routing_scores_sorted = sorted(routing_scores, reverse=True)

    top_routing_score = routing_scores_sorted[0]
    max_retrieval_score = max(int(c["retrieval_score"]) for c in final_candidates)

    # Support grade — pick the best
    best_support_grade = "weak"
    for c in final_candidates:
        grade = str(c.get("support_grade") or "weak")
        if _SUPPORT_GRADE_RANK.get(grade, 0) > _SUPPORT_GRADE_RANK.get(best_support_grade, 0):
            best_support_grade = grade

    # High-value types
    has_high_value_types = any(
        _candidate_layer(c) in _HIGH_VALUE_TYPES
        for c in final_candidates
    )

    # Active work signals
    has_active_work_signals = any(
        bool(set(c.get("work_signal_types") or ()) & _ACTIVE_WORK_SIGNAL_TYPES)
        for c in final_candidates
    )

    # Score dispersion + top gap (need 2+ candidates)
    if len(routing_scores_sorted) >= 2:
        score_dispersion = statistics.stdev(routing_scores)
        top_gap = routing_scores_sorted[0] - routing_scores_sorted[1]
    else:
        score_dispersion = 0.0
        top_gap = 0

    # Composite retrieval signals
    lexical_scores = [
        int(c["lexical_score"])
        for c in final_candidates
        if c.get("lexical_score") is not None
    ]
    vector_scores = [
        int(c["vector_score"])
        for c in final_candidates
        if c.get("vector_score") is not None
    ]
    max_lexical_score = max(lexical_scores) if lexical_scores else None
    max_vector_score = max(vector_scores) if vector_scores else None

    # Detect lexical-only mode: when no candidate has retrieval_source set,
    # the system is running in lexical-only mode (no vector provider).
    is_lexical_only = all(
        _candidate_retrieval_source(c) is None
        for c in final_candidates
    )

    # Recency
    best_candidate_age_seconds: float | None = None
    if now_timestamp is not None:
        freshness_values = [
            float(c["freshness_timestamp_value"])
            for c in final_candidates
            if c.get("freshness_timestamp_value") is not None
              and float(c["freshness_timestamp_value"]) > 0
        ]
        if freshness_values:
            best_candidate_age_seconds = max(0.0, now_timestamp - max(freshness_values))

    return InjectionSignals(
        top_routing_score=top_routing_score,
        max_retrieval_score=max_retrieval_score,
        candidate_count=len(final_candidates),
        best_support_grade=best_support_grade,
        has_high_value_types=has_high_value_types,
        has_active_work_signals=has_active_work_signals,
        score_dispersion=score_dispersion,
        top_gap=top_gap,
        max_lexical_score=max_lexical_score,
        max_vector_score=max_vector_score,
        best_candidate_age_seconds=best_candidate_age_seconds,
        is_lexical_only=is_lexical_only,
    )


# ---------------------------------------------------------------------------
# Justification: Approach A — Weighted linear combination
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LinearWeights:
    """Calibrated weights for the linear justification formula.

    Calibrated against 44 labeled scenarios (23 positive, 21 negative) from
    seed invariants, memory_routing benchmarks, work_resumption benchmarks,
    and authored off-topic negatives.
    """

    w_top_routing: float = 0.15
    w_retrieval: float = 0.30
    w_support: float = 0.15
    w_type_richness: float = 0.15
    w_dispersion: float = 0.10
    w_top_gap: float = 0.10
    w_work_signals: float = 0.05
    threshold: float = 0.20

    # Normalization ranges (derived from calibration data)
    routing_score_max: float = 700.0
    retrieval_score_max: float = 30.0
    dispersion_max: float = 300.0
    top_gap_max: float = 500.0


def _support_grade_factor(grade: str) -> float:
    return {"weak": 0.0, "supported": 0.5, "strong": 1.0}.get(grade, 0.0)


def _type_richness_factor(has_high_value: bool) -> float:
    return 1.0 if has_high_value else 0.0


def _clamp_normalize(value: float, max_val: float) -> float:
    if max_val <= 0:
        return 0.0
    return min(1.0, max(0.0, value / max_val))


def justify_injection_linear(
    signals: InjectionSignals,
    weights: LinearWeights | None = None,
) -> JustificationResult:
    """Weighted linear combination of signals → justification score."""
    w = weights or LinearWeights()

    norm_routing = _clamp_normalize(signals.top_routing_score, w.routing_score_max)
    norm_retrieval = _clamp_normalize(signals.max_retrieval_score, w.retrieval_score_max)
    support_f = _support_grade_factor(signals.best_support_grade)
    type_f = _type_richness_factor(signals.has_high_value_types)
    norm_dispersion = _clamp_normalize(signals.score_dispersion, w.dispersion_max)
    norm_gap = _clamp_normalize(signals.top_gap, w.top_gap_max)
    work_f = 1.0 if signals.has_active_work_signals else 0.0

    score = (
        w.w_top_routing * norm_routing
        + w.w_retrieval * norm_retrieval
        + w.w_support * support_f
        + w.w_type_richness * type_f
        + w.w_dispersion * norm_dispersion
        + w.w_top_gap * norm_gap
        + w.w_work_signals * work_f
    )

    justified = score >= w.threshold
    if justified:
        parts = []
        if norm_routing >= 0.4:
            parts.append("strong_routing_score")
        if support_f >= 0.5:
            parts.append("supported_evidence")
        if type_f > 0:
            parts.append("high_value_types")
        if norm_dispersion >= 0.3:
            parts.append("score_peaked")
        if work_f > 0:
            parts.append("active_work")
        reason = "justified:" + "+".join(parts) if parts else "justified:aggregate"
    else:
        parts = []
        if norm_routing < 0.3:
            parts.append("weak_routing")
        if norm_retrieval < 0.2:
            parts.append("weak_retrieval")
        if support_f == 0.0:
            parts.append("weak_support")
        if signals.candidate_count >= 2 and norm_dispersion < 0.1:
            parts.append("flat_scores")
        reason = "low_justification:" + "+".join(parts) if parts else "low_justification:aggregate"

    return JustificationResult(justified=justified, score=round(score, 4), reason=reason)


# ---------------------------------------------------------------------------
# Justification: Approach B — Rule-based with tiered gates
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RuleThresholds:
    """Calibrated thresholds for the rule-based justification.

    Calibrated against 44 labeled scenarios (23 positive, 21 negative) from
    seed invariants, memory_routing benchmarks, work_resumption benchmarks,
    and authored off-topic negatives.

    Positives: max_retrieval_score >= 2 covers 96%, >= 3 covers 91%.
    Negatives with candidates: max_retrieval_score >= 2 in only 36%.
    """

    # Gate 1a: Strong retrieval + structural support
    high_retrieval_score: int = 3
    min_support_grade_for_retrieval: str = "supported"

    # Gate 1b: Moderate retrieval (replaces old lexical floor)
    # IDF-weighted score >= 2 means 2+ content-bearing tokens matched.
    # Off-topic queries (weather, idioms) typically score 0-1.
    moderate_retrieval_score: int = 2

    # Gate 2: Active work + minimum routing score
    min_work_routing_score: int = 300

    # Gate 3: Score shape (2+ candidates) + minimum retrieval
    dispersion_floor: float = 80.0
    gap_floor: int = 50
    min_retrieval_for_shape: int = 2

    # Gate 4: Vector confidence (composite only)
    vector_confidence_floor: int = 700


def justify_injection_rules(
    signals: InjectionSignals,
    thresholds: RuleThresholds | None = None,
) -> JustificationResult:
    """Rule-based tiered gate justification."""
    t = thresholds or RuleThresholds()

    # Gate 1a: Strong retrieval + non-weak support
    min_support_rank = _SUPPORT_GRADE_RANK.get(t.min_support_grade_for_retrieval, 1)
    actual_support_rank = _SUPPORT_GRADE_RANK.get(signals.best_support_grade, 0)
    if (
        signals.max_retrieval_score >= t.high_retrieval_score
        and actual_support_rank >= min_support_rank
    ):
        return JustificationResult(
            justified=True,
            score=1.0,
            reason="gate1a:strong_retrieval+supported_evidence",
        )

    # Gate 1b: Moderate retrieval quality (IDF floor replacement)
    # The check varies by retrieval mode to match the signal semantics.
    #
    # Lexical-only: IDF score >= 1 is sufficient.  The scoring pipeline IS the
    #   quality signal and IDF scores are compressed in small corpora.  Off-topic
    #   suppression relies on score=0 (zero overlap).
    #
    # Composite: check max_lexical_score against the IDF threshold.  Lexical
    #   overlap is the primary evidence of topical relevance.  Vector-only
    #   candidates (no lexical match) are handled by Gate 4 (vector confidence).
    if signals.is_lexical_only:
        if signals.max_retrieval_score >= 1:
            return JustificationResult(
                justified=True,
                score=0.85,
                reason="gate1b:moderate_retrieval_quality_lexical_only",
            )
    else:
        # Composite mode: check lexical score specifically
        if (
            signals.max_lexical_score is not None
            and signals.max_lexical_score >= t.moderate_retrieval_score
        ):
            return JustificationResult(
                justified=True,
                score=0.85,
                reason="gate1b:moderate_retrieval_quality_composite",
            )

    # Gate 2: Active work signals + high-value types + minimum routing
    if (
        signals.has_active_work_signals
        and signals.has_high_value_types
        and signals.top_routing_score >= t.min_work_routing_score
    ):
        return JustificationResult(
            justified=True,
            score=0.9,
            reason="gate2:active_work+high_value_types",
        )

    # Gate 3: Score shape (2+ candidates, peaked distribution, minimum retrieval)
    if (
        signals.candidate_count >= 2
        and signals.score_dispersion >= t.dispersion_floor
        and signals.top_gap >= t.gap_floor
        and signals.max_retrieval_score >= t.min_retrieval_for_shape
    ):
        return JustificationResult(
            justified=True,
            score=0.8,
            reason="gate3:peaked_score_distribution",
        )

    # Gate 4: Vector confidence (composite retrieval only)
    if (
        signals.max_vector_score is not None
        and signals.max_vector_score >= t.vector_confidence_floor
    ):
        return JustificationResult(
            justified=True,
            score=0.7,
            reason="gate4:high_vector_confidence",
        )

    # No gate passed — suppress
    parts = []
    if signals.max_retrieval_score < t.moderate_retrieval_score:
        parts.append("low_retrieval")
    if actual_support_rank < min_support_rank:
        parts.append("weak_support")
    if signals.candidate_count < 2:
        parts.append("single_candidate")
    elif signals.score_dispersion < t.dispersion_floor:
        parts.append("flat_scores")
    if signals.max_vector_score is None:
        parts.append("no_vector")
    reason = "no_gate_passed:" + "+".join(parts) if parts else "no_gate_passed"

    return JustificationResult(justified=False, score=0.0, reason=reason)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candidate_layer(candidate: dict[str, object]) -> str:
    """Extract the layer from a candidate dict, falling back to item type."""
    layer = candidate.get("layer")
    if layer:
        return str(layer)
    item = candidate.get("item")
    if isinstance(item, QueryResultItem):
        return str(item.type or "")
    return ""


def _candidate_retrieval_source(candidate: dict[str, object]) -> str | None:
    """Extract retrieval_source from the candidate's item."""
    item = candidate.get("item")
    if item is not None and hasattr(item, "retrieval_source"):
        return item.retrieval_source
    return None
