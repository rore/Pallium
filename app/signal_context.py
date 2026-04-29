"""Shared signal-handling context manager for daemon-like workers."""

from __future__ import annotations

import signal
import sys
import threading
from contextlib import contextmanager
from collections.abc import Generator


@contextmanager
def graceful_stop(
    *,
    install: bool | None = None,
) -> Generator[object, None, None]:
    """Context manager that installs SIGINT/SIGTERM handlers and exposes a stop flag.

    Usage::

        with graceful_stop() as stop:
            while not stop.requested:
                ...  # do work

    The ``install`` parameter controls whether signal handlers are registered.
    When *None* (default), handlers are only installed on the main thread.
    """
    if install is None:
        install = threading.current_thread() is threading.main_thread()

    class _StopFlag:
        __slots__ = ("requested",)

        def __init__(self) -> None:
            self.requested = False

    flag = _StopFlag()

    def _handler(_signum=None, _frame=None) -> None:
        flag.requested = True

    prev_int = None
    prev_term = None
    prev_break = None
    if install:
        prev_int = signal.signal(signal.SIGINT, _handler)
        prev_term = signal.signal(signal.SIGTERM, _handler)
        if sys.platform == "win32" and hasattr(signal, "SIGBREAK"):
            prev_break = signal.signal(signal.SIGBREAK, _handler)
    try:
        yield flag
    finally:
        if install:
            signal.signal(signal.SIGINT, prev_int)
            signal.signal(signal.SIGTERM, prev_term)
            if prev_break is not None:
                signal.signal(signal.SIGBREAK, prev_break)
