from __future__ import annotations

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
        original_component = getattr(record, "pallium_component", None)
        record.pallium_component = self._component
        try:
            return super().format(record)
        finally:
            if original_component is None:
                delattr(record, "pallium_component")
            else:
                record.pallium_component = original_component

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return datetime.fromtimestamp(record.created, timezone.utc).isoformat()


def emit_runtime_log(component: str, message: str, *, stderr: bool = False, level: int = logging.INFO) -> None:
    logger_name = f"pallium.runtime.{component}.{'stderr' if stderr else 'stdout'}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = logging.StreamHandler(sys.stderr if stderr else sys.stdout)
    handler.setFormatter(RuntimeLogFormatter(component))
    logger.addHandler(handler)
    logger.log(level, message)


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


def configure_file_logging(log_dir: Path) -> None:
    """Configure root logger to write to a log file (for service mode).

    Rotation happens at startup: if the log exceeds 5MB, old files are
    shifted before opening a fresh one. This avoids conflicts with child
    processes that share the same file handle.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "pallium.log"

    _rotate_on_startup(log_file, max_bytes=5 * 1024 * 1024, keep=5)

    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(RuntimeLogFormatter("service"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


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
