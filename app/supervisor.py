from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Callable

from app.runtime_logging import emit_runtime_log
from app.signal_context import graceful_stop


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Pallium API with supervised background processors")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--processors", "--workers", dest="processors", type=int, default=1)
    parser.add_argument("--cleaners", type=int, default=1)
    parser.add_argument("--reload", action="store_true")
    return parser


def build_server_command(host: str, port: int) -> list[str]:
    return [sys.executable, "-m", "app.run", "serve", "--host", host, "--port", str(port)]


def build_processor_command(index: int) -> list[str]:
    return [sys.executable, "-m", "app.processor", "--processor-id", f"supervisor-processor-{index}"]


def build_cleaner_command(index: int) -> list[str]:
    return [sys.executable, "-m", "app.cleaner", "--cleaner-id", f"supervisor-cleaner-{index}"]


def run_supervisor(
    args: list[str] | None = None,
    *,
    popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    sleep_fn: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    parsed = build_parser().parse_args(args)
    if parsed.reload:
        emit_runtime_log("supervisor", "supervisor mode does not support --reload in v1", stderr=True)
        return 2
    if parsed.processors < 1:
        raise ValueError("--processors must be >= 1")
    if parsed.cleaners < 0:
        raise ValueError("--cleaners must be >= 0")

    processes: list[subprocess.Popen] = []
    exit_code = 0

    with graceful_stop(install=True) as stop:
        try:
            server = popen_factory(build_server_command(parsed.host, parsed.port), cwd=os.getcwd())
            processes.append(server)
            emit_runtime_log("supervisor", f"started api pid={server.pid} host={parsed.host} port={parsed.port}")
            for index in range(1, parsed.processors + 1):
                processor = popen_factory(build_processor_command(index), cwd=os.getcwd())
                processes.append(processor)
                emit_runtime_log("supervisor", f"started processor pid={processor.pid} processor_id=supervisor-processor-{index}")
            for index in range(1, parsed.cleaners + 1):
                cleaner = popen_factory(build_cleaner_command(index), cwd=os.getcwd())
                processes.append(cleaner)
                emit_runtime_log("supervisor", f"started cleaner pid={cleaner.pid} cleaner_id=supervisor-cleaner-{index}")

            while True:
                if should_stop is not None and should_stop():
                    stop.requested = True
                for process in processes:
                    return_code = process.poll()
                    if return_code is not None:
                        emit_runtime_log("supervisor", f"process exited pid={process.pid} code={return_code}", stderr=return_code != 0)
                        exit_code = return_code
                        stop.requested = True
                        break
                if stop.requested:
                    break
                sleep_fn(0.1)
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
            for process in reversed(processes):
                if process.poll() is None:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        emit_runtime_log(
                            "supervisor",
                            f"forcing process shutdown pid={process.pid} after terminate timeout",
                            stderr=True,
                        )
                        process.kill()
                        process.wait(timeout=5)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run_supervisor())
