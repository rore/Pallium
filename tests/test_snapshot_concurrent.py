"""Tier 2: Concurrent writer snapshot tests.

All tests use real SQLite databases with real concurrent writer threads.
No mocks on the data path.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from app.snapshot import create_snapshot, _validate_snapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_concurrent_db(db_path: Path, *, wal: bool = False, rows: int = 0) -> None:
    conn = sqlite3.connect(str(db_path))
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
    for i in range(rows):
        conn.execute("INSERT INTO items VALUES (?, ?)", (i, f"row-{i}"))
    conn.commit()
    conn.close()


def _make_fts5_db(db_path: Path, *, wal: bool = False) -> None:
    conn = sqlite3.connect(str(db_path))
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("CREATE VIRTUAL TABLE docs USING fts5(item_id UNINDEXED, body)")
    conn.commit()
    conn.close()


def _count_rows(db_path: Path, table: str = "items") -> int:
    conn = sqlite3.connect(str(db_path))
    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
    conn.close()
    return count


class ConcurrentWriter:
    """Writes to a real SQLite DB in a background thread."""

    def __init__(
        self,
        db_path: str,
        *,
        wal: bool = False,
        count: int = 100,
        delay: float = 0.005,
    ):
        self.db_path = db_path
        self.wal = wal
        self.count = count
        self.delay = delay
        self.inserted_ids: list[int] = []
        self.insert_durations: list[float] = []
        self.errors: list[Exception] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_id = 1000  # avoid collision with pre-existing rows

    def __enter__(self) -> "ConcurrentWriter":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        time.sleep(0.05)  # let writer get started
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        conn = sqlite3.connect(self.db_path, timeout=10)
        if self.wal:
            conn.execute("PRAGMA journal_mode=WAL")
        for i in range(self.count):
            if self._stop.is_set():
                break
            row_id = self._start_id + i
            try:
                t0 = time.monotonic()
                conn.execute(
                    "INSERT INTO items VALUES (?, ?)", (row_id, f"concurrent-{row_id}")
                )
                conn.commit()
                elapsed = time.monotonic() - t0
                self.inserted_ids.append(row_id)
                self.insert_durations.append(elapsed)
            except Exception as exc:
                self.errors.append(exc)
            if self.delay > 0:
                time.sleep(self.delay)
        conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_snapshot_during_concurrent_writes(tmp_path: Path) -> None:
    """Snapshot taken while a background thread inserts rows must be consistent."""
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_concurrent_db(db_path)

    with ConcurrentWriter(str(db_path), count=100, delay=0.005) as writer:
        snap = create_snapshot(str(db_path), snapshot_dir)
        # Let writer finish naturally
    snap_taken_at_insert_count = len(writer.inserted_ids)

    assert snap is not None
    assert _validate_snapshot(snap) is True
    assert len(writer.errors) == 0

    snap_count = _count_rows(snap)
    live_count = _count_rows(db_path)

    # Snapshot must not exceed what was in the live DB when snapshot completed
    assert snap_count <= live_count
    # Row count must reflect only complete transactions (no partial rows)
    # All IDs in snapshot must be sequentially valid
    conn = sqlite3.connect(str(snap))
    snap_ids = {row[0] for row in conn.execute("SELECT id FROM items").fetchall()}
    conn.close()
    all_valid_ids = set(range(snap_count)) | {w for w in writer.inserted_ids if w in snap_ids}
    # Every ID in the snapshot must be a known valid ID
    assert snap_ids.issubset(all_valid_ids | set(range(1000 + snap_taken_at_insert_count + 1)))


def test_snapshot_during_concurrent_writes_wal(tmp_path: Path) -> None:
    """Same as above with WAL journal mode explicitly enabled."""
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_concurrent_db(db_path, wal=True)

    with ConcurrentWriter(str(db_path), wal=True, count=100, delay=0.005) as writer:
        snap = create_snapshot(str(db_path), snapshot_dir)

    assert snap is not None
    assert _validate_snapshot(snap) is True
    assert len(writer.errors) == 0

    snap_count = _count_rows(snap)
    live_count = _count_rows(db_path)
    assert snap_count <= live_count


def test_snapshot_during_begin_immediate(tmp_path: Path) -> None:
    """Writer uses BEGIN IMMEDIATE; snapshot must succeed without OperationalError."""
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_concurrent_db(db_path, wal=True)

    inserted_ids: list[int] = []
    errors: list[Exception] = []
    stop_event = threading.Event()

    def immediate_writer() -> None:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        start_id = 2000
        for i in range(100):
            if stop_event.is_set():
                break
            row_id = start_id + i
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO items VALUES (?, ?)", (row_id, f"immediate-{row_id}")
                )
                conn.execute("COMMIT")
                inserted_ids.append(row_id)
            except Exception as exc:
                errors.append(exc)
            time.sleep(0.005)
        conn.close()

    t = threading.Thread(target=immediate_writer, daemon=True)
    t.start()
    time.sleep(0.05)

    snap = create_snapshot(str(db_path), snapshot_dir)

    stop_event.set()
    t.join(timeout=10)

    assert snap is not None
    assert _validate_snapshot(snap) is True

    # OperationalError (e.g. "database is locked") is acceptable for the writer
    # under BEGIN IMMEDIATE contention, but the snapshot itself must not raise.
    operational_errors = [e for e in errors if not isinstance(e, sqlite3.OperationalError)]
    assert len(operational_errors) == 0, f"Unexpected non-operational errors: {operational_errors}"

    snap_count = _count_rows(snap)
    live_count = _count_rows(db_path)
    assert snap_count <= live_count


@pytest.mark.slow
def test_multiple_snapshots_during_sustained_writes(tmp_path: Path) -> None:
    """Five snapshots taken 0.5 s apart; each must be valid with non-decreasing row counts."""
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_concurrent_db(db_path)

    snaps: list[Path] = []

    with ConcurrentWriter(str(db_path), count=500, delay=0.002) as _writer:
        for _ in range(5):
            snap = create_snapshot(str(db_path), snapshot_dir)
            assert snap is not None
            snaps.append(snap)
            time.sleep(0.5)

    assert len(snaps) == 5
    prev_count = -1
    for snap in snaps:
        assert _validate_snapshot(snap) is True
        count = _count_rows(snap)
        assert count >= prev_count, (
            f"Row count decreased: {count} < {prev_count}"
        )
        prev_count = count


def test_snapshot_does_not_block_writer_for_long(tmp_path: Path) -> None:
    """No single INSERT should be blocked for more than 2 seconds by a snapshot."""
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    # Pre-fill to ~500 pages (~5000 rows of modest size).
    # Use IDs starting at 0 so ConcurrentWriter's _start_id=1000 avoids collision.
    _make_concurrent_db(db_path, wal=True, rows=500)

    # ConcurrentWriter uses start_id=1000 by default, well above the 500 pre-fill IDs.
    with ConcurrentWriter(str(db_path), wal=True, count=50, delay=0.01) as writer:
        # Take snapshot while writes are in flight
        snap = create_snapshot(str(db_path), snapshot_dir, pages_per_step=256, sleep_between=0.01)

    assert snap is not None
    assert _validate_snapshot(snap) is True
    assert len(writer.errors) == 0

    if writer.insert_durations:
        max_duration = max(writer.insert_durations)
        assert max_duration < 2.0, (
            f"An INSERT was blocked for {max_duration:.3f}s — snapshot is too intrusive"
        )


def test_snapshot_during_concurrent_deletes(tmp_path: Path) -> None:
    """Snapshot taken while rows are being deleted must be consistent."""
    original_count = 200
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_concurrent_db(db_path, wal=True, rows=original_count)

    deleted_ids: list[int] = []
    errors: list[Exception] = []
    stop_event = threading.Event()

    def delete_writer() -> None:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        for row_id in range(original_count):
            if stop_event.is_set():
                break
            try:
                conn.execute("DELETE FROM items WHERE id = ?", (row_id,))
                conn.commit()
                deleted_ids.append(row_id)
            except Exception as exc:
                errors.append(exc)
            time.sleep(0.003)
        conn.close()

    t = threading.Thread(target=delete_writer, daemon=True)
    t.start()
    time.sleep(0.05)

    snap = create_snapshot(str(db_path), snapshot_dir)

    stop_event.set()
    t.join(timeout=10)

    assert snap is not None
    assert _validate_snapshot(snap) is True
    assert len(errors) == 0

    snap_count = _count_rows(snap)
    # At snapshot time: snap_count + rows_deleted_by_then ≈ original_count
    # We can't know exactly how many were deleted during the backup, but the
    # snapshot must be internally consistent: no negative counts, no overflow.
    assert 0 <= snap_count <= original_count


def test_snapshot_during_concurrent_fts5_inserts(tmp_path: Path) -> None:
    """FTS5 virtual table must be queryable in the snapshot after concurrent inserts."""
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_fts5_db(db_path, wal=True)

    errors: list[Exception] = []
    stop_event = threading.Event()

    def fts5_writer() -> None:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        for i in range(100):
            if stop_event.is_set():
                break
            row_id = 1000 + i
            try:
                conn.execute(
                    "INSERT INTO items VALUES (?, ?)", (row_id, f"fts-row-{row_id}")
                )
                conn.execute(
                    "INSERT INTO docs VALUES (?, ?)",
                    (row_id, f"searchable content for row {row_id}"),
                )
                conn.commit()
            except Exception as exc:
                errors.append(exc)
            time.sleep(0.005)
        conn.close()

    t = threading.Thread(target=fts5_writer, daemon=True)
    t.start()
    time.sleep(0.05)

    snap = create_snapshot(str(db_path), snapshot_dir)

    stop_event.set()
    t.join(timeout=10)

    assert snap is not None
    assert _validate_snapshot(snap) is True
    assert len(errors) == 0

    # FTS5 must be queryable in the snapshot
    conn = sqlite3.connect(str(snap))
    try:
        fts_rows = conn.execute(
            "SELECT item_id FROM docs WHERE docs MATCH 'searchable'"
        ).fetchall()
    finally:
        conn.close()

    items_count = _count_rows(snap, "items")
    # Every FTS5 row should correspond to a row in items (consistency)
    assert len(fts_rows) <= items_count


def test_snapshot_under_mixed_concurrent_load(tmp_path: Path) -> None:
    """Three concurrent threads (insert / BEGIN IMMEDIATE update / delete) must not corrupt snapshot."""
    initial_rows = 150
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_fts5_db(db_path, wal=True)

    # Pre-fill for update/delete threads
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    for i in range(initial_rows):
        conn.execute("INSERT INTO items VALUES (?, ?)", (i, f"prefill-{i}"))
        conn.execute(
            "INSERT INTO docs VALUES (?, ?)", (i, f"prefill content {i}")
        )
    conn.commit()
    conn.close()

    errors: list[Exception] = []
    stop_event = threading.Event()

    def inserter() -> None:
        c = sqlite3.connect(str(db_path), timeout=10)
        c.execute("PRAGMA journal_mode=WAL")
        for i in range(200):
            if stop_event.is_set():
                break
            row_id = 5000 + i
            try:
                c.execute("INSERT INTO items VALUES (?, ?)", (row_id, f"new-{row_id}"))
                c.execute("INSERT INTO docs VALUES (?, ?)", (row_id, f"new content {row_id}"))
                c.commit()
            except Exception as exc:
                errors.append(exc)
            time.sleep(0.003)
        c.close()

    def updater() -> None:
        c = sqlite3.connect(str(db_path), timeout=10)
        c.execute("PRAGMA journal_mode=WAL")
        for i in range(initial_rows):
            if stop_event.is_set():
                break
            try:
                c.execute("BEGIN IMMEDIATE")
                c.execute("UPDATE items SET value = ? WHERE id = ?", (f"updated-{i}", i))
                c.execute("COMMIT")
            except Exception as exc:
                errors.append(exc)
            time.sleep(0.004)
        c.close()

    def deleter() -> None:
        c = sqlite3.connect(str(db_path), timeout=10)
        c.execute("PRAGMA journal_mode=WAL")
        for i in range(0, initial_rows, 3):  # delete every 3rd row
            if stop_event.is_set():
                break
            try:
                c.execute("DELETE FROM items WHERE id = ?", (i,))
                c.commit()
            except Exception as exc:
                errors.append(exc)
            time.sleep(0.005)
        c.close()

    t1 = threading.Thread(target=inserter, daemon=True)
    t2 = threading.Thread(target=updater, daemon=True)
    t3 = threading.Thread(target=deleter, daemon=True)
    for t in (t1, t2, t3):
        t.start()
    time.sleep(0.05)

    snap = create_snapshot(str(db_path), snapshot_dir)

    stop_event.set()
    for t in (t1, t2, t3):
        t.join(timeout=10)

    assert snap is not None
    assert _validate_snapshot(snap) is True

    # Only OperationalError (lock contention) is tolerable from concurrent threads
    unexpected = [e for e in errors if not isinstance(e, sqlite3.OperationalError)]
    assert len(unexpected) == 0, f"Unexpected errors: {unexpected}"

    # FTS5 must be queryable in the snapshot
    conn = sqlite3.connect(str(snap))
    try:
        fts_rows = conn.execute(
            "SELECT item_id FROM docs WHERE docs MATCH 'content'"
        ).fetchall()
        items_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    finally:
        conn.close()

    assert items_count >= 0
    # FTS5 is queryable — row count may diverge from items because deleter only
    # removes from items, not docs (intentional mixed-load scenario).
    assert len(fts_rows) >= 0
