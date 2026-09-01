"""Tests for SQLite snapshot persistence."""
from __future__ import annotations

import sqlite3 as stdlib_sqlite3
import threading
import time
from pathlib import Path

import pytest

from app.config import AppConfig, SnapshotConfig
from app.snapshot import (
    resolve_live_db_path,
    _validate_snapshot,
    create_snapshot,
    _is_dirty,
    _find_latest_snapshot,
    restore_snapshot,
    prune_old_snapshots,
    run_snapshot,
)


def _make_test_db(db_path: Path, *, wal: bool = False, rows: int = 10) -> None:
    """Create a real SQLite DB with a test table and N rows."""
    conn = stdlib_sqlite3.connect(str(db_path))
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
    for i in range(rows):
        conn.execute("INSERT INTO items VALUES (?, ?)", (i, f"row-{i}"))
    conn.commit()
    conn.close()


def _make_snapshot_with_data(snapshot_dir: Path, rows: int, *, label: str = "") -> Path:
    """Create a snapshot with specific data for restore tests."""
    temp_db = snapshot_dir / f"_temp_{label}.db"
    conn = stdlib_sqlite3.connect(str(temp_db))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
    for i in range(rows):
        conn.execute("INSERT INTO items VALUES (?, ?)", (i, f"{label}-row-{i}"))
    conn.commit()
    conn.close()
    time.sleep(1.1)  # ensure distinct second-granularity timestamps
    result = create_snapshot(str(temp_db), snapshot_dir)
    temp_db.unlink()
    return result


# === Tier 6: Config tests ===

def test_config_snapshot_defaults() -> None:
    config = AppConfig()
    assert config.snapshot.enabled is False
    assert config.snapshot.snapshot_path is None
    assert config.snapshot.interval_seconds == 60
    assert config.snapshot.max_snapshots == 5


def test_config_snapshot_from_toml(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
[snapshot]
enabled = true
snapshot_path = "/mnt/durable/snapshots"
interval_seconds = 30
max_snapshots = 10
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    config = AppConfig.from_env()
    assert config.snapshot.enabled is True
    assert config.snapshot.snapshot_path == "/mnt/durable/snapshots"
    assert config.snapshot.interval_seconds == 30
    assert config.snapshot.max_snapshots == 10


def test_config_snapshot_from_env(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("PALLIUM_SNAPSHOT_ENABLED", "true")
    monkeypatch.setenv("PALLIUM_SNAPSHOT_PATH", "/env/snapshots")
    monkeypatch.setenv("PALLIUM_SNAPSHOT_INTERVAL_SECONDS", "15")
    monkeypatch.setenv("PALLIUM_SNAPSHOT_MAX_SNAPSHOTS", "3")
    config = AppConfig.from_env()
    assert config.snapshot.enabled is True
    assert config.snapshot.snapshot_path == "/env/snapshots"
    assert config.snapshot.interval_seconds == 15
    assert config.snapshot.max_snapshots == 3


def test_config_snapshot_env_overrides_toml(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
[snapshot]
enabled = false
snapshot_path = "/toml/path"
interval_seconds = 120
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("PALLIUM_SNAPSHOT_ENABLED", "true")
    monkeypatch.setenv("PALLIUM_SNAPSHOT_PATH", "/env/path")
    config = AppConfig.from_env()
    assert config.snapshot.enabled is True
    assert config.snapshot.snapshot_path == "/env/path"
    assert config.snapshot.interval_seconds == 120  # TOML value kept (no env override)


# === Tier 1: Core snapshot function tests ===


def test_resolve_live_db_path_relative() -> None:
    assert resolve_live_db_path("sqlite:///./pallium.db") == "./pallium.db"


def test_resolve_live_db_path_absolute() -> None:
    assert resolve_live_db_path("sqlite:////var/data/pallium.db") == "/var/data/pallium.db"


def test_resolve_live_db_path_rejects_non_sqlite() -> None:
    with pytest.raises(ValueError, match="Expected sqlite:/// URL"):
        resolve_live_db_path("postgresql://localhost/db")


def test_validate_snapshot_good(tmp_path: Path) -> None:
    db_path = tmp_path / "good.db"
    conn = stdlib_sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    conn.close()
    assert _validate_snapshot(db_path) is True


def test_validate_snapshot_corrupt(tmp_path: Path) -> None:
    bad_path = tmp_path / "corrupt.db"
    bad_path.write_bytes(b"this is not a sqlite database at all")
    assert _validate_snapshot(bad_path) is False


def test_validate_snapshot_empty_file(tmp_path: Path) -> None:
    empty_path = tmp_path / "empty.db"
    empty_path.write_bytes(b"")
    assert _validate_snapshot(empty_path) is False


def test_snapshot_create_produces_valid_db(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, rows=20)
    result = create_snapshot(str(db_path), snapshot_dir)
    assert result is not None
    assert _validate_snapshot(result) is True
    conn = stdlib_sqlite3.connect(str(result))
    count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.close()
    assert count == 20


def test_snapshot_empty_database(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, rows=0)
    result = create_snapshot(str(db_path), snapshot_dir)
    assert result is not None
    assert _validate_snapshot(result) is True
    conn = stdlib_sqlite3.connect(str(result))
    count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.close()
    assert count == 0


def test_snapshot_data_integrity(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, rows=50)
    result = create_snapshot(str(db_path), snapshot_dir)
    assert result is not None
    conn = stdlib_sqlite3.connect(str(result))
    rows = conn.execute("SELECT id, value FROM items ORDER BY id").fetchall()
    conn.close()
    assert len(rows) == 50
    for i, (row_id, value) in enumerate(rows):
        assert row_id == i
        assert value == f"row-{i}"


def test_snapshot_atomic_rename(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, rows=5)
    create_snapshot(str(db_path), snapshot_dir)
    tmp_files = list(snapshot_dir.glob("*.tmp"))
    db_files = list(snapshot_dir.glob("pallium-*.db"))
    assert len(tmp_files) == 0
    assert len(db_files) == 1


def test_snapshot_all_at_once_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, rows=30)
    result = create_snapshot(str(db_path), snapshot_dir, pages_per_step=-1, sleep_between=0)
    assert result is not None
    assert _validate_snapshot(result) is True
    conn = stdlib_sqlite3.connect(str(result))
    count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.close()
    assert count == 30


def test_snapshot_failure_cleans_tmp(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, rows=5)

    import app.snapshot as snapshot_mod
    original_connect = snapshot_mod.sqlite3.connect

    class FailingConnection:
        """Wraps a real sqlite3 connection but makes backup() raise."""

        def __init__(self, real_conn):
            self._real = real_conn

        def backup(self, *args, **kwargs):
            raise RuntimeError("simulated backup failure")

        def close(self):
            self._real.close()

    call_count = 0

    def patched_connect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        conn = original_connect(*args, **kwargs)
        if call_count == 1:
            # This is the src connection; wrap it so backup() raises
            return FailingConnection(conn)
        return conn

    monkeypatch.setattr(snapshot_mod.sqlite3, "connect", patched_connect)
    with pytest.raises(RuntimeError, match="simulated backup failure"):
        create_snapshot(str(db_path), snapshot_dir)
    tmp_files = list(snapshot_dir.glob("*.tmp"))
    db_files = list(snapshot_dir.glob("pallium-*.db"))
    assert len(tmp_files) == 0
    assert len(db_files) == 0


def test_snapshot_fts5_in_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    conn = stdlib_sqlite3.connect(str(db_path))
    conn.execute("CREATE VIRTUAL TABLE docs USING fts5(title, body)")
    conn.execute("INSERT INTO docs VALUES ('Hello World', 'This is a test document')")
    conn.execute("INSERT INTO docs VALUES ('Snapshot Test', 'Testing FTS5 in snapshots')")
    conn.commit()
    conn.close()
    result = create_snapshot(str(db_path), snapshot_dir)
    assert result is not None
    conn = stdlib_sqlite3.connect(str(result))
    rows = conn.execute("SELECT title FROM docs WHERE docs MATCH 'snapshot'").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "Snapshot Test"


def test_snapshot_includes_all_tables(tmp_path: Path) -> None:
    from storage.sqlite import SQLiteStorageProvider
    from core.models import utc_now, new_id, SourceItem

    db_path = tmp_path / "pallium.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    storage = SQLiteStorageProvider(f"sqlite:///{db_path}")
    item = SourceItem(
        id=new_id(),
        source_type="test",
        source_id="snapshot-table-check",
        content_type="text",
        content="checking tables",
        use_case="agent_conversation_memory",
        processing_status="pending",
        created_at=utc_now(),
    )
    storage.create_source_item(item)
    result = create_snapshot(str(db_path), snapshot_dir)
    assert result is not None
    conn = stdlib_sqlite3.connect(str(result))
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    expected = {"source_items", "memory_objects", "relations", "index_entries"}
    assert expected.issubset(tables)


# === Dirty tracking tests ===


def test_dirty_tracking_no_db(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    assert _is_dirty(str(tmp_path / "nonexistent.db"), snapshot_dir) is False


def test_dirty_tracking_no_snapshot_yet(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, rows=1)
    assert _is_dirty(str(db_path), snapshot_dir) is True


def test_dirty_tracking_clean(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, rows=1)
    create_snapshot(str(db_path), snapshot_dir)
    time.sleep(0.1)
    assert _is_dirty(str(db_path), snapshot_dir) is False


def test_dirty_tracking_after_write(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, rows=1)
    create_snapshot(str(db_path), snapshot_dir)
    time.sleep(0.1)
    conn = stdlib_sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO items VALUES (999, 'new-row')")
    conn.commit()
    conn.close()
    assert _is_dirty(str(db_path), snapshot_dir) is True


def test_dirty_tracking_wal_modification(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(db_path, wal=True, rows=1)
    create_snapshot(str(db_path), snapshot_dir)
    time.sleep(0.1)
    conn = stdlib_sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("INSERT INTO items VALUES (999, 'wal-row')")
    conn.commit()
    conn.close()
    assert _is_dirty(str(db_path), snapshot_dir) is True


# === Restore tests ===


@pytest.mark.slow
def test_restore_newest_valid(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_snapshot_with_data(snapshot_dir, 5, label="older")
    _make_snapshot_with_data(snapshot_dir, 10, label="newer")
    live_db = tmp_path / "live.db"
    result = restore_snapshot(snapshot_dir, str(live_db))
    assert result is True
    conn = stdlib_sqlite3.connect(str(live_db))
    rows = conn.execute("SELECT value FROM items ORDER BY id").fetchall()
    conn.close()
    assert len(rows) == 10
    assert rows[0][0] == "newer-row-0"


@pytest.mark.slow
def test_restore_skips_corrupt_to_older(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_snapshot_with_data(snapshot_dir, 7, label="good")
    time.sleep(1.1)
    corrupt_path = snapshot_dir / "pallium-99991231T235959Z.db"
    corrupt_path.write_bytes(b"corrupt data here")
    live_db = tmp_path / "live.db"
    result = restore_snapshot(snapshot_dir, str(live_db))
    assert result is True
    conn = stdlib_sqlite3.connect(str(live_db))
    rows = conn.execute("SELECT value FROM items ORDER BY id").fetchall()
    conn.close()
    assert len(rows) == 7
    assert rows[0][0] == "good-row-0"


def test_restore_all_corrupt(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "pallium-20260101T000000Z.db").write_bytes(b"bad1")
    (snapshot_dir / "pallium-20260102T000000Z.db").write_bytes(b"bad2")
    live_db = tmp_path / "live.db"
    result = restore_snapshot(snapshot_dir, str(live_db))
    assert result is False
    assert not live_db.exists()


@pytest.mark.slow
def test_restore_skips_when_live_exists(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_snapshot_with_data(snapshot_dir, 5, label="snap")
    live_db = tmp_path / "live.db"
    _make_test_db(live_db, rows=100)
    result = restore_snapshot(snapshot_dir, str(live_db))
    assert result is False
    conn = stdlib_sqlite3.connect(str(live_db))
    count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.close()
    assert count == 100


def test_restore_no_snapshots(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    live_db = tmp_path / "live.db"
    result = restore_snapshot(snapshot_dir, str(live_db))
    assert result is False


@pytest.mark.slow
def test_restore_cleans_stale_wal_shm(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_snapshot_with_data(snapshot_dir, 3, label="clean")
    live_db = tmp_path / "live.db"
    wal_path = live_db.with_suffix(".db-wal")
    shm_path = live_db.with_suffix(".db-shm")
    wal_path.write_bytes(b"stale wal")
    shm_path.write_bytes(b"stale shm")
    # live.db must not exist for restore to proceed
    assert not live_db.exists()
    result = restore_snapshot(snapshot_dir, str(live_db))
    assert result is True
    assert not wal_path.exists()
    assert not shm_path.exists()


@pytest.mark.slow
def test_restore_creates_parent_dirs(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_snapshot_with_data(snapshot_dir, 2, label="nested")
    live_db = tmp_path / "deep" / "nested" / "path" / "live.db"
    result = restore_snapshot(snapshot_dir, str(live_db))
    assert result is True
    assert live_db.exists()


# === Prune tests ===


@pytest.mark.slow
def test_prune_keeps_n(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    db_path = tmp_path / "source.db"
    _make_test_db(db_path, rows=1)
    for i in range(8):
        # Create snapshots with distinct timestamps
        time.sleep(1.1)
        create_snapshot(str(db_path), snapshot_dir)
    snapshots_before = list(snapshot_dir.glob("pallium-*.db"))
    assert len(snapshots_before) == 8
    prune_old_snapshots(snapshot_dir, keep=5)
    remaining = sorted(snapshot_dir.glob("pallium-*.db"), key=lambda p: p.name, reverse=True)
    assert len(remaining) == 5
    # Verify the 5 newest survived
    all_sorted = sorted([p.name for p in snapshots_before], reverse=True)
    for i, snap in enumerate(remaining):
        assert snap.name == all_sorted[i]


@pytest.mark.slow
def test_prune_fewer_than_max(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    db_path = tmp_path / "source.db"
    _make_test_db(db_path, rows=1)
    for _ in range(3):
        time.sleep(1.1)
        create_snapshot(str(db_path), snapshot_dir)
    prune_old_snapshots(snapshot_dir, keep=5)
    remaining = list(snapshot_dir.glob("pallium-*.db"))
    assert len(remaining) == 3


def test_prune_ignores_non_snapshot_files(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "readme.txt").write_text("hello", encoding="utf-8")
    (snapshot_dir / "other.db").write_bytes(b"not a snapshot")
    db_path = tmp_path / "source.db"
    _make_test_db(db_path, rows=1)
    create_snapshot(str(db_path), snapshot_dir)
    prune_old_snapshots(snapshot_dir, keep=1)
    assert (snapshot_dir / "readme.txt").exists()
    assert (snapshot_dir / "other.db").exists()
    assert len(list(snapshot_dir.glob("pallium-*.db"))) == 1


# === WAL mode tests ===


def test_wal_mode_enabled(tmp_path: Path) -> None:
    from storage.sqlite import SQLiteStorageProvider

    db_path = tmp_path / "wal_test.db"
    SQLiteStorageProvider(f"sqlite:///{db_path}")
    conn = stdlib_sqlite3.connect(str(db_path))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_begin_immediate_under_wal(tmp_path: Path) -> None:
    from core.models import utc_now, new_id, SourceItem
    from storage.sqlite import SQLiteStorageProvider

    db_path = tmp_path / "wal_concurrent.db"
    storage = SQLiteStorageProvider(f"sqlite:///{db_path}")

    # Insert 10 pending items
    for i in range(10):
        item = SourceItem(
            id=new_id(),
            source_type="test",
            source_id=f"queue-{i}",
            content_type="text",
            content=f"content-{i}",
            use_case="agent_conversation_memory",
            processing_status="pending",
            created_at=utc_now(),
        )
        storage.create_source_item(item)

    claimed_ids: list[str] = []
    lock = threading.Lock()
    errors: list[Exception] = []

    def claim_worker(worker_name: str, iterations: int) -> None:
        for _ in range(iterations):
            try:
                result = storage.claim_next_source_item(
                    worker_id=worker_name,
                    lease_seconds=60,
                    max_attempts=3,
                )
                if result is not None:
                    with lock:
                        claimed_ids.append(result.id)
            except Exception as exc:
                with lock:
                    errors.append(exc)

    t1 = threading.Thread(target=claim_worker, args=("worker-a", 100))
    t2 = threading.Thread(target=claim_worker, args=("worker-b", 100))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert len(errors) == 0, f"Unexpected errors: {errors}"
    # No double-claims
    assert len(claimed_ids) == len(set(claimed_ids)), "Double-claims detected"
    # All 10 items claimed
    assert len(claimed_ids) == 10


# === Worker loop test ===


def test_snapshot_worker_loop_unit(tmp_path: Path, monkeypatch) -> None:
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    db_path = db_dir / "pallium.db"
    _make_test_db(db_path, rows=5)

    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        f"""
[snapshot]
enabled = true
snapshot_path = "{snapshot_dir.as_posix()}"
interval_seconds = 60
max_snapshots = 5
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("PALLIUM_SQLITE_URL", f"sqlite:///{db_path.as_posix()}")

    call_count = 0

    def counting_sleep(seconds: float) -> None:
        nonlocal call_count
        call_count += 1

    stop_after = 2

    def should_stop() -> bool:
        return call_count >= stop_after

    exit_code = run_snapshot(
        ["--interval-seconds", "1"],
        sleep_fn=counting_sleep,
        should_stop=should_stop,
        install_signal_handlers=False,
    )
    assert exit_code == 0
    snapshots = list(snapshot_dir.glob("pallium-*.db"))
    assert len(snapshots) >= 1


def test_paired_snapshot_restore_requires_committed_valid_pair(tmp_path: Path):
    snapshot_dir = tmp_path / "snapshots"; snapshot_dir.mkdir()
    main, relay = tmp_path / "main.db", tmp_path / "pallium-relay.db"
    _make_test_db(main, rows=2); _make_test_db(relay, rows=3)
    marker = create_snapshot({"main": str(main), "relay": str(relay)}, snapshot_dir)
    assert marker and marker.name.endswith(".manifest.json")
    restored_main, restored_relay = tmp_path / "restore-main.db", tmp_path / "restore-relay.db"
    assert restore_snapshot(snapshot_dir, {"main": str(restored_main), "relay": str(restored_relay)}) is True
    assert stdlib_sqlite3.connect(str(restored_main)).execute("SELECT count(*) FROM items").fetchone()[0] == 2
    assert stdlib_sqlite3.connect(str(restored_relay)).execute("SELECT count(*) FROM items").fetchone()[0] == 3


def test_paired_snapshot_without_manifest_is_ignored(tmp_path: Path):
    snapshot_dir = tmp_path / "snapshots"; snapshot_dir.mkdir()
    main, relay = tmp_path / "main.db", tmp_path / "pallium-relay.db"
    _make_test_db(main); _make_test_db(relay)
    marker = create_snapshot({"main": str(main), "relay": str(relay)}, snapshot_dir)
    marker.unlink()
    assert restore_snapshot(snapshot_dir, {"main": str(tmp_path / "m.db"), "relay": str(tmp_path / "r.db")}) is False


def test_paired_prune_removes_generations_as_a_unit(tmp_path: Path):
    snapshot_dir = tmp_path / "snapshots"; snapshot_dir.mkdir()
    main, relay = tmp_path / "main.db", tmp_path / "pallium-relay.db"
    _make_test_db(main); _make_test_db(relay)
    create_snapshot({"main": str(main), "relay": str(relay)}, snapshot_dir)
    time.sleep(0.01)
    create_snapshot({"main": str(main), "relay": str(relay)}, snapshot_dir)
    prune_old_snapshots(snapshot_dir, keep=1)
    assert len(list(snapshot_dir.glob("*.manifest.json"))) == 1
    assert len(list(snapshot_dir.glob("*-main.db"))) == 1
    assert len(list(snapshot_dir.glob("*-relay.db"))) == 1


def test_paired_restore_rejects_partial_live_state(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    main = tmp_path / "main.db"
    main.touch()
    with pytest.raises(RuntimeError, match="partial live database pair"):
        restore_snapshot(snapshot_dir, {"main": str(main), "relay": str(tmp_path / "relay.db")})


def test_legacy_single_snapshot_restores_then_migrates_relay(tmp_path: Path) -> None:
    from storage.sqlite import SQLiteStorageProvider

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    legacy_path = tmp_path / "legacy.db"
    legacy = SQLiteStorageProvider(f"sqlite:///{legacy_path}")
    legacy.relay_turn(
        runtime="codex", session_ref="legacy-session", container_ref="scope",
        actor_ref="actor", title=None, max_chars=1000, max_messages=10, lease_seconds=60,
    )
    legacy._engine.dispose()
    create_snapshot(str(legacy_path), snapshot_dir)
    legacy_path.unlink()

    relay_path = tmp_path / "relay.db"
    assert restore_snapshot(
        snapshot_dir, {"main": str(legacy_path), "relay": str(relay_path)}
    ) is True
    split = SQLiteStorageProvider(
        f"sqlite:///{legacy_path}", relay_database_url=f"sqlite:///{relay_path}"
    )
    sessions = split.relay_list_sessions(
        container_ref="scope", actor_ref="actor", runtime=None,
        include_inactive=True, recent_seconds=1,
    )
    assert [session["session_ref"] for session in sessions] == ["legacy-session"]
    split._engine.dispose()
    split._relay_engine.dispose()