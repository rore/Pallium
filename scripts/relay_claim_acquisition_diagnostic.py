"""Temporary, opt-in pytest observer; never import from production code.

Only the selected real claim is observed. Times include observer overhead;
low thread CPU cannot distinguish native I/O from descheduling. No SQL or
exception text is collected. Public listeners remain on the owned engine.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
import threading
import time

import pytest

TARGET = "tests/test_codex_wake_sqlite.py::test_http_claim_correlation_uses_fresh_identity_and_preserves_authority[outcome]"
EXPECTED_SQLALCHEMY = "2.1.5"
LIMIT = 256
MAX_NUMBER = 3_600_000_000_000


class Recorder:
    def __init__(self):
        self.events = []
        self.issues = set()
        self.pending = {}
        self.thread = None
        self.attempt = 0
        self.requests = 0
        self.dropped = 0
        self.observed = False
        self.failed = False
        self.wall = time.monotonic_ns()
        self.cpu = 0

    def active(self):
        return self.thread == threading.get_ident()

    def record(self, phase, state, **numbers):
        if not self.active():
            return
        try:
            if len(self.events) >= LIMIT:
                self.dropped = min(self.dropped + 1, MAX_NUMBER)
                self.issues.add("overflow")
                return
            values = {"wall_ns": time.monotonic_ns() - self.wall,
                      "cpu_ns": time.thread_time_ns() - self.cpu,
                      "attempt": self.attempt, **numbers}
            if any(type(v) is not int or abs(v) > MAX_NUMBER for v in values.values()):
                self.issues.add("numeric_metadata")
                return
            self.events.append({"phase": phase, "state": state, **values})
            if state == 0:
                self.pending[phase] = self.pending.get(phase, 0) + 1
            elif state in (1, 2):
                if not self.pending.get(phase):
                    self.issues.add("unmatched_phase")
                else:
                    self.pending[phase] -= 1
        except BaseException:
            self.issues.add("observer_fault")

    def call(self, phase, delegate, *args, **kwargs):
        if not self.active():
            return delegate(*args, **kwargs)
        self.record(phase, 0)
        try:
            result = delegate(*args, **kwargs)
        except BaseException as exc:
            try:
                code, code_state = sqlite_code(exc)
                if code_state == 2:
                    self.issues.add("invalid_error_code")
            except BaseException:
                self.issues.add("observer_fault")
                code, code_state = -1, 3
            self.record(phase, 2, sqlite_code=code, code_state=code_state)
            raise
        self.record(phase, 1)
        return result

    def patch(self, stack, obj, name, value):
        own = name in vars(obj)
        original = getattr(obj, name)
        setattr(obj, name, value)

        def restore():
            try:
                if own:
                    setattr(obj, name, original)
                else:
                    delattr(obj, name)
            except BaseException:
                self.issues.add("restore_fault")
        stack.callback(restore)

    def payload(self):
        issues = set(self.issues)
        if any(self.pending.values()):
            issues.add("missing_phase")
        if not self.observed:
            issues.add("claim_not_observed")
        else:
            def seen(phase, state=None, attempt=None):
                return any(e["phase"] == phase and (state is None or e["state"] == state)
                           and (attempt is None or e["attempt"] == attempt) for e in self.events)
            if not all(seen(p) for p in ("turn", "turn_delegate", "gate")):
                issues.add("required_phase_missing")
            acquired = any(e["phase"] == "gate_result" and e.get("acquired") == 1
                           for e in self.events)
            if seen("gate", 1) and not seen("gate_result"):
                issues.add("required_phase_missing")
            if acquired and not seen("factory", 0):
                issues.add("required_phase_missing")
            for attempt in {e["attempt"] for e in self.events if e["phase"] == "factory"}:
                if not seen("budget", attempt=attempt):
                    issues.add("required_phase_missing")
                if seen("factory", 1, attempt) and not all(
                        seen(p, attempt=attempt) for p in ("connection", "session_close")):
                    issues.add("required_phase_missing")
                if seen("connection", 1, attempt) and not all(
                        seen(p, attempt=attempt) for p in ("pool_queue", "checkout", "reset", "checkin")):
                    issues.add("required_phase_missing")
                if seen("creator", 1, attempt) and not seen("connect_listeners", 1, attempt):
                    issues.add("required_phase_missing")
        result = {"schema": 1, "failed": self.failed, "complete": not issues,
                  "issues": sorted(issues), "dropped": self.dropped,
                  "requests": self.requests, "observer_inclusive": True}
        if self.failed:
            result["events"] = self.events
        return result


def sqlite_code(exc):
    original = getattr(exc, "orig", exc)
    if isinstance(original, sqlite3.Error):
        value = getattr(original, "sqlite_errorcode", None)
        if value is None:
            return -1, 0
        if type(value) is int and 0 <= value <= 0x7FFFFFFF:
            return value, 1
        return -1, 2
    return -1, 0


def install(recorder, stack, storage):
    """Patch only this fixture's provider/engine; never SQLAlchemy classes."""
    from sqlalchemy import event

    engine = storage._relay_engine
    pool = engine.pool
    if (importlib.metadata.version("sqlalchemy") != EXPECTED_SQLALCHEMY
            or type(pool).__module__ != "sqlalchemy.pool.impl"
            or type(pool).__name__ != "QueuePool"):
        recorder.issues.add("unsupported_runtime")
        return

    # Install while the engine is idle, before the original test runs. Do not
    # remove listeners during dispatch; the fixture owns engine disposal.
    for phase, event_name in (("connect_listeners", "connect"), ("checkout", "checkout")):
        def before(*_args, _phase=phase):
            recorder.record(_phase, 0)
        def after(*_args, _phase=phase):
            recorder.record(_phase, 1)
        event.listen(engine, event_name, before, insert=True)
        event.listen(engine, event_name, after)
    for name in ("reset", "checkin"):
        def milestone(*_args, _name=name):
            recorder.record(_name, 3)
        event.listen(engine, name, milestone)

    original_turn = storage.relay_turn

    def turn(*args, **kwargs):
        if not kwargs.get("exact_delivery_id"):
            return original_turn(*args, **kwargs)
        recorder.requests += 1
        if recorder.requests != 1:
            recorder.issues.add("multiple_claims")
            return original_turn(*args, **kwargs)
        recorder.thread = threading.get_ident()
        recorder.cpu = time.thread_time_ns()
        recorder.wall = time.monotonic_ns()
        recorder.observed = True
        recorder.record("turn", 0)
        with ExitStack() as patches:
            try:
                instrument(recorder, patches, storage, pool)
            except BaseException:
                recorder.issues.add("installation_fault")
                patches.close()
            try:
                return recorder.call("turn_delegate", original_turn, *args, **kwargs)
            finally:
                recorder.record("turn", 1)
                recorder.thread = None
    recorder.patch(stack, storage, "relay_turn", turn)


def instrument(recorder, stack, storage, pool):
    native_lock = storage._relay_writer_lock

    class Lock:
        def acquire(self, *args, **kwargs):
            try:
                timeout = kwargs.get("timeout", args[1] if len(args) > 1 else -1)
                recorder.record("gate_timeout", 3, timeout_ms=int(timeout * 1000))
            except BaseException:
                recorder.issues.add("observer_fault")
            result = recorder.call("gate", native_lock.acquire, *args, **kwargs)
            recorder.record("gate_result", 3, acquired=int(result))
            return result
        def release(self):
            return recorder.call("gate_release", native_lock.release)
        def locked(self):
            return native_lock.locked()
    recorder.patch(stack, storage, "_relay_writer_lock", Lock())

    native_get = pool._pool.get
    def get(*args, **kwargs):
        try:
            block = kwargs.get("block", args[0] if args else True)
            # Unlocked approximate snapshots, not locking qsize/checkedout.
            recorder.record("approximate_pool_snapshot", 3, blocking=int(block),
                            idle=len(pool._pool.queue), overflow=pool._overflow)
        except BaseException:
            recorder.issues.add("observer_fault")
        return recorder.call("pool_queue", native_get, *args, **kwargs)
    recorder.patch(stack, pool._pool, "get", get)
    creator = pool._invoke_creator
    recorder.patch(stack, pool, "_invoke_creator",
                   lambda *a, **kw: recorder.call("creator", creator, *a, **kw))

    native_factory = storage._relay_session_factory
    def factory(*args, **kwargs):
        if not recorder.active():
            return native_factory(*args, **kwargs)
        recorder.attempt += 1
        frame = None
        try:
            frame = sys._getframe(1)
            from storage.sqlite_queue import SQLiteQueueMixin
            if frame.f_code is SQLiteQueueMixin._begin_immediate_for.__wrapped__.__code__:
                deadline = frame.f_locals.get("acquisition_deadline")
                attempt = frame.f_locals.get("attempt")
                if type(deadline) is float and type(attempt) is int:
                    recorder.record("budget", 3, source_attempt=attempt,
                                    remaining_ns=int(deadline * 1_000_000_000) - time.monotonic_ns())
                else:
                    recorder.issues.add("missing_budget")
            else:
                recorder.issues.add("unknown_factory_caller")
        except BaseException:
            recorder.issues.add("observer_fault")
        finally:
            del frame
        session = recorder.call("factory", native_factory, *args, **kwargs)
        try:
            connection = session.connection
            close = session.close
            recorder.patch(stack, session, "connection",
                           lambda *a, **kw: recorder.call("connection", connection, *a, **kw))
            recorder.patch(stack, session, "close",
                           lambda *a, **kw: recorder.call("session_close", close, *a, **kw))
        except BaseException:
            recorder.issues.add("observer_fault")
        return session
    recorder.patch(stack, storage, "_relay_session_factory", factory)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    if item.nodeid != TARGET:
        yield
        return
    recorder = Recorder()
    item._claim_acquisition_recorder = recorder
    with ExitStack() as stack:
        try:
            install(recorder, stack, item.funcargs["relay_store"][1])
        except BaseException:
            recorder.issues.add("installation_fault")
            stack.close()
        yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if item.nodeid != TARGET:
        return
    report = outcome.get_result()
    recorder = getattr(item, "_claim_acquisition_recorder", None)
    if recorder is None:
        recorder = Recorder()
        item._claim_acquisition_recorder = recorder
    recorder.failed |= report.failed
    if report.failed or report.when == "teardown":
        directory = os.environ.get("PALLIUM_CLAIM_DIAGNOSTIC_DIR")
        if directory:
            try:
                path = Path(directory)
                path.mkdir(parents=True, exist_ok=True)
                (path / f"claim-{os.getpid()}.json").write_text(
                    json.dumps(recorder.payload(), sort_keys=True), encoding="utf-8")
            except BaseException:
                recorder.issues.add("sink_fault")


def runtime_receipt():
    return {"python": platform.python_version(), "platform": sys.platform,
            "sqlite": sqlite3.sqlite_version, "expected_sqlalchemy": EXPECTED_SQLALCHEMY,
            "distributions": sorted((d.metadata["Name"], d.version)
                                    for d in importlib.metadata.distributions()),
            "source": {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (
                "storage/sqlite.py", "storage/sqlite_queue.py", "storage/sqlite_relay.py",
                "tests/test_codex_wake_sqlite.py", "scripts/relay_claim_acquisition_diagnostic.py")}}


def evidence_status(directory):
    """Missing/sink-failed capture cannot look complete because runtime exists."""
    files = list(directory.glob("claim-*.json"))
    result = {"target_reports": len(files), "complete": False, "issues": ["missing_or_multiple_reports"]}
    if len(files) == 1:
        try:
            if files[0].stat().st_size > 1_000_000:
                raise ValueError
            claim = json.loads(files[0].read_text(encoding="utf-8"))
            result.update(complete=claim["complete"] is True, failed=claim["failed"] is True,
                          issues=claim["issues"])
        except Exception:
            result["issues"] = ["unreadable_report"]
    try:
        runtime_path = directory / "runtime.json"
        if runtime_path.stat().st_size > 1_000_000:
            raise ValueError
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        if (not all(type(runtime.get(k)) is str and runtime[k]
                    for k in ("python", "platform", "sqlite"))
                or runtime.get("expected_sqlalchemy") != EXPECTED_SQLALCHEMY
                or not isinstance(runtime.get("source"), dict) or not runtime["source"]
                or not isinstance(runtime.get("distributions"), list) or not runtime["distributions"]):
            raise ValueError
    except Exception:
        result["complete"] = False
        result["issues"] = [*result["issues"], "missing_or_malformed_runtime"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "evidence-status.json").write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    return result["complete"]


if __name__ == "__main__":
    if sys.argv[1] == "--status":
        raise SystemExit(0 if evidence_status(Path(sys.argv[2])) else 1)
    else:
        destination = Path(sys.argv[1])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(runtime_receipt(), sort_keys=True), encoding="utf-8")
