import threading
from unittest.mock import MagicMock

import pytest

from core.vector_index_holder import VectorIndexHolder
from storage.vector_index import VectorIndex


def _mock_index() -> VectorIndex:
    return MagicMock(spec=VectorIndex)


class TestVectorIndexHolder:
    def test_initial_none(self):
        holder = VectorIndexHolder()
        assert holder.index is None
        assert holder.is_available is False

    def test_initial_with_index(self):
        mock_index = _mock_index()
        holder = VectorIndexHolder(mock_index)
        assert holder.index is mock_index
        assert holder.is_available is True

    def test_swap_returns_old(self):
        old = _mock_index()
        new = _mock_index()
        holder = VectorIndexHolder(old)
        returned = holder.swap(new)
        assert returned is old
        assert holder.index is new

    def test_concurrent_access(self):
        """Many readers + one writer don't crash."""
        holder = VectorIndexHolder(_mock_index())
        results = []
        barrier = threading.Barrier(11)

        def reader():
            barrier.wait()
            for _ in range(1000):
                idx = holder.index
                assert idx is not None
            results.append("ok")

        def writer():
            barrier.wait()
            for _ in range(100):
                holder.swap(_mock_index())

        threads = [threading.Thread(target=reader) for _ in range(10)]
        threads.append(threading.Thread(target=writer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 10
