import json
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.models import IndexEntry
from core.rebuild_coordinator import RebuildCheckpoint, RebuildCoordinator
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


# --- Test helpers for RebuildCoordinator ---


def _make_entry(entry_id: str, text: str = "some text") -> IndexEntry:
    """Create a minimal IndexEntry for testing."""
    return IndexEntry(
        id=entry_id,
        target_kind="memory_object",
        target_id=f"mo-{entry_id}",
        index_type="vector",
        text_view=text,
        text_view_name="default.embedding",
    )


def _make_stub_provider(dimensions=8):
    provider = MagicMock()
    provider.dimensions.return_value = dimensions
    provider.model_name.return_value = "test-model"
    provider.embed.side_effect = lambda texts, **kw: [[0.1] * dimensions for _ in texts]
    return provider


def _make_stub_storage(entries: list[IndexEntry]):
    storage = MagicMock()

    def page(index_type, *, after_id=None, limit=None):
        effective_limit = limit or 128
        if after_id is None:
            return entries[:effective_limit]
        for i, e in enumerate(entries):
            if e.id == after_id:
                return entries[i + 1:i + 1 + effective_limit]
        return []

    storage.list_index_entries_by_type_page.side_effect = page
    storage.count_index_entries_by_type.return_value = len(entries)
    storage.update_index_entry_text_view = MagicMock()
    storage.get_memory_object = MagicMock(side_effect=KeyError)
    storage.get_source_item = MagicMock(side_effect=KeyError)
    return storage


def _make_coordinator(tmp_path: Path, entries: list[IndexEntry], **kwargs):
    """Helper to create a coordinator with stubs and a real index path."""
    storage = _make_stub_storage(entries)
    provider = _make_stub_provider(dimensions=kwargs.pop("dimensions", 8))
    holder = VectorIndexHolder()
    index_path = tmp_path / "live.usearch"
    coordinator = RebuildCoordinator(
        storage=storage,
        embedding_provider=provider,
        index_holder=holder,
        index_path=index_path,
        target_model_name="test-model",
        target_dimensions=provider.dimensions(),
        target_schema_version=1,
        reason="test rebuild",
        batch_size=kwargs.pop("batch_size", 2),
        shadow_save_interval=kwargs.pop("shadow_save_interval", 2),
        on_swap_callback=kwargs.pop("on_swap_callback", None),
    )
    return coordinator, holder, storage, provider


class TestRebuildCheckpoint:
    def test_save_load_roundtrip(self, tmp_path: Path):
        path = tmp_path / "checkpoint.json"
        cp = RebuildCheckpoint(
            status="in_progress",
            reason="model upgrade",
            model_name="test-model",
            dimensions=8,
            embedding_schema_version=1,
            temp_index_dir=str(tmp_path / "shadow"),
            last_processed_entry_id="entry-5",
            entry_count_total=100,
            entry_count_processed=50,
            batch_size=10,
            started_at="2026-01-01T00:00:00+00:00",
        )
        cp.save(path)

        loaded = RebuildCheckpoint.load(path)
        assert loaded is not None
        assert loaded.status == "in_progress"
        assert loaded.reason == "model upgrade"
        assert loaded.last_processed_entry_id == "entry-5"
        assert loaded.entry_count_processed == 50
        assert loaded.entry_count_total == 100
        assert loaded.updated_at != ""

    def test_load_nonexistent_returns_none(self, tmp_path: Path):
        path = tmp_path / "nonexistent.json"
        result = RebuildCheckpoint.load(path)
        assert result is None

    def test_load_ignores_unknown_fields(self, tmp_path: Path):
        path = tmp_path / "checkpoint.json"
        data = {
            "status": "in_progress",
            "reason": "test",
            "model_name": "m",
            "dimensions": 8,
            "embedding_schema_version": 1,
            "temp_index_dir": "/tmp/x",
            "last_processed_entry_id": None,
            "entry_count_total": 10,
            "entry_count_processed": 0,
            "batch_size": 5,
            "started_at": "",
            "updated_at": "",
            "future_field": "should be ignored",
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        loaded = RebuildCheckpoint.load(path)
        assert loaded is not None
        assert loaded.status == "in_progress"
        assert not hasattr(loaded, "future_field")


class TestRebuildCoordinator:
    def test_full_rebuild_completes_and_swaps(self, tmp_path: Path):
        """Full rebuild with 5 entries, batch_size=2 completes and swaps into holder."""
        entries = [_make_entry(f"e-{i}", f"text {i}") for i in range(5)]
        coordinator, holder, storage, provider = _make_coordinator(
            tmp_path, entries, batch_size=2, shadow_save_interval=2,
        )

        coordinator.run_sync()

        assert holder.is_available
        assert holder.index.entry_count() == 5
        # State file cleaned up
        state_path = Path(f"{tmp_path / 'live.usearch'}.rebuild_state.json")
        assert not state_path.exists()
        # Shadow dir cleaned up
        shadow_dir = Path(f"{tmp_path / 'live.usearch'}.rebuild")
        assert not shadow_dir.exists()

    def test_on_swap_callback_invoked(self, tmp_path: Path):
        """on_swap_callback is called after successful swap."""
        entries = [_make_entry("e-0", "hello")]
        callback_called = []
        coordinator, holder, _, _ = _make_coordinator(
            tmp_path, entries, on_swap_callback=lambda: callback_called.append(True),
        )
        coordinator.run_sync()
        assert callback_called == [True]

    def test_status_reports_progress(self, tmp_path: Path):
        """Status returns correct progress info."""
        entries = [_make_entry(f"e-{i}") for i in range(4)]
        coordinator, holder, _, _ = _make_coordinator(tmp_path, entries, batch_size=2)

        # Before start
        assert coordinator.status() is None

        coordinator.run_sync()
        # After completion, checkpoint is marked completed
        status = coordinator.status()
        assert status is not None
        assert status["status"] == "completed"
        assert status["entries_processed"] == 4
        assert status["progress_percent"] == 100.0

    def test_resume_from_checkpoint(self, tmp_path: Path):
        """Rebuild resumes from a prior checkpoint after simulated crash."""
        entries = [_make_entry(f"e-{i}", f"text {i}") for i in range(6)]
        storage = _make_stub_storage(entries)
        provider = _make_stub_provider()
        holder = VectorIndexHolder()
        index_path = tmp_path / "live.usearch"

        # First coordinator: process 1 batch (2 entries), then simulate crash
        coord1 = RebuildCoordinator(
            storage=storage,
            embedding_provider=provider,
            index_holder=holder,
            index_path=index_path,
            target_model_name="test-model",
            target_dimensions=8,
            target_schema_version=1,
            reason="test",
            batch_size=2,
            shadow_save_interval=2,
        )
        coord1._start_or_resume()
        coord1._process_one_batch()
        # Verify checkpoint has progress
        state_path = Path(f"{index_path}.rebuild_state.json")
        assert state_path.exists()
        cp = RebuildCheckpoint.load(state_path)
        assert cp.entry_count_processed == 2
        assert cp.last_processed_entry_id == "e-1"
        # Save the shadow index so resume can load it
        coord1._shadow_index.save()

        # Second coordinator: resume and complete
        coord2 = RebuildCoordinator(
            storage=storage,
            embedding_provider=provider,
            index_holder=holder,
            index_path=index_path,
            target_model_name="test-model",
            target_dimensions=8,
            target_schema_version=1,
            reason="test",
            batch_size=2,
            shadow_save_interval=2,
        )
        coord2.run_sync()

        assert holder.is_available
        assert holder.index.entry_count() == 6

    def test_cancellation_via_stop_event(self, tmp_path: Path):
        """Setting stop_event before run prevents completion."""
        entries = [_make_entry(f"e-{i}") for i in range(100)]
        coordinator, holder, _, _ = _make_coordinator(tmp_path, entries, batch_size=5)

        # Set stop before running
        coordinator._stop_event.set()
        coordinator.run_sync()

        # Rebuild didn't complete — holder should not be available
        assert not holder.is_available

    def test_empty_index_rebuild(self, tmp_path: Path):
        """Rebuild with zero entries completes without error."""
        entries = []
        coordinator, holder, _, _ = _make_coordinator(tmp_path, entries)
        coordinator.run_sync()
        # With 0 entries expected, rebuild should succeed (empty is valid)
        assert holder.is_available
        assert holder.index.entry_count() == 0

    def test_start_runs_in_background_thread(self, tmp_path: Path):
        """start() launches a daemon thread that completes the rebuild."""
        entries = [_make_entry(f"e-{i}") for i in range(3)]
        coordinator, holder, _, _ = _make_coordinator(tmp_path, entries)

        coordinator.start()
        coordinator._thread.join(timeout=10)

        assert holder.is_available
        assert holder.index.entry_count() == 3


class TestCrashRecovery:
    def test_cleanup_orphaned_rebuild(self, tmp_path: Path):
        """Shadow dir without state file is cleaned up."""
        index_path = tmp_path / "live.usearch"
        shadow_dir = Path(f"{index_path}.rebuild")
        shadow_dir.mkdir(parents=True)
        # Create a dummy file in it
        (shadow_dir / "index.usearch").write_bytes(b"dummy")

        # No state file exists
        result = RebuildCoordinator.cleanup_orphaned_rebuild(index_path)
        assert result is True
        assert not shadow_dir.exists()

    def test_cleanup_does_nothing_when_state_exists(self, tmp_path: Path):
        """Shadow dir WITH state file is NOT cleaned up."""
        index_path = tmp_path / "live.usearch"
        shadow_dir = Path(f"{index_path}.rebuild")
        shadow_dir.mkdir(parents=True)
        state_path = Path(f"{index_path}.rebuild_state.json")
        state_path.write_text("{}", encoding="utf-8")

        result = RebuildCoordinator.cleanup_orphaned_rebuild(index_path)
        assert result is False
        assert shadow_dir.exists()

    def test_has_pending_rebuild_returns_checkpoint(self, tmp_path: Path):
        """Detects a resumable checkpoint file."""
        index_path = tmp_path / "live.usearch"
        state_path = Path(f"{index_path}.rebuild_state.json")
        cp = RebuildCheckpoint(
            status="in_progress",
            reason="model change",
            model_name="test",
            dimensions=8,
            embedding_schema_version=1,
            temp_index_dir=str(tmp_path / "shadow"),
            last_processed_entry_id="e-10",
            entry_count_total=50,
            entry_count_processed=20,
            batch_size=10,
        )
        cp.save(state_path)

        result = RebuildCoordinator.has_pending_rebuild(index_path)
        assert result is not None
        assert result.status == "in_progress"
        assert result.entry_count_processed == 20

    def test_has_pending_rebuild_returns_none(self, tmp_path: Path):
        """No state file means no pending rebuild."""
        index_path = tmp_path / "live.usearch"
        result = RebuildCoordinator.has_pending_rebuild(index_path)
        assert result is None

    def test_cleanup_does_nothing_when_no_shadow_dir(self, tmp_path: Path):
        """No shadow dir means nothing to clean."""
        index_path = tmp_path / "live.usearch"
        result = RebuildCoordinator.cleanup_orphaned_rebuild(index_path)
        assert result is False
