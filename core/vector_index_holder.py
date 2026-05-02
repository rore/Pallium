"""Thread-safe mutable slot for the active VectorIndex.

All consumers (VectorEmbedder, VectorRetrievalProvider) hold a reference to the
holder, not the index directly. The holder's .index property returns the current
live index. Swap is atomic under a lock.
"""
from __future__ import annotations

import threading

from storage.vector_index import VectorIndex


class VectorIndexHolder:
    def __init__(self, index: VectorIndex | None = None) -> None:
        self._lock = threading.Lock()
        self._index = index

    @property
    def index(self) -> VectorIndex | None:
        with self._lock:
            return self._index

    def swap(self, new_index: VectorIndex) -> VectorIndex | None:
        """Atomically replace the live index. Returns the previous index."""
        with self._lock:
            old = self._index
            self._index = new_index
            return old

    @property
    def is_available(self) -> bool:
        return self._index is not None
