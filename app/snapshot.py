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
import json
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable, Mapping

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
        try:
            result = conn.execute("PRAGMA quick_check").fetchone()
            return result is not None and result[0] == "ok"
        finally:
            conn.close()
    except Exception:
        return False


def _snapshot_live_paths(live_db_path: str | Mapping[str, str]) -> dict[str, str]:
    if isinstance(live_db_path, Mapping):
        paths = {str(role): str(path) for role, path in live_db_path.items()}
        if set(paths) != {"main", "relay"}:
            raise ValueError("snapshot paths must contain exactly main and relay")
        return paths
    return {"main": str(live_db_path)}


def create_snapshot(live_db_path: str | Mapping[str, str], snapshot_dir: Path, *, pages_per_step: int = BACKUP_PAGES_PER_STEP, sleep_between: float = BACKUP_SLEEP_BETWEEN) -> Path | None:
    paths = _snapshot_live_paths(live_db_path)
    if len(paths) == 2:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        tmp = {r: snapshot_dir / f"pallium-{timestamp}-{r}.tmp" for r in paths}
        final = {r: snapshot_dir / f"pallium-{timestamp}-{r}.db" for r in paths}
        manifest_tmp = snapshot_dir / f"pallium-{timestamp}.manifest.tmp"
        manifest = snapshot_dir / f"pallium-{timestamp}.manifest.json"
        try:
            for role, source in paths.items():
                src = sqlite3.connect(source, timeout=5); dst = sqlite3.connect(str(tmp[role]))
                try: src.backup(dst, pages=pages_per_step, sleep=sleep_between)
                finally: dst.close(); src.close()
                if not _validate_snapshot(tmp[role]): raise RuntimeError(f"snapshot validation failed for {role}")
            for role in final: os.replace(str(tmp[role]), str(final[role]))
            manifest_tmp.write_text(json.dumps({"generation": timestamp}), encoding="utf-8")
            os.replace(str(manifest_tmp), str(manifest))
            return manifest
        except BaseException:
            for path in (*tmp.values(), manifest_tmp): path.unlink(missing_ok=True)
            raise
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    final_path = snapshot_dir / f"pallium-{timestamp}.db"; tmp_path = snapshot_dir / f"pallium-{timestamp}.tmp"
    src = dst = None
    try:
        src = sqlite3.connect(paths["main"], timeout=5); dst = sqlite3.connect(str(tmp_path))
        src.backup(dst, pages=pages_per_step, sleep=sleep_between); dst.close(); dst = None; src.close(); src = None
        os.replace(str(tmp_path), str(final_path)); return final_path
    except BaseException:
        if dst is not None: dst.close()
        if src is not None: src.close()
        tmp_path.unlink(missing_ok=True); raise


def restore_snapshot(snapshot_dir: Path, live_db_path: str | Mapping[str, str], *, compatibility: bool | None = None) -> bool:
    paths = _snapshot_live_paths(live_db_path)
    if len(paths) == 2:
        if any(Path(path).exists() for path in paths.values()): return False
        for marker in sorted(snapshot_dir.glob("pallium-*.manifest.json"), key=lambda p: p.name, reverse=True):
            try:
                generation = json.loads(marker.read_text(encoding="utf-8"))["generation"]
                pair = {r: snapshot_dir / f"pallium-{generation}-{r}.db" for r in paths}
                if not all(_validate_snapshot(p) for p in pair.values()): continue
                for role, target in paths.items():
                    target_path = Path(target); target_path.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(str(pair[role]), str(target_path))
                    target_path.with_suffix(".db-wal").unlink(missing_ok=True); target_path.with_suffix(".db-shm").unlink(missing_ok=True)
                return True
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError): continue
        return False
    if compatibility is False: return False
    live_path = Path(paths["main"])
    if live_path.exists(): return False
    for candidate in sorted(snapshot_dir.glob("pallium-*.db"), key=lambda p: p.name, reverse=True):
        if _validate_snapshot(candidate):
            live_path.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(str(candidate), str(live_path))
            live_path.with_suffix(".db-wal").unlink(missing_ok=True); live_path.with_suffix(".db-shm").unlink(missing_ok=True); return True
    return False


def prune_old_snapshots(snapshot_dir: Path, *, keep: int) -> None:
    markers = sorted(snapshot_dir.glob("pallium-*.manifest.json"), key=lambda p: p.name, reverse=True)
    for marker in markers[keep:]:
        try:
            generation = json.loads(marker.read_text(encoding="utf-8"))["generation"]
            for role in ("main", "relay"): (snapshot_dir / f"pallium-{generation}-{role}.db").unlink(missing_ok=True)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError): pass
        marker.unlink(missing_ok=True)
    if not markers:
        for old in sorted(snapshot_dir.glob("pallium-*.db"), key=lambda p: p.name, reverse=True)[keep:]: old.unlink(missing_ok=True)


def _find_latest_snapshot(snapshot_dir: Path) -> Path | None:
    """Find the newest snapshot file in the directory."""
    snapshots = sorted(snapshot_dir.glob("pallium-*.db"), key=lambda p: p.name, reverse=True)
    return snapshots[0] if snapshots else None


def _is_dirty(live_db_path: str | Mapping[str, str], snapshot_dir: Path) -> bool:
    """Check if any live DB has been modified since the last committed snapshot."""
    paths = _snapshot_live_paths(live_db_path)
    if len(paths) == 2:
        live_mtime = max((Path(path).stat().st_mtime for path in paths.values() if Path(path).exists()), default=0)
        for path in paths.values():
            wal_path = Path(path).with_suffix(".db-wal")
            if wal_path.exists(): live_mtime = max(live_mtime, wal_path.stat().st_mtime)
        latest = max(snapshot_dir.glob("pallium-*.manifest.json"), default=None, key=lambda p: p.name)
        return live_mtime > (latest.stat().st_mtime if latest else 0)
    db_path = Path(paths["main"])
    if not db_path.exists(): return False
    db_mtime = db_path.stat().st_mtime
    wal_path = db_path.with_suffix(".db-wal")
    if wal_path.exists(): db_mtime = max(db_mtime, wal_path.stat().st_mtime)
    latest = _find_latest_snapshot(snapshot_dir)
    return latest is None or db_mtime > latest.stat().st_mtime


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

    if not snapshot_config.enabled:
        return 0

    if not snapshot_config.snapshot_path:
        emit_runtime_log("snapshot", "snapshot enabled but snapshot_path not set", stderr=True)
        return 1

    live_db_path = paired_live_paths(resolve_live_db_path(resolved_config.sqlite_url))
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
                        prune_old_snapshots(snapshot_dir, keep=snapshot_config.max_snapshots)
            except Exception as exc:
                emit_runtime_log("snapshot", f"failed: {exc}", stderr=True)
            if stop.requested or (should_stop is not None and should_stop()):
                break
            sleep_fn(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_snapshot())
