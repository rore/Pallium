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

BACKUP_PAGES_PER_STEP = 256
BACKUP_SLEEP_BETWEEN = 0.01


def resolve_live_db_path(sqlite_url: str) -> str:
    """Extract the filesystem path from a SQLAlchemy SQLite URL."""
    prefix = "sqlite:///"
    if not sqlite_url.startswith(prefix):
        raise ValueError(f"Expected sqlite:/// URL, got: {sqlite_url}")
    return sqlite_url[len(prefix):]


def _validate_snapshot(path: Path) -> bool:
    """Quick structural integrity check on a snapshot file."""
    try:
        if path.stat().st_size == 0:
            return False
        conn = sqlite3.connect(str(path))
        result = conn.execute("PRAGMA quick_check").fetchone()
        conn.close()
        return result is not None and result[0] == "ok"
    except Exception:
        return False


def create_snapshot(
    live_db_path: str,
    snapshot_dir: Path,
    *,
    pages_per_step: int = BACKUP_PAGES_PER_STEP,
    sleep_between: float = BACKUP_SLEEP_BETWEEN,
) -> Path | None:
    """Create a consistent snapshot using the SQLite backup API.

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
    wal_path = db_path.with_suffix(".db-wal")
    if wal_path.exists():
        db_mtime = max(db_mtime, wal_path.stat().st_mtime)
    latest = _find_latest_snapshot(snapshot_dir)
    if latest is None:
        return True
    return db_mtime > latest.stat().st_mtime


def restore_snapshot(snapshot_dir: Path, live_db_path: str) -> bool:
    """Restore the newest valid snapshot to the live DB path.

    Returns True if restored, False if starting fresh.
    Skips restore if the live DB already exists.
    """
    live_path = Path(live_db_path)
    if live_path.exists():
        logger.info("Live DB exists at %s — skipping snapshot restore", live_db_path)
        return False
    candidates = sorted(snapshot_dir.glob("pallium-*.db"), key=lambda p: p.name, reverse=True)
    for candidate in candidates:
        if _validate_snapshot(candidate):
            live_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(candidate), str(live_path))
            live_path.with_suffix(".db-wal").unlink(missing_ok=True)
            live_path.with_suffix(".db-shm").unlink(missing_ok=True)
            logger.info("Restored snapshot %s -> %s", candidate.name, live_db_path)
            return True
        else:
            logger.warning("Snapshot %s failed validation, trying next", candidate.name)
    logger.info("No valid snapshots found in %s — starting fresh", snapshot_dir)
    return False


def _prune_old_snapshots(snapshot_dir: Path, *, keep: int) -> None:
    """Remove oldest snapshots, keeping the most recent `keep` files."""
    snapshots = sorted(snapshot_dir.glob("pallium-*.db"), key=lambda p: p.name, reverse=True)
    for old in snapshots[keep:]:
        old.unlink(missing_ok=True)


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
