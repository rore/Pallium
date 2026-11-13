"""Paced, supervisor-owned expiry of an existing Relay database."""
from __future__ import annotations

import argparse
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.exc import OperationalError

from app.runtime_logging import emit_runtime_log
from app.signal_context import graceful_stop
from core.errors import ImmediateTransactionBusyError, is_transient_error
from storage.sqlite import SQLiteStorageProvider

_WINDOW_YIELD_SECONDS = 0.05
_CONTENTION_DEFER_SECONDS = 0.25
_SWEEP_IDLE_SECONDS = 1.0
_TRANSIENT_MAX_CONSECUTIVE = 10


def _contention(error):
    if isinstance(error, ImmediateTransactionBusyError):
        return True
    original = error.orig if isinstance(error, OperationalError) else error
    if not isinstance(original, sqlite3.OperationalError):
        return False
    code = getattr(original, "sqlite_errorcode", None)
    if type(code) is int:
        return code & 255 in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    return str(original).lower() in {"database is locked", "database table is locked"}


def run_cleaner(args: list[str] | None = None, *, sleep_fn: Callable[[float], None] = time.sleep,
                should_stop: Callable[[], bool] | None = None,
                install_signal_handlers: bool | None = None) -> int:
    parser = argparse.ArgumentParser(description="Expire Relay deliveries in bounded, paced windows")
    parser.add_argument("--database-url", required=True, help="Existing file-backed Relay SQLite database")
    parser.add_argument("--once", action="store_true", help="Attempt one bounded window, not a complete sweep")
    parsed = parser.parse_args(args)
    storage = None
    with graceful_stop(install=install_signal_handlers) as stop:
        def stopping():
            return stop.requested or (should_stop is not None and should_stop())

        after_id = upper_id = cutoff = None
        transient_errors = scanned = expired = 0
        state = "running"
        try:
            if stopping():
                return 0
            storage = SQLiteStorageProvider.open_relay_maintenance(parsed.database_url)
            emit_runtime_log("relay-expiry-cleaner", "outcome=started")
            while not stopping():
                if cutoff is None:
                    cutoff = datetime.now(timezone.utc)
                try:
                    result = storage.relay_expire_window(after_id=after_id, upper_id=upper_id,
                                                        cutoff=cutoff, limit=64, should_stop=stopping)
                except InterruptedError:
                    if stopping():
                        return 0
                    raise
                except Exception as exc:
                    busy = _contention(exc)
                    if not busy and not is_transient_error(exc):
                        raise
                    if not busy:
                        transient_errors += 1
                    next_state = "deferred" if busy else "transient_error"
                    if state != next_state:
                        emit_runtime_log("relay-expiry-cleaner", f"outcome={next_state} error_type={type(exc).__name__}")
                    state = next_state
                    if parsed.once or transient_errors >= _TRANSIENT_MAX_CONSECUTIVE:
                        return 1
                    delay = _CONTENTION_DEFER_SECONDS
                else:
                    if state != "running":
                        emit_runtime_log("relay-expiry-cleaner", "outcome=resumed")
                    state = "running"
                    transient_errors = 0
                    after_id, upper_id = result["after_id"], result["upper_id"]
                    scanned += result["scanned"]
                    expired += result["expired"]
                    if result["sweep_complete"]:
                        if expired:
                            emit_runtime_log("relay-expiry-cleaner", f"outcome=sweep_complete scanned={scanned} expired={expired}")
                        after_id = upper_id = cutoff = None
                        scanned = expired = 0
                        delay = _SWEEP_IDLE_SECONDS
                    else:
                        delay = _WINDOW_YIELD_SECONDS
                    if parsed.once:
                        return 0
                if stopping():
                    return 0
                sleep_fn(delay)
            return 0
        except Exception as exc:
            emit_runtime_log("relay-expiry-cleaner", f"outcome=failed error_type={type(exc).__name__}", stderr=True)
            return 1
        finally:
            if storage is not None:
                storage.close()
                emit_runtime_log("relay-expiry-cleaner", "outcome=stopped")


if __name__ == "__main__":
    raise SystemExit(run_cleaner())
