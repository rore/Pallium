from __future__ import annotations

import argparse
import os
import signal
import socket
import threading
import time
from collections.abc import Callable

from app.config import AppConfig
from app.dependencies import build_service
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

    stop_requested = False

    def request_stop(_signum=None, _frame=None) -> None:
        nonlocal stop_requested
        stop_requested = True

    if install_signal_handlers is None:
        install_signal_handlers = threading.current_thread() is threading.main_thread()

    previous_sigint = None
    previous_sigterm = None
    if install_signal_handlers:
        previous_sigint = signal.signal(signal.SIGINT, request_stop)
        previous_sigterm = signal.signal(signal.SIGTERM, request_stop)

    try:
        while True:
            if stop_requested or (should_stop is not None and should_stop()):
                return 0
            result = service.process_next_source_item(
                worker_id=worker_id,
                lease_seconds=parsed.lease_seconds,
                max_attempts=parsed.max_attempts,
            )
            if result is not None:
                _log_result(worker_id, result)
                if parsed.once or stop_requested or (should_stop is not None and should_stop()):
                    return 0
                continue
            thread_lease = service.process_next_thread_rebuild(
                worker_id=worker_id,
                lease_seconds=parsed.lease_seconds,
            )
            if thread_lease is not None:
                _log_thread_rebuild(worker_id, thread_lease)
                if parsed.once or stop_requested or (should_stop is not None and should_stop()):
                    return 0
                continue
            if parsed.once or stop_requested or (should_stop is not None and should_stop()):
                return 0
            sleep_fn(parsed.poll_interval_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        if install_signal_handlers:
            signal.signal(signal.SIGINT, previous_sigint)
            signal.signal(signal.SIGTERM, previous_sigterm)


def _log_result(worker_id: str, result: ItemProcessingResult) -> None:
    print(
        f"[{worker_id}] source_item={result.source_item_id} status={result.processing_status} attempts={result.processing_attempts}",
        flush=True,
    )


def _log_thread_rebuild(worker_id: str, lease: ThreadProcessingLease) -> None:
    print(
        f"[{worker_id}] thread_scope={lease.container_ref}:{lease.thread_ref} status=completed",
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(run_worker())
