from __future__ import annotations

import argparse

import uvicorn

from app.cleaner import run_cleaner
from app.processor import run_processor
from app.runtime_logging import build_uvicorn_log_config
from app.supervisor import run_supervisor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Pallium locally")
    parser.add_argument("mode", nargs="?", choices=("all", "serve", "processor", "cleaner"), default="all")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--processors", type=int, default=1)
    parser.add_argument("--cleaners", type=int, default=1)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--processor-id", default=None)
    parser.add_argument("--cleaner-id", default=None)
    parser.add_argument("--poll-interval-seconds", type=float, default=1.0)
    parser.add_argument("--run-interval-seconds", type=float, default=None)
    parser.add_argument("--lease-seconds", type=int, default=None)
    parser.add_argument("--max-attempts", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--once", action="store_true")
    return parser


def run(args: list[str] | None = None) -> int:
    parsed = build_parser().parse_args(args)
    if parsed.mode == "serve":
        uvicorn.run(
            "app.main:app",
            host=parsed.host,
            port=parsed.port,
            reload=parsed.reload,
            log_config=build_uvicorn_log_config(component="api"),
        )
        return 0
    if parsed.mode == "processor":
        processor_args: list[str] = []
        if parsed.processor_id:
            processor_args.extend(["--processor-id", parsed.processor_id])
        processor_args.extend(["--poll-interval-seconds", str(parsed.poll_interval_seconds)])
        if parsed.lease_seconds is not None:
            processor_args.extend(["--lease-seconds", str(parsed.lease_seconds)])
        if parsed.max_attempts is not None:
            processor_args.extend(["--max-attempts", str(parsed.max_attempts)])
        if parsed.once:
            processor_args.append("--once")
        return run_processor(processor_args)
    if parsed.mode == "cleaner":
        cleaner_args: list[str] = []
        if parsed.cleaner_id:
            cleaner_args.extend(["--cleaner-id", parsed.cleaner_id])
        if parsed.run_interval_seconds is not None:
            cleaner_args.extend(["--run-interval-seconds", str(parsed.run_interval_seconds)])
        if parsed.lease_seconds is not None:
            cleaner_args.extend(["--lease-seconds", str(parsed.lease_seconds)])
        if parsed.batch_size is not None:
            cleaner_args.extend(["--batch-size", str(parsed.batch_size)])
        if parsed.once:
            cleaner_args.append("--once")
        return run_cleaner(cleaner_args)
    supervisor_args = [
        "--host",
        parsed.host,
        "--port",
        str(parsed.port),
        "--processors",
        str(parsed.processors),
        "--cleaners",
        str(parsed.cleaners),
    ]
    if parsed.reload:
        supervisor_args.append("--reload")
    return run_supervisor(supervisor_args)


if __name__ == "__main__":
    raise SystemExit(run())
