"""Tests for the vector retrieval benchmark harness.

Deterministic tests that verify:
- Scenario JSON format (required fields)
- Runner plumbing (mock embeddings, mock VectorIndex, real lexical provider)
- Aggregate metric computation
- Gap confirmation logic (lexical misses, vector finds)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.vector_retrieval.vector_retrieval_runner import (
    BenchmarkSummary,
    MockEmbeddingProvider,
    MockVectorIndex,
    ScenarioResult,
    load_scenarios,
    run_benchmark,
    run_scenario,
)


SCENARIO_FILE = Path("evals/vector_retrieval/scenarios.json")

REQUIRED_SCENARIO_FIELDS = {
    "scenario_id",
    "scenario_family",
    "description",
    "prior_events",
    "memory_objects",
    "current_query",
    "expected_vector_recall",
    "expected_lexical_recall",
    "expected_memory_types",
}

REQUIRED_QUERY_FIELDS = {
    "text",
    "limit",
    "container_ref",
    "visibility_context",
}

REQUIRED_PRIOR_EVENT_FIELDS = {
    "source_type",
    "source_id",
    "content_type",
    "content",
    "container_ref",
}

REQUIRED_MEMORY_OBJECT_FIELDS = {
    "memory_id",
    "type",
    "payload",
    "text_views",
}


# ---------------------------------------------------------------------------
# Scenario format validation
# ---------------------------------------------------------------------------


class TestScenarioFormat:
    """Verify the scenario JSON file has correct structure."""

    def test_scenarios_file_exists(self) -> None:
        assert SCENARIO_FILE.exists(), f"Scenario file not found: {SCENARIO_FILE}"

    def test_scenarios_is_valid_json(self) -> None:
        raw = SCENARIO_FILE.read_text(encoding="utf-8")
        scenarios = json.loads(raw)
        assert isinstance(scenarios, list)
        assert len(scenarios) >= 4, "Expected at least 4 scenarios"

    def test_scenario_required_fields(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        for scenario in scenarios:
            missing = REQUIRED_SCENARIO_FIELDS - set(scenario.keys())
            assert not missing, (
                f"Scenario {scenario.get('scenario_id', '?')} missing fields: {missing}"
            )

    def test_query_required_fields(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        for scenario in scenarios:
            query = scenario["current_query"]
            missing = REQUIRED_QUERY_FIELDS - set(query.keys())
            assert not missing, (
                f"Scenario {scenario['scenario_id']} query missing fields: {missing}"
            )

    def test_prior_events_required_fields(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        for scenario in scenarios:
            for i, event in enumerate(scenario["prior_events"]):
                missing = REQUIRED_PRIOR_EVENT_FIELDS - set(event.keys())
                assert not missing, (
                    f"Scenario {scenario['scenario_id']} event[{i}] missing: {missing}"
                )

    def test_memory_objects_required_fields(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        for scenario in scenarios:
            for i, mo in enumerate(scenario["memory_objects"]):
                missing = REQUIRED_MEMORY_OBJECT_FIELDS - set(mo.keys())
                assert not missing, (
                    f"Scenario {scenario['scenario_id']} memory_object[{i}] missing: {missing}"
                )

    def test_expected_memory_types_non_empty(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        for scenario in scenarios:
            assert len(scenario["expected_memory_types"]) > 0, (
                f"Scenario {scenario['scenario_id']} has empty expected_memory_types"
            )

    def test_text_views_non_empty(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        for scenario in scenarios:
            for mo in scenario["memory_objects"]:
                assert len(mo["text_views"]) > 0, (
                    f"Scenario {scenario['scenario_id']} memory {mo['memory_id']} "
                    "has empty text_views"
                )

    def test_unique_scenario_ids(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        ids = [s["scenario_id"] for s in scenarios]
        assert len(ids) == len(set(ids)), f"Duplicate scenario IDs: {ids}"


# ---------------------------------------------------------------------------
# Mock component tests
# ---------------------------------------------------------------------------


class TestMockComponents:
    """Verify mock embedding provider and vector index work correctly."""

    def test_mock_embedding_returns_vector_per_input(self) -> None:
        provider = MockEmbeddingProvider()
        vectors = provider.embed(["hello", "world"])
        assert len(vectors) == 2
        assert len(vectors[0]) == 4

    def test_mock_embedding_custom_text_vectors(self) -> None:
        custom = {"query": [0.9, 0.8, 0.7, 0.6]}
        provider = MockEmbeddingProvider(text_vectors=custom)
        vectors = provider.embed(["query", "other"])
        assert vectors[0] == [0.9, 0.8, 0.7, 0.6]
        assert vectors[1] == [0.1, 0.2, 0.3, 0.4]  # default

    def test_mock_embedding_dimensions(self) -> None:
        provider = MockEmbeddingProvider(dims=8)
        assert provider.dimensions() == 8

    def test_mock_vector_index_search(self) -> None:
        index = MockVectorIndex(hits=[("a", 0.9), ("b", 0.7)])
        results = index.search([0.1, 0.2], k=10)
        assert results == [("a", 0.9), ("b", 0.7)]

    def test_mock_vector_index_respects_k(self) -> None:
        index = MockVectorIndex(hits=[("a", 0.9), ("b", 0.7), ("c", 0.5)])
        results = index.search([0.1], k=2)
        assert len(results) == 2

    def test_mock_vector_index_empty(self) -> None:
        index = MockVectorIndex()
        results = index.search([0.1], k=5)
        assert results == []


# ---------------------------------------------------------------------------
# Per-scenario runner tests
# ---------------------------------------------------------------------------


class TestRunScenario:
    """Run each scenario individually and verify gap confirmation."""

    def test_all_scenarios_run_without_error(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        for scenario in scenarios:
            result = run_scenario(scenario)
            assert isinstance(result, ScenarioResult), (
                f"Scenario {scenario['scenario_id']} did not return ScenarioResult"
            )

    def test_lexical_misses_abstract_queries(self) -> None:
        """All scenarios are designed so lexical has zero overlap -> no hits."""
        scenarios = load_scenarios(SCENARIO_FILE)
        for scenario in scenarios:
            if scenario["expected_lexical_recall"] is False:
                result = run_scenario(scenario)
                assert not result.lexical_found, (
                    f"Scenario {scenario['scenario_id']}: lexical should MISS "
                    f"but found a result"
                )

    def test_vector_finds_expected_memory(self) -> None:
        """All scenarios with expected_vector_recall=True should have vector hits."""
        scenarios = load_scenarios(SCENARIO_FILE)
        for scenario in scenarios:
            if scenario["expected_vector_recall"] is True:
                result = run_scenario(scenario)
                assert result.vector_found, (
                    f"Scenario {scenario['scenario_id']}: vector should FIND "
                    f"but missed"
                )

    def test_gap_confirmed_for_all_scenarios(self) -> None:
        """Every scenario should confirm the gap: lexical miss + vector hit."""
        scenarios = load_scenarios(SCENARIO_FILE)
        for scenario in scenarios:
            result = run_scenario(scenario)
            assert result.expected_gap_confirmed, (
                f"Scenario {scenario['scenario_id']}: gap NOT confirmed "
                f"(lexical_found={result.lexical_found}, "
                f"vector_found={result.vector_found})"
            )

    def test_cosine_similarity_recorded(self) -> None:
        """Vector results should include the mock cosine similarity."""
        scenarios = load_scenarios(SCENARIO_FILE)
        for scenario in scenarios:
            result = run_scenario(scenario, mock_vector_similarity=0.85)
            if result.vector_found:
                assert result.vector_cosine_similarity is not None, (
                    f"Scenario {scenario['scenario_id']}: missing cosine_similarity"
                )
                assert result.vector_cosine_similarity == pytest.approx(0.85), (
                    f"Scenario {scenario['scenario_id']}: "
                    f"expected sim=0.85, got {result.vector_cosine_similarity}"
                )

    def test_vector_above_threshold(self) -> None:
        """With mock similarity 0.85 and threshold 0.3, all should pass."""
        scenarios = load_scenarios(SCENARIO_FILE)
        for scenario in scenarios:
            result = run_scenario(scenario, min_similarity=0.3, mock_vector_similarity=0.85)
            if result.vector_found:
                assert result.vector_above_threshold

    def test_below_threshold_produces_no_vector_hit(self) -> None:
        """When mock similarity is below threshold, vector should miss."""
        scenarios = load_scenarios(SCENARIO_FILE)
        scenario = scenarios[0]
        result = run_scenario(
            scenario, min_similarity=0.9, mock_vector_similarity=0.5,
        )
        assert not result.vector_found
        assert not result.vector_above_threshold
        assert not result.expected_gap_confirmed


# ---------------------------------------------------------------------------
# Full benchmark aggregate tests
# ---------------------------------------------------------------------------


class TestBenchmarkAggregates:
    """Verify aggregate metric computation from run_benchmark."""

    def test_benchmark_returns_summary(self) -> None:
        summary = run_benchmark(SCENARIO_FILE)
        assert isinstance(summary, BenchmarkSummary)

    def test_total_scenarios_matches_file(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        summary = run_benchmark(SCENARIO_FILE)
        assert summary.total_scenarios == len(scenarios)

    def test_vector_recall_rate_is_1_0(self) -> None:
        """All scenarios should be vector-recalled with default mock similarity."""
        summary = run_benchmark(SCENARIO_FILE)
        assert summary.vector_recall_rate == pytest.approx(1.0)

    def test_lexical_recall_rate_is_0_0(self) -> None:
        """All scenarios are designed for zero lexical overlap."""
        summary = run_benchmark(SCENARIO_FILE)
        assert summary.lexical_recall_rate == pytest.approx(0.0)

    def test_gap_confirmation_rate_is_1_0(self) -> None:
        """Every scenario should confirm the gap."""
        summary = run_benchmark(SCENARIO_FILE)
        assert summary.gap_confirmation_rate == pytest.approx(1.0)

    def test_threshold_pass_rate_is_1_0(self) -> None:
        """All vector hits should be above threshold with default mock sim."""
        summary = run_benchmark(SCENARIO_FILE)
        assert summary.threshold_pass_rate == pytest.approx(1.0)

    def test_all_scenario_results_present(self) -> None:
        summary = run_benchmark(SCENARIO_FILE)
        assert len(summary.scenario_results) == summary.total_scenarios

    def test_scenario_result_ids_match(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        summary = run_benchmark(SCENARIO_FILE)
        expected_ids = {s["scenario_id"] for s in scenarios}
        actual_ids = {r.scenario_id for r in summary.scenario_results}
        assert expected_ids == actual_ids

    def test_below_threshold_degrades_rates(self) -> None:
        """When mock similarity is below threshold, aggregates should reflect misses."""
        summary = run_benchmark(
            SCENARIO_FILE,
            min_similarity=0.9,
            mock_vector_similarity=0.5,
        )
        assert summary.vector_recall_rate == pytest.approx(0.0)
        assert summary.gap_confirmation_rate == pytest.approx(0.0)
        assert summary.threshold_pass_rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Scenario content validation
# ---------------------------------------------------------------------------


class TestScenarioContent:
    """Validate that scenarios cover the required failure classes."""

    def test_has_task_checkpoint_scenario(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        types_covered = set()
        for s in scenarios:
            types_covered.update(s["expected_memory_types"])
        assert "task_checkpoint" in types_covered

    def test_has_investigation_outcome_scenario(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        types_covered = set()
        for s in scenarios:
            types_covered.update(s["expected_memory_types"])
        assert "investigation_outcome" in types_covered

    def test_has_pattern_memory_scenario(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        types_covered = set()
        for s in scenarios:
            types_covered.update(s["expected_memory_types"])
        assert "pattern_memory" in types_covered

    def test_has_decision_scenario(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        types_covered = set()
        for s in scenarios:
            types_covered.update(s["expected_memory_types"])
        assert "decision" in types_covered

    def test_all_use_library_domain(self) -> None:
        """All scenarios should use the neutral library domain."""
        scenarios = load_scenarios(SCENARIO_FILE)
        for s in scenarios:
            container = s["current_query"]["container_ref"]
            assert container.startswith("chat:library"), (
                f"Scenario {s['scenario_id']} uses non-library container: {container}"
            )

    def test_scenario_families_present(self) -> None:
        scenarios = load_scenarios(SCENARIO_FILE)
        families = {s["scenario_family"] for s in scenarios}
        assert len(families) >= 2, (
            f"Expected at least 2 scenario families, got {families}"
        )
