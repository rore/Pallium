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
from app.transient_errors import is_transient_error
from core.contracts import ItemProcessingResult
from storage.base import ThreadProcessingLease
from core.service import DEFAULT_PROCESSING_LEASE_SECONDS, DEFAULT_PROCESSING_MAX_ATTEMPTS

MAX_REBUILD_WAIT_SECONDS = 5.0

# Transient error retry policy
_TRANSIENT_BACKOFF_BASE = 1.0
_TRANSIENT_BACKOFF_MAX = 30.0
_TRANSIENT_MAX_CONSECUTIVE = 10


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Pallium async ingest worker")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--poll-interval-seconds", type=float, default=0.2)
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
    clock: Callable[[], float] = time.monotonic,
) -> int:
    parsed = build_parser().parse_args(args)
    service = build_service(config, enable_vector=False)
    worker_id = parsed.worker_id or default_worker_id()
    last_rebuild_check = clock()

    process_next_item = service.process_next_source_item_summary
    if "process_next_source_item" in vars(service):
        process_next_item = service.process_next_source_item

    def _stopping() -> bool:
        return stop.requested or (should_stop is not None and should_stop())

    def _try_thread_rebuild() -> bool:
        thread_lease = service.process_next_thread_rebuild(
            worker_id=worker_id,
            lease_seconds=parsed.lease_seconds,
        )
        if thread_lease is not None:
            _log_thread_rebuild(worker_id, thread_lease)
            return True
        return False

    consecutive_transient_errors = 0

    with graceful_stop(install=install_signal_handlers) as stop:
        try:
            while True:
                if _stopping():
                    return 0
                try:
                    result = process_next_item(
                        worker_id=worker_id,
                        lease_seconds=parsed.lease_seconds,
                        max_attempts=parsed.max_attempts,
                    )
                    if result is not None:
                        _log_result(worker_id, result)
                        if parsed.once or _stopping():
                            return 0
                        if clock() - last_rebuild_check >= MAX_REBUILD_WAIT_SECONDS:
                            _try_thread_rebuild()
                            last_rebuild_check = clock()
                        continue
                    if _try_thread_rebuild():
                        last_rebuild_check = clock()
                        if parsed.once or _stopping():
                            return 0
                        continue
                except Exception as exc:
                    if not is_transient_error(exc):
                        raise
                    consecutive_transient_errors += 1
                    backoff = min(
                        _TRANSIENT_BACKOFF_MAX,
                        _TRANSIENT_BACKOFF_BASE * (2 ** (consecutive_transient_errors - 1)),
                    )
                    emit_runtime_log(
                        "processor",
                        f"worker_id={worker_id} transient_error={exc} "
                        f"consecutive={consecutive_transient_errors} backoff={backoff:.1f}s",
                        stderr=True,
                    )
                    if consecutive_transient_errors >= _TRANSIENT_MAX_CONSECUTIVE:
                        emit_runtime_log(
                            "processor",
                            f"worker_id={worker_id} giving up after {consecutive_transient_errors} "
                            f"consecutive transient errors",
                            stderr=True,
                        )
                        return 1
                    sleep_fn(backoff)
                    continue
                consecutive_transient_errors = 0
                if parsed.once or _stopping():
                    return 0
                sleep_fn(parsed.poll_interval_seconds)
        except KeyboardInterrupt:
            return 0


def _log_result(worker_id: str, result: ItemProcessingResult) -> None:
    message = (
        f"worker_id={worker_id} source_item={result.source_item_id} "
        f"status={result.processing_status} attempts={result.processing_attempts}"
    )
    if result.packages_processed:
        message = f"{message} packages={','.join(result.packages_processed)}"
    if result.failure_category:
        message = f"{message} failure_category={result.failure_category}"
    if result.processing_error:
        compact_error = " ".join(result.processing_error.split())
        if len(compact_error) > 300:
            compact_error = f"{compact_error[:297]}..."
        message = f"{message} processing_error={compact_error}"
    emit_runtime_log("processor", message)

def _log_thread_rebuild(worker_id: str, lease: ThreadProcessingLease) -> None:
    emit_runtime_log(
        "processor",
        f"worker_id={worker_id} thread_scope={lease.container_ref}:{lease.thread_ref} status=completed",
    )

if __name__ == "__main__":
    raise SystemExit(run_worker())
