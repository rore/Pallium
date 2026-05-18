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

import os
import sys
from dataclasses import dataclass

from semantic.agent_conversation_memory_routing_constants import normalize_lexical_score

_VERBOSE = os.environ.get("PALLIUM_INJECTION_VERBOSE", "") == "1"


def _verbose(msg: str) -> None:
    """Write verbose injection debug output to stderr.

    Uses print(stderr) instead of the logging framework to avoid holding
    file handles that cause SQLite temp-file cleanup failures on Windows.
    """
    print(msg, file=sys.stderr, flush=True)

# Memory types that received LLM extraction with validated structure.
# These get a lower injection bar because the extraction already confirmed relevance.
HIGH_VALUE_MEMORY_TYPES = frozenset({
    "decision", "investigation_outcome", "task_checkpoint",
    "continuity_memory", "pattern_memory", "constraint_memory",
})


@dataclass(frozen=True)
class InjectionThresholds:
    """All injection check thresholds. Swappable for testing.

    Lexical thresholds are in normalized 0-1 space (via normalize_lexical_score).
    In lexical-only mode (no composite scores), the set-level gate falls
    through to the retrieval_score > 0 check instead.
    """
    set_lexical_threshold: float = 0.04    # min normalized lexical for set-level gate (= 2/50)
    set_vector_high: int = 750             # cosine*1000 for strong vector match
    set_lexical_low: float = 0.01          # min normalized lexical for vector+lexical condition (any meaningful match)
    candidate_lexical_floor: float = 0.01  # per-candidate min normalized lexical (source hits)
    candidate_vector_override: int = 800   # per-candidate strong vector (source hits)
    high_value_lexical_floor: float = 0.01 # per-candidate min normalized lexical (structured memory)
    high_value_vector_floor: int = 650     # per-candidate vector floor (structured memory)
    min_raw_lexical_bm25: float = 12.0     # per-candidate: require raw BM25 >= this (blocks vector-only)


_DEFAULT_THRESHOLDS = InjectionThresholds()


def should_allow_injection(
    candidates: list[dict],
    *,
    thresholds: InjectionThresholds = _DEFAULT_THRESHOLDS,
    verbose: bool = _VERBOSE,
    query_text: str = "",
    intent: str = "",
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
        # Exclude turn_summary from best_lexical: a turn_summary's
        # lexical overlap with the query is circular — it was derived from content
        # that shares the query's words by construction (e.g., an ingested copy of
        # the query text gets summarized, producing a summary that echoes the query).
        # Including it inflates the set-level gate confidence without adding
        # independent evidence of topical relevance.
        _non_summary_candidates = [
            c for c in candidates
            if getattr(c.get("item"), "type", None) != "turn_summary"
        ]
        _lex_candidates = _non_summary_candidates or candidates
        best_lexical = max(normalize_lexical_score(c.get("lexical_score")) for c in _lex_candidates)
        best_vector = max(int(c.get("vector_score", 0) or 0) for c in candidates)
        has_any_lexical = any(c.get("lexical_score") is not None for c in _lex_candidates)

        cond1 = best_lexical >= thresholds.set_lexical_threshold
        cond2 = best_vector >= thresholds.set_vector_high and best_lexical >= thresholds.set_lexical_low
        cond3 = best_vector >= thresholds.candidate_vector_override and not has_any_lexical
        # Condition 4: supported structured memory with lexical + vector confirmation.
        # Decisions/investigations that passed LLM extraction with evidence backing
        # deserve a lower bar — but require vector confirmation to avoid off-topic
        # injection when only incidental lexical overlap exists (e.g., stop words).
        cond4 = (
            _has_supported_high_value_memory(candidates)
            and best_lexical >= thresholds.set_lexical_low
            and best_vector >= thresholds.high_value_vector_floor
        )
        # Condition 5: work_resumption intent with supported structured memory.
        # "Pick up where I left off" has no lexical overlap with the actual work
        # topic — the intent classification itself is the confidence signal.
        # Requires the routing to have already classified this as work_resumption
        # (which needs turn_kind=resumed_session + candidate evidence).
        cond5 = (
            intent == "work_resumption"
            and _has_supported_high_value_memory(candidates)
        )

        result = cond1 or cond2 or cond3 or cond4 or cond5

        if verbose:
            _verbose(
                f"INJECTION query={query_text[:80]!r} intent={intent} | SET_GATE: "
                f"candidates={len(candidates)} best_lex={best_lexical} best_vec={best_vector} "
                f"has_any_lex={has_any_lexical} has_hv={_has_high_value_memory(candidates)} "
                f"has_supported_hv={_has_supported_high_value_memory(candidates)} | "
                f"cond1={cond1} cond2={cond2} cond3={cond3} cond4={cond4} cond5={cond5} "
                f"-> {'ALLOW' if result else 'BLOCK'}"
            )
            for i, c in enumerate(candidates[:10]):
                item = c.get("item")
                _verbose(
                    f"  [{i}] id={getattr(item, 'result_id', '?')[:40] if item else '?'} "
                    f"kind={getattr(item, 'result_kind', '?') if item else '?'} "
                    f"type={getattr(item, 'type', None) if item else '?'} "
                    f"lex={c.get('lexical_score')} vec={c.get('vector_score')} "
                    f"src={getattr(item, 'retrieval_source', None) if item else None} "
                    f"support={c.get('support_grade', '?')} score={c.get('routing_score', '?')}"
                )

        return result

    # Fallback: composite scores absent (lexical-only retrieval mode).
    best_retrieval = max(float(c.get("retrieval_score", 0) or 0) for c in candidates)
    result = best_retrieval > 0
    if verbose:
        _verbose(
            f"INJECTION query={query_text[:80]!r} intent={intent} | SET_GATE fallback: "
            f"candidates={len(candidates)} best_retrieval={best_retrieval} "
            f"-> {'ALLOW' if result else 'BLOCK'}"
        )
    return result


def candidate_injection_eligible(
    candidate: dict,
    *,
    thresholds: InjectionThresholds = _DEFAULT_THRESHOLDS,
    verbose: bool = _VERBOSE,
) -> bool:
    """Per-candidate: does this specific candidate have enough grounding to inject?

    Primary gate: requires raw BM25 lexical score >= min_raw_lexical_bm25.
    This blocks vector-only candidates and low-lexical candidates that lack
    topical vocabulary overlap with the query.

    Type-aware secondary checks apply after the lexical floor passes.
    """
    raw_lex = candidate.get("lexical_score")
    raw_vec = candidate.get("vector_score")
    item = candidate.get("item")
    item_id = getattr(item, "result_id", "?")[:40] if item else "?"
    item_kind = getattr(item, "result_kind", "?") if item else "?"
    item_type = getattr(item, "type", None) if item else None

    if raw_lex is not None or raw_vec is not None:
        # Primary gate: require minimum raw BM25 lexical confirmation.
        raw_lex_value = float(raw_lex) if raw_lex is not None else 0.0
        if raw_lex is None or raw_lex_value < thresholds.min_raw_lexical_bm25:
            if verbose:
                _verbose(
                    f"  PER_CANDIDATE lexical_floor: id={item_id} kind={item_kind} type={item_type} "
                    f"raw_lex={raw_lex} vec={raw_vec} -> BLOCKED "
                    f"(requires raw BM25 >= {thresholds.min_raw_lexical_bm25})"
                )
            return False

        lex = normalize_lexical_score(raw_lex)
        vec = float(raw_vec or 0)
        is_source = item_kind == "source_hit"

        # Structured memory: lower bar
        if not is_source and item_type in HIGH_VALUE_MEMORY_TYPES:
            eligible = lex >= thresholds.high_value_lexical_floor or vec >= thresholds.high_value_vector_floor
            if verbose:
                _verbose(
                    f"  PER_CANDIDATE high_value: id={item_id} type={item_type} "
                    f"lex={lex} vec={vec} -> {'ELIGIBLE' if eligible else 'BLOCKED'} "
                    f"(floor: lex>={thresholds.high_value_lexical_floor} or vec>={thresholds.high_value_vector_floor})"
                )
            return eligible

        # Source hits and other types: higher bar
        eligible = (
            lex >= thresholds.candidate_lexical_floor
            or vec >= thresholds.candidate_vector_override
            or (raw_lex is None and vec >= thresholds.set_vector_high)
        )
        if verbose:
            _verbose(
                f"  PER_CANDIDATE source/other: id={item_id} kind={item_kind} type={item_type} "
                f"lex={lex} vec={vec} -> {'ELIGIBLE' if eligible else 'BLOCKED'} "
                f"(floor: lex>={thresholds.candidate_lexical_floor} or vec>={thresholds.candidate_vector_override})"
            )
        return eligible

    # No composite scores — lexical-only retrieval mode.
    retrieval = float(candidate.get("retrieval_score", 0) or 0)
    eligible = retrieval > 0
    if verbose:
        _verbose(
            f"  PER_CANDIDATE fallback: id={item_id} kind={item_kind} type={item_type} "
            f"retrieval={retrieval} -> {'ELIGIBLE' if eligible else 'BLOCKED'}"
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
