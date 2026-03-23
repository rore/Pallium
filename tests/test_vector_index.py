from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

try:
    import usearch  # noqa: F401
    HAS_USEARCH = True
except ImportError:
    HAS_USEARCH = False

pytestmark = [
    pytest.mark.skipif(
        not HAS_USEARCH,
        reason="usearch not installed — mock fixture unreliable under xdist",
    ),
    # Force all tests in this module into the same xdist worker.
    # The mock_usearch fixture patches sys.modules for usearch, and numpy's
    # native C extension cannot be re-loaded in a process that already imported
    # it.  Grouping prevents xdist from scattering these tests across workers
    # where the patching collides with numpy's one-load-per-process constraint.
    pytest.mark.xdist_group("vector_index"),
]


class FakeResults:
    """Mock for usearch search results."""

    def __init__(self, keys, distances):
        self.keys = keys
        self.distances = distances


class FakeIndex:
    """Mock for usearch.index.Index that tracks add/remove/search/save/load calls."""

    def __init__(self, ndim: int = 0, metric: str = "cos", dtype: str = "f32"):
        self.ndim = ndim
        self.metric = metric
        self.dtype = dtype
        self._vectors: dict[int, list[float]] = {}

    def add(self, key: int, vector) -> None:
        self._vectors[key] = vector.tolist() if hasattr(vector, "tolist") else list(vector)

    def remove(self, key: int) -> None:
        self._vectors.pop(key, None)

    def search(self, query_vector, k: int, exact: bool = False) -> FakeResults:
        """Brute-force cosine distance search over stored vectors."""
        import math

        results: list[tuple[int, float]] = []
        qv = list(query_vector)
        for key, vec in self._vectors.items():
            dot = sum(a * b for a, b in zip(qv, vec))
            mag_q = math.sqrt(sum(a * a for a in qv))
            mag_v = math.sqrt(sum(a * a for a in vec))
            if mag_q == 0 or mag_v == 0:
                cos_sim = 0.0
            else:
                cos_sim = dot / (mag_q * mag_v)
            # usearch cosine metric returns distance = 1 - similarity
            distance = 1.0 - cos_sim
            results.append((key, distance))
        results.sort(key=lambda x: x[1])
        results = results[:k]
        return FakeResults(
            keys=[r[0] for r in results],
            distances=[r[1] for r in results],
        )

    def save(self, path: str) -> None:
        # Write a marker so load can detect the file; convert numpy arrays to lists for JSON
        vecs = {str(k): (v.tolist() if hasattr(v, "tolist") else v) for k, v in self._vectors.items()}
        Path(path).write_text(json.dumps({"vectors": vecs}), encoding="utf-8")

    def load(self, path: str) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self._vectors = {int(k): v for k, v in data["vectors"].items()}


@pytest.fixture()
def mock_usearch():
    """Patch usearch.index.Index with FakeIndex for all tests in this module.

    Only patches the Index class, not the whole usearch module tree.
    Replacing the top-level ``usearch`` entry in sys.modules with a MagicMock
    poisons numpy's C-extension loader (numpy cannot be re-imported in a
    process that already loaded it), causing spurious ImportErrors under
    pytest-xdist and even in sequential runs.
    """
    with patch("usearch.index.Index", FakeIndex):
        yield


def test_import_guard_when_usearch_missing():
    """When usearch is not installed, _require_usearch raises ImportError with a clear message."""
    with patch.dict("sys.modules", {"usearch": None, "usearch.index": None}):
        from storage.vector_index import _require_usearch

        # Force re-import to pick up patched modules
        with pytest.raises(ImportError, match="usearch is required"):
            _require_usearch()


def test_create_empty_and_entry_count(mock_usearch, tmp_path: Path):
    from storage.vector_index import VectorIndex

    index_path = tmp_path / "test.index"
    idx = VectorIndex.create_empty(index_path, dimensions=3, model_name="test-model")
    assert idx.entry_count() == 0

    # Verify metadata file was written
    meta_path = Path(f"{index_path}.meta.json")
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["model_name"] == "test-model"
    assert meta["dimensions"] == 3
    assert meta["entry_count"] == 0

    # Verify idmap file was written
    idmap_path = Path(f"{index_path}.idmap.json")
    assert idmap_path.exists()


def test_load_empty_index_skips_native_load(mock_usearch, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from storage.vector_index import VectorIndex

    index_path = tmp_path / "test.index"
    VectorIndex.create_empty(index_path, dimensions=3, model_name="test-model")

    def _unexpected_load(self, path: str) -> None:
        raise AssertionError("empty vector index should not call native load")

    monkeypatch.setattr(FakeIndex, "load", _unexpected_load)

    loaded = VectorIndex.load(index_path)

    assert loaded.entry_count() == 0
    assert loaded.model_name == "test-model"
    assert loaded.dimensions == 3


def test_add_and_search(mock_usearch, tmp_path: Path):
    from storage.vector_index import VectorIndex

    index_path = tmp_path / "test.index"
    idx = VectorIndex(index_path, dimensions=3, model_name="test-model")

    idx.add("entry-1", [1.0, 0.0, 0.0])
    idx.add("entry-2", [0.0, 1.0, 0.0])
    idx.add("entry-3", [1.0, 1.0, 0.0])
    assert idx.entry_count() == 3

    # Search for vector close to entry-1
    results = idx.search([1.0, 0.0, 0.0], k=2)
    assert len(results) == 2
    assert results[0][0] == "entry-1"
    assert results[0][1] == pytest.approx(1.0, abs=0.01)


def test_add_replaces_existing(mock_usearch, tmp_path: Path):
    from storage.vector_index import VectorIndex

    index_path = tmp_path / "test.index"
    idx = VectorIndex(index_path, dimensions=3, model_name="test-model")

    idx.add("entry-1", [1.0, 0.0, 0.0])
    idx.add("entry-1", [0.0, 1.0, 0.0])  # Replace
    assert idx.entry_count() == 1

    results = idx.search([0.0, 1.0, 0.0], k=1)
    assert results[0][0] == "entry-1"
    assert results[0][1] == pytest.approx(1.0, abs=0.01)


def test_remove(mock_usearch, tmp_path: Path):
    from storage.vector_index import VectorIndex

    index_path = tmp_path / "test.index"
    idx = VectorIndex(index_path, dimensions=3, model_name="test-model")

    idx.add("entry-1", [1.0, 0.0, 0.0])
    idx.add("entry-2", [0.0, 1.0, 0.0])
    assert idx.entry_count() == 2

    idx.remove("entry-1")
    assert idx.entry_count() == 1

    results = idx.search([1.0, 0.0, 0.0], k=5)
    assert len(results) == 1
    assert results[0][0] == "entry-2"


def test_remove_nonexistent_raises(mock_usearch, tmp_path: Path):
    from storage.vector_index import VectorIndex

    index_path = tmp_path / "test.index"
    idx = VectorIndex(index_path, dimensions=3, model_name="test-model")

    with pytest.raises(KeyError):
        idx.remove("nonexistent")


def test_search_empty_index(mock_usearch, tmp_path: Path):
    from storage.vector_index import VectorIndex

    index_path = tmp_path / "test.index"
    idx = VectorIndex(index_path, dimensions=3, model_name="test-model")

    results = idx.search([1.0, 0.0, 0.0], k=5)
    assert results == []


def test_save_and_load_round_trip(mock_usearch, tmp_path: Path):
    from storage.vector_index import VectorIndex

    index_path = tmp_path / "test.index"
    idx = VectorIndex(index_path, dimensions=3, model_name="test-model")
    idx.add("entry-1", [1.0, 0.0, 0.0])
    idx.add("entry-2", [0.0, 1.0, 0.0])
    idx.add("entry-3", [0.0, 0.0, 1.0])
    idx.save()

    # Load from disk
    loaded = VectorIndex.load(index_path)
    assert loaded.entry_count() == 3
    assert loaded._model_name == "test-model"
    assert loaded._dimensions == 3

    # Search should still work
    results = loaded.search([1.0, 0.0, 0.0], k=2)
    assert len(results) == 2
    assert results[0][0] == "entry-1"
    assert results[0][1] == pytest.approx(1.0, abs=0.01)


def test_save_and_load_after_remove(mock_usearch, tmp_path: Path):
    from storage.vector_index import VectorIndex

    index_path = tmp_path / "test.index"
    idx = VectorIndex(index_path, dimensions=3, model_name="test-model")
    idx.add("entry-1", [1.0, 0.0, 0.0])
    idx.add("entry-2", [0.0, 1.0, 0.0])
    idx.remove("entry-1")
    idx.save()

    loaded = VectorIndex.load(index_path)
    assert loaded.entry_count() == 1

    results = loaded.search([1.0, 0.0, 0.0], k=5)
    assert len(results) == 1
    assert results[0][0] == "entry-2"


def test_metadata_file_contents(mock_usearch, tmp_path: Path):
    from storage.vector_index import VectorIndex

    index_path = tmp_path / "test.index"
    idx = VectorIndex(index_path, dimensions=128, model_name="text-embedding-ada-002")
    idx.add("a", [0.1] * 128)
    idx.add("b", [0.2] * 128)
    idx.save()

    meta_path = Path(f"{index_path}.meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta == {
        "model_name": "text-embedding-ada-002",
        "dimensions": 128,
        "entry_count": 2,
    }


def test_vector_index_config_defaults():
    from storage.vector_index import VectorIndexConfig

    config = VectorIndexConfig()
    assert config.enabled is True
    assert config.index_path == "./pallium_vector.index"
    assert config.embedding_provider == "onnx"
    assert config.min_similarity == 0.55


def test_vector_index_config_custom():
    from storage.vector_index import VectorIndexConfig

    config = VectorIndexConfig(
        enabled=True,
        index_path="/tmp/custom.index",
        embedding_provider="openai",
        min_similarity=0.5,
    )
    assert config.enabled is True
    assert config.index_path == "/tmp/custom.index"
    assert config.embedding_provider == "openai"
    assert config.min_similarity == 0.5


def test_search_k_larger_than_entries(mock_usearch, tmp_path: Path):
    from storage.vector_index import VectorIndex

    index_path = tmp_path / "test.index"
    idx = VectorIndex(index_path, dimensions=3, model_name="test-model")
    idx.add("only-one", [1.0, 0.0, 0.0])

    results = idx.search([1.0, 0.0, 0.0], k=100)
    assert len(results) == 1
    assert results[0][0] == "only-one"


def test_search_results_sorted_by_similarity_descending(mock_usearch, tmp_path: Path):
    from storage.vector_index import VectorIndex

    index_path = tmp_path / "test.index"
    idx = VectorIndex(index_path, dimensions=3, model_name="test-model")
    idx.add("exact", [1.0, 0.0, 0.0])
    idx.add("partial", [0.7, 0.7, 0.0])
    idx.add("orthogonal", [0.0, 1.0, 0.0])

    results = idx.search([1.0, 0.0, 0.0], k=3)
    assert len(results) == 3
    # Similarities should be in descending order
    similarities = [r[1] for r in results]
    assert similarities == sorted(similarities, reverse=True)
    assert results[0][0] == "exact"
