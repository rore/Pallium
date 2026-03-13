from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Pallium API with supervised worker processes")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--reload", action="store_true")
    return parser


def build_server_command(host: str, port: int) -> list[str]:
    return [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port)]


def build_worker_command(index: int) -> list[str]:
    return [sys.executable, "-m", "app.worker", "--worker-id", f"supervisor-worker-{index}"]


def run_supervisor(
    args: list[str] | None = None,
    *,
    popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    sleep_fn: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    parsed = build_parser().parse_args(args)
    if parsed.reload:
        print("supervisor mode does not support --reload in v1", file=sys.stderr, flush=True)
        return 2
    if parsed.workers < 1:
        raise ValueError("--workers must be >= 1")

    processes: list[subprocess.Popen] = []
    exit_code = 0
    stop_requested = False

    def request_stop(_signum=None, _frame=None) -> None:
        nonlocal stop_requested
        stop_requested = True

    previous_sigint = signal.signal(signal.SIGINT, request_stop)
    previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
    try:
        server = popen_factory(build_server_command(parsed.host, parsed.port), cwd=os.getcwd())
        processes.append(server)
        print(f"started api pid={server.pid} host={parsed.host} port={parsed.port}", flush=True)
        for index in range(1, parsed.workers + 1):
            worker = popen_factory(build_worker_command(index), cwd=os.getcwd())
            processes.append(worker)
            print(f"started worker pid={worker.pid} worker_id=supervisor-worker-{index}", flush=True)

        while True:
            if should_stop is not None and should_stop():
                stop_requested = True
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    print(f"process exited pid={process.pid} code={return_code}", flush=True)
                    exit_code = return_code
                    stop_requested = True
                    break
            if stop_requested:
                break
            sleep_fn(0.1)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in reversed(processes):
            if process.poll() is None:
                process.wait(timeout=5)
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run_supervisor())
