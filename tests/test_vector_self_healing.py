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

    def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
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


@requires_usearch
def test_vector_index_known_entry_ids(tmp_path: Path) -> None:
    index_path = tmp_path / "ids.index"
    vi = VectorIndex.create_empty(index_path, dimensions=4, model_name="test-model")
    assert vi.known_entry_ids() == frozenset()

    vi.add("entry-a", [0.1, 0.2, 0.3, 0.4])
    vi.add("entry-b", [0.5, 0.6, 0.7, 0.8])
    assert vi.known_entry_ids() == frozenset({"entry-a", "entry-b"})

    vi.remove("entry-a")
    assert vi.known_entry_ids() == frozenset({"entry-b"})


@requires_usearch
def test_reconcile_forward_embeds_missing_entries(test_db_url: str, tmp_path: Path) -> None:
    """Entries in SQLite but not in usearch are embedded by reconciliation."""
    storage = SQLiteStorageProvider(test_db_url)
    embedding_provider = StubEmbeddingProvider()
    index_path = tmp_path / "reconcile.index"
    vector_index = VectorIndex.create_empty(index_path, dimensions=4, model_name="test-model")

    vector_embedder = VectorEmbedder(storage, embedding_provider, vector_index)

    # Create a vector index entry in SQLite only (simulating an orphan)
    from core.indexing import build_index_entry
    orphan_entry = build_index_entry(
        target_kind="source_item",
        target_id="orphan-source-1",
        index_type="vector",
        text_view="Some text that should be embedded",
        text_view_name="source_content.embedding",
    )
    storage.create_index_entry(orphan_entry)

    assert storage.count_index_entries_by_type("vector") == 1
    assert vector_index.entry_count() == 0

    reconciled = vector_embedder.reconcile(batch_size=50)

    assert reconciled == 1
    assert vector_index.entry_count() == 1
    assert orphan_entry.id in vector_index.known_entry_ids()


@requires_usearch
def test_reconcile_reverse_removes_stale_entries(test_db_url: str, tmp_path: Path) -> None:
    """Entries in usearch but not in SQLite are removed by reconciliation."""
    storage = SQLiteStorageProvider(test_db_url)
    embedding_provider = StubEmbeddingProvider()
    index_path = tmp_path / "reconcile.index"
    vector_index = VectorIndex.create_empty(index_path, dimensions=4, model_name="test-model")

    vector_embedder = VectorEmbedder(storage, embedding_provider, vector_index)

    # Add an entry to usearch only (simulating retention deleting the SQLite row)
    vector_index.add("stale-entry-1", [0.1, 0.2, 0.3, 0.4])
    assert vector_index.entry_count() == 1
    assert storage.count_index_entries_by_type("vector") == 0

    reconciled = vector_embedder.reconcile(batch_size=50)

    assert reconciled == 1
    assert vector_index.entry_count() == 0


@requires_usearch
def test_reconcile_noop_when_counts_match(test_db_url: str, tmp_path: Path) -> None:
    """When SQLite and usearch counts match, reconciliation is a no-op."""
    storage = SQLiteStorageProvider(test_db_url)
    embedding_provider = StubEmbeddingProvider()
    index_path = tmp_path / "reconcile.index"
    vector_index = VectorIndex.create_empty(index_path, dimensions=4, model_name="test-model")

    vector_embedder = VectorEmbedder(storage, embedding_provider, vector_index)

    # Both empty — counts match
    reconciled = vector_embedder.reconcile(batch_size=50)
    assert reconciled == 0


@requires_usearch
def test_reconcile_forward_respects_batch_size(test_db_url: str, tmp_path: Path) -> None:
    """Forward reconciliation embeds at most batch_size entries per call."""
    storage = SQLiteStorageProvider(test_db_url)
    embedding_provider = StubEmbeddingProvider()
    index_path = tmp_path / "reconcile.index"
    vector_index = VectorIndex.create_empty(index_path, dimensions=4, model_name="test-model")

    vector_embedder = VectorEmbedder(storage, embedding_provider, vector_index)

    # Create 5 orphan entries in SQLite
    from core.indexing import build_index_entry
    for i in range(5):
        entry = build_index_entry(
            target_kind="source_item",
            target_id=f"batch-source-{i}",
            index_type="vector",
            text_view=f"Text for batch entry {i}",
            text_view_name="source_content.embedding",
        )
        storage.create_index_entry(entry)

    assert storage.count_index_entries_by_type("vector") == 5
    assert vector_index.entry_count() == 0

    # Reconcile with batch_size=2 — should embed exactly 2
    reconciled = vector_embedder.reconcile(batch_size=2)
    assert reconciled == 2
    assert vector_index.entry_count() == 2

    # Second call embeds 2 more
    reconciled = vector_embedder.reconcile(batch_size=2)
    assert reconciled == 2
    assert vector_index.entry_count() == 4

    # Third call embeds the last 1
    reconciled = vector_embedder.reconcile(batch_size=2)
    assert reconciled == 1
    assert vector_index.entry_count() == 5


@requires_usearch
def test_reconcile_noop_when_disabled(test_db_url: str) -> None:
    """Reconciliation returns 0 when embedding_provider or vector_index is None."""
    storage = SQLiteStorageProvider(test_db_url)
    embedder_no_provider = VectorEmbedder(storage, None, None)
    assert embedder_no_provider.reconcile(batch_size=50) == 0


@requires_usearch
def test_service_reconcile_vector_index_delegates(test_db_url: str, tmp_path: Path) -> None:
    """PalliumService.reconcile_vector_index() delegates to VectorEmbedder.reconcile()."""
    from core.service import PalliumService
    from retrieval.lexical import LexicalRetrievalProvider

    storage = SQLiteStorageProvider(test_db_url)
    embedding_provider = StubEmbeddingProvider()
    index_path = tmp_path / "svc.index"
    vector_index = VectorIndex.create_empty(index_path, dimensions=4, model_name="test-model")
    retrieval = LexicalRetrievalProvider(storage)
    plugins = {"demo_agent_memory": DemoAgentMemoryPlugin()}

    service = PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
        embedding_provider=embedding_provider,
        vector_index=vector_index,
    )

    # Both empty — should return 0
    result = service.reconcile_vector_index()
    assert result == 0


def test_worker_loop_calls_reconciliation_when_idle(test_db_url: str, monkeypatch) -> None:
    """Worker calls reconcile_vector_index when no source items or thread rebuilds pending."""
    from app.worker import run_worker
    from app.config import AppConfig
    from storage.vector_index import VectorIndexConfig

    reconcile_calls = []

    class TrackingService:
        def __init__(self, real_service):
            self._real = real_service

        def __getattr__(self, name):
            if name == "reconcile_vector_index":
                def tracked():
                    reconcile_calls.append(1)
                    return 0
                return tracked
            return getattr(self._real, name)

    from core.service import PalliumService
    from retrieval.lexical import LexicalRetrievalProvider

    storage = SQLiteStorageProvider(test_db_url)
    retrieval = LexicalRetrievalProvider(storage)
    plugins = {"demo_agent_memory": DemoAgentMemoryPlugin()}
    real_service = PalliumService(
        storage=storage,
        retrieval=retrieval,
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
    )

    tracking_service = TrackingService(real_service)

    monkeypatch.setattr(
        "app.worker.build_service",
        lambda config: tracking_service,
    )

    run_worker(["--once"], config=AppConfig(
        storage_backend="sqlite",
        sqlite_url=test_db_url,
        default_use_case="demo_agent_memory",
        vector_index=VectorIndexConfig(enabled=False),
    ))

    assert len(reconcile_calls) >= 1, "Worker should call reconcile_vector_index when idle"
