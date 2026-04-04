"""Tests for vector index self-healing: orphan prevention, startup mismatch, reconciliation."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.contracts import ProcessResult, build_source_item
from core.models import IndexEntry
from core.processing import ItemProcessor
from core.vector_embed import VectorEmbedder
from core.thread_rebuild import ThreadRebuilder
from core.observability import IntegrationDebugLogger
from providers.embedding.base import EmbeddingProvider
from semantic.base import SemanticPlugin
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider
from storage.vector_index import VectorIndex

try:
    import usearch  # noqa: F401
    HAS_USEARCH = True
except ImportError:
    HAS_USEARCH = False

requires_usearch = pytest.mark.skipif(not HAS_USEARCH, reason="usearch not installed")


class StubEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dims: int = 4, model: str = "test-model") -> None:
        self._dims = dims
        self._model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * self._dims for _ in texts]

    def dimensions(self) -> int:
        return self._dims

    def model_name(self) -> str:
        return self._model


class AlwaysFailPlugin(SemanticPlugin):
    """Plugin whose process_item always raises, but provides source_item_embedding_text."""
    name = "always_fail_with_embedding"

    def process_item(self, source_item):
        raise RuntimeError("LLM connection failed")

    def source_item_embedding_text(self, source_item):
        if len(source_item.content) >= 40:
            return source_item.content
        return None


@requires_usearch
def test_source_vector_embedded_even_when_llm_fails(test_db_url: str, tmp_path: Path) -> None:
    """When process_item raises, the source item vector entry is still embedded into usearch."""
    storage = SQLiteStorageProvider(test_db_url)
    embedding_provider = StubEmbeddingProvider()
    index_path = tmp_path / "test.index"
    vector_index = VectorIndex.create_empty(index_path, dimensions=4, model_name="test-model")

    vector_embedder = VectorEmbedder(storage, embedding_provider, vector_index)
    plugin = AlwaysFailPlugin()
    plugins = {plugin.name: plugin}
    observability = IntegrationDebugLogger(enabled=False)

    thread_rebuilder = ThreadRebuilder(
        storage=storage,
        semantic_plugins=plugins,
        vector_embedder=vector_embedder,
        observability=observability,
        persist_fn=lambda r: None,
        supersede_fn=lambda a, b: None,
    )
    processor = ItemProcessor(
        storage=storage,
        semantic_plugins=plugins,
        default_use_case=plugin.name,
        vector_embedder=vector_embedder,
        thread_rebuilder=thread_rebuilder,
        observability=observability,
        persist_fn=lambda r: None,
        supersede_fn=lambda a, b: None,
        get_item_processing_fn=lambda sid: None,
    )

    source_item = build_source_item(
        source_type="chat_message",
        source_id="fail-embed-test-1",
        content_type="text/plain",
        content="Decision: use item event time for reservation ordering to avoid duplicate holds.",
        metadata=None,
        use_case=plugin.name,
    )
    storage.create_source_item(source_item)

    claimed = storage.claim_next_source_item(worker_id="test", lease_seconds=60, max_attempts=3)
    assert claimed is not None

    processor._process_source_item(claimed, max_attempts=3, worker_id="test")

    # Source item should be marked as failed (LLM error)
    after = storage.get_source_item(claimed.id)
    assert after.processing_status == "pending"  # retryable, not final

    # But the source vector entry should exist in BOTH SQLite and usearch
    sqlite_vector_entries = storage.list_index_entries_by_type("vector")
    assert len(sqlite_vector_entries) == 1

    assert vector_index.entry_count() == 1, (
        "Source vector must be in usearch even when LLM fails"
    )
