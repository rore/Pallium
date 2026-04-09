# SQLite Snapshot Persistence for Ephemeral Storage — Design

**Date:** 2026-04-09
**Status:** Draft

---

## Problem

Pallium uses SQLite with multiple writer processes (API server, processors, cleaners) managed by a
supervisor. SQLite requires a real local filesystem with working POSIX/Windows file locks — network
filesystems (NFS, SMB, FUSE-based mounts) are unreliable for live database access. But
container/ephemeral compute environments (Docker, Kubernetes, cloud container services) only offer
durable storage via network-mounted volumes. Running SQLite directly on those mounts risks
corruption.

Pallium needs to run its live SQLite database on fast local/ephemeral disk while durably persisting
consistent snapshots to a configurable stable path. This enables Pallium to survive container
restarts, VM preemptions, and other ephemeral compute lifecycle events without losing accumulated
memory.

### Scale context

Pallium will serve team agents handling groups of ~50 developers communicating via Slack, alongside
local AI assistant instances. This means sustained write pressure throughout the workday — thousands
of source items per day, each potentially generating memory objects, relations, and index entries.
The database will grow to hundreds of MB over weeks. The snapshot mechanism must not cause visible
ingest stalls under this sustained write load.

## Goals

1. Consistent, periodic snapshots of the live SQLite database to a durable path.
2. Automatic restore from the newest valid snapshot on startup.
3. No blocking or stalling of writers during snapshot (yielding copy, not full-lock copy).
4. Best-effort shutdown snapshot to minimize data loss on SIGTERM.
5. Configurable via TOML and env vars, following existing Pallium config patterns.
6. No external dependencies — the snapshot destination is "just a filesystem path."

## Non-Goals

- Cloud SDK integrations or object storage backends.
- Vector index snapshotting (rebuildable from DB via `rebuild-vector-index`; reconciliation fills
  gaps at runtime).
- Multi-instance coordination (single instance with SQLite; PostgreSQL for multi-instance).
- Incremental/differential backup (full snapshot each time is sufficient at expected scale).
- Snapshot encryption or compression (the durable mount handles these concerns if needed).

---

## Architecture

### Process model

```
Supervisor startup
  │
  ├─ 1. Restore newest valid snapshot → live DB path  (before any child spawns)
  │
  ├─ 2. Spawn children:
  │     ├─ API server          (existing, not restartable)
  │     ├─ Processor(s)        (existing, restartable)
  │     ├─ Cleaner(s)          (existing, restartable)
  │     └─ Snapshot worker     (NEW, restartable)
  │
  └─ 3. Supervisor loop (poll children, restart crashed, handle signals)
         │
         └─ On SIGTERM/SIGINT:
              ├─ Terminate all children (existing behavior)
              ├─ Wait for children to exit (existing behavior)
              ├─ Best-effort final snapshot  (NEW)
              └─ Exit
```

The snapshot worker is a new supervised child process, launched via
`python -m app.snapshot --interval-seconds 60`. It follows the same pattern as the cleaner:
a poll loop with `graceful_stop`, restartable by the supervisor.

### Data flow

```
Startup:
  snapshot_path/pallium-<timestamp>.db  →  shutil.copy2  →  live_db_path

Runtime (periodic, in snapshot worker):
  live_db_path  →  sqlite3.backup(pages=256, sleep=0.01)  →  snapshot_path/pallium-<timestamp>.tmp
  pallium-<timestamp>.tmp  →  os.replace  →  snapshot_path/pallium-<timestamp>.db

Shutdown (in supervisor, after children exit):
  live_db_path  →  sqlite3.backup(pages=-1)  →  snapshot_path/pallium-<timestamp>.tmp
  pallium-<timestamp>.tmp  →  os.replace  →  snapshot_path/pallium-<timestamp>.db
```

---

## Detailed Design

### 1. Configuration

New `[snapshot]` section in `pallium.local.toml`, plus env var overrides following the existing
pattern in `app/config.py`.

```toml
[snapshot]
enabled = true
snapshot_path = "/mnt/durable/pallium-snapshots"
interval_seconds = 60
max_snapshots = 5
```

**Config dataclass:**

```python
@dataclass(frozen=True)
class SnapshotConfig:
    enabled: bool = False                  # opt-in, off by default
    snapshot_path: str | None = None       # required when enabled
    interval_seconds: int = 60             # snapshot interval
    max_snapshots: int = 5                 # retained snapshot count
```

**Env var overrides:**

| Env var | Config key | Default |
|---|---|---|
| `PALLIUM_SNAPSHOT_ENABLED` | `snapshot.enabled` | `false` |
| `PALLIUM_SNAPSHOT_PATH` | `snapshot.snapshot_path` | (none) |
| `PALLIUM_SNAPSHOT_INTERVAL_SECONDS` | `snapshot.interval_seconds` | `60` |
| `PALLIUM_SNAPSHOT_MAX_SNAPSHOTS` | `snapshot.max_snapshots` | `5` |

**Validation:** If `enabled = true` and `snapshot_path` is not set, startup fails with a clear
error message. The `snapshot_path` directory must exist (Pallium does not create it — the
deployment is responsible for mounting durable storage).

**AppConfig integration:** `SnapshotConfig` is added as a field on `AppConfig`, loaded from the
`[snapshot]` TOML section and env vars in `AppConfig.from_env()`, following the exact same pattern
as `RetentionConfig`.

### 2. Snapshot file naming and layout

Snapshot files are named with a UTC timestamp for natural sort ordering:

```
/mnt/durable/pallium-snapshots/
  pallium-20260409T143022Z.db
  pallium-20260409T143122Z.db
  pallium-20260409T143222Z.db
```

Format: `pallium-<YYYYMMDD>T<HHMMSS>Z.db`

Temp files during write: `pallium-<timestamp>.tmp` in the same directory — written first, then
atomically renamed via `os.replace()`. This ensures a crash during write never leaves a partial
`.db` file.

### 3. Snapshot mechanism — SQLite Backup API

Python's `sqlite3.backup()` copies pages from a source connection to a destination connection.
It supports incremental copying with writer yielding between page batches.

**Why SQLite Backup API over VACUUM INTO:**

- `VACUUM INTO` acquires a shared lock for the entire duration, blocking all writers. At the
  expected scale (hundreds of MB), this means seconds of write stall visible to 50 developers.
- `sqlite3.backup(pages=N, sleep=S)` copies N pages per batch, sleeps S seconds between batches,
  allowing writers to proceed in the gaps. The total copy takes longer wall-clock time, but
  individual lock holds are brief.
- The backup API produces a raw page copy (not defragmented). Compaction is not a goal — consistent
  snapshot is the goal. If fragmentation ever matters, a one-off `VACUUM` on the snapshot suffices.

**Parameters:**

```python
BACKUP_PAGES_PER_STEP = 256    # ~1MB per step at 4KB page size
BACKUP_SLEEP_BETWEEN = 0.01   # 10ms yield between steps
```

At 256 pages per step with 10ms sleep, a 500MB database (~128K pages) takes ~500 steps = ~5 seconds
of sleep + copy time. Writers are blocked for microseconds per step (the time to copy 256 pages),
yielding for 10ms between steps.

**Implementation sketch:**

```python
import sqlite3
import os
from pathlib import Path
from datetime import datetime, timezone

def create_snapshot(
    live_db_path: str,
    snapshot_dir: Path,
    *,
    pages_per_step: int = 256,
    sleep_between: float = 0.01,
) -> Path | None:
    """Create a consistent snapshot of the live database.

    Returns the snapshot path on success, None on failure.
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
    except Exception:
        dst.close()
        src.close()
        tmp_path.unlink(missing_ok=True)
        raise
```

**Connection notes:** The `sqlite3.connect()` call opens a direct connection to the live database
file, bypassing SQLAlchemy. This is necessary because `sqlite3.backup()` operates on the `sqlite3`
module's connection objects, not SQLAlchemy sessions. The source connection is read-only in effect
(backup reads pages). WAL mode (see section 7) ensures readers and writers can coexist.

### 4. Dirty tracking

Snapshots should only run when the database has changed since the last snapshot. There's no need
to write identical snapshots every 60 seconds during quiet periods.

**Mechanism:** File modification time comparison.

```python
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
        return True  # no snapshot yet — definitely dirty
    return db_mtime > latest.stat().st_mtime
```

This is simple and sufficient: if the DB file (or its WAL) is newer than the latest snapshot, take
a snapshot. No need for in-process counters, write hooks, or cross-process signaling. Note that
`st_mtime` has 1-second granularity on some filesystems — a modification within the same second as
the last snapshot may be missed until the next interval. This is acceptable; worst case is one
extra interval of data loss window.

**Edge case:** The very first snapshot after startup will always fire (no snapshot exists yet or
the restored snapshot is older than the DB after schema init touches it). This is correct — we want
an initial snapshot shortly after startup.

### 5. Startup restore

Restore runs in the supervisor process before any child is spawned. This ensures the database is
ready before the API server, processors, or cleaners perform schema initialization.

**Algorithm:**

1. If `snapshot.enabled` is false, skip entirely (normal startup).
2. If the live DB already exists, skip restore (Pallium was not restarted from scratch — the
   existing DB is authoritative). Log this.
3. List all `pallium-*.db` files in `snapshot_path`, sorted by name descending (newest first).
4. For each candidate snapshot (newest first):
   a. Validate with `PRAGMA quick_check` (checks b-tree structural integrity without full
      row-level constraint verification — fast even on large databases).
   b. If valid: copy to live DB path via `shutil.copy2()`, log success, done.
   c. If invalid: log warning, try the next older snapshot.
5. If no valid snapshot found: log warning, start with empty DB (fresh start). This is not an
   error — it's the expected state on first deployment.

**Why `shutil.copy2` and not `sqlite3.backup`:** Restore runs before any process has the database
open. There are no concurrent readers or writers. A simple file copy is correct, faster, and
simpler. The backup API's yielding behavior is only needed at runtime when writers are active.

**Why not restore if DB exists:** When the live DB already exists (e.g., Pallium restarted but the
ephemeral disk survived), it contains more recent data than any snapshot. Overwriting it with an
older snapshot would lose data. The snapshot is a safety net for when the ephemeral disk is wiped,
not a "restore to last known good" mechanism.

**WAL cleanup:** After copying the snapshot, if WAL or SHM files exist at the live path from a
previous run, delete them. The snapshot is a clean database without WAL state. Stale WAL/SHM files
from a previous process could confuse SQLite. (In practice, ephemeral disk wipes take care of this,
but defense in depth.)

```python
def restore_snapshot(
    snapshot_dir: Path,
    live_db_path: str,
) -> bool:
    """Restore the newest valid snapshot to the live DB path.

    Returns True if a snapshot was restored, False if starting fresh.
    """
    live_path = Path(live_db_path)
    if live_path.exists():
        # Live DB exists — it has more recent data than any snapshot
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
            # Clean stale WAL/SHM
            live_path.with_suffix(".db-wal").unlink(missing_ok=True)
            live_path.with_suffix(".db-shm").unlink(missing_ok=True)
            return True

    return False  # no valid snapshot — fresh start


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

### 6. Snapshot worker process

New module: `app/snapshot.py`. Follows the same pattern as `app/cleaner.py`: argument parser,
poll loop with `graceful_stop`, restartable by the supervisor.

```python
# app/snapshot.py — simplified structure

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Pallium snapshot worker")
    parser.add_argument("--interval-seconds", type=int, default=None)
    return parser


def run_snapshot(args: list[str] | None = None, *, config: AppConfig | None = None) -> int:
    parsed = build_parser().parse_args(args)
    resolved_config = config or AppConfig.from_env()
    snapshot_config = resolved_config.snapshot

    if not snapshot_config.enabled or not snapshot_config.snapshot_path:
        return 0  # snapshot not configured — exit cleanly

    live_db_path = _resolve_live_db_path(resolved_config.sqlite_url)
    snapshot_dir = Path(snapshot_config.snapshot_path)
    interval = parsed.interval_seconds or snapshot_config.interval_seconds

    if not snapshot_dir.is_dir():
        emit_runtime_log("snapshot", f"snapshot_path does not exist: {snapshot_dir}", stderr=True)
        return 1

    with graceful_stop(install=True) as stop:
        while not stop.requested:
            try:
                if _is_dirty(live_db_path, snapshot_dir):
                    path = create_snapshot(live_db_path, snapshot_dir)
                    if path is not None:
                        emit_runtime_log("snapshot", f"snapshot created: {path.name}")
                        _prune_old_snapshots(snapshot_dir, keep=snapshot_config.max_snapshots)
                else:
                    emit_runtime_log("snapshot", "skipped: database not modified since last snapshot")
            except Exception as exc:
                emit_runtime_log("snapshot", f"snapshot failed: {exc}", stderr=True)
            if stop.requested:
                break
            time.sleep(interval)
    return 0
```

**Integration into supervisor:** `app/supervisor.py` gains `build_snapshot_command()` and spawns
the snapshot worker as a restartable child when snapshot is enabled.

```python
def build_snapshot_command(interval_seconds: int) -> list[str]:
    return [sys.executable, "-m", "app.snapshot", "--interval-seconds", str(interval_seconds)]
```

In `run_supervisor()`, after spawning cleaners:

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
```

### 7. WAL mode

WAL (Write-Ahead Logging) is a natural pairing with snapshot persistence. WAL mode allows
concurrent reads during writes, reduces write contention between processes, and is the recommended
journal mode for multi-process SQLite on local disk.

**Current state:** Pallium does not configure journal mode — SQLite defaults to DELETE (rollback
journal). This means every write acquires an exclusive lock for the duration of the transaction.
With 50 developers generating sustained writes, this is a bottleneck independent of snapshots.

**Change:** Enable WAL mode during schema initialization in `storage/sqlite_schema.py`. WAL is
set per-database, persists across connections, and only needs to be set once (it's stored in the
database file header).

```python
def _initialize_schema(self) -> None:
    with self._schema_initialization_lock():
        # Enable WAL mode for concurrent read/write access
        with self._engine.begin() as connection:
            connection.execute(text("PRAGMA journal_mode=WAL"))
        Base.metadata.create_all(self._engine)
        # ... rest of existing schema init ...
```

**Why WAL helps snapshots:** In WAL mode, `sqlite3.backup()` reads from a consistent snapshot of
the database without blocking writers. Writers append to the WAL file while the backup reads from
the main database file + committed WAL frames. Without WAL, the backup API still works but has
higher contention.

**Why WAL helps Pallium generally:** Beyond snapshots, WAL mode benefits the existing
multi-process architecture. Processors and cleaners using `BEGIN IMMEDIATE` currently contend
for the exclusive lock. WAL mode allows concurrent readers (API queries) to proceed during writes
and reduces lock contention between writers (they contend only at commit, not for the duration of
the transaction).

**WAL checkpoint behavior:** SQLite auto-checkpoints when the WAL reaches 1000 pages (~4MB). This
is fine for Pallium. We do not need to configure custom checkpoint thresholds.

**Backward compatibility:** Enabling WAL on an existing database is safe — SQLite handles the
transition transparently. The only observable change is the presence of `-wal` and `-shm` sidecar
files alongside the database file. The `clean-data.sh` script should be updated to also remove
these sidecar files.

### 8. Shutdown snapshot

Best-effort snapshot in the supervisor's `finally` block, after all children have exited but before
the supervisor process terminates.

```python
# In run_supervisor(), inside the finally block, after waiting for children:
if snapshot_config.enabled and snapshot_config.snapshot_path:
    try:
        snapshot_dir = Path(snapshot_config.snapshot_path)
        live_db_path = _resolve_live_db_path(config.sqlite_url)
        # All children are stopped — no concurrent writers.
        # Use pages=-1 for all-at-once copy (no need to yield).
        path = create_snapshot(
            live_db_path, snapshot_dir,
            pages_per_step=-1,
            sleep_between=0,
        )
        if path is not None:
            emit_runtime_log("supervisor", f"shutdown snapshot created: {path.name}")
            _prune_old_snapshots(snapshot_dir, keep=snapshot_config.max_snapshots)
    except Exception as exc:
        emit_runtime_log(
            "supervisor",
            f"shutdown snapshot failed (data loss window = last {snapshot_config.interval_seconds}s): {exc}",
            stderr=True,
        )
```

**Why pages=-1 at shutdown:** All child processes are terminated and waited on. There are no
concurrent writers. Copying all pages at once is faster and simpler. The yielding behavior is
only needed during runtime.

**Why best-effort:** The supervisor is shutting down, possibly under time pressure (container
runtime gives 30s on SIGTERM). If the snapshot fails, log it and exit. The last periodic snapshot
is at most `interval_seconds` old — that's the data loss window.

### 9. Snapshot pruning

After each successful snapshot (periodic or shutdown), prune old snapshots to retain only
`max_snapshots` most recent.

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

Default `max_snapshots = 5` means at 60s intervals, the last ~5 minutes of snapshots are
retained. If the newest snapshot is corrupt (disk error during write — prevented by atomic rename
but possible via mount failure), restore falls back to the next oldest.

### 10. Helper: resolving live DB path from sqlite_url

The existing `sqlite_url` config value is a SQLAlchemy URL (e.g., `sqlite:///./pallium.db`). The
snapshot system needs the raw filesystem path.

```python
def _resolve_live_db_path(sqlite_url: str) -> str:
    """Extract the filesystem path from a SQLAlchemy SQLite URL."""
    # sqlite:///./pallium.db → ./pallium.db
    # sqlite:////absolute/path.db → /absolute/path.db
    prefix = "sqlite:///"
    if not sqlite_url.startswith(prefix):
        raise ValueError(f"Expected sqlite:/// URL, got: {sqlite_url}")
    return sqlite_url[len(prefix):]
```

This function lives in `app/snapshot.py` and is imported by `app/supervisor.py` for the restore
and shutdown snapshot steps.

**Supervisor config loading:** The supervisor calls `AppConfig.from_env()` to obtain
`SnapshotConfig` before spawning children. This is a new dependency — the current supervisor
does not load `AppConfig`. The config load is lightweight (reads TOML + env, no DB or network).
The supervisor uses it only for snapshot config; child processes load their own config
independently as they do today.

### 11. CLI mode

Add `snapshot` as a new mode in `app/run.py` for standalone testing and manual snapshot creation:

```python
if parsed.mode == "snapshot":
    from app.snapshot import run_snapshot
    return run_snapshot(config=AppConfig.from_env())
```

This allows `python -m app.run snapshot` for manual operation or debugging, consistent with the
existing `processor` and `cleaner` standalone modes.

---

## Data loss window

The worst-case data loss window equals the snapshot interval. Default 60 seconds means at most
60 seconds of data is lost if the ephemeral disk disappears between snapshots.

**Reducing the window:** Set `interval_seconds` lower (e.g., 30 or 15). The cost is more frequent
disk I/O to the durable mount, but the dirty-tracking guard ensures no snapshot is written when
nothing changed.

**Shutdown behavior:** If the supervisor receives SIGTERM and the shutdown snapshot succeeds, the
data loss window shrinks to zero for graceful shutdowns. Only ungraceful termination (SIGKILL,
power loss, OOM kill) has the full interval as data loss window.

---

## Error handling

| Scenario | Behavior |
|---|---|
| Snapshot write fails (disk full, mount unavailable) | Log error, retry on next interval. No crash. |
| Restore finds no snapshots | Log info, start with empty DB. Normal first-run behavior. |
| Restore finds only corrupt snapshots | Log warning for each, start with empty DB. |
| Snapshot worker crashes | Supervisor restarts it (restartable=True). |
| Snapshot path directory doesn't exist | Snapshot worker exits with error. Supervisor restarts, same error. After 3 crashes in 60s, supervisor gives up (existing restart policy). |
| Live DB path doesn't exist at snapshot time | `_is_dirty` returns False, no snapshot attempted. |
| Shutdown snapshot fails | Log error with data loss window estimate, exit anyway. |
| Snapshot takes longer than interval | Next snapshot is skipped (dirty check still passes, but the worker's sleep cycle naturally spaces them). |
| Concurrent restore + schema init | Impossible — restore runs in supervisor before spawning children. |

---

## Files changed

| File | Change |
|---|---|
| `app/config.py` | Add `SnapshotConfig` dataclass, add to `AppConfig`, load from TOML + env |
| `app/snapshot.py` | **New.** Snapshot worker: `create_snapshot`, `restore_snapshot`, `_is_dirty`, `_validate_snapshot`, `_prune_old_snapshots`, `_resolve_live_db_path`, `run_snapshot` entry point |
| `app/supervisor.py` | Load snapshot config, call `restore_snapshot` before spawning children, spawn snapshot worker as restartable child, shutdown snapshot in `finally` block, `build_snapshot_command` |
| `app/run.py` | Add `"snapshot"` mode to CLI choices, dispatch to `run_snapshot` |
| `storage/sqlite_schema.py` | Add `PRAGMA journal_mode=WAL` in `_initialize_schema` |
| `scripts/clean-data.sh` | Also remove `*.db-wal` and `*.db-shm` sidecar files |
| `docs/context/architecture.md` | Document snapshot persistence as an operational capability |
| `docs/context/decisions.md` | Record WAL mode decision and snapshot mechanism choice |

## Test plan

### Testing philosophy

This is data-loss-prevention infrastructure. Failures here are silent and show up in production
as missing memory after a container restart — hard to reproduce, hard to debug, hard to explain
to 50 developers whose agent lost its memory. The test strategy prioritizes **real SQLite
databases, real concurrent writers, real file operations, and real failure injection** over mocks.

Tests use `tmp_path` (pytest fixture) for both live DB and snapshot directories. Every test
creates a real SQLite database, writes real rows, and verifies data through real SQL queries.
No mocking of `sqlite3`, `shutil`, or `os.replace` in the core data-path tests.

### Tier 1 — Unit tests (real SQLite, single-process)

These run fast and test the core snapshot/restore functions in isolation with real databases.

| Test | What it verifies |
|---|---|
| `test_snapshot_create_produces_valid_db` | `create_snapshot` produces a `.db` file that passes `PRAGMA quick_check` and contains all rows from the source |
| `test_snapshot_empty_database` | Create a DB with schema but zero rows. Snapshot. Restore. Verify: all tables exist, zero rows, schema init on restored DB is a no-op (no migration errors). This is the first-deployment path. |
| `test_snapshot_data_integrity` | Write N rows to live DB, snapshot, open snapshot with a fresh connection, verify all N rows present and values match |
| `test_snapshot_includes_all_tables` | Create a DB with source_items, memory_objects, relations, index_entries, lexical_fts. Snapshot. Verify all tables and row counts match in the snapshot. |
| `test_snapshot_atomic_rename` | After `create_snapshot`, no `.tmp` files remain in snapshot_dir. Only `.db` files exist. |
| `test_snapshot_failure_cleans_tmp` | Patch the `dst` connection to raise during `backup()`. Verify no `.tmp` or `.db` file is left behind for that timestamp. |
| `test_snapshot_all_at_once_mode` | Call `create_snapshot` with `pages_per_step=-1, sleep_between=0` (the shutdown path). Verify: produces a valid snapshot with all data. Confirms the shutdown code path works independently of the yielding path. |
| `test_snapshot_fts5_in_snapshot` | Verify that the FTS5 virtual table `lexical_fts` is present and queryable in the snapshot (FTS5 tables can behave differently under backup). |
| `test_dirty_tracking_clean` | Create snapshot, don't modify DB, verify `_is_dirty` returns False |
| `test_dirty_tracking_after_write` | Create snapshot, write a row, verify `_is_dirty` returns True |
| `test_dirty_tracking_wal_modification` | Create snapshot, write a row (WAL mode — modifies WAL not main DB file), verify `_is_dirty` returns True by checking WAL mtime |
| `test_dirty_tracking_no_snapshot_yet` | No snapshots in dir, verify `_is_dirty` returns True |
| `test_dirty_tracking_no_db` | DB file doesn't exist, verify `_is_dirty` returns False |
| `test_restore_newest_valid` | Create 3 snapshots with different data. Restore. Verify restored DB contains data from the newest snapshot. |
| `test_restore_skips_corrupt_to_older` | Create 3 snapshots. Corrupt the newest (truncate file). Restore. Verify restored DB contains data from second-newest. |
| `test_restore_all_corrupt` | Create 3 snapshots, corrupt all. Restore returns False. No live DB created. |
| `test_restore_skips_when_live_exists` | Live DB already exists with data. Snapshot dir has an older snapshot. Restore returns False. Live DB unchanged. |
| `test_restore_no_snapshots` | Empty snapshot dir. Restore returns False. No live DB created. |
| `test_restore_cleans_stale_wal_shm` | Create stale `.db-wal` and `.db-shm` at the live path. Restore a snapshot. Verify WAL/SHM deleted and live DB contains snapshot data. |
| `test_restore_creates_parent_dirs` | Live DB path has a non-existent parent directory. Restore creates it. |
| `test_prune_keeps_n` | Create 8 snapshots. Prune with keep=5. Verify 5 newest remain, 3 oldest deleted. |
| `test_prune_fewer_than_max` | Create 3 snapshots. Prune with keep=5. All 3 remain. |
| `test_prune_ignores_non_snapshot_files` | Place a `readme.txt` in snapshot dir. Prune doesn't touch it. |
| `test_validate_snapshot_good` | Valid DB passes `_validate_snapshot`. |
| `test_validate_snapshot_corrupt` | Truncated/garbage file fails `_validate_snapshot`. |
| `test_validate_snapshot_empty_file` | Zero-byte file fails `_validate_snapshot`. |
| `test_resolve_live_db_path_relative` | `sqlite:///./pallium.db` → `./pallium.db` |
| `test_resolve_live_db_path_absolute` | `sqlite:////var/data/pallium.db` → `/var/data/pallium.db` |
| `test_resolve_live_db_path_rejects_non_sqlite` | `postgresql://...` raises ValueError |
| `test_snapshot_worker_loop_unit` | Call `run_snapshot()` directly with a `should_stop` callback that fires after 3 iterations. Verify: takes snapshots on dirty intervals, skips on clean intervals, exits cleanly when stopped. Mirrors the cleaner's unit test pattern. |

### Tier 2 — Concurrent writer tests (real SQLite, multi-threaded)

These verify that snapshots produce consistent data while writers are actively modifying the
database. They use threads (not subprocesses) for simplicity, since SQLite's file-level locking
works the same way.

| Test | What it verifies |
|---|---|
| `test_snapshot_during_concurrent_writes` | Start a writer thread that inserts rows in a loop (100 rows, small sleep between each). Take a snapshot mid-writes. Verify: snapshot is a valid DB, row count in snapshot is consistent (no partial transactions — every row that's present has all its columns), and row count in snapshot <= row count in live DB at snapshot completion. |
| `test_snapshot_during_concurrent_writes_wal` | Same as above but explicitly enable WAL mode first. Verify snapshot is consistent. |
| `test_snapshot_during_begin_immediate` | Writer thread runs `BEGIN IMMEDIATE` transactions (mimicking queue claiming from `sqlite_queue.py`). Take snapshot during writes. Verify snapshot consistency and no `OperationalError: database is locked` from either side. |
| `test_multiple_snapshots_during_sustained_writes` | Writer thread inserts rows continuously. Take 5 snapshots in sequence, 1 second apart. Verify: each snapshot is valid, each snapshot has >= the row count of the previous snapshot, no snapshot has more rows than the live DB had at that point. |
| `test_snapshot_does_not_block_writer_for_long` | Writer thread records timestamps before and after each INSERT. Take a snapshot (500-page DB to make it non-trivial). Verify: no single INSERT took longer than 1 second (i.e., the backup API's yielding actually works). This is a performance assertion, not just correctness. |
| `test_begin_immediate_serialization_under_wal` | Two writer threads both attempt `BEGIN IMMEDIATE` queue claims concurrently, 100 iterations each. Verify: no double-claims (same source_item_id claimed by two workers), no `OperationalError` crashes, all claims resolve correctly. Run against a real `SQLiteStorageProvider` instance with WAL enabled. |
| `test_snapshot_during_concurrent_deletes` | Writer thread runs DELETE transactions (mimicking retention cleaner: delete source items, memory objects, relations, index entries, and FTS5 rows in the same transaction). Take snapshot during deletes. Verify: snapshot is consistent — no orphaned relations pointing to deleted source items, no FTS5 rows for deleted index entries. |
| `test_snapshot_during_concurrent_fts5_inserts` | Writer thread inserts lexical index entries (which also insert into the `lexical_fts` FTS5 virtual table) in a loop. Take snapshot mid-writes. Verify: FTS5 shadow tables are consistent in the snapshot — `SELECT count(*) FROM lexical_fts` matches the number of lexical index entries, and FTS5 MATCH queries return correct results. |
| `test_snapshot_under_mixed_concurrent_load` | 3-5 writer threads doing mixed operations simultaneously: thread 1 inserts source items, thread 2 runs `BEGIN IMMEDIATE` queue claims, thread 3 deletes old items (mimicking cleaner), thread 4 inserts index entries + FTS5 rows. Take a snapshot during this mixed load. Verify: snapshot is a valid DB, all tables pass referential consistency checks, FTS5 is queryable. This is the closest simulation of real production contention with 50 developers. |

### Tier 3 — Full lifecycle integration tests (multi-process)

These test the actual supervisor → restore → snapshot worker → shutdown cycle using real
subprocesses, matching production behavior as closely as possible.

| Test | What it verifies |
|---|---|
| `test_full_lifecycle_restore_snapshot_shutdown` | **The critical end-to-end test.** 1) Create a live DB, write data, snapshot it to snapshot_dir. 2) Delete the live DB (simulating ephemeral disk wipe). 3) Run the supervisor with snapshot enabled. 4) Verify: restore happened (live DB exists with snapshot data), API server is reachable, ingest a new item via HTTP, let the snapshot worker take at least one snapshot. 5) Stop the supervisor (SIGTERM). 6) Verify: shutdown snapshot exists in snapshot_dir and contains the newly ingested item. 7) Delete live DB again. 8) Restore from the shutdown snapshot. 9) Verify: the newly ingested item is present. |
| `test_supervisor_spawns_snapshot_worker` | Start supervisor with snapshot config. Verify the snapshot worker process is running (check process list / labels in logs). Stop supervisor. |
| `test_supervisor_does_not_spawn_when_disabled` | Start supervisor without snapshot config. Verify no snapshot worker process in logs. |
| `test_supervisor_restarts_crashed_snapshot_worker` | Start supervisor, kill the snapshot worker process. Verify supervisor restarts it (check logs for restart message). |
| `test_supervisor_restore_ordering` | Start supervisor with snapshot config and a snapshot in the dir but no live DB. Verify via log ordering: restore log appears before any child spawn log. |
| `test_restore_then_vector_reconciliation` | Create a live DB with source items and vector index entries in SQLite (but no usearch index file). Snapshot it. Wipe live DB and any usearch files. Restore from snapshot. Start the API server (which starts the vector reconciliation thread). Verify: the reconciliation thread detects the SQLite vector entries, embeds them into a fresh usearch index, and vector search returns results. This is the full production recovery path — snapshot has no vector index, reconciliation rebuilds it. |

### Tier 4 — Failure injection tests

These deliberately break things to verify graceful degradation. They use real file operations.

| Test | What it verifies |
|---|---|
| `test_snapshot_to_readonly_dir` | Make snapshot_dir read-only. Call `create_snapshot`. Verify: raises exception, no partial files left, live DB is unaffected. |
| `test_snapshot_to_full_disk` | Create a tiny tmpfs or ramdisk (1MB). Fill it. Attempt snapshot of a larger DB. Verify: exception raised, no partial `.db` file, `.tmp` cleaned up. (On Windows: use a size-limited temp directory with pre-filled ballast files.) |
| `test_snapshot_when_live_db_deleted_during_backup` | Start a snapshot. Delete the live DB file mid-backup (between page batches, via a callback). Verify: `create_snapshot` raises, no corrupt snapshot written. |
| `test_restore_from_snapshot_with_older_schema` | Create a snapshot from a DB with fewer columns (simulating an older Pallium version). Restore it. Run schema init on it. Verify: migrations apply cleanly, new columns exist, old data preserved. |
| `test_snapshot_worker_survives_transient_failure` | Inject a single failure (e.g., patch `os.replace` to fail once then succeed). Verify: worker logs the error, sleeps, succeeds on the next interval. |
| `test_corrupt_snapshot_among_valid_ones` | Place a corrupt `.db` file (random bytes) with the newest timestamp alongside valid older snapshots. Restore. Verify: corrupt one skipped, next valid one used, warning logged. |
| `test_snapshot_with_active_wal_checkpoint` | Write enough data to trigger an auto-checkpoint (>1000 WAL pages). Take a snapshot during or right after checkpoint. Verify: snapshot is complete and valid. |
| `test_stale_tmp_files_from_previous_crash` | Place orphaned `.tmp` files in snapshot_dir (from a simulated previous crash). Run snapshot worker. Verify: new snapshots are created with fresh timestamps, orphaned `.tmp` files don't interfere. (Optionally: clean them up.) |
| `test_shutdown_snapshot_when_snapshot_dir_gone` | Configure snapshot to a directory, then delete it before the supervisor's shutdown snapshot runs. Verify: supervisor logs an error with the data loss window estimate but exits cleanly without crashing or hanging. |
| `test_os_replace_failure_on_windows` | (Windows-only, skip on Linux.) Open the target `.db` path with a file handle that blocks replacement. Call `create_snapshot`. Verify: `os.replace` fails, `.tmp` file remains on disk for manual recovery, exception is raised, live DB is unaffected. |

### Tier 5 — Data fidelity round-trip tests

These verify that the full snapshot → wipe → restore cycle preserves all data exactly.

| Test | What it verifies |
|---|---|
| `test_roundtrip_source_items` | Write 50 source items with varied fields (all nullable columns populated). Snapshot → wipe → restore. Query all 50 back. Verify every field matches. |
| `test_roundtrip_memory_objects_and_relations` | Write source items, memory objects, relations, index entries. Snapshot → wipe → restore. Verify all objects, relations, and index entries present with correct foreign-key relationships. |
| `test_roundtrip_fts5_search` | Write items, create lexical index entries (populating `lexical_fts`). Snapshot → wipe → restore. Run an FTS5 `MATCH` query. Verify: same results as before snapshot. |
| `test_roundtrip_processing_queue_state` | Write source items in various processing states (pending, processing with active lease, completed, failed with retry). Snapshot → wipe → restore. Verify: all processing states, lease timestamps, and retry state preserved exactly. A processor worker can resume claiming from the restored DB. |
| `test_roundtrip_thread_processing_leases` | Create thread processing lease records in various states. Snapshot → wipe → restore. Verify all lease state preserved. |
| `test_roundtrip_maintenance_state` | Write maintenance state records (retention cursor state). Snapshot → wipe → restore. Verify cursor position preserved. |
| `test_roundtrip_package_processing_status` | Create package processing status records in varied states (pending, processing with lease, completed, failed with retry, skipped) across multiple source items and packages. Snapshot → wipe → restore. Verify all per-package states, attempt counts, and lease timestamps preserved. A worker can resume claiming package tasks from the restored DB. |
| `test_roundtrip_large_content` | Write source items with large `content` fields (100KB+ text). Snapshot → wipe → restore. Verify content matches byte-for-byte. |
| `test_roundtrip_unicode_content` | Write source items with Hebrew, Arabic, CJK, and emoji content. Snapshot → wipe → restore. Verify content matches exactly (no encoding corruption). |

### Tier 6 — Config and CLI tests

Standard unit tests for configuration parsing and CLI dispatch.

| Test | What it verifies |
|---|---|
| `test_config_snapshot_from_toml` | TOML `[snapshot]` section parsed into `SnapshotConfig` |
| `test_config_snapshot_from_env` | `PALLIUM_SNAPSHOT_*` env vars override TOML values |
| `test_config_snapshot_defaults` | Missing `[snapshot]` section → `enabled=False`, all defaults |
| `test_config_validation_enabled_no_path` | `enabled=true` without `snapshot_path` → startup error |
| `test_cli_snapshot_mode` | `python -m app.run snapshot` dispatches to `run_snapshot` |
| `test_wal_mode_enabled` | Schema init sets `journal_mode=WAL` |

### Implementation notes for test infrastructure

**Concurrent writer harness:** Create a reusable `ConcurrentWriter` context manager that spawns a
thread writing rows to a real `SQLiteStorageProvider` at a configurable rate. The writer records
every row ID it inserts, so tests can verify exact membership in snapshots.

```python
class ConcurrentWriter:
    """Writes source items to a real SQLiteStorageProvider in a background thread."""
    def __init__(self, storage: SQLiteStorageProvider, rate_per_second: float = 50):
        ...
    def __enter__(self) -> "ConcurrentWriter": ...
    def __exit__(self, *exc) -> None: ...
    @property
    def inserted_ids(self) -> list[str]: ...
    @property
    def insert_durations_ms(self) -> list[float]: ...
```

**Snapshot dir fixture:** A pytest fixture that provides a `tmp_path`-backed snapshot directory
pre-populated with valid and/or corrupt snapshots as needed.

**Multi-process tests:** The Tier 3 lifecycle tests use `subprocess.Popen` to run the real
supervisor, matching the existing `test_supervisor.py` pattern. They communicate via log file
inspection and HTTP requests to the API server (waiting for it to become healthy before
proceeding).

**Platform notes:** The Tier 4 "full disk" test may need conditional skipping on Windows where
tmpfs is not available. Use a ballast-file approach as fallback: create a small temp directory,
fill it with a large file leaving only a few KB free, then attempt the snapshot.

## Out of scope

- Vector index snapshotting (rebuildable; reconciliation handles runtime gaps).
- Snapshot compression (durable mount handles this if needed).
- Snapshot encryption (durable mount handles this if needed).
- Remote/cloud storage backends (snapshot_path is a local filesystem path).
- Multi-instance coordination (PostgreSQL is the multi-instance path).
- Schema migration validation on restore (schema init handles migrations on any DB).
- Monitoring/alerting integration (logging is sufficient for v1; operators can watch logs).
