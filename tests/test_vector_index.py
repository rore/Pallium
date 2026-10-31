from __future__ import annotations

import json
import threading
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

    def get(self, keys):
        if isinstance(keys, int):
            return self._vectors.get(keys)
        return [self._vectors.get(key) for key in keys]

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

    def save(self, path: str | None = None) -> bytearray | None:
        # Write a marker so load can detect the file; convert numpy arrays to lists for JSON
        vecs = {str(k): (v.tolist() if hasattr(v, "tolist") else v) for k, v in self._vectors.items()}
        data = bytearray(json.dumps({"vectors": vecs}).encode("utf-8"))
        if path is None:
            return data
        Path(path).write_bytes(data)

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


def test_score_subset_uses_keyed_vectors_and_deterministic_cosine(mock_usearch, tmp_path: Path):
    from storage.vector_index import VectorIndex

    idx = VectorIndex(tmp_path / "test.index", dimensions=2, model_name="test-model")
    idx.add("b", [1.0, 0.0])
    idx.add("a", [1.0, 0.0])
    idx.add("zero", [0.0, 0.0])
    assert idx.score_subset([1.0, 0.0], ["missing", "zero", "b", "a"]) == [
        ("a", pytest.approx(1.0)),
        ("b", pytest.approx(1.0)),
        ("zero", pytest.approx(0.0)),
    ]

    assert idx.score_subset([0.0, 0.0], ["b", "zero"]) == [
        ("zero", pytest.approx(1.0)),
        ("b", pytest.approx(0.0)),
    ]


def test_score_subset_handles_negative_missing_duplicates_and_dimension_errors(mock_usearch, tmp_path: Path):
    from storage.vector_index import VectorIndex

    idx = VectorIndex(tmp_path / "test.index", dimensions=2, model_name="test-model")
    idx.add("positive", [2.0, 0.0])
    idx.add("negative", [-3.0, 0.0])
    assert idx.score_subset([1.0, 0.0], ["missing", "negative", "positive", "positive"]) == [
        ("positive", pytest.approx(1.0)),
        ("negative", pytest.approx(-1.0)),
    ]
    with pytest.raises(ValueError):
        idx.score_subset([1.0], ["positive"])


def test_score_subset_matches_real_usearch_zero_and_cosine_semantics(tmp_path: Path):
    from storage.vector_index import VectorIndex

    idx = VectorIndex(tmp_path / "real.index", dimensions=2, model_name="real-usearch")
    idx.add("both-zero", [0.0, 0.0])
    idx.add("one-zero", [1.0, 0.0])
    idx.add("opposite", [-2.0, 0.0])
    idx.add("non-unit", [3.0, 4.0])
    idx.add("tie-b", [0.6, 0.8])
    idx.add("tie-a", [0.6, 0.8])

    assert idx.score_subset([0.0, 0.0], [
        "missing", "both-zero", "one-zero", "opposite", "non-unit", "tie-b", "tie-a"
    ]) == [
        ("both-zero", pytest.approx(1.0)),
        ("non-unit", pytest.approx(0.0)),
        ("one-zero", pytest.approx(0.0)),
        ("opposite", pytest.approx(0.0)),
        ("tie-a", pytest.approx(0.0)),
        ("tie-b", pytest.approx(0.0)),
    ]
    assert idx.score_subset([1.0, 0.0], [
        "missing", "both-zero", "one-zero", "opposite", "non-unit", "tie-b", "tie-a"
    ]) == [
        ("one-zero", pytest.approx(1.0)),
        ("non-unit", pytest.approx(0.6)),
        ("tie-a", pytest.approx(0.6)),
        ("tie-b", pytest.approx(0.6)),
        ("both-zero", pytest.approx(0.0)),
        ("opposite", pytest.approx(-1.0)),
    ]
    query = [1.0, 0.0]
    entry_ids = ["both-zero", "one-zero", "opposite", "non-unit", "tie-b", "tie-a"]
    subset_scores = dict(idx.score_subset(query, entry_ids))
    native_scores = dict(idx.search(query, idx.entry_count()))
    assert subset_scores == pytest.approx(native_scores, abs=1e-6)


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
        "embedding_schema_version": 1,
    }


def test_vector_index_config_defaults():
    from storage.vector_index import VectorIndexConfig

    config = VectorIndexConfig()
    assert config.enabled is True
    assert config.index_path == "./vector_index"
    assert config.embedding_provider == "onnx"
    assert config.min_similarity is None  # None = use model's recommended value


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


def test_save_uses_native_buffer_without_copy_and_publishes_metadata_last(mock_usearch, tmp_path, monkeypatch):
    import storage.vector_index as module
    index = module.VectorIndex(tmp_path / "snapshot.index", 2, "generic")
    index.add("שלום-α", [1., 0.])
    serialize, write, replace = index._index.save, Path.write_bytes, module._replace_with_retry
    buffers, published = [], []
    def buffered():
        value = serialize()
        buffers.append(value)
        return value
    def writing(path, value):
        assert value is buffers[-1] and isinstance(value, bytearray)
        return write(path, value)
    def replacing(source, target):
        published.append(Path(target).name)
        return replace(source, target)
    monkeypatch.setattr(index._index, "save", buffered)
    monkeypatch.setattr(Path, "write_bytes", writing)
    monkeypatch.setattr(module, "_replace_with_retry", replacing)
    index.save()
    assert len(buffers) == 1
    assert published == ["snapshot.index", "snapshot.index.idmap.json", "snapshot.index.meta.json"]
    assert module.VectorIndex.load(index._index_path).search([1., 0.], 1)[0][0] == "שלום-α"


@pytest.mark.parametrize("stage", ["serialize", "binary-write", "binary-replace", "idmap-write", "idmap-replace", "meta-write", "meta-replace"])
def test_save_failure_preserves_cleanup_metadata_and_releases_mutation_lock(mock_usearch, tmp_path, monkeypatch, stage):
    import storage.vector_index as module
    index = module.VectorIndex.create_empty(tmp_path / "snapshot.index", 2, "generic")
    index.add("old", [1., 0.])
    index.save()
    binary_before = index._index_path.read_bytes()
    meta_path = Path(str(index._index_path) + ".meta.json")
    meta_before = meta_path.read_bytes()
    index.add("new", [0., 1.])
    original = OSError("controlled persistence failure")
    write_bytes, write_text, replace = Path.write_bytes, Path.write_text, module._replace_with_retry
    def fail_serialize():
        raise original
    def failing_bytes(path, value):
        write_bytes(path, value[:4])
        raise original
    def failing_text(path, value, *args, **kwargs):
        if (stage == "idmap-write" and ".idmap." in path.name
                or stage == "meta-write" and ".meta." in path.name):
            write_text(path, value[:4], *args, **kwargs)
            raise original
        return write_text(path, value, *args, **kwargs)
    def failing_replace(source, target):
        if (stage == "binary-replace" and Path(target) == index._index_path
                or stage == "idmap-replace" and str(target).endswith(".idmap.json")
                or stage == "meta-replace" and str(target).endswith(".meta.json")):
            raise original
        return replace(source, target)
    with monkeypatch.context() as patcher:
        if stage == "serialize":
            patcher.setattr(index._index, "save", fail_serialize)
        if stage == "binary-write":
            patcher.setattr(Path, "write_bytes", failing_bytes)
        patcher.setattr(Path, "write_text", failing_text)
        patcher.setattr(module, "_replace_with_retry", failing_replace)
        with pytest.raises(OSError) as caught:
            index.save()
        assert caught.value is original
    assert meta_path.read_bytes() == meta_before
    if stage in {"serialize", "binary-write", "binary-replace"}:
        assert index._index_path.read_bytes() == binary_before
    assert list(tmp_path.glob("*.tmp")) == []
    errors = []
    def retry_from_another_thread():
        try:
            index.add("new", [0., 1.])  # Reentrant add-to-remove after failed save.
            index.save()
        except BaseException as exc:
            errors.append(exc)
    worker = threading.Thread(target=retry_from_another_thread, daemon=True)
    worker.start(); worker.join(3)
    assert not worker.is_alive() and not errors
    loaded = module.VectorIndex.load(index._index_path)
    assert loaded.entry_count() == 2 and loaded.search([0., 1.], 1)[0][0] == "new"


@pytest.mark.parametrize("operation", ["add", "remove", "save"])
def test_slow_binary_write_serializes_mutations_and_saves_but_not_search(mock_usearch, tmp_path, monkeypatch, operation):
    from storage.vector_index import VectorIndex
    index = VectorIndex.create_empty(tmp_path / "snapshot.index", 2, "generic")
    index.add("old", [1., 0.])
    index.save()
    entered, release, attempted, done = (threading.Event() for _ in range(4))
    write = Path.write_bytes
    calls, errors = [], []
    def slow_write(path, value):
        calls.append(path)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return write(path, value)
    monkeypatch.setattr(Path, "write_bytes", slow_write)
    def first_save():
        try:
            index.save()
        except BaseException as exc:
            errors.append(exc)
    def overlap():
        attempted.set()
        try:
            if operation == "add":
                index.add("old", [0., 1.])
            elif operation == "remove":
                index.remove("old")
            else:
                index.save()
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()
    saver = threading.Thread(target=first_save, daemon=True)
    worker = threading.Thread(target=overlap, daemon=True)
    try:
        saver.start()
        assert entered.wait(3)
        worker.start()
        assert attempted.wait(3) and not done.wait(.05)
        assert index.search([1., 0.], 1)[0][0] == "old"
    finally:
        release.set()
        saver.join(3)
        if worker.ident is not None:
            worker.join(3)
    assert not saver.is_alive() and not worker.is_alive() and not errors
    index.save()
    loaded = VectorIndex.load(index._index_path)
    if operation == "remove":
        assert loaded.entry_count() == 0
    else:
        assert loaded.entry_count() == 1
        assert loaded.search([0., 1.] if operation == "add" else [1., 0.], 1)[0][1] == pytest.approx(1.)


@pytest.mark.parametrize("populated", [False, True])
def test_buffer_saved_native_index_round_trip(populated, tmp_path):
    from storage.vector_index import VectorIndex
    index = VectorIndex.create_empty(tmp_path / "native.index", 2, "generic")
    if populated:
        index.add("é-שלום", [1., 0.])
        index.add("removed", [0., 1.])
        index.remove("removed")
    index.save()
    loaded = VectorIndex.load(index._index_path)
    assert loaded.entry_count() == int(populated)
    assert (loaded.search([1., 0.], 1)[0][0] if populated else loaded.search([1., 0.], 1)) == ("é-שלום" if populated else [])
