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
    proof = "8" * 64

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

    monkeypatch.setattr(bridge, "native_available", lambda: True)
    server = _protocol_server(monkeypatch, Native)

    async def exercise(session):
        assert not (await _actual_status(session, "admitted")).isError
        epochs[0] = 2
        for _ in range(200):
            if len(calls) == 2:
                break
            await asyncio.sleep(.005)
        assert len(clients) == 2
        assert len(calls) == 2
        assert clients[1].disposals == 1
        assert not (await _actual_status(session, "fresh")).isError

    await _serve_protocol(server, exercise)
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
    registrations = []

    class Native:
        def __init__(self, *args, **kwargs):
            self.continuity = None
            self.unresolved = False

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
        release_ready.set()
        result = await worker.register({"thread_ref": "actual-runtime", "turn_ref": "kept"})
        assert result["status"] == "registered"
    release_ready.set()
    assert registrations == [{"thread_ref": "actual-runtime", "turn_ref": "kept"}]
