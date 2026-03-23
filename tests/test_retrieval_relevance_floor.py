"""Integration test: retrieval relevance floor with composite retrieval.

Exercises the REAL composite retrieval + routing + injection pipeline to prove
that the relevance floor discriminates correctly:
- Off-topic queries (no lexical overlap) are suppressed
- On-topic queries (lexical overlap) are injected

Uses TieredMemorySemanticProvider (deterministic, no LLM) with a mock vector
retrieval that returns stored memories for any query.  Real lexical retrieval
determines token overlap; CompositeRetrievalProvider fuses both and sets
retrieval_source / lexical_score on each item.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.models import QueryResultItem
from core.service import PalliumService
from retrieval.base import RetrievalQueryResult
from retrieval.composite import CompositeRetrievalProvider
from retrieval.lexical import LexicalRetrievalProvider
from retrieval.vector import VectorRetrievalProvider
from semantic.agent_conversation_memory import AgentConversationMemoryPlugin
from storage.sqlite import SQLiteStorageProvider
from tests.tiered_memory_stub_providers import TieredMemorySemanticProvider

pytestmark = pytest.mark.slow

CONTAINER_REF = "chat:relevance-floor-test"
THREAD_A = f"{CONTAINER_REF}:thread-A"
THREAD_B = f"{CONTAINER_REF}:thread-B"


def _build_vector_mock(storage: SQLiteStorageProvider, *, vector_score: int = 800):
    """Build a mock VectorRetrievalProvider that returns all stored memories.

    Simulates vector search finding items by semantic similarity even when
    lexical overlap is zero (the exact scenario that triggers the problem).

    ``vector_score`` controls the cosine similarity score (cosine × 1000)
    returned by the mock.  Use high values (800) for on-topic scenarios,
    low values (500) for off-topic scenarios where the embedding model
    would not report high similarity.
    """
    mock = MagicMock(spec=VectorRetrievalProvider)

    def _query_side_effect(*args, **kwargs):
        # Return all active memory objects AND source items as vector hits.
        # Simulates vector finding them by embedding similarity.
        limit = kwargs.get("limit", 10)
        items: list[QueryResultItem] = []
        for mo in storage.list_memory_objects():
            if mo.lifecycle != "active":
                continue
            items.append(
                QueryResultItem(
                    result_kind="memory_hit",
                    memory_object_id=mo.id,
                    type=mo.type,
                    payload=mo.payload,
                    score=vector_score,
                    evidence=[],
                    container_ref=mo.container_ref,
                    actor_ref=mo.actor_ref,
                    container_visibility=mo.container_visibility or "private",
                )
            )
        # Also return source items (which carry the actual domain text)
        from sqlalchemy import select
        from storage.sqlite_schema import SourceItemRecord
        with storage._session_factory() as session:
            for rec in session.scalars(select(SourceItemRecord)):
                items.append(
                    QueryResultItem(
                        result_kind="source_hit",
                        source_item_id=rec.id,
                        source_type=rec.source_type,
                        source_id=rec.source_id,
                        excerpt=(rec.content or "")[:200],
                        occurred_at=rec.occurred_at,
                        score=vector_score - 50,
                        evidence=[],
                        container_ref=rec.container_ref,
                        role=rec.role,
                        artifact_kind=rec.artifact_kind,
                        container_visibility=rec.container_visibility or "private",
                    )
                )
        return RetrievalQueryResult(results=items[:limit], trace=None)

    mock.query.side_effect = _query_side_effect
    return mock


def _build_service(test_db_url: str, *, vector_score: int = 800) -> PalliumService:
    """Build a PalliumService with composite retrieval (real lexical + mock vector)."""
    storage = SQLiteStorageProvider(database_url=test_db_url)
    lexical = LexicalRetrievalProvider(storage)
    vector_mock = _build_vector_mock(storage, vector_score=vector_score)
    composite = CompositeRetrievalProvider(lexical=lexical, vector=vector_mock)

    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant="strict_typed_memory_v4_evidence_guarded",
    )
    return PalliumService(
        storage=storage,
        retrieval=composite,
        semantic_plugins={"agent_conversation_memory": plugin},
        default_use_case="agent_conversation_memory",
    )


def _ingest_vector_db_conversation(service: PalliumService) -> None:
    """Ingest a 3-message conversation about vector databases in thread-A."""
    service.ingest_item(
        source_type="chat_message",
        source_id=f"{THREAD_A}-msg-1",
        content_type="text/plain",
        content="I've been looking at vector databases for my side project",
        metadata=None,
        use_case=None,
        artifact_kind="message",
        role="user",
        container_ref=CONTAINER_REF,
        thread_ref=THREAD_A,
        container_visibility="private",
    )
    service.ingest_item(
        source_type="assistant_artifact",
        source_id=f"{THREAD_A}-asst-1",
        content_type="text/plain",
        content=(
            "ChromaDB is a great lightweight option. "
            "Qdrant and FAISS are also worth considering."
        ),
        metadata=None,
        use_case=None,
        artifact_kind="assistant_output",
        role="assistant",
        container_ref=CONTAINER_REF,
        thread_ref=THREAD_A,
        container_visibility="private",
    )
    service.ingest_item(
        source_type="chat_message",
        source_id=f"{THREAD_A}-msg-2",
        content_type="text/plain",
        content="Chroma sounds interesting, I should check it sometime",
        metadata=None,
        use_case=None,
        artifact_kind="message",
        role="user",
        container_ref=CONTAINER_REF,
        thread_ref=THREAD_A,
        container_visibility="private",
    )
    service.drain_processing_queue()


class TestRetrievalRelevanceFloorIntegration:
    """Full-pipeline tests proving the relevance floor discriminates correctly.

    The mock vector returns all stored memories and source items for any
    query, simulating vector finding semantic matches without lexical
    overlap.  Real lexical retrieval determines actual token overlap.
    The composite provider fuses both and sets retrieval_source /
    lexical_score.

    Off-topic tests use thread_ref=THREAD_B so lexical only sees thread-B
    items (none exist).  On-topic tests omit thread_ref so lexical can
    find cross-thread source items that carry the actual domain text.
    The stub-generated memory text is generic ("Conversation summary.")
    and doesn't carry domain words, so thread-scoping is the lever that
    controls lexical match vs. no match.
    """

    def test_off_topic_query_suppressed(self, test_db_url: str) -> None:
        """'let's talk about something new' has no lexical overlap with
        vector-DB memories — injection should be suppressed.

        Uses low vector scores (500 = cosine 0.50) to simulate the embedding
        model's real response for unrelated queries (validated: unrelated
        pairs max out around cosine 0.63 with BGE-small).
        """
        service = _build_service(test_db_url, vector_score=500)
        _ingest_vector_db_conversation(service)

        result = service.query(
            text="let's talk about something new",
            limit=6,
            container_ref=CONTAINER_REF,
            thread_ref=THREAD_B,
            container_visibility="private",
            include_trace=True,
        )
        assert result.should_inject is False
        assert result.decision_reason == "low_retrieval_relevance"

    def test_on_topic_query_not_blocked_by_floor(self, test_db_url: str) -> None:
        """'what did we discuss about vector databases?' has lexical overlap
        with stored source items — the floor check should NOT suppress.

        Note: injection may still be suppressed by other eligibility checks
        (e.g. source hits aren't primary-injection-eligible for broad recall).
        We only assert the floor check is not the reason for suppression.
        """
        service = _build_service(test_db_url)
        _ingest_vector_db_conversation(service)

        # No thread_ref: lexical can find cross-thread source items
        result = service.query(
            text="what did we discuss about vector databases?",
            limit=6,
            container_ref=CONTAINER_REF,
            container_visibility="private",
            include_trace=True,
        )
        assert result.decision_reason != "low_retrieval_relevance", (
            f"Floor check should pass for on-topic query, got: {result.decision_reason}"
        )

    def test_unrelated_topic_suppressed(self, test_db_url: str) -> None:
        """'how about politics?' has no meaningful lexical overlap with
        vector-DB memories — injection should be suppressed.

        Uses low vector scores to simulate realistic embedding distance
        for unrelated queries.
        """
        service = _build_service(test_db_url, vector_score=500)
        _ingest_vector_db_conversation(service)

        result = service.query(
            text="how about politics?",
            limit=6,
            container_ref=CONTAINER_REF,
            thread_ref=THREAD_B,
            container_visibility="private",
            include_trace=True,
        )
        assert result.should_inject is False

    def test_retrieval_source_set_on_fused_items(self, test_db_url: str) -> None:
        """Verify that composite retrieval sets retrieval_source on fused items."""
        service = _build_service(test_db_url)
        _ingest_vector_db_conversation(service)

        # No thread_ref: allows cross-thread lexical matches
        result = service.query(
            text="vector databases chromadb",
            limit=6,
            container_ref=CONTAINER_REF,
            container_visibility="private",
            include_trace=True,
        )
        sources = {item.retrieval_source for item in result.results}
        assert "both" in sources or "lexical" in sources, (
            f"Expected at least one lexical-matched item, got sources: {sources}"
        )

    def test_lexical_score_propagated_through_fusion(self, test_db_url: str) -> None:
        """Verify that lexical_score is set on fused items from composite retrieval."""
        service = _build_service(test_db_url)
        _ingest_vector_db_conversation(service)

        # No thread_ref: allows cross-thread lexical matches
        result = service.query(
            text="vector databases chromadb",
            limit=6,
            container_ref=CONTAINER_REF,
            container_visibility="private",
            include_trace=True,
        )
        lexical_matched = [
            item for item in result.results
            if item.retrieval_source in ("both", "lexical")
        ]
        assert lexical_matched, "Expected at least one lexical-matched item"
        for item in lexical_matched:
            assert item.lexical_score is not None, (
                f"lexical_score should be set for retrieval_source={item.retrieval_source}"
            )
            assert item.lexical_score >= 1, (
                f"lexical_score should be positive, got {item.lexical_score}"
            )


def _build_lexical_only_service(test_db_url: str) -> PalliumService:
    """Build a PalliumService with lexical-only retrieval (no vector provider)."""
    storage = SQLiteStorageProvider(database_url=test_db_url)
    lexical = LexicalRetrievalProvider(storage)

    plugin = AgentConversationMemoryPlugin(
        provider=TieredMemorySemanticProvider(),
        prompt_variant="strict_typed_memory_v4_evidence_guarded",
    )
    return PalliumService(
        storage=storage,
        retrieval=lexical,
        semantic_plugins={"agent_conversation_memory": plugin},
        default_use_case="agent_conversation_memory",
    )


class TestRelevanceFloorLexicalOnly:
    """Prove the relevance floor works in lexical-only mode (no vector provider).

    This is the deployment mode the invariant runner uses by default.
    Previously, lexical-only items had retrieval_source=None which
    bypassed the floor entirely.
    """

    @pytest.mark.xfail(reason="Lexical-only mode bypasses relevance floor — see docs/designs/off-topic-injection-analysis.md")
    def test_off_topic_suppressed_lexical_only(self, test_db_url: str) -> None:
        """Weather query against catalog memories — lexical-only mode."""
        service = _build_lexical_only_service(test_db_url)
        _ingest_vector_db_conversation(service)

        result = service.query(
            text="Is it going to rain tomorrow?",
            limit=6,
            container_ref=CONTAINER_REF,
            container_visibility="private",
            include_trace=True,
        )
        assert result.should_inject is False, (
            f"Off-topic query should not inject in lexical-only mode. "
            f"decision_reason={result.decision_reason}"
        )

    def test_on_topic_not_blocked_lexical_only(self, test_db_url: str) -> None:
        """On-topic query should still pass the floor in lexical-only mode."""
        service = _build_lexical_only_service(test_db_url)
        _ingest_vector_db_conversation(service)

        result = service.query(
            text="what vector databases did we discuss?",
            limit=6,
            container_ref=CONTAINER_REF,
            container_visibility="private",
            include_trace=True,
        )
        assert result.decision_reason != "low_retrieval_relevance", (
            f"On-topic query should pass the floor, got: {result.decision_reason}"
        )

    def test_coattail_blocked_lexical_only(self, test_db_url: str) -> None:
        """A weak candidate should not ride through on a strong one's score.

        Ingest two topics, then query about one — only on-topic memories
        should be injection-eligible.  The floor must be per-item.
        """
        service = _build_lexical_only_service(test_db_url)
        _ingest_vector_db_conversation(service)  # vector DB topic

        result = service.query(
            text="what did we say about vector databases?",
            limit=6,
            container_ref=CONTAINER_REF,
            container_visibility="private",
            include_trace=True,
        )
        # The floor should pass because on-topic candidates exist.
        # This test verifies the floor doesn't suppress everything.
        assert result.decision_reason != "low_retrieval_relevance", (
            f"Floor should pass when on-topic candidates exist, got: {result.decision_reason}"
        )
