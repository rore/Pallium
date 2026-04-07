from __future__ import annotations

import sqlite3

from sqlalchemy.exc import OperationalError as SAOperationalError

_TRANSIENT_SQLITE_ERROR_SUBSTRINGS = (
    "disk i/o error",
    "database is locked",
    "database table is locked",
    "unable to open database file",
)


def is_transient_error(exc: Exception) -> bool:
    """Check if an exception is a transient error worth retrying.

    Currently covers SQLite transient errors (disk I/O, busy, locked),
    handling both raw sqlite3.OperationalError and SQLAlchemy-wrapped versions.
    """
    original = exc
    if isinstance(exc, SAOperationalError) and exc.orig is not None:
        original = exc.orig
    if not isinstance(original, sqlite3.OperationalError):
        return False
    message = str(original).lower()
    return any(s in message for s in _TRANSIENT_SQLITE_ERROR_SUBSTRINGS)
