"""Transparency checks for the temporary, explicitly loaded hosted capture."""
import asyncio
from contextlib import contextmanager
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import weakref

import pytest

from core.errors import ImmediateTransactionBusyError
from scripts import pytest_relay_capture as plugin


def _backend():
    calls = []

    class Session:
        def connection(self, *args, **kwargs):
            calls.append(("connection", args, kwargs))
            return "actual-connection"

    def factory(*args, **kwargs):
        calls.append(("factory", args, kwargs))
        return Session()

    class Provider:
        def __init__(self, value):
            calls.append(("initialize", value))
            self._relay_session_factory = factory
            self._relay_engine = SimpleNamespace(pool=SimpleNamespace(checkedout=lambda: 0))

        @contextmanager
        def _begin_immediate_for(self, factory, *, option):
            calls.append(("inner", option))
            session = factory()
            session.connection(execution_options={"isolation_level": "AUTOCOMMIT"})
            try:
                yield session
            finally:
                calls.append(("settled", option))

        @contextmanager
        def _begin_relay_immediate(self, *, option):
            with self._begin_immediate_for(self._relay_session_factory, option=option) as session:
                yield session

    def router(*args, **kwargs):
        calls.append(("router", args))
        return kwargs
    return Provider, SimpleNamespace(create_router=router), calls, factory


def test_capture_delegates_once_restores_and_keeps_immutable_owner(capsys):
    provider_type, dependencies, calls, factory = _backend()
    original_init, original_router = provider_type.__init__, dependencies.create_router
    state = plugin.Capture()
    state.install(provider_type, dependencies)
    token = state.owner.set(("item", "original-item"))
    provider = provider_type("constructor-argument")
    state.owner.reset(token)
    state.owner.set(("item", "later-item"))
    result = object()
    operation_calls = []

    async def runner(operation):
        calls.append(("runner",))
        return operation()

    try:
        configured = dependencies.create_router("service", relay_service=SimpleNamespace(_store=provider),
                                                relay_runner=runner)

        def operation():
            operation_calls.append(True)
            with provider._begin_relay_immediate(option=17) as session:
                assert session.connection("unchanged", custom=True) == "actual-connection"
            return result
        assert asyncio.run(configured["relay_runner"](operation)) is result
        assert operation_calls == [True]
        assert calls.count(("initialize", "constructor-argument")) == 1
        assert calls.count(("inner", 17)) == calls.count(("settled", 17)) == 1
        assert calls.count(("runner",)) == 1
        assert ("connection", ("unchanged",), {"custom": True}) in calls
        assert all(row["owner_item"] == "original-item" for row in state.tail)
        assert state.boundary("original-item")["owned_pool_checkouts"] == [0]
    finally:
        state.close()
    assert provider_type.__init__ is original_init
    assert dependencies.create_router is original_router
    assert provider._relay_session_factory is factory
    assert capsys.readouterr() == ("", "")


def test_failure_origin_survives_tail_eviction_and_reports_no_private_data(capsys):
    state = plugin.Capture()
    native = RuntimeError("secret payload and private/path")
    native.sqlite_errorcode, native.sqlite_errorname = 5, "SQLITE_BUSY"
    failure = ImmediateTransactionBusyError("secret session token", acquisition_stage="late_begin")
    failure.__cause__ = native
    state.record(("unknown", None), "outer_error", failure)
    for _ in range(200):
        state.record(("session_fixture", None), "cleanup")
    assert len(state.tail) == 128 and state.dropped == 73
    assert state.failures[0]["acquisition_stage"] == "late_begin"
    assert state.failures[0]["causes"][1]["sqlite_code"] == 5
    state.emit("hashed-item", ["setup", "teardown"], {}, {})
    output = json.dumps(state.bundles[0])
    assert '"late_begin"' in output and '"sqlite_code": 5' in output
    assert "secret" not in output and "private/path" not in output


def test_original_error_and_context_cleanup_survive_diagnostic_failure(monkeypatch):
    provider_type, dependencies, calls, _ = _backend()
    state = plugin.Capture()
    state.install(provider_type, dependencies)
    failure = RuntimeError("original operation failure")
    try:
        provider = provider_type("unchanged")

        async def runner(operation):
            return operation()
        configured = dependencies.create_router(relay_service=SimpleNamespace(_store=provider), relay_runner=runner)

        def operation():
            with provider._begin_relay_immediate(option=23):
                raise failure
        with pytest.raises(RuntimeError) as caught:
            asyncio.run(configured["relay_runner"](operation))
        assert caught.value is failure
        assert ("settled", 23) in calls
        assert state.operation.get() is None
        monkeypatch.setattr(plugin, "time", SimpleNamespace(
            monotonic_ns=lambda: (_ for _ in ()).throw(OSError()),
            thread_time_ns=plugin.time.thread_time_ns))
        state.record(("unknown", None), "ignored")
        state.emit("hashed-item", ["call"], {}, {})
        monkeypatch.setattr(plugin, "_capture", state)
        plugin.pytest_terminal_summary(SimpleNamespace(
            write_line=lambda *a: (_ for _ in ()).throw(OSError())), 1, SimpleNamespace())
    finally:
        state.close()


def test_provider_registry_does_not_retain_provider():
    provider_type, dependencies, _, _ = _backend()
    state = plugin.Capture()
    state.install(provider_type, dependencies)
    try:
        provider = provider_type("unchanged")
        reference = weakref.ref(provider)
        del provider
        gc.collect()
        assert reference() is None
        assert list(state.providers.items()) == []
    finally:
        state.close()


@pytest.mark.parametrize("phase", ["setup", "call", "teardown"])
def test_hook_reports_once_after_teardown_and_resets_fixture_scope(monkeypatch, phase):
    state = plugin.Capture()
    monkeypatch.setattr(plugin, "_capture", state)
    monkeypatch.setattr(plugin, "_phases", {})
    item = SimpleNamespace(nodeid="test_node[private-payload/path]")
    identifier = plugin._item_id(item.nodeid)
    output = []
    monkeypatch.setattr(state, "emit", lambda *args: output.append(args))
    protocol = plugin.pytest_runtest_protocol(item, None)
    next(protocol)
    fixture = plugin.pytest_fixture_setup(None, SimpleNamespace(scope="session", node=item))
    next(fixture)
    assert state.owner.get() == ("session_fixture", None)
    with pytest.raises(StopIteration):
        fixture.send(None)
    assert state.owner.get() == ("item", identifier)
    report = plugin.pytest_runtest_makereport(item, None)
    next(report)
    with pytest.raises(StopIteration):
        report.send(SimpleNamespace(get_result=lambda: SimpleNamespace(failed=True, when=phase)))
    assert output == []
    with pytest.raises(StopIteration):
        protocol.send(None)
    assert len(output) == 1 and output[0][0:2] == (identifier, [phase])
    assert state.owner.get() == ("unknown", None)
    assert "private" not in identifier


def test_unavailable_pool_and_attachment_cannot_change_original_result(monkeypatch):
    provider_type, dependencies, _, _ = _backend()
    state = plugin.Capture()
    state.install(provider_type, dependencies)
    try:
        token = state.owner.set(("item", "owned"))
        provider = provider_type("unchanged")
        state.owner.reset(token)
        provider._relay_engine.pool.checkedout = lambda: (_ for _ in ()).throw(OSError())
        assert state.boundary("owned")["owned_pool_checkouts"] == [None]
        provider._relay_engine.pool.checkedout = lambda: "private/path/payload"
        assert state.boundary("owned")["owned_pool_checkouts"] == [None]
        monkeypatch.setattr(state, "attach", lambda *a: (_ for _ in ()).throw(OSError()))
        assert isinstance(provider_type("unchanged"), provider_type)
    finally:
        state.close()


def test_hosted_default_capture_xdist_reports_setup_and_call_after_teardown(tmp_path):
    child = tmp_path / "test_capture_child.py"
    child.write_text('''import pytest
from scripts import pytest_relay_capture as plugin

@pytest.fixture
def broken_setup():
    plugin._capture.record(plugin._capture.owner.get(), "setup_marker")
    raise AssertionError("controlled setup failure")

def test_setup(broken_setup):
    pass

def test_call():
    plugin._capture.record(plugin._capture.owner.get(), "call_marker")
    raise AssertionError("controlled call failure")
''', encoding="utf-8")
    environment = dict(os.environ)
    root = str(Path(__file__).resolve().parents[1])
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [environment.get("PYTHONPATH"), root]))
    result = subprocess.run([
        sys.executable, "-m", "pytest", "-q", "-n", "2", "-p", "scripts.pytest_relay_capture",
        "-o", "addopts=", "--confcutdir=" + str(tmp_path), "--rootdir=" + str(tmp_path), str(child),
    ], cwd=tmp_path, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 1, result.stdout + result.stderr
    captures = [json.loads(line.split("=", 1)[1]) for line in result.stdout.splitlines()
                if line.startswith("relay-hosted-capture=")]
    assert len(captures) == 2, result.stdout + result.stderr
    assert sorted(row["failed_phases"] for row in captures) == [["call"], ["setup"]]
    assert all("before" in row and "after" in row for row in captures)
    assert {event["stage"] for row in captures for event in row["tail"]} >= {"setup_marker", "call_marker"}
