"""Inert lifecycle placeholder for the explicitly enabled Codex stdio child."""

from __future__ import annotations

import asyncio
import os
import queue
import re
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path


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
    """One finite child channel; EOF never revokes separate service custody."""

    def __init__(self, bootstrap_path: Path, *, retained=False):
        self.stop_event = threading.Event()
        self._retained = retained
        self._closed = False
        self._path = bootstrap_path
        self._requests = queue.Queue(maxsize=1)
        self._busy = False
        self._restart_allowed = True
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

    def _finish(self, client):
        restart_allowed = self._restart_allowed
        unresolved = bool(client is not None and getattr(client, "unresolved", False))
        if client is not None:
            try:
                client.dispose()
            except Exception:
                unresolved = True
            unresolved = unresolved or bool(getattr(client, "unresolved", False))
        self._restart_allowed = restart_allowed and not unresolved

    def _recover_if_gone(self, client, native_type, original_pipe, metadata, continuity):
        if not hasattr(client, "service_current") or not self._restart_allowed:
            return None, False
        try:
            if client.service_current():
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

    def _auto_reconnect(self, native_type, original_pipe, metadata, continuity, previous_manifest=None):
        started, delay = time.monotonic(), RECONNECT_INITIAL_BACKOFF_SECONDS
        from app.codex_bridge_pipe import ShadowUnavailable
        for attempt in range(RECONNECT_MAX_ATTEMPTS):
            if (self.stop_event.is_set() or time.monotonic() - started >= RECONNECT_WINDOW_SECONDS
                    or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe
                    or not self._valid_continuity(continuity)):
                return None
            try:
                if previous_manifest is None:
                    client = native_type(self._path, self.stop_event, retained=True)
                else:
                    client = native_type(self._path, self.stop_event, retained=True,
                                         previous_manifest=previous_manifest)
            except ShadowUnavailable as exc:
                if exc.category != "startup-unavailable":
                    return None
            except Exception:
                return None
            else:
                client.continuity = continuity
                try:
                    if time.monotonic() - started >= RECONNECT_WINDOW_SECONDS:
                        self._finish(client)
                        return None
                    if inventory_status(client.ready())["status"] != "ready":
                        self._finish(client)
                        return None
                    if (self.stop_event.is_set()
                            or time.monotonic() - started >= RECONNECT_WINDOW_SECONDS
                            or os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != original_pipe):
                        self._finish(client)
                        return None
                    result = inventory_status(client.register(metadata))
                    if (result["status"] == "registered" and client.continuity == continuity
                            and not self.stop_event.is_set()
                            and time.monotonic() - started < RECONNECT_WINDOW_SECONDS
                            and os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") == original_pipe):
                        return client
                    self._finish(client)
                except Exception:
                    self._finish(client)
                return None
            if attempt + 1 == RECONNECT_MAX_ATTEMPTS:
                break
            remaining = RECONNECT_WINDOW_SECONDS - (time.monotonic() - started)
            if remaining <= 0 or self.stop_event.wait(min(delay, remaining)):
                break
            delay = min(delay * 2, RECONNECT_MAX_BACKOFF_SECONDS)
        return None

    def _run(self):
        client = None
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
                                self.stop_event.set()
                                break
                            replacement, disposed = self._recover_if_gone(
                                client, NativeInventoryClient, original_pipe, admitted_metadata, continuity)
                            if disposed:
                                client = replacement
                            if replacement is None:
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
                                self._finish(retired_client)
                                client = None
                                if not self._restart_allowed:
                                    self.stop_event.set()
                                    break
                        continue
                if future.cancelled():
                    continue
                if self._retained and client is None:
                    from app.codex_bridge_pipe import NativeInventoryClient, ShadowUnavailable
                    if retired_client is None:
                        # Ordinary first startup remains a single attempt.
                        channel_pipe = os.environ.get("CODEX_APP_TOOLS_PIPE_PATH")
                        client = NativeInventoryClient(self._path, self.stop_event, retained=True)
                        ready = inventory_status(client.ready())
                        if ready["status"] != "ready":
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
                            try:
                                bootstrap_unchanged = retired_client.bootstrap_unchanged()
                            except Exception:
                                self._restart_allowed = False
                                raise
                            if not bootstrap_unchanged:
                                self._restart_allowed = False
                                self.stop_event.set()
                                break
                            remaining = acquire_deadline - time.monotonic()
                            if remaining <= 0:
                                break
                            try:
                                client = NativeInventoryClient(self._path, self.stop_event, retained=True)
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
                            try:
                                replacement_manifest = client.manifest
                                replacement_unchanged = client.bootstrap_unchanged()
                                retired_unchanged = retired_client.bootstrap_unchanged()
                            except Exception:
                                self._restart_allowed = False
                                raise
                            if self.stop_event.is_set():
                                break
                            if (os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != retired_pipe
                                    or type(replacement_manifest) is not dict
                                    or replacement_manifest != retired_manifest
                                    or replacement_unchanged is not True
                                    or retired_unchanged is not True):
                                self._restart_allowed = False
                                self.stop_event.set()
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
                                if ready.get("reason") == "peer-mismatch":
                                    self._restart_allowed = False
                                return
                            if self.stop_event.is_set():
                                break
                            if os.environ.get("CODEX_APP_TOOLS_PIPE_PATH") != retired_pipe:
                                self._restart_allowed = False
                                self.stop_event.set()
                                break
                            retired_client = retired_manifest = None
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
                if self._retained and not was_registered and retired_pipe is not None:
                    retired_pipe = None
                try:
                    result = inventory_status(client.register(metadata))
                except Exception:
                    result = inventory_status({"reason": "native-failed"})
                if future.cancelled():
                    if self._retained and not was_registered:
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
                        client, NativeInventoryClient, original_pipe, admitted_metadata, continuity)
                    if disposed:
                        client = replacement
                    if disposed and replacement is not None:
                        continue
                    # Busy admits nothing: keep only the checked live channel and old caller.
                    if (not disposed and replacement is client
                            and result["status"] == "unavailable" and result.get("reason") == "busy"
                            and not self.stop_event.is_set() and not getattr(client, "unresolved", False)
                            and getattr(client, "continuity", None) == continuity):
                        continue
                    self.stop_event.set()
                    break
                if result["status"] == "unavailable" and not was_registered:
                    self.stop_event.set()
                    break
        except Exception:
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
                self._finish(client)

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
