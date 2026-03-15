from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
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
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }
