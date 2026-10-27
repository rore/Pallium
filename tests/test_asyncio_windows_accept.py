"""Regression: a transient per-connection OSError must NOT close the listener.

Upstream CPython's ``BaseProactorEventLoop._start_serving`` closes the listening
socket on any OSError raised by the AcceptEx future. In production this means a
single misbehaving client (typical: ``WinError 64`` ERROR_NETNAME_DELETED from
an aborted half-open handshake) permanently kills the API listener while the
process keeps running. The patch in ``app.asyncio_windows_accept`` distinguishes
transient per-connection errors from fatal listener errors, mirroring the
behavior of Linux's ``SelectorEventLoop._accept_connection``.

These tests drive the patched ``_start_serving`` against a faked proactor and
socket, asserting:

1. A transient OSError (WinError 64) does NOT close the listening socket and
   DOES reschedule a fresh ``_proactor.accept(sock)`` call.
2. A resource-exhaustion OSError (EMFILE) closes the listener (matching upstream
   behavior — there's no graceful recovery from fd exhaustion at this layer).
3. ``sock.fileno() == -1`` (listener already torn down) is a clean no-op.
4. The patch is idempotent.
"""

from __future__ import annotations

import errno
import asyncio
import gc
import socket
import sys
from unittest.mock import MagicMock

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="ProactorEventLoop accept patch is Windows-specific",
)


def _install_patch_clean() -> None:
    """Force a fresh patch install (clears the idempotency flag first)."""
    from asyncio import proactor_events

    from app.asyncio_windows_accept import _PATCH_APPLIED_ATTR, apply_patch

    # Clear the flag set by app.main's import-time apply so we exercise the
    # real install path. The replacement function is identical.
    if hasattr(proactor_events.BaseProactorEventLoop, _PATCH_APPLIED_ATTR):
        delattr(proactor_events.BaseProactorEventLoop, _PATCH_APPLIED_ATTR)
    assert apply_patch() is True


class _FakeFuture:
    """Just enough Future surface for the patched _start_serving."""

    def __init__(self, exc: Exception | None = None, result: tuple | None = None):
        self._exc = exc
        self._result = result
        self._callbacks: list = []

    def result(self):
        if self._exc is not None:
            raise self._exc
        return self._result

    def add_done_callback(self, cb):
        self._callbacks.append(cb)


class _FakeProactor:
    def __init__(self):
        self.accept_calls: list = []
        self._futures: list[_FakeFuture] = []

    def queue_future(self, future: _FakeFuture) -> None:
        self._futures.append(future)

    def accept(self, sock):
        self.accept_calls.append(sock)
        if self._futures:
            return self._futures.pop(0)
        return _FakeFuture()  # never resolves


class _FakeSock:
    def __init__(self, fileno_value: int = 7):
        self._fileno = fileno_value
        self.close_count = 0

    def fileno(self) -> int:
        return self._fileno

    def close(self) -> None:
        self.close_count += 1
        self._fileno = -1


class _FakeLoop:
    """Minimal BaseProactorEventLoop substitute for direct call() testing."""

    def __init__(self):
        self._debug = False
        self._proactor = _FakeProactor()
        self._accept_futures: dict[int, _FakeFuture] = {}
        self._exception_messages: list[dict] = []
        self._call_soon_callbacks: list = []

    def is_closed(self) -> bool:
        return False

    def call_soon(self, cb, *args):
        self._call_soon_callbacks.append((cb, args))

    def call_exception_handler(self, ctx: dict) -> None:
        self._exception_messages.append(ctx)

    def _make_socket_transport(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("not expected in these tests")

    def _make_ssl_transport(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("not expected in these tests")


def _drive_first_accept(loop_fn, completed_future) -> None:
    """Helper: invoke the loop callback the way add_done_callback would."""
    loop_fn(completed_future)


def test_transient_oserror_keeps_listener_alive_and_reschedules():
    """WinError 64 (ERROR_NETNAME_DELETED) must not close the listener."""
    _install_patch_clean()
    from asyncio import proactor_events

    fake = _FakeLoop()
    sock = _FakeSock(fileno_value=42)

    # First accept() returns a future that fails with WinError 64.
    failing = _FakeFuture(exc=OSError(22, "The specified network name is no longer available"))
    failing._exc.winerror = 64  # type: ignore[attr-defined]
    fake._proactor.queue_future(failing)

    # The patched code, after handling the failure, will call _proactor.accept(sock)
    # again. That subsequent call returns a never-completing future to keep the
    # test simple — we only care that it WAS called.
    proactor_events.BaseProactorEventLoop._start_serving(
        fake, protocol_factory=MagicMock(), sock=sock
    )
    # call_soon scheduled the inner loop() — execute it synchronously.
    assert len(fake._call_soon_callbacks) == 1
    cb, _args = fake._call_soon_callbacks[0]
    cb()  # First tick: schedules the initial accept (the failing one).

    # Now simulate the failing future completing (add_done_callback fires).
    cb(failing)

    # 1. Listener was NOT closed.
    assert sock.close_count == 0, "transient OSError must NOT close listener"
    # 2. accept() was scheduled twice: initial + reschedule after failure.
    assert len(fake._proactor.accept_calls) == 2, fake._proactor.accept_calls
    # 3. Exception handler was called with a "kept alive" message.
    assert any(
        "listener kept alive" in ctx.get("message", "")
        for ctx in fake._exception_messages
    ), fake._exception_messages


@pytest.mark.parametrize("fatal_errno", [errno.EMFILE, errno.ENFILE, errno.ENOBUFS, errno.ENOMEM])
def test_resource_exhaustion_closes_listener(fatal_errno):
    """EMFILE/ENFILE/ENOBUFS/ENOMEM should still tear down (no graceful path)."""
    _install_patch_clean()
    from asyncio import proactor_events

    fake = _FakeLoop()
    sock = _FakeSock(fileno_value=42)

    failing = _FakeFuture(exc=OSError(fatal_errno, "private resource exhaustion"))
    fake._proactor.queue_future(failing)

    proactor_events.BaseProactorEventLoop._start_serving(
        fake, protocol_factory=MagicMock(), sock=sock
    )
    cb, _ = fake._call_soon_callbacks[0]
    cb()
    cb(failing)

    assert sock.close_count == 1, "EMFILE must close the listener"
    assert any(
        "resource exhaustion" in ctx.get("message", "")
        for ctx in fake._exception_messages
    ), fake._exception_messages


def test_listener_already_torn_down_is_noop():
    """If sock.fileno() == -1 already, the handler must not call close again."""
    _install_patch_clean()
    from asyncio import proactor_events

    fake = _FakeLoop()
    sock = _FakeSock(fileno_value=-1)  # Already torn down.

    failing = _FakeFuture(exc=OSError(22, "transient"))
    fake._proactor.queue_future(failing)

    proactor_events.BaseProactorEventLoop._start_serving(
        fake, protocol_factory=MagicMock(), sock=sock
    )
    cb, _ = fake._call_soon_callbacks[0]
    cb()
    cb(failing)

    assert sock.close_count == 0, "already-torn-down listener must not be closed again"
    # And no exception handler should have been called for this no-op path.
    assert fake._exception_messages == []


def test_apply_patch_is_idempotent():
    """Calling apply_patch a second time must return False and not double-wrap."""
    from asyncio import proactor_events

    from app.asyncio_windows_accept import _PATCH_APPLIED_ATTR, apply_patch

    if hasattr(proactor_events.BaseProactorEventLoop, _PATCH_APPLIED_ATTR):
        delattr(proactor_events.BaseProactorEventLoop, _PATCH_APPLIED_ATTR)
    assert apply_patch() is True
    assert apply_patch() is False, "second apply must be a no-op"
    assert getattr(proactor_events.BaseProactorEventLoop, _PATCH_APPLIED_ATTR) is True


def test_actual_windows_accept_failure_closes_peer_and_later_http_succeeds():
    """A failed real AcceptEx completion must release its peer, not its listener."""
    _install_patch_clean()

    async def journey():
        loop = asyncio.get_running_loop()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        allocated, reports = [], []
        reported = asyncio.Event()
        original_register = loop._proactor._register
        original_socket = loop._proactor._get_accept_socket
        injected = False

        def track(family):
            peer = original_socket(family)
            allocated.append(peer)
            return peer

        def register(operation, owner, complete):
            nonlocal injected
            if owner is listener and not injected:
                injected = True
                def abort(*args):
                    raise OSError(22, "private accept completion abort", None, 64)
                complete = abort
            return original_register(operation, owner, complete)

        def handler(_, context):
            reports.append(context.get("message", ""))
            if "listener kept alive" in context.get("message", ""):
                reported.set()

        class HTTP(asyncio.Protocol):
            def connection_made(self, transport):
                self.transport = transport

            def data_received(self, data):
                self.transport.write(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nOK")
                self.transport.close()

        loop._proactor._register = register
        loop._proactor._get_accept_socket = track
        loop.set_exception_handler(handler)
        first = server = None
        try:
            server = await loop.create_server(HTTP, sock=listener)
            address = listener.getsockname()
            first = socket.create_connection(address, timeout=1)
            await asyncio.wait_for(reported.wait(), 3)
            peer_closed = allocated[0].fileno() == -1
            reader, writer = await asyncio.wait_for(asyncio.open_connection(*address), 3)
            writer.write(b"GET / HTTP/1.0\r\n\r\n")
            await writer.drain()
            response = await asyncio.wait_for(reader.read(), 3)
            writer.close()
            await writer.wait_closed()
            for _ in range(3):
                gc.collect()
                await asyncio.sleep(0)
            assert injected and response.endswith(b"OK")
            assert sum("listener kept alive" in value for value in reports) == 1
            assert peer_closed, "failed accepted peer remained open after its completion"
            assert not any("Task exception was never retrieved" in value for value in reports)
        finally:
            if first:
                first.close()
            if server:
                server.close()
                await server.wait_closed()
            else:
                listener.close()
            for peer in allocated:
                peer.close()
            await asyncio.sleep(0)

    with asyncio.Runner(loop_factory=asyncio.ProactorEventLoop) as runner:
        runner.run(journey())


@pytest.mark.parametrize("failure", ["construct", "accept", "register"])
def test_native_accept_sync_failure_closes_only_peer_and_preserves_error(monkeypatch, failure):
    from asyncio import windows_events
    _install_patch_clean()

    async def journey():
        loop = asyncio.get_running_loop()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        allocated = []
        original_socket = loop._proactor._get_accept_socket
        marker = OSError(errno.EINVAL, "private synchronous accept failure")

        def track(family):
            peer = original_socket(family)
            allocated.append(peer)
            return peer

        class Operation:
            def AcceptEx(self, *args):
                if failure == "accept":
                    raise marker

        def operation(*args):
            if failure == "construct":
                raise marker
            return Operation()

        def register(*args):
            raise marker

        try:
            loop._proactor._get_accept_socket = track
            with monkeypatch.context() as native:
                native.setattr(windows_events._overlapped, "Overlapped", operation)
                native.setattr(loop._proactor, "_register", register)
                with pytest.raises(OSError) as raised:
                    loop._proactor.accept(listener)
            assert raised.value is marker
            assert len(allocated) == 1 and allocated[0].fileno() == -1
            assert listener.fileno() != -1
        finally:
            loop._proactor._stop_serving(listener)
            listener.close()
            for peer in allocated:
                peer.close()

    with asyncio.Runner(loop_factory=asyncio.ProactorEventLoop) as runner:
        runner.run(journey())


@pytest.mark.parametrize("failure", ["context", "timeout", "peername"])
def test_native_accept_completion_failure_releases_peer_without_helper_task(monkeypatch, failure):
    _install_patch_clean()

    async def journey():
        loop = asyncio.get_running_loop()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        marker = OSError(errno.EINVAL, "private accept completion failure")
        original_socket = loop._proactor._get_accept_socket
        peers, reports = [], []

        class Peer:
            def __init__(self, family):
                self.raw = original_socket(family)
                self.closes = 0
                peers.append(self)

            def fileno(self):
                return self.raw.fileno()

            def setsockopt(self, *args):
                if failure == "context":
                    raise marker
                self.raw.setsockopt(*args)

            def settimeout(self, value):
                if failure == "timeout":
                    raise marker
                self.raw.settimeout(value)

            def getpeername(self):
                if failure == "peername":
                    raise marker
                return self.raw.getpeername()

            def close(self):
                self.closes += 1
                self.raw.close()

        loop._proactor._get_accept_socket = Peer
        loop.set_exception_handler(lambda _, context: reports.append(context.get("message", "")))
        client = None
        try:
            future = loop._proactor.accept(listener)
            client = socket.create_connection(listener.getsockname(), timeout=1)
            with pytest.raises(OSError) as raised:
                await asyncio.wait_for(future, 3)
            await asyncio.sleep(0)
            gc.collect()
            await asyncio.sleep(0)
            assert raised.value is marker
            assert peers[0].fileno() == -1 and peers[0].closes == 1
            assert listener.fileno() != -1
            assert not reports
        finally:
            if client:
                client.close()
            loop._proactor._stop_serving(listener)
            listener.close()
            for peer in peers:
                peer.raw.close()

    with asyncio.Runner(loop_factory=asyncio.ProactorEventLoop) as runner:
        runner.run(journey())


@pytest.mark.parametrize("cancel_after_success", [False, True])
def test_native_accept_cancellation_and_success_keep_socket_ownership(cancel_after_success):
    _install_patch_clean()

    async def journey():
        loop = asyncio.get_running_loop()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        peers, reports = [], []
        original_socket = loop._proactor._get_accept_socket

        def track(family):
            peer = original_socket(family)
            peers.append(peer)
            return peer

        loop._proactor._get_accept_socket = track
        loop.set_exception_handler(lambda _, context: reports.append(context.get("message", "")))
        client = None
        try:
            future = loop._proactor.accept(listener)
            if cancel_after_success:
                client = socket.create_connection(listener.getsockname(), timeout=1)
                peer, address = await asyncio.wait_for(future, 3)
                assert not future.cancel()
                await asyncio.sleep(0)
                assert peer is peers[0] and peer.fileno() != -1
                assert address == client.getsockname() and peer.gettimeout() == listener.gettimeout()
                peer.send(b"OK")
                assert client.recv(2) == b"OK"
            else:
                assert future.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await future
                await asyncio.sleep(0)
                assert peers[0].fileno() == -1
            assert listener.fileno() != -1 and not reports
        finally:
            if client:
                client.close()
            loop._proactor._stop_serving(listener)
            listener.close()
            for peer in peers:
                peer.close()
            await asyncio.sleep(0)

    with asyncio.Runner(loop_factory=asyncio.ProactorEventLoop) as runner:
        runner.run(journey())


def test_non_windows_apply_does_not_change_existing_runtime_methods(monkeypatch):
    from asyncio import proactor_events, windows_events
    from app import asyncio_windows_accept as patch
    before = (proactor_events.BaseProactorEventLoop._start_serving, windows_events.IocpProactor.accept)
    with monkeypatch.context() as platform:
        platform.setattr(patch.sys, "platform", "linux")
        assert patch.apply_patch() is False
    assert (proactor_events.BaseProactorEventLoop._start_serving, windows_events.IocpProactor.accept) == before
