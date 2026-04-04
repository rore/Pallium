"""Pre-routing relevance floor. Drops candidates failing both thresholds."""
from __future__ import annotations

from dataclasses import dataclass
from core.models import QueryResultItem


@dataclass(frozen=True)
class FloorThresholds:
    """Relevance floor thresholds. Swappable for testing."""
    min_vector: int = 580   # cosine * 1000 (0.58)
    min_lexical: int = 2    # IDF score


_DEFAULT_THRESHOLDS = FloorThresholds()


@dataclass(frozen=True)
class FloorResult:
    survivors: list[QueryResultItem]
    filtered_count: int
    filtered_score_ranges: dict[str, tuple[int, int]]


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
    filtered_lexicals: list[int] = []

    for item in candidates:
        vec = int(getattr(item, "vector_score", 0) or 0)
        lex = int(getattr(item, "lexical_score", 0) or 0)
        if vec >= thresholds.min_vector or lex >= thresholds.min_lexical:
            survivors.append(item)
        else:
            filtered_vectors.append(vec)
            filtered_lexicals.append(lex)

    ranges: dict[str, tuple[int, int]] = {}
    if filtered_vectors:
        ranges["vector"] = (min(filtered_vectors), max(filtered_vectors))
    if filtered_lexicals:
        ranges["lexical"] = (min(filtered_lexicals), max(filtered_lexicals))

    return FloorResult(
        survivors=survivors,
        filtered_count=len(candidates) - len(survivors),
        filtered_score_ranges=ranges,
    )
