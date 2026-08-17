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


class ForgetAuthorizationError(PermissionError):
    """Raised when a caller is not authorized to forget a raw source turn.

    Raw-turn forgetting is a destructive mutation. Authorization is
    workspace/container-scoped: the caller's container scope must match the
    target turn's container. Missing caller scope is allowed only in
    single-user trusted (compatibility) mode; a *supplied-but-mismatched*
    scope is always denied. Storage enforces the predicate atomically inside
    its write transaction (raising the builtin ``PermissionError`` before any
    ``forgotten_at`` is written); the service re-raises that as this defined
    domain error and the HTTP/MCP boundary surfaces it as 403.

    Subclasses ``PermissionError`` so a storage-level ``PermissionError`` is
    caught uniformly. Not a transient error — never retried by _with_retry.
    """

