"""Tests for vector retrieval debug query exposure in PalliumService.

Verifies that:
- include_trace=True with vector_retrieval configured appends vector stage(s) to trace
- include_trace=False does NOT trigger vector retrieval
- vector_retrieval=None produces only lexical stage in trace
- Non-debug queries with vector_retrieval configured return lexical-only results
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from unittest.mock import MagicMock, call, PropertyMock

from core.models import (
    QueryFilters,
    QueryResultItem,
    QueryTrace,
    RetrievalStageTrace,
    RetrievalTraceHit,
)
from core.service import PalliumService
from retrieval.base import RetrievalQueryResult
from retrieval.lexical import LexicalRetrievalProvider
from retrieval.vector import VectorRetrievalProvider, VECTOR_STAGE_NAME
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(
    test_db_url: str,
    *,
    vector_retrieval: VectorRetrievalProvider | None = None,
) -> PalliumService:
    storage = SQLiteStorageProvider(database_url=test_db_url)
    retrieval = LexicalRetrievalProvider(storage)
    return PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins={"demo_agent_memory": DemoAgentMemoryPlugin()},
        default_use_case="demo_agent_memory",
        vector_retrieval=vector_retrieval,
    )


def _make_vector_stage_trace(
    stage_name: str = VECTOR_STAGE_NAME,
    candidate_hits_considered: int = 1,
) -> RetrievalStageTrace:
    return RetrievalStageTrace(
        stage_name=stage_name,
        candidate_hits_considered=candidate_hits_considered,
        candidate_hits=(
            RetrievalTraceHit(
                target_kind="memory_object",
                target_id="mo-vec-1",
                index_entry_id="idx-vec-1",
                index_type="vector",
                text_view_name="default",
                score=850,
                matched_tokens=(),
                cosine_similarity=0.85,
            ),
        ),
        selected_hits=(
            RetrievalTraceHit(
                target_kind="memory_object",
                target_id="mo-vec-1",
                index_entry_id="idx-vec-1",
                index_type="vector",
                text_view_name="default",
                score=850,
                matched_tokens=(),
                cosine_similarity=0.85,
            ),
        ),
        candidate_hits_before_visibility=1,
        candidate_hits_after_visibility=1,
    )


def _mock_vector_retrieval(stage_trace: RetrievalStageTrace | None = None) -> MagicMock:
    """Create a mock VectorRetrievalProvider that returns a RetrievalQueryResult with trace."""
    mock = MagicMock(spec=VectorRetrievalProvider)
    resolved_stage = stage_trace or _make_vector_stage_trace()
    trace = QueryTrace(
        query_text="",
        query_tokens=(),
        limit=10,
        filters=None,
        stages=(resolved_stage,),
    )
    mock.query.return_value = RetrievalQueryResult(
        results=[],
        trace=trace,
    )
    return mock


# ---------------------------------------------------------------------------
# Tests: include_trace=True with vector_retrieval present
# ---------------------------------------------------------------------------

class TestVectorDebugTraceAppended:
    """When include_trace=True and vector_retrieval is configured, the vector
    stage should be appended to the existing trace stages."""

    def test_trace_includes_vector_stage(self, test_db_url: str) -> None:
        mock_vector = _mock_vector_retrieval()
        service = _make_service(test_db_url, vector_retrieval=mock_vector)

        # Ingest an item so lexical retrieval has something to work with
        service.ingest_item(
            source_type="note",
            source_id="note-1",
            content_type="text/plain",
            content="Decision: use event-driven architecture for notifications.",
            metadata=None,
            use_case=None,
            artifact_kind="assistant_output",
            role="assistant",
        )
        service.drain_processing_queue()

        result = service.query("event-driven", limit=5, include_trace=True)

        assert result.trace is not None
        stage_names = [s.stage_name for s in result.trace.stages]
        assert VECTOR_STAGE_NAME in stage_names, f"Expected '{VECTOR_STAGE_NAME}' in stages: {stage_names}"
        # Lexical stage(s) should also be present
        assert len(result.trace.stages) >= 2

    def test_vector_retrieval_called_with_correct_args(self, test_db_url: str) -> None:
        mock_vector = _mock_vector_retrieval()
        service = _make_service(test_db_url, vector_retrieval=mock_vector)

        service.query("test query", limit=5, include_trace=True)

        mock_vector.query.assert_called_once()
        call_kwargs = mock_vector.query.call_args
        assert call_kwargs.kwargs.get("include_trace") is True or call_kwargs[1].get("include_trace") is True

    def test_vector_stage_appended_after_lexical(self, test_db_url: str) -> None:
        """Vector stage should come after existing stages, not replace them."""
        mock_vector = _mock_vector_retrieval()
        service = _make_service(test_db_url, vector_retrieval=mock_vector)

        service.ingest_item(
            source_type="note",
            source_id="note-1",
            content_type="text/plain",
            content="Decision: use event-driven architecture.",
            metadata=None,
            use_case=None,
        )
        service.drain_processing_queue()

        result = service.query("event-driven", limit=5, include_trace=True)

        assert result.trace is not None
        # Last stage should be the vector stage
        assert result.trace.stages[-1].stage_name == VECTOR_STAGE_NAME

    def test_results_are_lexical_only(self, test_db_url: str) -> None:
        """Even with vector retrieval in debug trace, the result set should
        come from lexical retrieval only -- vector results are NOT merged."""
        mock_vector = _mock_vector_retrieval()
        service = _make_service(test_db_url, vector_retrieval=mock_vector)

        service.ingest_item(
            source_type="note",
            source_id="note-1",
            content_type="text/plain",
            content="Decision: use event-driven architecture for notifications.",
            metadata=None,
            use_case=None,
            artifact_kind="assistant_output",
            role="assistant",
        )
        service.drain_processing_queue()

        result_with_vector = service.query("event-driven", limit=5, include_trace=True)
        # Rebuild service without vector to get baseline lexical results
        service_no_vector = _make_service(test_db_url, vector_retrieval=None)
        result_without_vector = service_no_vector.query("event-driven", limit=5, include_trace=True)

        # Result sets should be identical (same items, same scores)
        assert len(result_with_vector.results) == len(result_without_vector.results)
        with_ids = sorted(
            (getattr(r, "memory_object_id", None) or getattr(r, "source_item_id", None))
            for r in result_with_vector.results
        )
        without_ids = sorted(
            (getattr(r, "memory_object_id", None) or getattr(r, "source_item_id", None))
            for r in result_without_vector.results
        )
        assert with_ids == without_ids


# ---------------------------------------------------------------------------
# Tests: include_trace=False should NOT call vector retrieval
# ---------------------------------------------------------------------------

class TestVectorNotCalledWithoutTrace:
    """When include_trace=False, vector retrieval should not be invoked."""

    def test_vector_not_called_when_no_trace(self, test_db_url: str) -> None:
        mock_vector = _mock_vector_retrieval()
        service = _make_service(test_db_url, vector_retrieval=mock_vector)

        result = service.query("test query", limit=5, include_trace=False)

        mock_vector.query.assert_not_called()
        assert result.trace is None


# ---------------------------------------------------------------------------
# Tests: vector_retrieval=None should produce lexical-only trace
# ---------------------------------------------------------------------------

class TestNoVectorRetrieval:
    """When vector_retrieval is None, trace should contain only lexical stages."""

    def test_trace_has_only_lexical_stages(self, test_db_url: str) -> None:
        service = _make_service(test_db_url, vector_retrieval=None)

        service.ingest_item(
            source_type="note",
            source_id="note-1",
            content_type="text/plain",
            content="Decision: use event-driven architecture.",
            metadata=None,
            use_case=None,
        )
        service.drain_processing_queue()

        result = service.query("event-driven", limit=5, include_trace=True)

        assert result.trace is not None
        stage_names = [s.stage_name for s in result.trace.stages]
        assert VECTOR_STAGE_NAME not in stage_names


# ---------------------------------------------------------------------------
# Tests: non-debug path (include_trace=False) with vector_retrieval configured
# ---------------------------------------------------------------------------

class TestNonDebugPathUnchanged:
    """Non-debug queries with vector_retrieval configured should return the
    same results as without it -- lexical only, no vector involvement."""

    def test_non_debug_result_unchanged(self, test_db_url: str) -> None:
        mock_vector = _mock_vector_retrieval()
        service = _make_service(test_db_url, vector_retrieval=mock_vector)

        service.ingest_item(
            source_type="note",
            source_id="note-1",
            content_type="text/plain",
            content="Decision: use event-driven architecture for notifications.",
            metadata=None,
            use_case=None,
            artifact_kind="assistant_output",
            role="assistant",
        )
        service.drain_processing_queue()

        result = service.query("event-driven", limit=5, include_trace=False)

        # Vector retrieval should not have been called at all
        mock_vector.query.assert_not_called()

        # Results should still contain lexical hits
        assert result.trace is None
        assert result.should_inject is False

    def test_non_debug_results_match_no_vector_service(self, test_db_url: str) -> None:
        mock_vector = _mock_vector_retrieval()
        service_with = _make_service(test_db_url, vector_retrieval=mock_vector)
        service_without = _make_service(test_db_url, vector_retrieval=None)

        service_with.ingest_item(
            source_type="note",
            source_id="note-1",
            content_type="text/plain",
            content="Decision: use event-driven architecture for notifications.",
            metadata=None,
            use_case=None,
            artifact_kind="assistant_output",
            role="assistant",
        )
        service_with.drain_processing_queue()

        result_with = service_with.query("event-driven", limit=5, include_trace=False)
        result_without = service_without.query("event-driven", limit=5, include_trace=False)

        assert len(result_with.results) == len(result_without.results)


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

class TestVectorDebugEdgeCases:
    """Edge cases for vector debug trace merging."""

    def test_vector_returns_no_stages(self, test_db_url: str) -> None:
        """If vector provider returns a trace with empty stages, no vector
        stage is appended."""
        mock_vector = MagicMock(spec=VectorRetrievalProvider)
        mock_vector.query.return_value = RetrievalQueryResult(
            results=[],
            trace=QueryTrace(
                query_text="",
                query_tokens=(),
                limit=10,
                filters=None,
                stages=(),  # Empty stages
            ),
        )
        service = _make_service(test_db_url, vector_retrieval=mock_vector)

        result = service.query("test", limit=5, include_trace=True)

        assert result.trace is not None
        stage_names = [s.stage_name for s in result.trace.stages]
        assert VECTOR_STAGE_NAME not in stage_names

    def test_vector_returns_none_trace(self, test_db_url: str) -> None:
        """If vector provider returns None trace, no vector stage is appended."""
        mock_vector = MagicMock(spec=VectorRetrievalProvider)
        mock_vector.query.return_value = RetrievalQueryResult(
            results=[],
            trace=None,
        )
        service = _make_service(test_db_url, vector_retrieval=mock_vector)

        result = service.query("test", limit=5, include_trace=True)

        assert result.trace is not None
        stage_names = [s.stage_name for s in result.trace.stages]
        assert VECTOR_STAGE_NAME not in stage_names

    def test_empty_query_no_ingest(self, test_db_url: str) -> None:
        """Debug trace works even with no ingested content."""
        mock_vector = _mock_vector_retrieval()
        service = _make_service(test_db_url, vector_retrieval=mock_vector)

        result = service.query("anything", limit=5, include_trace=True)

        assert result.trace is not None
        stage_names = [s.stage_name for s in result.trace.stages]
        assert VECTOR_STAGE_NAME in stage_names
