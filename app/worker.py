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
from core.contracts import ItemProcessingResult
from storage.base import ThreadProcessingLease
from core.service import DEFAULT_PROCESSING_LEASE_SECONDS, DEFAULT_PROCESSING_MAX_ATTEMPTS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Pallium async ingest worker")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--poll-interval-seconds", type=float, default=1.0)
    parser.add_argument("--lease-seconds", type=int, default=DEFAULT_PROCESSING_LEASE_SECONDS)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_PROCESSING_MAX_ATTEMPTS)
    parser.add_argument("--once", action="store_true")
    return parser


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def run_worker(
    args: list[str] | None = None,
    *,
    config: AppConfig | None = None,
    sleep_fn=time.sleep,
    should_stop: Callable[[], bool] | None = None,
    install_signal_handlers: bool | None = None,
) -> int:
    parsed = build_parser().parse_args(args)
    service = build_service(config)
    worker_id = parsed.worker_id or default_worker_id()

    with graceful_stop(install=install_signal_handlers) as stop:
        try:
            while True:
                if stop.requested or (should_stop is not None and should_stop()):
                    return 0
                result = service.process_next_source_item(
                    worker_id=worker_id,
                    lease_seconds=parsed.lease_seconds,
                    max_attempts=parsed.max_attempts,
                )
                if result is not None:
                    _log_result(worker_id, result)
                    if parsed.once or stop.requested or (should_stop is not None and should_stop()):
                        return 0
                    continue
                thread_lease = service.process_next_thread_rebuild(
                    worker_id=worker_id,
                    lease_seconds=parsed.lease_seconds,
                )
                if thread_lease is not None:
                    _log_thread_rebuild(worker_id, thread_lease)
                    if parsed.once or stop.requested or (should_stop is not None and should_stop()):
                        return 0
                    continue
                if parsed.once or stop.requested or (should_stop is not None and should_stop()):
                    return 0
                sleep_fn(parsed.poll_interval_seconds)
        except KeyboardInterrupt:
            return 0


def _log_result(worker_id: str, result: ItemProcessingResult) -> None:
    emit_runtime_log(
        "processor",
        f"worker_id={worker_id} source_item={result.source_item_id} status={result.processing_status} attempts={result.processing_attempts}",
    )

def _log_thread_rebuild(worker_id: str, lease: ThreadProcessingLease) -> None:
    emit_runtime_log(
        "processor",
        f"worker_id={worker_id} thread_scope={lease.container_ref}:{lease.thread_ref} status=completed",
    )

if __name__ == "__main__":
    raise SystemExit(run_worker())
