"""Simplified injection check. Replaces QPP 4-gate system.

Two levels: set-level gate + per-candidate eligibility.
Uses InjectionThresholds dataclass for all thresholds.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InjectionThresholds:
    """All injection check thresholds. Swappable for testing."""
    set_lexical_threshold: int = 3      # min IDF for set-level gate
    set_vector_high: int = 750          # cosine*1000 for strong vector match
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
    """
    if not candidates:
        return False
    best_lexical = max(int(c.get("lexical_score", 0) or 0) for c in candidates)
    best_vector = max(int(c.get("vector_score", 0) or 0) for c in candidates)

    # Condition 1: meaningful lexical overlap
    if best_lexical >= thresholds.set_lexical_threshold:
        return True
    # Condition 2: strong vector match WITH some lexical signal
    if best_vector >= thresholds.set_vector_high and best_lexical >= thresholds.set_lexical_low:
        return True
    return False


def candidate_injection_eligible(
    candidate: dict,
    *,
    thresholds: InjectionThresholds = _DEFAULT_THRESHOLDS,
) -> bool:
    """Per-candidate: does this specific candidate have enough grounding to inject?"""
    lex = int(candidate.get("lexical_score", 0) or 0)
    vec = int(candidate.get("vector_score", 0) or 0)
    if lex >= thresholds.candidate_lexical_floor:
        return True
    if vec >= thresholds.candidate_vector_override:
        return True
    return False
