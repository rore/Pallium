"""Offline wake-store initialization at supported single-owner boundaries."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from app.codex_wake import legacy_codex_wake_directory
from core.codex_wake import CodexWakeRegistry
from core.relay import RelayService


def _present(path: Path) -> bool:
    try:
        path.stat()
        return True
    except FileNotFoundError:
        return False


def _paths(config):
    if config.storage_backend != "sqlite":
        return None
    relay_url = config.resolved_relay_sqlite_url
    if relay_url == "sqlite:///:memory:":
        return None
    return (Path(config.sqlite_url.removeprefix("sqlite:///")),
            Path(relay_url.removeprefix("sqlite:///")),
            legacy_codex_wake_directory(relay_url) / "reservations.json")


def _marker_present(database: Path) -> bool:
    try:
        return _read_marker(database)
    except sqlite3.Error as exc:
        raise RuntimeError("Cannot inspect Codex wake SQLite authority") from exc


def _read_marker(database: Path) -> bool:
    """Read without schema bootstrap or creating an absent database."""
    if not _present(database):
        return False
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        table = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='relay_codex_wake_state'").fetchone()
        if table is None:
            return False
        rows = connection.execute("SELECT id, generation FROM relay_codex_wake_state LIMIT 2").fetchall()
        if not rows:
            return False
        if len(rows) != 1 or rows[0][0] != 1 or type(rows[0][1]) is not int or not 0 <= rows[0][1] < 2**63:
            raise RuntimeError("invalid Codex wake migration authority")
        return True


def _initialize_and_verify(config, legacy: Path) -> None:
    from storage.sqlite import SQLiteStorageProvider

    storage = SQLiteStorageProvider(config.sqlite_url, config.resolved_relay_sqlite_url)
    try:
        registry = CodexWakeRegistry(relay_service=RelayService(storage), legacy_state_dir=legacy.parent)
        if not registry.initialize(old_owner_drained=True) or not registry.usable:
            raise RuntimeError("Codex wake initialization failed; service remains stopped")
    finally:
        storage.close()


def prepare_codex_wake_start(config, *, owner_lock=None) -> None:
    """Auto-initialize genuinely fresh stores; never auto-import an old store."""
    paths = _paths(config)
    if paths is None:
        return
    main, relay, legacy = paths
    if _marker_present(relay):
        return
    if any(_present(path) for path in paths):
        raise RuntimeError("Existing Codex wake store requires the one-time offline 'pallium service initialize-wakes' upgrade")
    from app.cli.service import _PalliumLock, _pallium_home

    lock = owner_lock or _PalliumLock(_pallium_home() / "run" / "pallium.lock")
    acquired = owner_lock is None
    if acquired and not lock.acquire():
        raise RuntimeError("Pallium owner lock is busy; wake initialization refused")
    if lock._fd is None:
        raise RuntimeError("Pallium owner lock is not held")
    try:
        if _marker_present(relay):
            return
        if any(_present(path) for path in paths):
            raise RuntimeError("Wake store appeared during initialization; offline upgrade required")
        _initialize_and_verify(config, legacy)
    finally:
        if acquired:
            lock.release()


def assert_codex_wake_install_ready(config) -> None:
    """Preserve old launcher/unit metadata until required offline import ends."""
    paths = _paths(config)
    if paths is not None and not _marker_present(paths[1]) and any(_present(path) for path in paths):
        raise RuntimeError("Offline 'pallium service initialize-wakes' upgrade required before reinstalling")


def initialize_codex_wakes_offline(config, home: Path, *, foreground_quiescent: bool = False) -> None:
    """Installed stop proof or explicit operator quiescence precedes import."""
    paths = _paths(config)
    if paths is None:
        return
    from app.cli.service import _PalliumLock, assert_service_stopped

    lock = _PalliumLock(home / "run" / "pallium.lock")
    if not lock.acquire():
        raise RuntimeError("Pallium owner lock is busy; offline import refused")
    try:
        if not foreground_quiescent:
            assert_service_stopped(home)
        _initialize_and_verify(config, paths[2])
    finally:
        lock.release()
