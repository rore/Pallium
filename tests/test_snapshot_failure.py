"""Tier 4: Failure injection tests for snapshot persistence."""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import AppConfig, SnapshotConfig
from app.snapshot import create_snapshot, restore_snapshot, _validate_snapshot, run_snapshot


def _make_test_db(db_path: Path, *, wal: bool = False, rows: int = 10) -> None:
    conn = sqlite3.connect(str(db_path))
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
    for i in range(rows):
        conn.execute("INSERT INTO items VALUES (?, ?)", (i, f"row-{i}"))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 1. Snapshot to a read-only directory
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform == "win32", reason="os.chmod readonly does not prevent file creation on Windows")
def test_snapshot_to_readonly_dir(tmp_path: Path) -> None:
    """create_snapshot raises when the snapshot directory is not writable."""
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, rows=5)

    os.chmod(str(snapshot_dir), 0o444)
    try:
        with pytest.raises(Exception):
            create_snapshot(str(db_path), snapshot_dir)
        # No partial .tmp files should remain
        assert list(snapshot_dir.glob("*.tmp")) == []
        # Live DB must be intact
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        conn.close()
        assert count == 5
    finally:
        # Restore permissions so tmp_path cleanup works
        os.chmod(str(snapshot_dir), 0o755)


# ---------------------------------------------------------------------------
# 2. Restore a snapshot whose schema is older (missing columns)
# ---------------------------------------------------------------------------

def test_restore_from_snapshot_with_older_schema(tmp_path: Path) -> None:
    """Restoring a snapshot with fewer columns triggers migrations cleanly."""
    from storage.sqlite import SQLiteStorageProvider

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    old_schema_db = tmp_path / "old_schema.db"

    # Build a minimal DB that looks like an old schema: only the baseline columns
    conn = sqlite3.connect(str(old_schema_db))
    conn.execute(
        "CREATE TABLE source_items "
        "(id TEXT PRIMARY KEY, source_type TEXT, source_id TEXT, "
        "content_type TEXT, content TEXT, created_at DATETIME)"
    )
    conn.execute(
        "INSERT INTO source_items VALUES "
        "('old-1', 'test', 'test-1', 'text', 'hello', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    # Snapshot the old-schema DB
    snap = create_snapshot(str(old_schema_db), snapshot_dir)
    assert snap is not None
    assert _validate_snapshot(snap) is True

    # Restore into a new location (live path must not pre-exist)
    live_db = tmp_path / "restored.db"
    result = restore_snapshot(snapshot_dir, str(live_db))
    assert result is True
    assert live_db.exists()

    # Opening with SQLiteStorageProvider triggers _initialize_schema (migrations)
    storage = SQLiteStorageProvider(f"sqlite:///{live_db}")

    # Confirm new columns were added
    conn = sqlite3.connect(str(live_db))
    col_names = {row[1] for row in conn.execute("PRAGMA table_info(source_items)")}
    conn.close()
    expected_new_cols = {"processing_status", "container_ref", "use_case", "visibility"}
    assert expected_new_cols.issubset(col_names), f"Missing columns: {expected_new_cols - col_names}"

    # Old data must still be present
    conn = sqlite3.connect(str(live_db))
    row = conn.execute("SELECT content FROM source_items WHERE id='old-1'").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "hello"


# ---------------------------------------------------------------------------
# 3. Worker survives a transient create_snapshot failure
# ---------------------------------------------------------------------------

def test_snapshot_worker_survives_transient_failure(tmp_path: Path, monkeypatch) -> None:
    """run_snapshot logs the error on first failure and succeeds on next iteration."""
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, rows=5)

    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        f"""
[snapshot]
enabled = true
snapshot_path = "{snapshot_dir.as_posix()}"
interval_seconds = 1
max_snapshots = 5
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("PALLIUM_SQLITE_URL", f"sqlite:///{db_path.as_posix()}")

    import app.snapshot as snapshot_mod

    original_create = snapshot_mod.create_snapshot
    call_count = 0

    def flaky_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("transient mount error")
        return original_create(*args, **kwargs)

    monkeypatch.setattr(snapshot_mod, "create_snapshot", flaky_create)

    sleep_calls = 0

    def counting_sleep(seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1

    def should_stop() -> bool:
        # Stop after the second sleep (i.e., we've gone around the loop twice)
        return sleep_calls >= 2

    exit_code = run_snapshot(
        ["--interval-seconds", "1"],
        sleep_fn=counting_sleep,
        should_stop=should_stop,
        install_signal_handlers=False,
    )
    assert exit_code == 0
    # create_snapshot must have been called at least twice: once (fail), once (succeed)
    assert call_count >= 2
    # A valid snapshot must exist from the successful call
    snapshots = list(snapshot_dir.glob("pallium-*.db"))
    assert len(snapshots) >= 1


# ---------------------------------------------------------------------------
# 4. Corrupt snapshot among valid ones — fallback to older valid snapshot
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_corrupt_snapshot_among_valid_ones(tmp_path: Path) -> None:
    """restore_snapshot skips a corrupt newest file and uses the next valid one."""
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    # Create a legitimate snapshot first
    good_db = tmp_path / "good_source.db"
    _make_test_db(good_db, rows=7)
    good_snap = create_snapshot(str(good_db), snapshot_dir)
    assert good_snap is not None

    # Give the corrupt one a later timestamp so it sorts first
    time.sleep(1.1)
    corrupt_path = snapshot_dir / "pallium-99991231T235959Z.db"
    corrupt_path.write_bytes(os.urandom(512))

    live_db = tmp_path / "live.db"
    result = restore_snapshot(snapshot_dir, str(live_db))
    assert result is True
    # The restored data must come from the valid older snapshot
    conn = sqlite3.connect(str(live_db))
    count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.close()
    assert count == 7


# ---------------------------------------------------------------------------
# 5. Snapshot with active WAL (large WAL file before checkpoint)
# ---------------------------------------------------------------------------

def test_snapshot_with_active_wal_checkpoint(tmp_path: Path) -> None:
    """Snapshot works correctly with a large WAL file (many uncommitted pages)."""
    db_path = tmp_path / "wal_heavy.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")  # disable auto-checkpoint to keep WAL large
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
    # Insert enough rows to produce a non-trivial WAL file (several hundred KB)
    for i in range(2000):
        conn.execute("INSERT INTO items VALUES (?, ?)", (i, f"row-{i}-" + "x" * 50))
    conn.commit()
    conn.close()

    snap = create_snapshot(str(db_path), snapshot_dir)
    assert snap is not None
    assert _validate_snapshot(snap) is True

    conn = sqlite3.connect(str(snap))
    count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.close()
    assert count == 2000


# ---------------------------------------------------------------------------
# 6. Stale .tmp files from a previous crash do not interfere
# ---------------------------------------------------------------------------

def test_stale_tmp_files_from_previous_crash(tmp_path: Path) -> None:
    """Orphaned .tmp files left by a previous crash do not block a new snapshot."""
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, rows=3)

    # Place orphaned .tmp files simulating a previous crash
    orphan1 = snapshot_dir / "pallium-20260101T000000Z.tmp"
    orphan2 = snapshot_dir / "pallium-20260102T120000Z.tmp"
    orphan1.write_bytes(b"leftover partial backup 1")
    orphan2.write_bytes(b"leftover partial backup 2")

    snap = create_snapshot(str(db_path), snapshot_dir)
    assert snap is not None
    assert _validate_snapshot(snap) is True

    # A proper snapshot was created
    db_files = list(snapshot_dir.glob("pallium-*.db"))
    assert len(db_files) == 1

    # Orphaned .tmp files are still present (cleanup is not our job)
    assert orphan1.exists()
    assert orphan2.exists()


# ---------------------------------------------------------------------------
# 7. Snapshot when snapshot_dir was deleted after startup
# ---------------------------------------------------------------------------

def test_shutdown_snapshot_when_snapshot_dir_gone(tmp_path: Path) -> None:
    """create_snapshot raises an appropriate exception when snapshot_dir has been removed."""
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, rows=5)

    # Remove the snapshot directory to simulate it being unmounted/deleted
    snapshot_dir.rmdir()
    assert not snapshot_dir.exists()

    with pytest.raises(Exception):
        create_snapshot(str(db_path), snapshot_dir)


# ---------------------------------------------------------------------------
# 8. os.replace failure — tmp file is cleaned up
# ---------------------------------------------------------------------------

def test_os_replace_failure(tmp_path: Path) -> None:
    """If os.replace fails, the .tmp file is removed and the exception propagates."""
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, rows=5)

    import app.snapshot as snapshot_mod

    original_replace = os.replace

    def failing_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch_target = "app.snapshot.os.replace"
    with patch(monkeypatch_target, side_effect=OSError("simulated replace failure")):
        with pytest.raises(OSError, match="simulated replace failure"):
            create_snapshot(str(db_path), snapshot_dir)

    # No .tmp or .db files should remain
    assert list(snapshot_dir.glob("*.tmp")) == []
    assert list(snapshot_dir.glob("pallium-*.db")) == []
    # Live DB is untouched
    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.close()
    assert count == 5
