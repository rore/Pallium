# SQLite Snapshot Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add periodic SQLite snapshot persistence so Pallium can run on ephemeral disk while durably backing up data to a configurable stable path.

**Architecture:** A new `app/snapshot.py` module contains all snapshot logic (create, restore, dirty-tracking, validation, pruning). The supervisor restores on startup before spawning children, spawns a snapshot worker as a new restartable child, and takes a best-effort shutdown snapshot. WAL mode is enabled in schema init for better concurrent read/write behavior. Configuration follows the existing `RetentionConfig` pattern via `[snapshot]` TOML section + env vars.

**Tech Stack:** Python 3.12, sqlite3 stdlib (backup API), pytest, real SQLite databases in tests (no mocks on the data path).

**Spec:** `docs/specs/2026-04-09-sqlite-snapshot-persistence-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `app/config.py` | Modify | Add `SnapshotConfig` dataclass, add to `AppConfig`, load from TOML + env vars |
| `app/snapshot.py` | Create | All snapshot logic: `create_snapshot`, `restore_snapshot`, `_is_dirty`, `_find_latest_snapshot`, `_validate_snapshot`, `_prune_old_snapshots`, `resolve_live_db_path`, `run_snapshot` worker entry point |
| `app/supervisor.py` | Modify | Restore before child spawn, spawn snapshot worker, shutdown snapshot, `build_snapshot_command` |
| `app/run.py` | Modify | Add `"snapshot"` CLI mode |
| `storage/sqlite_schema.py` | Modify | Add `PRAGMA journal_mode=WAL` |
| `scripts/clean-data.sh` | Modify | Also remove `*.db-wal` and `*.db-shm` files |
| `tests/test_snapshot.py` | Create | Tier 1 unit tests + Tier 6 config tests |
| `tests/test_snapshot_concurrent.py` | Create | Tier 2 concurrent writer tests |
| `tests/test_snapshot_lifecycle.py` | Create | Tier 3 multi-process lifecycle tests |
| `tests/test_snapshot_failure.py` | Create | Tier 4 failure injection tests |
| `tests/test_snapshot_roundtrip.py` | Create | Tier 5 data fidelity round-trip tests |
| `docs/context/architecture.md` | Modify | Document snapshot persistence capability |
| `docs/context/decisions.md` | Modify | Record WAL mode and snapshot mechanism decisions |

---

## Task 1: SnapshotConfig + AppConfig Integration

**Files:**
- Modify: `app/config.py`
- Create: `tests/test_snapshot.py` (first tests in this file)

---

- [ ] **Step 1.1: Write failing tests for SnapshotConfig parsing**

Create `tests/test_snapshot.py`:

```python
"""Tests for SQLite snapshot persistence."""
from __future__ import annotations

from pathlib import Path

from app.config import AppConfig, SnapshotConfig


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


def test_config_validation_enabled_no_path(monkeypatch, tmp_path: Path) -> None:
    """Snapshot enabled without snapshot_path should cause the worker to exit with error."""
    from app.snapshot import run_snapshot
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        """
[snapshot]
enabled = true
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
    # run_snapshot should return 0 (exit cleanly) since snapshot_path is None
    exit_code = run_snapshot(
        [],
        sleep_fn=lambda _: None,
        should_stop=lambda: True,
    )
    assert exit_code == 0  # graceful no-op when path is missing
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `python -m pytest tests/test_snapshot.py -x -q`
Expected: FAIL — `AppConfig` has no `snapshot` attribute.

- [ ] **Step 1.3: Implement SnapshotConfig and AppConfig integration**

In `app/config.py`, add the `SnapshotConfig` dataclass after `RetentionConfig`:

```python
@dataclass(frozen=True)
class SnapshotConfig:
    enabled: bool = False
    snapshot_path: str | None = None
    interval_seconds: int = 60
    max_snapshots: int = 5
```

Add `snapshot: SnapshotConfig = field(default_factory=SnapshotConfig)` to `AppConfig`.

In `AppConfig.from_env()`, add snapshot config loading following the same pattern as `RetentionConfig`:

```python
snapshot=SnapshotConfig(
    enabled=_resolve_bool_value(
        "PALLIUM_SNAPSHOT_ENABLED",
        env_values,
        _read_nested(config_data, "snapshot", "enabled"),
        False,
    ),
    snapshot_path=_resolve_global_value(
        "PALLIUM_SNAPSHOT_PATH",
        env_values,
        _as_optional_string(_read_nested(config_data, "snapshot", "snapshot_path")),
    ),
    interval_seconds=_resolve_int_setting(
        "PALLIUM_SNAPSHOT_INTERVAL_SECONDS",
        env_values,
        _read_nested(config_data, "snapshot", "interval_seconds"),
        60,
    ),
    max_snapshots=_resolve_int_setting(
        "PALLIUM_SNAPSHOT_MAX_SNAPSHOTS",
        env_values,
        _read_nested(config_data, "snapshot", "max_snapshots"),
        5,
    ),
),
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `python -m pytest tests/test_snapshot.py -x -q`
Expected: 4 passed.

- [ ] **Step 1.5: Commit**

```bash
git add app/config.py tests/test_snapshot.py
git commit -m "feat: add SnapshotConfig to AppConfig with TOML + env var loading"
```

---

## Task 2: Core Snapshot Functions

**Files:**
- Create: `app/snapshot.py`
- Modify: `tests/test_snapshot.py` (add Tier 1 tests)

This task implements all the pure functions in `app/snapshot.py` with TDD. The functions have no external dependencies — they operate on file paths and sqlite3 connections.

---

- [ ] **Step 2.1: Write failing tests for `resolve_live_db_path`**

Append to `tests/test_snapshot.py`:

```python
import pytest
from app.snapshot import resolve_live_db_path


def test_resolve_live_db_path_relative() -> None:
    assert resolve_live_db_path("sqlite:///./pallium.db") == "./pallium.db"


def test_resolve_live_db_path_absolute() -> None:
    assert resolve_live_db_path("sqlite:////var/data/pallium.db") == "/var/data/pallium.db"


def test_resolve_live_db_path_rejects_non_sqlite() -> None:
    with pytest.raises(ValueError, match="Expected sqlite:///"):
        resolve_live_db_path("postgresql://localhost/db")
```

- [ ] **Step 2.2: Implement `resolve_live_db_path` in `app/snapshot.py`**

Create `app/snapshot.py`:

```python
"""SQLite snapshot persistence for ephemeral storage deployments.

Provides periodic consistent snapshots of the live SQLite database to a
configurable durable path, automatic restore on startup, and best-effort
shutdown snapshot. Uses the SQLite backup API for non-blocking copies.
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable

from app.config import AppConfig, SnapshotConfig
from app.runtime_logging import emit_runtime_log
from app.signal_context import graceful_stop

logger = logging.getLogger(__name__)

BACKUP_PAGES_PER_STEP = 256   # ~1MB per step at 4KB page size
BACKUP_SLEEP_BETWEEN = 0.01   # 10ms yield between steps


def resolve_live_db_path(sqlite_url: str) -> str:
    """Extract the filesystem path from a SQLAlchemy SQLite URL."""
    prefix = "sqlite:///"
    if not sqlite_url.startswith(prefix):
        raise ValueError(f"Expected sqlite:/// URL, got: {sqlite_url}")
    return sqlite_url[len(prefix):]
```

- [ ] **Step 2.3: Run tests, verify pass**

Run: `python -m pytest tests/test_snapshot.py::test_resolve_live_db_path_relative tests/test_snapshot.py::test_resolve_live_db_path_absolute tests/test_snapshot.py::test_resolve_live_db_path_rejects_non_sqlite -x -q`
Expected: 3 passed.

- [ ] **Step 2.4: Write failing tests for `_validate_snapshot`**

Append to `tests/test_snapshot.py`:

```python
import sqlite3 as stdlib_sqlite3
from app.snapshot import _validate_snapshot


def test_validate_snapshot_good(tmp_path: Path) -> None:
    db_path = tmp_path / "good.db"
    conn = stdlib_sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    assert _validate_snapshot(db_path) is True


def test_validate_snapshot_corrupt(tmp_path: Path) -> None:
    db_path = tmp_path / "corrupt.db"
    db_path.write_bytes(b"this is not a sqlite database at all")
    assert _validate_snapshot(db_path) is False


def test_validate_snapshot_empty_file(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    db_path.write_bytes(b"")
    assert _validate_snapshot(db_path) is False
```

- [ ] **Step 2.5: Implement `_validate_snapshot`**

Add to `app/snapshot.py`:

```python
def _validate_snapshot(path: Path) -> bool:
    """Quick structural integrity check on a snapshot file."""
    try:
        conn = sqlite3.connect(str(path))
        result = conn.execute("PRAGMA quick_check").fetchone()
        conn.close()
        return result is not None and result[0] == "ok"
    except Exception:
        return False
```

- [ ] **Step 2.6: Run tests, verify pass**

Run: `python -m pytest tests/test_snapshot.py -k "validate" -x -q`
Expected: 3 passed.

- [ ] **Step 2.7: Write failing tests for `create_snapshot`**

Append to `tests/test_snapshot.py`:

```python
from app.snapshot import create_snapshot


def _make_test_db(db_path: Path, *, wal: bool = False, rows: int = 10) -> None:
    """Helper: create a real SQLite DB with a test table and N rows."""
    conn = stdlib_sqlite3.connect(str(db_path))
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
    for i in range(rows):
        conn.execute("INSERT INTO items VALUES (?, ?)", (i, f"row-{i}"))
    conn.commit()
    conn.close()


def test_snapshot_create_produces_valid_db(tmp_path: Path) -> None:
    live_db = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(live_db, rows=20)

    result = create_snapshot(str(live_db), snapshot_dir)

    assert result is not None
    assert result.exists()
    assert result.suffix == ".db"
    assert _validate_snapshot(result)
    # Verify data integrity
    conn = stdlib_sqlite3.connect(str(result))
    count = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    conn.close()
    assert count == 20


def test_snapshot_empty_database(tmp_path: Path) -> None:
    live_db = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(live_db, rows=0)

    result = create_snapshot(str(live_db), snapshot_dir)

    assert result is not None
    assert _validate_snapshot(result)
    conn = stdlib_sqlite3.connect(str(result))
    count = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    conn.close()
    assert count == 0


def test_snapshot_data_integrity(tmp_path: Path) -> None:
    live_db = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(live_db, rows=50)

    result = create_snapshot(str(live_db), snapshot_dir)

    conn = stdlib_sqlite3.connect(str(result))
    rows = conn.execute("SELECT id, value FROM items ORDER BY id").fetchall()
    conn.close()
    assert len(rows) == 50
    for i, (row_id, value) in enumerate(rows):
        assert row_id == i
        assert value == f"row-{i}"


def test_snapshot_atomic_rename(tmp_path: Path) -> None:
    live_db = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(live_db)

    create_snapshot(str(live_db), snapshot_dir)

    tmp_files = list(snapshot_dir.glob("*.tmp"))
    db_files = list(snapshot_dir.glob("pallium-*.db"))
    assert len(tmp_files) == 0
    assert len(db_files) == 1


def test_snapshot_all_at_once_mode(tmp_path: Path) -> None:
    live_db = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(live_db, rows=30)

    result = create_snapshot(str(live_db), snapshot_dir, pages_per_step=-1, sleep_between=0)

    assert result is not None
    assert _validate_snapshot(result)
    conn = stdlib_sqlite3.connect(str(result))
    count = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    conn.close()
    assert count == 30


def test_snapshot_failure_cleans_tmp(tmp_path: Path, monkeypatch) -> None:
    live_db = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(live_db)

    original_backup = sqlite3.Connection.backup

    def failing_backup(self, *args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(sqlite3.Connection, "backup", failing_backup)

    with pytest.raises(OSError, match="simulated disk failure"):
        create_snapshot(str(live_db), snapshot_dir)

    assert list(snapshot_dir.glob("*.tmp")) == []
    assert list(snapshot_dir.glob("pallium-*.db")) == []
```

- [ ] **Step 2.8: Implement `create_snapshot`**

Add to `app/snapshot.py`:

```python
def create_snapshot(
    live_db_path: str,
    snapshot_dir: Path,
    *,
    pages_per_step: int = BACKUP_PAGES_PER_STEP,
    sleep_between: float = BACKUP_SLEEP_BETWEEN,
) -> Path | None:
    """Create a consistent snapshot of the live database.

    Uses the SQLite backup API for non-blocking page-level copying.
    Writes to a .tmp file first, then atomically renames to .db.
    Returns the snapshot path on success.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final_path = snapshot_dir / f"pallium-{timestamp}.db"
    tmp_path = snapshot_dir / f"pallium-{timestamp}.tmp"

    src = sqlite3.connect(live_db_path, timeout=5)
    dst = sqlite3.connect(str(tmp_path))
    try:
        src.backup(dst, pages=pages_per_step, sleep=sleep_between)
        dst.close()
        src.close()
        os.replace(str(tmp_path), str(final_path))
        return final_path
    except BaseException:
        dst.close()
        src.close()
        tmp_path.unlink(missing_ok=True)
        raise
```

- [ ] **Step 2.9: Run tests, verify pass**

Run: `python -m pytest tests/test_snapshot.py -k "snapshot_create or snapshot_empty or snapshot_data_integrity or snapshot_atomic or snapshot_all_at_once or snapshot_failure" -x -q`
Expected: 6 passed.

- [ ] **Step 2.10: Write failing tests for dirty tracking**

Append to `tests/test_snapshot.py`:

```python
from app.snapshot import _is_dirty, _find_latest_snapshot


def test_dirty_tracking_no_db(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    assert _is_dirty(str(tmp_path / "nonexistent.db"), snapshot_dir) is False


def test_dirty_tracking_no_snapshot_yet(tmp_path: Path) -> None:
    live_db = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(live_db)
    assert _is_dirty(str(live_db), snapshot_dir) is True


def test_dirty_tracking_clean(tmp_path: Path) -> None:
    live_db = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(live_db)
    create_snapshot(str(live_db), snapshot_dir)
    # Give filesystem time to settle mtime
    time.sleep(0.1)
    assert _is_dirty(str(live_db), snapshot_dir) is False


def test_dirty_tracking_after_write(tmp_path: Path) -> None:
    live_db = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(live_db)
    create_snapshot(str(live_db), snapshot_dir)
    time.sleep(0.1)
    # Modify the DB
    conn = stdlib_sqlite3.connect(str(live_db))
    conn.execute("INSERT INTO items VALUES (999, 'new')")
    conn.commit()
    conn.close()
    assert _is_dirty(str(live_db), snapshot_dir) is True


def test_dirty_tracking_wal_modification(tmp_path: Path) -> None:
    live_db = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(live_db, wal=True)
    create_snapshot(str(live_db), snapshot_dir)
    time.sleep(0.1)
    # Write in WAL mode — updates WAL file, not necessarily the main DB
    conn = stdlib_sqlite3.connect(str(live_db))
    conn.execute("INSERT INTO items VALUES (999, 'wal-write')")
    conn.commit()
    conn.close()
    assert _is_dirty(str(live_db), snapshot_dir) is True
```

- [ ] **Step 2.11: Implement `_find_latest_snapshot` and `_is_dirty`**

Add to `app/snapshot.py`:

```python
def _find_latest_snapshot(snapshot_dir: Path) -> Path | None:
    """Find the newest snapshot file in the directory."""
    snapshots = sorted(snapshot_dir.glob("pallium-*.db"), key=lambda p: p.name, reverse=True)
    return snapshots[0] if snapshots else None


def _is_dirty(live_db_path: str, snapshot_dir: Path) -> bool:
    """Check if the live DB has been modified since the last snapshot."""
    db_path = Path(live_db_path)
    if not db_path.exists():
        return False
    db_mtime = db_path.stat().st_mtime

    # Also check WAL file — writes in WAL mode update the WAL, not the main DB
    wal_path = db_path.with_suffix(".db-wal")
    if wal_path.exists():
        db_mtime = max(db_mtime, wal_path.stat().st_mtime)

    latest = _find_latest_snapshot(snapshot_dir)
    if latest is None:
        return True
    return db_mtime > latest.stat().st_mtime
```

- [ ] **Step 2.12: Run dirty tracking tests, verify pass**

Run: `python -m pytest tests/test_snapshot.py -k "dirty" -x -q`
Expected: 5 passed.

- [ ] **Step 2.13: Write failing tests for `restore_snapshot`**

Append to `tests/test_snapshot.py`:

```python
from app.snapshot import restore_snapshot


def _make_snapshot_with_data(snapshot_dir: Path, rows: int, *, label: str = "") -> Path:
    """Helper: create a snapshot with specific data for restore tests."""
    temp_db = snapshot_dir / f"_temp_{label}.db"
    conn = stdlib_sqlite3.connect(str(temp_db))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
    for i in range(rows):
        conn.execute("INSERT INTO items VALUES (?, ?)", (i, f"{label}-row-{i}"))
    conn.commit()
    conn.close()
    # Snapshot it with a unique timestamp
    time.sleep(1.1)  # ensure distinct second-granularity timestamps
    result = create_snapshot(str(temp_db), snapshot_dir)
    temp_db.unlink()
    return result


def test_restore_newest_valid(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    live_db = tmp_path / "data" / "live.db"

    _make_snapshot_with_data(snapshot_dir, rows=5, label="old")
    _make_snapshot_with_data(snapshot_dir, rows=15, label="newest")

    restored = restore_snapshot(snapshot_dir, str(live_db))
    assert restored is True
    assert live_db.exists()
    conn = stdlib_sqlite3.connect(str(live_db))
    count = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    first_value = conn.execute("SELECT value FROM items WHERE id=0").fetchone()[0]
    conn.close()
    assert count == 15
    assert first_value == "newest-row-0"


def test_restore_skips_corrupt_to_older(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    live_db = tmp_path / "live.db"

    _make_snapshot_with_data(snapshot_dir, rows=5, label="good")
    newest = _make_snapshot_with_data(snapshot_dir, rows=10, label="bad")
    # Corrupt the newest
    newest.write_bytes(b"corrupt data")

    restored = restore_snapshot(snapshot_dir, str(live_db))
    assert restored is True
    conn = stdlib_sqlite3.connect(str(live_db))
    count = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    first_value = conn.execute("SELECT value FROM items WHERE id=0").fetchone()[0]
    conn.close()
    assert count == 5
    assert first_value == "good-row-0"


def test_restore_all_corrupt(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    live_db = tmp_path / "live.db"

    s1 = _make_snapshot_with_data(snapshot_dir, rows=5, label="a")
    s2 = _make_snapshot_with_data(snapshot_dir, rows=5, label="b")
    s1.write_bytes(b"corrupt")
    s2.write_bytes(b"corrupt")

    restored = restore_snapshot(snapshot_dir, str(live_db))
    assert restored is False
    assert not live_db.exists()


def test_restore_skips_when_live_exists(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    live_db = tmp_path / "live.db"
    _make_test_db(live_db, rows=100)
    _make_snapshot_with_data(snapshot_dir, rows=5, label="old")

    restored = restore_snapshot(snapshot_dir, str(live_db))
    assert restored is False
    # Live DB unchanged
    conn = stdlib_sqlite3.connect(str(live_db))
    count = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    conn.close()
    assert count == 100


def test_restore_no_snapshots(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    live_db = tmp_path / "live.db"

    restored = restore_snapshot(snapshot_dir, str(live_db))
    assert restored is False
    assert not live_db.exists()


def test_restore_cleans_stale_wal_shm(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    live_db = tmp_path / "live.db"
    wal_file = tmp_path / "live.db-wal"
    shm_file = tmp_path / "live.db-shm"
    wal_file.write_bytes(b"stale wal")
    shm_file.write_bytes(b"stale shm")

    _make_snapshot_with_data(snapshot_dir, rows=5, label="snap")

    restored = restore_snapshot(snapshot_dir, str(live_db))
    assert restored is True
    assert not wal_file.exists()
    assert not shm_file.exists()


def test_restore_creates_parent_dirs(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    live_db = tmp_path / "deep" / "nested" / "dir" / "live.db"

    _make_snapshot_with_data(snapshot_dir, rows=3, label="snap")

    restored = restore_snapshot(snapshot_dir, str(live_db))
    assert restored is True
    assert live_db.exists()
```

- [ ] **Step 2.14: Implement `restore_snapshot`**

Add to `app/snapshot.py`:

```python
def restore_snapshot(
    snapshot_dir: Path,
    live_db_path: str,
) -> bool:
    """Restore the newest valid snapshot to the live DB path.

    Returns True if a snapshot was restored, False if starting fresh.
    Skips restore if the live DB already exists (it has more recent data).
    """
    live_path = Path(live_db_path)
    if live_path.exists():
        logger.info("Live DB exists at %s — skipping snapshot restore", live_db_path)
        return False

    candidates = sorted(
        snapshot_dir.glob("pallium-*.db"),
        key=lambda p: p.name,
        reverse=True,
    )
    for candidate in candidates:
        if _validate_snapshot(candidate):
            live_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(candidate), str(live_path))
            # Clean stale WAL/SHM from previous runs
            live_path.with_suffix(".db-wal").unlink(missing_ok=True)
            live_path.with_suffix(".db-shm").unlink(missing_ok=True)
            logger.info("Restored snapshot %s → %s", candidate.name, live_db_path)
            return True
        else:
            logger.warning("Snapshot %s failed validation, trying next", candidate.name)

    logger.info("No valid snapshots found in %s — starting fresh", snapshot_dir)
    return False
```

- [ ] **Step 2.15: Run restore tests, verify pass**

Run: `python -m pytest tests/test_snapshot.py -k "restore" -x -q`
Expected: 7 passed.

- [ ] **Step 2.16: Write failing tests for `_prune_old_snapshots`**

Append to `tests/test_snapshot.py`:

```python
from app.snapshot import _prune_old_snapshots


def test_prune_keeps_n(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    # Create 8 fake snapshots
    for i in range(8):
        (snapshot_dir / f"pallium-2026040{i}T120000Z.db").write_text("x")
    _prune_old_snapshots(snapshot_dir, keep=5)
    remaining = sorted(snapshot_dir.glob("pallium-*.db"))
    assert len(remaining) == 5
    # Newest 5 kept (sorted by name, 03-07)
    assert remaining[0].name == "pallium-20260403T120000Z.db"
    assert remaining[-1].name == "pallium-20260407T120000Z.db"


def test_prune_fewer_than_max(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    for i in range(3):
        (snapshot_dir / f"pallium-2026040{i}T120000Z.db").write_text("x")
    _prune_old_snapshots(snapshot_dir, keep=5)
    assert len(list(snapshot_dir.glob("pallium-*.db"))) == 3


def test_prune_ignores_non_snapshot_files(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "readme.txt").write_text("keep me")
    (snapshot_dir / "other.db").write_text("not a pallium snapshot")
    for i in range(3):
        (snapshot_dir / f"pallium-2026040{i}T120000Z.db").write_text("x")
    _prune_old_snapshots(snapshot_dir, keep=2)
    assert (snapshot_dir / "readme.txt").exists()
    assert (snapshot_dir / "other.db").exists()
    assert len(list(snapshot_dir.glob("pallium-*.db"))) == 2
```

- [ ] **Step 2.17: Implement `_prune_old_snapshots`**

Add to `app/snapshot.py`:

```python
def _prune_old_snapshots(snapshot_dir: Path, *, keep: int) -> None:
    """Remove oldest snapshots, keeping the most recent `keep` files."""
    snapshots = sorted(
        snapshot_dir.glob("pallium-*.db"),
        key=lambda p: p.name,
        reverse=True,
    )
    for old in snapshots[keep:]:
        old.unlink(missing_ok=True)
```

- [ ] **Step 2.18: Run prune tests, verify pass**

Run: `python -m pytest tests/test_snapshot.py -k "prune" -x -q`
Expected: 3 passed.

- [ ] **Step 2.19: Write FTS5 snapshot test**

Append to `tests/test_snapshot.py`:

```python
def test_snapshot_fts5_in_snapshot(tmp_path: Path) -> None:
    live_db = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    conn = stdlib_sqlite3.connect(str(live_db))
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS lexical_fts USING fts5("
        "text_view, index_entry_id UNINDEXED, "
        "tokenize='unicode61 remove_diacritics 2')"
    )
    conn.execute(
        "INSERT INTO lexical_fts(text_view, index_entry_id) VALUES (?, ?)",
        ("the quick brown fox", "entry-1"),
    )
    conn.execute(
        "INSERT INTO lexical_fts(text_view, index_entry_id) VALUES (?, ?)",
        ("lazy dog sleeps", "entry-2"),
    )
    conn.commit()
    conn.close()

    result = create_snapshot(str(live_db), snapshot_dir)

    conn = stdlib_sqlite3.connect(str(result))
    # FTS5 table exists and is queryable
    matches = conn.execute(
        "SELECT index_entry_id FROM lexical_fts WHERE lexical_fts MATCH 'fox'"
    ).fetchall()
    conn.close()
    assert len(matches) == 1
    assert matches[0][0] == "entry-1"


def test_snapshot_includes_all_tables(tmp_path: Path) -> None:
    """Verify snapshot captures source_items, memory_objects, relations, index_entries, lexical_fts."""
    live_db = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    # Use real SQLiteStorageProvider to create all tables
    from storage.sqlite import SQLiteStorageProvider
    storage = SQLiteStorageProvider(f"sqlite:///{live_db}")
    # Insert a minimal source item to prove the table has data
    from core.models import utc_now, new_id
    from core.models import SourceItem
    item = SourceItem(
        id=new_id(),
        source_type="test",
        source_id="test-1",
        content_type="text",
        content="test content",
        created_at=utc_now(),
    )
    storage.create_source_item(item)

    result = create_snapshot(str(live_db), snapshot_dir)

    conn = stdlib_sqlite3.connect(str(result))
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()}
    conn.close()
    assert "source_items" in tables
    assert "memory_objects" in tables
    assert "relations" in tables
    assert "index_entries" in tables
    # FTS5 tables appear differently in sqlite_master
    fts_tables = {row[0] for row in stdlib_sqlite3.connect(str(result)).execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'lexical_fts%'"
    ).fetchall()}
    assert len(fts_tables) > 0  # FTS5 creates shadow tables
```

- [ ] **Step 2.20: Run all Tier 1 tests so far, verify pass**

Run: `python -m pytest tests/test_snapshot.py -x -q`
Expected: All passed (should be ~30 tests at this point).

- [ ] **Step 2.21: Commit**

```bash
git add app/snapshot.py tests/test_snapshot.py
git commit -m "feat: add core snapshot functions — create, restore, dirty tracking, validation, pruning"
```

---

## Task 3: WAL Mode

**Files:**
- Modify: `storage/sqlite_schema.py`
- Modify: `tests/test_snapshot.py` (add WAL tests)

---

- [ ] **Step 3.1: Write failing test for WAL mode**

Append to `tests/test_snapshot.py`:

```python
def test_wal_mode_enabled(tmp_path: Path) -> None:
    from storage.sqlite import SQLiteStorageProvider
    db_path = tmp_path / "wal_test.db"
    storage = SQLiteStorageProvider(f"sqlite:///{db_path}")
    conn = stdlib_sqlite3.connect(str(db_path))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_begin_immediate_under_wal(tmp_path: Path) -> None:
    """Verify BEGIN IMMEDIATE queue claiming serializes correctly under WAL mode."""
    from storage.sqlite import SQLiteStorageProvider
    from core.models import utc_now, new_id, SourceItem

    db_path = tmp_path / "wal_queue.db"
    storage = SQLiteStorageProvider(f"sqlite:///{db_path}")

    # Verify WAL is active
    conn = stdlib_sqlite3.connect(str(db_path))
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()

    # Create test source items
    now = utc_now()
    for i in range(10):
        item = SourceItem(
            id=new_id(),
            source_type="test",
            source_id=f"queue-{i}",
            content_type="text",
            content=f"content-{i}",
            use_case="agent_conversation_memory",
            processing_status="pending",
            created_at=now,
        )
        storage.create_source_item(item)

    # Two threads claiming concurrently
    import threading
    claimed_ids: list[list[str]] = [[], []]
    errors: list[Exception] = []

    def claim_loop(worker_idx: int) -> None:
        try:
            for _ in range(10):
                result = storage.claim_next_source_item(
                    worker_id=f"worker-{worker_idx}",
                    lease_seconds=60,
                    max_attempts=3,
                )
                if result is not None:
                    claimed_ids[worker_idx].append(result.id)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=claim_loop, args=(0,))
    t2 = threading.Thread(target=claim_loop, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"Concurrent claim errors: {errors}"
    all_claimed = claimed_ids[0] + claimed_ids[1]
    # No double claims
    assert len(all_claimed) == len(set(all_claimed))
    # All 10 items claimed
    assert len(all_claimed) == 10
```

- [ ] **Step 3.2: Implement WAL mode in schema init**

In `storage/sqlite_schema.py`, add WAL PRAGMA at the beginning of `_initialize_schema`:

```python
def _initialize_schema(self) -> None:
    with self._schema_initialization_lock():
        # Enable WAL mode for concurrent read/write access.
        # WAL persists in the database file header — only needs to be set once.
        with self._engine.begin() as connection:
            connection.execute(text("PRAGMA journal_mode=WAL"))
        Base.metadata.create_all(self._engine)
        self._ensure_source_item_columns()
        # ... rest unchanged ...
```

- [ ] **Step 3.3: Run WAL tests, verify pass**

Run: `python -m pytest tests/test_snapshot.py -k "wal or begin_immediate" -x -q`
Expected: 2 passed.

- [ ] **Step 3.4: Run full existing test suite to check for regressions**

Run: `python -m pytest tests/ -x -q --timeout=60`
Expected: All existing tests pass. WAL mode is backward-compatible.

- [ ] **Step 3.5: Commit**

```bash
git add storage/sqlite_schema.py tests/test_snapshot.py
git commit -m "feat: enable WAL journal mode for concurrent read/write access"
```

---

## Task 4: Snapshot Worker Process

**Files:**
- Modify: `app/snapshot.py`
- Modify: `tests/test_snapshot.py`

---

- [ ] **Step 4.1: Write failing test for snapshot worker loop**

Append to `tests/test_snapshot.py`:

```python
from app.snapshot import run_snapshot


def test_snapshot_worker_loop_unit(tmp_path: Path, monkeypatch) -> None:
    live_db = tmp_path / "live.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    _make_test_db(live_db, rows=5)

    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        f"""
[storage]
sqlite_url = "sqlite:///{live_db}"

[snapshot]
enabled = true
snapshot_path = "{snapshot_dir}"
interval_seconds = 1
max_snapshots = 3
""".replace("\\", "/"),
        encoding="utf-8",
    )
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))

    iteration_count = 0

    def counting_sleep(seconds):
        nonlocal iteration_count
        iteration_count += 1

    exit_code = run_snapshot(
        ["--interval-seconds", "1"],
        sleep_fn=counting_sleep,
        should_stop=lambda: iteration_count >= 2,
    )

    assert exit_code == 0
    snapshots = list(snapshot_dir.glob("pallium-*.db"))
    assert len(snapshots) >= 1  # at least one snapshot taken
```

- [ ] **Step 4.2: Implement `run_snapshot` worker entry point**

Add to `app/snapshot.py`:

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Pallium snapshot worker")
    parser.add_argument("--interval-seconds", type=int, default=None)
    return parser


def run_snapshot(
    args: list[str] | None = None,
    *,
    config: AppConfig | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] | None = None,
    install_signal_handlers: bool | None = None,
) -> int:
    parsed = build_parser().parse_args(args)
    resolved_config = config or AppConfig.from_env()
    snapshot_config = resolved_config.snapshot

    if not snapshot_config.enabled or not snapshot_config.snapshot_path:
        return 0

    live_db_path = resolve_live_db_path(resolved_config.sqlite_url)
    snapshot_dir = Path(snapshot_config.snapshot_path)
    interval = parsed.interval_seconds or snapshot_config.interval_seconds

    if not snapshot_dir.is_dir():
        emit_runtime_log("snapshot", f"snapshot_path does not exist: {snapshot_dir}", stderr=True)
        return 1

    with graceful_stop(install=install_signal_handlers) as stop:
        while True:
            if stop.requested or (should_stop is not None and should_stop()):
                break
            try:
                if _is_dirty(live_db_path, snapshot_dir):
                    path = create_snapshot(live_db_path, snapshot_dir)
                    if path is not None:
                        emit_runtime_log("snapshot", f"created {path.name}")
                        _prune_old_snapshots(snapshot_dir, keep=snapshot_config.max_snapshots)
            except Exception as exc:
                emit_runtime_log("snapshot", f"failed: {exc}", stderr=True)
            if stop.requested or (should_stop is not None and should_stop()):
                break
            sleep_fn(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_snapshot())
```

- [ ] **Step 4.3: Run worker loop test, verify pass**

Run: `python -m pytest tests/test_snapshot.py::test_snapshot_worker_loop_unit -x -q`
Expected: 1 passed.

- [ ] **Step 4.4: Commit**

```bash
git add app/snapshot.py tests/test_snapshot.py
git commit -m "feat: add snapshot worker process with poll loop and graceful stop"
```

---

## Task 5: Supervisor Integration

**Files:**
- Modify: `app/supervisor.py`
- Modify: `tests/test_async_worker.py` (supervisor tests are here)

---

- [ ] **Step 5.1: Write failing tests for supervisor snapshot integration**

Append to `tests/test_async_worker.py` (where existing supervisor tests live):

```python
def test_supervisor_spawns_snapshot_worker_when_enabled(capsys, tmp_path, monkeypatch) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text(
        f"""
[snapshot]
enabled = true
snapshot_path = "{snapshot_dir}"
interval_seconds = 60
""".replace("\\", "/"),
        encoding="utf-8",
    )
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))

    started: list[FakeProcess] = []
    def popen_factory(command, cwd=None):
        process = FakeProcess(command, cwd=cwd)
        started.append(process)
        return process

    exit_code = supervisor.run_supervisor(
        ['--host', '127.0.0.1', '--port', '8099', '--processors', '1', '--cleaners', '0'],
        popen_factory=popen_factory,
        sleep_fn=lambda _: None,
        should_stop=lambda: True,
    )

    assert exit_code == 0
    snapshot_processes = [p for p in started if 'app.snapshot' in ' '.join(p.command)]
    assert len(snapshot_processes) == 1
    assert all(p.terminated for p in started)


def test_supervisor_does_not_spawn_snapshot_when_disabled(capsys, tmp_path, monkeypatch) -> None:
    config_file = tmp_path / "pallium.local.toml"
    config_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))

    started: list[FakeProcess] = []
    def popen_factory(command, cwd=None):
        process = FakeProcess(command, cwd=cwd)
        started.append(process)
        return process

    exit_code = supervisor.run_supervisor(
        ['--host', '127.0.0.1', '--port', '8099', '--processors', '1', '--cleaners', '0'],
        popen_factory=popen_factory,
        sleep_fn=lambda _: None,
        should_stop=lambda: True,
    )

    assert exit_code == 0
    snapshot_processes = [p for p in started if 'app.snapshot' in ' '.join(p.command)]
    assert len(snapshot_processes) == 0
```

- [ ] **Step 5.2: Implement supervisor snapshot integration**

Modify `app/supervisor.py`:

1. Add imports at top:
```python
from app.config import AppConfig
from app.snapshot import resolve_live_db_path, restore_snapshot, create_snapshot, _prune_old_snapshots
```

2. Add `build_snapshot_command`:
```python
def build_snapshot_command(interval_seconds: int) -> list[str]:
    return [sys.executable, "-m", "app.snapshot", "--interval-seconds", str(interval_seconds)]
```

3. In `run_supervisor()`, after parsing args, load config and handle restore + snapshot worker spawn:

At the beginning of `run_supervisor`, after parsing and validation:
```python
    # Load config for snapshot features
    config = AppConfig.from_env()
    snapshot_config = config.snapshot

    # Restore snapshot before spawning any children
    if snapshot_config.enabled and snapshot_config.snapshot_path:
        snapshot_dir = Path(snapshot_config.snapshot_path)
        if snapshot_dir.is_dir():
            try:
                live_db_path = resolve_live_db_path(config.sqlite_url)
                restored = restore_snapshot(snapshot_dir, live_db_path)
                if restored:
                    emit_runtime_log("supervisor", f"restored snapshot to {live_db_path}")
                else:
                    emit_runtime_log("supervisor", "snapshot restore skipped (live DB exists or no snapshots)")
            except Exception as exc:
                emit_runtime_log("supervisor", f"snapshot restore failed: {exc}", stderr=True)
```

After spawning cleaners, add snapshot worker:
```python
        if snapshot_config.enabled and snapshot_config.snapshot_path:
            cmd = build_snapshot_command(snapshot_config.interval_seconds)
            proc = popen_factory(cmd, cwd=os.getcwd())
            slots.append(_ManagedSlot(
                command=cmd,
                label="snapshot",
                process=proc,
                restartable=True,
                restart_times=[],
            ))
            emit_runtime_log("supervisor", f"started snapshot pid={proc.pid}")
```

In the `finally` block, after terminating and waiting for all children, add shutdown snapshot:
```python
            # Best-effort shutdown snapshot
            if snapshot_config.enabled and snapshot_config.snapshot_path:
                try:
                    snapshot_dir = Path(snapshot_config.snapshot_path)
                    live_db_path = resolve_live_db_path(config.sqlite_url)
                    path = create_snapshot(
                        live_db_path, snapshot_dir,
                        pages_per_step=-1, sleep_between=0,
                    )
                    if path is not None:
                        emit_runtime_log("supervisor", f"shutdown snapshot: {path.name}")
                        _prune_old_snapshots(snapshot_dir, keep=snapshot_config.max_snapshots)
                except Exception as exc:
                    emit_runtime_log(
                        "supervisor",
                        f"shutdown snapshot failed (data loss window ~{snapshot_config.interval_seconds}s): {exc}",
                        stderr=True,
                    )
```

Also add `from pathlib import Path` to imports.

- [ ] **Step 5.3: Run supervisor tests, verify pass**

Run: `python -m pytest tests/test_async_worker.py -k "snapshot" -x -q`
Expected: 2 passed.

- [ ] **Step 5.4: Run all existing supervisor tests for regression**

Run: `python -m pytest tests/test_async_worker.py -k "supervisor" -x -q`
Expected: All pass (existing tests should not break — they don't set snapshot config).

- [ ] **Step 5.5: Commit**

```bash
git add app/supervisor.py tests/test_async_worker.py
git commit -m "feat: supervisor snapshot integration — restore, spawn worker, shutdown snapshot"
```

---

## Task 6: CLI Mode + clean-data.sh

**Files:**
- Modify: `app/run.py`
- Modify: `scripts/clean-data.sh`
- Modify: `tests/test_app_run.py`

---

- [ ] **Step 6.1: Write failing test for CLI snapshot mode**

Append to `tests/test_app_run.py`:

```python
def test_run_snapshot_mode_invokes_snapshot(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_snapshot(args=None, config=None):
        captured["called"] = True
        return 0

    from app import snapshot as snapshot_mod
    monkeypatch.setattr(snapshot_mod, "run_snapshot", fake_run_snapshot)

    # Need to patch the import inside app.run
    import app.run as run_mod
    original_run = run_mod.run

    def patched_run(args):
        # The actual run function does a lazy import of run_snapshot
        return original_run(args)

    exit_code = app_run.run(["snapshot"])
    assert exit_code == 0
```

Note: The actual implementation may need the test adjusted slightly depending on how the import works. The key is: `python -m app.run snapshot` dispatches to `run_snapshot`.

- [ ] **Step 6.2: Add snapshot mode to `app/run.py`**

In `build_parser()`, add `"snapshot"` to the choices:
```python
choices=("all", "serve", "mcp", "processor", "cleaner", "snapshot", "rebuild-vector-index", "download-embedding-model"),
```

In `run()`, add the snapshot dispatch before `rebuild-vector-index`:
```python
    if parsed.mode == "snapshot":
        from app.snapshot import run_snapshot
        return run_snapshot()
```

- [ ] **Step 6.3: Update `scripts/clean-data.sh`**

Add WAL and SHM cleanup:
```bash
rm -f pallium.db pallium.db.schema.lock pallium.db-wal pallium.db-shm .pallium-schema-init.lock
```

- [ ] **Step 6.4: Run CLI test, verify pass**

Run: `python -m pytest tests/test_app_run.py -x -q`
Expected: All pass.

- [ ] **Step 6.5: Commit**

```bash
git add app/run.py scripts/clean-data.sh tests/test_app_run.py
git commit -m "feat: add snapshot CLI mode and WAL sidecar cleanup in clean-data.sh"
```

---

## Task 7: Tier 2 — Concurrent Writer Tests

**Files:**
- Create: `tests/test_snapshot_concurrent.py`

These tests use real SQLite databases with concurrent writer threads. They are the most important tests for validating that the backup API works correctly under production-like load.

---

- [ ] **Step 7.1: Create concurrent test file with ConcurrentWriter harness**

Create `tests/test_snapshot_concurrent.py` with the test harness and all Tier 2 tests. The key tests:

1. `test_snapshot_during_concurrent_writes` — single writer thread, 100 inserts, snapshot mid-writes
2. `test_snapshot_during_concurrent_writes_wal` — same with explicit WAL mode
3. `test_snapshot_during_begin_immediate` — BEGIN IMMEDIATE transactions during snapshot
4. `test_multiple_snapshots_during_sustained_writes` — 5 sequential snapshots during continuous writes
5. `test_snapshot_does_not_block_writer_for_long` — performance assertion: no INSERT > 1s
6. `test_snapshot_during_concurrent_deletes` — DELETE transactions during snapshot
7. `test_snapshot_during_concurrent_fts5_inserts` — FTS5 inserts during snapshot
8. `test_snapshot_under_mixed_concurrent_load` — 3-5 threads with mixed ops
9. `test_begin_immediate_serialization_under_wal` — (already in Task 3, but also belongs in this file for organization; can be a cross-reference)

The `ConcurrentWriter` context manager: spawns a thread that writes to a real SQLite DB via `sqlite3` (not SQLAlchemy — to avoid connection pool interference). Records all inserted IDs and per-insert durations.

Full implementation: the subagent should implement all 8 tests (excluding the BEGIN IMMEDIATE test already in Task 3) following the exact descriptions in the spec's Tier 2 section. Each test must use real `sqlite3` connections, real writes, and verify snapshot consistency by opening the snapshot with a fresh connection and checking data.

- [ ] **Step 7.2: Run concurrent tests**

Run: `python -m pytest tests/test_snapshot_concurrent.py -x -q -v`
Expected: All pass.

- [ ] **Step 7.3: Commit**

```bash
git add tests/test_snapshot_concurrent.py
git commit -m "test: add Tier 2 concurrent writer snapshot tests"
```

---

## Task 8: Tier 4 — Failure Injection Tests

**Files:**
- Create: `tests/test_snapshot_failure.py`

---

- [ ] **Step 8.1: Implement all Tier 4 failure injection tests**

Create `tests/test_snapshot_failure.py` implementing all tests from the spec's Tier 4 section:

1. `test_snapshot_to_readonly_dir` — make snapshot_dir read-only, verify exception + no partial files
2. `test_snapshot_to_full_disk` — fill temp dir with ballast, attempt snapshot of larger DB (skip on platforms without easy disk-full simulation)
3. `test_snapshot_when_live_db_deleted_during_backup` — delete live DB mid-backup via a progress callback (may need to use `pages=1` for granularity)
4. `test_restore_from_snapshot_with_older_schema` — create DB with fewer columns, snapshot, restore, run schema init → verify migrations apply
5. `test_snapshot_worker_survives_transient_failure` — patch `os.replace` to fail once, verify worker continues
6. `test_corrupt_snapshot_among_valid_ones` — newest is garbage bytes, restore falls back to older valid
7. `test_snapshot_with_active_wal_checkpoint` — write >1000 WAL pages, snapshot during/after checkpoint
8. `test_stale_tmp_files_from_previous_crash` — orphaned .tmp files don't interfere with new snapshots
9. `test_shutdown_snapshot_when_snapshot_dir_gone` — delete snapshot_dir before shutdown snapshot
10. `test_os_replace_failure_on_windows` — Windows-only, skip on Linux

Each test uses real file operations, real SQLite databases, and real failure injection. Mocking is only acceptable for `os.replace` failure injection (one test), not for the data path.

- [ ] **Step 8.2: Run failure injection tests**

Run: `python -m pytest tests/test_snapshot_failure.py -x -q -v`
Expected: All pass (some may be skipped on Linux/Windows as noted).

- [ ] **Step 8.3: Commit**

```bash
git add tests/test_snapshot_failure.py
git commit -m "test: add Tier 4 failure injection tests for snapshot persistence"
```

---

## Task 9: Tier 5 — Data Fidelity Round-Trip Tests

**Files:**
- Create: `tests/test_snapshot_roundtrip.py`

These are the most important tests for production confidence. They verify that every data type in Pallium survives the full snapshot → wipe → restore cycle.

---

- [ ] **Step 9.1: Implement all Tier 5 round-trip tests**

Create `tests/test_snapshot_roundtrip.py` implementing all tests from the spec's Tier 5 section. Each test follows the pattern:

1. Create a `SQLiteStorageProvider` with a real temp DB
2. Write specific data through the storage API
3. Call `create_snapshot`
4. Delete the live DB (wipe)
5. Call `restore_snapshot`
6. Create a new `SQLiteStorageProvider` on the restored DB
7. Query back all data and verify field-by-field match

Tests:
1. `test_roundtrip_source_items` — 50 items with all nullable columns populated
2. `test_roundtrip_memory_objects_and_relations` — items + memories + relations + index entries, verify FK relationships
3. `test_roundtrip_fts5_search` — items + lexical indexes, verify FTS5 MATCH query works after restore
4. `test_roundtrip_processing_queue_state` — items in pending/processing/completed/failed states with leases
5. `test_roundtrip_thread_processing_leases` — lease records in various states
6. `test_roundtrip_maintenance_state` — maintenance state with cursor positions
7. `test_roundtrip_package_processing_status` — per-package processing records
8. `test_roundtrip_large_content` — 100KB+ text content
9. `test_roundtrip_unicode_content` — Hebrew, Arabic, CJK, emoji content

Use `core.models.new_id()` and `core.models.utc_now()` for IDs and timestamps. Use the storage provider's CRUD methods (not raw SQL) for writes and reads to test the real data path.

- [ ] **Step 9.2: Run round-trip tests**

Run: `python -m pytest tests/test_snapshot_roundtrip.py -x -q -v`
Expected: All pass.

- [ ] **Step 9.3: Commit**

```bash
git add tests/test_snapshot_roundtrip.py
git commit -m "test: add Tier 5 data fidelity round-trip tests for all Pallium data types"
```

---

## Task 10: Tier 3 — Lifecycle Integration Tests

**Files:**
- Create: `tests/test_snapshot_lifecycle.py`

These are multi-process tests using real supervisor runs. They are the slowest tests but provide the highest production confidence.

---

- [ ] **Step 10.1: Implement lifecycle integration tests**

Create `tests/test_snapshot_lifecycle.py` with tests that use the `FakeProcess` pattern from `tests/test_async_worker.py` for supervisor tests, and real subprocesses for the full end-to-end test.

Tests:
1. `test_supervisor_restore_ordering` — verify restore log appears before child spawn logs (uses `FakeProcess` + log capture)
2. `test_supervisor_restarts_crashed_snapshot_worker` — kill snapshot process, verify restart (uses `FakeProcess` with crash simulation)
3. `test_full_lifecycle_restore_snapshot_shutdown` — the critical e2e test (may need real subprocesses or careful `FakeProcess` orchestration)
4. `test_restore_then_vector_reconciliation` — restore DB with vector entries, verify reconciliation fills usearch (requires usearch; skip if not installed)

For the full lifecycle test: if real subprocesses are impractical in CI, use the `popen_factory` injection + `FakeProcess` pattern with assertions on the sequence of operations (restore called before spawn, shutdown snapshot called after terminate).

- [ ] **Step 10.2: Run lifecycle tests**

Run: `python -m pytest tests/test_snapshot_lifecycle.py -x -q -v`
Expected: All pass.

- [ ] **Step 10.3: Commit**

```bash
git add tests/test_snapshot_lifecycle.py
git commit -m "test: add Tier 3 lifecycle integration tests for snapshot persistence"
```

---

## Task 11: Documentation Updates

**Files:**
- Modify: `docs/context/architecture.md`
- Modify: `docs/context/decisions.md`

---

- [ ] **Step 11.1: Update architecture.md**

Add a new section "## Snapshot Persistence" after the "Lifecycle" section:

```markdown
## Snapshot Persistence

Pallium supports periodic SQLite snapshot persistence for ephemeral storage deployments
(containers, VMs, cloud compute). The live database runs on fast local/ephemeral disk while
consistent snapshots are written to a configurable durable path.

Current behavior:

- startup: restore newest valid snapshot to live DB path (before any child process spawns)
- runtime: periodic snapshots via SQLite backup API with page-level yielding to writers
- shutdown: best-effort snapshot after all children exit
- dirty tracking: snapshot only when DB modified since last snapshot (mtime-based)
- pruning: retains configurable number of most recent snapshots
- validation: `PRAGMA quick_check` on restore candidates, falling back to older snapshots
- vector index is not snapshotted — reconciliation rebuilds it from DB after restore

The snapshot worker runs as a restartable supervised child process alongside processors and
cleaners. WAL mode is enabled on the live database for concurrent read/write access.

Configuration: `[snapshot]` section in `pallium.local.toml` or `PALLIUM_SNAPSHOT_*` env vars.
```

- [ ] **Step 11.2: Update decisions.md**

Add two new accepted decisions:

```markdown
### 2026-04-09 - WAL journal mode for multi-process SQLite

WAL (Write-Ahead Logging) is enabled during schema initialization. WAL allows concurrent readers
during writes and reduces write contention between the API server, processors, and cleaners.

Why:

- DELETE journal mode (SQLite default) acquires an exclusive lock for the full transaction duration
- with sustained write pressure from multiple processes, this creates visible contention
- WAL allows readers to proceed during writes and narrows the write-contention window to commit time
- WAL is the recommended journal mode for multi-process SQLite on local disk
- also required for non-blocking snapshot persistence via the SQLite backup API

### 2026-04-09 - SQLite backup API for snapshot persistence

Periodic snapshots use Python's `sqlite3.backup()` with page-level yielding (`pages=256, sleep=0.01`)
instead of `VACUUM INTO`. Shutdown snapshots use `pages=-1` (all-at-once) since no writers are active.

Why:

- `VACUUM INTO` holds a shared lock for the entire copy duration, blocking all writers
- at expected scale (hundreds of MB), this means seconds of write stall
- `sqlite3.backup()` copies pages in batches, yielding to writers between batches
- individual lock holds are microseconds per batch; writers see negligible contention
- the backup API produces a raw page copy (no defragmentation), which is acceptable — the goal is
  consistent snapshot, not compaction
```

- [ ] **Step 11.3: Commit**

```bash
git add docs/context/architecture.md docs/context/decisions.md
git commit -m "docs: document snapshot persistence capability and WAL mode decision"
```

---

## Task 12: Full Regression + Final Verification

---

- [ ] **Step 12.1: Run the complete test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All tests pass. No regressions from WAL mode or config changes.

- [ ] **Step 12.2: Run only the new snapshot tests**

Run: `python -m pytest tests/test_snapshot.py tests/test_snapshot_concurrent.py tests/test_snapshot_failure.py tests/test_snapshot_roundtrip.py tests/test_snapshot_lifecycle.py -v`
Expected: All pass with verbose output showing every test name.

- [ ] **Step 12.3: Verify clean-data.sh works**

Run: `bash scripts/clean-data.sh`
Expected: No errors. Script completes cleanly.

- [ ] **Step 12.4: Final commit if any remaining changes**

```bash
git status
# If clean, nothing to commit. If any remaining changes, commit them.
```
