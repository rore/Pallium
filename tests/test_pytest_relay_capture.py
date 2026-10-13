"""Transparency checks for the temporary, explicitly loaded hosted capture."""
import asyncio
from contextlib import contextmanager
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
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


def test_real_sessionmaker_api_preserves_commit_rollback_and_configuration(tmp_path):
    from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, select
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///" + str(tmp_path / "factory.db"))
    metadata = MetaData()
    rows = Table("entries", metadata, Column("id", Integer, primary_key=True), Column("value", String))
    metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    class Provider:
        _relay_session_factory = factory
        _relay_engine = engine

    provider, state = Provider(), plugin.Capture()
    try:
        state.attach(provider)
        observed = provider._relay_session_factory
        assert observed.kw is factory.kw and observed.class_ is factory.class_
        observed.configure(info={"configured": True})
        assert factory.kw["info"] == {"configured": True}
        with observed.begin() as session:
            session.execute(rows.insert().values(id=1, value="café 東京"))
        failure = RuntimeError("controlled rollback")
        with pytest.raises(RuntimeError) as caught:
            with observed.begin() as session:
                session.execute(rows.insert().values(id=2, value="rolled back"))
                raise failure
        assert caught.value is failure
        assert list(state.tail) == []  # Direct .begin() is the unchanged original path.
        with observed(info={"per_call": True}) as session:
            assert session.info == {"configured": True, "per_call": True}
            assert session.execute(select(rows).order_by(rows.c.id)).all() == [(1, "café 東京")]
        assert [record["stage"] for record in state.tail] == ["factory_entered", "factory_settled"]
    finally:
        state.close()
        engine.dispose()
    assert provider._relay_session_factory is factory


def _native_capture(tmp_path, session_type=None):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session, sessionmaker
    from storage.sqlite_queue import SQLiteQueueMixin

    engine = create_engine("sqlite:///" + str(tmp_path / "holder.db"))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE entries (id INTEGER PRIMARY KEY, value TEXT)"))

    class Provider(SQLiteQueueMixin):
        def __init__(self):
            self._relay_engine = engine
            self._relay_session_factory = sessionmaker(engine, class_=session_type or Session)
            self._relay_writer_lock = threading.Lock()

    state = plugin.Capture()
    state.install(Provider, SimpleNamespace(create_router=lambda *a, **k: k))
    return state, Provider(), engine


@pytest.mark.parametrize("rollback", [False, True])
def test_native_first_write_ends_only_after_commit_or_rollback(tmp_path, rollback):
    from sqlalchemy import text
    state, provider, engine = _native_capture(tmp_path)
    failure = RuntimeError("controlled body rollback")
    try:
        try:
            with provider._begin_low_priority_relay_write() as session:
                session.connection().execute(text("SAVEPOINT before_write"))
                session.connection().execute(text("INSERT INTO entries VALUES (1, 'private-payload')"))
                session.connection().execute(text("ROLLBACK TO SAVEPOINT before_write"))
                assert len(state.active_holders) == 1  # Savepoint rollback does not release the writer.
                session.connection().execute(text("INSERT INTO entries VALUES (1, 'private-payload')"))
                assert len(state.active_holders) == 1
                state.record(state.provider_owner(provider), "acquisition_refusal", failure)
                assert len(state.failures[-1]["active_holders"]) == 1
                if rollback:
                    raise failure
        except RuntimeError as error:
            assert rollback and error is failure
        assert state.active_holders == {} and state.low_priority.get() is None
        stages = [row["stage"] for row in state.tail]
        assert "low_priority_first_write" in stages
        assert ("native_rollback_returned" if rollback else "native_commit_returned") in stages
        assert len(state.failures[-1]["active_holders"]) == 1  # Later cleanup cannot erase origin.
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM entries")).scalar_one() == int(not rollback)
        assert "private-payload" not in json.dumps(list(state.tail))
    finally:
        callback = state.listeners[0][1]
        state.listeners.insert(0, (lambda: object(), callback))  # A failed removal must not stop cleanup.
        state.close()
        from sqlalchemy import event
        assert not event.contains(engine, "after_cursor_execute", callback)
        engine.dispose()


@pytest.mark.parametrize("close_failure", [False, True])
def test_failed_native_commit_keeps_holder_until_actual_close(tmp_path, close_failure):
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    failure = RuntimeError("controlled close failure")

    class ClosingSession(Session):
        allow_close = not close_failure
        def close(self):
            if not self.allow_close:
                raise failure
            return super().close()

    state, provider, engine = _native_capture(tmp_path, ClosingSession)
    token = state.low_priority.set((provider._relay_capture_provider_id, state.provider_owner(provider)))
    session = provider._relay_session_factory()
    try:
        connection = session.connection(execution_options={"isolation_level": "AUTOCOMMIT"})
        connection.execute(text("BEGIN DEFERRED"))
        connection.execute(text("INSERT INTO entries VALUES (1, 'private-payload')"))
        with pytest.raises(OperationalError) as caught:
            connection.execute(text("COMMIT INVALID"))
        state.record(state.provider_owner(provider), "commit_refusal", caught.value)
        assert len(state.active_holders) == len(state.failures[-1]["active_holders"]) == 1
        assert "native_commit_returned" not in [row["stage"] for row in state.tail]
        if close_failure:
            with pytest.raises(RuntimeError) as caught:
                session.close()
            assert caught.value is failure and len(state.active_holders) == 1
        session.allow_close = True
        session.close()
        assert state.active_holders == {}
        assert "session_close_returned" in [row["stage"] for row in state.tail]
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as fresh:
            fresh.execute(text("BEGIN IMMEDIATE"))
            assert fresh.execute(text("SELECT count(*) FROM entries")).scalar_one() == 0
            fresh.execute(text("ROLLBACK"))
    finally:
        session.allow_close = True
        session.close()
        state.low_priority.reset(token)
        state.close()
        engine.dispose()


def test_live_holder_overflow_is_explicit_and_never_evicts_origin(tmp_path):
    state, provider, engine = _native_capture(tmp_path)
    token = state.low_priority.set((provider._relay_capture_provider_id, state.provider_owner(provider)))
    try:
        for identifier in range(16):
            state.active_holders[(0, identifier)] = {"connection": identifier}
        # One real successful DML cannot silently evict the sixteen existing identities.
        from sqlalchemy import text
        with provider._begin_low_priority_relay_write() as session:
            session.connection().execute(text("INSERT INTO entries VALUES (1, 'private-payload')"))
        state.record(state.provider_owner(provider), "refusal", RuntimeError())
        assert len(state.active_holders) == 16 and state.holder_overflow == 1
        assert state.failures[-1]["observed_low_priority_coverage_complete"] is False
        assert state.failures[-1]["holder_overflow"] == 1
    finally:
        state.low_priority.reset(token)
        state.close()
        engine.dispose()


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
