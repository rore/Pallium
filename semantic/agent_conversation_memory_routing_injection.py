"""Simplified injection check. Replaces QPP 4-gate system.

Two levels: set-level gate + per-candidate eligibility.
Uses InjectionThresholds dataclass for all thresholds.
Type-aware: structured memory (decisions, investigations, checkpoints) gets
a lower injection bar than source hits.

Verbose mode: set PALLIUM_INJECTION_VERBOSE=1 or pass verbose=True to get
detailed logging of every decision. Use this when investigating injection
failures in eval scenarios.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

_log = logging.getLogger("pallium.routing.injection")
_VERBOSE = os.environ.get("PALLIUM_INJECTION_VERBOSE", "") == "1"

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
    verbose: bool = _VERBOSE,
) -> bool:
    """Set-level gate: should we inject anything at all?

    Requires minimum lexical signal somewhere in the candidate set.
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

        cond1 = best_lexical >= thresholds.set_lexical_threshold
        cond2 = best_vector >= thresholds.set_vector_high and best_lexical >= thresholds.set_lexical_low
        cond3 = best_vector >= thresholds.candidate_vector_override and not has_any_lexical

        if verbose:
            _log.warning(
                "SET_GATE: candidates=%d best_lex=%d best_vec=%d has_any_lex=%s "
                "has_hv=%s has_supported_hv=%s | cond1=%s cond2=%s cond3=%s → %s",
                len(candidates), best_lexical, best_vector, has_any_lexical,
                _has_high_value_memory(candidates),
                _has_supported_high_value_memory(candidates),
                cond1, cond2, cond3,
                "ALLOW" if (cond1 or cond2 or cond3) else "BLOCK",
            )
            # Log each candidate's scores for analysis
            for i, c in enumerate(candidates[:10]):
                item = c.get("item")
                _log.warning(
                    "  candidate[%d]: id=%s kind=%s type=%s lex=%s vec=%s "
                    "retrieval_source=%s support=%s routing_score=%s suppressed=%s",
                    i,
                    getattr(item, "result_id", "?")[:40] if item else "?",
                    getattr(item, "result_kind", "?") if item else "?",
                    getattr(item, "type", None) if item else "?",
                    c.get("lexical_score"),
                    c.get("vector_score"),
                    getattr(item, "retrieval_source", None) if item else None,
                    c.get("support_grade", "?"),
                    c.get("routing_score", "?"),
                    c.get("suppressed", False),
                )

        # Condition 1: meaningful lexical overlap
        if cond1:
            return True
        # Condition 2: strong vector match WITH some lexical signal
        if cond2:
            return True
        # Condition 3: strong vector match when no lexical scoring was available
        if cond3:
            return True
        return False

    # Fallback: composite scores absent (lexical-only retrieval mode).
    best_retrieval = max(int(c.get("retrieval_score", 0) or 0) for c in candidates)
    result = best_retrieval > 0
    if verbose:
        _log.warning(
            "SET_GATE fallback: candidates=%d best_retrieval=%d → %s",
            len(candidates), best_retrieval, "ALLOW" if result else "BLOCK",
        )
    return result


def candidate_injection_eligible(
    candidate: dict,
    *,
    thresholds: InjectionThresholds = _DEFAULT_THRESHOLDS,
    verbose: bool = _VERBOSE,
) -> bool:
    """Per-candidate: does this specific candidate have enough grounding to inject?

    Type-aware: structured memory gets a lower bar. Source hits need stronger signals.
    """
    raw_lex = candidate.get("lexical_score")
    raw_vec = candidate.get("vector_score")
    item = candidate.get("item")
    item_id = getattr(item, "result_id", "?")[:40] if item else "?"
    item_kind = getattr(item, "result_kind", "?") if item else "?"
    item_type = getattr(item, "type", None) if item else None

    if raw_lex is not None or raw_vec is not None:
        lex = int(raw_lex or 0)
        vec = int(raw_vec or 0)
        is_source = item_kind == "source_hit"

        # Structured memory: lower bar
        if not is_source and item_type in HIGH_VALUE_MEMORY_TYPES:
            eligible = lex >= thresholds.high_value_lexical_floor or vec >= thresholds.high_value_vector_floor
            if verbose:
                _log.warning(
                    "  PER_CANDIDATE high_value: id=%s type=%s lex=%d vec=%d "
                    "→ %s (floor: lex>=%d or vec>=%d)",
                    item_id, item_type, lex, vec,
                    "ELIGIBLE" if eligible else "BLOCKED",
                    thresholds.high_value_lexical_floor, thresholds.high_value_vector_floor,
                )
            return eligible

        # Source hits and other types: higher bar
        eligible = (
            lex >= thresholds.candidate_lexical_floor
            or vec >= thresholds.candidate_vector_override
            or (raw_lex is None and vec >= thresholds.set_vector_high)
        )
        if verbose:
            _log.warning(
                "  PER_CANDIDATE source/other: id=%s kind=%s type=%s lex=%d vec=%d "
                "→ %s (floor: lex>=%d or vec>=%d)",
                item_id, item_kind, item_type, lex, vec,
                "ELIGIBLE" if eligible else "BLOCKED",
                thresholds.candidate_lexical_floor, thresholds.candidate_vector_override,
            )
        return eligible

    # No composite scores — lexical-only retrieval mode.
    retrieval = int(candidate.get("retrieval_score", 0) or 0)
    eligible = retrieval > 0
    if verbose:
        _log.warning(
            "  PER_CANDIDATE fallback: id=%s kind=%s type=%s retrieval=%d → %s",
            item_id, item_kind, item_type, retrieval,
            "ELIGIBLE" if eligible else "BLOCKED",
        )
    return eligible


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
    payload completeness).
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
