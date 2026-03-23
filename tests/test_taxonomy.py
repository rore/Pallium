"""Tests for the taxonomy module — fast, no external dependencies."""
from __future__ import annotations

from itertools import combinations

from evals.generated_exploratory.taxonomy import (
    DIMENSIONS,
    HIGH_RISK_PAIRS,
    P0_INVARIANTS,
    P1_INVARIANTS,
    all_pairwise_cells,
    cell_summary,
    dimension_pair_key,
    high_risk_cells,
    infer_priority_tier,
    pairwise_cells,
    validate_high_risk_pairs,
)


class TestDimensions:
    def test_dimensions_non_empty(self):
        assert len(DIMENSIONS) >= 10, f"Expected >=10 dimensions, got {len(DIMENSIONS)}"

    def test_all_dimensions_have_levels(self):
        for name, levels in DIMENSIONS.items():
            assert len(levels) >= 2, f"Dimension {name!r} must have >=2 levels, got {len(levels)}"

    def test_levels_are_unique(self):
        for name, levels in DIMENSIONS.items():
            assert len(levels) == len(set(levels)), f"Dimension {name!r} has duplicate levels"

    def test_memory_type_target_includes_production_types(self):
        types = set(DIMENSIONS["memory_type_target"])
        for expected in ["decision", "investigation_outcome", "thread_summary",
                         "task_checkpoint", "interest", "constraint_memory"]:
            assert expected in types, f"Missing memory type: {expected}"


class TestPairwiseCells:
    def test_basic_pair(self):
        cells = pairwise_cells("actor_count", "visibility")
        # 2 * 3 = 6
        assert len(cells) == 6
        for cell in cells:
            assert "actor_count" in cell
            assert "visibility" in cell

    def test_unknown_dimension_raises(self):
        import pytest
        with pytest.raises(KeyError, match="Unknown dimension"):
            pairwise_cells("nonexistent", "visibility")

    def test_same_dimension_raises(self):
        import pytest
        with pytest.raises(ValueError, match="must be different"):
            pairwise_cells("visibility", "visibility")

    def test_all_pairwise_cells_count(self):
        cells = all_pairwise_cells()
        # Each pair contributes product-of-levels cells.
        expected = sum(
            len(DIMENSIONS[a]) * len(DIMENSIONS[b])
            for a, b in combinations(sorted(DIMENSIONS), 2)
        )
        assert len(cells) == expected

    def test_high_risk_cells_subset(self):
        hr = high_risk_cells()
        all_c = all_pairwise_cells()
        assert len(hr) <= len(all_c)
        assert len(hr) > 0


class TestHighRiskPairs:
    def test_validation_passes(self):
        errors = validate_high_risk_pairs()
        assert errors == [], f"HIGH_RISK_PAIRS validation failed: {errors}"

    def test_pairs_are_distinct(self):
        for dim_a, dim_b in HIGH_RISK_PAIRS:
            assert dim_a != dim_b, f"HIGH_RISK_PAIRS contains same-dimension pair: {dim_a}"


class TestTierInference:
    def test_p0_from_correctness_invariant(self):
        assert infer_priority_tier(["INV-01"]) == "P0"
        assert infer_priority_tier(["INV-02", "INV-07"]) == "P0"
        assert infer_priority_tier(["INV-04"]) == "P0"

    def test_p1_from_quality_invariant(self):
        assert infer_priority_tier(["INV-03"]) == "P1"
        assert infer_priority_tier(["INV-05"]) == "P1"
        assert infer_priority_tier(["INV-10"]) == "P1"

    def test_p2_default(self):
        assert infer_priority_tier([]) == "P2"
        assert infer_priority_tier(["UNKNOWN"]) == "P2"

    def test_p0_overrides_p1(self):
        # If both P0 and P1 invariants are present, P0 wins.
        assert infer_priority_tier(["INV-01", "INV-05"]) == "P0"

    def test_invariant_sets_are_disjoint(self):
        assert P0_INVARIANTS & P1_INVARIANTS == set()


class TestDimensionPairKey:
    def test_stable_ordering(self):
        key = dimension_pair_key({"visibility": "public", "actor_count": "single_user"})
        assert key == "actor_count=single_user__visibility=public"

    def test_deterministic(self):
        cell = {"thread_relation": "cross_thread", "visibility": "private"}
        assert dimension_pair_key(cell) == dimension_pair_key(cell)


class TestCellSummary:
    def test_summary_structure(self):
        s = cell_summary()
        assert "dimensions" in s
        assert "dimension_pairs" in s
        assert "total_pairwise_cells" in s
        assert "high_risk_pairs" in s
        assert "high_risk_cells" in s
        assert s["dimensions"] == len(DIMENSIONS)
