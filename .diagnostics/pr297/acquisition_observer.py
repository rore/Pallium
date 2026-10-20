"""Disposable fixture-owned observation; never changes acquisition policy."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
import sys
import time

import pytest
from sqlalchemy import event
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.orm import Session, sessionmaker

_DEFAULT_DO = DefaultDialect.do_execute
_SESSION_CONNECTION, _SESSION_CLOSE = Session.connection, Session.close
_WALL, _CPU = time.perf_counter_ns, time.thread_time_ns
_MONO, _MONO_NS = time.monotonic, time.monotonic_ns
_worker = os.environ.get("PYTEST_XDIST_WORKER", "controller")
_bindings, _counts, _gaps, _slow = {}, {}, [], []
_control = None
_serial = 0
_mutex, _local = threading.Lock(), threading.local()


def count(name):
    with _mutex:
        _counts[name] = _counts.get(name, 0) + 1


def gap(reason, owner=None):
    with _mutex:
        name = "gap:" + reason
        _counts[name] = _counts.get(name, 0) + 1
        if len(_gaps) < 128:
            _gaps.append(dict(reason=reason, fixture_owner=owner))


def stamp():
    return [_WALL(), _CPU()]


class Binding:
    def __init__(self, provider, owner):
        from storage import sqlite_queue
        global _serial
        _serial += 1
        self.identity, self.provider, self.owner = _serial, provider, owner
        self.engine = provider._relay_engine
        self.dialect = self.engine.dialect
        self.original_do = self.dialect.do_execute
        self.original_begin = provider._begin_relay_immediate
        self.original_for = provider._begin_immediate_for
        self.factory, self.lock = provider._relay_session_factory, provider._relay_writer_lock
        self.allowance = provider._RELAY_IMMEDIATE_ACQUISITION_SECONDS
        self.queue = sqlite_queue
        self.sequence = self.active = 0
        self.disposed = self.restored = False
        self.previous_present = "_begin_relay_immediate" in provider.__dict__
        self.previous_value = provider.__dict__.get("_begin_relay_immediate")
        self.listeners = []
        self.wrapper = self.begin

    def compatible(self):
        return (
            self.queue.time.monotonic is _MONO
            and self.queue._acquisition_monotonic_ns is _MONO_NS
            and self.provider._relay_engine is self.engine
            and self.provider._relay_writer_lock is self.lock
            and self.provider._RELAY_IMMEDIATE_ACQUISITION_SECONDS == self.allowance == 0.45
            and self.provider._relay_session_factory is self.factory
            and type(self.factory) is sessionmaker
            and self.factory.kw.get("bind") is self.engine
            and self.factory.class_.__bases__ == (Session,)
            and self.factory.class_.connection is _SESSION_CONNECTION
            and self.factory.class_.close is _SESSION_CLOSE
            and self.provider._begin_immediate_for == self.original_for
            and getattr(self.original_for, "__func__", None) is self.queue.SQLiteQueueMixin._begin_immediate_for
            and getattr(self.original_begin, "__func__", None) is self.queue.SQLiteQueueMixin._begin_relay_immediate
            and self.dialect.do_execute == self.original_do
            and getattr(self.dialect.do_execute, "__func__", None) is _DEFAULT_DO
            and not list(self.dialect.dispatch.do_execute_no_params)
            and list(self.dialect.dispatch.do_execute) == [self.execute]
        )

    def record(self, data, name, **values):
        try:
            if len(data["events"]) >= 32:
                data["dropped"] += 1
            else:
                data["events"].append(dict(name=name, stamp=stamp(), **values))
        except BaseException:
            data["dropped"] += 1

    def current(self):
        value = getattr(_local, "acquisition", None)
        return value if value is not None and value[0] is self else None

    def execute(self, cursor, statement, parameters, context):
        selected = self.current()
        if selected is None:
            return None
        data = selected[1]
        try:
            if context.root_connection.engine is not self.engine:
                return None
            if not self.compatible():
                data["incompatible_during_call"] = True
                return None
            normalized = statement.strip().upper()
            kind = normalized if normalized in {"BEGIN IMMEDIATE", "COMMIT", "ROLLBACK"} else None
            if normalized.startswith("PRAGMA BUSY_TIMEOUT=") and normalized.partition("=")[2].isdecimal():
                kind = normalized
            if kind is None:
                return None
            connection = id(context.root_connection.connection.dbapi_connection)
            before = stamp()
        except BaseException:
            data["dropped"] += 1
            return None
        try:
            self.original_do(cursor, statement, parameters, context)
        except BaseException as error:
            try:
                after = stamp()
                self.record(data, "driver_error", sql_kind=kind, before=before, after=after,
                            connection=connection, error_type=type(error).__name__)
            except BaseException:
                data["dropped"] += 1
            raise
        try:
            after = stamp()
            self.record(data, "driver_return", sql_kind=kind, before=before, after=after, connection=connection)
        except BaseException:
            data["dropped"] += 1
        return True  # SQLAlchemy contract: original execution occurred exactly once.

    def checkin(self, dbapi_connection, connection_record):
        selected = self.current()
        if selected is not None:
            self.record(selected[1], "pool_checkin", connection=id(dbapi_connection))

    @contextmanager
    def begin(self, *args, **kwargs):
        prior = getattr(_local, "acquisition", None)
        _local.acquisition = None
        data = None
        try:
            try:
                compatible = self.compatible()
            except BaseException:
                compatible = False
            if compatible:
                with _mutex:
                    self.sequence += 1
                    sequence = self.sequence
                    self.active += 1
                data = dict(worker=_worker, fixture_owner=self.owner, provider_lifetime=self.identity,
                            acquisition=sequence, thread=threading.get_ident(),
                            after_client_disposal=self.disposed, events=[], dropped=0, body=False)
                _local.acquisition = (self, data)
                self.record(data, "acquisition_enter")
            else:
                gap("incompatible_or_synthetic_acquisition", self.owner)
            try:
                with self.original_begin(*args, **kwargs) as session:
                    if data is not None:
                        data["body"] = True
                        self.record(data, "body_yield", session=id(session))
                    yield session
            except BaseException as error:
                if data is not None:
                    try:
                        from core.errors import ImmediateTransactionBusyError
                        stage = getattr(error, "acquisition_stage", None)
                        data["typed_refusal"] = (not data["body"] and isinstance(error, ImmediateTransactionBusyError)
                                                   and stage in ImmediateTransactionBusyError.ACQUISITION_STAGES)
                        phases = getattr(error, "acquisition_phase_ms", None)
                        safe = {key: value for key, value in phases.items()
                                if key in {"session_factory", "session_connection", "setup_pragma", "begin_immediate"}
                                and type(value) is int and 0 <= value < 10**9} if isinstance(phases, dict) else None
                        self.record(data, "acquisition_error", error_type=type(error).__name__,
                                    stage=stage if data["typed_refusal"] else None, phases=safe)
                    except BaseException:
                        data["dropped"] += 1
                raise
            else:
                if data is not None:
                    data["success"] = True
        finally:
            if data is not None:
                try:
                    self.record(data, "acquisition_exit", writer_locked=self.lock.locked())
                    self.retain(data)
                except BaseException:
                    gap("observer_finalization_error", self.owner)
                with _mutex:
                    self.active -= 1
            _local.acquisition = prior

    def retain(self, data):
        global _control
        events = data["events"]
        boundary = next((e for e in events if e["name"] in {"body_yield", "acquisition_error"}), None)
        elapsed = None if not events or boundary is None else boundary["stamp"][0] - events[0]["stamp"][0]
        data["prebody_ns"] = elapsed
        with _mutex:
            _counts["observed"] = _counts.get("observed", 0) + 1
            if data["dropped"] or elapsed is None or elapsed < 0 or data.get("incompatible_during_call"):
                _counts["incomplete_acquisitions"] = _counts.get("incomplete_acquisitions", 0) + 1
            if data.get("typed_refusal") or (elapsed is not None and elapsed >= 450_000_000):
                if len(_slow) < 128:
                    _slow.append(data)
                else:
                    _counts["slow_buffer_overflow"] = _counts.get("slow_buffer_overflow", 0) + 1
            elif data.get("success") and _control is None:
                _control = data
            else:
                _counts["intentionally_discarded_fast"] = _counts.get("intentionally_discarded_fast", 0) + 1

    def install(self):
        # Recovery is registered before any private mutation.
        for target, name, callback in ((self.dialect, "do_execute", self.execute), (self.engine.pool, "checkin", self.checkin)):
            event.listen(target, name, callback)
            self.listeners.append((target, name, callback))
        self.provider._begin_relay_immediate = self.wrapper

    def restore(self):
        if self.restored:
            return True
        if self.active:
            gap("active_acquisition_at_restore", self.owner)
            return False
        try:
            if self.provider.__dict__.get("_begin_relay_immediate") is not self.wrapper:
                gap("instance_wrapper_changed", self.owner)
            elif self.previous_present:
                self.provider._begin_relay_immediate = self.previous_value
            else:
                del self.provider._begin_relay_immediate
        except BaseException:
            gap("wrapper_restoration_error", self.owner)
        for target, name, callback in reversed(self.listeners):
            try:
                if event.contains(target, name, callback):
                    event.remove(target, name, callback)
            except BaseException:
                gap("listener_restoration_error", self.owner)
        self.restored = True
        count("bindings_restored")
        return True


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_fixture_setup(fixturedef, request):
    outcome = yield
    if fixturedef.argname != "client" or outcome.excinfo is not None:
        return
    owner = request.node.nodeid
    try:
        expected = Path(request.config.rootpath) / "tests" / "conftest.py"
        if fixturedef.scope != "function" or Path(fixturedef.func.__code__.co_filename).resolve() != expected.resolve():
            gap("unregistered_client_fixture", owner)
            return
        provider = outcome.get_result().app.state.pallium_service._storage
        from storage.sqlite import SQLiteStorageProvider
        if type(provider) is not SQLiteStorageProvider:
            gap("non_native_client_provider", owner)
            return
        engine = provider._relay_engine
        database = Path(engine.url.database).resolve()
        base = request.config._tmp_path_factory.getbasetemp().resolve()
        if not database.is_relative_to(base) or not database.is_file():
            gap("unproven_fixture_database", owner)
            return
        dialect = engine.dialect
        if (dialect.name != "sqlite" or dialect.driver != "pysqlite"
                or getattr(dialect.do_execute, "__func__", None) is not _DEFAULT_DO
                or list(dialect.dispatch.do_execute) or list(dialect.dispatch.do_execute_no_params)):
            gap("incompatible_fixture_dialect", owner)
            return
        binding = Binding(provider, owner)
        _bindings.setdefault(owner, []).append(binding)
        binding.install()
        count("bindings_registered")
    except BaseException:
        gap("fixture_registration_error", owner)


def pytest_fixture_post_finalizer(fixturedef, request):
    if fixturedef.argname == "client":
        for binding in _bindings.get(request.node.nodeid, []):
            binding.disposed = True


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    try:
        yield
    finally:
        # Original client disposal and monkeypatch undo precede restoration.
        remaining = [b for b in _bindings.get(item.nodeid, []) if not b.restore()]
        if remaining:
            _bindings[item.nodeid] = remaining
        else:
            _bindings.pop(item.nodeid, None)


def pytest_sessionfinish(session, exitstatus):
    for bindings in list(_bindings.values()):
        for binding in bindings:
            binding.restore()
    if _worker == "controller":
        return
    report = dict(worker=_worker, pid=os.getpid(), pytest_exitstatus=int(exitstatus),
                  counts=_counts, gaps=_gaps, slow=_slow, control=_control,
                  remaining_active=sum(b.active for values in _bindings.values() for b in values),
                  coverage="Only native function-scoped tests/conftest.py client provider acquisitions after fixture yield; auxiliary, construction, session-shared and subprocess providers are unobserved.",
                  limitations="Fixture owner is resource ownership, not background request origin. Driver brackets include observer/Python/scheduling. Session.close is not wrapped; pool checkin and lock snapshots do not prove physical I/O cause. Synthetic/incompatible calls delegate unchanged; fast records are intentionally discarded.")
    destination = Path(os.environ["PALLIUM_DIAGNOSTIC_OUTPUT"]) / ("worker-" + _worker + ".json")
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")



def pytest_sessionstart(session):
    guard = sys.modules.get("sitecustomize")
    expected = Path(__file__).resolve().parent / "guard" / "sitecustomize.py"
    assert guard is not None and Path(guard.__file__).resolve() == expected, "Private guard did not load"
