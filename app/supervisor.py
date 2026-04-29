from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from app.config import AppConfig
from app.runtime_logging import emit_runtime_log
from app.signal_context import graceful_stop
from app.snapshot import resolve_live_db_path, restore_snapshot, create_snapshot, prune_old_snapshots

# On Windows + Python 3.13, onnxruntime has a non-deterministic heap corruption
# bug during model initialization.  CREATE_NEW_PROCESS_GROUP isolates children.
_POPEN_KWARGS: dict[str, object] = {}
if sys.platform == "win32":
    _POPEN_KWARGS = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000}


def _default_popen(cmd: list[str], **kwargs) -> subprocess.Popen:
    return subprocess.Popen(cmd, **{**kwargs, **_POPEN_KWARGS})

# Supervisor restart policy: if a child crashes more than this many times
# within the window, the supervisor gives up and shuts everything down.
_MAX_RAPID_RESTARTS = 3
_RAPID_RESTART_WINDOW_SECONDS = 60.0


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


def build_snapshot_command(interval_seconds: int) -> list[str]:
    return [sys.executable, "-m", "app.snapshot", "--interval-seconds", str(interval_seconds)]


def _wait_for_api(
    host: str,
    port: int,
    *,
    timeout: float = 30.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    process: subprocess.Popen | None = None,
) -> bool:
    """Block until the API server accepts connections, or timeout/crash.

    Returns True if the API became ready, False if it exited or timed out.
    """
    import socket as _socket

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return False
        try:
            with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect((host, port))
                return True
        except (OSError, ConnectionRefusedError):
            sleep_fn(0.5)
    return False


_API_START_MAX_ATTEMPTS = 5
_API_START_BACKOFF_SECONDS = 2.0


def _start_api_with_retry(
    cmd: list[str],
    host: str,
    port: int,
    *,
    popen_factory: Callable[..., subprocess.Popen] = _default_popen,
    sleep_fn: Callable[[float], None] = time.sleep,
    stop: object | None = None,
) -> subprocess.Popen | None:
    """Start the API server, retrying on startup crashes."""
    for attempt in range(1, _API_START_MAX_ATTEMPTS + 1):
        if stop is not None and getattr(stop, "requested", False):
            return None
        proc = popen_factory(cmd, cwd=os.getcwd())
        emit_runtime_log("supervisor", f"started api pid={proc.pid} host={host} port={port} attempt={attempt}")
        if _wait_for_api(host, port, timeout=30.0, process=proc):
            return proc
        # If process is still alive but didn't bind port (slow startup), proceed
        if proc.poll() is None:
            return proc
        # Process died during startup — retry
        emit_runtime_log(
            "supervisor",
            f"api startup failed attempt={attempt}/{_API_START_MAX_ATTEMPTS} code={proc.returncode}",
            stderr=True,
        )
        if attempt < _API_START_MAX_ATTEMPTS:
            sleep_fn(_API_START_BACKOFF_SECONDS * attempt)
    return None


def run_supervisor(
    args: list[str] | None = None,
    *,
    popen_factory: Callable[..., subprocess.Popen] = _default_popen,
    sleep_fn: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    parsed = build_parser().parse_args(args)
    if parsed.reload:
        emit_runtime_log("supervisor", "supervisor mode does not support --reload in v1", stderr=True)
        return 2
    if parsed.processors < 1:
        raise ValueError("--processors must be >= 1")
    if parsed.cleaners < 0:
        raise ValueError("--cleaners must be >= 0")

    # Load config for snapshot features (non-fatal — snapshot is optional)
    try:
        config = AppConfig.from_env()
        snapshot_config = config.snapshot
    except Exception as exc:
        emit_runtime_log("supervisor", f"config load failed, snapshots disabled: {exc}", stderr=True)
        from app.config import SnapshotConfig
        config = None
        snapshot_config = SnapshotConfig()

    # Restore snapshot before spawning any children
    if snapshot_config.enabled and snapshot_config.snapshot_path:
        snapshot_dir = Path(snapshot_config.snapshot_path)
        if snapshot_dir.is_dir():
            try:
                live_db_path = resolve_live_db_path(config.sqlite_url)
                restored = restore_snapshot(snapshot_dir, live_db_path)
                if restored:
                    emit_runtime_log("supervisor", f"restored snapshot to {live_db_path}")
                else:
                    emit_runtime_log("supervisor", "snapshot restore skipped (live DB exists or no snapshots)")
            except Exception as exc:
                emit_runtime_log("supervisor", f"snapshot restore failed: {exc}", stderr=True)

    # Each managed slot: (command, label, process, restart_times)
    slots: list[_ManagedSlot] = []
    exit_code = 0

    with graceful_stop(install=True) as stop:
        try:
            # Start API with retry — onnxruntime on Windows/Python 3.13 has a
            # non-deterministic heap corruption bug during model initialization.
            # Once past startup the process is stable, so we retry until healthy.
            server_cmd = build_server_command(parsed.host, parsed.port)
            server = _start_api_with_retry(
                server_cmd, parsed.host, parsed.port,
                popen_factory=popen_factory,
                sleep_fn=sleep_fn,
                stop=stop,
            )
            if server is None:
                emit_runtime_log("supervisor", "api failed to start after retries, giving up", stderr=True)
                return 1
            slots.append(_ManagedSlot(
                command=server_cmd,
                label="api",
                process=server,
                restartable=False,
                restart_times=[],
            ))

            for index in range(1, parsed.processors + 1):
                cmd = build_processor_command(index)
                proc = popen_factory(cmd, cwd=os.getcwd())
                slots.append(_ManagedSlot(
                    command=cmd,
                    label=f"processor supervisor-processor-{index}",
                    process=proc,
                    restartable=True,
                    restart_times=[],
                ))
                emit_runtime_log("supervisor", f"started processor pid={proc.pid} processor_id=supervisor-processor-{index}")
            for index in range(1, parsed.cleaners + 1):
                cmd = build_cleaner_command(index)
                proc = popen_factory(cmd, cwd=os.getcwd())
                slots.append(_ManagedSlot(
                    command=cmd,
                    label=f"cleaner supervisor-cleaner-{index}",
                    process=proc,
                    restartable=True,
                    restart_times=[],
                ))
                emit_runtime_log("supervisor", f"started cleaner pid={proc.pid} cleaner_id=supervisor-cleaner-{index}")

            if snapshot_config.enabled and snapshot_config.snapshot_path:
                cmd = build_snapshot_command(snapshot_config.interval_seconds)
                proc = popen_factory(cmd, cwd=os.getcwd())
                slots.append(_ManagedSlot(
                    command=cmd,
                    label="snapshot",
                    process=proc,
                    restartable=True,
                    restart_times=[],
                ))
                emit_runtime_log("supervisor", f"started snapshot pid={proc.pid}")

            while True:
                if should_stop is not None and should_stop():
                    stop.requested = True
                for slot in slots:
                    return_code = slot.process.poll()
                    if return_code is None:
                        continue
                    emit_runtime_log(
                        "supervisor",
                        f"process exited pid={slot.process.pid} label={slot.label} code={return_code}",
                        stderr=return_code != 0,
                    )
                    if not slot.restartable:
                        # API server exit is always fatal
                        exit_code = return_code
                        stop.requested = True
                        break
                    # Check restart budget
                    now = clock()
                    slot.restart_times = [
                        t for t in slot.restart_times
                        if now - t < _RAPID_RESTART_WINDOW_SECONDS
                    ]
                    if len(slot.restart_times) >= _MAX_RAPID_RESTARTS:
                        emit_runtime_log(
                            "supervisor",
                            f"child {slot.label} crashed {_MAX_RAPID_RESTARTS} times "
                            f"within {_RAPID_RESTART_WINDOW_SECONDS}s, shutting down",
                            stderr=True,
                        )
                        exit_code = return_code
                        stop.requested = True
                        break
                    # Restart the child
                    slot.restart_times.append(now)
                    new_proc = popen_factory(slot.command, cwd=os.getcwd())
                    emit_runtime_log(
                        "supervisor",
                        f"restarted {slot.label} old_pid={slot.process.pid} new_pid={new_proc.pid}",
                    )
                    slot.process = new_proc
                if stop.requested:
                    break
                sleep_fn(0.1)
        finally:
            all_processes = [slot.process for slot in slots]
            for process in reversed(all_processes):
                if process.poll() is None:
                    process.terminate()
            for process in reversed(all_processes):
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

            # Best-effort shutdown snapshot
            if snapshot_config.enabled and snapshot_config.snapshot_path:
                try:
                    snapshot_dir = Path(snapshot_config.snapshot_path)
                    live_db_path = resolve_live_db_path(config.sqlite_url)
                    path = create_snapshot(
                        live_db_path, snapshot_dir,
                        pages_per_step=-1, sleep_between=0,
                    )
                    if path is not None:
                        emit_runtime_log("supervisor", f"shutdown snapshot: {path.name}")
                        prune_old_snapshots(snapshot_dir, keep=snapshot_config.max_snapshots)
                except Exception as exc:
                    emit_runtime_log(
                        "supervisor",
                        f"shutdown snapshot failed (data loss window ~{snapshot_config.interval_seconds}s): {exc}",
                        stderr=True,
                    )
    return exit_code


class _ManagedSlot:
    """Tracks a supervised child process and its restart history."""

    __slots__ = ("command", "label", "process", "restartable", "restart_times")

    def __init__(
        self,
        *,
        command: list[str],
        label: str,
        process: subprocess.Popen,
        restartable: bool,
        restart_times: list[float],
    ) -> None:
        self.command = command
        self.label = label
        self.process = process
        self.restartable = restartable
        self.restart_times = restart_times


if __name__ == "__main__":
    raise SystemExit(run_supervisor())
