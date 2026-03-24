"""Deterministic mapping from taxonomy cells to applicable invariants.

No LLM involved — this is a lookup from dimension values to invariant IDs.
Used by the generator to stamp each generated scenario with the invariants
it should be evaluated against.
"""
from __future__ import annotations

from typing import Any

from evals.generated_exploratory.invariants import ALL_INVARIANTS

# Universal invariants — apply to every scenario regardless of dimensions.
_UNIVERSAL = ["INV-03", "INV-06", "INV-07", "INV-09", "INV-13"]

# Dimension-value → conditional invariants.
# Note: INV-10 (idf_discrimination) is not derivable — it requires hand-authored
# scenario metadata (idf_expected_top_result_id) that the generator cannot produce.
_CONDITIONAL: list[tuple[str, str, list[str]]] = [
    # (dimension, level, invariant_ids)
    ("container_relation", "different_container", ["INV-01", "INV-04"]),
    ("visibility", "private", ["INV-04"]),
    ("visibility", "container", ["INV-04", "INV-11"]),
    ("visibility", "public", ["INV-04", "INV-11"]),
    ("source_role", "assistant", ["INV-02"]),
    ("query_intent", "backward_recall", ["INV-05"]),
    ("injection_outcome", "suppress", ["INV-08"]),
    ("actor_count", "multi_user", ["INV-12"]),
]


def derive_invariants(taxonomy_cell: dict[str, str]) -> list[str]:
    """Return sorted list of invariant IDs applicable to a taxonomy cell.

    Combines universal invariants with conditional ones triggered by the
    cell's dimension values. Deduplicates and validates against the registry.
    """
    ids: set[str] = set(_UNIVERSAL)
    for dim, level, inv_ids in _CONDITIONAL:
        if taxonomy_cell.get(dim) == level:
            ids.update(inv_ids)

    # Only return IDs that exist in the registry.
    valid = sorted(inv_id for inv_id in ids if inv_id in ALL_INVARIANTS)
    return valid


def derive_priority_tier(invariant_ids: list[str]) -> str:
    """Infer priority tier from derived invariants.

    Delegates to taxonomy.infer_priority_tier for consistency.
    """
    from evals.generated_exploratory.taxonomy import infer_priority_tier

    return infer_priority_tier(invariant_ids)


def build_generation_metadata(
    taxonomy_cell: dict[str, str],
    invariant_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build the _generation_metadata block for a generated scenario."""
    ids = invariant_ids or derive_invariants(taxonomy_cell)
    return {
        "taxonomy_cell": taxonomy_cell,
        "invariant_assertions": ids,
        "priority_tier": derive_priority_tier(ids),
        "tier_reason": "generated_unreviewed",
        "review_status": "generated",
    }
