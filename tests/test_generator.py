"""Tests for invariant_derivation and generator modules."""
from __future__ import annotations

import json

from evals.generated_exploratory.invariant_derivation import (
    build_generation_metadata,
    derive_invariants,
    derive_priority_tier,
)
from evals.generated_exploratory.generator import (
    _build_cell_description,
    _build_dimension_guidance,
    _parse_cell_spec,
    _stamp_metadata,
)


class TestDeriveInvariants:
    def test_universal_always_present(self):
        ids = derive_invariants({})
        assert "INV-03" in ids
        assert "INV-06" in ids
        assert "INV-07" in ids
        assert "INV-09" in ids
        assert "INV-13" in ids

    def test_cross_container_triggers_scope_invariants(self):
        ids = derive_invariants({"container_relation": "different_container"})
        assert "INV-01" in ids
        assert "INV-04" in ids

    def test_public_triggers_personal_memory_check(self):
        ids = derive_invariants({"visibility": "public"})
        assert "INV-11" in ids

    def test_limited_triggers_personal_memory_check(self):
        ids = derive_invariants({"visibility": "container"})
        assert "INV-11" in ids

    def test_private_does_not_trigger_personal_memory_check(self):
        ids = derive_invariants({"visibility": "private"})
        assert "INV-11" not in ids

    def test_multi_user_triggers_actor_leak_check(self):
        ids = derive_invariants({"actor_count": "multi_user"})
        assert "INV-12" in ids

    def test_assistant_role_triggers_wrong_role_check(self):
        ids = derive_invariants({"source_role": "assistant"})
        assert "INV-02" in ids

    def test_backward_recall_triggers_noise_check(self):
        ids = derive_invariants({"query_intent": "backward_recall"})
        assert "INV-05" in ids

    def test_suppress_triggers_noise_injection_check(self):
        ids = derive_invariants({"injection_outcome": "suppress"})
        assert "INV-08" in ids

    def test_combined_cell(self):
        ids = derive_invariants({
            "container_relation": "different_container",
            "visibility": "container",
            "actor_count": "multi_user",
        })
        assert "INV-01" in ids
        assert "INV-04" in ids
        assert "INV-11" in ids
        assert "INV-12" in ids

    def test_only_valid_invariant_ids_returned(self):
        ids = derive_invariants({"container_relation": "different_container"})
        from evals.generated_exploratory.invariants import ALL_INVARIANTS
        for inv_id in ids:
            assert inv_id in ALL_INVARIANTS


class TestDerivePriorityTier:
    def test_p0_for_scope_invariant(self):
        assert derive_priority_tier(["INV-01", "INV-07"]) == "P0"

    def test_p0_for_actor_invariant(self):
        assert derive_priority_tier(["INV-12"]) == "P0"

    def test_p1_for_quality_invariant(self):
        assert derive_priority_tier(["INV-03", "INV-07"]) == "P1"

    def test_p2_for_no_invariants(self):
        assert derive_priority_tier([]) == "P2"


class TestBuildGenerationMetadata:
    def test_includes_required_fields(self):
        meta = build_generation_metadata({"visibility": "public"})
        assert "taxonomy_cell" in meta
        assert "invariant_assertions" in meta
        assert "priority_tier" in meta
        assert meta["tier_reason"] == "generated_unreviewed"
        assert meta["review_status"] == "generated"

    def test_tier_derived_from_invariants(self):
        meta = build_generation_metadata({"container_relation": "different_container"})
        assert meta["priority_tier"] == "P0"  # INV-01 is P0


class TestGeneratorHelpers:
    def test_parse_cell_spec_single(self):
        cell = _parse_cell_spec("visibility=private")
        assert cell == {"visibility": "private"}

    def test_parse_cell_spec_multi(self):
        cell = _parse_cell_spec("thread_relation=cross_thread,visibility=private")
        assert cell == {"thread_relation": "cross_thread", "visibility": "private"}

    def test_parse_cell_spec_invalid_dim(self):
        import pytest
        with pytest.raises(ValueError, match="Unknown dimension"):
            _parse_cell_spec("nonexistent=value")

    def test_parse_cell_spec_invalid_level(self):
        import pytest
        with pytest.raises(ValueError, match="Unknown level"):
            _parse_cell_spec("visibility=nonexistent")

    def test_build_cell_description(self):
        desc = _build_cell_description({"visibility": "private", "thread_relation": "cross_thread"})
        assert "visibility: private" in desc
        assert "thread_relation: cross_thread" in desc

    def test_build_dimension_guidance(self):
        guidance = _build_dimension_guidance({"visibility": "private"})
        assert "private" in guidance.lower()

    def test_stamp_metadata_adds_metadata(self):
        scenarios = [{"scenario_id": "test-1", "steps": [
            {"action": "query", "query": {"text": "test"}},
        ]}]
        result = _stamp_metadata(scenarios, {"visibility": "public"}, "batch-1")
        assert result[0]["_generation_metadata"]["taxonomy_cell"] == {"visibility": "public"}
        assert result[0]["_generation_metadata"]["batch_id"] == "batch-1"

    def test_stamp_metadata_adds_invariants_to_query_steps(self):
        scenarios = [{"scenario_id": "test-1", "steps": [
            {"action": "ingest", "events": []},
            {"action": "query", "query": {"text": "test"}},
        ]}]
        result = _stamp_metadata(scenarios, {"container_relation": "different_container"}, "b1")
        query_step = result[0]["steps"][1]
        assert "invariant_assertions" in query_step
        assert "INV-01" in query_step["invariant_assertions"]
