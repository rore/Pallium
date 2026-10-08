"""Retained inventory worker reconnects only after an observed registration."""

import asyncio
import os
import threading
import time

import pytest

from app import codex_bridge_pipe as bridge
from app.mcp import codex_desktop_bridge as lifecycle
from app.mcp import server as mcp_server
from tests.test_codex_mcp_desktop_bridge import _serve_protocol


def _protocol_server(monkeypatch, native, operations=None):
    monkeypatch.setattr(bridge, "NativeInventoryClient", native)
    monkeypatch.setattr(lifecycle, "RECONNECT_IDLE_POLL_SECONDS", 0.01)
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "original-capability")
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:19836")
    monkeypatch.setenv("PALLIUM_CONTAINER_REF", "git:example.test/reconnect")

    class Client:
        def __init__(self, _ctx):
            pass

        async def relay_status(self, *args, **kwargs):
            if operations is not None:
                operations.append((args, kwargs))
            return {"payload": "", "deliveries": [], "payload_offset": 0,
                    "payload_total_chars": 0, "content_truncated": False, "next_offset": None}

    monkeypatch.setattr(mcp_server, "PalliumMcpClient", Client)
    return mcp_server.create_server(
        lifespan=mcp_server._codex_retained_lifespan, codex_retained=True)


async def _actual_status(session, turn):
    return await session.call_tool("pallium_relay_status", {"message_id": "message"},
        meta={"threadId": "actual-runtime", "turnId": turn})


@pytest.mark.asyncio
async def test_actual_request_reconnects_after_old_service_epoch_is_gone(monkeypatch):
    epochs = [1]
    clients = []

    class Native:
        def __init__(self, path, stop, *, retained):
            assert retained
            self.epoch = epochs[0]
            self.continuity = None
            self.unresolved = False
            self.disposals = 0
            self.registrations = []
            clients.append(self)

        def ready(self):
            return {"status": "ready", "reason": "ready"}

        def register(self, metadata):
            self.registrations.append((dict(metadata), self.continuity))
            if self.epoch != epochs[0]:
                return {"status": "unavailable", "reason": "closed"}
            if self.continuity is None:
                self.continuity = "a" * 64
            return {"status": "registered", "reason": "ok"}

        def service_current(self):
            return self.epoch == epochs[0]

        def dispose(self):
            self.disposals += 1

    operations = []
    server = _protocol_server(monkeypatch, Native, operations)

    async def exercise(session):
        async def call(turn):
            result = await session.call_tool("pallium_relay_status", {"message_id": "message"},
                meta={"threadId": "actual-runtime", "turnId": turn})
            assert not result.isError

        await call("first")
        epochs[0] = 2
        for _ in range(200):
            if len(clients) >= 2:
                break
            await asyncio.sleep(.005)
        assert len(clients) == 2
        epochs[0] = 3
        for _ in range(200):
            if len(clients) >= 3:
                break
            await asyncio.sleep(.005)
        assert len(clients) == 3
        await call("reconnected")

    await _serve_protocol(server, exercise)
    assert [(item.epoch, item.continuity) for item in clients] == [
        (1, "a" * 64), (2, "a" * 64), (3, "a" * 64)]
    assert [len(item.registrations) for item in clients] == [1, 1, 2]
    assert len(operations) == 2
    assert all(item.disposals == 1 for item in clients)


@pytest.mark.asyncio
async def test_real_request_before_idle_poll_is_not_replayed_after_recovery(monkeypatch):
    epochs, clients, operations = [1], [], []

    class Native:
        def __init__(self, *args, retained, previous_manifest=None):
            self.epoch = epochs[0]
            self.manifest = {"epoch": self.epoch}
            self.continuity = None
            self.unresolved = False
            self.registrations = 0
            clients.append(self)

        def ready(self):
            return {"status": "ready"}

        def register(self, _metadata):
            self.registrations += 1
            if self.epoch != epochs[0]:
                return {"status": "unavailable", "reason": "closed"}
            self.continuity = self.continuity or "a" * 64
            return {"status": "registered", "reason": "ok"}

        def service_current(self):
            return self.epoch == epochs[0]

        def dispose(self):
            pass

    server = _protocol_server(monkeypatch, Native, operations)
    monkeypatch.setattr(lifecycle, "RECONNECT_IDLE_POLL_SECONDS", 5)

    async def exercise(session):
        assert not (await _actual_status(session, "first")).isError
        epochs[0] = 2
        assert not (await _actual_status(session, "trigger")).isError
        for _ in range(200):
            if len(clients) == 2:
                break
            await asyncio.sleep(.005)
        assert len(clients) == 2
        assert not (await _actual_status(session, "after-recovery")).isError

    await _serve_protocol(server, exercise)
    assert len(operations) == 3
    assert [client.registrations for client in clients] == [2, 2]


@pytest.mark.asyncio
async def test_retained_protocol_does_not_enroll_before_a_real_request(monkeypatch):
    clients = []

    class Native:
        def __init__(self, *args, **kwargs):
            clients.append(self)

    server = _protocol_server(monkeypatch, Native)
    await _serve_protocol(server, lambda _session: asyncio.sleep(.03))
    assert clients == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["unavailable", "busy", "missing-proof"])
async def test_unsuccessful_or_unproven_registration_never_enables_reconnect(monkeypatch, reply):
    epochs, clients = [1], []

    class Native:
        def __init__(self, *args, **kwargs):
            self.epoch = epochs[0]
            self.continuity = None
            self.unresolved = False
            clients.append(self)

        def ready(self):
            return {"status": "ready"}

        def register(self, _metadata):
            if reply in {"unavailable", "busy"}:
                reason = "busy" if reply == "busy" else "closed"
                return {"status": "unavailable", "reason": reason}
            return {"status": "registered", "reason": "ok"}

        def service_current(self):
            return self.epoch == epochs[0]

        def dispose(self):
            pass

    server = _protocol_server(monkeypatch, Native)

    async def exercise(session):
        await _actual_status(session, "first")
        epochs[0] = 2
        await asyncio.sleep(.05)

    await _serve_protocol(server, exercise)
    assert len(clients) == 1


@pytest.mark.asyncio
async def test_retry_limit_applies_only_to_typed_startup_unavailability(monkeypatch):
    epochs, clients, attempts = [1], [], []

    class Native:
        def __init__(self, *args, retained, previous_manifest=None):
            self.epoch = epochs[0]
            self.manifest = {"epoch": self.epoch}
            self.continuity = None
            self.unresolved = False
            clients.append(self)
            if self.epoch > 1:
                attempts.append(previous_manifest)
                raise bridge.ShadowUnavailable("startup-unavailable")

        def ready(self):
            return {"status": "ready"}

        def register(self, _metadata):
            self.continuity = "b" * 64
            return {"status": "registered", "reason": "ok"}

        def service_current(self):
            return self.epoch == epochs[0]

        def dispose(self):
            pass

    monkeypatch.setattr(lifecycle, "RECONNECT_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(lifecycle, "RECONNECT_WINDOW_SECONDS", 5)
    monkeypatch.setattr(lifecycle, "RECONNECT_INITIAL_BACKOFF_SECONDS", .001)
    monkeypatch.setattr(lifecycle, "RECONNECT_MAX_BACKOFF_SECONDS", .001)
    server = _protocol_server(monkeypatch, Native)

    async def exercise(session):
        await _actual_status(session, "first")
        epochs[0] = 2
        for _ in range(100):
            if len(attempts) == 3:
                break
            await asyncio.sleep(.005)
        await asyncio.sleep(.02)

    await _serve_protocol(server, exercise)
    assert len(attempts) == 3
    assert attempts == [{"epoch": 1}] * 3
    assert len(clients) == 4


@pytest.mark.asyncio
async def test_retry_deadline_and_shutdown_bound_startup_retries(monkeypatch):
    epochs, attempts = [1], []
    waiting = threading.Event()

    class Native:
        def __init__(self, *args, retained, previous_manifest=None):
            self.epoch = epochs[0]
            self.manifest = {"epoch": self.epoch}
            self.continuity = None
            self.unresolved = False
            if self.epoch > 1:
                attempts.append(previous_manifest)
                waiting.set()
                time.sleep(.01)
                raise bridge.ShadowUnavailable("startup-unavailable")

        def ready(self):
            return {"status": "ready"}

        def register(self, _metadata):
            self.continuity = "c" * 64
            return {"status": "registered", "reason": "ok"}

        def service_current(self):
            return self.epoch == epochs[0]

        def dispose(self):
            pass

    monkeypatch.setattr(lifecycle, "RECONNECT_MAX_ATTEMPTS", 12)
    monkeypatch.setattr(lifecycle, "RECONNECT_WINDOW_SECONDS", .025)
    monkeypatch.setattr(lifecycle, "RECONNECT_INITIAL_BACKOFF_SECONDS", .01)
    monkeypatch.setattr(lifecycle, "RECONNECT_MAX_BACKOFF_SECONDS", .01)
    server = _protocol_server(monkeypatch, Native)

    async def exercise(session):
        await _actual_status(session, "first")
        epochs[0] = 2
        await asyncio.to_thread(waiting.wait, .5)

    await _serve_protocol(server, exercise)
    assert attempts == [{"epoch": 1}]


@pytest.mark.asyncio
async def test_unresolved_old_channel_prevents_replacement(monkeypatch):
    epochs, clients = [1], []

    class Native:
        def __init__(self, *args, **kwargs):
            self.epoch = epochs[0]
            self.continuity = None
            self.unresolved = False
            self.disposals = 0
            clients.append(self)

        def ready(self):
            return {"status": "ready"}

        def register(self, _metadata):
            self.continuity = "d" * 64
            return {"status": "registered", "reason": "ok"}

        def service_current(self):
            return self.epoch == epochs[0]

        def dispose(self):
            self.disposals += 1
            self.unresolved = True

    server = _protocol_server(monkeypatch, Native)

    async def exercise(session):
        await _actual_status(session, "first")
        epochs[0] = 2
        await asyncio.sleep(.05)

    await _serve_protocol(server, exercise)
    assert len(clients) == 1 and clients[0].disposals == 1


@pytest.mark.asyncio
async def test_capability_change_stops_auto_recovery_but_fresh_request_can_register(monkeypatch):
    epochs, clients = [1], []

    class Native:
        def __init__(self, *args, **kwargs):
            self.epoch = epochs[0]
            self.capability = os.environ["CODEX_APP_TOOLS_PIPE_PATH"]
            self.continuity = None
            self.unresolved = False
            clients.append(self)

        def ready(self):
            return {"status": "ready"}

        def register(self, _metadata):
            if self.epoch != epochs[0]:
                return {"status": "unavailable", "reason": "closed"}
            self.continuity = "f" * 64
            return {"status": "registered", "reason": "ok"}

        def service_current(self):
            return self.epoch == epochs[0]

        def dispose(self):
            pass

    monkeypatch.setattr(bridge, "native_available", lambda: True)
    server = _protocol_server(monkeypatch, Native)

    async def exercise(session):
        await _actual_status(session, "first")
        epochs[0] = 2
        os.environ["CODEX_APP_TOOLS_PIPE_PATH"] = "changed-capability"
        await asyncio.sleep(.05)
        assert len(clients) == 1
        result = await _actual_status(session, "fresh")
        assert not result.isError

    await _serve_protocol(server, exercise)
    assert [item.capability for item in clients] == ["original-capability", "changed-capability"]


@pytest.mark.asyncio
@pytest.mark.parametrize("busy_reply", [
    ({"status": "unavailable", "reason": "busy"}, True),
    ({"status": "unavailable", "reason": "closed"}, False),
])
# FastMCP caller surface is real; Native replies are simulated, not Win32 pipe coverage.
async def test_retained_worker_preserves_admission_after_busy_reregister(monkeypatch, busy_reply):
    busy_reply, preserves = busy_reply
    epochs, clients, calls = [1], [], []
    proof = "9" * 64

    class Native:
        def __init__(self, *args, **kwargs):
            self.epoch = epochs[0]
            self.continuity = None
            self.unresolved = False
            self.disposals = 0
            clients.append(self)

        def ready(self):
            return {"status": "ready"}

        def register(self, metadata):
            calls.append((self, dict(metadata)))
            if len(calls) == 1:
                self.continuity = proof
                return {"status": "registered", "reason": "ok"}
            if len(calls) == 2:
                return dict(busy_reply)
            self.continuity = proof
            return {"status": "registered", "reason": "ok"}

        def service_current(self):
            return self.epoch == epochs[0]

        def dispose(self):
            self.disposals += 1

    monkeypatch.setattr(bridge, "native_available", lambda: True)
    server = _protocol_server(monkeypatch, Native)

    async def exercise(session):
        assert not (await _actual_status(session, "admitted")).isError
        busy = await _actual_status(session, "busy")
        assert not busy.isError
        await asyncio.sleep(.03)
        assert len(clients) == 1
        assert clients[0].continuity == proof
        assert clients[0].service_current() and not clients[0].unresolved
        assert len(calls) == 2
        assert clients[0].disposals == (0 if preserves else 1)
        assert calls[0][1] == {"thread_ref": "actual-runtime", "turn_ref": "admitted"}
        assert calls[1][1] == {"thread_ref": "actual-runtime", "turn_ref": "busy"}
        if preserves:
            epochs[0] = 2
            for _ in range(200):
                if len(calls) == 3:
                    break
                await asyncio.sleep(.005)
            assert len(clients) == 2
            assert calls[2][0] is clients[1]
            assert calls[2][1] == calls[0][1]
        assert not (await _actual_status(session, "fresh")).isError

    await _serve_protocol(server, exercise)
    assert len(clients) == 2
    assert clients[-1].continuity == proof
    assert calls[-1][0] is clients[-1]
    assert calls[-1][1] == {"thread_ref": "actual-runtime", "turn_ref": "fresh"}
    turns = [metadata["turn_ref"] for _, metadata in calls]
    assert turns == (["admitted", "busy", "admitted", "fresh"] if preserves
                     else ["admitted", "busy", "fresh"])


@pytest.mark.asyncio
async def test_busy_auto_reconnect_is_not_retried_before_a_fresh_call(monkeypatch):
    epochs, clients, calls = [1], [], []
    workers = []
    dispose_started, release_dispose = threading.Event(), threading.Event()
    proof = "8" * 64

    class ObservedWorker(lifecycle.InventoryWorker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            workers.append(self)

    class Native:
        def __init__(self, *args, **kwargs):
            self.epoch = epochs[0]
            self.continuity = None
            self.unresolved = False
            self.disposals = 0
            clients.append(self)

        def ready(self):
            return {"status": "ready"}

        def register(self, metadata):
            calls.append((self, dict(metadata)))
            if len(calls) == 2:
                return {"status": "unavailable", "reason": "busy"}
            self.continuity = proof
            return {"status": "registered", "reason": "ok"}

        def service_current(self):
            return self.epoch == epochs[0]

        def dispose(self):
            self.disposals += 1
            if len(clients) > 1 and self is clients[1]:
                dispose_started.set()
                release_dispose.wait()

    monkeypatch.setattr(bridge, "native_available", lambda: True)
    monkeypatch.setattr(lifecycle, "InventoryWorker", ObservedWorker)
    server = _protocol_server(monkeypatch, Native)

    async def exercise(session):
        assert not (await _actual_status(session, "admitted")).isError
        epochs[0] = 2
        try:
            assert await asyncio.to_thread(dispose_started.wait, 1)
            worker = workers[0]
            assert len(clients) == 2
            assert len(calls) == 2
            assert clients[1].disposals == 1
            assert worker._thread.is_alive()
        finally:
            release_dispose.set()
        # Disposal precedes worker retirement; only a later request may restart it.
        deadline = time.monotonic() + 1
        while worker._thread.is_alive() and time.monotonic() < deadline:
            await asyncio.sleep(.005)
        assert not worker._thread.is_alive()
        assert worker.stop_event.is_set() and worker._restart_allowed
        assert len(clients) == 2
        assert len(calls) == 2
        assert not (await _actual_status(session, "fresh")).isError

    try:
        await _serve_protocol(server, exercise)
    finally:
        release_dispose.set()
    assert len(clients) == 3
    assert len(calls) == 3
    assert calls[0][1]["turn_ref"] == "admitted"
    assert calls[1][1]["turn_ref"] == "admitted"
    assert calls[2][0] is clients[2]
    assert calls[2][1]["turn_ref"] == "fresh"


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", [
    "proof", "unresolved", "service-gone", "service-error", "capability", "thread",
])
async def test_busy_response_does_not_preserve_changed_or_unresolved_admission(monkeypatch, denial):
    clients, calls = [], []
    proof = "7" * 64

    class Native:
        def __init__(self, _path, stop, *, retained):
            assert retained
            self.stop = stop
            self.continuity = None
            self.unresolved = False
            self.fail_current = False
            self.current = True
            self.disposals = 0
            clients.append(self)

        def ready(self):
            return {"status": "ready"}

        def register(self, metadata):
            calls.append(dict(metadata))
            if len(calls) == 1:
                self.continuity = proof
                return {"status": "registered", "reason": "ok"}
            if denial == "proof":
                self.continuity = "6" * 64
            elif denial == "unresolved":
                self.unresolved = True
            elif denial == "service-gone":
                self.current = False
            elif denial == "service-error":
                self.fail_current = True
            return {"status": "unavailable", "reason": "busy"}

        def service_current(self):
            if self.fail_current:
                raise RuntimeError("service state unresolved")
            return self.current

        def dispose(self):
            self.disposals += 1

    server = _protocol_server(monkeypatch, Native)

    async def exercise(session):
        assert not (await _actual_status(session, "admitted")).isError
        if denial == "capability":
            os.environ["CODEX_APP_TOOLS_PIPE_PATH"] = "changed-capability"
            result = await _actual_status(session, "changed-capability")
        elif denial == "thread":
            result = await session.call_tool("pallium_relay_status", {"message_id": "message"},
                meta={"threadId": "changed-runtime", "turnId": "changed-thread"})
        else:
            result = await _actual_status(session, "busy")
        assert not result.isError
        await asyncio.sleep(.03)

    await _serve_protocol(server, exercise)
    if denial == "service-gone":
        assert len(clients) == 2
        assert len(calls) == 3
        assert calls[2] == {"thread_ref": "actual-runtime", "turn_ref": "admitted"}
        assert [client.disposals for client in clients] == [1, 1]
    else:
        assert len(clients) == 1
        assert len(calls) == (1 if denial in {"capability", "thread"} else 2)
        assert clients[0].disposals == 1
    if denial == "proof":
        assert clients[0].continuity != proof
    if denial == "unresolved":
        assert clients[0].unresolved


@pytest.mark.asyncio
async def test_concurrent_actual_requests_do_not_create_a_second_worker(monkeypatch):
    clients, register_started, release_register = [], threading.Event(), threading.Event()

    class Native:
        def __init__(self, *args, **kwargs):
            self.continuity = None
            self.unresolved = False
            clients.append(self)

        def ready(self):
            return {"status": "ready"}

        def register(self, metadata):
            register_started.set()
            release_register.wait(1)
            self.continuity = "1" * 64
            return {"status": "registered", "reason": "ok"}

        def dispose(self):
            pass

    server = _protocol_server(monkeypatch, Native)

    async def exercise(session):
        first = asyncio.create_task(_actual_status(session, "first"))
        assert await asyncio.to_thread(register_started.wait, .5)
        second = await _actual_status(session, "concurrent")
        assert not second.isError
        release_register.set()
        assert not (await first).isError

    try:
        await _serve_protocol(server, exercise)
    finally:
        release_register.set()
    assert len(clients) == 1


@pytest.mark.asyncio
async def test_cancelled_queued_actual_request_is_skipped(monkeypatch):
    ready_started, release_ready = threading.Event(), threading.Event()
    registrations, clients = [], []

    class Native:
        def __init__(self, *args, **kwargs):
            clients.append(self)
            self.continuity = None
            self.unresolved = False
            self.manifest = {"epoch": "same"}

        def bootstrap_unchanged(self):
            return True

        def ready(self):
            ready_started.set()
            release_ready.wait(1)
            return {"status": "ready"}

        def register(self, metadata):
            registrations.append(dict(metadata))
            self.continuity = "e" * 64
            return {"status": "registered", "reason": "ok"}

        def dispose(self):
            pass

    monkeypatch.setattr(bridge, "NativeInventoryClient", Native)
    monkeypatch.setattr(lifecycle, "RECONNECT_IDLE_POLL_SECONDS", 0.01)
    monkeypatch.setenv("PALLIUM_BASE_URL", "http://localhost:19836")
    monkeypatch.setenv("PALLIUM_AGENT_REF", "codex")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "original-capability")
    async with lifecycle.retained_lifespan(None) as state:
        worker = state["codex_retained"]
        cancelled = asyncio.create_task(worker.register(
            {"thread_ref": "actual-runtime", "turn_ref": "cancelled"}))
        assert await asyncio.to_thread(ready_started.wait, .5)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        kept = asyncio.create_task(worker.register({"thread_ref": "actual-runtime", "turn_ref": "kept"}))
        await asyncio.sleep(0)
        release_ready.set()
        result = await kept
        assert result["status"] == "registered"
    release_ready.set()
    assert registrations == [{"thread_ref": "actual-runtime", "turn_ref": "kept"}]
    assert len(clients) == 1


def _cancelled_initial_worker(monkeypatch, *, construct=None, bootstrap=None, ready=None, dispose=None,
                              hold_disposal=False):
    state = {"clients": [], "constructs": 0, "ready": [], "registrations": [],
             "candidate_disposed": threading.Event()}
    events = {name: threading.Event() for name in (
        "ready_started", "release_ready", "dispose_started", "release_dispose", "dispose_finished")}
    if not hold_disposal:
        events["release_dispose"].set()

    class Native:
        def __init__(self, *_args, **_kwargs):
            self.index = state["constructs"]
            state["constructs"] += 1
            self.disposed = False
            self.unresolved = False
            self.continuity = None
            self.manifest = {"epoch": "same"}
            if construct is not None:
                construct(self.index, self)
            state["clients"].append(self)

        def bootstrap_unchanged(self):
            return True if bootstrap is None else bootstrap(self.index, self)

        def ready(self):
            state["ready"].append(self.index)
            if self.index == 0:
                events["ready_started"].set()
                events["release_ready"].wait(1)
            if ready is not None:
                result = ready(self.index, self)
                if result is not None:
                    return result
            return {"status": "ready"}

        def register(self, metadata):
            state["registrations"].append((self.index, dict(metadata)))
            self.continuity = "a" * 64
            return {"status": "registered", "reason": "ok"}

        def dispose(self):
            self.disposed = True
            if self.index == 0:
                events["dispose_started"].set()
                events["release_dispose"].wait(1)
            try:
                if dispose is not None:
                    dispose(self.index, self)
            finally:
                if self.index == 0:
                    events["dispose_finished"].set()
                else:
                    state["candidate_disposed"].set()

    monkeypatch.setattr(bridge, "NativeInventoryClient", Native)
    monkeypatch.setattr(bridge, "native_available", lambda: True)
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "original-capability")
    worker = lifecycle.InventoryWorker("unused-bootstrap", retained=True)
    return worker, state, events


@pytest.mark.asyncio
@pytest.mark.parametrize("journey", ["queued-before-disposal", "queued-during-disposal", "terminal-bootstrap"])
async def test_mcp_cancellation_releases_unused_channel_for_fresh_request(monkeypatch, journey):
    from mcp.shared.exceptions import McpError
    from mcp.types import CancelledNotification, CancelledNotificationParams, ClientNotification

    clients, calls, operations, workers, request_ids = [], [], [], [], []
    ready_started, release_ready = threading.Event(), threading.Event()
    dispose_started, release_dispose, dispose_finished = (
        threading.Event(), threading.Event(), threading.Event())
    if journey != "queued-during-disposal":
        release_dispose.set()

    class Native:
        def __init__(self, *_args, **_kwargs):
            self.index = len(clients)
            self.manifest = {"epoch": "same"}
            self.continuity = None
            self.unresolved = False
            self.disposed = False
            clients.append(self)

        def bootstrap_unchanged(self):
            return not (journey == "terminal-bootstrap" and self.index == 0 and self.disposed)

        def ready(self):
            calls.append(("ready", self.index))
            if self.index == 0:
                ready_started.set()
                if not release_ready.wait(5):
                    raise AssertionError("test did not release ready gate")
            return {"status": "ready"}

        def register(self, metadata):
            calls.append(("register", self.index, dict(metadata)))
            self.continuity = "c" * 64
            return {"status": "registered", "reason": "ok"}

        def dispose(self):
            self.disposed = True
            calls.append(("dispose", self.index))
            if self.index == 0:
                dispose_started.set()
                if not release_dispose.wait(5):
                    raise AssertionError("test did not release disposal gate")
                dispose_finished.set()

    original_worker = lifecycle.InventoryWorker

    class CapturingWorker(original_worker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            workers.append(self)

    monkeypatch.setattr(lifecycle, "InventoryWorker", CapturingWorker)
    monkeypatch.setattr(bridge, "NativeInventoryClient", Native)
    monkeypatch.setattr(bridge, "native_available", lambda: True)
    server = _protocol_server(monkeypatch, Native, operations)

    async def queue_request(session, worker, turn):
        task = asyncio.create_task(_actual_status(session, turn))
        deadline = time.monotonic() + 1
        while worker._requests.qsize() != 1 and time.monotonic() < deadline:
            await asyncio.sleep(.005)
        assert worker._requests.qsize() == 1
        return task

    async def exercise(session):
        original_send_request = session.send_request
        pending = []

        async def observe_request(*args, **kwargs):
            request_ids.append(session._request_id)
            return await original_send_request(*args, **kwargs)

        session.send_request = observe_request
        first = asyncio.create_task(_actual_status(session, "cancelled"))
        pending.append(first)
        assert await asyncio.to_thread(ready_started.wait, .5)
        deadline = time.monotonic() + 1
        while not request_ids and time.monotonic() < deadline:
            await asyncio.sleep(.005)
        assert request_ids
        try:
            await session.send_notification(ClientNotification(CancelledNotification(
                params=CancelledNotificationParams(requestId=request_ids[0], reason="test cancellation"))))
            with pytest.raises(McpError):
                await asyncio.wait_for(first, 1)

            worker = workers[0]
            if journey == "queued-before-disposal":
                fresh = await queue_request(session, worker, "fresh")
                pending.append(fresh)
                release_ready.set()
                result = await asyncio.wait_for(fresh, 1)
                assert not result.isError
            else:
                release_ready.set()
                assert await asyncio.to_thread(dispose_started.wait, 1)
                if journey == "queued-during-disposal":
                    fresh = await queue_request(session, worker, "fresh")
                    pending.append(fresh)
                    release_dispose.set()
                    result = await asyncio.wait_for(fresh, 1)
                    assert not result.isError
                else:
                    release_dispose.set()
                    assert await asyncio.to_thread(dispose_finished.wait, 1)
                    await _actual_status(session, "fresh")
                    await _actual_status(session, "later")
                    assert calls == [("ready", 0), ("dispose", 0)]
        finally:
            release_ready.set()
            release_dispose.set()
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    try:
        await _serve_protocol(server, exercise)
    finally:
        release_ready.set()
        release_dispose.set()
        if workers:
            await workers[0].stop()
    assert workers and not workers[0]._thread.is_alive()

    if journey == "queued-before-disposal":
        assert len(clients) == 1
        assert calls == [("ready", 0), ("register", 0,
            {"thread_ref": "actual-runtime", "turn_ref": "fresh"}), ("dispose", 0)]
        assert len(operations) == 1
    elif journey == "queued-during-disposal":
        assert len(clients) == 2
        assert calls == [("ready", 0), ("dispose", 0), ("ready", 1),
            ("register", 1, {"thread_ref": "actual-runtime", "turn_ref": "fresh"}), ("dispose", 1)]
        assert len(operations) == 1
    else:
        assert len(clients) == 1
        assert calls == [("ready", 0), ("dispose", 0)]
        assert len(operations) == 2
    assert all(call[0] != "register" or call[2]["turn_ref"] != "cancelled" for call in calls)


@pytest.mark.asyncio
async def test_mcp_cancellation_after_retained_admission_does_not_replay(monkeypatch):
    from mcp.shared.exceptions import McpError
    from mcp.types import CancelledNotification, CancelledNotificationParams, ClientNotification

    clients, registrations, operations, workers, request_ids = [], [], [], [], []
    register_started, release_register = threading.Event(), threading.Event()

    class Native:
        def __init__(self, *_args, **_kwargs):
            self.continuity = None
            self.unresolved = False
            self.manifest = {"epoch": "same"}
            self.disposals = 0
            clients.append(self)

        def ready(self):
            return {"status": "ready"}

        def register(self, metadata):
            registrations.append(dict(metadata))
            if metadata["turn_ref"] == "cancelled-admitted":
                register_started.set()
                if not release_register.wait(5):
                    raise AssertionError("test did not release admitted register gate")
            self.continuity = "d" * 64
            return {"status": "registered", "reason": "ok"}

        def service_current(self):
            return True

        def dispose(self):
            self.disposals += 1

    original_worker = lifecycle.InventoryWorker

    class CapturingWorker(original_worker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            workers.append(self)

    monkeypatch.setattr(lifecycle, "InventoryWorker", CapturingWorker)
    monkeypatch.setattr(bridge, "NativeInventoryClient", Native)
    monkeypatch.setattr(bridge, "native_available", lambda: True)
    server = _protocol_server(monkeypatch, Native, operations)

    async def exercise(session):
        original_send_request = session.send_request

        async def observe_request(*args, **kwargs):
            request_ids.append(session._request_id)
            return await original_send_request(*args, **kwargs)

        session.send_request = observe_request
        assert not (await _actual_status(session, "admitted")).isError
        cancelled = asyncio.create_task(_actual_status(session, "cancelled-admitted"))
        assert await asyncio.to_thread(register_started.wait, .5)
        assert len(request_ids) >= 2
        await session.send_notification(ClientNotification(CancelledNotification(
            params=CancelledNotificationParams(requestId=request_ids[-1], reason="test cancellation"))))
        with pytest.raises(McpError):
            await asyncio.wait_for(cancelled, 1)
        release_register.set()
        assert not (await _actual_status(session, "after-cancel")).isError

    try:
        await _serve_protocol(server, exercise)
    finally:
        release_register.set()
        if workers:
            await workers[0].stop()
    assert len(clients) == 1 and clients[0].disposals == 1
    assert registrations == [
        {"thread_ref": "actual-runtime", "turn_ref": "admitted"},
        {"thread_ref": "actual-runtime", "turn_ref": "cancelled-admitted"},
        {"thread_ref": "actual-runtime", "turn_ref": "after-cancel"},
    ]
    assert len(operations) == 2
    assert workers and not workers[0]._thread.is_alive()


async def _cancel_initial_request(worker, events):
    first = asyncio.create_task(worker.register(
        {"thread_ref": "actual-runtime", "turn_ref": "cancelled"}))
    assert await asyncio.to_thread(events["ready_started"].wait, .5)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    events["release_ready"].set()
    assert await asyncio.to_thread(events["dispose_started"].wait, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("queue_during_disposal", [False, True])
async def test_cancelled_first_ready_releases_resolved_channel_and_keeps_fresh_request(
        monkeypatch, queue_during_disposal):
    worker, state, events = _cancelled_initial_worker(monkeypatch, hold_disposal=True)
    metadata = {"thread_ref": "actual-runtime", "turn_ref": "fresh"}
    second = None
    try:
        await _cancel_initial_request(worker, events)
        if queue_during_disposal:
            second = asyncio.create_task(worker.register(metadata))
            await asyncio.sleep(0)
            assert worker._requests.qsize() == 1
            events["release_dispose"].set()
        else:
            events["release_dispose"].set()
            assert await asyncio.to_thread(events["dispose_finished"].wait, 1)
            second = asyncio.create_task(worker.register(metadata))
        result = await asyncio.wait_for(second, 1)
        assert result["status"] == "registered"
        assert len(state["clients"]) == 2
        assert state["ready"] == [0, 1]
        assert state["registrations"] == [(1, metadata)]
    finally:
        events["release_ready"].set()
        events["release_dispose"].set()
        if second is not None and not second.done():
            second.cancel()
            await asyncio.gather(second, return_exceptions=True)
        await worker.stop()
    assert not worker._thread.is_alive()


@pytest.mark.asyncio
async def test_initial_startup_unavailability_is_not_retried(monkeypatch):
    attempts = []

    class Native:
        def __init__(self, *_args, **_kwargs):
            attempts.append("construct")
            raise bridge.ShadowUnavailable("startup-unavailable")

    monkeypatch.setattr(bridge, "NativeInventoryClient", Native)
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "original-capability")
    worker = lifecycle.InventoryWorker("unused-bootstrap", retained=True)
    try:
        result = await worker.register({"thread_ref": "actual-runtime", "turn_ref": "first"})
        assert result["status"] == "unavailable"
        assert result["reason"] == "native-failed"
        assert attempts == ["construct"]
    finally:
        await worker.stop()


@pytest.mark.asyncio
async def test_retired_channel_retries_only_startup_unavailability(monkeypatch):
    attempts = []

    def construct(index, _client):
        if index:
            attempts.append(index)
            if index < 3:
                raise bridge.ShadowUnavailable("startup-unavailable")

    worker, state, events = _cancelled_initial_worker(monkeypatch, construct=construct)
    try:
        await _cancel_initial_request(worker, events)
        events["release_dispose"].set()
        assert await asyncio.to_thread(events["dispose_finished"].wait, 1)
        result = await worker.register({"thread_ref": "actual-runtime", "turn_ref": "fresh"})
        assert result["status"] == "registered"
        assert attempts == [1, 2, 3]
        assert state["ready"] == [0, 3]
        assert state["registrations"] == [(3, {"thread_ref": "actual-runtime", "turn_ref": "fresh"})]
    finally:
        events["release_ready"].set()
        await worker.stop()


@pytest.mark.asyncio
async def test_retired_channel_does_not_retry_non_startup_constructor_error(monkeypatch):
    attempts = []

    def construct(index, _client):
        if index:
            attempts.append(index)
            raise bridge.ShadowUnavailable("peer-mismatch")

    worker, state, events = _cancelled_initial_worker(monkeypatch, construct=construct)
    try:
        await _cancel_initial_request(worker, events)
        events["release_dispose"].set()
        assert await asyncio.to_thread(events["dispose_finished"].wait, 1)
        result = await worker.register({"thread_ref": "actual-runtime", "turn_ref": "fresh"})
        assert result["reason"] == "native-failed"
        assert attempts == [1]
        assert len(state["clients"]) == 1
        assert state["ready"] == [0] and state["registrations"] == []
        assert not worker._restart_allowed
        assert (await worker.register({"thread_ref": "actual-runtime", "turn_ref": "later"}))[
            "reason"] == "stopped"
        assert state["constructs"] == 2 and len(state["clients"]) == 1
    finally:
        events["release_ready"].set()
        await worker.stop()


@pytest.mark.asyncio
async def test_retired_channel_acquisition_expires_then_worker_accepts_fresh_call(monkeypatch):
    allow_replacement = threading.Event()

    def construct(index, _client):
        if index and not allow_replacement.is_set():
            raise bridge.ShadowUnavailable("startup-unavailable")

    worker, state, events = _cancelled_initial_worker(monkeypatch, construct=construct)
    try:
        await _cancel_initial_request(worker, events)
        events["release_dispose"].set()
        assert await asyncio.to_thread(events["dispose_finished"].wait, 1)
        started = time.monotonic()
        failed = await worker.register({"thread_ref": "actual-runtime", "turn_ref": "waited"})
        assert failed["status"] == "unavailable" and failed["reason"] == "native-failed"
        assert .9 <= time.monotonic() - started < 1.5
        assert state["ready"] == [0] and state["registrations"] == []

        allow_replacement.set()
        recovered = await worker.register({"thread_ref": "actual-runtime", "turn_ref": "later"})
        assert recovered["status"] == "registered"
        assert state["ready"] == [0, state["clients"][-1].index]
        assert state["registrations"] == [(state["clients"][-1].index,
            {"thread_ref": "actual-runtime", "turn_ref": "later"})]
    finally:
        events["release_ready"].set()
        await worker.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["capability", "bootstrap", "bootstrap-error",
                                     "candidate-manifest", "candidate-bootstrap"])
async def test_retired_channel_fences_changed_or_untrusted_replacement(monkeypatch, failure):
    def construct(index, client):
        if index and failure == "capability":
            os.environ["CODEX_APP_TOOLS_PIPE_PATH"] = "changed-capability"
        if index and failure == "candidate-manifest":
            client.manifest = {"epoch": "changed"}

    def bootstrap(index, client):
        if index == 0 and client.disposed and failure == "bootstrap-error":
            raise bridge.ShadowUnavailable("peer-mismatch")
        if index == 0 and client.disposed and failure == "bootstrap":
            return False
        if index and failure == "candidate-bootstrap":
            return False
        return True

    def dispose(index, client):
        if index and failure == "candidate-manifest":
            client.unresolved = True

    worker, state, events = _cancelled_initial_worker(
        monkeypatch, construct=construct, bootstrap=bootstrap, dispose=dispose)
    try:
        await _cancel_initial_request(worker, events)
        events["release_dispose"].set()
        assert await asyncio.to_thread(events["dispose_finished"].wait, 1)
        result = await worker.register({"thread_ref": "actual-runtime", "turn_ref": "fresh"})
        assert result["status"] == "unavailable"
        expected_clients = 2 if failure in {"capability", "candidate-manifest", "candidate-bootstrap"} else 1
        assert len(state["clients"]) == expected_clients
        assert state["registrations"] == []
        assert state["ready"] == [0]
        if expected_clients == 2:
            assert await asyncio.to_thread(state["candidate_disposed"].wait, 1)
            assert state["clients"][1].disposed
        if failure == "candidate-manifest":
            assert not worker._restart_allowed
            assert (await worker.register({"thread_ref": "actual-runtime", "turn_ref": "later"}))[
                "reason"] == "stopped"
            assert len(state["clients"]) == 2
        elif failure in {"capability", "bootstrap", "bootstrap-error", "candidate-bootstrap"}:
            assert not worker._restart_allowed
            constructs = state["constructs"]
            assert (await worker.register({"thread_ref": "actual-runtime", "turn_ref": "later"}))[
                "reason"] == "stopped"
            assert state["constructs"] == constructs
    finally:
        events["release_ready"].set()
        await worker.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["replace", "remove"])
async def test_retired_channel_rechecks_capability_after_replacement_ready(monkeypatch, change):
    def ready(index, _client):
        if index:
            if change == "replace":
                os.environ["CODEX_APP_TOOLS_PIPE_PATH"] = "changed-capability"
            else:
                os.environ.pop("CODEX_APP_TOOLS_PIPE_PATH", None)

    worker, state, events = _cancelled_initial_worker(monkeypatch, ready=ready)
    try:
        await _cancel_initial_request(worker, events)
        events["release_dispose"].set()
        assert await asyncio.to_thread(events["dispose_finished"].wait, 1)
        result = await worker.register({"thread_ref": "actual-runtime", "turn_ref": change})
        assert result["reason"] == "stopped"
        assert len(state["clients"]) == 2
        assert state["ready"] == [0, 1]
        assert state["registrations"] == []
        assert await asyncio.to_thread(state["candidate_disposed"].wait, 1)
        assert state["clients"][1].disposed
        assert not worker._restart_allowed
        assert (await worker.register({"thread_ref": "actual-runtime", "turn_ref": "later"}))[
            "reason"] == "stopped"
        assert state["constructs"] == 2
    finally:
        events["release_ready"].set()
        await worker.stop()


@pytest.mark.asyncio
async def test_cancelled_replacement_ready_keeps_retired_capability_fence_at_idle(monkeypatch):
    candidate_ready_started, release_candidate_ready = threading.Event(), threading.Event()
    switched = threading.Event()
    post_ready_reads = []
    original_get = os.environ.get
    worker = None

    def controlled_get(key, default=None):
        if (key == "CODEX_APP_TOOLS_PIPE_PATH" and worker is not None
                and threading.current_thread() is worker._thread
                and switched.is_set()):
            if not post_ready_reads:
                post_ready_reads.append("post-ready")
                return original_get(key, default)
            return "changed-capability"
        return original_get(key, default)

    def ready(index, _client):
        if index == 1:
            candidate_ready_started.set()
            if not release_candidate_ready.wait(5):
                raise AssertionError("test did not release replacement ready gate")

    worker, state, events = _cancelled_initial_worker(monkeypatch, ready=ready)
    monkeypatch.setattr(os.environ, "get", controlled_get)
    request = None
    try:
        await _cancel_initial_request(worker, events)
        events["release_dispose"].set()
        assert await asyncio.to_thread(events["dispose_finished"].wait, 1)
        request = asyncio.create_task(worker.register({"thread_ref": "actual-runtime", "turn_ref": "cancelled-ready"}))
        assert await asyncio.to_thread(candidate_ready_started.wait, 1)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        switched.set()
        release_candidate_ready.set()
        assert await asyncio.to_thread(state["candidate_disposed"].wait, 1)
        assert await asyncio.to_thread(worker._thread.join, .5) is None
        assert not worker._thread.is_alive()
        assert post_ready_reads == ["post-ready"]
        assert not worker._restart_allowed
        assert (await worker.register({"thread_ref": "actual-runtime", "turn_ref": "later"}))[
            "reason"] == "stopped"
        assert state["constructs"] == 2
        assert state["registrations"] == []
    finally:
        events["release_ready"].set()
        events["release_dispose"].set()
        release_candidate_ready.set()
        if request is not None and not request.done():
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
        await worker.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["peer-mismatch", "invalid-response", "unknown",
                                     "deadline", "generic-unavailable"])
async def test_retired_ready_failure_is_not_replayed_and_only_trust_mismatch_is_terminal(
        monkeypatch, failure):
    def ready(index, _client):
        if index != 1:
            return None
        if failure == "peer-mismatch":
            return {"status": "unavailable", "reason": "peer-mismatch"}
        if failure == "deadline":
            raise bridge.ShadowUnavailable("deadline")
        if failure == "invalid-response":
            raise bridge.ShadowUnavailable("invalid-response")
        if failure == "unknown":
            raise RuntimeError("unclassified readiness error")
        return {"status": "unavailable", "reason": "native-failed"}

    worker, state, events = _cancelled_initial_worker(monkeypatch, ready=ready)
    try:
        await _cancel_initial_request(worker, events)
        events["release_dispose"].set()
        assert await asyncio.to_thread(events["dispose_finished"].wait, 1)
        failed = await worker.register({"thread_ref": "actual-runtime", "turn_ref": "first-fresh"})
        assert failed["reason"] == ("native-failed" if failure in {"deadline", "invalid-response", "unknown"}
                                     else "stopped")
        assert state["ready"] == [0, 1]
        assert state["registrations"] == []
        terminal = failure in {"peer-mismatch", "invalid-response", "unknown"}
        assert worker._restart_allowed is (not terminal)
        deadline = time.monotonic() + 1
        while worker._thread.is_alive() and time.monotonic() < deadline:
            await asyncio.sleep(.005)
        assert not worker._thread.is_alive()
        later = await worker.register({"thread_ref": "actual-runtime", "turn_ref": "later"})
        if terminal:
            assert later["reason"] == "stopped"
            assert state["ready"] == [0, 1] and state["registrations"] == []
        else:
            assert later["status"] == "registered"
            assert state["ready"] == [0, 1, 2]
            assert state["registrations"] == [(2, {"thread_ref": "actual-runtime", "turn_ref": "later"})]
    finally:
        events["release_ready"].set()
        await worker.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("disposal", ["unresolved", "raises"])
async def test_unresolved_initial_disposal_prevents_replacement(monkeypatch, disposal):
    def dispose(index, client):
        if index == 0:
            if disposal == "unresolved":
                client.unresolved = True
            else:
                raise OSError("disposal failed")

    worker, state, events = _cancelled_initial_worker(monkeypatch, dispose=dispose)
    try:
        await _cancel_initial_request(worker, events)
        events["release_dispose"].set()
        assert await asyncio.to_thread(events["dispose_finished"].wait, 1)
        result = await worker.register({"thread_ref": "actual-runtime", "turn_ref": "fresh"})
        assert result["reason"] == "stopped"
        assert len(state["clients"]) == 1
        assert state["ready"] == [0] and state["registrations"] == []
    finally:
        events["release_ready"].set()
        await worker.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "stop"])
async def test_retired_channel_wait_honors_cancellation_and_stop(monkeypatch, action):
    allow_replacement = threading.Event()
    wait_started = threading.Event()

    def construct(index, _client):
        if index and not allow_replacement.is_set():
            raise bridge.ShadowUnavailable("startup-unavailable")

    worker, state, events = _cancelled_initial_worker(monkeypatch, construct=construct)
    original_wait = worker.stop_event.wait

    def observed_wait(timeout=None):
        wait_started.set()
        return original_wait(timeout)

    worker.stop_event.wait = observed_wait
    request = None
    try:
        await _cancel_initial_request(worker, events)
        events["release_dispose"].set()
        assert await asyncio.to_thread(events["dispose_finished"].wait, 1)
        request = asyncio.create_task(worker.register({"thread_ref": "actual-runtime", "turn_ref": action}))
        assert await asyncio.to_thread(wait_started.wait, .5)
        if action == "cancel":
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            allow_replacement.set()
            result = await worker.register({"thread_ref": "actual-runtime", "turn_ref": "later"})
            assert result["status"] == "registered"
            assert state["registrations"] == [(state["clients"][-1].index,
                {"thread_ref": "actual-runtime", "turn_ref": "later"})]
        else:
            await worker.stop()
            result = await request
            assert result["reason"] == "stopped"
            assert worker._restart_allowed
            assert len(state["clients"]) == 1
        if action == "stop":
            assert state["registrations"] == []
    finally:
        events["release_ready"].set()
        if request is not None and not request.done():
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
        await worker.stop()
