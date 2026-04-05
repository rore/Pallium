from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VectorIndexConfig:
    enabled: bool = True
    index_path: str = "./pallium_vector.index"
    embedding_provider: str = "onnx"  # key into embedding_providers
    min_similarity: float = 0.55


def _require_usearch():
    """Lazy import guard for usearch. Raises a clear error when not installed."""
    try:
        from usearch.index import Index
    except ImportError:
        raise ImportError(
            "usearch is required for vector indexing but is not installed. "
            "Install it with: pip install usearch"
        ) from None
    return Index


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON to a file atomically via temp file + os.replace."""
    tmp = path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


class VectorIndex:
    """In-process vector index backed by usearch.

    Wraps usearch.index.Index(ndim=dims, metric='cos', dtype='f32').
    Uses exact=True for search (brute-force cosine at current scale).

    Entry ID mapping: bidirectional dict between string UUIDs and usearch
    integer keys, persisted as {index_path}.idmap.json.

    Metadata file {index_path}.meta.json stores model_name, dimensions,
    and entry_count.

    Thread safety: usearch.Index is concurrent by design (add/search/remove
    can run simultaneously). The Python-side dicts (_id_to_key, _key_to_id)
    are individually thread-safe under CPython's GIL, but compound operations
    (e.g., add's read-then-write sequence) are not atomic. In practice this
    means a concurrent search may briefly see an incomplete state — at worst
    a single result is missed for one query. If Pallium moves to free-threaded
    Python (PEP 703), these operations will need a lock.
    """

    def __init__(self, index_path: Path, dimensions: int, model_name: str) -> None:
        Index = _require_usearch()
        self._index_path = Path(index_path)
        self._dimensions = dimensions
        self._model_name = model_name
        self._index = Index(ndim=dimensions, metric="cos", dtype="f32")
        self._id_to_key: dict[str, int] = {}
        self._key_to_id: dict[int, str] = {}
        self._next_key: int = 0

    def add(self, entry_id: str, vector: list[float]) -> None:
        """Add or replace a vector for the given entry_id."""
        import numpy as np

        if entry_id in self._id_to_key:
            self.remove(entry_id)
        key = self._next_key
        self._next_key += 1
        self._id_to_key[entry_id] = key
        self._key_to_id[key] = entry_id
        self._index.add(key, np.array(vector, dtype=np.float32))

    def remove(self, entry_id: str) -> None:
        """Remove a vector by entry_id. Raises KeyError if not found."""
        if entry_id not in self._id_to_key:
            raise KeyError(entry_id)
        key = self._id_to_key.pop(entry_id)
        del self._key_to_id[key]
        self._index.remove(key)

    def search(self, query_vector: list[float], k: int) -> list[tuple[str, float]]:
        """Returns (entry_id, cosine_similarity) sorted descending by similarity.

        Uses exact=True for brute-force cosine search at current scale.
        """
        if not self._id_to_key:
            return []
        import numpy as np

        effective_k = min(k, len(self._id_to_key))
        results = self._index.search(np.array(query_vector, dtype=np.float32), effective_k, exact=True)
        hits: list[tuple[str, float]] = []
        for i in range(len(results.keys)):
            key = int(results.keys[i])
            if key in self._key_to_id:
                # usearch cosine metric returns distance; similarity = 1 - distance
                distance = float(results.distances[i])
                similarity = 1.0 - distance
                hits.append((self._key_to_id[key], similarity))
        hits.sort(key=lambda x: x[1], reverse=True)
        return hits

    def save(self) -> None:
        """Persist the index, ID map, and metadata to disk.

        JSON sidecar files are written atomically via temp file + os.replace.
        meta.json is written LAST so its mtime serves as the change indicator.
        """
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        # 1. Binary index (usearch writes directly)
        self._index.save(str(self._index_path))
        # 2. ID map (atomic)
        idmap_path = Path(f"{self._index_path}.idmap.json")
        idmap_data = {
            "id_to_key": self._id_to_key,
            "next_key": self._next_key,
        }
        _atomic_write_json(idmap_path, idmap_data)
        # 3. Meta LAST (atomic — its mtime is the freshness signal)
        meta_path = Path(f"{self._index_path}.meta.json")
        meta_data = {
            "model_name": self._model_name,
            "dimensions": self._dimensions,
            "entry_count": len(self._id_to_key),
        }
        _atomic_write_json(meta_path, meta_data)

    @classmethod
    def load(cls, index_path: Path) -> VectorIndex:
        """Load a previously saved index from disk."""
        meta_path = Path(f"{index_path}.meta.json")
        meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
        model_name = meta_data["model_name"]
        dimensions = meta_data["dimensions"]

        instance = cls(index_path, dimensions, model_name)

        idmap_path = Path(f"{index_path}.idmap.json")
        idmap_data = json.loads(idmap_path.read_text(encoding="utf-8"))
        instance._id_to_key = {k: int(v) for k, v in idmap_data["id_to_key"].items()}
        instance._key_to_id = {v: k for k, v in instance._id_to_key.items()}
        instance._next_key = idmap_data["next_key"]

        # Loading an empty persisted usearch index can crash the Windows native runtime.
        if meta_data.get("entry_count", 0) > 0 and index_path.exists() and index_path.stat().st_size > 0:
            instance._index.load(str(index_path))

        return instance

    @classmethod
    def create_empty(cls, index_path: Path, dimensions: int, model_name: str) -> VectorIndex:
        """Create a new empty index and persist it immediately."""
        instance = cls(index_path, dimensions, model_name)
        instance.save()
        return instance

    def entry_count(self) -> int:
        """Return the number of entries currently in the index."""
        return len(self._id_to_key)

    @property
    def model_name(self) -> str:
        """Return the model name this index was built with."""
        return self._model_name

    @property
    def dimensions(self) -> int:
        """Return the dimensionality of the vectors in this index."""
        return self._dimensions

    def known_entry_ids(self) -> frozenset[str]:
        """Return the set of entry IDs currently in the index."""
        return frozenset(self._id_to_key.keys())