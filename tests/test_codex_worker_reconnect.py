"""Retained inventory worker reconnects only after an observed registration."""

import asyncio
import os
import queue
import threading
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

from app import codex_bridge_pipe as bridge
from app.mcp import codex_desktop_bridge as lifecycle
from app.mcp import server as mcp_server
from tests.test_codex_mcp_desktop_bridge import _serve_protocol


@pytest.mark.parametrize("fault", ["valid", "foreign-pid", "hostile-creation", "invalid-creation",
                                  "hostile-reason", "hostile-unresolved"])
def test_client_close_file_is_bounded_private_and_quiet(monkeypatch, tmp_path, capsys, fault):
    import logging

    class Hostile:
        def __str__(self):
            raise AssertionError("private-value-stringified")
        __repr__ = __str__

    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    handlers = list(logging.getLogger().handlers)
    creation = "2026-01-02T03:04:05.123000+00:00"
    identity = (os.getpid() + (fault == "foreign-pid"), creation)
    if fault == "hostile-creation":
        identity = (os.getpid(), Hostile())
    if fault == "invalid-creation":
        identity = (os.getpid(), "private-path-sentinel\nprivate-token-sentinel")
    lifecycle._client_close_diagnostic(Hostile() if fault == "hostile-reason" else "cleanup",
        identity, Hostile() if fault == "hostile-unresolved" else False)
    path = tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log"
    text = path.read_text(encoding="utf-8")
    expected = "unknown" if fault in {"foreign-pid", "hostile-creation", "invalid-creation"} else creation
    assert f"reason=cleanup own_pid={os.getpid()} native_creation={expected}" in text
    assert f"unresolved={'unknown' if fault == 'hostile-unresolved' else 'False'}" in text
    assert "private-" not in text and "thread" not in text and "endpoint" not in text
    assert not (tmp_path / "logs" / "pallium.log").exists()
    assert logging.getLogger().handlers == handlers
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("fault", ["mkdir", "handler", "format", "close"])
def test_client_close_sink_failure_does_not_escape_or_use_stderr(monkeypatch, tmp_path, capsys, fault):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    closed = []
    original_close = lifecycle._QuietCloseHandler.close

    def fail(*args, **kwargs):
        raise OSError("private-sink-error-sentinel")

    def close(handler):
        original_close(handler)
        closed.append(True)
        if fault == "close":
            fail()

    with monkeypatch.context() as patch:
        patch.setattr(lifecycle._QuietCloseHandler, "close", close)
        if fault == "mkdir":
            patch.setattr(Path, "mkdir", fail)
        elif fault == "handler":
            patch.setattr(lifecycle, "_QuietCloseHandler", fail)
        elif fault == "format":
            patch.setattr(lifecycle._QuietCloseHandler, "format", fail)
        lifecycle._client_close_diagnostic("cleanup", (os.getpid(), "unknown"), False)
    assert bool(closed) == (fault in {"format", "close"})
    assert capsys.readouterr() == ("", "")


def test_client_close_rotation_serializes_workers_and_closes_handlers(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    closed = []
    original_close = lifecycle._QuietCloseHandler.close
    def close(handler):
        original_close(handler)
        closed.append(True)
    monkeypatch.setattr(lifecycle._QuietCloseHandler, "close", close)
    identity = (os.getpid(), "2026-01-02T03:04:05+00:00")
    for _ in range(100):
        lifecycle._client_close_diagnostic("cleanup", identity, False)
    gate = threading.Barrier(16)
    def write():
        gate.wait()
        lifecycle._client_close_diagnostic("cleanup", identity, False)
    workers = [threading.Thread(target=write) for _ in range(16)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    paths = sorted((tmp_path / "logs").glob("*"))
    assert len(paths) == 2 and all(0 < path.stat().st_size <= 4096 for path in paths)
    assert len(closed) == 116
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines and all("reason=cleanup own_pid=" in line and line.endswith("unresolved=False") for line in lines)


@pytest.mark.parametrize("failure", ["clean", "getter", "dispose"])
def test_client_close_identity_is_captured_before_cleanup(monkeypatch, tmp_path, failure):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    worker = lifecycle.InventoryWorker.__new__(lifecycle.InventoryWorker)
    worker._restart_allowed, worker._retained = True, True
    creation = "2026-01-02T03:04:05+00:00"
    class Native:
        unresolved = False
        source = SimpleNamespace(pid=os.getpid(), creation=creation)
        def dispose(self):
            self.source = None
            self.closed = True
            if failure == "dispose":
                raise OSError("private-disposal-sentinel")
    client = Native()
    if failure == "getter":
        class BadSource:
            @property
            def pid(self):
                raise OSError("private-getter-sentinel")
        client.source = BadSource()
    worker._finish(client, reason="cleanup")
    assert client.closed and client.source is None
    assert worker._restart_allowed == (failure != "dispose")
    text = (tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log").read_text(encoding="utf-8")
    assert f"native_creation={'unknown' if failure == 'getter' else creation}" in text
    assert f"unresolved={failure == 'dispose'}" in text and "private-" not in text


def test_reconnect_diagnostic_sanitizes_and_rotates_without_escaping(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))

    class Hostile:
        def __str__(self):
            raise AssertionError("private-diagnostic-value-stringified")
        __repr__ = __str__

    for _ in range(120):
        diagnostic = lifecycle._new_reconnect_diagnostic("idle")
        lifecycle._mark_reconnect(diagnostic, phase=Hostile(), phase_state=Hostile(),
            attempt=Hostile(), registration=Hostile(), outcome=Hostile(),
            unresolved=Hostile(), owner_exited=Hostile())
        lifecycle._client_reconnect_diagnostic(diagnostic, Hostile())

    paths = sorted((tmp_path / "logs").glob(f"codex-retained-client-{os.getpid()}.log*"))
    assert len(paths) == 2 and all(0 < path.stat().st_size <= 4096 for path in paths)
    records = [line for path in paths for line in path.read_text(encoding="utf-8").splitlines()]
    assert records and all("reconnect_terminal" in line and "phase=unknown" in line
                           and "phase_state=unknown" in line and "attempt=unknown" in line
                           and "registration=unknown" in line and "outcome=unknown" in line
                           and "restart_allowed=unknown" in line and "unresolved=unknown" in line
                           and "owner_exited=unknown" in line for line in records)
    assert "private-diagnostic-value" not in "\n".join(records)
    assert capsys.readouterr() == ("", "")


def test_reconnect_episode_allocator_does_not_wait_for_sink_lock(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    ready = threading.Event()
    allocated = []
    started = False
    lifecycle._close_log_lock.acquire()
    try:
        thread = threading.Thread(target=lambda: (allocated.append(
            lifecycle._new_reconnect_diagnostic("idle")), ready.set()))
        thread.start()
        started = True
        assert ready.wait(1), "episode allocation waited on the file sink lock"
    finally:
        lifecycle._close_log_lock.release()
        if started:
            thread.join(1)
    assert not thread.is_alive() and allocated[0]["episode"] is not None


def test_reconnect_diagnostic_sink_failure_is_contained(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))

    def fail(*_args, **_kwargs):
        raise OSError("private-diagnostic-sink-sentinel")

    diagnostic = lifecycle._new_reconnect_diagnostic("idle")
    lifecycle._mark_reconnect(diagnostic, outcome="constructor-error")
    monkeypatch.setattr(lifecycle, "_QuietCloseHandler", fail)
    lifecycle._client_reconnect_diagnostic(diagnostic, True)
    assert capsys.readouterr() == ("", "")
    assert "private-diagnostic-sink-sentinel" not in str(diagnostic)


def test_reconnect_allocator_failure_preserves_existing_recovery_result(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "original-capability")
    monkeypatch.setattr(lifecycle, "_new_reconnect_diagnostic", lambda _context: None)
    worker = object.__new__(lifecycle.InventoryWorker)
    worker.stop_event = threading.Event()
    worker._retained = True
    worker._restart_allowed = True
    calls = []

    class Native:
        continuity, unresolved = "a" * 64, False
        io = SimpleNamespace(unresolved=False)
        def service_current(self):
            calls.append("service-current")
            return True
        def ready(self):
            calls.append("ready")
            raise RuntimeError("existing-ready-failure")
        def register(self, _metadata):
            calls.append("register")
        def dispose(self):
            calls.append("dispose")

    result = worker._recover_if_gone(Native(), Native, "original-capability",
        {"thread_ref": "runtime", "turn_ref": "turn"}, "a" * 64)
    assert result == (None, False)
    assert not worker._restart_allowed
    assert calls == ["service-current", "ready"]
    assert not (tmp_path / "logs").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("journey", ["idle-transport", "unused-ready", "caller-thread", "lifespan-stop"])
async def test_actual_mcp_close_branch_has_durable_marker(monkeypatch, tmp_path, journey):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    if journey == "idle-transport":
        await test_admitted_idle_retirement_freshly_enrolls_three_times_without_foreground(monkeypatch, tmp_path)
        expected = "idle-ready-transport"
    elif journey == "unused-ready":
        await test_mcp_cancellation_releases_unused_channel_for_fresh_request(monkeypatch, "terminal-bootstrap")
        expected = "unused-ready-retired"
    elif journey == "caller-thread":
        await test_busy_response_does_not_preserve_changed_or_unresolved_admission(monkeypatch, "thread")
        expected = "caller-thread-changed"
    else:
        await test_concurrent_actual_requests_do_not_create_a_second_worker(monkeypatch)
        expected = "lifespan-stop"
    text = (tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log").read_text(encoding="utf-8")
    assert f"reason={expected} " in text
    assert "actual-runtime" not in text and "original-capability" not in text


@pytest.mark.parametrize("category", ["deadline", "transport-failed"])
def test_registered_idle_retirement_records_exact_ready_failure(monkeypatch, tmp_path, category):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "original-capability")
    worker = lifecycle.InventoryWorker.__new__(lifecycle.InventoryWorker)
    worker._restart_allowed, worker._retained = True, True
    worker.stop_event = threading.Event()
    worker._fresh_request_retirement = None
    acquisitions = []
    worker._auto_reconnect = lambda *args, **kwargs: acquisitions.append(kwargs)
    proof = "a" * 64
    class Native:
        continuity, unresolved, manifest = proof, False, {"epoch": "same"}
        source = SimpleNamespace(pid=os.getpid(), creation="2026-01-02T03:04:05+00:00")
        io = SimpleNamespace(unresolved=False)
        def ready(self):
            raise bridge.ShadowUnavailable(category)
        def service_current(self):
            return True
        def bootstrap_unchanged(self):
            return True
        def retired_service_exited(self):
            return False
        def retire(self):
            self.source = None
            self.closed = True
        def dispose(self):
            self.disposed = True
    client = Native()
    assert worker._recover_if_gone(client, Native, "original-capability",
        {"thread_ref": "actual-runtime", "turn_ref": "admitted"}, proof,
        allow_ready_retirement=True) == (None, True)
    assert client.closed and worker._restart_allowed and not worker.stop_event.is_set()
    assert worker._fresh_request_retirement is None and client.disposed
    assert acquisitions == [{"retired_context": (client, {"epoch": "same"})}]
    text = (tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log").read_text(encoding="utf-8")
    expected = "idle-ready-deadline" if category == "deadline" else "idle-ready-transport"
    assert f"reason={expected} " in text


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["registered", "unavailable"])
async def test_first_cancelled_mcp_admission_records_validated_reply(monkeypatch, tmp_path, reply):
    from mcp.shared.exceptions import McpError
    from mcp.types import CancelledNotification, CancelledNotificationParams, ClientNotification

    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    entered, release = threading.Event(), threading.Event()
    workers, clients, operations = [], [], []
    original_worker = lifecycle.InventoryWorker
    class Worker(original_worker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            workers.append(self)
    class Native:
        def __init__(self, *args, **kwargs):
            self.source = SimpleNamespace(pid=os.getpid(), creation="2026-01-02T03:04:05+00:00")
            self.continuity, self.unresolved, self.closed = None, False, False
            clients.append(self)
        def ready(self):
            return {"status": "ready"}
        def register(self, metadata):
            entered.set()
            assert release.wait(5)
            self.continuity = "a" * 64
            return {"status": reply, "reason": "ok" if reply == "registered" else "native-failed"}
        def dispose(self):
            self.source = None
            self.closed = True
    monkeypatch.setattr(lifecycle, "InventoryWorker", Worker)
    server = _protocol_server(monkeypatch, Native, operations)
    async def exercise(session):
        request_ids = []
        original_send = session.send_request
        async def observe(*args, **kwargs):
            request_ids.append(session._request_id)
            return await original_send(*args, **kwargs)
        session.send_request = observe
        task = asyncio.create_task(_actual_status(session, "cancelled-first"))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            await session.send_notification(ClientNotification(CancelledNotification(
                params=CancelledNotificationParams(requestId=request_ids[-1], reason="test cancellation"))))
            with pytest.raises(McpError):
                await asyncio.wait_for(task, 1)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    try:
        await _serve_protocol(server, exercise)
    finally:
        release.set()
        for worker in workers:
            await worker.stop()
            worker._thread.join()
    assert len(clients) == 1 and clients[0].closed and operations == []
    text = (tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log").read_text(encoding="utf-8")
    expected = "first-registered-result-cancelled" if reply == "registered" else "first-admission-cancelled"
    assert f"reason={expected} " in text
    assert "native_creation=2026-01-02T03:04:05+00:00" in text


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
async def test_admitted_idle_retirement_freshly_enrolls_three_times_without_foreground(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    clients, workers, registrations, operations = [], [], [], []
    fail_ready = [threading.Event() for _ in range(3)]
    enrolled = [threading.Event() for _ in range(4)]
    proof = "a" * 64

    class Native:
        def __init__(self, _path, stop, *, retained, previous_manifest=None):
            assert retained and previous_manifest is None
            self.index = len(clients)
            self.manifest = {"epoch": "same"}
            self.continuity, self.unresolved = None, False
            self.io = SimpleNamespace(unresolved=False)
            self.retirements = self.disposals = 0
            clients.append(self)

        def service_current(self):
            return True

        def bootstrap_unchanged(self):
            return True

        def retired_service_exited(self):
            return False

        def ready(self):
            if (self.continuity and self.index < 3
                    and fail_ready[self.index].is_set()):
                raise bridge.ShadowUnavailable("deadline" if self.index % 2 == 0 else "transport-failed")
            return {"status": "ready", "connected": self.continuity is not None,
                    "source_exited": False}

        def register(self, metadata):
            assert self.continuity == (None if self.index == 0 else proof)
            registrations.append((self.index, dict(metadata)))
            self.continuity = proof
            enrolled[self.index].set()
            return {"status": "registered", "reason": "ok"}

        def retire(self):
            self.retirements += 1
            self.io = None

        def dispose(self):
            self.disposals += 1
            self.io = None

    class Worker(lifecycle.InventoryWorker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            workers.append(self)

    monkeypatch.setattr(lifecycle, "InventoryWorker", Worker)
    server = _protocol_server(monkeypatch, Native, operations)

    async def exercise(session):
        assert not (await _actual_status(session, "admitted")).isError
        for cycle in range(3):
            fail_ready[cycle].set()
            assert await asyncio.to_thread(enrolled[cycle + 1].wait, 5), (
                f"idle retirement {cycle + 1} required another foreground caller")
        assert len(operations) == 1
        assert registrations == [(index, {"thread_ref": "actual-runtime", "turn_ref": "admitted"})
                                 for index in range(4)]

    try:
        await _serve_protocol(server, exercise)
    finally:
        for worker in workers:
            await worker.stop()
            await asyncio.to_thread(worker._thread.join, 5)
            assert not worker._thread.is_alive()
    assert len(clients) == 4
    assert [client.retirements for client in clients] == [1, 1, 1, 0]
    assert all(client.disposals == 1 and client.io is None for client in clients)


@pytest.mark.parametrize("fault", ["clean", "wait-failed", "unresolved", "raises", "returns-unresolved", "incomplete"])
def test_retired_native_owner_proof_has_one_owner_and_fails_closed(monkeypatch, fault):
    retained, closed = [], []
    monkeypatch.setattr(bridge, "_retained", retained)

    class Handle:
        def __init__(self, name):
            self.name, self.handle = name, object()
        def close(self):
            if self.handle is not None:
                closed.append(self.name)
                self.handle = None

    state = [258]
    owner, source = Handle("owner"), Handle("source")
    original_handle = owner.handle

    def wait(handle, timeout):
        assert handle is original_handle and timeout == 0
        return state[0]

    client = bridge.NativeInventoryClient.__new__(bridge.NativeInventoryClient)
    client.w = SimpleNamespace(event=SimpleNamespace(WaitForSingleObject=wait, WAIT_OBJECT_0=0, WAIT_TIMEOUT=258))
    client.peer, client.source, client.unresolved = owner, source, False
    client.io = SimpleNamespace(unresolved=fault == "unresolved", close=lambda: closed.append("io"))
    dispose = lambda: bridge.NativeInventoryClient.dispose(client)
    if fault == "raises":
        def dispose():
            raise OSError("controlled disposal failure")
    elif fault == "returns-unresolved":
        def dispose():
            bridge.NativeInventoryClient.dispose(client)
            client.unresolved = True
    elif fault == "incomplete":
        dispose = lambda: None
    client.dispose = dispose
    try:
        if fault in {"raises", "returns-unresolved", "incomplete"}:
            with pytest.raises((OSError, bridge.ShadowUnavailable)):
                client.retire()
            assert owner.handle is None
            with pytest.raises(bridge.ShadowUnavailable):
                client.retired_service_exited()
        elif fault == "unresolved":
            client.retire()
            assert retained == [client] and closed == []
            with pytest.raises(bridge.ShadowUnavailable):
                client.retired_service_exited()
        else:
            client.retire()
            assert closed == ["io", "source"] and owner.handle is original_handle
            assert client.retired_service_exited() is False
            state[0] = 0xFFFFFFFF if fault == "wait-failed" else 0
            if fault == "wait-failed":
                with pytest.raises(bridge.ShadowUnavailable, match="peer-unavailable"):
                    client.retired_service_exited()
            else:
                assert client.retired_service_exited() is True
    finally:
        if client.io is not None:
            client.io.unresolved = False  # Only fake handles are settled for test cleanup.
        bridge.NativeInventoryClient.dispose(client)
    assert closed.count("owner") == closed.count("source") == closed.count("io") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["exit-later", "exit-during-retire", "live-bootstrap", "pid-reuse-live",
                                "wait-failed", "dispose-unresolved", "other-caller", "capability",
                                "constructor-failure", "ready-failure", "cancel", "shutdown"])
async def test_fresh_caller_after_retirement_requires_trusted_old_owner_exit(monkeypatch, case):
    from mcp.shared.exceptions import McpError
    from mcp.types import CancelledNotification, CancelledNotificationParams, ClientNotification

    clients, workers, registrations, operations = [], [], [], []
    retired, candidate_ready, release_ready = threading.Event(), threading.Event(), threading.Event()
    manifest = [{"pid": 1, "creation": "old", "epoch": "old"}]
    retained = []
    monkeypatch.setattr(bridge, "_retained", retained)
    proof = "a" * 64
    native_client = bridge.NativeInventoryClient

    class Peer:
        def __init__(self):
            self.handle, self.closed, self.exited, self.failed = self, 0, False, False
        def close(self):
            if self.handle is not None:
                self.closed += 1
                self.handle = None

    def wait(handle, timeout):
        assert timeout == 0
        return 0xFFFFFFFF if handle.failed else 0 if handle.exited else 258

    class Native:
        retire = native_client.retire
        retired_service_exited = native_client.retired_service_exited
        def __init__(self, *args, retained, previous_manifest=None):
            self.index = len(clients)
            if self.index and case == "constructor-failure":
                raise OSError("controlled candidate constructor failure")
            self.manifest = dict(manifest[0])
            if previous_manifest is not None:
                assert previous_manifest == clients[0].manifest and self.manifest != previous_manifest
            self.w = SimpleNamespace(event=SimpleNamespace(WaitForSingleObject=wait, WAIT_OBJECT_0=0, WAIT_TIMEOUT=258))
            self.peer, self.source = Peer(), Peer()
            self.owner = self.peer
            self.io = SimpleNamespace(unresolved=False, close=lambda: None)
            self.unresolved, self.continuity, self.failed = False, None, False
            clients.append(self)
        def bootstrap_unchanged(self):
            return self.manifest == manifest[0]
        def service_current(self):
            if self.owner.exited:
                return False
            if not self.bootstrap_unchanged():
                raise bridge.ShadowUnavailable("peer-mismatch")
            return True
        def ready(self):
            if self.index == 0 and self.failed:
                raise bridge.ShadowUnavailable("transport-failed")
            if self.index and case == "ready-failure":
                raise bridge.ShadowUnavailable("deadline")
            if self.index and case == "cancel":
                candidate_ready.set()
                assert release_ready.wait(2)
            return {"status": "ready", "connected": self.continuity is not None, "source_exited": False}
        def register(self, metadata):
            registrations.append((self.index, dict(metadata), self.continuity))
            if self.index == 0 and self.continuity:
                self.failed = True
                raise bridge.ShadowUnavailable("transport-failed")
            self.continuity = proof
            return {"status": "registered", "reason": "ok"}
        def dispose(self):
            native_client.dispose(self)
            if self.index == 0 and self.continuity and self.peer is None:
                if case == "exit-during-retire":
                    self.owner.exited = True
                    manifest[0] = {"pid": 2, "creation": "new", "epoch": "new"}
                if case == "dispose-unresolved":
                    self.unresolved = True

    class Worker(lifecycle.InventoryWorker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            workers.append(self)
        def _recover_if_gone(self, *args, **kwargs):
            result = super()._recover_if_gone(*args, **kwargs)
            retired.set()
            return result

    monkeypatch.setattr(lifecycle, "InventoryWorker", Worker)
    monkeypatch.setattr(bridge, "native_available", lambda: True)
    server = _protocol_server(monkeypatch, Native, operations)
    monkeypatch.setattr(lifecycle, "RECONNECT_IDLE_POLL_SECONDS", 5)

    async def exercise(session):
        assert not (await _actual_status(session, "admitted")).isError
        assert not (await _actual_status(session, "failed-foreground")).isError
        assert await asyncio.to_thread(retired.wait, 1)
        old = clients[0]
        if case == "shutdown":
            await workers[0].stop()
            return
        if case != "exit-during-retire":
            old.owner.exited = case not in {"live-bootstrap", "pid-reuse-live"}
            manifest[0] = {"pid": 1 if case == "pid-reuse-live" else 2, "creation": "new", "epoch": "new"}
        if case == "wait-failed":
            old.owner.failed = True
        if case == "capability":
            monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "changed-capability")
        if case == "other-caller":
            result = await session.call_tool("pallium_relay_status", {"message_id": "message"},
                meta={"threadId": "other-runtime", "turnId": "fresh"})
        elif case == "cancel":
            request_id = session._request_id
            request = asyncio.create_task(_actual_status(session, "fresh"))
            try:
                assert await asyncio.to_thread(candidate_ready.wait, 1)
                await session.send_notification(ClientNotification(CancelledNotification(
                    params=CancelledNotificationParams(requestId=request_id, reason="controlled cancellation"))))
                with pytest.raises(McpError):
                    await asyncio.wait_for(request, 1)
            finally:
                release_ready.set()
                if not request.done():
                    request.cancel()
                await asyncio.gather(request, return_exceptions=True)
            return
        else:
            result = await _actual_status(session, "fresh")
        assert not result.isError
        if case in {"exit-later", "exit-during-retire"}:
            assert registrations == [(0, {"thread_ref": "actual-runtime", "turn_ref": "admitted"}, None),
                                     (0, {"thread_ref": "actual-runtime", "turn_ref": "failed-foreground"}, proof),
                                     (1, {"thread_ref": "actual-runtime", "turn_ref": "fresh"}, proof)]
            assert workers[0]._restart_allowed and workers[0]._thread.is_alive()
        else:
            assert len(registrations) == 2

    try:
        await _serve_protocol(server, exercise)
    finally:
        release_ready.set()
        for worker in workers:
            await worker.stop()
            await asyncio.to_thread(worker._thread.join)
    assert registrations[0][1]["turn_ref"] == "admitted"
    assert all(client.owner.closed == 1 for client in clients)
    assert all(client.io is None and client.source is None for client in clients)
    assert len(operations) == (2 if case in {"cancel", "shutdown"} else 3)


@pytest.mark.parametrize("case", ["healthy", "ready-busy", "register-success", "register-busy", "register-malformed", "unresolved",
    "invalid-continuity", "pipe-changed", "source-exited", "ready-malformed",
    "ready-refused", "register-refused", "register-uncertain", "continuity-changed",
    "pipe-changed-after", "stopped-after", "ready-pipe-changed", "ready-continuity-changed",
    "ready-unresolved", "ready-stopped"])
def test_same_epoch_recovery_preserves_admission_and_identity_fences(monkeypatch, tmp_path, case):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    worker = object.__new__(lifecycle.InventoryWorker)
    worker.stop_event = threading.Event()
    worker._restart_allowed = True
    worker._retained = True
    worker._auto_reconnect = lambda *a: pytest.fail("same epoch replaced the source channel")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "original-capability")
    calls = []

    class Native:
        continuity = "a" * 64
        def __init__(self):
            self._unresolved = case == "unresolved"
            self.check_order = []

        @property
        def unresolved(self):
            if case == "register-success":
                self.check_order.append("unresolved")
            return self._unresolved

        @unresolved.setter
        def unresolved(self, value):
            self._unresolved = value

        def service_current(self):
            if case == "register-success":
                self.check_order.append("service-current")
            return True

        def ready(self):
            calls.append("ready")
            if case == "register-success":
                self.check_order.append("ready")
            if case == "ready-pipe-changed":
                monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "changed-capability")
            if case == "ready-continuity-changed":
                self.continuity = "b" * 64
            if case == "ready-unresolved":
                self.unresolved = True
            if case == "ready-stopped":
                worker.stop_event.set()
            if case == "ready-busy":
                return {"status": "unavailable", "reason": "busy"}
            if case == "ready-refused":
                return {"status": "unavailable", "reason": "peer-mismatch"}
            if case == "ready-malformed":
                return {"status": "ready"}
            return {"status": "ready", "connected": case == "healthy",
                    "source_exited": case == "source-exited"}

        def register(self, metadata):
            calls.append("register")
            if case == "register-success":
                self.check_order.append("register")
            assert metadata == {"thread_ref": "actual-runtime", "turn_ref": "first"}
            if case == "register-busy":
                return {"status": "unavailable", "reason": "busy"}
            if case == "register-refused":
                return {"status": "unavailable", "reason": "peer-mismatch"}
            if case == "register-malformed":
                return None
            if case == "register-uncertain":
                self.unresolved = True
                raise bridge.ShadowUnavailable("transport-failed")
            if case == "continuity-changed":
                self.continuity = "b" * 64
            if case == "pipe-changed-after":
                monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "changed-capability")
            if case == "stopped-after":
                worker.stop_event.set()
            return {"status": "registered", "reason": "ok"}

    client = Native()
    proof = "a" * 64
    if case == "invalid-continuity":
        proof = "invalid"
    if case == "pipe-changed":
        monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "changed-capability")
    result, disposed = worker._recover_if_gone(client, Native, "original-capability",
        {"thread_ref": "actual-runtime", "turn_ref": "first"}, proof)
    assert not disposed
    accepted = case in {"healthy", "ready-busy", "register-success", "register-busy"}
    assert (result is client) == accepted
    expected = [] if case in {"unresolved", "invalid-continuity", "pipe-changed"} else ["ready"]
    if case in {"register-success", "register-busy", "register-refused", "register-malformed", "register-uncertain", "continuity-changed",
                "pipe-changed-after", "stopped-after"}:
        expected.append("register")
    assert calls == expected
    if case == "register-success":
        assert client.check_order == [
            "unresolved", "service-current", "ready", "unresolved", "register", "unresolved"]
    log_path = tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log"
    if case == "healthy":
        assert not log_path.exists(), "healthy READY polling must stay silent"
    else:
        terminal = [line for line in log_path.read_text(encoding="utf-8").splitlines()
                    if "reconnect_terminal" in line]
        assert len(terminal) == 1
        if case in {"register-refused", "register-malformed"}:
            assert "registration=completed" in terminal[0] and "outcome=register-unconfirmed" in terminal[0]
        elif case == "register-uncertain":
            assert "registration=attempted" in terminal[0] and "outcome=register-uncertain" in terminal[0]
        elif case == "register-success":
            assert "phase=postregister" in terminal[0] and "phase_state=completed" in terminal[0]
            assert "registration=completed" in terminal[0] and "outcome=ready-available" in terminal[0]
            assert "unresolved=False" in terminal[0] and "restart_allowed=True" in terminal[0]
        elif case == "ready-refused":
            assert "phase=ready" in terminal[0] and "registration=not-attempted" in terminal[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["transport-failed", "deadline", "primary-peer-mismatch",
    "primary-invalid-response", "primary-generic", "primary-refusal", "unresolved-io",
    "retire-unresolved", "changed-bootstrap", "changed-continuity", "changed-capability",
    "other-caller", "cancel-fresh", "shutdown", "transport-failed-healthy", "deadline-healthy",
    "primary-peer-mismatch-healthy", "primary-invalid-response-healthy", "primary-generic-healthy",
    "primary-refusal-healthy", "unresolved-io-healthy", "changed-continuity-healthy",
    "changed-capability-healthy"])
async def test_fresh_caller_recovers_resolved_foreground_channel_failure(monkeypatch, tmp_path, case):
    from mcp.shared.exceptions import McpError
    from mcp.types import CancelledNotification, CancelledNotificationParams, ClientNotification

    clients, workers, registrations, outcomes, operations = [], [], [], [], []
    observed, candidate_ready, release_ready = threading.Event(), threading.Event(), threading.Event()
    proof = "a" * 64
    failure_case = case.removesuffix("-healthy")
    healthy_followup = case.endswith("-healthy")
    retained = []
    monkeypatch.setattr(bridge, "_retained", retained)
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    native_client = bridge.NativeInventoryClient

    class Peer:
        def __init__(self):
            self.handle, self.closed = self, 0
            self.pid, self.creation = os.getpid(), "2026-01-02T03:04:05+00:00"
        def close(self):
            if self.handle is not None:
                self.closed += 1
                self.handle = None

    class IO:
        unresolved, closed = False, 0
        def close(self):
            self.closed += 1

    class Native:
        retire = native_client.retire
        retired_service_exited = native_client.retired_service_exited
        def __init__(self, *args, retained, previous_manifest=None):
            assert previous_manifest is None  # The authenticated service never exits.
            self.index = len(clients)
            self.manifest = {"epoch": "same", "pid": 1, "creation": "same"}
            self.peer, self.source, self.io = Peer(), Peer(), IO()
            self.owner, self.source_peer, self.source_io = self.peer, self.source, self.io
            self.w = SimpleNamespace(event=SimpleNamespace(
                WaitForSingleObject=lambda handle, timeout: 258, WAIT_OBJECT_0=0, WAIT_TIMEOUT=258))
            self.unresolved, self.continuity, self.failed = False, None, False
            clients.append(self)
        def bootstrap_unchanged(self):
            return not (self.failed and case == "changed-bootstrap")
        def service_current(self):
            if not self.bootstrap_unchanged():
                raise bridge.ShadowUnavailable("peer-mismatch")
            return True
        def ready(self):
            if self.index == 0 and self.failed:
                if failure_case == "changed-capability":
                    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "changed-capability")
                if healthy_followup:
                    return {"status": "ready", "connected": True, "source_exited": False}
                raise bridge.ShadowUnavailable("deadline" if case == "deadline" else "transport-failed")
            if self.index and case == "cancel-fresh":
                candidate_ready.set()
                assert release_ready.wait(5)
            return {"status": "ready", "connected": self.continuity is not None, "source_exited": False}
        def register(self, metadata):
            registrations.append((self.index, dict(metadata), self.continuity))
            if self.index == 0 and self.continuity and (not healthy_followup or len(registrations) == 2):
                self.failed = True
                if failure_case == "unresolved-io":
                    self.io.unresolved = True
                if failure_case == "changed-continuity":
                    self.continuity = "b" * 64
                if failure_case == "primary-refusal":
                    return {"status": "unavailable", "reason": "peer-mismatch"}
                if failure_case == "primary-generic":
                    raise RuntimeError("controlled foreground failure")
                category = (failure_case.removeprefix("primary-") if failure_case.startswith("primary-")
                            else "deadline" if failure_case == "deadline" else "transport-failed")
                raise bridge.ShadowUnavailable(category)
            assert metadata["thread_ref"] == "actual-runtime"
            assert self.continuity == (None if self.index == 0 and len(registrations) == 1 else proof)
            self.continuity = proof
            return {"status": "registered", "reason": "ok"}
        def dispose(self):
            native_client.dispose(self)
            if self.failed and case == "retire-unresolved":
                self.unresolved = True

    class Worker(lifecycle.InventoryWorker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            workers.append(self)
        async def register(self, metadata):
            result = await super().register(metadata)
            outcomes.append((dict(metadata), result))
            return result
        def _recover_if_gone(self, *args, **kwargs):
            try:
                return super()._recover_if_gone(*args, **kwargs)
            finally:
                observed.set()

    monkeypatch.setattr(lifecycle, "InventoryWorker", Worker)
    monkeypatch.setattr(bridge, "native_available", lambda: True)
    server = _protocol_server(monkeypatch, Native, operations)
    monkeypatch.setattr(lifecycle, "RECONNECT_IDLE_POLL_SECONDS", 5)
    request = None

    async def exercise(session):
        nonlocal request
        assert not (await _actual_status(session, "admitted")).isError
        assert not (await _actual_status(session, "failed-foreground")).isError
        assert await asyncio.to_thread(observed.wait, 2)
        assert outcomes[1][1]["status"] == "unavailable"
        assert outcomes[1][1]["reason"] == ("peer-mismatch" if failure_case == "primary-refusal" else "native-failed")
        assert len(clients) == 1 and len(registrations) == 2
        assert len(operations) == 2  # Unavailable enrollment does not replay or suppress Relay.
        if healthy_followup:
            safe = failure_case in {"transport-failed", "deadline"}
            if not safe:
                await asyncio.to_thread(workers[0]._thread.join, 1)
            assert workers[0]._thread.is_alive() == safe
            if not safe:
                assert len(clients) == 1 and len(registrations) == 2
                return
        if case == "shutdown":
            await workers[0].stop()
            return
        if case == "cancel-fresh":
            request_id = session._request_id
            request = asyncio.create_task(_actual_status(session, "fresh"))
            try:
                assert await asyncio.to_thread(candidate_ready.wait, 2)
                await session.send_notification(ClientNotification(CancelledNotification(
                    params=CancelledNotificationParams(requestId=request_id, reason="controlled cancellation"))))
                with pytest.raises(McpError):
                    await asyncio.wait_for(request, 2)
            finally:
                release_ready.set()
            return
        if case == "other-caller":
            result = await session.call_tool("pallium_relay_status", {"message_id": "message"},
                meta={"threadId": "other-runtime", "turnId": "fresh"})
        else:
            result = await _actual_status(session, "fresh")
        assert not result.isError
        if healthy_followup and failure_case in {"transport-failed", "deadline"}:
            assert registrations == [
                (0, {"thread_ref": "actual-runtime", "turn_ref": "admitted"}, None),
                (0, {"thread_ref": "actual-runtime", "turn_ref": "failed-foreground"}, proof),
                (0, {"thread_ref": "actual-runtime", "turn_ref": "fresh"}, proof),
            ]
            assert len(clients) == 1 and outcomes[-1][1]["status"] == "registered"
            assert workers[0]._restart_allowed and workers[0]._thread.is_alive()
        elif case in {"transport-failed", "deadline"}:
            assert registrations == [
                (0, {"thread_ref": "actual-runtime", "turn_ref": "admitted"}, None),
                (0, {"thread_ref": "actual-runtime", "turn_ref": "failed-foreground"}, proof),
                (1, {"thread_ref": "actual-runtime", "turn_ref": "fresh"}, proof),
            ], "Fresh same caller must register after resolved foreground channel failure"
            assert outcomes[-1][1]["status"] == "registered"
            assert workers[0]._restart_allowed and workers[0]._thread.is_alive()
            text = (tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log").read_text(encoding="utf-8")
            expected = "reregister-ready-deadline" if case == "deadline" else "reregister-ready-transport"
            assert f"reason={expected} " in text
        else:
            assert len(clients) == 1 and len(registrations) == 2
            assert not workers[0]._restart_allowed
        assert len(operations) == 3

    try:
        await _serve_protocol(server, exercise)
    finally:
        release_ready.set()
        if request is not None and not request.done():
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
        try:
            for worker in workers:
                await worker.stop()
            for worker in workers:
                await asyncio.to_thread(worker._thread.join)
        finally:
            # Only fake I/O/handles are settled after checking refusal and worker cleanup.
            for client in clients:
                if client.io is not None:
                    client.io.unresolved = False
                native_client.dispose(client)
    assert all(not worker._thread.is_alive() for worker in workers)
    assert all(client.owner.closed == client.source_peer.closed == client.source_io.closed == 1
               for client in clients)
    assert all(client.peer is None and client.source is None and client.io is None for client in clients)


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
            return {"status": "ready", "reason": "ready", "connected": True,
                    "source_exited": False}

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
            return {"status": "ready", "connected": self.continuity is not None,
                    "source_exited": False}

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
@pytest.mark.parametrize("termination", ["deadline", "shutdown"])
async def test_retry_deadline_and_shutdown_bound_startup_retries(monkeypatch, termination):
    epochs, attempts = [1], []
    waiting = threading.Event()
    admitted_ready, ready_responses = threading.Event(), []
    disposed, disposal_epochs = threading.Event(), []
    workers, entered = [], []

    class ObservedWorker(lifecycle.InventoryWorker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            workers.append(self)

    class Native:
        def __init__(self, *args, retained, previous_manifest=None):
            self.epoch = epochs[0]
            self.manifest = {"epoch": self.epoch}
            self.continuity = None
            self.unresolved = False
            if self.epoch > 1:
                entered.append(time.monotonic())
                attempts.append(previous_manifest)
                waiting.set()
                time.sleep(.01)
                raise bridge.ShadowUnavailable("startup-unavailable")

        def ready(self):
            result = {"status": "ready", "connected": self.continuity is not None,
                      "source_exited": False}
            if self.continuity is not None and self.epoch == 1:
                ready_responses.append(dict(result))
                admitted_ready.set()
            return result

        def register(self, _metadata):
            self.continuity = "c" * 64
            return {"status": "registered", "reason": "ok"}

        def service_current(self):
            return self.epoch == epochs[0]

        def dispose(self):
            disposal_epochs.append(epochs[0])
            disposed.set()

    monkeypatch.setattr(lifecycle, "RECONNECT_MAX_ATTEMPTS", 12)
    monkeypatch.setattr(lifecycle, "RECONNECT_WINDOW_SECONDS", .025)
    monkeypatch.setattr(lifecycle, "RECONNECT_INITIAL_BACKOFF_SECONDS", .01)
    monkeypatch.setattr(lifecycle, "RECONNECT_MAX_BACKOFF_SECONDS", .01)
    monkeypatch.setattr(lifecycle, "InventoryWorker", ObservedWorker)
    server = _protocol_server(monkeypatch, Native)

    async def exercise(session):
        assert not (await _actual_status(session, "first")).isError
        assert await asyncio.to_thread(admitted_ready.wait, .5)
        if ready_responses[0].get("connected") is not True:
            assert await asyncio.to_thread(disposed.wait, .5)
            assert disposal_epochs == [1] and workers[0].stop_event.is_set()
        assert ready_responses[0].get("connected") is True
        assert ready_responses[0].get("source_exited") is False
        epochs[0] = 2
        assert await asyncio.to_thread(waiting.wait, .5)
        if termination == "deadline":
            await asyncio.to_thread(workers[0]._thread.join, .5)
            assert not workers[0]._thread.is_alive() and workers[0].stop_event.is_set()

    await _serve_protocol(server, exercise)
    assert 1 <= len(attempts) <= 12
    assert attempts == [{"epoch": 1}] * len(attempts)
    assert all(value - entered[0] < .025 for value in entered)
    assert disposal_epochs == [2]


@pytest.mark.asyncio
async def test_unresolved_old_channel_prevents_replacement(monkeypatch):
    epochs, clients = [1], []
    disposal_epochs = []

    class Native:
        def __init__(self, *args, **kwargs):
            self.epoch = epochs[0]
            self.continuity = None
            self.unresolved = False
            self.disposals = 0
            clients.append(self)

        def ready(self):
            return {"status": "ready", "connected": self.continuity is not None,
                    "source_exited": False}

        def register(self, _metadata):
            self.continuity = "d" * 64
            return {"status": "registered", "reason": "ok"}

        def service_current(self):
            return self.epoch == epochs[0]

        def dispose(self):
            disposal_epochs.append(epochs[0])
            assert epochs[0] == 2, "baseline readiness disposed before service replacement"
            self.disposals += 1
            self.unresolved = True

    server = _protocol_server(monkeypatch, Native)

    async def exercise(session):
        assert not (await _actual_status(session, "first")).isError
        epochs[0] = 2
        await asyncio.sleep(.05)

    await _serve_protocol(server, exercise)
    assert len(clients) == 1 and clients[0].disposals == 1
    assert disposal_epochs == [2]


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
            return {"status": "ready", "connected": self.continuity is not None,
                    "source_exited": False}

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
            return {"status": "ready", "connected": True, "source_exited": False}

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
@pytest.mark.parametrize("busy_stage", ["ready", "register"])
@pytest.mark.parametrize("busy_count", [1, 2])
async def test_busy_auto_reconnect_recovers_without_a_fresh_call(monkeypatch, tmp_path, busy_stage, busy_count):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    epochs, clients, calls = [1], [], []
    workers = []
    dispose_started, release_dispose = threading.Event(), threading.Event()
    recovered = threading.Event()
    reconnected_written, idle_get_entered = threading.Event(), threading.Event()
    terminal_lock, terminal_rows = threading.Lock(), []
    proof = "8" * 64

    original_terminal_writer = lifecycle._client_reconnect_diagnostic

    def observe_terminal(diagnostic, restart_allowed):
        original_terminal_writer(diagnostic, restart_allowed)
        if type(diagnostic) is dict:
            row = dict(diagnostic)
            row["restart_allowed"] = restart_allowed
            row["owned_worker"] = bool(workers and threading.current_thread() is workers[0]._thread)
            with terminal_lock:
                terminal_rows.append(row)
            if row["outcome"] == "reconnected":
                reconnected_written.set()

    monkeypatch.setattr(lifecycle, "_client_reconnect_diagnostic", observe_terminal)

    class ObservedWorker(lifecycle.InventoryWorker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            original_get = self._requests.get

            def wait_for_teardown(*get_args, **get_kwargs):
                if reconnected_written.is_set():
                    idle_get_entered.set()
                    self.stop_event.wait()
                    if self.stop_event.is_set():
                        raise queue.Empty
                return original_get(*get_args, **get_kwargs)

            self._requests.get = wait_for_teardown
            workers.append(self)

    class Native:
        def __init__(self, *args, **kwargs):
            self.epoch = epochs[0]
            self.continuity = None
            self.unresolved = False
            self.disposals = 0
            clients.append(self)

        def ready(self):
            if busy_stage == "ready" and 0 < clients.index(self) <= busy_count:
                return {"status": "unavailable", "reason": "busy"}
            return {"status": "ready", "connected": self.continuity is not None,
                    "source_exited": False}

        def register(self, metadata):
            calls.append((self, dict(metadata)))
            if busy_stage == "register" and 0 < clients.index(self) <= busy_count:
                return {"status": "unavailable", "reason": "busy"}
            self.continuity = proof
            if self.epoch > 1:
                recovered.set()
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
    monkeypatch.setattr(lifecycle, "RECONNECT_INITIAL_BACKOFF_SECONDS", .001)
    monkeypatch.setattr(lifecycle, "RECONNECT_MAX_BACKOFF_SECONDS", .001)
    operations = []
    server = _protocol_server(monkeypatch, Native, operations)

    async def exercise(session):
        assert not (await _actual_status(session, "admitted")).isError
        epochs[0] = 2
        try:
            assert await asyncio.to_thread(dispose_started.wait, 1)
            worker = workers[0]
            assert len(clients) == 2
            assert len(calls) == (1 if busy_stage == "ready" else 2)
            assert clients[1].disposals == 1
            assert worker._thread.is_alive()
        finally:
            release_dispose.set()
        assert await asyncio.to_thread(recovered.wait, 1), "busy admission stranded accepted worker"
        assert worker._thread.is_alive() and not worker.stop_event.is_set()
        assert worker._restart_allowed
        assert await asyncio.to_thread(reconnected_written.wait, 1)
        assert await asyncio.to_thread(idle_get_entered.wait, 1)

    try:
        await _serve_protocol(server, exercise)
    finally:
        release_dispose.set()
    assert len(clients) == busy_count + 2
    assert len(calls) == (2 if busy_stage == "ready" else busy_count + 2)
    assert all(metadata == {"thread_ref": "actual-runtime", "turn_ref": "admitted"}
               for _, metadata in calls)
    assert all(client.continuity == proof and client.disposals == 1 for client in clients)
    assert len(operations) == 1
    assert not workers[0]._thread.is_alive()
    assert len(terminal_rows) == 2, terminal_rows
    assert len({row["episode"] for row in terminal_rows}) == 2, terminal_rows
    assert all(row["owned_worker"] for row in terminal_rows), terminal_rows
    log_path = tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log"
    written = [line for line in log_path.read_text(encoding="utf-8").splitlines()
               if "reconnect_terminal" in line]
    assert len(written) == 2, "\n".join(written)
    for row, line in zip(terminal_rows, written, strict=True):
        for field in ("episode", "context", "phase", "phase_state", "attempt", "registration",
                      "outcome", "restart_allowed", "unresolved", "owner_exited"):
            assert f"{field}={row[field]}" in line.split(), "\n".join(written)
    successful, shutdown_refusal = terminal_rows
    assert successful["outcome"] == "reconnected", terminal_rows
    assert successful["phase"] == "postregister" and successful["phase_state"] == "completed", terminal_rows
    assert successful["attempt"] == busy_count + 1, terminal_rows
    assert successful["registration"] == "completed" and successful["restart_allowed"] is True, terminal_rows
    assert shutdown_refusal["outcome"] == "preentry-refused", terminal_rows
    assert shutdown_refusal["phase"] == "preflight" and shutdown_refusal["phase_state"] == "completed", terminal_rows
    assert shutdown_refusal["attempt"] == 0 and shutdown_refusal["registration"] == "not-attempted", terminal_rows
    assert shutdown_refusal["restart_allowed"] is False, terminal_rows


def _automatic_recovery_worker(monkeypatch):
    # Exercise the retry loop without creating another background owner.
    worker = lifecycle.InventoryWorker.__new__(lifecycle.InventoryWorker)
    worker._path = "unused-bootstrap"
    worker.stop_event = threading.Event()
    worker._retained = True
    worker._restart_allowed = True
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "original-capability")
    monkeypatch.setattr(lifecycle, "RECONNECT_INITIAL_BACKOFF_SECONDS", .001)
    monkeypatch.setattr(lifecycle, "RECONNECT_MAX_BACKOFF_SECONDS", .001)
    return worker


def test_reconnect_terminal_rows_correlate_real_workers_and_episodes(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "original-capability")
    monkeypatch.setattr(lifecycle, "RECONNECT_MAX_ATTEMPTS", 1)
    proof = "a" * 64
    invocations = [(0, 0), (0, 1), (1, 0)]

    class Old:
        continuity, unresolved, manifest = proof, False, {"epoch": "retired"}
        io = SimpleNamespace(unresolved=False)
        def service_current(self):
            return False
        def dispose(self):
            pass

    class Native:
        def __init__(self, *_args, **_kwargs):
            raise bridge.ShadowUnavailable("startup-unavailable")

    workers = [_automatic_recovery_worker(monkeypatch) for _ in range(2)]
    for worker in workers:
        worker._retained = True

    def run(item):
        worker_index, _episode_index = item
        result = workers[worker_index]._recover_if_gone(
            Old(), Native, "original-capability", {"thread_ref": "runtime", "turn_ref": "turn"}, proof)
        assert result == (None, True)

    threads = [threading.Thread(target=run, args=(item,)) for item in invocations]
    for thread in threads:
        thread.start()
    try:
        for thread in threads:
            thread.join(2)
            assert not thread.is_alive()
    finally:
        for thread in threads:
            thread.join(1)

    path = tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log"
    records = [line for line in path.read_text(encoding="utf-8").splitlines()
               if "reconnect_terminal" in line]
    assert len(records) == len(invocations)
    episodes = [int(line.split("episode=", 1)[1].split()[0]) for line in records]
    assert len(set(episodes)) == len(invocations)
    assert all("phase=backoff" in line and "attempt=1" in line
               and "registration=not-attempted" in line
               and "outcome=attempts-exhausted" in line
               and "owner_exited=unknown" in line for line in records)


def test_reconnect_early_guard_keeps_last_entered_attempt(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "original-capability")
    monkeypatch.setattr(lifecycle, "RECONNECT_MAX_ATTEMPTS", 3)
    worker = _automatic_recovery_worker(monkeypatch)
    worker._retained = True
    real_monotonic = time.monotonic
    clock_reads = []
    monkeypatch.setattr(lifecycle, "time", SimpleNamespace(
        monotonic=lambda: (clock_reads.append(None), real_monotonic())[1]))
    proof = "a" * 64

    class Old:
        continuity, unresolved, manifest = proof, False, {"epoch": "retired"}
        io = SimpleNamespace(unresolved=False)
        def service_current(self):
            return False
        def dispose(self):
            pass

    class Native:
        def __init__(self, *_args, **_kwargs):
            raise bridge.ShadowUnavailable("startup-unavailable")

    def stop_after_first_attempt(_timeout):
        worker.stop_event.set()
        return False
    worker.stop_event.wait = stop_after_first_attempt
    assert worker._recover_if_gone(Old(), Native, "original-capability",
        {"thread_ref": "runtime", "turn_ref": "turn"}, proof) == (None, True)
    path = tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log"
    terminal = [line for line in path.read_text(encoding="utf-8").splitlines()
                if "reconnect_terminal" in line]
    assert len(terminal) == 1
    assert "phase=preflight" in terminal[0] and "attempt=1" in terminal[0]
    assert "outcome=reconnect-guard-refused" in terminal[0]
    assert len(clock_reads) == 3, "stop must short-circuit the next window clock read"


def test_reconnect_raise_is_logged_without_changing_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "original-capability")
    worker = _automatic_recovery_worker(monkeypatch)
    worker._retained = True
    failure = RuntimeError("sentinel recovery failure")

    class Old:
        continuity, unresolved, manifest = "a" * 64, False, {"epoch": "retired"}
        io = SimpleNamespace(unresolved=False)
        def service_current(self):
            return False
        def dispose(self):
            pass

    class Candidate:
        @property
        def continuity(self):
            return None
        @continuity.setter
        def continuity(self, _value):
            raise failure

    class Native:
        def __new__(cls, *_args, **_kwargs):
            return Candidate()

    with pytest.raises(RuntimeError) as raised:
        worker._recover_if_gone(Old(), Native, "original-capability",
            {"thread_ref": "runtime", "turn_ref": "turn"}, "a" * 64)
    assert raised.value is failure
    path = tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log"
    terminal = [line for line in path.read_text(encoding="utf-8").splitlines()
                if "reconnect_terminal" in line]
    assert len(terminal) == 1 and "outcome=reconnect-error" in terminal[0]
    assert "sentinel recovery failure" not in terminal[0]


@pytest.mark.parametrize(("case", "expected_outcome", "expected_unresolved"), [
    ("register-proof", "postregister-fence-refused", "unknown"),
    ("register-unresolved", "postregister-fence-refused", "True"),
    ("ready-refused", "ready-refused", "unknown"),
    ("register-exception", "register-uncertain", "unknown"),
    ("register-malformed", "register-unconfirmed", "unknown"),
    ("service-check-raises", "reconnect-error", "unknown"),
])
def test_reconnect_episode_records_truthful_stage_and_last_known_state(
        monkeypatch, tmp_path, case, expected_outcome, expected_unresolved):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "original-capability")
    worker = _automatic_recovery_worker(monkeypatch)
    worker._fresh_request_retirement = None
    worker._retained = True
    proof = "a" * 64
    register_calls = []

    class Old:
        manifest, continuity, unresolved = {"epoch": "old"}, proof, False
        io = SimpleNamespace(unresolved=False)
        def service_current(self):
            if case == "service-check-raises":
                raise RuntimeError("service-check-sentinel")
            return True
        def ready(self):
            raise bridge.ShadowUnavailable("transport-failed")
        def bootstrap_unchanged(self):
            return True
        def retired_service_exited(self):
            return False
        def retire(self):
            pass
        def dispose(self):
            pass

    class Native:
        def __init__(self, *_args, **_kwargs):
            self.manifest = {"epoch": "old"}
            self.continuity, self.unresolved = None, False
            self.io = SimpleNamespace(unresolved=False)
        def bootstrap_unchanged(self):
            return True
        def ready(self):
            if case == "ready-refused":
                return {"status": "unavailable", "reason": "peer-mismatch"}
            return {"status": "ready"}
        def register(self, _metadata):
            register_calls.append(case)
            if case == "register-proof":
                self.continuity = "b" * 64
            elif case == "register-unresolved":
                self.unresolved = True
            elif case == "register-exception":
                raise bridge.ShadowUnavailable("transport-failed")
            elif case == "register-malformed":
                return None
            return {"status": "registered", "reason": "ok"}
        def dispose(self):
            pass

    old = Old()
    replacement, disposed = worker._recover_if_gone(
        old, Native, "original-capability", {"thread_ref": "runtime", "turn_ref": "turn"}, proof,
        allow_ready_retirement=True)
    assert replacement is None and (disposed is (case != "service-check-raises"))
    path = tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log"
    terminal = [line for line in path.read_text(encoding="utf-8").splitlines()
                if "reconnect_terminal" in line]
    assert len(terminal) == 1
    assert f"outcome={expected_outcome}" in terminal[0]
    assert f"unresolved={expected_unresolved}" in terminal[0]
    assert register_calls == ([] if case in {"ready-refused", "service-check-raises"} else [case])
    if case == "service-check-raises":
        assert "phase=service-check" in terminal[0] and "phase_state=raised" in terminal[0]
        assert "service-check-sentinel" not in terminal[0]
    if case == "ready-refused":
        assert "registration=not-attempted" in terminal[0]
    elif case == "register-exception":
        assert "registration=attempted" in terminal[0]


@pytest.mark.parametrize("case", [
    "live-owner", "exited-owner", "unproved-epoch", "same-epoch-after-exit",
    "old-witness-error", "old-bootstrap-after", "new-bootstrap", "capability-after",
    "retire-unresolved", "old-cleanup-error", "old-cleanup-unresolved", "old-cleanup-capability",
    "ready-proof", "ready-unresolved", "ready-stop", "ready-refused", "ready-exception",
    "register-stop-cleanup-unresolved", "rejected-candidate-cleanup-unresolved",
    "register-proof", "register-unresolved", "register-exception", "ready-fence-error",
])
def test_idle_retired_episode_fences_identity_and_cleanup(monkeypatch, tmp_path, case):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    worker = _automatic_recovery_worker(monkeypatch)
    worker._fresh_request_retirement = None
    clients, registrations = [], []
    proof = "a" * 64

    class Old:
        manifest = {"epoch": "old"}
        continuity, unresolved, retired, changed, disposals = proof, False, False, False, 0
        io = SimpleNamespace(unresolved=False)
        def service_current(self):
            return True
        def ready(self):
            raise bridge.ShadowUnavailable("transport-failed")
        def bootstrap_unchanged(self):
            return not self.changed
        def retired_service_exited(self):
            if case == "old-witness-error":
                raise bridge.ShadowUnavailable("peer-unavailable")
            return case in {"exited-owner", "same-epoch-after-exit"}
        def retire(self):
            self.retired = True
            self.io = None
            self.unresolved = case == "retire-unresolved"
        def dispose(self):
            self.disposals += 1
            if case == "old-cleanup-error":
                raise OSError("unsettled old owner")
            if case == "old-cleanup-unresolved":
                self.unresolved = True
            if case == "old-cleanup-capability":
                monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "changed-capability")

    old = Old()

    class Native:
        def __init__(self, _path, stop, *, retained, previous_manifest=None):
            assert retained
            assert (previous_manifest == old.manifest) == (case in {"exited-owner", "same-epoch-after-exit"})
            self.manifest = {"epoch": "new" if case in {"exited-owner", "unproved-epoch"} else "old"}
            self._continuity, self.raise_continuity_read = None, False
            self._unresolved, self.unresolved_reads, self.disposals = False, [], 0
            self.io = SimpleNamespace(unresolved=False)
            clients.append(self)
            if case == "old-bootstrap-after":
                old.changed = True
            if case == "capability-after":
                monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "changed-capability")
        @property
        def continuity(self):
            if self.raise_continuity_read:
                raise RuntimeError("private-fence-sentinel")
            return self._continuity
        @continuity.setter
        def continuity(self, value):
            self._continuity = value
        @property
        def unresolved(self):
            if case == "register-stop-cleanup-unresolved":
                self.unresolved_reads.append(self._unresolved)
            return self._unresolved
        @unresolved.setter
        def unresolved(self, value):
            self._unresolved = value
        def bootstrap_unchanged(self):
            return case not in {"new-bootstrap", "rejected-candidate-cleanup-unresolved"}
        def ready(self):
            if case == "ready-proof":
                self.continuity = "b" * 64
            if case == "ready-unresolved":
                self.io.unresolved = True
            if case == "ready-stop":
                worker.stop_event.set()
            if case == "ready-exception":
                raise bridge.ShadowUnavailable("deadline")
            if case == "ready-fence-error":
                self.raise_continuity_read = True
            return {"status": "unavailable", "reason": "peer-mismatch"} if case == "ready-refused" else {"status": "ready"}
        def register(self, metadata):
            registrations.append(dict(metadata))
            if case == "register-stop-cleanup-unresolved":
                worker.stop_event.set()
                return {"status": "registered", "reason": "ok"}
            if case == "register-proof":
                self.continuity = "b" * 64
            if case == "register-unresolved":
                self.unresolved = True
            if case == "register-exception":
                raise bridge.ShadowUnavailable("transport-failed")
            return {"status": "registered", "reason": "ok"}
        def dispose(self):
            self.disposals += 1
            if case in {"register-stop-cleanup-unresolved", "rejected-candidate-cleanup-unresolved"}:
                self.unresolved = True
            self.io = None

    metadata = {"thread_ref": "actual-runtime", "turn_ref": "admitted"}
    replacement, disposed = worker._recover_if_gone(
        old, Native, "original-capability", metadata, proof, allow_ready_retirement=True)
    if not disposed:
        worker._finish(old)
    accepted = case in {"live-owner", "exited-owner"}
    assert (replacement is not None) == accepted
    assert old.retired and old.disposals == 1 and worker._fresh_request_retirement is None
    assert len(clients) == (0 if case in {"old-witness-error", "retire-unresolved"} else 1)
    assert all(entry == metadata for entry in registrations)
    if replacement is not None:
        worker._finish(replacement)
    assert all(client.disposals == 1 and client.io is None for client in clients)
    if case == "ready-fence-error":
        assert registrations == []
        path = tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log"
        terminal = [line for line in path.read_text(encoding="utf-8").splitlines()
                    if "reconnect_terminal" in line]
        assert len(terminal) == 1
        assert "phase=candidate-fence" in terminal[0] and "phase_state=raised" in terminal[0]
        assert "outcome=safety-refused" in terminal[0]
        assert "private-fence-sentinel" not in terminal[0]
    if case in {"old-cleanup-error", "old-cleanup-unresolved"}:
        path = tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log"
        terminal = [line for line in path.read_text(encoding="utf-8").splitlines()
                    if "reconnect_terminal" in line]
        assert len(terminal) == 1
        assert "phase=cleanup" in terminal[0] and "phase_state=completed" in terminal[0]
        assert "outcome=safety-refused" in terminal[0] and "unresolved=True" in terminal[0]
    if case == "register-stop-cleanup-unresolved":
        assert len(clients) == 1 and clients[0].unresolved_reads == [False, False, True]
        path = tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log"
        terminal = [line for line in path.read_text(encoding="utf-8").splitlines()
                    if "reconnect_terminal" in line]
        assert len(terminal) == 1
        assert "outcome=postregister-fence-refused" in terminal[0]
        assert "unresolved=True" in terminal[0]
    if case == "rejected-candidate-cleanup-unresolved":
        assert len(clients) == 1 and clients[0].disposals == 1 and registrations == []
        path = tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log"
        terminal = [line for line in path.read_text(encoding="utf-8").splitlines()
                    if "reconnect_terminal" in line]
        assert len(terminal) == 1
        assert "phase=constructor" in terminal[0] and "outcome=safety-refused" in terminal[0]
        assert "unresolved=True" in terminal[0] and "restart_allowed=False" in terminal[0]


@pytest.mark.parametrize("bound", ["attempts", "window", "shutdown"])
def test_idle_retired_episode_shares_one_budget_across_acquisition_and_busy(monkeypatch, tmp_path, bound):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    worker = _automatic_recovery_worker(monkeypatch)
    worker._fresh_request_retirement = None
    monkeypatch.setattr(lifecycle, "RECONNECT_MAX_ATTEMPTS", 3)
    clock, attempts, clients, registrations, clock_reads = [0.0], [], [], [], []
    def monotonic():
        clock_reads.append(clock[0])
        return clock[0]
    monkeypatch.setattr(lifecycle, "time", SimpleNamespace(monotonic=monotonic))
    monkeypatch.setattr(lifecycle, "RECONNECT_WINDOW_SECONDS", .02)
    def backoff(timeout):
        if bound == "window":
            clock[0] = .02
        if bound == "shutdown":
            worker.stop_event.set()
        return worker.stop_event.is_set()
    worker.stop_event.wait = backoff

    class Old:
        manifest, continuity, unresolved = {"epoch": "same"}, "a" * 64, False
        io = SimpleNamespace(unresolved=False)
        disposals = 0
        def service_current(self):
            return True
        def bootstrap_unchanged(self):
            return True
        def retired_service_exited(self):
            return False
        def ready(self):
            raise bridge.ShadowUnavailable("deadline")
        def retire(self):
            self.io = None
        def dispose(self):
            self.disposals += 1

    class Native:
        def __init__(self, *args, **kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1:
                raise bridge.ShadowUnavailable("startup-unavailable")
            self.manifest, self.continuity, self.unresolved = {"epoch": "same"}, None, False
            self.disposals = 0
            clients.append(self)
        def bootstrap_unchanged(self):
            return True
        def ready(self):
            return {"status": "unavailable", "reason": "busy"} if len(attempts) == 2 else {"status": "ready"}
        def register(self, metadata):
            registrations.append(metadata)
            return {"status": "unavailable", "reason": "busy"}
        def dispose(self):
            self.disposals += 1

    old = Old()
    assert worker._recover_if_gone(old, Native, "original-capability",
        {"thread_ref": "actual-runtime", "turn_ref": "admitted"}, old.continuity,
        allow_ready_retirement=True) == (None, True)
    assert len(attempts) == (3 if bound == "attempts" else 1)
    assert len(registrations) == (1 if bound == "attempts" else 0)
    assert old.disposals == 1 and worker._fresh_request_retirement is None
    assert all(client.disposals == 1 for client in clients)
    assert worker._restart_allowed
    if bound == "window":
        path = tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log"
        terminal = [line for line in path.read_text(encoding="utf-8").splitlines()
                    if "reconnect_terminal" in line]
        assert len(terminal) == 1
        assert "phase=preflight" in terminal[0] and "outcome=window-exhausted" in terminal[0]
        assert clock_reads == [0.0, 0.0, 0.0, .02]


def test_constructor_finishing_after_window_records_cleanup_unresolved(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLIUM_HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "original-capability")
    worker = _automatic_recovery_worker(monkeypatch)
    worker._retained = True
    monkeypatch.setattr(lifecycle, "RECONNECT_WINDOW_SECONDS", .02)
    clock, clock_reads, clients, native_calls = [0.0], [], [], []

    def monotonic():
        clock_reads.append(clock[0])
        return clock[0]
    monkeypatch.setattr(lifecycle, "time", SimpleNamespace(monotonic=monotonic))

    class Old:
        continuity, unresolved, manifest = "a" * 64, False, {"epoch": "old"}
        io = SimpleNamespace(unresolved=False)
        def service_current(self):
            return False
        def dispose(self):
            pass

    class Native:
        def __init__(self, *_args, **_kwargs):
            self.manifest = {"epoch": "new"}
            self.continuity, self.unresolved = None, False
            self.io = SimpleNamespace(unresolved=False)
            self.disposals = 0
            clients.append(self)
            clock[0] = .02
        def ready(self):
            native_calls.append("ready")
            pytest.fail("expired candidate must be disposed before READY")
        def register(self, _metadata):
            native_calls.append("register")
            pytest.fail("expired candidate must not REGISTER")
        def dispose(self):
            self.disposals += 1
            self.unresolved = True

    assert worker._recover_if_gone(
        Old(), Native, "original-capability", {"thread_ref": "runtime", "turn_ref": "turn"},
        "a" * 64) == (None, True)
    assert native_calls == [] and len(clients) == 1
    assert clients[0].disposals == 1 and clients[0].unresolved is True
    assert worker._restart_allowed is False
    assert clock_reads == [0.0, 0.0, .02]
    path = tmp_path / "logs" / f"codex-retained-client-{os.getpid()}.log"
    terminal = [line for line in path.read_text(encoding="utf-8").splitlines()
                if "reconnect_terminal" in line]
    assert len(terminal) == 1
    assert "phase=cleanup" in terminal[0] and "phase_state=completed" in terminal[0]
    assert "outcome=window-exhausted" in terminal[0] and "unresolved=True" in terminal[0]


@pytest.mark.parametrize("stage", ["ready", "register"])
@pytest.mark.parametrize("failure", ["proof", "disposed-proof", "unresolved", "dispose-error",
                                     "capability", "disposed-capability", "nonbusy", "exception"])
def test_busy_recovery_rejects_changed_or_uncertain_candidate(monkeypatch, stage, failure):
    worker = _automatic_recovery_worker(monkeypatch)
    clients = []
    proof = "8" * 64

    class Native:
        def __init__(self, *args, **kwargs):
            self.continuity = None
            self.unresolved = False
            self.disposals = 0
            clients.append(self)

        def reject(self):
            if failure == "proof":
                self.continuity = "9" * 64
            if failure == "capability":
                os.environ["CODEX_APP_TOOLS_PIPE_PATH"] = "changed-capability"
            if failure == "exception":
                raise bridge.ShadowUnavailable("invalid-response")
            return {"status": "unavailable", "reason": "closed" if failure == "nonbusy" else "busy"}

        def ready(self):
            return self.reject() if stage == "ready" else {"status": "ready"}

        def register(self, metadata):
            assert metadata == {"thread_ref": "actual-runtime", "turn_ref": "admitted"}
            return self.reject()

        def dispose(self):
            self.disposals += 1
            if failure == "disposed-proof":
                self.continuity = "9" * 64
            if failure == "disposed-capability":
                os.environ["CODEX_APP_TOOLS_PIPE_PATH"] = "changed-capability"
            if failure == "unresolved":
                self.unresolved = True
            if failure == "dispose-error":
                raise OSError("unresolved disposal")

    assert worker._auto_reconnect(Native, "original-capability",
        {"thread_ref": "actual-runtime", "turn_ref": "admitted"}, proof) is None
    assert len(clients) == 1 and clients[0].disposals == 1
    if failure in {"unresolved", "dispose-error"}:
        assert not worker._restart_allowed


@pytest.mark.parametrize("bound", ["attempts", "window", "early-wake", "shutdown"])
def test_busy_and_startup_recovery_share_finite_budget(monkeypatch, bound):
    worker = _automatic_recovery_worker(monkeypatch)
    attempts, disposed = [], []
    monkeypatch.setattr(lifecycle, "RECONNECT_MAX_ATTEMPTS", 3)
    if bound in {"window", "early-wake"}:
        clock, waits, entered = [0.0], [], []
        real_monotonic = time.monotonic
        monkeypatch.setattr(lifecycle, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        monkeypatch.setattr(lifecycle, "RECONNECT_WINDOW_SECONDS", .02)
        monkeypatch.setattr(lifecycle, "RECONNECT_INITIAL_BACKOFF_SECONDS", .04)
        def consume_budget(timeout):
            waits.append(timeout)
            clock[0] += timeout - .001 if bound == "early-wake" and len(waits) == 1 else timeout
            return False
        worker.stop_event.wait = consume_budget
    if bound == "shutdown":
        def stop_on_backoff(_timeout):
            worker.stop_event.set()
            return True
        worker.stop_event.wait = stop_on_backoff

    class Native:
        def __init__(self, *args, previous_manifest, **kwargs):
            attempts.append(previous_manifest)
            if bound in {"window", "early-wake"}:
                entered.append(clock[0])
            self.continuity = None
            self.unresolved = False
            if bound == "attempts" and len(attempts) == 1:
                raise bridge.ShadowUnavailable("startup-unavailable")

        def ready(self):
            return {"status": "unavailable", "reason": "busy"}

        def register(self, metadata):
            pytest.fail("readiness was rejected")

        def dispose(self):
            disposed.append(self)

    assert worker._auto_reconnect(Native, "original-capability",
        {"thread_ref": "actual-runtime", "turn_ref": "admitted"}, "8" * 64, {"epoch": 1}) is None
    expected = {"attempts": 3, "early-wake": 2}.get(bound, 1)
    assert attempts == [{"epoch": 1}] * expected
    assert len(disposed) == (2 if bound == "attempts" else expected)
    assert worker._restart_allowed
    assert worker.stop_event.is_set() is (bound == "shutdown")
    if bound in {"window", "early-wake"}:
        assert waits == pytest.approx([.02, .001] if bound == "early-wake" else [.02])
        assert entered == pytest.approx([0, .019] if bound == "early-wake" else [0])
        assert all(value < .02 for value in entered) and clock[0] == pytest.approx(.02)
        assert time.monotonic is real_monotonic


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", [
    "proof", "unresolved", "service-gone", "service-error", "capability", "thread",
])
async def test_busy_response_does_not_preserve_changed_or_unresolved_admission(monkeypatch, denial):
    clients, calls = [], []
    admitted_ready, ready_responses = threading.Event(), []
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
            result = {"status": "ready", "connected": self.continuity is not None,
                      "source_exited": False}
            if self.continuity == proof and len(calls) == 1:
                ready_responses.append(dict(result))
                admitted_ready.set()
            return result

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
        # Observe a real idle poll before injecting the next admission refusal.
        assert await asyncio.to_thread(admitted_ready.wait, 1)
        assert ready_responses[0].get("connected") is True
        assert ready_responses[0].get("source_exited") is False
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
        catalog = await session.list_tools()
        assert any(tool.name == "pallium_relay_status" for tool in catalog.tools)
        assert not clients and not calls and not operations
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
            return {"status": "ready", "connected": self.continuity is not None,
                    "source_exited": False}

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
