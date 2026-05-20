from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO

from app.config import AppConfig
from app.runtime_logging import emit_runtime_log
from app.signal_context import graceful_stop
from app.snapshot import resolve_live_db_path, restore_snapshot, create_snapshot, prune_old_snapshots

# On Windows + Python 3.13, onnxruntime has a non-deterministic heap corruption
# bug during model initialization.  CREATE_NEW_PROCESS_GROUP isolates children.
# On POSIX, start_new_session puts each child in its own process group so we
# can kill the whole tree via killpg without taking the supervisor down.
_POPEN_KWARGS: dict[str, object] = {}
if sys.platform == "win32":
    _POPEN_KWARGS = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000}
else:
    _POPEN_KWARGS = {"start_new_session": True}


def _default_popen(cmd: list[str], **kwargs) -> subprocess.Popen:
    return subprocess.Popen(cmd, **{**kwargs, **_POPEN_KWARGS})


# taskkill exit codes considered "successful kill or already gone":
# 0   = killed
# 128 = process not found (already exited — Windows error 128 surfaces here for /PID targets)
# Code 1 is NOT included: it means "could not be terminated" (permission denied or
# generic failure for /PID targets) and treating it as success would silently mask
# a real failure on low-privilege Scheduled Task accounts.
_TASKKILL_SUCCESS_CODES = frozenset({0, 128})


def _kill_tree(
    process: subprocess.Popen,
    *,
    force: bool = False,
    wait_timeout: float = 5.0,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    killpg: Callable[[int, int], None] | None = None,
    log: Callable[[str, str], None] | None = None,
) -> None:
    """Kill ``process`` and all of its descendants, then reap.

    Cross-platform process-tree kill that closes the gap left by
    ``Popen.terminate()``/``.kill()`` on Windows: those use
    ``TerminateProcess`` which is non-recursive, so when the spawned binary is
    a launcher trampoline (e.g. uv's venv ``python.exe`` redirector) the real
    interpreter survives and keeps holding sockets/files.

    - Windows: ``taskkill /T [/F] /PID``. ``/T`` walks the parent-child tree
      recorded by Windows.
    - POSIX:   ``killpg`` on the child's process group. Requires that the
      child was spawned with ``start_new_session=True`` (handled by
      ``_default_popen``).

    Pass ``wait_timeout=0`` to skip the post-kill ``process.wait`` (used by the
    finally block to fan out signals before waiting in parallel). Tolerates
    "already dead" states without raising.
    """
    if process is None:
        return
    pid = process.pid

    if sys.platform == "win32":
        cmd = ["taskkill", "/T", "/PID", str(pid)]
        if force:
            cmd.insert(1, "/F")
        try:
            run_timeout = wait_timeout if wait_timeout > 0 else 5.0
            result = runner(cmd, capture_output=True, timeout=run_timeout, check=False)
            if result.returncode not in _TASKKILL_SUCCESS_CODES:
                if log is not None:
                    log(
                        "supervisor",
                        f"taskkill returned unexpected code {result.returncode} "
                        f"for pid={pid}: {result.stderr.decode(errors='replace').strip()}",
                    )
        except subprocess.TimeoutExpired:
            if log is not None:
                log("supervisor", f"taskkill timed out for pid={pid}")
        except (OSError, FileNotFoundError) as exc:
            # taskkill missing or unspawnable — fall back to direct kill
            if log is not None:
                log("supervisor", f"taskkill unavailable ({exc}); falling back to process.kill")
            try:
                process.kill()
            except OSError:
                pass
    else:
        sig = signal.SIGKILL if force else signal.SIGTERM
        _killpg = killpg if killpg is not None else os.killpg
        try:
            pgid = os.getpgid(pid)
            _killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            # Process already gone or different session — fall back to direct kill
            try:
                if force:
                    process.kill()
                else:
                    process.terminate()
            except OSError:
                pass
        except OSError as exc:
            if log is not None:
                log("supervisor", f"killpg failed for pid={pid}: {exc}")
            try:
                if force:
                    process.kill()
                else:
                    process.terminate()
            except OSError:
                pass

    if wait_timeout > 0:
        try:
            process.wait(timeout=wait_timeout)
        except subprocess.TimeoutExpired:
            if log is not None:
                log("supervisor", f"process pid={pid} did not exit within {wait_timeout}s after kill")
        except OSError:
            pass

# Supervisor restart policy: if a child crashes more than this many times
# within the window, the supervisor gives up and shuts everything down.
_MAX_RAPID_RESTARTS = 3
_RAPID_RESTART_WINDOW_SECONDS = 60.0

# Health probe: periodically TCP-connect to the API to detect the WinError 64
# stuck-socket case (process alive but accept loop dead).
_API_HEALTH_PROBE_INTERVAL = 30.0   # seconds between probes
_API_HEALTH_PROBE_FAIL_THRESHOLD = 2  # consecutive failures before kill


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
    expected_nonce: str | None = None,
    run_dir: Path | None = None,
    grace_period: float = 3.0,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Block until the API server accepts connections, or timeout/crash.

    Returns True if the API became ready, False if it exited or timed out.

    When ``expected_nonce`` and ``run_dir`` are provided, the probe goes
    beyond a TCP connection check: after the port accepts, it reads
    ``{run_dir}/api_token`` and verifies the JSON ``nonce`` matches the value
    we passed via ``PALLIUM_API_LAUNCH_TOKEN``. This rejects orphan
    "previous-generation" processes that are still bound to the port from a
    prior supervisor run.

    The grace period exists to cover the small window between uvicorn's port
    bind and the lifespan startup writing the token (typically sub-second).
    It is **disabled** the moment we see any wrong-nonce token during the
    probe, because that proves a foreign process is bound — and an orphan
    racing its own lifespan-finally cleanup could otherwise launder a stale
    bind into a successful probe via the missing-file path.
    """
    import socket as _socket

    deadline = clock() + timeout
    tcp_first_seen: float | None = None
    foreign_bind_seen = False
    while clock() < deadline:
        if process is not None and process.poll() is not None:
            return False
        try:
            with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect((host, port))
        except (OSError, ConnectionRefusedError):
            sleep_fn(0.5)
            continue

        # TCP succeeded.
        if expected_nonce is None or run_dir is None:
            return True  # legacy / no self-id requested

        token_path = run_dir / "api_token"
        token_match = _check_token(token_path, expected_nonce)
        if token_match is True:
            return True
        if token_match is False:
            # Mismatched nonce — definitive proof of a foreign bind. Never
            # trust the missing-token grace path after seeing this; if the
            # orphan deletes the file mid-probe, we must not silently accept.
            foreign_bind_seen = True
        else:
            # token_match is None: file absent or unreadable. Apply the grace
            # period only if we have NOT seen a foreign-bind marker.
            if not foreign_bind_seen:
                now = clock()
                if tcp_first_seen is None:
                    tcp_first_seen = now
                elif now - tcp_first_seen >= grace_period:
                    return True
        sleep_fn(0.5)
    return False


def _check_token(token_path: Path, expected_nonce: str) -> bool | None:
    """Return True if token file matches, False on mismatch, None if absent/unreadable.

    Reads the file directly without a prior ``exists()`` check to avoid TOCTOU
    on Windows where atomic ``os.replace`` can swap the file between checks.
    Any read failure (FileNotFoundError, partial JSON, permission error) is
    treated uniformly as "absent" so the caller's grace-period logic governs.
    """
    try:
        data = json.loads(token_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return False
    return data.get("nonce") == expected_nonce


_API_START_MAX_ATTEMPTS = 5
_API_START_BACKOFF_SECONDS = 2.0


def _pallium_run_dir() -> Path:
    """Resolve the runtime directory where the API writes its launch token.

    Uses ``PALLIUM_HOME`` if set, otherwise falls back to ``~/.pallium``.
    Both supervisor and child API process compute this identically — they
    inherit the same environment.
    """
    home_env = os.environ.get("PALLIUM_HOME")
    home = Path(home_env) if home_env else Path.home() / ".pallium"
    return home / "run"


def _generate_launch_token() -> str:
    return secrets.token_urlsafe(16)


def _tcp_probe(host: str, port: int) -> bool:
    """Return True if a TCP connection to host:port succeeds, False otherwise."""
    import socket as _socket
    try:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect((host, port))
            return True
    except OSError:
        return False


def _start_api_with_retry(
    cmd: list[str],
    host: str,
    port: int,
    *,
    popen_factory: Callable[..., subprocess.Popen] = _default_popen,
    sleep_fn: Callable[[float], None] = time.sleep,
    wait_for_api_fn: Callable[..., bool] = _wait_for_api,  # pass lambda *_, **__: True in tests
    stop: object | None = None,
    run_dir: Path | None = None,
    token_fn: Callable[[], str] = _generate_launch_token,
) -> subprocess.Popen | None:
    """Start the API server, retrying on startup crashes.

    Each attempt mints a fresh launch token via ``token_fn`` and exports it as
    ``PALLIUM_API_LAUNCH_TOKEN`` to the child environment. ``wait_for_api_fn``
    receives ``expected_nonce`` and ``run_dir`` so it can refuse to mistake an
    orphan from a prior generation for our new child. The token is also
    threaded through retries so a stale token from a crashed previous attempt
    can never be confused for the next one.
    """
    if run_dir is None:
        run_dir = _pallium_run_dir()
    for attempt in range(1, _API_START_MAX_ATTEMPTS + 1):
        if stop is not None and getattr(stop, "requested", False):
            return None
        nonce = token_fn()
        env = {**os.environ, "PALLIUM_API_LAUNCH_TOKEN": nonce}
        proc = popen_factory(cmd, cwd=os.getcwd(), env=env)
        emit_runtime_log("supervisor", f"started api pid={proc.pid} host={host} port={port} attempt={attempt}")
        if wait_for_api_fn(
            host, port, timeout=30.0, process=proc,
            expected_nonce=nonce, run_dir=run_dir,
        ):
            return proc
        # wait_for_api returned False. Two sub-cases:
        #   (a) process is alive but probe failed (timeout, foreign bind,
        #       missing token past grace). Under self-id mode this is NOT
        #       a "slow startup, give it a chance" scenario — it likely
        #       means a previous-generation orphan is holding the port and
        #       our child can never bind. Kill the proc and retry rather
        #       than handing the supervisor a child that will never serve.
        #   (b) process exited on its own — fall through to retry log.
        if proc.poll() is None:
            emit_runtime_log(
                "supervisor",
                f"api probe failed (process alive but unverified), killing pid={proc.pid} for retry attempt={attempt}/{_API_START_MAX_ATTEMPTS}",
                stderr=True,
            )
            try:
                _kill_tree(proc, force=True, log=emit_runtime_log)
            except Exception:
                pass
        else:
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
    wait_for_api_fn: Callable[..., bool] = _wait_for_api,
    should_stop: Callable[[], bool] | None = None,
    clock: Callable[[], float] = time.monotonic,
    log_file: Path | None = None,
    log_stream: IO[str] | None = None,
    kill_fn: Callable[..., None] = _kill_tree,
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
    _log_fh: IO[str] | None = None
    _owns_log_fh = False

    if log_stream is not None:
        # Shared stream from configure_file_logging — children inherit the
        # SAME kernel File Object as the root logger's handler. This keeps
        # the file position coherent across writers (supervisor logs +
        # child stdout/stderr). Do not close it; the caller owns the
        # lifecycle (process exit will release it).
        _log_fh = log_stream
    elif log_file is not None:
        try:
            _log_fh = open(log_file, "a", encoding="utf-8")  # noqa: SIM115
            _owns_log_fh = True
        except OSError:
            pass

    def _popen_with_log(cmd: list[str], **kwargs) -> subprocess.Popen:
        if _log_fh is not None:
            kwargs.setdefault("stdout", _log_fh)
            kwargs.setdefault("stderr", _log_fh)
        return popen_factory(cmd, **kwargs)

    with graceful_stop(install=True) as stop:
        try:
            # Start API with retry — onnxruntime on Windows/Python 3.13 has a
            # non-deterministic heap corruption bug during model initialization.
            # Once past startup the process is stable, so we retry until healthy.
            server_cmd = build_server_command(parsed.host, parsed.port)
            server = _start_api_with_retry(
                server_cmd, parsed.host, parsed.port,
                popen_factory=_popen_with_log,
                sleep_fn=sleep_fn,
                wait_for_api_fn=wait_for_api_fn,
                stop=stop,
            )
            if server is None:
                emit_runtime_log("supervisor", "api failed to start after retries, giving up", stderr=True)
                return 1
            slots.append(_ManagedSlot(
                command=server_cmd,
                label="api",
                process=server,
                restartable=True,
                use_retry_start=True,
                restart_times=[],
            ))

            for index in range(1, parsed.processors + 1):
                cmd = build_processor_command(index)
                proc = _popen_with_log(cmd, cwd=os.getcwd())
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
                proc = _popen_with_log(cmd, cwd=os.getcwd())
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
                proc = _popen_with_log(cmd, cwd=os.getcwd())
                slots.append(_ManagedSlot(
                    command=cmd,
                    label="snapshot",
                    process=proc,
                    restartable=True,
                    restart_times=[],
                ))
                emit_runtime_log("supervisor", f"started snapshot pid={proc.pid}")

            _last_probe = clock()
            _probe_failures = 0

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
                        # non-restartable slot exit is always fatal
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
                    if slot.use_retry_start:
                        new_proc = _start_api_with_retry(
                            slot.command, parsed.host, parsed.port,
                            popen_factory=_popen_with_log,
                            sleep_fn=sleep_fn,
                            wait_for_api_fn=wait_for_api_fn,
                            stop=stop,
                        )
                        if new_proc is None:
                            stop.requested = True
                            break
                    else:
                        new_proc = _popen_with_log(slot.command, cwd=os.getcwd())
                    emit_runtime_log(
                        "supervisor",
                        f"restarted {slot.label} old_pid={slot.process.pid} new_pid={new_proc.pid}",
                    )
                    slot.process = new_proc
                    if slot.use_retry_start:
                        _probe_failures = 0
                        _last_probe = clock()  # give new API a full probe interval before first check
                if stop.requested:
                    break
                # Periodic TCP health probe — detects the WinError 64 stuck-socket case
                # where the API process is alive but the accept loop is dead (Python 3.13
                # asyncio IOCP does not exit the process on this error).
                api_slot = next((s for s in slots if s.label == "api"), None)
                if api_slot is not None and api_slot.process.poll() is None:
                    now_probe = clock()
                    if now_probe - _last_probe >= _API_HEALTH_PROBE_INTERVAL:
                        _last_probe = now_probe
                        if _tcp_probe(parsed.host, parsed.port):
                            _probe_failures = 0
                        else:
                            _probe_failures += 1
                            emit_runtime_log(
                                "supervisor",
                                f"api health probe failed ({_probe_failures}/{_API_HEALTH_PROBE_FAIL_THRESHOLD})",
                                stderr=_probe_failures >= _API_HEALTH_PROBE_FAIL_THRESHOLD,
                            )
                            if _probe_failures >= _API_HEALTH_PROBE_FAIL_THRESHOLD:
                                emit_runtime_log("supervisor", "killing api for restart (unresponsive)", stderr=True)
                                kill_fn(api_slot.process, force=True, log=emit_runtime_log)
                                _probe_failures = 0
                                _last_probe = clock()  # replacement gets full probe interval before first check
                sleep_fn(0.1)
        finally:
            all_processes = [slot.process for slot in slots]
            # Three-pass shutdown to bound total wall time:
            #   1. Fan out SIGTERM/taskkill /T to every live child without waiting.
            #   2. Wait up to 5s per child for graceful exit (sequential, but
            #      most exit immediately so this is dominated by the slowest).
            #   3. Escalate to SIGKILL/taskkill /F /T on survivors and reap.
            # Without pass 1's wait_timeout=0, _kill_tree would block its own
            # internal wait *and* the outer process.wait, doubling the budget.
            for process in reversed(all_processes):
                if process.poll() is None:
                    kill_fn(process, force=False, wait_timeout=0, log=emit_runtime_log)
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
                        kill_fn(process, force=True, log=emit_runtime_log)

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
    if _log_fh is not None and _owns_log_fh:
        _log_fh.close()
    return exit_code


class _ManagedSlot:
    """Tracks a supervised child process and its restart history."""

    __slots__ = ("command", "label", "process", "restartable", "use_retry_start", "restart_times")

    def __init__(
        self,
        *,
        command: list[str],
        label: str,
        process: subprocess.Popen,
        restartable: bool,
        use_retry_start: bool = False,
        restart_times: list[float],
    ) -> None:
        self.command = command
        self.label = label
        self.process = process
        self.restartable = restartable
        self.use_retry_start = use_retry_start
        self.restart_times = restart_times


if __name__ == "__main__":
    raise SystemExit(run_supervisor())
