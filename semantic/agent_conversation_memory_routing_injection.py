"""Simplified injection check. Replaces QPP 4-gate system.

Two levels: set-level gate + per-candidate eligibility.
Uses InjectionThresholds dataclass for all thresholds.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InjectionThresholds:
    """All injection check thresholds. Swappable for testing."""
    set_lexical_threshold: int = 2      # min IDF for set-level gate (at least one shared content word)
    set_vector_high: int = 750          # cosine*1000 for strong vector match (condition 2 + condition 3)
    set_lexical_low: int = 1            # min lexical for vector+lexical condition
    candidate_lexical_floor: int = 1    # per-candidate min lexical
    candidate_vector_override: int = 800  # per-candidate strong vector override


_DEFAULT_THRESHOLDS = InjectionThresholds()


def should_allow_injection(
    candidates: list[dict],
    *,
    thresholds: InjectionThresholds = _DEFAULT_THRESHOLDS,
) -> bool:
    """Set-level gate: should we inject anything at all?

    Requires minimum lexical signal somewhere in the candidate set.
    This is the primary off-topic injection guard.

    When composite retrieval scores (lexical_score/vector_score) are absent,
    falls back to the retrieval_score field set by routing scoring.
    """
    if not candidates:
        return False

    has_any_score = any(
        c.get("lexical_score") is not None or c.get("vector_score") is not None
        for c in candidates
    )

    if has_any_score:
        best_lexical = max(int(c.get("lexical_score", 0) or 0) for c in candidates)
        best_vector = max(int(c.get("vector_score", 0) or 0) for c in candidates)
        has_any_lexical = any(c.get("lexical_score") is not None for c in candidates)

        # Condition 1: meaningful lexical overlap
        if best_lexical >= thresholds.set_lexical_threshold:
            return True
        # Condition 2: strong vector match WITH some lexical signal
        if best_vector >= thresholds.set_vector_high and best_lexical >= thresholds.set_lexical_low:
            return True
        # Condition 3: strong vector match when no lexical scoring was available
        # Use candidate_vector_override (800) as higher bar since there's no lexical confirmation
        if best_vector >= thresholds.candidate_vector_override and not has_any_lexical:
            return True
        return False

    # Fallback: composite scores absent (lexical-only retrieval mode).
    # retrieval_score is the raw IDF score from lexical search.
    # Require at least one matching term (score > 0). In lexical-only mode, score 0
    # means no words matched at all — certain off-topic.
    best_retrieval = max(int(c.get("retrieval_score", 0) or 0) for c in candidates)
    return best_retrieval > 0


def candidate_injection_eligible(
    candidate: dict,
    *,
    thresholds: InjectionThresholds = _DEFAULT_THRESHOLDS,
) -> bool:
    """Per-candidate: does this specific candidate have enough grounding to inject?

    When composite retrieval scores (lexical_score/vector_score) are absent,
    falls back to retrieval_score from the routing scoring pipeline.
    """
    raw_lex = candidate.get("lexical_score")
    raw_vec = candidate.get("vector_score")

    if raw_lex is not None or raw_vec is not None:
        lex = int(raw_lex or 0)
        vec = int(raw_vec or 0)
        if lex >= thresholds.candidate_lexical_floor:
            return True
        if vec >= thresholds.candidate_vector_override:
            return True
        # When lexical scoring is absent for this candidate, a strong vector match suffices
        if raw_lex is None and vec >= thresholds.set_vector_high:
            return True
        return False

    # No composite scores — lexical-only retrieval mode.
    # Require non-zero retrieval_score (at least one matching word).
    retrieval = int(candidate.get("retrieval_score", 0) or 0)
    return retrieval > 0
