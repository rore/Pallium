"""Pre-routing relevance floor. Drops candidates failing both thresholds."""
from __future__ import annotations

from dataclasses import dataclass
from core.models import QueryResultItem
from semantic.agent_conversation_memory_routing_constants import normalize_lexical_score


@dataclass(frozen=True)
class FloorThresholds:
    """Relevance floor thresholds. Swappable for testing."""
    min_vector: int = 580       # cosine * 1000 (0.58)
    min_lexical: float = 0.33   # normalized 0-1 (≈ 2/6 raw BM25)


_DEFAULT_THRESHOLDS = FloorThresholds()


@dataclass(frozen=True)
class FloorResult:
    survivors: list[QueryResultItem]
    filtered_count: int
    filtered_score_ranges: dict[str, tuple[float, float]]


def apply_relevance_floor(
    candidates: list[QueryResultItem],
    *,
    thresholds: FloorThresholds = _DEFAULT_THRESHOLDS,
) -> FloorResult:
    """Filter candidates below both quality thresholds.

    A candidate survives if vector_score >= threshold OR lexical_score >= threshold.
    """
    survivors: list[QueryResultItem] = []
    filtered_vectors: list[int] = []
    filtered_lexicals: list[float] = []

    for item in candidates:
        raw_vec = getattr(item, "vector_score", None)
        raw_lex = getattr(item, "lexical_score", None)
        # If neither score is available, we have no basis to filter — pass through.
        if raw_vec is None and raw_lex is None:
            survivors.append(item)
            continue
        vec = int(raw_vec or 0)
        lex = normalize_lexical_score(raw_lex)
        # A candidate fails the floor only when both measured dimensions are weak.
        # A None score is treated as "no signal" — not as a failing score.
        vec_ok = raw_vec is not None and vec >= thresholds.min_vector
        lex_ok = raw_lex is not None and lex >= thresholds.min_lexical
        vec_fails = raw_vec is not None and vec < thresholds.min_vector
        lex_fails = raw_lex is not None and lex < thresholds.min_lexical
        if vec_ok or lex_ok:
            survivors.append(item)
        elif vec_fails and lex_fails:
            # Both dimensions present and both weak — filter.
            filtered_vectors.append(vec)
            filtered_lexicals.append(lex)
        else:
            # Only one dimension present and it's weak — not enough evidence to filter.
            survivors.append(item)

    ranges: dict[str, tuple[float, float]] = {}
    if filtered_vectors:
        ranges["vector"] = (min(filtered_vectors), max(filtered_vectors))
    if filtered_lexicals:
        ranges["lexical"] = (min(filtered_lexicals), max(filtered_lexicals))

    return FloorResult(
        survivors=survivors,
        filtered_count=len(candidates) - len(survivors),
        filtered_score_ranges=ranges,
    )
