"""Pure observer/runner safety: no application, database, server or child journey."""
import asyncio
from contextlib import ExitStack
import json
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute

from scripts import relay_targeted_boundary_capture as capture


@pytest.mark.parametrize("failure", [None, ValueError("failure"), asyncio.CancelledError()])
def test_acquire_delegates_once_preserves_borrower_result_and_exception(failure):
    calls, borrower, result = [], object(), object()
    async def original(value):
        calls.append(value)
        if failure is not None:
            raise failure
        return result
    recorder = capture.Recorder()
    token = capture.REQUEST.set(7)
    try:
        if failure is None:
            assert asyncio.run(capture.acquire_observer(original, recorder)(borrower)) is result
        else:
            with pytest.raises(type(failure)) as raised:
                asyncio.run(capture.acquire_observer(original, recorder)(borrower))
            assert raised.value is failure
    finally:
        capture.REQUEST.reset(token)
    assert calls == [borrower]
    assert [event["stage"] for event in recorder.events] == ["acquire_start", "acquire_end"]
    assert {event["request"] for event in recorder.events} == {7}
    assert ("acquire_not_completed" in recorder.reasons) is (failure is not None)


def test_recorder_uncorrelated_caps_and_clock_fault_are_contained(monkeypatch):
    recorder = capture.Recorder()
    recorder.record("asgi_entry")
    assert recorder.events == [] and "uncorrelated" in recorder.reasons
    token = capture.REQUEST.set(1)
    try:
        for _ in range(capture.EVENT_LIMIT + 1):
            recorder.record("asgi_entry")
        assert len(recorder.events) == capture.EVENT_LIMIT
        assert "event_cap" in recorder.reasons
        monkeypatch.setattr(capture, "time", SimpleNamespace(monotonic=lambda: (_ for _ in ()).throw(ValueError())))
        recorder.record("route_entry")
        assert "observer_fault" in recorder.reasons
    finally:
        capture.REQUEST.reset(token)


def fake_client():
    calls = []
    class Limiter:
        async def acquire_on_behalf_of(self, borrower):
            calls.append(borrower)
            return "admitted"
    limiter = Limiter()
    borrower = object()
    async def endpoint():
        return await limiter.acquire_on_behalf_of(borrower)
    route = APIRoute("/relay/turn", endpoint, methods=["POST"])
    async def app(scope, receive, send):
        return await route.dependant.call()
    app.routes = [route]
    client = SimpleNamespace(app=app, _transport=SimpleNamespace(app=app))
    return client, route, limiter, borrower, calls


def test_actual_dependant_callable_and_transport_are_wrapped_and_restored():
    client, route, limiter, borrower, calls = fake_client()
    original_call, original_app = route.dependant.call, client.app
    recorder, stack = capture.Recorder(), ExitStack()
    capture.install(client, recorder, stack, limiter_lookup=lambda _: limiter)
    assert route.endpoint is original_call
    assert route.dependant.call is not original_call
    assert asyncio.run(client._transport.app({"type": "http"}, None, None)) == "admitted"
    assert calls == [borrower]
    assert [event["stage"] for event in recorder.events] == [
        "asgi_entry", "route_entry", "acquire_start", "acquire_end"]
    assert capture.REQUEST.get() is None
    stack.close()
    stack.close()
    assert client._transport.app is original_app
    assert route.dependant.call is original_call
    assert "acquire_on_behalf_of" not in vars(limiter)


def test_partial_install_can_restore_independently(monkeypatch):
    client, route, limiter, _, _ = fake_client()
    original_replace = capture.replace
    def fail_second(stack, owner, name, replacement):
        if owner is route.dependant:
            raise ValueError("partial install")
        return original_replace(stack, owner, name, replacement)
    monkeypatch.setattr(capture, "replace", fail_second)
    stack = ExitStack()
    with pytest.raises(ValueError):
        capture.install(client, capture.Recorder(), stack, limiter_lookup=lambda _: limiter)
    assert "acquire_on_behalf_of" in vars(limiter)
    stack.close()
    assert "acquire_on_behalf_of" not in vars(limiter)
    assert client._transport.app is client.app


def test_native_teardown_precedes_restoration_and_write(tmp_path, monkeypatch):
    order = []
    stack = ExitStack()
    stack.callback(lambda: order.append("restore"))
    recorder = capture.Recorder()
    item = SimpleNamespace(_boundary_capture=(recorder, stack, tmp_path))
    monkeypatch.setenv(capture.OUTPUT_ENV, str(tmp_path))
    def observed(*args):
        order.append("write")
        return {"complete": False}
    monkeypatch.setattr(capture, "observation", observed)
    hook = capture.pytest_runtest_teardown(item, None)
    next(hook)
    order.append("native_teardown")
    with pytest.raises(StopIteration):
        next(hook)
    assert order == ["native_teardown", "restore", "write"]


def test_non_target_fixture_does_not_resolve_client(monkeypatch):
    def forbidden(*args):
        raise AssertionError("must not request fixture")
    request = SimpleNamespace(node=SimpleNamespace(nodeid="unrelated"), getfixturevalue=forbidden)
    monkeypatch.setenv(capture.OUTPUT_ENV, "unused")
    capture._target_capture.__wrapped__(request)


def test_native_sanitization_retains_only_allowed_scalars(tmp_path):
    path = tmp_path / "stages.json"
    path.write_text(json.dumps([
        {"stage": "forward", "path": "/relay/turn", "entered": 1, "returned": 6,
         "error": {"secret": "payload"}, "delivery_id": "private"},
        {"stage": "worker", "submitted": 4, "entered": 4.1, "returned": 5},
        {"stage": "durable_turn", "entered": 4.2, "returned": 4.5},
    ]))
    recorder = capture.Recorder()
    recorder.events = [{"stage": stage, "request": 2, "time": index + 2}
                       for index, stage in enumerate(["asgi_entry", "route_entry", "acquire_start", "acquire_end"])]
    result = capture.observation(recorder, path)
    assert result["complete"]
    encoded = json.dumps(result)
    assert "private" not in encoded and "secret" not in encoded and "payload" not in encoded
    assert len(encoded.encode()) <= capture.JSON_LIMIT
    recorder.events.pop()
    assert not capture.observation(recorder, path)["complete"]


def test_closure_provenance_is_exact():
    value = object()
    def relay_turn():
        return value
    relay_turn.__module__ = "api.routes"
    assert capture.closure(relay_turn, "value", "api.routes", "relay_turn") is value
    with pytest.raises(ValueError):
        capture.closure(relay_turn, "value", "app.main", "relay_turn")
    with pytest.raises(KeyError):
        capture.closure(relay_turn, "unknown", "api.routes", "relay_turn")


def test_recover_exact_owned_limiter_chain_with_fake_instances(monkeypatch):
    import anyio
    class FakeLimiter:
        async def acquire_on_behalf_of(self, borrower):
            pass
    FakeLimiter.acquire_on_behalf_of.__module__ = "anyio.fake"
    monkeypatch.setattr(anyio, "CapacityLimiter", FakeLimiter)
    codex_admission_limiter = FakeLimiter()
    async def run_codex_relay_operation():
        return codex_admission_limiter
    run_codex_relay_operation.__module__ = "app.main"
    relay_codex_runner = run_codex_relay_operation
    async def _run_relay_operation():
        return relay_codex_runner
    _run_relay_operation.__module__ = "api.routes"
    async def relay_turn():
        return _run_relay_operation
    relay_turn.__module__ = "api.routes"
    assert capture.recover_limiter(relay_turn) is codex_admission_limiter
    codex_admission_limiter = object()
    with pytest.raises(ValueError):
        capture.recover_limiter(relay_turn)


def test_json_cap_and_observer_fault_do_not_change_delegate_result(monkeypatch):
    recorder = capture.Recorder()
    token = capture.REQUEST.set(1)
    try:
        monkeypatch.setattr(capture, "JSON_LIMIT", 4096)
        recorder.record("asgi_entry")
        assert recorder.events == [] and "json_cap" in recorder.reasons
        monkeypatch.setattr(capture, "time", SimpleNamespace(monotonic=lambda: (_ for _ in ()).throw(ValueError())))
        async def original(borrower):
            return borrower
        borrower = object()
        assert asyncio.run(capture.acquire_observer(original, recorder)(borrower)) is borrower
        assert "observer_fault" in recorder.reasons
    finally:
        capture.REQUEST.reset(token)


class FakeSelector:
    def __init__(self, *, ready=True):
        self.entries = {}
        self.ready = ready

    def register(self, stream, events, name):
        self.entries[stream.fileno()] = SimpleNamespace(fileobj=stream, data=name)

    def unregister(self, stream):
        del self.entries[stream.fileno()]

    def get_map(self):
        return self.entries

    def select(self, timeout):
        return [(entry, None) for entry in self.entries.values()] if self.ready else []

    def close(self):
        pass


def test_shared_stream_cap_preserves_native_exit_and_only_signals_owned_group(tmp_path, monkeypatch):
    chunks = iter([b"0123456789", b""])
    monkeypatch.setattr(capture, "selectors", SimpleNamespace(DefaultSelector=FakeSelector, EVENT_READ=1))
    monkeypatch.setattr(capture, "os", SimpleNamespace(set_blocking=lambda *args: None, read=lambda *args: next(chunks)))
    signals = []
    monkeypatch.setattr(capture, "terminate_group", lambda process, sig: signals.append((process.pid, sig)))
    process = SimpleNamespace(pid=4321, returncode=9, poll=lambda: 9, wait=lambda timeout: 9)
    stream = SimpleNamespace(fileno=lambda: 42)
    result = capture.collect(process, {"stdout.log": stream}, tmp_path, limit=4)
    assert result["native_exit"] == 9
    assert "output_cap" in result["reasons"]
    assert (tmp_path / "stdout.log").read_bytes() == b"0123"
    assert {pid for pid, _ in signals} == {4321}


def test_owned_timeout_terminates_then_kills_and_bounds_unsettled_drain(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "signal", SimpleNamespace(SIGTERM=15, SIGKILL=9))
    monkeypatch.setattr(capture, "selectors", SimpleNamespace(DefaultSelector=lambda: FakeSelector(ready=False), EVENT_READ=1))
    monkeypatch.setattr(capture, "os", SimpleNamespace(set_blocking=lambda *args: None))
    ticks = iter(range(100))
    monkeypatch.setattr(capture, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    signals = []
    monkeypatch.setattr(capture, "terminate_group", lambda process, sig: signals.append(sig))
    process = SimpleNamespace(pid=4321, returncode=None, poll=lambda: None,
                              wait=lambda timeout: (_ for _ in ()).throw(capture.subprocess.TimeoutExpired("fake", timeout)))
    stream = SimpleNamespace(fileno=lambda: 42)
    result = capture.collect(process, {"stdout.log": stream}, tmp_path, wall=1, term=1, drain=1)
    assert signals[:2] == [capture.signal.SIGTERM, capture.signal.SIGKILL]
    assert {"timeout", "drain_incomplete", "owned_process_unsettled"}.issubset(result["reasons"])
    assert result["native_exit"] is None


def test_normal_exit_drains_without_signal_and_closes_fifo_keeper_once(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "selectors", SimpleNamespace(DefaultSelector=FakeSelector, EVENT_READ=1))
    monkeypatch.setattr(capture, "os", SimpleNamespace(set_blocking=lambda *args: None, read=lambda *args: b""))
    monkeypatch.setattr(capture, "terminate_group", lambda *args: pytest.fail("normal drain must not signal"))
    closed = []
    keeper = SimpleNamespace(close=lambda: closed.append(True))
    process = SimpleNamespace(pid=4321, returncode=1, poll=lambda: 1, wait=lambda timeout: 1)
    result = capture.collect(process, {"native-junit.xml": SimpleNamespace(fileno=lambda: 42)},
                             tmp_path, fifo_writer=keeper)
    assert result["reasons"] == [] and result["native_exit"] == 1
    assert result["owned_settled"] and closed == [True]
