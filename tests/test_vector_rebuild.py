"""Tests for core/vector_rebuild.py and related VectorIndex schema version changes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.models import IndexEntry, MemoryObject, SourceItem


try:
    import usearch  # noqa: F401
    HAS_USEARCH = True
except ImportError:
    HAS_USEARCH = False

pytestmark = [
    pytest.mark.skipif(
        not HAS_USEARCH,
        reason="usearch not installed",
    ),
    pytest.mark.xdist_group("vector_rebuild"),
]


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


def _make_mock_storage(entries=None, memory_objects=None, source_items=None):
    """Build a mock storage provider."""
    storage = MagicMock()
    storage.list_index_entries_by_type.return_value = entries or []
    storage.update_index_entry_text_view = MagicMock()

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


def _make_mock_embedding_provider(dimensions: int = 3):
    """Build a mock embedding provider."""
    provider = MagicMock()
    provider.dimensions.return_value = dimensions
    provider.model_name.return_value = "test-model-v2"
    provider.embed.side_effect = lambda texts, mode="passage": [[0.1, 0.2, 0.3]] * len(texts)
    return provider


class TestRebuildRecomputesText:
    def test_rebuild_recomputes_text_with_prefix(self, mock_usearch, tmp_path: Path):
        """Rebuild recomputes embedding text from source and applies type prefix."""
        from core.vector_rebuild import rebuild_vector_index

        memory_object = _make_memory_object()
        entry = _make_index_entry(text_view="stale old text")
        storage = _make_mock_storage(entries=[entry], memory_objects=[memory_object])
        provider = _make_mock_embedding_provider()

        index_path = tmp_path / "test.index"
        result = rebuild_vector_index(
            storage=storage,
            embedding_provider=provider,
            index_path=index_path,
            embedding_schema_version=2,
        )

        # The text was recomputed — should call embed with the new text
        provider.embed.assert_called_once()
        embed_texts = provider.embed.call_args[0][0]
        assert len(embed_texts) == 1
        # build_embedding_text for "decision" type includes "[decision]" prefix
        assert embed_texts[0].startswith("[decision]")
        assert result.entry_count() == 1

    def test_rebuild_skips_orphaned_entries(self, mock_usearch, tmp_path: Path):
        """Entries whose source object no longer exists are skipped without crash."""
        from core.vector_rebuild import rebuild_vector_index

        # Entry pointing to non-existent memory object
        entry = _make_index_entry(target_id="deleted-mem")
        storage = _make_mock_storage(entries=[entry])
        provider = _make_mock_embedding_provider()

        index_path = tmp_path / "test.index"
        result = rebuild_vector_index(
            storage=storage,
            embedding_provider=provider,
            index_path=index_path,
            embedding_schema_version=2,
        )

        assert result.entry_count() == 0
        provider.embed.assert_not_called()

    def test_rebuild_updates_stored_text_view(self, mock_usearch, tmp_path: Path):
        """update_index_entry_text_view is called when text changes during rebuild."""
        from core.vector_rebuild import rebuild_vector_index

        memory_object = _make_memory_object()
        entry = _make_index_entry(text_view="old stale text that does not match")
        storage = _make_mock_storage(entries=[entry], memory_objects=[memory_object])
        provider = _make_mock_embedding_provider()

        index_path = tmp_path / "test.index"
        rebuild_vector_index(
            storage=storage,
            embedding_provider=provider,
            index_path=index_path,
            embedding_schema_version=2,
        )

        storage.update_index_entry_text_view.assert_called_once()
        call_args = storage.update_index_entry_text_view.call_args
        assert call_args[0][0] == "entry-1"
        # New text should be the recomputed one
        assert call_args[0][1].startswith("[decision]")

    def test_rebuild_does_not_update_unchanged_text(self, mock_usearch, tmp_path: Path):
        """update_index_entry_text_view is NOT called when text already matches."""
        from core.vector_rebuild import rebuild_vector_index
        from semantic.agent_conversation_memory_embedding import build_embedding_text

        memory_object = _make_memory_object()
        # Pre-compute the correct text so stored text_view matches
        correct_text = build_embedding_text(memory_object)
        entry = _make_index_entry(text_view=correct_text)
        storage = _make_mock_storage(entries=[entry], memory_objects=[memory_object])
        provider = _make_mock_embedding_provider()

        index_path = tmp_path / "test.index"
        rebuild_vector_index(
            storage=storage,
            embedding_provider=provider,
            index_path=index_path,
            embedding_schema_version=2,
        )

        storage.update_index_entry_text_view.assert_not_called()


class TestRebuildFactEntries:
    def test_rebuild_atomic_fact_entry(self, mock_usearch, tmp_path: Path):
        """Rebuild handles atomic_fact entries via fact-specific text recomputation."""
        from core.vector_rebuild import rebuild_vector_index

        memory_object = MemoryObject(
            type="atomic_fact",
            schema_id="test",
            schema_version="1",
            payload={"subject": "PostgreSQL", "statement": "supports MVCC for concurrency"},
            id="mem-fact-1",
        )
        entry = _make_index_entry(
            target_id="mem-fact-1",
            text_view="old fact text",
            text_view_name="memory_object.fact_embedding",
        )
        storage = _make_mock_storage(entries=[entry], memory_objects=[memory_object])
        provider = _make_mock_embedding_provider()

        index_path = tmp_path / "test.index"
        rebuild_vector_index(
            storage=storage,
            embedding_provider=provider,
            index_path=index_path,
            embedding_schema_version=2,
        )

        embed_texts = provider.embed.call_args[0][0]
        assert embed_texts[0] == "[atomic_fact] PostgreSQL: supports MVCC for concurrency"

    def test_rebuild_fact_summary_entry(self, mock_usearch, tmp_path: Path):
        """Rebuild handles fact_summary entries via fact-specific text recomputation."""
        from core.vector_rebuild import rebuild_vector_index

        memory_object = MemoryObject(
            type="fact_summary",
            schema_id="test",
            schema_version="1",
            payload={"subject": "Databases", "summary": "PostgreSQL preferred for production use"},
            id="mem-fs-1",
        )
        entry = _make_index_entry(
            target_id="mem-fs-1",
            text_view="old summary text",
            text_view_name="memory_object.fact_summary_embedding",
        )
        storage = _make_mock_storage(entries=[entry], memory_objects=[memory_object])
        provider = _make_mock_embedding_provider()

        index_path = tmp_path / "test.index"
        rebuild_vector_index(
            storage=storage,
            embedding_provider=provider,
            index_path=index_path,
            embedding_schema_version=2,
        )

        embed_texts = provider.embed.call_args[0][0]
        assert embed_texts[0] == "[fact_summary] Databases: PostgreSQL preferred for production use"


class TestRebuildSourceItemEntries:
    def test_rebuild_source_item_entry(self, mock_usearch, tmp_path: Path):
        """Rebuild handles source_item entries correctly."""
        from core.vector_rebuild import rebuild_vector_index

        source_item = _make_source_item()
        entry = _make_index_entry(
            target_kind="source_item",
            target_id="src-1",
            text_view="old source text",
        )
        storage = _make_mock_storage(entries=[entry], source_items=[source_item])
        provider = _make_mock_embedding_provider()

        index_path = tmp_path / "test.index"
        rebuild_vector_index(
            storage=storage,
            embedding_provider=provider,
            index_path=index_path,
            embedding_schema_version=2,
        )

        embed_texts = provider.embed.call_args[0][0]
        assert embed_texts[0] == source_item.content

    def test_rebuild_skips_orphaned_source_item(self, mock_usearch, tmp_path: Path):
        """Source item entry with deleted source is skipped."""
        from core.vector_rebuild import rebuild_vector_index

        entry = _make_index_entry(
            target_kind="source_item",
            target_id="deleted-src",
        )
        storage = _make_mock_storage(entries=[entry])
        provider = _make_mock_embedding_provider()

        index_path = tmp_path / "test.index"
        result = rebuild_vector_index(
            storage=storage,
            embedding_provider=provider,
            index_path=index_path,
            embedding_schema_version=2,
        )

        assert result.entry_count() == 0


class TestAutoRebuildThreshold:
    def test_auto_rebuild_threshold_value(self):
        from core.vector_rebuild import AUTO_REBUILD_THRESHOLD
        assert AUTO_REBUILD_THRESHOLD == 5000


class TestVectorIndexSchemaVersion:
    def test_schema_version_in_meta_json(self, mock_usearch, tmp_path: Path):
        """Schema version is persisted in meta.json on save and loaded back."""
        from storage.vector_index import VectorIndex

        index_path = tmp_path / "test.index"
        idx = VectorIndex.create_empty(index_path, dimensions=3, model_name="test-model", embedding_schema_version=2)
        assert idx.embedding_schema_version == 2

        # Verify persisted in meta.json
        meta_path = Path(f"{index_path}.meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["embedding_schema_version"] == 2

        # Load and verify
        loaded = VectorIndex.load(index_path)
        assert loaded.embedding_schema_version == 2

    def test_schema_version_defaults_to_1(self, mock_usearch, tmp_path: Path):
        """Loading an old meta.json without embedding_schema_version defaults to 1."""
        from storage.vector_index import VectorIndex

        index_path = tmp_path / "test.index"
        # Create an index and manually strip the schema version from meta
        VectorIndex.create_empty(index_path, dimensions=3, model_name="test-model", embedding_schema_version=2)

        meta_path = Path(f"{index_path}.meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        del meta["embedding_schema_version"]
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        loaded = VectorIndex.load(index_path)
        assert loaded.embedding_schema_version == 1

    def test_create_empty_default_schema_version(self, mock_usearch, tmp_path: Path):
        """create_empty without explicit schema_version defaults to 1."""
        from storage.vector_index import VectorIndex

        index_path = tmp_path / "test.index"
        idx = VectorIndex.create_empty(index_path, dimensions=3, model_name="test-model")
        assert idx.embedding_schema_version == 1
