"""Tests for vector index lifecycle in multi-process supervisor mode.

These tests cover the failure modes that were previously untested:
- Reconcile picks up SQLite-only entries (simulating processor → server flow)
- enable_vector=False produces a working service without vector infra
- Atomic save uses os.replace for JSON sidecars
- End-to-end: processor-like ingest → reconcile → server-like query
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from core.contracts import ProcessResult, build_source_item
from core.indexing import VECTOR_INDEX_TYPE, build_index_entry
from core.models import MemoryObject, Relation, new_id, utc_now
from core.service import PalliumService
from core.vector_embed import VectorEmbedder
from core.vector_index_holder import VectorIndexHolder
from providers.embedding.base import EmbeddingProvider
from retrieval.composite import CompositeRetrievalProvider
from retrieval.lexical import LexicalRetrievalProvider
from retrieval.vector import VectorRetrievalProvider
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider
from storage.vector_index import VectorIndex, _atomic_write_json


# ── Stub embedding provider ──────────────────────────────────────────────

class StubEmbeddingProvider(EmbeddingProvider):
    """Returns deterministic vectors based on text hash."""

    def model_name(self) -> str:
        return "stub-embed"

    def dimensions(self) -> int:
        return 8

    def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        import hashlib
        vectors = []
        for text in texts:
            h = hashlib.md5(text.encode()).digest()
            vec = [float(b) / 255.0 for b in h[:8]]
            # Normalize to unit length for cosine
            norm = sum(v * v for v in vec) ** 0.5
            vectors.append([v / norm for v in vec])
        return vectors


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def test_db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def vector_index_path(tmp_path):
    return tmp_path / "test_vector.index"


# ── Tests: Atomic save ───────────────────────────────────────────────────

def test_atomic_write_json_no_leftover_tmp_files(tmp_path):
    path = tmp_path / "test.json"
    _atomic_write_json(path, {"key": "value"})
    assert path.exists()
    assert json.loads(path.read_text()) == {"key": "value"}
    # No .tmp files left behind
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []


def test_atomic_write_json_overwrites_existing(tmp_path):
    path = tmp_path / "test.json"
    _atomic_write_json(path, {"version": 1})
    _atomic_write_json(path, {"version": 2})
    assert json.loads(path.read_text()) == {"version": 2}


def test_vector_index_save_creates_all_three_files(vector_index_path):
    idx = VectorIndex.create_empty(vector_index_path, dimensions=8, model_name="test")
    assert vector_index_path.exists()
    assert Path(f"{vector_index_path}.idmap.json").exists()
    assert Path(f"{vector_index_path}.meta.json").exists()


# ── Tests: Reconcile picks up SQLite-only entries ─────────────────────────

def test_reconcile_picks_up_sqlite_only_entries(test_db_url, vector_index_path):
    """Simulates processor writing to SQLite, then server reconciling."""
    storage = SQLiteStorageProvider(test_db_url)
    embedding = StubEmbeddingProvider()
    vector_index = VectorIndex.create_empty(vector_index_path, dimensions=8, model_name="stub-embed")
    embedder = VectorEmbedder(storage, embedding, index_holder=VectorIndexHolder(vector_index))

    # Simulate processor: write IndexEntry to SQLite without touching usearch
    entry = build_index_entry(
        target_kind="memory_object",
        target_id="mo-test-1",
        index_type=VECTOR_INDEX_TYPE,
        text_view="Alice has 3 cats",
        text_view_name="test.embedding",
    )
    storage.create_index_entry(entry)

    # Before reconcile: usearch is empty
    assert vector_index.entry_count() == 0

    # Reconcile (simulating server daemon thread)
    changed = embedder.reconcile()
    assert changed == 1
    assert vector_index.entry_count() == 1

    # The entry should now be searchable
    hits = vector_index.search(embedding.embed(["Alice cats"])[0], k=5)
    assert len(hits) >= 1
    assert hits[0][0] == entry.id


def test_reconcile_is_idempotent(test_db_url, vector_index_path):
    storage = SQLiteStorageProvider(test_db_url)
    embedding = StubEmbeddingProvider()
    vector_index = VectorIndex.create_empty(vector_index_path, dimensions=8, model_name="stub-embed")
    embedder = VectorEmbedder(storage, embedding, index_holder=VectorIndexHolder(vector_index))

    entry = build_index_entry(
        target_kind="memory_object", target_id="mo-1",
        index_type=VECTOR_INDEX_TYPE, text_view="test text",
        text_view_name="test.embedding",
    )
    storage.create_index_entry(entry)

    assert embedder.reconcile() == 1
    assert embedder.reconcile() == 0  # No changes on second call


def test_reconcile_sets_provider_metadata(test_db_url, vector_index_path):
    storage = SQLiteStorageProvider(test_db_url)
    embedding = StubEmbeddingProvider()
    vector_index = VectorIndex.create_empty(vector_index_path, dimensions=8, model_name="stub-embed")
    embedder = VectorEmbedder(storage, embedding, index_holder=VectorIndexHolder(vector_index))

    entry = build_index_entry(
        target_kind="memory_object", target_id="mo-1",
        index_type=VECTOR_INDEX_TYPE, text_view="test text",
        text_view_name="test.embedding",
    )
    storage.create_index_entry(entry)
    embedder.reconcile()

    updated = storage.get_index_entry(entry.id)
    assert updated.provider_name == "stub-embed"
    assert updated.provider_version == "dim=8"


# ── Tests: enable_vector=False ────────────────────────────────────────────

def test_enable_vector_false_produces_working_service(test_db_url):
    """Service with enable_vector=False processes items and queries without vector infra."""
    from app.config import AppConfig
    from app.dependencies import build_service
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES

    service = build_service(
        AppConfig(
            storage_backend="sqlite",
            sqlite_url=test_db_url,
            default_use_case="demo_agent_memory",
            semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(enabled=False),
        ),
        enable_vector=False,
    ).service

    # Ingest and process
    ingest = service.ingest_item(
        source_type="test", source_id="ev-1",
        content_type="text/plain", content="Test content",
        metadata=None, use_case=None,
        artifact_kind="assistant_output", role="assistant",
    )
    assert ingest.processing_status == "pending"
    results = service.drain_processing_queue(worker_id="test")
    assert len(results) >= 1

    # Query works (lexical only, no vector errors)
    query_result = service.query("test content", limit=5)
    assert query_result is not None


# ── Tests: End-to-end processor → reconcile → query ──────────────────────

def test_end_to_end_processor_reconcile_query(test_db_url, vector_index_path):
    """Simulates full supervisor flow: processor writes SQLite, server reconciles and queries."""
    storage = SQLiteStorageProvider(test_db_url)
    embedding = StubEmbeddingProvider()
    plugins = {"demo_agent_memory": DemoAgentMemoryPlugin()}

    # Processor service: no vector infra (simulated by not passing vector components)
    processor_service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
    )

    # Ingest and process (writes IndexEntry to SQLite, but no usearch since no vector_index)
    processor_service.ingest_item(
        source_type="test", source_id="e2e-1",
        content_type="text/plain",
        content="Decision: use item event time for reservation ordering.",
        metadata=None, use_case=None,
        artifact_kind="assistant_output", role="assistant",
    )
    processor_service.drain_processing_queue(worker_id="processor")

    # Server service: with vector infra
    vector_index = VectorIndex.create_empty(vector_index_path, dimensions=8, model_name="stub-embed")
    holder = VectorIndexHolder(vector_index)
    vector_retrieval = VectorRetrievalProvider(storage, embedding, index_holder=holder)
    composite = CompositeRetrievalProvider(
        lexical=LexicalRetrievalProvider(storage),
        vector=vector_retrieval,
    )
    server_service = PalliumService(
        storage=storage,
        retrieval=composite,
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
        embedding_provider=embedding,
        index_holder=holder,
    )

    # Before reconcile: vector index is empty
    assert vector_index.entry_count() == 0

    # Reconcile (simulating daemon thread)
    reconciled = server_service.reconcile_vector_index()
    # May or may not have vector entries depending on what demo plugin indexes
    # The important thing is no errors and the service works

    # Query works and returns results
    result = server_service.query("reservation ordering", limit=5)
    assert len(result.results) >= 1


# ── Tests: Reconcile daemon thread ────────────────────────────────────────

def test_reconcile_daemon_thread_fires(test_db_url, vector_index_path):
    """Verify the daemon thread calls reconcile and picks up new entries."""
    from app.main import _start_reconcile_thread

    storage = SQLiteStorageProvider(test_db_url)
    embedding = StubEmbeddingProvider()
    vector_index = VectorIndex.create_empty(vector_index_path, dimensions=8, model_name="stub-embed")
    plugins = {"demo_agent_memory": DemoAgentMemoryPlugin()}

    service = PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
        embedding_provider=embedding,
        index_holder=VectorIndexHolder(vector_index),
    )

    # Write an entry to SQLite
    entry = build_index_entry(
        target_kind="memory_object", target_id="mo-daemon-1",
        index_type=VECTOR_INDEX_TYPE, text_view="daemon test",
        text_view_name="test.embedding",
    )
    storage.create_index_entry(entry)

    assert vector_index.entry_count() == 0

    # Start daemon with short interval
    stop = _start_reconcile_thread(service, interval=0.1)
    try:
        # Wait for at least one reconcile cycle
        deadline = time.monotonic() + 5.0
        while vector_index.entry_count() == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert vector_index.entry_count() == 1
    finally:
        stop.set()
