"""Inert lifecycle placeholder for the explicitly enabled Codex stdio child."""

from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import queue
import re
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path


_close_log_lock = threading.Lock()
_client_worker_id_lock = threading.Lock()
_client_worker_sequence = 0
_CLOSE_REASONS = frozenset({
    "idle-ready-deadline", "idle-ready-transport", "unused-ready-retired",
    "reregister-ready-deadline", "reregister-ready-transport",
    "caller-thread-changed", "first-admission-cancelled", "first-registered-result-cancelled",
    "initial-ready-unavailable",
    "replacement-ready-unavailable", "initial-register-unavailable", "reregister-unavailable",
    "idle-ready-unavailable", "capability-changed", "continuity-changed",
    "worker-error", "worker-finished", "lifespan-stop", "cleanup",
})


class _QuietCloseHandler(RotatingFileHandler):
    def handleError(self, record):
        pass


def _client_close_diagnostic(reason, identity, unresolved):
    try:
        own_pid = os.getpid()
        if type(reason) is not str or reason not in _CLOSE_REASONS:
            reason = "cleanup"
        creation = "unknown"
        pid, value = identity
        if (type(pid) is int and pid == own_pid and type(value) is str and len(value) <= 40
                and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:[+-][0-9]{2}:[0-9]{2})?", value)):
            creation = value
        unresolved = unresolved if type(unresolved) is bool else "unknown"
        _write_client_diagnostic("pallium.codex.close",
            "reason=%s own_pid=%s native_creation=%s unresolved=%s",
            (reason, own_pid, creation, unresolved))
    except Exception:
        pass  # A diagnostic sink must never interfere with native ownership cleanup.


def _write_client_diagnostic(name, message, args):
    try:
        from app.runtime_logging import RuntimeLogFormatter

        own_pid = os.getpid()
        record = logging.LogRecord(name, logging.WARNING, "", 0, message, args, None)
        with _close_log_lock:
            home = os.environ.get("PALLIUM_HOME")
            directory = (Path(home).expanduser().resolve() if home else Path.home() / ".pallium") / "logs"
            directory.mkdir(parents=True, exist_ok=True)
            handler = _QuietCloseHandler(directory / f"codex-retained-client-{own_pid}.log",
                maxBytes=4096, backupCount=1, encoding="utf-8", delay=True)
            try:
                handler.setFormatter(RuntimeLogFormatter("codex-retained-client"))
                handler.handle(record)
            finally:
                handler.close()
    except Exception:
        pass


def _next_client_worker_id():
    global _client_worker_sequence
    try:
        with _client_worker_id_lock:
            _client_worker_sequence = _client_worker_sequence % 999999999 + 1
            return _client_worker_sequence
    except Exception:
        return "unknown"


_RECOVERY_DIAGNOSTIC_VALUES = {
    "acquisition": frozenset({"not-attempted", "ready", "startup-unavailable", "failed"}),
    "ready": frozenset({"not-attempted", "ready", "busy", "deadline", "transport-failed", "terminal"}),
    "register": frozenset({"not-attempted", "registered", "busy", "refused", "uncertain", "error"}),
    "terminal": frozenset({"retry", "success", "not-eligible", "acquisition-terminal", "ready-retry", "ready-terminal",
                            "register-busy", "register-terminal", "stopped", "exhausted",
                            "window-exhausted", "uncertain"}),
}


def _client_recovery_diagnostic(worker, episode, attempt, acquisition, ready, register, terminal,
                                restart_allowed, unresolved="unknown"):
    try:
        values = (acquisition, ready, register, terminal)
        names = ("acquisition", "ready", "register", "terminal")
        values = tuple(value if type(value) is str and value in _RECOVERY_DIAGNOSTIC_VALUES[key]
                       else "unknown" for key, value in zip(names, values))
        worker = worker if type(worker) is int and 0 <= worker <= 999999999 else "unknown"
        episode = episode if type(episode) is int and 1 <= episode <= 999999 else "unknown"
        attempt = attempt if type(attempt) is int and 1 <= attempt <= RECONNECT_MAX_ATTEMPTS else "unknown"
        restart_allowed = restart_allowed if type(restart_allowed) is bool else "unknown"
        unresolved = unresolved if type(unresolved) is bool else "unknown"
        _write_client_diagnostic("pallium.codex.recovery",
            "event=recovery worker=%s episode=%s attempt=%s acquisition=%s ready=%s register=%s terminal=%s restart_allowed=%s unresolved=%s",
            (worker, episode, attempt, *values, restart_allowed, unresolved))
    except Exception:
        pass


def _diagnostic(category: str) -> None:
    try:
        print(f"Pallium Codex bridge inert: {category}", file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


async def _idle() -> None:
    await asyncio.Future()


def _task_finished(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        _diagnostic("task-failed")


@asynccontextmanager
async def lifespan(_server):
    task = asyncio.create_task(_idle())
    task.add_done_callback(_task_finished)
    try:
        yield {}
    finally:
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=1.0)
        if not done:
            _diagnostic("shutdown-timeout")


def public_status(value: object) -> dict:
    """Never forward native handles, policy, paths, or arbitrary error text."""
    out = {"mode": "shadow", "status": "unavailable"}
    if isinstance(value, dict):
        status = value.get("status")
        if isinstance(status, str) and status in {"enrolled", "eligible", "held", "inactive", "unavailable"}:
            out["status"] = status
        reason = value.get("reason")
        if isinstance(reason, str) and reason in {
            "stopped", "wrong-controller", "busy", "timeout", "not-enrolled",
            "native-failed", "invalid-metadata",
            "ok", "observed", "evidence-limited", "evidence-unavailable", "closed",
        }:
            out["reason"] = reason
        ttl = value.get("ttl_seconds")
        if type(ttl) in (int, float) and 0 <= ttl <= 300:
            out["ttl_seconds"] = ttl
    return out


class ShadowWorker:
    """One daemon owns the native connection, including unresolved native I/O."""

    def __init__(self, bootstrap_path: Path):
        self.stop_event = threading.Event()
        self._path = bootstrap_path
        self._requests = queue.Queue(maxsize=1)
        self._controller = None
        self._busy = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    async def request(self, operation: str, metadata: dict[str, str]) -> dict:
        if self.stop_event.is_set() or not os.environ.get("CODEX_APP_TOOLS_PIPE_PATH"):
            self.stop_event.set()
            return public_status({"reason": "stopped"})
        if self._controller is not None and metadata.get("thread_ref") != self._controller.get("thread_ref"):
            return public_status({"reason": "wrong-controller"})
        if self._busy:
            return public_status({"reason": "busy"})
        self._busy = True
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._requests.put_nowait((operation, metadata, loop, future))
        try:
            return await asyncio.wait_for(future, timeout=3.5)
        except asyncio.TimeoutError:
            self.stop_event.set()
            return public_status({"reason": "timeout"})
        except asyncio.CancelledError:
            self.stop_event.set()
            raise
        finally:
            self._busy = False

    @staticmethod
    def _complete(future, result):
        if not future.done():
            future.set_result(result)

    def _run(self):
        client = None
        next_renew = float("inf")
        try:
            while not self.stop_event.is_set():
                if not os.environ.get("CODEX_APP_TOOLS_PIPE_PATH"):
                    self.stop_event.set()
                    break
                try:
                    operation, metadata, loop, future = self._requests.get(timeout=0.1)
                except queue.Empty:
                    if client is not None and time.monotonic() >= next_renew:
                        result = public_status(client.renew())
                        next_renew = time.monotonic() + 5
                        if result["status"] == "unavailable" or result.get("reason") == "closed":
                            self.stop_event.set()
                    continue
                if self.stop_event.is_set():
                    result = public_status({"reason": "stopped"})
                elif operation == "status" and self._controller is None:
                    result = public_status({"reason": "not-enrolled"})
                else:
                    if client is None:
                        from app.codex_bridge_pipe import NativeShadowClient
                        client = NativeShadowClient(self._path, self.stop_event)
                    if operation == "enroll":
                        result = public_status(client.enroll(metadata))
                        if result["status"] == "enrolled":
                            self._controller = dict(metadata)
                            next_renew = time.monotonic() + 5
                    else:
                        result = public_status(client.status())
                    if result["status"] == "unavailable" or result.get("reason") == "closed":
                        self.stop_event.set()
                try:
                    loop.call_soon_threadsafe(self._complete, future, result)
                except RuntimeError:
                    self.stop_event.set()
        except Exception:
            self.stop_event.set()
            if "future" in locals():
                try:
                    loop.call_soon_threadsafe(self._complete, future, public_status({"reason": "native-failed"}))
                except RuntimeError:
                    pass
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    async def stop(self):
        self.stop_event.set()
        deadline = time.monotonic() + 0.5
        while self._thread.is_alive() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)


@asynccontextmanager
async def shadow_lifespan(_server):
    worker = ShadowWorker(Path(os.environ["PALLIUM_CODEX_SHADOW_BOOTSTRAP_FILE"]))
    try:
        yield {"codex_shadow": worker}
    finally:
        await worker.stop()


def inventory_status(value: object) -> dict:
    """Inventory evidence only; never forward native contents or authority."""
    result = {"mode": "inventory", "status": "unavailable"}
    if not isinstance(value, dict):
        return result
    if isinstance(value.get("status"), str) and value["status"] in {"ready", "registered", "inactive", "unavailable"}:
        result["status"] = value["status"]
    if isinstance(value.get("reason"), str) and value["reason"] in {
        "ready", "ok", "observed", "closed", "policy-inactive", "policy-changed",
        "peer-mismatch", "busy", "stopped", "native-failed", "timeout",
    }:
        result["reason"] = value["reason"]
    ttl = value.get("ttl_seconds")
    if type(ttl) is int and 0 <= ttl <= 300:
        result["ttl_seconds"] = ttl
    for field in ("connected", "inventory_ok", "source_exited"):
        if type(value.get(field)) is bool:
            result[field] = value[field]
    return result


RECONNECT_IDLE_POLL_SECONDS = 1.0
RECONNECT_MAX_ATTEMPTS = 12
RECONNECT_WINDOW_SECONDS = 300.0
RECONNECT_INITIAL_BACKOFF_SECONDS = 1.0
RECONNECT_MAX_BACKOFF_SECONDS = 30.0


class InventoryWorker:
    """One finite child channel; retained registration requires a live source channel."""

    def __init__(self, bootstrap_path: Path, *, retained=False):
        self.stop_event = threading.Event()
        self._retained = retained
        self._closed = False
        self._path = bootstrap_path
        self._requests = queue.Queue(maxsize=1)
        self._busy = False
        self._restart_allowed = True
        try:
            self._diagnostic_worker_id = _next_client_worker_id()
        except Exception:
            self._diagnostic_worker_id = "unknown"
        self._diagnostic_unresolved = "unknown"
        self._fresh_request_retirement = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    async def register(self, metadata: dict[str, str]) -> dict:
        if self._retained and not self._closed and self.stop_event.is_set() and not self._thread.is_alive():
            from app.codex_bridge_pipe import native_available
            if self._restart_allowed and native_available() and os.environ.get("CODEX_APP_TOOLS_PIPE_PATH"):
                # Only a fresh runtime request restarts resolved custody; never replay a caller.
                self.stop_event.clear()
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
        if self.stop_event.is_set() or "CODEX_APP_TOOLS_PIPE_PATH" not in os.environ:
            self.stop_event.set()
            return inventory_status({"reason": "stopped"})
        if self._busy:
            return inventory_status({"reason": "busy"})
        self._busy = True
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        try:
            self._requests.put_nowait((loop, future, metadata))
        except queue.Full:
            self._busy = False
            return inventory_status({"reason": "busy"})
        try:
            return await asyncio.wait_for(future, timeout=3.5)
        except asyncio.TimeoutError:
            if not self._retained:
                self.stop_event.set()
            return inventory_status({"reason": "timeout"})
        except asyncio.CancelledError:
            if not self._retained:
                self.stop_event.set()
            raise
        finally:
            self._busy = False

    @staticmethod
    def _valid_continuity(value):
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

    def _finish(self, client, *, retire=False, reason="cleanup"):
        identity = (None, None)
        try:
            identity = (client.source.pid, client.source.creation)
        except Exception:
            pass
        restart_allowed = self._restart_allowed
        unresolved = bool(client is not None and getattr(client, "unresolved", False))
        if client is not None:
            try:
                close = getattr(client, "retire", None) if retire else None
                (close if callable(close) else client.dispose)()
            except Exception:
                unresolved = True
            unresolved = unresolved or bool(getattr(client, "unresolved", False))
        self._restart_allowed = restart_allowed and not unresolved
        self._diagnostic_unresolved = unresolved
        if self._retained and client is not None:
            _client_close_diagnostic(reason, identity, unresolved)

    def _recover_if_gone(self, client, native_type, original_pipe, metadata, continuity,
                         *, allow_ready_retirement=False, ready_retirement_context="idle"):
        if not hasattr(client, "service_current") or not self._restart_allowed:
            return None, False
        try:
            if (self.stop_event.is_set() or getattr(client, "unresolved", False)
                    or getattr(getattr(client, "io", None), "unresolved", False)
                    or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                    or not self._valid_continuity(continuity)
                    or getattr(client, "continuity", None) != continuity):
                raise RuntimeError("retained continuity unavailable")
            if client.service_current():
                try:
                    ready = inventory_status(client.ready())
                except Exception as exc:
                    from app.codex_bridge_pipe import ShadowUnavailable
                    source_io = getattr(client, "io", None)
                    manifest = getattr(client, "manifest", None)
                    if (not allow_ready_retirement or not isinstance(exc, ShadowUnavailable)
                            or exc.category not in {"transport-failed", "deadline"}
                            or self.stop_event.is_set() or getattr(client, "unresolved", False)
                            or getattr(source_io, "unresolved", False)
                            or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                            or getattr(client, "continuity", None) != continuity
                            or type(manifest) is not dict or not client.service_current()
                            or client.bootstrap_unchanged() is not True):
                        raise
                    previous_manifest = dict(manifest)
                    self._finish(client, retire=True, reason=(
                        f"{ready_retirement_context}-ready-deadline" if exc.category == "deadline"
                        else f"{ready_retirement_context}-ready-transport"))
                    exit_witness = getattr(client, "retired_service_exited", None)
                    owner_exited = callable(exit_witness) and exit_witness() is True
                    if (not self._restart_allowed or self.stop_event.is_set()
                            or getattr(client, "unresolved", False)
                            or getattr(source_io, "unresolved", False)
                            or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                            or getattr(client, "continuity", None) != continuity
                            or (not owner_exited and client.bootstrap_unchanged() is not True)
                            or client.manifest != previous_manifest):
                        self._restart_allowed = False
                        if ready_retirement_context != "idle":
                            raise
                    if ready_retirement_context == "idle":
                        replacement = None
                        try:
                            if self._restart_allowed:
                                replacement = self._auto_reconnect(
                                    native_type, original_pipe, metadata, continuity,
                                    retired_context=(client, previous_manifest))
                        except Exception:
                            self._restart_allowed = False
                        finally:
                            # The episode borrows the old authenticated exit witness.
                            if callable(getattr(client, "retire", None)):
                                self._finish(client)
                        if (not self._restart_allowed or self.stop_event.is_set()
                                or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                                or replacement is not None and (
                                    replacement.continuity != continuity
                                    or getattr(replacement, "unresolved", False)
                                    or getattr(getattr(replacement, "io", None), "unresolved", False))):
                            if replacement is not None:
                                self._finish(replacement)
                            return None, True
                        return replacement, True
                    # Foreground failure still requires a new real caller.
                    self._fresh_request_retirement = (client, previous_manifest)
                    return None, True
                busy = ready.get("status") == "unavailable" and ready.get("reason") == "busy"
                if not busy:
                    if (ready.get("status") != "ready"
                            or type(ready.get("connected")) is not bool
                            or ready.get("source_exited") is not False):
                        raise RuntimeError("retained readiness unavailable")
                    if not ready["connected"]:
                        if (self.stop_event.is_set() or getattr(client, "unresolved", False)
                                or getattr(getattr(client, "io", None), "unresolved", False)
                                or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                                or getattr(client, "continuity", None) != continuity):
                            raise RuntimeError("retained continuity changed before registration")
                        registered = inventory_status(client.register(metadata))
                        if not (registered.get("status") == "registered"
                                or registered.get("status") == "unavailable"
                                and registered.get("reason") == "busy"):
                            raise RuntimeError("retained registration unavailable")
                if (self.stop_event.is_set() or getattr(client, "unresolved", False)
                        or getattr(getattr(client, "io", None), "unresolved", False)
                        or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                        or getattr(client, "continuity", None) != continuity):
                    raise RuntimeError("retained continuity changed")
                return client, False
        except Exception:
            self._restart_allowed = False
            return None, False
        if getattr(client, "unresolved", False):
            self._restart_allowed = False
            return None, False
        previous_manifest = getattr(client, "manifest", None)
        self._finish(client)
        if not self._restart_allowed:
            return None, True
        return (self._auto_reconnect(
            native_type, original_pipe, metadata, continuity, previous_manifest), True)

    def _retired_candidate(self, native_type, original_pipe, retired_client, retired_manifest):
        from app.codex_bridge_pipe import ShadowUnavailable
        candidate = None
        try:
            if os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe:
                raise RuntimeError("retired capability changed")
            exit_witness = getattr(retired_client, "retired_service_exited", None)
            owner_exited = callable(exit_witness) and exit_witness() is True
            if not owner_exited and retired_client.bootstrap_unchanged() is not True:
                raise RuntimeError("retired bootstrap changed")
            if owner_exited:
                candidate = native_type(self._path, self.stop_event, retained=True,
                                        previous_manifest=retired_manifest)
            else:
                candidate = native_type(self._path, self.stop_event, retained=True)
            replacement_manifest = candidate.manifest
            replacement_unchanged = candidate.bootstrap_unchanged()
            retired_unchanged = (exit_witness() is True if owner_exited
                                 else retired_client.bootstrap_unchanged())
            if (os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                    or type(replacement_manifest) is not dict
                    or (replacement_manifest == retired_manifest if owner_exited
                        else replacement_manifest != retired_manifest)
                    or replacement_unchanged is not True or retired_unchanged is not True):
                raise RuntimeError("retired acquisition identity changed")
            return candidate
        except Exception as exc:
            if candidate is not None:
                self._finish(candidate)
            if not (candidate is None and isinstance(exc, ShadowUnavailable)
                    and exc.category == "startup-unavailable"):
                self._restart_allowed = False
            raise

    def _auto_reconnect(self, native_type, original_pipe, metadata, continuity, previous_manifest=None,
                        *, retired_context=None):
        started, delay = time.monotonic(), RECONNECT_INITIAL_BACKOFF_SECONDS
        from app.codex_bridge_pipe import ShadowUnavailable
        worker = getattr(self, "_diagnostic_worker_id", "unknown")
        episode = getattr(self, "_recovery_episode", 0) % 999999 + 1
        self._recovery_episode = episode
        last = ("not-attempted", "not-attempted", "not-attempted")

        def diagnose(attempt, acquisition, ready, register, terminal, unresolved=None):
            if unresolved is None:
                unresolved = getattr(self, "_diagnostic_unresolved", "unknown")
            _client_recovery_diagnostic(worker, episode, attempt, acquisition, ready, register,
                                        terminal, self._restart_allowed, unresolved)

        def not_started(attempt, terminal):
            diagnose(attempt, "not-attempted", "not-attempted", "not-attempted", terminal, "unknown")

        for attempt in range(RECONNECT_MAX_ATTEMPTS):
            if self.stop_event.is_set():
                not_started(attempt + 1, "stopped")
                return None
            if not self._restart_allowed:
                not_started(attempt + 1, "not-eligible")
                return None
            if time.monotonic() - started >= RECONNECT_WINDOW_SECONDS:
                not_started(attempt + 1, "window-exhausted")
                return None
            if (os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                    or not self._valid_continuity(continuity)):
                not_started(attempt + 1, "not-eligible")
                return None
            acquisition, ready_result, register_result = "not-attempted", "not-attempted", "not-attempted"
            self._diagnostic_unresolved = "unknown"
            try:
                if retired_context is not None:
                    client = self._retired_candidate(native_type, original_pipe, *retired_context)
                elif previous_manifest is None:
                    client = native_type(self._path, self.stop_event, retained=True)
                else:
                    client = native_type(self._path, self.stop_event, retained=True,
                                         previous_manifest=previous_manifest)
            except ShadowUnavailable as exc:
                acquisition = "startup-unavailable" if exc.category == "startup-unavailable" else "failed"
                last = (acquisition, ready_result, register_result)
                if exc.category != "startup-unavailable":
                    diagnose(attempt + 1, *last, "acquisition-terminal")
                    return None
                diagnose(attempt + 1, *last, "retry")
            except Exception:
                acquisition = "failed"
                last = (acquisition, ready_result, register_result)
                diagnose(attempt + 1, *last, "acquisition-terminal")
                return None
            else:
                acquisition = "ready"
                client.continuity = continuity
                source_io = getattr(client, "io", None)
                retry_ready = False
                stopped_for_ready_retry = False
                try:
                    if time.monotonic() - started >= RECONNECT_WINDOW_SECONDS:
                        self._finish(client)
                        last = (acquisition, ready_result, register_result)
                        diagnose(attempt + 1, *last, "window-exhausted")
                        return None
                    manifest = getattr(client, "manifest", None)
                    ready_manifest = dict(manifest) if type(manifest) is dict else None
                    try:
                        ready_result = "terminal"
                        ready = client.ready()
                    except ShadowUnavailable as exc:
                        ready_result = exc.category if exc.category in {"deadline", "transport-failed"} else "terminal"
                        # READY is read-only; REGISTER failures below must never replay.
                        # A failing guard must leave the whole retry assignment false.
                        retry_ready = (exc.category in {"deadline", "transport-failed"}
                            and not (stopped_for_ready_retry := self.stop_event.is_set())
                            and self._restart_allowed
                            and not getattr(client, "unresolved", False)
                            and not getattr(source_io, "unresolved", False)
                            and os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") == original_pipe
                            and client.continuity == continuity
                            and ready_manifest is not None
                            and client.manifest == ready_manifest
                            and client.bootstrap_unchanged() is True
                            and client.service_current() is True)
                        raise
                    result = inventory_status(ready)
                    ready_result = ("ready" if result["status"] == "ready" else
                                    "busy" if result.get("reason") == "busy" else "terminal")
                    if result["status"] == "ready":
                        if (self.stop_event.is_set()
                                or time.monotonic() - started >= RECONNECT_WINDOW_SECONDS
                                or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                                or client.continuity != continuity
                                or getattr(client, "unresolved", False)
                                or getattr(getattr(client, "io", None), "unresolved", False)):
                            self._finish(client)
                            last = (acquisition, ready_result, register_result)
                            diagnose(attempt + 1, *last, "not-eligible")
                            return None
                        register_result = "error"
                        result = inventory_status(client.register(metadata))
                        register_result = ("registered" if result["status"] == "registered" else
                                           "busy" if result.get("reason") == "busy" else "refused")
                        if (result["status"] == "registered" and client.continuity == continuity
                                and not self.stop_event.is_set()
                                and time.monotonic() - started < RECONNECT_WINDOW_SECONDS
                                and os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") == original_pipe
                                and not getattr(client, "unresolved", False)
                                and not getattr(getattr(client, "io", None), "unresolved", False)):
                            diagnose(attempt + 1, acquisition, ready_result, register_result, "success", False)
                            return client
                    self._finish(client)
                    # Explicit busy rejects admission before mutation; uncertain replies never retry.
                    if (result["status"] != "unavailable" or result.get("reason") != "busy"
                            or not self._restart_allowed or client.continuity != continuity):
                        last = (acquisition, ready_result, register_result)
                        diagnose(attempt + 1, *last,
                                 "register-terminal" if ready_result == "ready" else "ready-terminal")
                        return None
                    last = (acquisition, ready_result, register_result)
                    diagnose(attempt + 1, *last, "retry", False)
                except Exception:
                    self._finish(client)
                    if not retry_ready:
                        last = (acquisition, ready_result, register_result)
                        diagnose(attempt + 1, *last,
                                 "register-terminal" if register_result != "not-attempted"
                                 else "stopped" if stopped_for_ready_retry else "ready-terminal")
                        return None
                    stopped_for_safe = False
                    try:
                        safe = (self._restart_allowed
                            and not (stopped_for_safe := self.stop_event.is_set())
                            and not getattr(source_io, "unresolved", False)
                            and os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") == original_pipe
                            and client.continuity == continuity
                            and client.manifest == ready_manifest
                            and client.bootstrap_unchanged() is True)
                    except Exception:
                        safe = False
                    if not safe:
                        self._restart_allowed = False
                        last = (acquisition, ready_result, register_result)
                        diagnose(attempt + 1, *last, "stopped" if stopped_for_safe else "uncertain")
                        return None
                    last = (acquisition, ready_result, register_result)
                    diagnose(attempt + 1, *last, "ready-retry", False)
            if attempt + 1 == RECONNECT_MAX_ATTEMPTS:
                diagnose(attempt + 1, *last, "exhausted")
                break
            remaining = RECONNECT_WINDOW_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                diagnose(attempt + 1, *last, "window-exhausted")
                break
            if self.stop_event.wait(min(delay, remaining)):
                diagnose(attempt + 1, *last, "stopped")
                break
            delay = min(delay * 2, RECONNECT_MAX_BACKOFF_SECONDS)
        return None

    def _run(self):
        client = None
        close_reason = "worker-finished"
        first_request = None
        admitted_metadata = continuity = original_pipe = None
        registered = False
        registration_attempted = False
        channel_pipe = retired_pipe = None
        retired_client = retired_manifest = None
        try:
            if self._retained:
                # Do not occupy the private service slot before a real Relay caller exists.
                while not self.stop_event.is_set():
                    try:
                        first_request = self._requests.get(timeout=0.1)
                        if first_request[1].cancelled():
                            first_request = None
                            continue
                        loop, future, metadata = first_request
                        break
                    except queue.Empty:
                        continue
                if self.stop_event.is_set():
                    return
            else:
                from app.codex_bridge_pipe import NativeInventoryClient
                client = NativeInventoryClient(self._path, self.stop_event)
                ready = inventory_status(client.ready())
                if ready["status"] != "ready":
                    return
            while not self.stop_event.is_set():
                if first_request is not None:
                    loop, future, metadata = first_request
                    first_request = None
                else:
                    try:
                        loop, future, metadata = self._requests.get(timeout=(
                            RECONNECT_IDLE_POLL_SECONDS if registered else 0.1))
                    except queue.Empty:
                        if registered and self._retained:
                            if os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe:
                                close_reason = "capability-changed"
                                self.stop_event.set()
                                break
                            replacement, disposed = self._recover_if_gone(
                                client, NativeInventoryClient, original_pipe, admitted_metadata, continuity,
                                allow_ready_retirement=True)
                            if disposed:
                                client = replacement
                            if self._fresh_request_retirement is not None:
                                retired_client, retired_manifest = self._fresh_request_retirement
                                self._fresh_request_retirement = None
                                retired_pipe = original_pipe
                                registered = False
                                continue
                            if replacement is None:
                                close_reason = "idle-ready-unavailable"
                                self.stop_event.set()
                                break
                            client = replacement
                        elif (self._retained and client is not None and not registration_attempted
                              and callable(getattr(client, "bootstrap_unchanged", None))
                              and type(getattr(client, "manifest", None)) is dict):
                            # Preserve calls already waiting on this ready source channel.
                            try:
                                first_request = self._requests.get_nowait()
                            except queue.Empty:
                                if os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != channel_pipe:
                                    if retired_pipe is not None:
                                        self._restart_allowed = False
                                    self.stop_event.set()
                                    break
                                retired_manifest = dict(client.manifest)
                                retired_pipe = channel_pipe
                                retired_client = client
                                self._finish(retired_client, retire=True, reason="unused-ready-retired")
                                client = None
                                if not self._restart_allowed:
                                    self.stop_event.set()
                                    break
                        continue
                if future.cancelled():
                    continue
                if (self._retained and admitted_metadata is not None
                        and metadata.get("thread_ref") != admitted_metadata.get("thread_ref")):
                    close_reason = "caller-thread-changed"
                    self._restart_allowed = False
                    self.stop_event.set()
                    loop.call_soon_threadsafe(ShadowWorker._complete, future,
                        inventory_status({"reason": "peer-mismatch"}))
                    break
                if self._retained and client is None:
                    from app.codex_bridge_pipe import NativeInventoryClient, ShadowUnavailable
                    if retired_client is None:
                        # Ordinary first startup remains a single attempt.
                        channel_pipe = os.environ.get("CODEX_APP_TOOLS_PIPE_PATH")
                        client = NativeInventoryClient(self._path, self.stop_event, retained=True)
                        ready = inventory_status(client.ready())
                        if ready["status"] != "ready":
                            close_reason = "initial-ready-unavailable"
                            return
                    else:
                        acquire_deadline = time.monotonic() + 1.0
                        while client is None:
                            if self.stop_event.is_set() or future.cancelled():
                                break
                            if os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != retired_pipe:
                                self._restart_allowed = False
                                self.stop_event.set()
                                break
                            remaining = acquire_deadline - time.monotonic()
                            if remaining <= 0:
                                break
                            try:
                                client = self._retired_candidate(
                                    NativeInventoryClient, retired_pipe, retired_client, retired_manifest)
                            except ShadowUnavailable as exc:
                                if exc.category != "startup-unavailable":
                                    self._restart_allowed = False
                                    raise
                                remaining = acquire_deadline - time.monotonic()
                                if remaining <= 0 or self.stop_event.wait(min(0.05, remaining)):
                                    break
                                continue
                            except Exception:
                                self._restart_allowed = False
                                raise
                            if self.stop_event.is_set():
                                break
                            if future.cancelled():
                                unused = client
                                self._finish(unused)
                                client = None
                                if not self._restart_allowed:
                                    self.stop_event.set()
                                break
                            try:
                                ready_result = client.ready()
                            except ShadowUnavailable as exc:
                                if exc.category not in {"stopped", "deadline", "transport-failed"}:
                                    self._restart_allowed = False
                                raise
                            except Exception:
                                self._restart_allowed = False
                                raise
                            ready = inventory_status(ready_result)
                            if ready["status"] != "ready":
                                close_reason = "replacement-ready-unavailable"
                                if ready.get("reason") == "peer-mismatch":
                                    self._restart_allowed = False
                                return
                            if self.stop_event.is_set():
                                break
                            if os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != retired_pipe:
                                self._restart_allowed = False
                                self.stop_event.set()
                                break
                            if callable(getattr(retired_client, "retire", None)):
                                self._finish(retired_client)
                            retired_client = retired_manifest = None
                            if not self._restart_allowed:
                                self.stop_event.set()
                                break
                            registration_attempted = False
                    if client is None:
                        if future.cancelled():
                            continue
                        if self.stop_event.is_set():
                            break
                        loop.call_soon_threadsafe(ShadowWorker._complete, future,
                            inventory_status({"reason": "native-failed"}))
                        continue
                    if self.stop_event.is_set():
                        break
                if future.cancelled():
                    continue
                if (registered and self._retained
                        and metadata.get("thread_ref") != admitted_metadata.get("thread_ref")):
                    close_reason = "caller-thread-changed"
                    self.stop_event.set()
                    loop.call_soon_threadsafe(ShadowWorker._complete, future,
                        inventory_status({"reason": "peer-mismatch"}))
                    break
                if future.cancelled():
                    continue
                request_pipe = os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") if self._retained else None
                if (self._retained and not registered and retired_pipe is not None
                        and request_pipe != retired_pipe):
                    self._restart_allowed = False
                    self.stop_event.set()
                    loop.call_soon_threadsafe(ShadowWorker._complete, future,
                        inventory_status({"reason": "peer-mismatch"}))
                    break
                if registered and self._retained and request_pipe != original_pipe:
                    self.stop_event.set()
                    loop.call_soon_threadsafe(ShadowWorker._complete, future,
                        inventory_status({"reason": "peer-mismatch"}))
                    break
                was_registered = registered
                registration_attempted = True
                if self._retained and not was_registered and continuity is not None:
                    client.continuity = continuity
                if self._retained and not was_registered and retired_pipe is not None:
                    retired_pipe = None
                foreground_transport_failure = False
                try:
                    result = inventory_status(client.register(metadata))
                except Exception as exc:
                    from app.codex_bridge_pipe import ShadowUnavailable
                    foreground_transport_failure = (isinstance(exc, ShadowUnavailable)
                        and exc.category in {"transport-failed", "deadline"})
                    result = inventory_status({"reason": "native-failed"})
                if future.cancelled():
                    if self._retained and not was_registered:
                        close_reason = ("first-registered-result-cancelled" if result["status"] == "registered"
                                        else "first-admission-cancelled")
                        self.stop_event.set()
                        break
                    continue
                if self._retained and request_pipe != os.environ.get("CODEX_APP_TOOLS_PIPE_PATH"):
                    self.stop_event.set()
                    loop.call_soon_threadsafe(ShadowWorker._complete, future,
                        inventory_status({"reason": "peer-mismatch"}))
                    break
                if self._retained and result["status"] == "registered":
                    if not hasattr(client, "continuity") or not hasattr(client, "service_current"):
                        # Older fake clients remain usable but cannot authorize continuity.
                        pass
                    else:
                        proof = getattr(client, "continuity", None)
                        if (not self._valid_continuity(proof)
                                or (was_registered and proof != continuity)):
                            close_reason = "continuity-changed"
                            result = inventory_status({"reason": "peer-mismatch"})
                            self.stop_event.set()
                            self._restart_allowed = False
                        else:
                            registered = True
                            admitted_metadata = dict(metadata)
                            continuity = proof
                            if not was_registered:
                                original_pipe = request_pipe
                loop.call_soon_threadsafe(ShadowWorker._complete, future, result)
                if was_registered and self._retained and result["status"] != "registered":
                    replacement, disposed = self._recover_if_gone(
                        client, NativeInventoryClient, original_pipe, admitted_metadata, continuity,
                        allow_ready_retirement=foreground_transport_failure, ready_retirement_context="reregister")
                    if disposed:
                        client = replacement
                    if self._fresh_request_retirement is not None:
                        retired_client, retired_manifest = self._fresh_request_retirement
                        self._fresh_request_retirement = None
                        retired_pipe = original_pipe
                        registered = False
                        continue
                    if disposed and replacement is not None:
                        continue
                    # Keep checked prior custody without replaying a failed caller.
                    if (not disposed and replacement is client
                            and (foreground_transport_failure
                                 or result["status"] == "unavailable" and result.get("reason") == "busy")
                            and not self.stop_event.is_set() and not getattr(client, "unresolved", False)
                            and getattr(client, "continuity", None) == continuity):
                        continue
                    self.stop_event.set()
                    if close_reason == "worker-finished":
                        close_reason = "reregister-unavailable"
                    break
                if result["status"] == "unavailable" and not was_registered:
                    close_reason = "initial-register-unavailable"
                    self.stop_event.set()
                    break
        except Exception:
            close_reason = "worker-error"
            self.stop_event.set()
            if "future" in locals():
                try:
                    loop.call_soon_threadsafe(ShadowWorker._complete, future,
                        inventory_status({"reason": "native-failed"}))
                except RuntimeError:
                    pass
        finally:
            self.stop_event.set()
            if "future" in locals():
                try:
                    loop.call_soon_threadsafe(ShadowWorker._complete, future,
                        inventory_status({"reason": "stopped"}))
                except RuntimeError:
                    pass
            try:
                loop, pending, _ = self._requests.get_nowait()
                loop.call_soon_threadsafe(ShadowWorker._complete, pending,
                    inventory_status({"reason": "stopped"}))
            except (queue.Empty, RuntimeError):
                pass
            if client is not None:
                self._finish(client, reason=("lifespan-stop" if self._closed
                    and close_reason == "worker-finished" else close_reason))
            if retired_client is not None and retired_client is not client and callable(getattr(retired_client, "retire", None)):
                self._finish(retired_client)
            pending_retirement = self._fresh_request_retirement
            self._fresh_request_retirement = None
            if (pending_retirement is not None and pending_retirement[0] is not client
                    and pending_retirement[0] is not retired_client
                    and callable(getattr(pending_retirement[0], "retire", None))):
                self._finish(pending_retirement[0])

    async def stop(self):
        self._closed = True
        self.stop_event.set()
        deadline = time.monotonic() + 0.5
        while self._thread.is_alive() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)


@asynccontextmanager
async def inventory_lifespan(_server):
    worker = InventoryWorker(Path(os.environ["PALLIUM_CODEX_INVENTORY_BOOTSTRAP_FILE"]))
    try:
        yield {"codex_inventory": worker}
    finally:
        await worker.stop()


@asynccontextmanager
async def retained_lifespan(_server):
    from app.codex_bridge_pipe import retained_bootstrap_path

    worker = InventoryWorker(retained_bootstrap_path(os.environ.get("PALLIUM_BASE_URL")), retained=True)
    try:
        yield {"codex_retained": worker}
    finally:
        await worker.stop()
