"""Inert lifecycle placeholder for the explicitly enabled Codex stdio child."""

from __future__ import annotations

import asyncio
import os
import queue
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


class InventoryWorker:
    """One finite child channel; EOF never revokes separate service custody."""

    def __init__(self, bootstrap_path: Path):
        self.stop_event = threading.Event()
        self._path = bootstrap_path
        self._requests = queue.Queue(maxsize=1)
        self._busy = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    async def register(self) -> dict:
        if self.stop_event.is_set() or "CODEX_APP_TOOLS_PIPE_PATH" not in os.environ:
            self.stop_event.set()
            return inventory_status({"reason": "stopped"})
        if self._busy:
            return inventory_status({"reason": "busy"})
        self._busy = True
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._requests.put_nowait((loop, future))
        try:
            return await asyncio.wait_for(future, timeout=3.5)
        except asyncio.TimeoutError:
            self.stop_event.set()
            return inventory_status({"reason": "timeout"})
        except asyncio.CancelledError:
            self.stop_event.set()
            raise
        finally:
            self._busy = False

    def _run(self):
        client = None
        try:
            from app.codex_bridge_pipe import NativeInventoryClient
            client = NativeInventoryClient(self._path, self.stop_event)
            ready = inventory_status(client.ready())
            if ready["status"] != "ready":
                return
            while not self.stop_event.is_set():
                try:
                    loop, future = self._requests.get(timeout=0.1)
                except queue.Empty:
                    continue
                result = inventory_status(client.register())
                if result["status"] == "unavailable":
                    self.stop_event.set()
                loop.call_soon_threadsafe(ShadowWorker._complete, future, result)
                if result["status"] == "unavailable":
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
            try:
                loop, pending = self._requests.get_nowait()
                loop.call_soon_threadsafe(ShadowWorker._complete, pending,
                    inventory_status({"reason": "stopped"}))
            except (queue.Empty, RuntimeError):
                pass
            if client is not None:
                try:
                    client.dispose()
                except Exception:
                    pass

    async def stop(self):
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
