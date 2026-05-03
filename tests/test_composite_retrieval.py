from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from core.models import (
    EvidenceReference,
    FusionStageTrace,
    QueryFilters,
    QueryResultItem,
    QueryTrace,
    RetrievalStageTrace,
    RetrievalTraceHit,
)
from retrieval.base import RetrievalProvider, RetrievalQueryResult
from retrieval.composite import CompositeRetrievalProvider, RRF_K, RRF_SCORE_SCALE, RRF_LEXICAL_WEIGHT, RRF_VECTOR_WEIGHT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    result_id: str,
    score: int = 100,
    result_kind: str = "memory_hit",
    memory_object_id: str | None = None,
    payload: dict | None = None,
    excerpt: str | None = None,
) -> QueryResultItem:
    """Build a minimal QueryResultItem for testing."""
    return QueryResultItem(
        result_id=result_id,
        result_kind=result_kind,
        score=score,
        evidence=[],
        memory_object_id=memory_object_id or result_id.replace("memory_object:", ""),
        payload=payload or {"text": f"content for {result_id}"},
        excerpt=excerpt,
    )


def _make_trace(
    stage_name: str = "lexical",
    candidate_count: int = 0,
) -> QueryTrace:
    return QueryTrace(
        query_text="test query",
        query_tokens=("test", "query"),
        limit=10,
        filters=None,
        stages=(
            RetrievalStageTrace(
                stage_name=stage_name,
                candidate_hits_considered=candidate_count,
                candidate_hits=(),
                selected_hits=(),
            ),
        ),
    )


class StubRetrievalProvider(RetrievalProvider):
    """Stub that returns pre-configured results."""

    def __init__(self, results: list[QueryResultItem], trace: QueryTrace | None = None) -> None:
        self._results = results
        self._trace = trace

    def query(
        self,
        text: str,
        limit: int,
        filters: QueryFilters | None = None,
        *,
        visibility: str | None = None,
        query_container_ref: str | None = None,
        include_trace: bool = False,
        require_visibility: bool = False,
        query_actor_ref: str | None = None,
    ) -> RetrievalQueryResult:
        return RetrievalQueryResult(
            results=self._results[:limit],
            trace=self._trace if include_trace else None,
        )


# ---------------------------------------------------------------------------
# Tests: vector=None passthrough
# ---------------------------------------------------------------------------


class TestVectorNonePassthrough:
    def test_returns_lexical_results_unchanged(self):
        items = [_make_result("memory_object:a", score=200), _make_result("memory_object:b", score=100)]
        lexical = StubRetrievalProvider(items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=None)

        result = composite.query("test", limit=10)

        assert result.results == items
        assert len(result.results) == 2

    def test_returns_lexical_trace_unchanged(self):
        items = [_make_result("memory_object:a")]
        trace = _make_trace("lexical", 5)
        lexical = StubRetrievalProvider(items, trace=trace)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=None)

        result = composite.query("test", limit=10, include_trace=True)

        assert result.trace is trace

    def test_passes_kwargs_through(self):
        """Ensure visibility and filter args reach the lexical provider."""
        captured = {}

        class CapturingProvider(RetrievalProvider):
            def query(self, text, limit, filters=None, *, visibility=None, query_container_ref=None, include_trace=False, require_visibility=False, query_actor_ref=None):
                captured["text"] = text
                captured["limit"] = limit
                captured["filters"] = filters
                captured["visibility"] = visibility
                captured["include_trace"] = include_trace
                captured["require_visibility"] = require_visibility
                return RetrievalQueryResult(results=[], trace=None)

        vis = "public"
        filt = QueryFilters(container_ref="c1")
        composite = CompositeRetrievalProvider(lexical=CapturingProvider(), vector=None)
        composite.query("hello", 5, filt, visibility=vis, include_trace=True, require_visibility=True)

        assert captured["text"] == "hello"
        assert captured["limit"] == 5
        assert captured["filters"] == filt
        assert captured["visibility"] == vis
        assert captured["include_trace"] is True
        assert captured["require_visibility"] is True


# ---------------------------------------------------------------------------
# Tests: RRF ranking
# ---------------------------------------------------------------------------


class TestRRFRanking:
    def test_dual_source_items_rank_higher(self):
        """An item found by both providers should rank higher than one found by only one."""
        # Item A: lexical rank 1, vector rank 2
        # Item B: lexical rank 2 only
        # Item C: vector rank 1 only
        lexical_items = [
            _make_result("memory_object:a", score=200),
            _make_result("memory_object:b", score=100),
        ]
        vector_items = [
            _make_result("memory_object:c", score=800),
            _make_result("memory_object:a", score=700),
        ]

        lexical = StubRetrievalProvider(lexical_items)
        vector = StubRetrievalProvider(vector_items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10)

        # A is in both (rank 1 lexical, rank 2 vector) -> highest RRF
        assert result.results[0].result_id == "memory_object:a"
        # Remaining two are single-source
        remaining_ids = {r.result_id for r in result.results[1:]}
        assert remaining_ids == {"memory_object:b", "memory_object:c"}

    def test_rrf_score_computation(self):
        """Verify the exact RRF score formula: sum of 1/(k+rank) across providers."""
        lexical_items = [
            _make_result("memory_object:a", score=200),
        ]
        vector_items = [
            _make_result("memory_object:a", score=800),
        ]

        lexical = StubRetrievalProvider(lexical_items)
        vector = StubRetrievalProvider(vector_items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10)

        expected_rrf = RRF_LEXICAL_WEIGHT / (RRF_K + 1) + RRF_VECTOR_WEIGHT / (RRF_K + 1)  # Both at rank 1
        expected_score = int(expected_rrf * RRF_SCORE_SCALE)
        assert result.results[0].score == expected_score

    def test_single_source_rrf_score(self):
        """Item from only one provider gets 1/(k+rank) * SCALE."""
        lexical_items = [_make_result("memory_object:a", score=200)]
        vector_items = [_make_result("memory_object:b", score=800)]

        lexical = StubRetrievalProvider(lexical_items)
        vector = StubRetrievalProvider(vector_items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10)

        # Single-source items at rank 1: lexical gets RRF_LEXICAL_WEIGHT, vector gets RRF_VECTOR_WEIGHT
        for r in result.results:
            if r.retrieval_source == "lexical":
                expected = int(RRF_LEXICAL_WEIGHT / (RRF_K + 1) * RRF_SCORE_SCALE)
            else:
                expected = int(RRF_VECTOR_WEIGHT / (RRF_K + 1) * RRF_SCORE_SCALE)
            assert r.score == expected


# ---------------------------------------------------------------------------
# Tests: deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_same_result_id_deduped_to_one(self):
        """Same result_id from both providers produces one result tagged 'both'."""
        lexical_items = [
            _make_result("memory_object:shared", score=200, payload={"source": "lexical"}),
        ]
        vector_items = [
            _make_result("memory_object:shared", score=800, payload={"source": "vector"}),
        ]

        lexical = StubRetrievalProvider(lexical_items)
        vector = StubRetrievalProvider(vector_items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10)

        assert len(result.results) == 1
        assert result.results[0].result_id == "memory_object:shared"
        assert result.results[0].retrieval_source == "both"

    def test_lexical_version_kept_on_dedup(self):
        """When deduplicating, the lexical version's payload is preserved."""
        lexical_items = [
            _make_result("memory_object:shared", score=200, payload={"source": "lexical"}),
        ]
        vector_items = [
            _make_result("memory_object:shared", score=800, payload={"source": "vector"}),
        ]

        lexical = StubRetrievalProvider(lexical_items)
        vector = StubRetrievalProvider(vector_items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10)

        assert result.results[0].payload == {"source": "lexical"}

    def test_lexical_only_tagged_lexical(self):
        """Item found only in lexical gets retrieval_source='lexical'."""
        lexical_items = [_make_result("memory_object:lex_only", score=200)]
        vector_items = [_make_result("memory_object:vec_only", score=800)]

        lexical = StubRetrievalProvider(lexical_items)
        vector = StubRetrievalProvider(vector_items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10)

        by_id = {r.result_id: r for r in result.results}
        assert by_id["memory_object:lex_only"].retrieval_source == "lexical"
        assert by_id["memory_object:vec_only"].retrieval_source == "vector"


# ---------------------------------------------------------------------------
# Tests: score range
# ---------------------------------------------------------------------------


class TestScoreRange:
    def test_score_range_typical_inputs(self):
        """Scores should fall in the 7-24 range for typical rank-1 items."""
        lexical_items = [_make_result(f"memory_object:l{i}", score=200 - i) for i in range(10)]
        vector_items = [_make_result(f"memory_object:v{i}", score=800 - i) for i in range(10)]

        lexical = StubRetrievalProvider(lexical_items)
        vector = StubRetrievalProvider(vector_items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=20)

        max_score = int((RRF_LEXICAL_WEIGHT + RRF_VECTOR_WEIGHT) / (RRF_K + 1) * RRF_SCORE_SCALE)
        min_score = int(min(RRF_LEXICAL_WEIGHT, RRF_VECTOR_WEIGHT) / (RRF_K + 10) * RRF_SCORE_SCALE)
        for r in result.results:
            assert min_score <= r.score <= max_score, f"Score {r.score} for {r.result_id} outside expected range"

    def test_dual_source_rank1_score(self):
        """Both at rank 1: (1.5+1.0)/(60+1) * 600 = 24.59 -> 24."""
        lexical_items = [_make_result("memory_object:a")]
        vector_items = [_make_result("memory_object:a")]

        lexical = StubRetrievalProvider(lexical_items)
        vector = StubRetrievalProvider(vector_items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10)
        expected = int((RRF_LEXICAL_WEIGHT + RRF_VECTOR_WEIGHT) / (RRF_K + 1) * RRF_SCORE_SCALE)
        assert result.results[0].score == expected

    def test_single_source_rank1_scores(self):
        """Single source at rank 1: lexical gets 1.5/61*600=14, vector gets 1.0/61*600=9."""
        lexical_items = [_make_result("memory_object:a")]
        vector_items = [_make_result("memory_object:b")]

        lexical = StubRetrievalProvider(lexical_items)
        vector = StubRetrievalProvider(vector_items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10)
        by_id = {r.result_id: r for r in result.results}
        expected_lex = int(RRF_LEXICAL_WEIGHT / (RRF_K + 1) * RRF_SCORE_SCALE)
        expected_vec = int(RRF_VECTOR_WEIGHT / (RRF_K + 1) * RRF_SCORE_SCALE)
        assert by_id["memory_object:a"].score == expected_lex
        assert by_id["memory_object:b"].score == expected_vec


# ---------------------------------------------------------------------------
# Tests: fusion trace
# ---------------------------------------------------------------------------


class TestFusionTrace:
    def test_fusion_trace_present(self):
        lexical_items = [_make_result("memory_object:a"), _make_result("memory_object:b")]
        vector_items = [_make_result("memory_object:a"), _make_result("memory_object:c")]

        lexical = StubRetrievalProvider(lexical_items, trace=_make_trace("lexical", 2))
        vector = StubRetrievalProvider(vector_items, trace=_make_trace("vector", 2))
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10, include_trace=True)

        assert result.trace is not None
        assert result.trace.fusion_trace is not None

    def test_fusion_trace_counts(self):
        lexical_items = [_make_result("memory_object:a"), _make_result("memory_object:b")]
        vector_items = [_make_result("memory_object:a"), _make_result("memory_object:c")]

        lexical = StubRetrievalProvider(lexical_items, trace=_make_trace("lexical", 2))
        vector = StubRetrievalProvider(vector_items, trace=_make_trace("vector", 2))
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10, include_trace=True)
        ft = result.trace.fusion_trace

        assert ft.lexical_candidate_count == 2
        assert ft.vector_candidate_count == 2
        assert ft.fused_candidate_count == 3  # a, b, c
        assert ft.both_sources_count == 1  # a
        assert ft.selected_count == 3
        assert ft.k == RRF_K
        assert ft.rrf_score_scale == RRF_SCORE_SCALE

    def test_fusion_trace_hits_match_results(self):
        lexical_items = [_make_result("memory_object:a")]
        vector_items = [_make_result("memory_object:a")]

        lexical = StubRetrievalProvider(lexical_items, trace=_make_trace("lexical", 1))
        vector = StubRetrievalProvider(vector_items, trace=_make_trace("vector", 1))
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10, include_trace=True)
        ft = result.trace.fusion_trace

        assert len(ft.hits) == 1
        hit = ft.hits[0]
        assert hit.result_id == "memory_object:a"
        assert hit.lexical_rank == 1
        assert hit.vector_rank == 1
        assert hit.retrieval_source == "both"
        assert hit.rrf_rank == 1
        assert hit.fused_score == result.results[0].score

    def test_no_fusion_trace_without_include_trace(self):
        lexical_items = [_make_result("memory_object:a")]
        vector_items = [_make_result("memory_object:a")]

        lexical = StubRetrievalProvider(lexical_items)
        vector = StubRetrievalProvider(vector_items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10, include_trace=False)
        assert result.trace is None

    def test_stages_merged_from_both_providers(self):
        lexical_items = [_make_result("memory_object:a")]
        vector_items = [_make_result("memory_object:b")]

        lexical = StubRetrievalProvider(lexical_items, trace=_make_trace("lexical", 1))
        vector = StubRetrievalProvider(vector_items, trace=_make_trace("vector", 1))
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10, include_trace=True)

        stage_names = [s.stage_name for s in result.trace.stages]
        assert "lexical" in stage_names
        assert "vector" in stage_names


# ---------------------------------------------------------------------------
# Tests: limit enforcement
# ---------------------------------------------------------------------------


class TestLimitEnforcement:
    def test_limit_respected(self):
        lexical_items = [_make_result(f"memory_object:l{i}") for i in range(5)]
        vector_items = [_make_result(f"memory_object:v{i}") for i in range(5)]

        lexical = StubRetrievalProvider(lexical_items)
        vector = StubRetrievalProvider(vector_items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=3)

        assert len(result.results) <= 3

    def test_limit_one(self):
        lexical_items = [_make_result("memory_object:a"), _make_result("memory_object:b")]
        vector_items = [_make_result("memory_object:c")]

        lexical = StubRetrievalProvider(lexical_items)
        vector = StubRetrievalProvider(vector_items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=1)
        assert len(result.results) == 1

    def test_limit_larger_than_available(self):
        lexical_items = [_make_result("memory_object:a")]
        vector_items = [_make_result("memory_object:b")]

        lexical = StubRetrievalProvider(lexical_items)
        vector = StubRetrievalProvider(vector_items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=100)
        assert len(result.results) == 2


# ---------------------------------------------------------------------------
# Tests: empty results
# ---------------------------------------------------------------------------


class TestEmptyResults:
    def test_both_empty(self):
        lexical = StubRetrievalProvider([])
        vector = StubRetrievalProvider([])
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10)
        assert result.results == []

    def test_lexical_empty_vector_has_results(self):
        vector_items = [_make_result("memory_object:v1"), _make_result("memory_object:v2")]

        lexical = StubRetrievalProvider([])
        vector = StubRetrievalProvider(vector_items)
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10)

        assert len(result.results) == 2
        for r in result.results:
            assert r.retrieval_source == "vector"

    def test_vector_empty_lexical_has_results(self):
        lexical_items = [_make_result("memory_object:l1"), _make_result("memory_object:l2")]

        lexical = StubRetrievalProvider(lexical_items)
        vector = StubRetrievalProvider([])
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10)

        assert len(result.results) == 2
        for r in result.results:
            assert r.retrieval_source == "lexical"

    def test_both_empty_with_trace(self):
        lexical = StubRetrievalProvider([], trace=_make_trace("lexical", 0))
        vector = StubRetrievalProvider([], trace=_make_trace("vector", 0))
        composite = CompositeRetrievalProvider(lexical=lexical, vector=vector)

        result = composite.query("test", limit=10, include_trace=True)

        assert result.results == []
        assert result.trace is not None
        assert result.trace.fusion_trace is not None
        assert result.trace.fusion_trace.fused_candidate_count == 0
        assert result.trace.fusion_trace.both_sources_count == 0
        assert result.trace.fusion_trace.selected_count == 0
