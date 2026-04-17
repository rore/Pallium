from __future__ import annotations

import argparse
import socket

from app.config import AppConfig
from app.worker import run_worker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Pallium async ingest processor")
    parser.add_argument("--processor-id", default=None)
    parser.add_argument("--poll-interval-seconds", type=float, default=0.2)
    parser.add_argument("--lease-seconds", type=int, default=None)
    parser.add_argument("--max-attempts", type=int, default=None)
    parser.add_argument("--once", action="store_true")
    return parser


def default_processor_id() -> str:
    return f"{socket.gethostname()}:{__name__}"


def run_processor(args: list[str] | None = None, *, config: AppConfig | None = None, sleep_fn=None) -> int:
    parsed = build_parser().parse_args(args)
    worker_args: list[str] = []
    processor_id = parsed.processor_id or default_processor_id()
    worker_args.extend(["--worker-id", processor_id])
    worker_args.extend(["--poll-interval-seconds", str(parsed.poll_interval_seconds)])
    if parsed.lease_seconds is not None:
        worker_args.extend(["--lease-seconds", str(parsed.lease_seconds)])
    if parsed.max_attempts is not None:
        worker_args.extend(["--max-attempts", str(parsed.max_attempts)])
    if parsed.once:
        worker_args.append("--once")
    if sleep_fn is None:
        return run_worker(worker_args, config=config)
    return run_worker(worker_args, config=config, sleep_fn=sleep_fn)


if __name__ == "__main__":
    raise SystemExit(run_processor())
