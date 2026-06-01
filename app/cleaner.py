from __future__ import annotations

import argparse
import os
import socket
import time
from collections.abc import Callable

from app.config import AppConfig
from app.dependencies import build_service
from app.runtime_logging import emit_runtime_log
from app.signal_context import graceful_stop
from core.errors import is_transient_error
from storage.base import RetentionLeaseLostError, RetentionRunStats

_TRANSIENT_MAX_CONSECUTIVE = 10


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Pallium retention cleaner")
    parser.add_argument("--cleaner-id", default=None)
    parser.add_argument("--run-interval-seconds", type=float, default=None)
    parser.add_argument("--lease-seconds", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--once", action="store_true")
    return parser


def default_cleaner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:cleaner"


def run_cleaner(
    args: list[str] | None = None,
    *,
    config: AppConfig | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] | None = None,
    install_signal_handlers: bool | None = None,
) -> int:
    parsed = build_parser().parse_args(args)
    resolved_config = config or AppConfig.from_env()
    service = build_service(resolved_config, enable_vector=False).service
    cleaner_id = parsed.cleaner_id or default_cleaner_id()
    run_interval_seconds = parsed.run_interval_seconds if parsed.run_interval_seconds is not None else resolved_config.retention.run_interval_seconds
    lease_seconds = parsed.lease_seconds if parsed.lease_seconds is not None else resolved_config.retention.lease_seconds
    batch_size = parsed.batch_size if parsed.batch_size is not None else resolved_config.retention.batch_size

    consecutive_transient_errors = 0

    with graceful_stop(install=install_signal_handlers) as stop:
        try:
            while True:
                if stop.requested or (should_stop is not None and should_stop()):
                    return 0
                try:
                    stats = service.run_retention_pass(
                        worker_id=cleaner_id,
                        lease_seconds=lease_seconds,
                        batch_size=batch_size,
                    )
                except RetentionLeaseLostError as exc:
                    emit_runtime_log("cleaner", f"cleaner_id={cleaner_id} retention lease lost error={exc}", stderr=True)
                    if parsed.once:
                        return 1
                    if stop.requested or (should_stop is not None and should_stop()):
                        return 0
                    sleep_fn(run_interval_seconds)
                    continue
                except Exception as exc:
                    if not is_transient_error(exc):
                        raise
                    consecutive_transient_errors += 1
                    emit_runtime_log(
                        "cleaner",
                        f"cleaner_id={cleaner_id} transient_error={exc} "
                        f"consecutive={consecutive_transient_errors}",
                        stderr=True,
                    )
                    if consecutive_transient_errors >= _TRANSIENT_MAX_CONSECUTIVE:
                        emit_runtime_log(
                            "cleaner",
                            f"cleaner_id={cleaner_id} giving up after "
                            f"{consecutive_transient_errors} consecutive transient errors",
                            stderr=True,
                        )
                        return 1
                    if parsed.once:
                        return 1
                    if stop.requested or (should_stop is not None and should_stop()):
                        return 0
                    sleep_fn(run_interval_seconds)
                    continue
                consecutive_transient_errors = 0
                if stats is not None:
                    _log_retention_stats(cleaner_id, stats)
                    if parsed.once:
                        return 0
                elif parsed.once:
                    return 0
                if stop.requested or (should_stop is not None and should_stop()):
                    return 0
                sleep_fn(run_interval_seconds)
        except KeyboardInterrupt:
            return 0


def _log_retention_stats(cleaner_id: str, stats: RetentionRunStats) -> None:
    emit_runtime_log(
        "cleaner",
        (
            f"cleaner_id={cleaner_id} retention deleted_source_items={stats.deleted_source_items} "
            f"deleted_memory_objects={stats.deleted_memory_objects} "
            f"deleted_relations={stats.deleted_relations} "
            f"deleted_index_entries={stats.deleted_index_entries} "
            f"stripped_debug_metadata={stats.stripped_debug_metadata} "
            f"skipped_protected_source_items={stats.skipped_protected_source_items}"
        ),
    )


if __name__ == "__main__":
    raise SystemExit(run_cleaner())
