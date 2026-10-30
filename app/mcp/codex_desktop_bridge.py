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
from itertools import count
from contextlib import asynccontextmanager
from pathlib import Path


_close_log_lock = threading.Lock()
_reconnect_episode = count(1)
_CLOSE_REASONS = frozenset({
    "idle-ready-deadline", "idle-ready-transport", "unused-ready-retired",
    "reregister-ready-deadline", "reregister-ready-transport",
    "caller-thread-changed", "first-admission-cancelled", "first-registered-result-cancelled",
    "initial-ready-unavailable",
    "replacement-ready-unavailable", "initial-register-unavailable", "reregister-unavailable",
    "idle-ready-unavailable", "capability-changed", "continuity-changed",
    "worker-error", "worker-finished", "lifespan-stop", "cleanup",
})
_RECONNECT_PHASES = frozenset({"preflight", "service-check", "ready", "retire", "owner-check",
                               "constructor", "candidate-ready", "candidate-fence", "register",
                               "postregister", "cleanup", "backoff"})
_RECONNECT_STATES = frozenset({"entered", "completed", "raised"})
_RECONNECT_REGISTRATION = frozenset({"not-attempted", "attempted", "completed"})
_RECONNECT_OUTCOMES = frozenset({
    "unclassified", "preentry-refused", "ready-retired", "ready-available", "ready-busy",
    "fresh-request-required", "safety-refused", "service-not-current", "reconnected",
    "constructor-retry", "constructor-refused", "constructor-error", "reconnect-error", "ready-retry",
    "ready-refused", "ready-busy-retry", "register-busy", "register-busy-retry",
    "register-unconfirmed", "register-uncertain", "cleanup-error",
    "postregister-fence-refused", "candidate-fence-refused", "attempts-exhausted",
    "window-exhausted", "reconnect-stopped", "reconnect-guard-refused",
})


def _new_reconnect_diagnostic(context):
    try:
        episode = next(_reconnect_episode)
        episode = episode if episode <= 2147483647 else None
        return {"episode": episode, "context": context, "phase": "preflight",
                "phase_state": "entered", "attempt": 0, "registration": "not-attempted",
                "outcome": "unclassified", "unresolved": "unknown", "owner_exited": "unknown"}
    except Exception:
        return None


def _mark_reconnect(diagnostic, *, phase=None, phase_state=None, attempt=None, registration=None,
                    outcome=None, unresolved=None, owner_exited=None):
    if diagnostic is None:
        return
    try:
        for key, value in (("phase", phase), ("phase_state", phase_state), ("attempt", attempt),
                           ("registration", registration), ("outcome", outcome),
                           ("unresolved", unresolved), ("owner_exited", owner_exited)):
            if value is not None:
                if key == "unresolved" and diagnostic.get(key) is True:
                    continue  # An observed ownership hazard remains relevant to this episode.
                diagnostic[key] = value
    except Exception:
        pass


def _client_reconnect_diagnostic(diagnostic, restart_allowed):
    try:
        from app.runtime_logging import RuntimeLogFormatter

        if type(diagnostic) is not dict:
            return
        own_pid = os.getpid()
        episode = diagnostic.get("episode")
        episode = episode if type(episode) is int and 1 <= episode <= 2147483647 else "unknown"
        context = diagnostic.get("context")
        context = context if type(context) is str and context in {"idle", "reregister"} else "unknown"
        phase = diagnostic.get("phase")
        phase = phase if type(phase) is str and phase in _RECONNECT_PHASES else "unknown"
        phase_state = diagnostic.get("phase_state")
        phase_state = phase_state if type(phase_state) is str and phase_state in _RECONNECT_STATES else "unknown"
        attempt = diagnostic.get("attempt")
        attempt = attempt if type(attempt) is int and 0 <= attempt <= RECONNECT_MAX_ATTEMPTS else "unknown"
        registration = diagnostic.get("registration")
        registration = registration if type(registration) is str and registration in _RECONNECT_REGISTRATION else "unknown"
        outcome = diagnostic.get("outcome")
        outcome = outcome if type(outcome) is str and outcome in _RECONNECT_OUTCOMES else "unknown"
        unresolved = diagnostic.get("unresolved")
        unresolved = unresolved if type(unresolved) is bool else "unknown"
        owner_exited = diagnostic.get("owner_exited")
        owner_exited = owner_exited if type(owner_exited) is bool else "unknown"
        restart_allowed = restart_allowed if type(restart_allowed) is bool else "unknown"
        record = logging.LogRecord("pallium.codex.reconnect", logging.WARNING, "", 0,
            "reconnect_terminal own_pid=%s episode=%s context=%s phase=%s phase_state=%s "
            "attempt=%s registration=%s outcome=%s restart_allowed=%s unresolved=%s owner_exited=%s",
            (own_pid, episode, context, phase, phase_state, attempt, registration, outcome,
             restart_allowed, unresolved, owner_exited), None)
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
        pass  # Outcome diagnostics must not change reconnect control flow.


class _QuietCloseHandler(RotatingFileHandler):
    def handleError(self, record):
        pass


def _client_close_diagnostic(reason, identity, unresolved):
    try:
        from app.runtime_logging import RuntimeLogFormatter

        own_pid = os.getpid()
        if type(reason) is not str or reason not in _CLOSE_REASONS:
            reason = "cleanup"
        creation = "unknown"
        pid, value = identity
        if (type(pid) is int and pid == own_pid and type(value) is str and len(value) <= 40
                and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:[+-][0-9]{2}:[0-9]{2})?", value)):
            creation = value
        unresolved = unresolved if type(unresolved) is bool else "unknown"
        record = logging.LogRecord("pallium.codex.close", logging.WARNING, "", 0,
            "reason=%s own_pid=%s native_creation=%s unresolved=%s",
            (reason, own_pid, creation, unresolved), None)
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
        pass  # A diagnostic sink must never interfere with native ownership cleanup.


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
        if self._retained and client is not None:
            _client_close_diagnostic(reason, identity, unresolved)
        return unresolved

    def _recover_if_gone(self, client, native_type, original_pipe, metadata, continuity,
                         *, allow_ready_retirement=False, ready_retirement_context="idle"):
        if not hasattr(client, "service_current") or not self._restart_allowed:
            diagnostic = _new_reconnect_diagnostic(ready_retirement_context) if self._retained else None
            _mark_reconnect(diagnostic, phase="preflight", phase_state="completed",
                            outcome="preentry-refused")
            _client_reconnect_diagnostic(diagnostic, self._restart_allowed)
            return None, False
        diagnostic = None
        service_check_pending = False
        try:
            if (self.stop_event.is_set() or getattr(client, "unresolved", False)
                    or getattr(getattr(client, "io", None), "unresolved", False)
                    or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                    or not self._valid_continuity(continuity)
                    or getattr(client, "continuity", None) != continuity):
                diagnostic = _new_reconnect_diagnostic(ready_retirement_context)
                _mark_reconnect(diagnostic, phase="preflight", phase_state="completed",
                                outcome="preentry-refused")
                raise RuntimeError("retained continuity unavailable")
            service_check_pending = True
            if client.service_current():
                service_check_pending = False
                try:
                    ready = inventory_status(client.ready())
                except Exception as exc:
                    from app.codex_bridge_pipe import ShadowUnavailable
                    diagnostic = _new_reconnect_diagnostic(ready_retirement_context)
                    _mark_reconnect(diagnostic, phase="ready", phase_state="raised",
                                    outcome="ready-refused")
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
                    retirement_reason = (
                        f"{ready_retirement_context}-ready-deadline" if exc.category == "deadline"
                        else f"{ready_retirement_context}-ready-transport")
                    _mark_reconnect(diagnostic, phase="retire", phase_state="entered",
                                    outcome="ready-retired", unresolved="unknown")
                    retired_unresolved = self._finish(client, retire=True, reason=(
                        retirement_reason))
                    _mark_reconnect(diagnostic, phase="retire", phase_state="completed",
                                    unresolved=True if retired_unresolved is True else None)
                    _mark_reconnect(diagnostic, phase="owner-check", phase_state="entered")
                    exit_witness = getattr(client, "retired_service_exited", None)
                    owner_exited = callable(exit_witness) and exit_witness() is True
                    _mark_reconnect(diagnostic, phase="owner-check", phase_state="completed",
                                    owner_exited=owner_exited)
                    if (not self._restart_allowed or self.stop_event.is_set()
                            or getattr(client, "unresolved", False)
                            or getattr(source_io, "unresolved", False)
                            or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                            or getattr(client, "continuity", None) != continuity
                            or (not owner_exited and client.bootstrap_unchanged() is not True)
                            or client.manifest != previous_manifest):
                        self._restart_allowed = False
                        _mark_reconnect(diagnostic, outcome="safety-refused")
                        if ready_retirement_context != "idle":
                            raise
                    else:
                        _mark_reconnect(diagnostic, unresolved=False)
                    if ready_retirement_context == "idle":
                        replacement = None
                        old_cleanup_unresolved = None
                        try:
                            if self._restart_allowed:
                                replacement = self._auto_reconnect(
                                    native_type, original_pipe, metadata, continuity, None, diagnostic,
                                    retired_context=(client, previous_manifest))
                        except Exception:
                            self._restart_allowed = False
                            _mark_reconnect(diagnostic, outcome="safety-refused")
                        finally:
                            # The episode borrows the old authenticated exit witness.
                            if callable(getattr(client, "retire", None)):
                                old_cleanup_unresolved = self._finish(client)
                                if old_cleanup_unresolved is True:
                                    _mark_reconnect(diagnostic, phase="cleanup", phase_state="completed",
                                                    outcome="safety-refused", unresolved=True)
                        replacement_unresolved = replacement_io_unresolved = None
                        _mark_reconnect(diagnostic, unresolved="unknown")
                        if (not self._restart_allowed or self.stop_event.is_set()
                                or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                                or replacement is not None and (
                                    replacement.continuity != continuity
                                    or (replacement_unresolved := getattr(replacement, "unresolved", False))
                                    or (replacement_io_unresolved := getattr(
                                        getattr(replacement, "io", None), "unresolved", False)))):
                            if replacement_unresolved is True or replacement_io_unresolved is True:
                                _mark_reconnect(diagnostic, unresolved=True)
                            if replacement is not None:
                                replacement_cleanup_unresolved = self._finish(replacement)
                                _mark_reconnect(diagnostic, unresolved=(
                                    True if replacement_cleanup_unresolved is True else None))
                            if (old_cleanup_unresolved is True or diagnostic is None
                                    or diagnostic.get("outcome") not in {
                                        "postregister-fence-refused", "candidate-fence-refused"}):
                                _mark_reconnect(diagnostic, outcome="safety-refused")
                            _client_reconnect_diagnostic(diagnostic, self._restart_allowed)
                            return None, True
                        if replacement is not None:
                            _mark_reconnect(diagnostic, outcome="reconnected", unresolved=False)
                        _client_reconnect_diagnostic(diagnostic, self._restart_allowed)
                        return replacement, True
                    # Foreground failure still requires a new real caller.
                    self._fresh_request_retirement = (client, previous_manifest)
                    _mark_reconnect(diagnostic, outcome="fresh-request-required")
                    _client_reconnect_diagnostic(diagnostic, self._restart_allowed)
                    return None, True
                busy = ready.get("status") == "unavailable" and ready.get("reason") == "busy"
                if not busy:
                    if (ready.get("status") != "ready"
                            or type(ready.get("connected")) is not bool
                            or ready.get("source_exited") is not False):
                        diagnostic = _new_reconnect_diagnostic(ready_retirement_context)
                        _mark_reconnect(diagnostic, phase="ready", phase_state="completed",
                                        outcome="ready-refused")
                        raise RuntimeError("retained readiness unavailable")
                    if not ready["connected"]:
                        if (self.stop_event.is_set() or getattr(client, "unresolved", False)
                                or getattr(getattr(client, "io", None), "unresolved", False)
                                or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                                or getattr(client, "continuity", None) != continuity):
                            diagnostic = _new_reconnect_diagnostic(ready_retirement_context)
                            _mark_reconnect(diagnostic, phase="preflight", phase_state="completed",
                                            outcome="preentry-refused")
                            raise RuntimeError("retained continuity changed before registration")
                        if diagnostic is None:
                            diagnostic = _new_reconnect_diagnostic(ready_retirement_context)
                        _mark_reconnect(diagnostic, phase="register", phase_state="entered",
                                        registration="attempted", unresolved="unknown")
                        registration_reply = client.register(metadata)
                        _mark_reconnect(diagnostic, phase="register", phase_state="completed",
                                        registration="completed")
                        registered = inventory_status(registration_reply)
                        if not (registered.get("status") == "registered"
                                or registered.get("status") == "unavailable"
                                and registered.get("reason") == "busy"):
                            _mark_reconnect(diagnostic, outcome="register-unconfirmed")
                            raise RuntimeError("retained registration unavailable")
                        if registered.get("status") == "unavailable":
                            _mark_reconnect(diagnostic, outcome="register-busy")
                        _mark_reconnect(diagnostic, phase="postregister", phase_state="entered",
                                        unresolved="unknown")
                caller_unresolved = caller_io_unresolved = None
                if (self.stop_event.is_set()
                        or (caller_unresolved := getattr(client, "unresolved", False))
                        or (caller_io_unresolved := getattr(
                            getattr(client, "io", None), "unresolved", False))
                        or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                        or getattr(client, "continuity", None) != continuity):
                    if diagnostic is None:
                        diagnostic = _new_reconnect_diagnostic(ready_retirement_context)
                    _mark_reconnect(diagnostic, outcome=(
                        "postregister-fence-refused" if diagnostic is not None
                        and diagnostic.get("phase") == "postregister" else "safety-refused"),
                        unresolved=True if caller_unresolved is True or caller_io_unresolved is True else None)
                    raise RuntimeError("retained continuity changed")
                if busy and diagnostic is None:
                    diagnostic = _new_reconnect_diagnostic(ready_retirement_context)
                    _mark_reconnect(diagnostic, phase="ready", phase_state="completed",
                                    outcome="ready-busy")
                if diagnostic is not None:
                    _mark_reconnect(diagnostic, phase_state="completed", unresolved=False)
                    if diagnostic.get("outcome") == "unclassified":
                        _mark_reconnect(diagnostic, outcome="ready-busy" if busy else "ready-available")
                    _client_reconnect_diagnostic(diagnostic, self._restart_allowed)
                return client, False
        except Exception:
            self._restart_allowed = False
            if diagnostic is None:
                diagnostic = _new_reconnect_diagnostic(ready_retirement_context)
                if service_check_pending:
                    _mark_reconnect(diagnostic, phase="service-check", phase_state="raised",
                                    outcome="reconnect-error")
            outcome = diagnostic.get("outcome") if type(diagnostic) is dict else None
            if outcome == "unclassified":
                if (diagnostic is not None and diagnostic.get("phase") == "register"
                        and diagnostic.get("registration") == "attempted"):
                    outcome = "register-uncertain"
                    _mark_reconnect(diagnostic, phase_state="raised")
                elif (diagnostic is not None and diagnostic.get("phase") == "register"
                      and diagnostic.get("registration") == "completed"):
                    outcome = "register-unconfirmed"
                elif diagnostic is not None and diagnostic.get("phase") == "postregister":
                    outcome = "postregister-fence-refused"
                else:
                    outcome = "safety-refused"
            _mark_reconnect(diagnostic, outcome=outcome)
            _client_reconnect_diagnostic(diagnostic, self._restart_allowed)
            return None, False
        if getattr(client, "unresolved", False):
            self._restart_allowed = False
            if diagnostic is None:
                diagnostic = _new_reconnect_diagnostic(ready_retirement_context)
            _mark_reconnect(diagnostic, phase="preflight", phase_state="completed",
                            outcome="preentry-refused", unresolved=True)
            _client_reconnect_diagnostic(diagnostic, self._restart_allowed)
            return None, False
        diagnostic = _new_reconnect_diagnostic(ready_retirement_context)
        _mark_reconnect(diagnostic, phase="service-check", phase_state="completed",
                        outcome="service-not-current")
        try:
            previous_manifest = getattr(client, "manifest", None)
            cleanup_unresolved = self._finish(client)
            _mark_reconnect(diagnostic, unresolved=True if cleanup_unresolved is True else None)
            if not self._restart_allowed:
                _mark_reconnect(diagnostic, outcome="safety-refused")
                return None, True
            replacement = self._auto_reconnect(
                native_type, original_pipe, metadata, continuity, previous_manifest, diagnostic)
            if replacement is not None:
                _mark_reconnect(diagnostic, outcome="reconnected")
            return replacement, True
        except Exception:
            _mark_reconnect(diagnostic, outcome="reconnect-error")
            raise
        finally:
            _client_reconnect_diagnostic(diagnostic, self._restart_allowed)

    def _retired_candidate(self, native_type, original_pipe, retired_client, retired_manifest,
                           *, diagnostic=None):
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
                cleanup_unresolved = self._finish(candidate)
                _mark_reconnect(diagnostic, unresolved=True if cleanup_unresolved is True else None)
            if not (candidate is None and isinstance(exc, ShadowUnavailable)
                    and exc.category == "startup-unavailable"):
                self._restart_allowed = False
            raise

    def _auto_reconnect(self, native_type, original_pipe, metadata, continuity, previous_manifest=None,
                        diagnostic=None, *, retired_context=None):
        started, delay = time.monotonic(), RECONNECT_INITIAL_BACKOFF_SECONDS
        from app.codex_bridge_pipe import ShadowUnavailable
        for attempt in range(RECONNECT_MAX_ATTEMPTS):
            window_expired = None
            if (self.stop_event.is_set() or not self._restart_allowed
                    or (window_expired := time.monotonic() - started >= RECONNECT_WINDOW_SECONDS)
                    or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                    or not self._valid_continuity(continuity)):
                _mark_reconnect(diagnostic, phase="preflight", phase_state="completed",
                                outcome="window-exhausted" if window_expired is True
                                else "reconnect-guard-refused")
                return None
            _mark_reconnect(diagnostic, phase="constructor", phase_state="entered",
                            attempt=attempt + 1, registration="not-attempted", unresolved="unknown",
                            outcome="unclassified")
            try:
                if retired_context is not None:
                    client = self._retired_candidate(native_type, original_pipe, *retired_context,
                                                     diagnostic=diagnostic)
                elif previous_manifest is None:
                    client = native_type(self._path, self.stop_event, retained=True)
                else:
                    client = native_type(self._path, self.stop_event, retained=True,
                                         previous_manifest=previous_manifest)
            except ShadowUnavailable as exc:
                if exc.category != "startup-unavailable":
                    _mark_reconnect(diagnostic, phase="constructor", phase_state="raised",
                                    outcome="constructor-refused")
                    return None
                _mark_reconnect(diagnostic, phase="constructor", phase_state="raised",
                                outcome="constructor-retry")
            except Exception:
                _mark_reconnect(diagnostic, phase="constructor", phase_state="raised",
                                outcome="constructor-error")
                return None
            else:
                _mark_reconnect(diagnostic, phase="constructor", phase_state="completed")
                client.continuity = continuity
                source_io = getattr(client, "io", None)
                retry_ready = False
                try:
                    if time.monotonic() - started >= RECONNECT_WINDOW_SECONDS:
                        _mark_reconnect(diagnostic, phase="backoff", phase_state="completed",
                                        outcome="window-exhausted")
                        _mark_reconnect(diagnostic, phase="cleanup", phase_state="entered",
                                        unresolved="unknown")
                        cleanup_unresolved = self._finish(client)
                        _mark_reconnect(diagnostic, phase_state="completed",
                                        unresolved=True if cleanup_unresolved is True else None)
                        return None
                    manifest = getattr(client, "manifest", None)
                    ready_manifest = dict(manifest) if type(manifest) is dict else None
                    try:
                        _mark_reconnect(diagnostic, phase="candidate-ready", phase_state="entered",
                                        unresolved="unknown")
                        ready = client.ready()
                    except ShadowUnavailable as exc:
                        # READY is read-only; REGISTER failures below must never replay.
                        retry_ready = (exc.category in {"deadline", "transport-failed"}
                            and not self.stop_event.is_set() and self._restart_allowed
                            and not getattr(client, "unresolved", False)
                            and not getattr(source_io, "unresolved", False)
                            and os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") == original_pipe
                            and client.continuity == continuity
                            and ready_manifest is not None
                            and client.manifest == ready_manifest
                            and client.bootstrap_unchanged() is True
                            and client.service_current() is True)
                        _mark_reconnect(diagnostic, phase="candidate-ready", phase_state="raised",
                                        outcome="ready-retry" if retry_ready else "ready-refused",
                                        unresolved=False if retry_ready else "unknown")
                        raise
                    _mark_reconnect(diagnostic, phase="candidate-ready", phase_state="completed")
                    result = inventory_status(ready)
                    if result["status"] != "ready":
                        _mark_reconnect(diagnostic, outcome=(
                            "ready-busy-retry" if result["status"] == "unavailable"
                            and result.get("reason") == "busy" else "ready-refused"))
                    if result["status"] == "ready":
                        _mark_reconnect(diagnostic, phase="candidate-fence", phase_state="entered",
                                        unresolved="unknown")
                        candidate_unresolved = candidate_io_unresolved = None
                        if (self.stop_event.is_set()
                                or time.monotonic() - started >= RECONNECT_WINDOW_SECONDS
                                or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                                or client.continuity != continuity
                                or (candidate_unresolved := getattr(client, "unresolved", False))
                                or (candidate_io_unresolved := getattr(
                                    getattr(client, "io", None), "unresolved", False))):
                            _mark_reconnect(diagnostic, phase_state="completed",
                                            outcome="candidate-fence-refused", unresolved=(
                                                True if candidate_unresolved is True
                                                or candidate_io_unresolved is True else None))
                            _mark_reconnect(diagnostic, phase="cleanup", phase_state="entered",
                                            unresolved="unknown")
                            cleanup_unresolved = self._finish(client)
                            _mark_reconnect(diagnostic, phase_state="completed",
                                            unresolved=True if cleanup_unresolved is True else None)
                            return None
                        _mark_reconnect(diagnostic, phase_state="completed", unresolved=False)
                        _mark_reconnect(diagnostic, phase="register", phase_state="entered",
                                        registration="attempted", unresolved="unknown")
                        registration_result = client.register(metadata)
                        _mark_reconnect(diagnostic, phase="register", phase_state="completed",
                                        registration="completed")
                        result = inventory_status(registration_result)
                        if result["status"] == "registered":
                            _mark_reconnect(diagnostic, phase="postregister", phase_state="entered",
                                            unresolved="unknown")
                            registered_unresolved = registered_io_unresolved = None
                            if (client.continuity == continuity and not self.stop_event.is_set()
                                    and time.monotonic() - started < RECONNECT_WINDOW_SECONDS
                                    and os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") == original_pipe
                                    and not (registered_unresolved := getattr(client, "unresolved", False))
                                    and not (registered_io_unresolved := getattr(
                                        getattr(client, "io", None), "unresolved", False))):
                                _mark_reconnect(diagnostic, phase_state="completed",
                                                outcome="reconnected", unresolved=False)
                                return client
                            _mark_reconnect(diagnostic, phase_state="completed",
                                            outcome="postregister-fence-refused", unresolved=(
                                                True if registered_unresolved is True
                                                or registered_io_unresolved is True else None))
                        elif result["status"] == "unavailable" and result.get("reason") == "busy":
                            _mark_reconnect(diagnostic, outcome="register-busy-retry")
                        else:
                            _mark_reconnect(diagnostic, outcome="register-unconfirmed")
                    _mark_reconnect(diagnostic, phase="cleanup", phase_state="entered",
                                    unresolved="unknown")
                    cleanup_unresolved = self._finish(client)
                    _mark_reconnect(diagnostic, phase_state="completed",
                                    unresolved=True if cleanup_unresolved is True else None)
                    # Explicit busy rejects admission before mutation; uncertain replies never retry.
                    if (result["status"] != "unavailable" or result.get("reason") != "busy"
                            or not self._restart_allowed or client.continuity != continuity):
                        if (result["status"] == "unavailable" and result.get("reason") == "busy"
                                and diagnostic is not None
                                and diagnostic.get("outcome") in {"ready-busy-retry", "register-busy-retry"}):
                            _mark_reconnect(diagnostic, outcome="safety-refused")
                        return None
                except Exception:
                    if diagnostic is not None:
                        phase = diagnostic.get("phase")
                        phase_state = diagnostic.get("phase_state")
                        outcome = diagnostic.get("outcome")
                        if phase == "cleanup":
                            outcome = "cleanup-error"
                        elif outcome == "unclassified":
                            if phase == "register" and diagnostic.get("registration") == "attempted":
                                outcome = "register-uncertain"
                            elif phase == "register" and diagnostic.get("registration") == "completed":
                                outcome = "register-unconfirmed"
                            elif phase == "postregister":
                                outcome = "postregister-fence-refused"
                            elif phase == "candidate-ready":
                                outcome = "ready-refused"
                            else:
                                outcome = "safety-refused"
                        if phase_state == "entered":
                            phase_state = "raised"
                        _mark_reconnect(diagnostic, phase_state=phase_state, outcome=outcome)
                    failure_trace = ((phase, phase_state, outcome)
                                     if diagnostic is not None else None)
                    _mark_reconnect(diagnostic, phase="cleanup", phase_state="entered",
                                    unresolved="unknown")
                    cleanup_unresolved = self._finish(client)
                    _mark_reconnect(diagnostic, phase_state="completed",
                                    unresolved=True if cleanup_unresolved is True else None)
                    if failure_trace is not None and failure_trace[0] != "cleanup":
                        _mark_reconnect(diagnostic, phase=failure_trace[0],
                                        phase_state=failure_trace[1], outcome=failure_trace[2])
                    if not retry_ready:
                        return None
                    try:
                        safe = (self._restart_allowed and not self.stop_event.is_set()
                            and not getattr(source_io, "unresolved", False)
                            and os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") == original_pipe
                            and client.continuity == continuity
                            and client.manifest == ready_manifest
                            and client.bootstrap_unchanged() is True)
                    except Exception:
                        safe = False
                    if not safe:
                        self._restart_allowed = False
                        _mark_reconnect(diagnostic, outcome="safety-refused")
                        return None
            if attempt + 1 == RECONNECT_MAX_ATTEMPTS:
                _mark_reconnect(diagnostic, phase="backoff", phase_state="completed",
                                outcome="attempts-exhausted", attempt=attempt + 1)
                break
            remaining = RECONNECT_WINDOW_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                _mark_reconnect(diagnostic, phase="backoff", phase_state="completed",
                                outcome="window-exhausted", attempt=attempt + 1)
                break
            _mark_reconnect(diagnostic, phase="backoff", phase_state="entered")
            if self.stop_event.wait(min(delay, remaining)):
                _mark_reconnect(diagnostic, phase="backoff", phase_state="completed",
                                outcome="reconnect-stopped")
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
