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


class SupersessionConflictError(Exception):
    """Raised by W3 storage methods when a supersession or correction is
    attempted on a memory that is not currently active.

    Callers (typically the MCP tool boundary) surface this as HTTP 409
    Conflict so an agent that concurrently attempts the same operation
    gets a clean, retryable error rather than a corrupted supersession
    chain.

    Not a transient error — do not retry via _with_retry.
    """

