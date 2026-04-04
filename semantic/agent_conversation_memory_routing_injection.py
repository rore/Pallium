"""Simplified injection check. Replaces QPP 4-gate system.

Two levels: set-level gate + per-candidate eligibility.
Uses InjectionThresholds dataclass for all thresholds.
Type-aware: structured memory (decisions, investigations, checkpoints) gets
a lower injection bar than source hits.
"""
from __future__ import annotations

from dataclasses import dataclass

# Memory types that received LLM extraction with validated structure.
# These get a lower injection bar because the extraction already confirmed relevance.
HIGH_VALUE_MEMORY_TYPES = frozenset({
    "decision", "investigation_outcome", "task_checkpoint",
    "continuity_memory", "pattern_memory", "interest",
})


@dataclass(frozen=True)
class InjectionThresholds:
    """All injection check thresholds. Swappable for testing."""
    set_lexical_threshold: int = 2      # min IDF for set-level gate
    set_vector_high: int = 750          # cosine*1000 for strong vector match
    set_lexical_low: int = 1            # min lexical for vector+lexical condition
    candidate_lexical_floor: int = 1    # per-candidate min lexical (source hits)
    candidate_vector_override: int = 800  # per-candidate strong vector (source hits)
    high_value_lexical_floor: int = 1   # per-candidate min lexical (structured memory)
    high_value_vector_floor: int = 650  # per-candidate vector floor (structured memory)


_DEFAULT_THRESHOLDS = InjectionThresholds()


def should_allow_injection(
    candidates: list[dict],
    *,
    thresholds: InjectionThresholds = _DEFAULT_THRESHOLDS,
) -> bool:
    """Set-level gate: should we inject anything at all?

    Requires minimum lexical signal somewhere in the candidate set.
    Type-aware: high-value structured memory with evidence support gets
    a lower lexical bar.
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
        # Condition 2: strong vector match WITH meaningful lexical signal
        if best_vector >= thresholds.set_vector_high and best_lexical >= thresholds.set_lexical_threshold:
            return True
        # Condition 3: strong vector match when no lexical scoring was available
        if best_vector >= thresholds.candidate_vector_override and not has_any_lexical:
            return True
        return False

    # Fallback: composite scores absent (lexical-only retrieval mode).
    # Require at least one matching term (score > 0).
    best_retrieval = max(int(c.get("retrieval_score", 0) or 0) for c in candidates)
    return best_retrieval > 0


def candidate_injection_eligible(
    candidate: dict,
    *,
    thresholds: InjectionThresholds = _DEFAULT_THRESHOLDS,
) -> bool:
    """Per-candidate: does this specific candidate have enough grounding to inject?

    Type-aware: structured memory (decisions, investigations, checkpoints) gets
    a lower bar because LLM extraction validated its relevance. Source hits and
    other types require stronger retrieval signals.
    """
    raw_lex = candidate.get("lexical_score")
    raw_vec = candidate.get("vector_score")

    if raw_lex is not None or raw_vec is not None:
        lex = int(raw_lex or 0)
        vec = int(raw_vec or 0)
        item = candidate.get("item")
        is_source = getattr(item, "result_kind", None) == "source_hit"
        item_type = getattr(item, "type", None)

        # Structured memory: lower bar
        if not is_source and item_type in HIGH_VALUE_MEMORY_TYPES:
            return lex >= thresholds.high_value_lexical_floor or vec >= thresholds.high_value_vector_floor

        # Source hits and other types: higher bar
        if lex >= thresholds.candidate_lexical_floor:
            return True
        if vec >= thresholds.candidate_vector_override:
            return True
        # When lexical scoring is absent for this candidate, strong vector suffices
        if raw_lex is None and vec >= thresholds.set_vector_high:
            return True
        return False

    # No composite scores — lexical-only retrieval mode.
    retrieval = int(candidate.get("retrieval_score", 0) or 0)
    return retrieval > 0


def _has_high_value_memory(candidates: list[dict]) -> bool:
    """Check if any candidate is a high-value structured memory type."""
    for c in candidates:
        item = c.get("item")
        if item is None:
            continue
        if getattr(item, "result_kind", None) == "source_hit":
            continue
        if getattr(item, "type", None) in HIGH_VALUE_MEMORY_TYPES:
            return True
    return False


def _has_supported_high_value_memory(candidates: list[dict]) -> bool:
    """Check if any candidate is a high-value memory with evidence support.

    Requires support_grade >= "supported" — this means the memory has
    structural evidence backing (evidence count, thread/container match,
    payload completeness). Off-topic high-value memories in a mismatched
    candidate set typically have weak support.
    """
    for c in candidates:
        item = c.get("item")
        if item is None:
            continue
        if getattr(item, "result_kind", None) == "source_hit":
            continue
        if getattr(item, "type", None) not in HIGH_VALUE_MEMORY_TYPES:
            continue
        support = str(c.get("support_grade", "weak"))
        if support in ("supported", "strong"):
            return True
    return False
