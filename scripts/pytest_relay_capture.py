"""Temporary opt-in failure capture: pytest -p scripts.pytest_relay_capture.

Observations include their own overhead; CPU intervals compare one thread only.
No captured value participates in application admission or deadline decisions.
"""
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import re
import threading
import time
import weakref

import pytest


def _item_id(nodeid):
    return hashlib.sha256(nodeid.encode("utf-8")).hexdigest()[:16]


class Capture:
    def __init__(self):
        self.owner = ContextVar("relay_capture_owner", default=("unknown", None))
        self.operation = ContextVar("relay_capture_operation", default=None)
        self.lock = threading.Lock()
        self.tail, self.failures = deque(maxlen=128), deque(maxlen=16)
        self.dropped = self.failure_dropped = self.sequence = 0
        self.providers = weakref.WeakKeyDictionary()
        self.original_factories = weakref.WeakKeyDictionary()
        self.bundles = deque(maxlen=16)
        self.bundle_dropped = 0
        self.restore = []
        self.closed = False

    def record(self, owner, stage, error=None):
        try:
            if self.closed:
                return
            row = {"owner_scope": owner[0], "owner_item": owner[1], "stage": stage,
                   "operation": self.operation.get(), "thread": threading.get_ident(),
                   "wall_ns": time.monotonic_ns(), "thread_cpu_ns": time.thread_time_ns()}
            if error is not None:
                from core.errors import ImmediateTransactionBusyError
                label = getattr(error, "acquisition_stage", None)
                row["acquisition_stage"] = (label if type(label) is str and
                    label in ImmediateTransactionBusyError.ACQUISITION_STAGES else "unknown")
                row["error_type"] = type(error).__name__[:64]
                chain, seen = [], set()
                cursor = error
                while cursor is not None and id(cursor) not in seen and len(chain) < 6:
                    seen.add(id(cursor))
                    native = getattr(cursor, "orig", cursor)
                    code = getattr(native, "sqlite_errorcode", None)
                    name = getattr(native, "sqlite_errorname", None)
                    chain.append({"type": type(cursor).__name__[:64],
                                  "sqlite_code": code if type(code) is int else None,
                                  "sqlite_name": name if type(name) is str and
                                  re.fullmatch(r"SQLITE_[A-Z0-9_]+", name) else None})
                    cursor = cursor.__cause__ or cursor.__context__
                row["causes"] = chain
            with self.lock:
                if len(self.tail) == self.tail.maxlen:
                    self.dropped += 1
                self.tail.append(row)
                if error is not None:
                    if len(self.failures) == self.failures.maxlen:
                        self.failure_dropped += 1
                    self.failures.append(dict(row))
        except Exception:
            pass  # Diagnostic failure must not change the original operation.

    def provider_owner(self, provider):
        try:
            with self.lock:
                return self.providers.get(provider, ("unknown", None))
        except Exception:
            return ("unknown", None)

    def attach(self, provider):
        owner = self.owner.get()
        with self.lock:
            self.providers[provider] = owner
        factory = provider._relay_session_factory

        def observed_factory(*args, **kwargs):
            self.record(owner, "factory_entered")
            try:
                session = factory(*args, **kwargs)
            except BaseException as error:
                self.record(owner, "factory_error", error)
                raise
            finally:
                self.record(owner, "factory_settled")
            try:
                connection = session.connection

                def observed_connection(*args, **kwargs):
                    self.record(owner, "connection_entered")
                    try:
                        return connection(*args, **kwargs)
                    except BaseException as error:
                        self.record(owner, "connection_error", error)
                        raise
                    finally:
                        self.record(owner, "connection_settled")
                session.connection = observed_connection
            except Exception:
                pass
            return session
        provider._relay_session_factory = observed_factory
        with self.lock:
            self.original_factories[provider] = factory

    def install(self, provider_type, dependencies):
        def replace(target, name, value):
            old = vars(target).get(name, _MISSING)
            self.restore.append((lambda: target, name, old))
            setattr(target, name, value)

        original_init = provider_type.__init__

        def initialize(provider, *args, **kwargs):
            original_init(provider, *args, **kwargs)
            try:
                self.attach(provider)
            except Exception:
                pass
        replace(provider_type, "__init__", initialize)

        def wrap_begin(delegate, stage):
            @contextmanager
            def begin(provider, *args, **kwargs):
                owner = self.provider_owner(provider)
                self.record(owner, stage + "_entered")
                try:
                    with delegate(provider, *args, **kwargs) as session:
                        self.record(owner, stage + "_acquired")
                        yield session
                except BaseException as error:
                    self.record(owner, stage + "_error", error)
                    raise
                finally:
                    self.record(owner, stage + "_settled")
            return begin
        for name, stage in (("_begin_relay_immediate", "outer"), ("_begin_immediate_for", "inner")):
            replace(provider_type, name, wrap_begin(getattr(provider_type, name), stage))

        original_router = dependencies.create_router

        def router(*args, **kwargs):
            relay = kwargs.get("relay_service")
            try:
                provider = getattr(relay, "_store", None)
            except Exception:
                provider = None
            owner = self.provider_owner(provider) if provider is not None else ("unknown", None)

            def wrap_runner(delegate):
                async def run(operation):
                    with self.lock:
                        self.sequence += 1
                        sequence = self.sequence
                    token = self.operation.set(sequence)
                    self.record(owner, "runner_submitted")
                    self.operation.reset(token)

                    def work():
                        token = self.operation.set(sequence)
                        self.record(owner, "worker_entered")
                        try:
                            return operation()
                        except BaseException as error:
                            self.record(owner, "worker_error", error)
                            raise
                        finally:
                            self.record(owner, "worker_settled")
                            self.operation.reset(token)
                    return await delegate(work)
                return run
            for key in ("relay_runner", "relay_codex_runner"):
                if kwargs.get(key) is not None:
                    kwargs[key] = wrap_runner(kwargs[key])
            return original_router(*args, **kwargs)
        replace(dependencies, "create_router", router)

    def boundary(self, item):
        try:
            threads = [thread.ident for thread in threading.enumerate() if thread.is_alive()]
            with self.lock:
                providers = list(self.providers.items())
        except Exception:
            return {"unavailable": True}
        pools = []
        for provider, owner in providers:
            if owner == ("item", item):
                try:
                    count = getattr(provider._relay_engine.pool, "checkedout", None)
                    value = count() if callable(count) else None
                    pools.append(value if type(value) is int else None)
                except Exception:
                    pools.append(None)
        return {"thread_count": len(threads), "thread_ids": threads[:64],
                "thread_ids_truncated": len(threads) > 64, "owned_pool_checkouts": pools[:32],
                "owned_pool_count": len(pools)}

    def emit(self, item, phases, before, after):
        try:
            with self.lock:
                data = {"item": item, "failed_phases": phases,
                        "tail": list(self.tail), "dropped": self.dropped,
                        "failures": list(self.failures), "failure_dropped": self.failure_dropped,
                        "before": before, "after": after}
                if len(self.bundles) == self.bundles.maxlen:
                    self.bundle_dropped += 1
                self.bundles.append(data)
        except Exception:
            pass

    def close(self):
        self.closed = True
        for provider, factory in list(self.original_factories.items()):
            provider._relay_session_factory = factory
        self.original_factories.clear()
        for reference, name, old in reversed(self.restore):
            target = reference()
            if target is not None:
                if old is _MISSING:
                    delattr(target, name)
                else:
                    setattr(target, name, old)
        self.restore.clear()


_MISSING = object()
_capture = None
_phases = {}
_worker_bundles = []


def pytest_configure(config):
    global _capture
    from app import dependencies
    from storage.sqlite import SQLiteStorageProvider
    _capture = Capture()
    _capture.install(SQLiteStorageProvider, dependencies)


def pytest_unconfigure(config):
    global _capture
    if _capture is not None:
        _capture.close()
        _capture = None
    _phases.clear()
    _worker_bundles.clear()


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    owner = (("item", _item_id(request.node.nodeid)) if request.scope == "function"
             else (request.scope + "_fixture", None))
    token = _capture.owner.set(owner)
    try:
        yield
    finally:
        _capture.owner.reset(token)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    identifier = _item_id(item.nodeid)
    token = _capture.owner.set(("item", identifier))
    before = _capture.boundary(identifier)
    try:
        yield
    finally:
        _capture.owner.reset(token)
        phases = _phases.pop(identifier, [])
        if phases:
            _capture.emit(identifier, phases, before, _capture.boundary(identifier))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.failed:
        _phases.setdefault(_item_id(item.nodeid), []).append(report.when)


def pytest_sessionfinish(session, exitstatus):
    if hasattr(session.config, "workeroutput"):
        session.config.workeroutput["relay_hosted_capture"] = {
            "bundles": list(_capture.bundles), "dropped": _capture.bundle_dropped}


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):
    try:
        data = node.workeroutput.get("relay_hosted_capture", {})
        if data.get("bundles"):
            _worker_bundles.append(data)
    except Exception:
        pass


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if hasattr(config, "workeroutput"):
        return
    data = _worker_bundles or [{"bundles": list(_capture.bundles),
                               "dropped": _capture.bundle_dropped}]
    for worker in data:
        for bundle in worker["bundles"]:
            try:
                terminalreporter.write_line("relay-hosted-capture=" + json.dumps(bundle))
            except Exception:
                pass
        if worker.get("dropped"):
            try:
                terminalreporter.write_line("relay-hosted-capture-dropped=" + str(worker["dropped"]))
            except Exception:
                pass
