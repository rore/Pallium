"""Tests for composite retrieval (lexical + vector) in PalliumService.

Verifies that:
- include_trace=True with CompositeRetrievalProvider shows both lexical and vector stages
- include_trace=False does NOT produce a trace but still fuses results
- Plain lexical provider (no composite) produces only lexical stages in trace
- CompositeRetrievalProvider fuses results from both sources
"""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

from core.models import (
    QueryResultItem,
    QueryTrace,
    RetrievalStageTrace,
    RetrievalTraceHit,
)
from core.service import PalliumService
from retrieval.base import RetrievalQueryResult
from retrieval.composite import CompositeRetrievalProvider
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
    """Build a PalliumService with optional composite retrieval.

    When vector_retrieval is provided, wraps lexical + vector into a
    CompositeRetrievalProvider. Otherwise uses plain lexical.
    """
    storage = SQLiteStorageProvider(database_url=test_db_url)
    lexical = LexicalRetrievalProvider(storage)
    if vector_retrieval is not None:
        retrieval = CompositeRetrievalProvider(
            lexical=lexical,
            vector=vector_retrieval,
        )
    else:
        retrieval = lexical
    return PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins={"demo_agent_memory": DemoAgentMemoryPlugin()},
        default_use_case="demo_agent_memory",
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
    """Create a mock VectorRetrievalProvider that returns a RetrievalQueryResult with trace.

    Respects include_trace: when False, returns trace=None (matching real behavior).
    """
    mock = MagicMock(spec=VectorRetrievalProvider)
    resolved_stage = stage_trace or _make_vector_stage_trace()
    trace_with_stages = QueryTrace(
        query_text="",
        query_tokens=(),
        limit=10,
        filters=None,
        stages=(resolved_stage,),
    )

    def _query_side_effect(*args, **kwargs):
        include_trace = kwargs.get("include_trace", False)
        return RetrievalQueryResult(
            results=[],
            trace=trace_with_stages if include_trace else None,
        )

    mock.query.side_effect = _query_side_effect
    return mock


# ---------------------------------------------------------------------------
# Tests: include_trace=True with CompositeRetrievalProvider
# ---------------------------------------------------------------------------

class TestCompositeTraceIncludesBothStages:
    """When include_trace=True and CompositeRetrievalProvider wraps lexical + vector,
    the trace should include stages from both providers."""

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

    def test_vector_stage_appears_in_trace(self, test_db_url: str) -> None:
        """Vector stage should appear in the composite trace alongside lexical."""
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
        stage_names = [s.stage_name for s in result.trace.stages]
        assert VECTOR_STAGE_NAME in stage_names

    def test_fusion_trace_present_when_vector_active(self, test_db_url: str) -> None:
        """When composite retrieval fuses results, fusion_trace should be on the trace."""
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

        result = service.query("event-driven", limit=5, include_trace=True)

        assert result.trace is not None
        assert result.trace.fusion_trace is not None
        assert result.trace.fusion_trace.stage_name == "rrf_fusion"


# ---------------------------------------------------------------------------
# Tests: include_trace=False should still fuse results but produce no trace
# ---------------------------------------------------------------------------

class TestCompositeWithoutTrace:
    """When include_trace=False, vector retrieval is still invoked for fusion
    but no trace is produced."""

    def test_no_trace_but_vector_still_called(self, test_db_url: str) -> None:
        mock_vector = _mock_vector_retrieval()
        service = _make_service(test_db_url, vector_retrieval=mock_vector)

        result = service.query("test query", limit=5, include_trace=False)

        # Vector is called because composite fuses results (not just debug)
        mock_vector.query.assert_called_once()
        assert result.trace is None


# ---------------------------------------------------------------------------
# Tests: plain lexical (no composite) produces lexical-only trace
# ---------------------------------------------------------------------------

class TestNoVectorRetrieval:
    """When using plain lexical provider (no composite), trace should contain only lexical stages."""

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

    def test_no_fusion_trace_without_vector(self, test_db_url: str) -> None:
        """Without composite retrieval, fusion_trace should be None."""
        service = _make_service(test_db_url, vector_retrieval=None)

        result = service.query("test", limit=5, include_trace=True)

        assert result.trace is not None
        assert result.trace.fusion_trace is None


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

class TestCompositeEdgeCases:
    """Edge cases for composite retrieval trace merging."""

    def test_vector_returns_no_stages(self, test_db_url: str) -> None:
        """If vector provider returns a trace with empty stages, the composite
        still fuses but vector stages are absent from trace."""
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
        """If vector provider returns None trace, the composite still works."""
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
        """Composite works even with no ingested content."""
        mock_vector = _mock_vector_retrieval()
        service = _make_service(test_db_url, vector_retrieval=mock_vector)

        result = service.query("anything", limit=5, include_trace=True)

        assert result.trace is not None
        stage_names = [s.stage_name for s in result.trace.stages]
        assert VECTOR_STAGE_NAME in stage_names
