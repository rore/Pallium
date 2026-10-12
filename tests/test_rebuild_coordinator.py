import json
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.models import IndexEntry, SourceItem
from core.rebuild_coordinator import RebuildCheckpoint, RebuildCoordinator, raw_source_vector_backfill_needed
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
    storage.list_raw_source_vector_backfill_page = None

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
    storage = kwargs.pop("storage", None)
    if storage is None:
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

    def test_stop_before_preparation_skips_work_and_reports_interrupted(self, tmp_path: Path):
        coordinator, _, _, _ = _make_coordinator(tmp_path, [])
        coordinator._stop_event.set()
        prepare = MagicMock()
        rebuild = MagicMock()
        coordinator._start_or_resume = prepare
        coordinator._rebuild_loop = rebuild

        coordinator.run_sync()

        prepare.assert_not_called()
        rebuild.assert_not_called()
        assert coordinator.status()["status"] == "interrupted"
        assert not coordinator._state_path.exists()

    def test_stop_after_thread_start_failure_skips_unstarted_join(self, tmp_path: Path, monkeypatch):
        coordinator, _, _, _ = _make_coordinator(tmp_path, [])

        def fail_start(_thread):
            raise RuntimeError("thread start failed")

        monkeypatch.setattr(threading.Thread, "start", fail_start)
        with pytest.raises(RuntimeError, match="thread start failed"):
            coordinator.start()

        assert coordinator._thread is not None
        assert coordinator._thread.ident is None
        coordinator.stop()
        assert coordinator._stop_event.is_set()
        assert not coordinator._thread.is_alive()

    def test_stop_after_preparation_without_checkpoint_skips_rebuild(self, tmp_path: Path):
        coordinator, _, _, _ = _make_coordinator(tmp_path, [])
        prepare = MagicMock(side_effect=coordinator._stop_event.set)
        rebuild = MagicMock()
        coordinator._start_or_resume = prepare
        coordinator._rebuild_loop = rebuild

        coordinator.run_sync()

        prepare.assert_called_once_with()
        rebuild.assert_not_called()
        assert coordinator.status()["status"] == "interrupted"
        assert not coordinator._state_path.exists()

    def test_stop_after_preparation_preserves_durable_checkpoint(self, tmp_path: Path):
        coordinator, _, _, _ = _make_coordinator(tmp_path, [])
        prepare = coordinator._start_or_resume
        rebuild = MagicMock()
        checkpoint_bytes: list[bytes] = []

        def prepare_then_stop() -> None:
            prepare()
            checkpoint_bytes.append(coordinator._state_path.read_bytes())
            coordinator._stop_event.set()

        coordinator._start_or_resume = prepare_then_stop
        coordinator._rebuild_loop = rebuild

        coordinator.run_sync()

        rebuild.assert_not_called()
        assert coordinator.status()["status"] == "interrupted"
        assert len(checkpoint_bytes) == 1
        assert coordinator._state_path.read_bytes() == checkpoint_bytes[0]

    def test_status_reports_failure_before_checkpoint(self, tmp_path: Path):
        coordinator, _, _, _ = _make_coordinator(tmp_path, [])
        coordinator._start_or_resume = MagicMock(side_effect=RuntimeError("private failure detail"))

        coordinator.run_sync()

        status = coordinator.status()
        assert status is not None
        assert status["status"] == "failed"
        assert status["active"] is False
        assert "private failure detail" not in str(status)

    def test_status_reports_failure_when_checkpoint_save_fails(self, tmp_path: Path, monkeypatch):
        coordinator, _, _, _ = _make_coordinator(tmp_path, [])

        def fail_save(self, path):
            raise OSError("private checkpoint path")

        monkeypatch.setattr(RebuildCheckpoint, "save", fail_save)
        coordinator.run_sync()

        status = coordinator.status()
        assert status is not None
        assert status["status"] == "failed"
        assert status["active"] is False
        assert "private checkpoint path" not in str(status)

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

    def test_sqlite_backfill_check_is_bounded_and_handles_states(self, tmp_path: Path):
        from core.indexing import SOURCE_ITEM_CONTENT_TEXT_VIEW, SOURCE_ITEM_VECTOR_TEXT_VIEW, build_index_entry
        from storage.sqlite import SQLiteStorageProvider

        storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'raw.db'}")
        assert raw_source_vector_backfill_needed(storage) is False

        ineligible = SourceItem(
            source_type="chat_message", source_id="ineligible", content_type="text/plain",
            content="too short", artifact_kind="tool_use_summary", id="ineligible",
        )
        storage.create_source_item(ineligible)
        storage.create_index_entry(build_index_entry(
            target_kind="source_item", target_id=ineligible.id, index_type="lexical",
            text_view=ineligible.content, text_view_name=SOURCE_ITEM_CONTENT_TEXT_VIEW,
        ))
        assert raw_source_vector_backfill_needed(storage) is False

        eligible = SourceItem(
            source_type="chat_message", source_id="eligible", content_type="text/plain",
            content="Unicode café source content that is long enough to embed.",
            artifact_kind="assistant_output", id="eligible",
        )
        storage.create_source_item(eligible)
        storage.create_index_entry(build_index_entry(
            target_kind="source_item", target_id=eligible.id, index_type="lexical",
            text_view=eligible.content, text_view_name=SOURCE_ITEM_CONTENT_TEXT_VIEW,
        ))
        storage.list_index_entries_by_type_page = MagicMock(
            side_effect=AssertionError("optimized check must not page lexical entries"),
        )
        assert raw_source_vector_backfill_needed(storage) is True

        storage.create_index_entry(build_index_entry(
            target_kind="source_item", target_id=eligible.id, index_type="vector",
            text_view=eligible.content, text_view_name=SOURCE_ITEM_VECTOR_TEXT_VIEW,
        ))
        assert raw_source_vector_backfill_needed(storage) is False

    def test_sqlite_backfill_check_skips_content_length_for_completed_vectors(self, tmp_path: Path):
        from sqlalchemy import event

        from core.indexing import SOURCE_ITEM_CONTENT_TEXT_VIEW, SOURCE_ITEM_VECTOR_TEXT_VIEW, build_index_entry
        from storage.sqlite import SQLiteStorageProvider

        storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'completed.db'}")
        for index in range(3):
            source = SourceItem(
                source_type="chat_message", source_id=f"completed-{index}",
                content_type="text/plain", content="Unicode café 完了済み source content is long enough.",
                artifact_kind="message", id=f"completed-{index}",
            )
            storage.create_source_item(source)
            storage.create_index_entry(build_index_entry(
                target_kind="source_item", target_id=source.id, index_type="lexical",
                text_view=source.content, text_view_name=SOURCE_ITEM_CONTENT_TEXT_VIEW,
            ))
            storage.create_index_entry(build_index_entry(
                target_kind="source_item", target_id=source.id, index_type="vector",
                text_view=source.content, text_view_name=SOURCE_ITEM_VECTOR_TEXT_VIEW,
            ))

        length_calls = []
        def counted_length(value):
            length = len(value)
            length_calls.append(length)
            return length

        storage._engine.dispose()
        event.listen(
            storage._engine, "connect",
            lambda dbapi_connection, _: dbapi_connection.create_function("length", 1, counted_length),
        )
        try:
            assert raw_source_vector_backfill_needed(storage) is False
            assert length_calls == []
        finally:
            storage.close()

    @pytest.mark.parametrize(
        (
            "artifact_kind", "content", "lexical_view", "lexical_target", "vector_view",
            "vector_target", "expected", "lexical_kind", "vector_kind", "vector_index_type",
        ),
        [
            ("message", "", "source_item.content", "source", None, None, False, "source_item", "source_item", "vector"),
            ("message", "é" * 39, "source_item.content", "source", None, None, False, "source_item", "source_item", "vector"),
            ("message", "é" * 40, "source_item.content", "source", None, None, True, "source_item", "source_item", "vector"),
            ("assistant_output", "é" * 40, "source_item.content", "source", None, None, True, "source_item", "source_item", "vector"),
            ("tool_use_summary", "é" * 40, "source_item.content", "source", None, None, False, "source_item", "source_item", "vector"),
            ("message", "é" * 40, "wrong.view", "source", None, None, False, "source_item", "source_item", "vector"),
            ("message", "é" * 40, "source_item.content", "orphan", None, None, False, "source_item", "source_item", "vector"),
            ("message", "é" * 40, "source_item.content", "source", "wrong.embedding", "source", True, "source_item", "source_item", "vector"),
            ("message", "é" * 40, "source_item.content", "source", "source_content.embedding", "other", True, "source_item", "source_item", "vector"),
            ("message", "é" * 40, "source_item.content", "source", "source_content.embedding", "source", False, "source_item", "source_item", "vector"),
            ("message", "é" * 40, "source_item.content", "source", None, None, False, "memory_object", "source_item", "vector"),
            ("message", "é" * 40, "source_item.content", "source", "source_content.embedding", "source", True, "source_item", "memory_object", "vector"),
            ("message", "é" * 40, "source_item.content", "source", "source_content.embedding", "source", True, "source_item", "source_item", "lexical"),
        ],
    )
    def test_sqlite_backfill_check_preserves_eligibility_states(
        self, tmp_path: Path, artifact_kind, content, lexical_view, lexical_target,
        vector_view, vector_target, expected, lexical_kind, vector_kind, vector_index_type,
    ):
        from core.indexing import build_index_entry
        from storage.sqlite import SQLiteStorageProvider

        storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'states.db'}")
        source = SourceItem(
            source_type="chat_message", source_id="source", content_type="text/plain",
            content=content, artifact_kind=artifact_kind, id="source",
        )
        storage.create_source_item(source)
        storage.create_index_entry(build_index_entry(
            target_kind=lexical_kind, target_id=lexical_target, index_type="lexical",
            text_view=content, text_view_name=lexical_view,
        ))
        if vector_view is not None:
            storage.create_index_entry(build_index_entry(
                target_kind=vector_kind, target_id=vector_target, index_type=vector_index_type,
                text_view=content, text_view_name=vector_view,
            ))
        assert raw_source_vector_backfill_needed(storage) is expected
        storage.close()

    def test_raw_source_backfill_needed_pages_and_handles_eligibility(self):
        sources = [
            SourceItem(
                source_type="chat_message", source_id="short", content_type="text/plain",
                content="short", artifact_kind="message", id="sourceshort",
            ),
            SourceItem(
                source_type="chat_message", source_id="unicode", content_type="text/plain",
                content="Unicode café source content that is long enough to embed.",
                artifact_kind="assistant_output", id="sourceunicode",
            ),
        ]
        lexical = [
            IndexEntry(
                id="lex-short", target_kind="source_item", target_id="sourceshort",
                index_type="lexical", text_view="short", text_view_name="source_item.content",
            ),
            IndexEntry(
                id="lex-unicode", target_kind="source_item", target_id="sourceunicode",
                index_type="lexical", text_view=sources[1].content,
                text_view_name="source_item.content",
            ),
        ]
        storage = MagicMock()
        calls = []
        def page(index_type, *, after_id=None, limit=None):
            calls.append((index_type, after_id, limit))
            entries = lexical if index_type == "lexical" else []
            if after_id is not None:
                entries = [entry for entry in entries if entry.id > after_id]
            return entries[:limit] if limit is not None else entries
        storage.list_index_entries_by_type_page.side_effect = page
        storage.get_source_item.side_effect = lambda source_id: next(
            source for source in sources if source.id == source_id
        )
        storage.find_index_entry.return_value = None

        assert raw_source_vector_backfill_needed(storage, batch_size=1) is True
        assert [call[1] for call in calls[:2]] == [None, "lex-short"]

        storage.find_index_entry.return_value = IndexEntry(
            target_kind="source_item", target_id=sources[1].id, index_type="vector",
            text_view=sources[1].content, text_view_name="source_content.embedding",
        )
        calls.clear()
        assert raw_source_vector_backfill_needed(storage, batch_size=2) is False

        storage.list_index_entries_by_type_page.side_effect = lambda *args, **kwargs: []
        assert raw_source_vector_backfill_needed(storage) is False
    def test_backfills_eligible_raw_vector_from_lexical_inventory(self, tmp_path: Path):
        source = SourceItem(
            source_type="chat_message",
            source_id="raw-1",
            content_type="text/plain",
            content="Unicode café source content that is long enough to embed.",
            artifact_kind="message",
        )
        lexical = IndexEntry(
            id="lex-0",
            target_kind="source_item",
            target_id=source.id,
            index_type="lexical",
            text_view=source.content,
            text_view_name="source_item.content",
        )
        vector_entries: list[IndexEntry] = []
        page_calls: list[tuple[str, str | None, int | None]] = []

        storage = MagicMock()
        def page(index_type, *, after_id=None, limit=None):
            page_calls.append((index_type, after_id, limit))
            entries = [lexical] if index_type == "lexical" else vector_entries
            if after_id is not None:
                entries = [entry for entry in entries if entry.id > after_id]
            return entries[:limit] if limit is not None else entries
        storage.list_index_entries_by_type_page.side_effect = page
        storage.list_raw_source_vector_backfill_page = None
        storage.get_source_item.return_value = source
        storage.get_memory_object.side_effect = KeyError
        storage.find_index_entry.side_effect = lambda **kwargs: next(
            (
                entry for entry in vector_entries
                if entry.target_id == kwargs["target_id"]
                and entry.index_type == kwargs["index_type"]
                and entry.text_view_name == kwargs["text_view_name"]
            ),
            None,
        )
        storage.create_index_entry.side_effect = vector_entries.append
        storage.count_index_entries_by_type.side_effect = lambda kind: sum(
            entry.index_type == kind for entry in vector_entries
        )

        provider = _make_stub_provider()
        coordinator = RebuildCoordinator(
            storage=storage,
            embedding_provider=provider,
            index_holder=VectorIndexHolder(),
            index_path=tmp_path / "live.usearch",
            target_model_name="test-model",
            target_dimensions=8,
            target_schema_version=1,
            reason="raw backfill",
            batch_size=1,
        )
        assert coordinator._inventory_raw_source_vectors() == 1
        assert coordinator._inventory_raw_source_vectors() == 0

        assert len(vector_entries) == 1
        assert vector_entries[0].text_view == source.content
        assert page_calls[0][0] == "lexical"
        assert page_calls[0][2] == 1

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

    def test_recover_interrupted_swap_cleans_old_files(self, tmp_path: Path):
        """Crash window 2: live files exist + .old remnants → forward cleanup."""
        from app.main import _recover_interrupted_swap

        index_path = tmp_path / "live.usearch"
        # Simulate: live files exist + .old remnants from interrupted swap
        index_path.write_bytes(b"live")
        Path(f"{index_path}.meta.json").write_text("{}", encoding="utf-8")
        Path(f"{index_path}.meta.json.old").write_text("{}", encoding="utf-8")
        Path(f"{index_path}.idmap.json.old").write_text("{}", encoding="utf-8")

        _recover_interrupted_swap(index_path)

        assert not Path(f"{index_path}.meta.json.old").exists()
        assert not Path(f"{index_path}.idmap.json.old").exists()
        # Live files untouched
        assert index_path.exists()
        assert Path(f"{index_path}.meta.json").exists()

    def test_recover_interrupted_swap_rollback_when_live_missing(self, tmp_path: Path):
        """Crash window 1: live files missing, .old has good copy → rollback."""
        from app.main import _recover_interrupted_swap

        index_path = tmp_path / "live.usearch"
        # Simulate: crash between live→.old rename and shadow→live move
        # .old files exist but live files do NOT
        Path(f"{index_path}.old").write_bytes(b"good index data")
        Path(f"{index_path}.meta.json.old").write_text('{"model_name":"test"}', encoding="utf-8")
        Path(f"{index_path}.idmap.json.old").write_text('{"entries":{}}', encoding="utf-8")

        _recover_interrupted_swap(index_path)

        # .old files should have been renamed back to live
        assert index_path.exists()
        assert index_path.read_bytes() == b"good index data"
        assert Path(f"{index_path}.meta.json").read_text(encoding="utf-8") == '{"model_name":"test"}'
        assert Path(f"{index_path}.idmap.json").read_text(encoding="utf-8") == '{"entries":{}}'
        # .old files should be gone
        assert not Path(f"{index_path}.old").exists()
        assert not Path(f"{index_path}.meta.json.old").exists()
        assert not Path(f"{index_path}.idmap.json.old").exists()

    def test_recover_interrupted_swap_noop_when_no_old_files(self, tmp_path: Path):
        """No .old files means nothing to recover."""
        from app.main import _recover_interrupted_swap

        index_path = tmp_path / "live.usearch"
        index_path.write_bytes(b"live")

        _recover_interrupted_swap(index_path)
        # No crash, no error
        assert index_path.exists()


class TestFullLifecycle:
    """Integration tests: real VectorIndex, full rebuild lifecycle."""

    def test_schema_change_rebuild_swaps_new_index(self, tmp_path: Path):
        """Schema version change: old index stays live, rebuild produces new, swap happens."""
        import time

        # 1. Create an "old" index at schema_version=1 with 10 entries
        index_path = tmp_path / "live.usearch"
        old_index = VectorIndex(index_path, dimensions=8, model_name="test-model", embedding_schema_version=1)
        for i in range(10):
            old_index.add(f"entry-{i}", [float(i % 3) / 3.0] * 8)
        old_index.save()

        # 2. Put old index in holder — it's "live"
        holder = VectorIndexHolder(old_index)
        assert holder.index.entry_count() == 10
        assert holder.index.embedding_schema_version == 1

        # 3. Set up storage + provider for rebuild
        entries = [_make_entry(f"entry-{i}", text=f"content {i}") for i in range(10)]
        storage = _make_stub_storage(entries)
        provider = _make_stub_provider(dimensions=8)

        # 4. Run rebuild targeting schema_version=2
        coordinator = RebuildCoordinator(
            storage=storage,
            embedding_provider=provider,
            index_holder=holder,
            index_path=index_path,
            target_model_name="test-model",
            target_dimensions=8,
            target_schema_version=2,
            reason="schema version: 1 -> 2",
            batch_size=3,
            shadow_save_interval=3,
        )
        coordinator.run_sync()

        # 5. Verify: new index has correct schema and entries
        assert holder.index.embedding_schema_version == 2
        assert holder.index.entry_count() == 10
        # Old index files replaced
        reloaded = VectorIndex.load(index_path)
        assert reloaded.embedding_schema_version == 2

    def test_concurrent_queries_during_background_rebuild(self, tmp_path: Path):
        """Queries against the old index work while rebuild runs in a background thread."""
        import time

        # Create old index with searchable vectors
        index_path = tmp_path / "live.usearch"
        old_index = VectorIndex(index_path, dimensions=8, model_name="test-model", embedding_schema_version=1)
        for i in range(20):
            old_index.add(f"entry-{i}", [0.5] * 8)
        old_index.save()

        holder = VectorIndexHolder(old_index)

        # Slow provider to ensure rebuild takes time
        provider = MagicMock()
        provider.dimensions.return_value = 8
        provider.model_name.return_value = "test-model"
        def slow_embed(texts, **kw):
            time.sleep(0.01)
            return [[0.5] * 8 for _ in texts]
        provider.embed.side_effect = slow_embed

        entries = [_make_entry(f"entry-{i}", text=f"content {i}") for i in range(20)]
        storage = _make_stub_storage(entries)

        coordinator = RebuildCoordinator(
            storage=storage,
            embedding_provider=provider,
            index_holder=holder,
            index_path=index_path,
            target_model_name="test-model",
            target_dimensions=8,
            target_schema_version=2,
            reason="test",
            batch_size=5,
            shadow_save_interval=5,
        )
        coordinator.start()

        # Run queries while rebuild is in progress
        query_results = []
        for _ in range(50):
            idx = holder.index
            if idx is not None:
                hits = idx.search([0.5] * 8, k=5)
                query_results.append(len(hits))
            time.sleep(0.005)

        coordinator.stop(timeout=10)

        # All queries returned results (old or new index, never None)
        assert all(r > 0 for r in query_results)
        assert len(query_results) == 50

    def test_stop_without_timeout_waits_for_worker_and_preserves_checkpoint(self, tmp_path: Path):
        entries = [_make_entry("e-0")]
        coordinator, _, _, provider = _make_coordinator(tmp_path, entries, batch_size=1)
        entered = threading.Event()
        release = threading.Event()

        def blocked_embed(texts, **kwargs):
            entered.set()
            assert release.wait(timeout=10)
            return [[0.1] * 8 for _ in texts]

        provider.embed.side_effect = blocked_embed
        coordinator.start()
        thread = coordinator._thread
        try:
            assert thread is not None
            assert entered.wait(timeout=10)
            coordinator.stop(timeout=0)
            assert thread.is_alive()
        finally:
            release.set()
            coordinator.stop(timeout=None)

        assert thread is not None
        assert not thread.is_alive()
        status = coordinator.status()
        assert status is not None
        assert status["status"] == "interrupted"
        checkpoint = RebuildCheckpoint.load(Path(f"{tmp_path / 'live.usearch'}.rebuild_state.json"))
        assert checkpoint is not None
        assert checkpoint.status == "in_progress"

    def test_stop_without_timeout_waits_during_inventory(self, tmp_path: Path):
        coordinator, holder, storage, _ = _make_coordinator(tmp_path, [])
        entered = threading.Event()
        release = threading.Event()

        def blocked_inventory(index_type, *, after_id=None, limit=None):
            entered.set()
            assert release.wait(timeout=10)
            return []

        storage.list_index_entries_by_type_page.side_effect = blocked_inventory
        coordinator.start()
        thread = coordinator._thread
        try:
            assert thread is not None
            assert entered.wait(timeout=10)
            coordinator.stop(timeout=0)
            assert thread.is_alive()
        finally:
            release.set()
            coordinator.stop(timeout=None)

        assert thread is not None
        assert not thread.is_alive()
        assert not holder.is_available
        status = coordinator.status()
        assert status is not None
        assert status["status"] == "interrupted"
        checkpoint = RebuildCheckpoint.load(Path(f"{tmp_path / 'live.usearch'}.rebuild_state.json"))
        assert checkpoint is not None
        assert checkpoint.status == "in_progress"

    def test_on_swap_callback_resets_reconcile(self, tmp_path: Path):
        """Verify the on_swap_callback mechanism works for reconcile state reset."""
        index_path = tmp_path / "live.usearch"
        old_index = VectorIndex(index_path, dimensions=8, model_name="test-model", embedding_schema_version=1)
        old_index.add("existing-1", [0.5] * 8)
        old_index.save()

        holder = VectorIndexHolder(old_index)
        entries = [_make_entry("entry-0", text="hello")]
        storage = _make_stub_storage(entries)
        provider = _make_stub_provider(dimensions=8)

        callback_invocations = []
        coordinator = RebuildCoordinator(
            storage=storage,
            embedding_provider=provider,
            index_holder=holder,
            index_path=index_path,
            target_model_name="test-model",
            target_dimensions=8,
            target_schema_version=2,
            reason="test",
            batch_size=10,
            shadow_save_interval=10,
            on_swap_callback=lambda: callback_invocations.append("reset"),
        )
        coordinator.run_sync()

        assert callback_invocations == ["reset"]
        assert holder.index.entry_count() == 1


def _create_raw_inventory_source(storage, source_id, *, content="é" * 40,
                                 artifact_kind="message", vector_id=None,
                                 lexical_view="source_item.content", target_kind="source_item"):
    source = SourceItem(id=source_id, source_type="chat_message", source_id=source_id,
                        content_type="text/plain", content=content, artifact_kind=artifact_kind)
    storage.create_source_item(source)
    storage.create_index_entry(IndexEntry(id=f"lex-{source_id}", target_kind=target_kind,
        target_id=source_id, index_type="lexical", text_view=content, text_view_name=lexical_view))
    if vector_id is not None:
        storage.create_index_entry(IndexEntry(id=vector_id, target_kind="source_item",
            target_id=source_id, index_type="vector", text_view=content,
            text_view_name="source_content.embedding"))
    return source


class TestFilteredRawSourceInventory:
    @pytest.mark.parametrize("failure", [None, ValueError("query failed")])
    def test_broken_optimized_page_does_not_fall_back(self, tmp_path, monkeypatch, failure):
        from storage.sqlite import SQLiteStorageProvider
        storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'broken.db'}")
        try:
            coordinator, _, _, _ = _make_coordinator(tmp_path, [], storage=storage)
            def page(**kwargs):
                if isinstance(failure, Exception):
                    raise failure
                return failure
            def forbidden_fallback(*args, **kwargs):
                pytest.fail("A broken optimized query must not silently fall back")
            monkeypatch.setattr(storage, "list_raw_source_vector_backfill_page", page)
            monkeypatch.setattr(storage, "list_index_entries_by_type_page", forbidden_fallback)
            with pytest.raises(ValueError if isinstance(failure, Exception) else TypeError):
                coordinator._inventory_raw_source_vectors()
        finally:
            storage.close()

    @pytest.mark.parametrize("missing_tail", [False, True])
    def test_sqlite_inventory_hydrates_only_missing_sources(self, tmp_path, monkeypatch, missing_tail):
        from sqlalchemy import event
        from storage.sqlite import SQLiteStorageProvider
        storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'inventory.db'}")
        try:
            for i in range(16):
                _create_raw_inventory_source(storage, f"source-{i:02d}",
                    vector_id=None if missing_tail and i == 15 else f"vector-{i:02d}")
            coordinator, _, _, _ = _make_coordinator(tmp_path, [], storage=storage)
            hydrated, statements = [], []
            original_get = storage.get_source_item
            def get_source(source_id):
                hydrated.append(source_id)
                return original_get(source_id)
            def capture(_conn, _cursor, statement, _params, _context, _many):
                statements.append(statement.split()[0])
            monkeypatch.setattr(storage, "get_source_item", get_source)
            event.listen(storage._engine, "before_cursor_execute", capture)
            try:
                assert coordinator._inventory_raw_source_vectors() == int(missing_tail)
            finally:
                event.remove(storage._engine, "before_cursor_execute", capture)
            assert hydrated == (["source-15"] if missing_tail else [])
            assert statements.count("SELECT") <= (4 if missing_tail else 1)
            assert storage.count_index_entries_by_type("vector") == 16
            assert coordinator._inventory_raw_source_vectors() == 0
        finally:
            storage.close()

    def test_candidate_pages_preserve_eligibility_and_duplicates(self, tmp_path):
        from core.indexing import SOURCE_ITEM_CONTENT_TEXT_VIEW, SOURCE_ITEM_VECTOR_TEXT_VIEW
        from sqlalchemy import select
        from storage.sqlite import SQLiteStorageProvider
        from storage.sqlite_schema import IndexEntryRecord
        storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'states.db'}")
        try:
            _create_raw_inventory_source(storage, "a-document", artifact_kind="document")
            _create_raw_inventory_source(storage, "b-short", content="é" * 39)
            _create_raw_inventory_source(storage, "b-short-nul", content="é" * 18 + "\x00" + "é" * 20)
            _create_raw_inventory_source(storage, "c-null", artifact_kind=None)
            _create_raw_inventory_source(storage, "d-view", lexical_view="other")
            _create_raw_inventory_source(storage, "e-kind", target_kind="memory_object")
            _create_raw_inventory_source(storage, "f-existing", vector_id="vector-f-1")
            storage.create_index_entry(IndexEntry(id="vector-f-2", target_kind="source_item",
                target_id="f-existing", index_type="vector", text_view="é" * 40,
                text_view_name=SOURCE_ITEM_VECTOR_TEXT_VIEW))
            _create_raw_inventory_source(storage, "g-eligible", artifact_kind="assistant_output")
            storage.create_index_entry(IndexEntry(id="lex-g-eligible-2", target_kind="source_item",
                target_id="g-eligible", index_type="lexical", text_view="é" * 40,
                text_view_name=SOURCE_ITEM_CONTENT_TEXT_VIEW))
            _create_raw_inventory_source(storage, "h-unicode", content="東京" * 20)
            _create_raw_inventory_source(storage, "i-nul", content="é" * 19 + "\x00" + "é" * 20)
            storage.create_index_entry(IndexEntry(id="vector-h-other", target_kind="source_item",
                target_id="h-unicode", index_type="vector", text_view="東京" * 20, text_view_name="other"))
            storage.create_index_entry(IndexEntry(id="lex-0-orphan", target_kind="source_item",
                target_id="absent", index_type="lexical", text_view="x" * 40,
                text_view_name=SOURCE_ITEM_CONTENT_TEXT_VIEW))
            ids, cursor = [], None
            while True:
                page = storage.list_raw_source_vector_backfill_page(
                    lexical_text_view_name=SOURCE_ITEM_CONTENT_TEXT_VIEW,
                    vector_text_view_name=SOURCE_ITEM_VECTOR_TEXT_VIEW, after_id=cursor, limit=1)
                if not page:
                    break
                ids.append(page[0].id)
                cursor = page[-1].id
            assert ids == ["lex-b-short", "lex-b-short-nul", "lex-g-eligible",
                           "lex-g-eligible-2", "lex-h-unicode", "lex-i-nul"]
            coordinator, _, _, _ = _make_coordinator(tmp_path, [], storage=storage, batch_size=1)
            assert coordinator._inventory_raw_source_vectors() == 3
            assert coordinator._inventory_raw_source_vectors() == 0
            with storage._engine.connect() as conn:
                targets = conn.execute(select(IndexEntryRecord.target_id).where(
                    IndexEntryRecord.index_type == "vector",
                    IndexEntryRecord.text_view_name == SOURCE_ITEM_VECTOR_TEXT_VIEW)).scalars().all()
            assert targets.count("g-eligible") == targets.count("h-unicode") == targets.count("i-nul") == 1
            assert "b-short" not in targets and "b-short-nul" not in targets
            assert targets.count("f-existing") == 2
        finally:
            storage.close()

    @pytest.mark.parametrize("race", ["delete", "ineligible", "vector"])
    def test_candidate_is_rechecked_after_selection(self, tmp_path, monkeypatch, race):
        from sqlalchemy import delete, update
        from storage.sqlite import SQLiteStorageProvider
        from storage.sqlite_schema import SourceItemRecord
        storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'race.db'}")
        try:
            _create_raw_inventory_source(storage, "source")
            original_page = storage.list_raw_source_vector_backfill_page
            raced = False
            def page(**kwargs):
                nonlocal raced
                result = original_page(**kwargs)
                if result and not raced:
                    raced = True
                    if race == "vector":
                        storage.create_index_entry(IndexEntry(id="raced-vector", target_kind="source_item",
                            target_id="source", index_type="vector", text_view="é" * 40,
                            text_view_name="source_content.embedding"))
                    else:
                        with storage._engine.begin() as conn:
                            statement = delete(SourceItemRecord) if race == "delete" else update(
                                SourceItemRecord).values(artifact_kind="document")
                            conn.execute(statement.where(SourceItemRecord.id == "source"))
                return result
            monkeypatch.setattr(storage, "list_raw_source_vector_backfill_page", page)
            coordinator, _, _, _ = _make_coordinator(tmp_path, [], storage=storage)
            assert coordinator._inventory_raw_source_vectors() == 0
            assert raced
            assert storage.count_index_entries_by_type("vector") == int(race == "vector")
        finally:
            storage.close()

    @pytest.mark.parametrize("when", ["before", "hydration"])
    def test_stopped_inventory_does_not_prepare_or_publish(self, tmp_path, monkeypatch, when):
        from storage.sqlite import SQLiteStorageProvider
        storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'stop.db'}")
        try:
            for name in ("a", "b"):
                _create_raw_inventory_source(storage, name)
            coordinator, holder, _, provider = _make_coordinator(tmp_path, [], storage=storage)
            old = VectorIndex.create_empty(coordinator._index_path, dimensions=8, model_name="test-model")
            old.add("old", [0.1] * 8)
            old.save()
            holder.swap(old)
            original_get, hydrated = storage.get_source_item, []
            def get_source(source_id):
                result = original_get(source_id)
                hydrated.append(source_id)
                coordinator.stop(timeout=0)
                return result
            monkeypatch.setattr(storage, "get_source_item", get_source)
            if when == "before":
                coordinator.stop(timeout=0)
            coordinator.run_sync()
            assert hydrated == ([] if when == "before" else ["a"])
            assert storage.count_index_entries_by_type("vector") == 0
            assert holder.index is old and holder.index.known_entry_ids() == frozenset({"old"})
            assert coordinator._shadow_index is None and not coordinator._state_path.exists()
            provider.embed.assert_not_called()
            # Terminal-state integration is supplied by the separately owned startup slice.
            assert coordinator.status()["status"] == "interrupted"
        finally:
            storage.close()

    def test_final_inventory_insert_cancel_resumes_before_old_cursor(self, tmp_path, monkeypatch):
        from dataclasses import replace
        from core import rebuild_coordinator as module
        from storage.sqlite import SQLiteStorageProvider
        storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'resume.db'}")
        try:
            _create_raw_inventory_source(storage, "old", vector_id="z-old")
            coordinator, holder, _, _ = _make_coordinator(tmp_path, [], storage=storage)
            coordinator._start_or_resume()
            assert coordinator._process_one_batch() == 1
            coordinator._shadow_index.save()
            checkpoint_bytes = coordinator._state_path.read_bytes()
            shadow = coordinator._shadow_dir / "index.usearch"
            shadow_files = (shadow, Path(f"{shadow}.idmap.json"), Path(f"{shadow}.meta.json"))
            shadow_bytes = [path.read_bytes() for path in shadow_files]
            assert RebuildCheckpoint.load(coordinator._state_path).last_processed_entry_id == "z-old"
            _create_raw_inventory_source(storage, "new")
            interrupted, _, _, _ = _make_coordinator(tmp_path, [], storage=storage)
            original_build, original_create = module.build_index_entry, storage.create_index_entry
            def build(**kwargs):
                return replace(original_build(**kwargs), id="a-repaired")
            def create(entry):
                original_create(entry)
                interrupted.stop(timeout=0)
            with monkeypatch.context() as patch:
                patch.setattr(module, "build_index_entry", build)
                patch.setattr(storage, "create_index_entry", create)
                interrupted.run_sync()
            assert storage.find_index_entry("source_item", "new", "vector", "source_content.embedding").id == "a-repaired"
            assert interrupted._shadow_index is None
            assert interrupted._state_path.read_bytes() == checkpoint_bytes
            assert [path.read_bytes() for path in shadow_files] == shadow_bytes
            resumed, resumed_holder, _, _ = _make_coordinator(tmp_path, [], storage=storage)
            resumed.run_sync()
            assert resumed.status()["status"] == "completed"
            assert resumed_holder.index.known_entry_ids() == frozenset({"a-repaired", "z-old"})
            assert RebuildCheckpoint.load(resumed._state_path).entry_count_total == 2
        finally:
            storage.close()
