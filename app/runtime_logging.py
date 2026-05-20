from __future__ import annotations

import io
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RuntimeLogFormatter(logging.Formatter):
    def __init__(self, component: str) -> None:
        super().__init__(fmt="%(asctime)s [%(pallium_component)s] %(message)s")
        self._component = component

    def format(self, record: logging.LogRecord) -> str:
        # Honor a per-record component (set via ``extra={"pallium_component": ...}``)
        # so propagation from one component's logger to another formatter (e.g.
        # the root FileHandler installed by ``configure_file_logging``) doesn't
        # rewrite the label. Only fall back to the formatter-level default if
        # the record carries no component of its own.
        original_component = getattr(record, "pallium_component", None)
        if original_component is None:
            record.pallium_component = self._component
        try:
            return super().format(record)
        finally:
            if original_component is None:
                delattr(record, "pallium_component")

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return datetime.fromtimestamp(record.created, timezone.utc).isoformat()


def emit_runtime_log(component: str, message: str, *, stderr: bool = False, level: int = logging.INFO) -> None:
    """Emit a `[component]` log line.

    Routes through the named logger ``pallium.runtime.<component>.<stream>`` with
    ``propagate=True`` so that any handlers attached to the root logger (e.g.
    the ``FileHandler`` installed by ``configure_file_logging``) also receive
    the record. A local ``StreamHandler`` is also attached so direct process
    output (tests, foreground CLI) keeps working when no root handler is set.

    The handler is rebuilt on each call rather than cached so that
    ``pytest``'s ``capsys`` (which swaps ``sys.stdout``/``sys.stderr`` per
    test) always sees the current stream.

    Under wscript-launched service mode (no console), the StreamHandler writes
    to a stdout/stderr that is effectively /dev/null, so the FileHandler on the
    root logger is the only sink that actually persists output. That is the
    bug this routing fixes.
    """
    logger_name = f"pallium.runtime.{component}.{'stderr' if stderr else 'stdout'}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = True
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = logging.StreamHandler(sys.stderr if stderr else sys.stdout)
    handler.setFormatter(RuntimeLogFormatter(component))
    logger.addHandler(handler)
    # Tag the record with the actual component so any other formatter that
    # receives it (e.g. the root FileHandler with formatter=RuntimeLogFormatter("service"))
    # preserves the correct ``[component]`` label instead of overwriting it.
    logger.log(level, message, extra={"pallium_component": component})


def build_uvicorn_log_config(*, component: str = "api") -> dict[str, Any]:
    formatter_path = "app.runtime_logging.RuntimeLogFormatter"
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "pallium_default": {"()": formatter_path, "component": component},
            "pallium_access": {"()": formatter_path, "component": component},
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "pallium_default",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "class": "logging.StreamHandler",
                "formatter": "pallium_access",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["access"], "level": "WARNING", "propagate": False},
        },
    }


def configure_file_logging(log_dir: Path) -> io.TextIOWrapper:
    """Configure root logger to write to a log file (for service mode).

    Returns the open log stream. Callers should pass it to ``run_supervisor``
    as ``log_stream`` so child Popen stdout/stderr inherit the *same* kernel
    File Object. On Windows, Python's ``open(path, "a")`` does not use
    ``FILE_APPEND_DATA`` — the MSVCRT runtime implements append as a
    user-space ``lseek``+``WriteFile``, which is non-atomic across distinct
    File Objects. If the supervisor's logging handler and child processes
    each opened their own handle, their writes would race and clobber each
    other (verified: supervisor's "started api pid=…" line was overwritten
    by child stdout/stderr in production). A single shared handle keeps the
    kernel file position coherent across all writers.

    Rotation happens at startup: if the log exceeds 5MB, old files are
    shifted before opening a fresh stream.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "pallium.log"

    _rotate_on_startup(log_file, max_bytes=5 * 1024 * 1024, keep=5)

    stream = open(log_file, "a", encoding="utf-8")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RuntimeLogFormatter("service"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return stream


def _rotate_on_startup(log_file: Path, *, max_bytes: int, keep: int) -> None:
    """Rotate log files at startup if the current log exceeds max_bytes."""
    if not log_file.exists():
        return
    try:
        if log_file.stat().st_size < max_bytes:
            return
    except OSError:
        return

    # Delete oldest backup if it exists
    oldest = log_file.parent / f"{log_file.stem}.log.{keep}"
    if oldest.exists():
        oldest.unlink(missing_ok=True)

    # Shift backups: .4→.5, .3→.4, ..., .1→.2
    for i in range(keep - 1, 0, -1):
        src = log_file.parent / f"{log_file.stem}.log.{i}"
        dst = log_file.parent / f"{log_file.stem}.log.{i + 1}"
        if src.exists():
            try:
                src.rename(dst)
            except OSError:
                pass

    # Current → .1
    try:
        log_file.rename(log_file.parent / f"{log_file.stem}.log.1")
    except OSError:
        pass
