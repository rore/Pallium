"""
Taxonomy of testing dimensions for automated exploratory QA.

Defines the dimensions, levels, pairwise cell generation, and high-risk
dimension pairs that should be prioritized for scenario generation.
"""
from __future__ import annotations

from itertools import combinations
from typing import Any


DIMENSIONS: dict[str, list[str]] = {
    "actor_count": ["single_user", "multi_user"],
    "thread_relation": ["same_thread", "cross_thread", "cross_session"],
    "container_relation": ["same_container", "different_container"],
    "visibility": ["private", "limited", "public"],
    "topic_pattern": ["single", "switch", "mixed", "return_to_prior"],
    "query_intent": ["forward", "backward_recall", "summary", "ambiguous"],
    "source_role": ["user", "assistant", "quoted_user"],
    "memory_type_target": [
        "decision",
        "investigation_outcome",
        "thread_summary",
        "task_checkpoint",
        "pattern_memory",
        "continuity_memory",
        "discussion_summary",
        "interest",
        "constraint_memory",
    ],
    "retrieval_path": ["lexical", "vector", "hybrid"],
    "injection_outcome": ["inject", "suppress", "partial_inject"],
    "scoring_quality": ["idf_discriminating", "common_word_overlap", "mixed"],
}

# Dimension pairs known to be high-risk based on manual exploratory findings.
# Each entry is a tuple of two dimension names.
HIGH_RISK_PAIRS: list[tuple[str, str]] = [
    ("thread_relation", "visibility"),
    ("thread_relation", "query_intent"),
    ("container_relation", "visibility"),
    ("actor_count", "visibility"),
    ("actor_count", "container_relation"),
    ("topic_pattern", "query_intent"),
    ("source_role", "memory_type_target"),
    ("query_intent", "injection_outcome"),
    ("thread_relation", "memory_type_target"),
    ("scoring_quality", "retrieval_path"),
    ("topic_pattern", "injection_outcome"),
    ("visibility", "memory_type_target"),
]

# Invariant-to-tier mapping: which invariants make a scenario P0 vs P1.
P0_INVARIANTS = frozenset({"INV-01", "INV-02", "INV-04", "INV-11", "INV-12", "INV-13"})
P1_INVARIANTS = frozenset({"INV-03", "INV-05", "INV-06", "INV-07", "INV-08", "INV-09", "INV-10"})


def pairwise_cells(dim_a: str, dim_b: str) -> list[dict[str, str]]:
    """Generate all level combinations for two dimensions.

    Returns a list of dicts, each with two keys (dim_a and dim_b) and their
    respective level values.
    """
    if dim_a not in DIMENSIONS:
        raise KeyError(f"Unknown dimension: {dim_a!r}")
    if dim_b not in DIMENSIONS:
        raise KeyError(f"Unknown dimension: {dim_b!r}")
    if dim_a == dim_b:
        raise ValueError(f"Dimensions must be different, got {dim_a!r} twice")
    return [
        {dim_a: level_a, dim_b: level_b}
        for level_a in DIMENSIONS[dim_a]
        for level_b in DIMENSIONS[dim_b]
    ]


def all_pairwise_cells() -> list[dict[str, str]]:
    """Generate all cells across all dimension pairs.

    Returns the union of pairwise_cells for every unique pair of dimensions.
    Cells are not deduplicated across pairs because each cell is keyed by its
    specific dimension pair.
    """
    cells: list[dict[str, str]] = []
    for dim_a, dim_b in combinations(sorted(DIMENSIONS), 2):
        cells.extend(pairwise_cells(dim_a, dim_b))
    return cells


def high_risk_cells() -> list[dict[str, str]]:
    """Generate cells for high-risk dimension pairs only."""
    cells: list[dict[str, str]] = []
    for dim_a, dim_b in HIGH_RISK_PAIRS:
        cells.extend(pairwise_cells(dim_a, dim_b))
    return cells


def validate_high_risk_pairs() -> list[str]:
    """Return error messages for any HIGH_RISK_PAIRS referencing unknown dimensions."""
    errors: list[str] = []
    for dim_a, dim_b in HIGH_RISK_PAIRS:
        if dim_a not in DIMENSIONS:
            errors.append(f"HIGH_RISK_PAIRS: unknown dimension {dim_a!r}")
        if dim_b not in DIMENSIONS:
            errors.append(f"HIGH_RISK_PAIRS: unknown dimension {dim_b!r}")
    return errors


# Validate on import — fail fast on typos.
_validation_errors = validate_high_risk_pairs()
if _validation_errors:
    raise ValueError(f"Taxonomy validation failed: {_validation_errors}")


def infer_priority_tier(invariant_ids: list[str]) -> str:
    """Infer priority tier from the invariants a scenario tests.

    Returns "P0" if any correctness invariant is present, "P1" if any quality
    invariant is present, "P2" otherwise.
    """
    ids = set(invariant_ids)
    if ids & P0_INVARIANTS:
        return "P0"
    if ids & P1_INVARIANTS:
        return "P1"
    return "P2"


def dimension_pair_key(cell: dict[str, str]) -> str:
    """Return a stable string key for a taxonomy cell.

    Example: {"thread_relation": "cross_thread", "visibility": "private"}
    becomes "thread_relation=cross_thread__visibility=private"
    """
    parts = sorted(f"{k}={v}" for k, v in cell.items())
    return "__".join(parts)


def cell_summary() -> dict[str, Any]:
    """Return a summary of the taxonomy for reporting."""
    total_pairs = len(list(combinations(sorted(DIMENSIONS), 2)))
    all_cells = all_pairwise_cells()
    hr_cells = high_risk_cells()
    return {
        "dimensions": len(DIMENSIONS),
        "dimension_pairs": total_pairs,
        "total_pairwise_cells": len(all_cells),
        "high_risk_pairs": len(HIGH_RISK_PAIRS),
        "high_risk_cells": len(hr_cells),
    }
