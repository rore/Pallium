"""Tests for core/vector_rebuild.py recompute helpers and VectorIndex schema version."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.models import IndexEntry, MemoryObject, SourceItem
from core.vector_rebuild import _recompute_embedding_text, _recompute_fact_embedding_text


try:
    import usearch  # noqa: F401
    HAS_USEARCH = True
except ImportError:
    HAS_USEARCH = False


def _make_memory_object(*, type: str = "decision", payload: dict | None = None, id: str = "mem-1") -> MemoryObject:
    return MemoryObject(
        type=type,
        schema_id="test",
        schema_version="1",
        payload=payload or {"decision": "Use PostgreSQL for production", "rationale": "Better concurrency support"},
        id=id,
    )


def _make_source_item(*, content: str = "What database should we use for our production system?", id: str = "src-1") -> SourceItem:
    return SourceItem(
        source_type="test",
        source_id="test-source-1",
        content_type="text/plain",
        content=content,
        artifact_kind="message",
        id=id,
    )


def _make_index_entry(
    *,
    target_kind: str = "memory_object",
    target_id: str = "mem-1",
    text_view: str = "old text view",
    text_view_name: str = "default",
    id: str = "entry-1",
) -> IndexEntry:
    return IndexEntry(
        target_kind=target_kind,
        target_id=target_id,
        index_type="vector",
        text_view=text_view,
        text_view_name=text_view_name,
        id=id,
    )


def _make_mock_storage(memory_objects=None, source_items=None):
    """Build a mock storage provider."""
    storage = MagicMock()
    mem_map = {mo.id: mo for mo in (memory_objects or [])}
    src_map = {si.id: si for si in (source_items or [])}

    def _get_memory_object(mid):
        if mid in mem_map:
            return mem_map[mid]
        raise KeyError(mid)

    def _get_source_item(sid):
        if sid in src_map:
            return src_map[sid]
        raise KeyError(sid)

    storage.get_memory_object.side_effect = _get_memory_object
    storage.get_source_item.side_effect = _get_source_item
    return storage


class TestRecomputeEmbeddingText:
    def test_recomputes_text_with_prefix_for_memory_object(self):
        """Recomputes embedding text from source and applies type prefix."""
        memory_object = _make_memory_object()
        entry = _make_index_entry(text_view="stale old text")
        storage = _make_mock_storage(memory_objects=[memory_object])

        result = _recompute_embedding_text(storage, entry)

        assert result is not None
        assert result.startswith("[decision]")

    def test_returns_none_for_orphaned_memory_object(self):
        """Entries whose memory object no longer exists return None."""
        entry = _make_index_entry(target_id="deleted-mem")
        storage = _make_mock_storage()

        result = _recompute_embedding_text(storage, entry)
        assert result is None

    def test_returns_none_for_orphaned_source_item(self):
        """Source item entry with deleted source returns None."""
        entry = _make_index_entry(target_kind="source_item", target_id="deleted-src")
        storage = _make_mock_storage()

        result = _recompute_embedding_text(storage, entry)
        assert result is None

    def test_recomputes_source_item_text(self):
        """Recomputes embedding text for source_item entries."""
        source_item = _make_source_item()
        entry = _make_index_entry(target_kind="source_item", target_id="src-1")
        storage = _make_mock_storage(source_items=[source_item])

        result = _recompute_embedding_text(storage, entry)
        assert result == source_item.content

    def test_routes_fact_embedding_to_fact_recompute(self):
        """Entries with fact_embedding in text_view_name use fact-specific recompute."""
        memory_object = MemoryObject(
            type="atomic_fact",
            schema_id="test",
            schema_version="1",
            payload={"subject": "PostgreSQL", "statement": "supports MVCC"},
            id="mem-fact-1",
        )
        entry = _make_index_entry(
            target_id="mem-fact-1",
            text_view_name="memory_object.fact_embedding",
        )
        storage = _make_mock_storage(memory_objects=[memory_object])

        result = _recompute_embedding_text(storage, entry)
        assert result == "[atomic_fact] PostgreSQL: supports MVCC"

    def test_routes_fact_summary_embedding_to_fact_recompute(self):
        """Entries with fact_summary_embedding use fact-specific recompute."""
        memory_object = MemoryObject(
            type="fact_summary",
            schema_id="test",
            schema_version="1",
            payload={"subject": "Databases", "summary": "PostgreSQL preferred"},
            id="mem-fs-1",
        )
        entry = _make_index_entry(
            target_id="mem-fs-1",
            text_view_name="memory_object.fact_summary_embedding",
        )
        storage = _make_mock_storage(memory_objects=[memory_object])

        result = _recompute_embedding_text(storage, entry)
        assert result == "[fact_summary] Databases: PostgreSQL preferred"

    def test_returns_none_for_unknown_target_kind(self):
        """Unknown target_kind returns None."""
        entry = IndexEntry(
            id="e1",
            target_kind="unknown",
            target_id="x",
            index_type="vector",
            text_view="text",
            text_view_name="default",
        )
        storage = _make_mock_storage()
        result = _recompute_embedding_text(storage, entry)
        assert result is None


class TestRecomputeFactEmbeddingText:
    def test_atomic_fact_with_subject(self):
        mo = MemoryObject(
            type="atomic_fact", schema_id="t", schema_version="1",
            payload={"subject": "Python", "statement": "is dynamically typed"},
        )
        assert _recompute_fact_embedding_text(mo) == "[atomic_fact] Python: is dynamically typed"

    def test_atomic_fact_without_subject(self):
        mo = MemoryObject(
            type="atomic_fact", schema_id="t", schema_version="1",
            payload={"statement": "is dynamically typed"},
        )
        assert _recompute_fact_embedding_text(mo) == "[atomic_fact] is dynamically typed"

    def test_fact_summary_with_subject(self):
        mo = MemoryObject(
            type="fact_summary", schema_id="t", schema_version="1",
            payload={"subject": "Languages", "summary": "Python is popular"},
        )
        assert _recompute_fact_embedding_text(mo) == "[fact_summary] Languages: Python is popular"

    def test_fact_summary_without_subject(self):
        mo = MemoryObject(
            type="fact_summary", schema_id="t", schema_version="1",
            payload={"summary": "Python is popular"},
        )
        assert _recompute_fact_embedding_text(mo) == "[fact_summary] Python is popular"

    def test_unknown_type_returns_none(self):
        mo = MemoryObject(
            type="decision", schema_id="t", schema_version="1",
            payload={"subject": "X", "statement": "Y"},
        )
        assert _recompute_fact_embedding_text(mo) is None

    def test_empty_payload_returns_none(self):
        mo = MemoryObject(
            type="atomic_fact", schema_id="t", schema_version="1",
            payload={},
        )
        assert _recompute_fact_embedding_text(mo) is None


pytestmark_usearch = pytest.mark.skipif(not HAS_USEARCH, reason="usearch not installed")


class FakeResults:
    def __init__(self, keys, distances):
        self.keys = keys
        self.distances = distances


class FakeIndex:
    def __init__(self, ndim: int = 0, metric: str = "cos", dtype: str = "f32"):
        self.ndim = ndim
        self._vectors: dict[int, list[float]] = {}

    def add(self, key: int, vector) -> None:
        self._vectors[key] = vector.tolist() if hasattr(vector, "tolist") else list(vector)

    def remove(self, key: int) -> None:
        self._vectors.pop(key, None)

    def search(self, query_vector, k: int, exact: bool = False) -> FakeResults:
        return FakeResults(keys=[], distances=[])

    def save(self, path: str) -> None:
        vecs = {str(k): v for k, v in self._vectors.items()}
        Path(path).write_text(json.dumps({"vectors": vecs}), encoding="utf-8")

    def load(self, path: str) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self._vectors = {int(k): v for k, v in data["vectors"].items()}


@pytest.fixture()
def mock_usearch():
    with patch("usearch.index.Index", FakeIndex):
        yield


@pytest.mark.xdist_group("vector_rebuild")
class TestVectorIndexSchemaVersion:
    @pytestmark_usearch
    def test_schema_version_in_meta_json(self, mock_usearch, tmp_path: Path):
        """Schema version is persisted in meta.json on save and loaded back."""
        from storage.vector_index import VectorIndex

        index_path = tmp_path / "test.index"
        idx = VectorIndex.create_empty(index_path, dimensions=3, model_name="test-model", embedding_schema_version=2)
        assert idx.embedding_schema_version == 2

        meta_path = Path(f"{index_path}.meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["embedding_schema_version"] == 2

        loaded = VectorIndex.load(index_path)
        assert loaded.embedding_schema_version == 2

    @pytestmark_usearch
    def test_schema_version_defaults_to_1(self, mock_usearch, tmp_path: Path):
        """Loading an old meta.json without embedding_schema_version defaults to 1."""
        from storage.vector_index import VectorIndex

        index_path = tmp_path / "test.index"
        VectorIndex.create_empty(index_path, dimensions=3, model_name="test-model", embedding_schema_version=2)

        meta_path = Path(f"{index_path}.meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        del meta["embedding_schema_version"]
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        loaded = VectorIndex.load(index_path)
        assert loaded.embedding_schema_version == 1

    @pytestmark_usearch
    def test_create_empty_default_schema_version(self, mock_usearch, tmp_path: Path):
        """create_empty without explicit schema_version defaults to 1."""
        from storage.vector_index import VectorIndex

        index_path = tmp_path / "test.index"
        idx = VectorIndex.create_empty(index_path, dimensions=3, model_name="test-model")
        assert idx.embedding_schema_version == 1
