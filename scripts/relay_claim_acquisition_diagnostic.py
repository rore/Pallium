"""Temporary, opt-in pytest observer; never import from production code.

Only two original delayed-HTTP rows are observed. Times include observer overhead;
low thread CPU cannot distinguish native I/O from descheduling. No SQL or
exception text is collected. Public listeners remain on the owned engine.
Cursor timings exclude fetching/materialization; unmeasured body time can
include ORM/fetch/Python work, waits or descheduling.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
import importlib.metadata
from itertools import count
import json
import math
import os
from pathlib import Path
import platform
import sqlite3
import sys
import threading
import time

import pytest

TARGET = "tests/test_agent_relay_hooks.py::test_codex_exact_wake_real_http_response_delay_is_bounded_and_traceable[2.2-False-claimed-False-False]"
TARGETS = {
    TARGET: 2,
    TARGET.replace("[2.2-False-claimed-False-False]", "[1.15-False-delivered-True-False]"): 1,
}
EXPECTED_SQLALCHEMY = "2.1.5"
LIMIT = 256
TURN_LIMIT = 3  # Two setup POSTs, then one exact hook claim in either selected row.
MAX_NUMBER = 3_600_000_000_000
RESOURCE_PHASES = {"turn", "gate", "factory", "connection", "creator", "body", "flush", "session_close"}


def numeric_file(path, limit=128):
    with open(path, "r", encoding="ascii") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError
    return value.split()


class NativeResources:
    """Read native counters; never enable kernel accounting or change affinity."""
    def __init__(self):
        self.metadata = {"rusage_supported": 0, "schedstat_supported": 0,
                         "schedstat_enabled": 0, "affinity_supported": 0,
                         "quota_supported": 0}
        self.resource = None
        if sys.platform != "linux":
            return
        try:
            import resource
            resource.getrusage(resource.RUSAGE_THREAD)
            self.resource = resource
            self.metadata["rusage_supported"] = 1
        except Exception:
            pass
        try:
            enabled, = numeric_file("/proc/sys/kernel/sched_schedstats", 8)
            self.metadata["schedstat_enabled"] = int(enabled == "1")
            values = numeric_file("/proc/thread-self/schedstat")
            if len(values) != 3 or any(not v.isdecimal() for v in values):
                raise ValueError
            self.metadata["schedstat_supported"] = int(enabled == "1")
        except Exception:
            pass
        try:
            self.metadata.update(affinity_supported=1, affinity_count=len(os.sched_getaffinity(0)))
        except Exception:
            pass
        try:
            quota, period = numeric_file("/sys/fs/cgroup/cpu.max", 64)
            if not period.isdecimal() or int(period) <= 0 or not (quota == "max" or quota.isdecimal()):
                raise ValueError
            self.metadata.update(quota_supported=1, quota_us=-1 if quota == "max" else int(quota),
                                 quota_period_us=int(period))
            if any(type(v) is not int or abs(v) > MAX_NUMBER for v in self.metadata.values()):
                self.metadata.pop("quota_us", None)
                self.metadata.pop("quota_period_us", None)
                self.metadata["quota_supported"] = 0
        except Exception:
            pass

    def snapshot(self):
        values = {}
        if self.metadata["rusage_supported"]:
            usage = self.resource.getrusage(self.resource.RUSAGE_THREAD)
            for key in ("utime", "stime"):
                value = getattr(usage, "ru_" + key)
                if not math.isfinite(value) or value < 0:
                    raise ValueError
                values[key + "_ns"] = int(value * 1_000_000_000)
            for key in ("minflt", "majflt", "inblock", "oublock", "nvcsw", "nivcsw"):
                value = getattr(usage, "ru_" + key)
                if type(value) is not int or value < 0:
                    raise ValueError
                values[key] = value
        if self.metadata["schedstat_supported"]:
            raw = numeric_file("/proc/thread-self/schedstat")
            if len(raw) != 3 or any(not v.isdecimal() for v in raw):
                raise ValueError
            values.update(zip(("scheduled_ns", "runqueue_ns", "timeslices"), map(int, raw)))
        return values


class Recorder:
    def __init__(self, resources=None, wall=None):
        self.events = []
        self.issues = set()
        self.pending = {}
        self.thread = None
        self.attempt = 0
        self.requests = 0
        self.dropped = 0
        self.observed = False
        self.failed = False
        try:
            self.wall = time.monotonic_ns() if wall is None else wall
        except BaseException:
            self.wall = 0
            self.issues.add("observer_fault")
        self.cpu = 0
        self.sql_ordinal = 0
        self.sql_pending = []
        self.http = None
        self.resources = resources
        self.resource_anchor = None
        self.resource_last = None

    def resource_snapshot(self):
        if self.resources is None:
            return None
        try:
            values = self.resources.snapshot()
            if self.resource_anchor is None:
                self.resource_anchor = values
            if set(values) != set(self.resource_anchor):
                raise ValueError
            if self.resource_last is not None and any(values[key] < self.resource_last[key] for key in values):
                raise ValueError
            deltas = {key: value - self.resource_anchor[key] for key, value in values.items()}
            if any(type(v) is not int or not 0 <= v <= MAX_NUMBER for v in deltas.values()):
                raise ValueError
            self.resource_last = values
            return deltas
        except BaseException:
            self.issues.add("resource_fault")
            return None

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
            event = {"phase": phase, "state": state, **values}
            if phase in RESOURCE_PHASES and state in (0, 1, 2) and self.resources is not None:
                event["resources"] = self.resource_snapshot()
            self.events.append(event)
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
        pretransaction_expiry = False
        if any(self.pending.values()):
            issues.add("missing_phase")
        if self.sql_pending:
            issues.add("missing_sql_end")
        if not self.observed:
            issues.add("claim_not_observed")
        else:
            def seen(phase, state=None, attempt=None):
                return any(e["phase"] == phase and (state is None or e["state"] == state)
                           and (attempt is None or e["attempt"] == attempt) for e in self.events)
            pretransaction_expiry = (
                self.http is not None and self.http["classification"] == 1
                and seen("turn", 0) and seen("turn", 1)
                and seen("turn_delegate", 0) and seen("turn_delegate", 2)
                and not seen("transaction", 0) and not seen("gate", 0)
            )
            if not all(seen(p) for p in ("turn", "turn_delegate")):
                issues.add("required_phase_missing")
            if not pretransaction_expiry and not seen("gate"):
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
            if not pretransaction_expiry and not seen("transaction", 0):
                issues.add("required_phase_missing")
            if seen("transaction", 1) and not all(seen(p, 1) for p in ("body", "flush")):
                issues.add("required_phase_missing")
        if self.http is None:
            issues.add("missing_http_outcome")
        spans, span_issues = span_timings(self.events)
        issues.update(span_issues)
        if self.resources is not None and not all(self.resources.metadata.get(key) == 1
                for key in ("rusage_supported", "schedstat_supported", "schedstat_enabled")):
            issues.add("resource_unsupported")
        result = {"schema": 1, "failed": self.failed, "complete": not issues,
                  "issues": sorted(issues), "dropped": self.dropped,
                  "requests": self.requests, "observer_inclusive": True,
                  "anchor_monotonic_ns": self.wall, "provider_cpu_anchor_ns": self.cpu,
                  "events": self.events, "spans": spans, "http": self.http,
                  "pretransaction_expiry": pretransaction_expiry,
                  "exclusive_timing": "direct nested children subtracted; milestones are not spans"}
        return result


def span_timings(events):
    """Derive inclusive/exclusive provider-thread spans; never sum nested work twice."""
    opened, spans, issues = [], [], set()
    for index, event in enumerate(events):
        state = event["state"]
        if state == 0:
            opened.append({"id": index, "event": event, "wall_children": 0, "cpu_children": 0})
        elif state in (1, 2):
            if not opened or opened[-1]["event"]["phase"] != event["phase"]:
                issues.add("span_nesting")
                continue
            start = opened.pop()
            if "ordinal" in start["event"] and any(
                    event.get(key) != start["event"][key] for key in ("ordinal", "kind")):
                issues.add("span_identity")
            wall = event["wall_ns"] - start["event"]["wall_ns"]
            cpu = event["cpu_ns"] - start["event"]["cpu_ns"]
            exclusive_wall, exclusive_cpu = wall - start["wall_children"], cpu - start["cpu_children"]
            if min(wall, cpu, exclusive_wall, exclusive_cpu) < 0:
                issues.add("invalid_span_time")
            span = {"id": start["id"], "parent": opened[-1]["id"] if opened else -1,
                          "phase": event["phase"], "attempt": event["attempt"],
                          "entered_wall_ns": start["event"]["wall_ns"],
                          "returned_wall_ns": event["wall_ns"],
                          "wall_ns": wall, "cpu_ns": cpu,
                          "exclusive_wall_ns": exclusive_wall, "exclusive_cpu_ns": exclusive_cpu}
            before, after = start["event"].get("resources"), event.get("resources")
            if before is not None or after is not None:
                if not isinstance(before, dict) or not isinstance(after, dict) or set(before) != set(after):
                    issues.add("missing_resource_boundary")
                else:
                    delta = {key: after[key] - before[key] for key in before}
                    if any(type(v) is not int or v < 0 for v in delta.values()):
                        issues.add("invalid_resource_delta")
                    span["resource_delta_inclusive"] = delta
            spans.append(span)
            if opened:
                opened[-1]["wall_children"] += wall
                opened[-1]["cpu_children"] += cpu
    if opened:
        issues.add("missing_span_end")
    return sorted(spans, key=lambda span: span["id"]), issues


def sql_class(statement):
    """Return a fixed numeric class, never SQL text or parameters."""
    if not isinstance(statement, str):
        return 0
    prefix = statement.lstrip()[:32].upper()
    for number, start in enumerate(("BEGIN", "PRAGMA", "ROLLBACK", "COMMIT",
                                   "SELECT", "INSERT", "UPDATE", "DELETE"), 1):
        if prefix.startswith(start):
            return number
    return 9


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


class Capture:
    """One row/provider, exactly three expected turns, no cross-area sampler."""
    patch = Recorder.patch

    def __init__(self, row, resources=None):
        self.row = row
        self.resources = NativeResources() if resources is None else resources
        self._issues = set()
        try:
            self.wall = time.monotonic_ns()
        except BaseException:
            self.wall = 0
            self._issues.add("observer_fault")
        self.local = threading.local()
        self.records = {}
        self.serial = count()
        self.failed = False
        self.closed = False

    def current(self):
        return None if self.closed else getattr(self.local, "recorder", None)

    def active(self):
        return self.current() is not None

    @property
    def issues(self):
        selected = self.current()
        return selected.issues if selected is not None else self._issues

    @property
    def attempt(self):
        return self.current().attempt

    @attempt.setter
    def attempt(self, value):
        self.current().attempt = value

    @property
    def sql_ordinal(self):
        return self.current().sql_ordinal

    @sql_ordinal.setter
    def sql_ordinal(self, value):
        self.current().sql_ordinal = value

    @property
    def sql_pending(self):
        return self.current().sql_pending

    def record(self, *args, **kwargs):
        selected = self.current()
        if selected is not None:
            selected.record(*args, **kwargs)

    def call(self, phase, delegate, *args, **kwargs):
        selected = self.current()
        return (selected.call(phase, delegate, *args, **kwargs) if selected is not None
                else delegate(*args, **kwargs))

    def start(self):
        ordinal = next(self.serial)
        if ordinal >= TURN_LIMIT:
            self._issues.add("turn_limit")
            return None
        if self.current() is not None:
            self._issues.add("nested_turn")
            return None
        selected = Recorder(self.resources, self.wall)
        selected.thread = threading.get_ident()
        selected.cpu = time.thread_time_ns()
        selected.observed, selected.requests = True, 1
        self.records[ordinal] = selected
        self.local.recorder = selected
        return selected

    def payload(self):
        if hasattr(self, "result"):
            return self.result
        # Called once after ordinary fixture teardown/drain, never during a turn.
        self.closed = True
        seen = next(self.serial)
        records = [{"ordinal": key + 1, **value.payload()} for key, value in sorted(self.records.items())]
        issues = set(self._issues)
        if not records or (not self.failed and seen != TURN_LIMIT):
            issues.add("missing_turn")
        if any(not record["complete"] for record in records):
            issues.add("incomplete_turn")
        self.result = {"schema": 2, "row": self.row, "failed": self.failed,
                       "complete": not issues, "issues": sorted(issues),
                       "expected_turns_on_success": TURN_LIMIT, "seen": seen,
                       "dropped": max(0, seen - len(records)), "records": records,
                       "resources": self.resources.metadata,
                       "quota_scope": "cgroup mount-root cpu.max, not effective process allotment",
                       "affinity_scope": "one-time attaching pytest thread, not measured provider affinity",
                       "resource_scope": "major-boundary inclusive native counter deltas; SQL uses existing wall/CPU only",
                       "construction_before_attachment_observed": False}
        self.result["slow_turns"] = sum(any(s["phase"] == "turn" and s["wall_ns"] >= 100_000_000
                                             for s in r["spans"]) for r in records)
        self.result["error_turns"] = sum(any(e["phase"] == "turn_delegate" and e["state"] == 2
                                              for e in r["events"]) for r in records)
        return self.result


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

    def sql_before(_conn, _cursor, statement, _parameters, _context, _many):
        if not recorder.active():
            return
        try:
            recorder.sql_ordinal += 1
            kind = sql_class(statement)
            if kind == 0:
                recorder.issues.add("unsupported_statement")
            recorder.sql_pending.append((recorder.sql_ordinal, kind))
            recorder.record("sql", 0, ordinal=recorder.sql_ordinal, kind=kind)
        except BaseException:
            recorder.issues.add("observer_fault")

    def sql_after(*_args):
        if recorder.active():
            try:
                ordinal, kind = recorder.sql_pending.pop()
                recorder.record("sql", 1, ordinal=ordinal, kind=kind)
            except BaseException:
                recorder.issues.add("observer_fault")

    def sql_error(context):
        if recorder.active():
            try:
                code, code_state = sqlite_code(context.original_exception)
                if code_state == 2:
                    recorder.issues.add("invalid_error_code")
                if recorder.sql_pending:
                    ordinal, kind = recorder.sql_pending.pop()
                    recorder.record("sql", 2, ordinal=ordinal, kind=kind,
                                    sqlite_code=code, code_state=code_state)
                else:
                    recorder.record("db_error", 3, sqlite_code=code, code_state=code_state)
            except BaseException:
                recorder.issues.add("observer_fault")
        # SQLAlchemy must retain its original exception and disconnect policy.
        return None

    event.listen(engine, "before_cursor_execute", sql_before)
    event.listen(engine, "after_cursor_execute", sql_after)
    event.listen(engine, "handle_error", sql_error)

    instrument(recorder, stack, storage, pool)
    original_turn = storage.relay_turn

    def turn(*args, **kwargs):
        try:
            selected = recorder.start()
        except BaseException:
            recorder._issues.add("observer_fault")
            return original_turn(*args, **kwargs)
        if selected is None:
            return original_turn(*args, **kwargs)
        recorder.record("turn", 0)
        try:
            return recorder.call("turn_delegate", original_turn, *args, **kwargs)
        except BaseException:
            selected.failed = True
            raise
        finally:
            recorder.record("turn", 1)
            recorder.local.recorder = None
    recorder.patch(stack, storage, "relay_turn", turn)


def instrument(recorder, stack, storage, pool):
    native_begin = storage._begin_relay_immediate

    @contextmanager
    def transaction():
        if not recorder.active():
            with native_begin() as session:
                yield session
            return
        recorder.record("transaction", 0)
        try:
            with native_begin() as session:
                recorder.record("body", 0)
                try:
                    yield session
                except BaseException:
                    recorder.record("body", 2)
                    raise
                else:
                    recorder.record("body", 1)
        except BaseException:
            recorder.record("transaction", 2)
            raise
        else:
            recorder.record("transaction", 1)

    recorder.patch(stack, storage, "_begin_relay_immediate", transaction)
    native_lock = storage._relay_writer_lock

    class Lock:
        def acquire(self, *args, **kwargs):
            if not recorder.active():
                return native_lock.acquire(*args, **kwargs)
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
        if not recorder.active():
            return native_get(*args, **kwargs)
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
            flush = session.flush
            recorder.patch(stack, session, "connection",
                           lambda *a, **kw: recorder.call("connection", connection, *a, **kw))
            recorder.patch(stack, session, "close",
                           lambda *a, **kw: recorder.call("session_close", close, *a, **kw))
            recorder.patch(stack, session, "flush",
                           lambda *a, **kw: recorder.call("flush", flush, *a, **kw))
        except BaseException:
            recorder.issues.add("observer_fault")
        return session
    recorder.patch(stack, storage, "_relay_session_factory", factory)


def install_http(recorder, stack, client):
    native_request = client.request

    def request(*args, **kwargs):
        selected = False
        try:
            method = args[0] if args else kwargs.get("method")
            url = args[1] if len(args) > 1 else kwargs.get("url")
            selected = method == "POST" and url == "/relay/turn"
        except BaseException:
            recorder.issues.add("http_selection_fault")
        if not selected:
            return native_request(*args, **kwargs)
        before = set(recorder.records)
        try:
            entered, cpu = time.monotonic_ns(), time.thread_time_ns()
        except BaseException:
            recorder.issues.add("http_outcome_fault")
            entered, cpu = recorder.wall, 0

        def finish(response, classification):
            try:
                added = set(recorder.records) - before
                if len(added) != 1:
                    recorder._issues.add("http_correlation")
                    return
                selected_record = recorder.records[added.pop()]
                if selected_record.http is not None:
                    recorder._issues.add("multiple_http_requests")
                status = -1 if response is None else response.status_code
                if type(status) is not int or (status != -1 and not 100 <= status <= 599):
                    raise ValueError
                if status == 200:
                    classification = 0
                elif status == 409 and response.json() == {"detail": "Relay claim request expired"}:
                    classification = 1
                selected_record.http = {
                    "status": status, "classification": classification,
                    "entered_wall_ns": entered - recorder.wall,
                    "returned_wall_ns": time.monotonic_ns() - recorder.wall,
                    "thread_cpu_ns": time.thread_time_ns() - cpu,
                }
                if any(type(value) is not int or abs(value) > MAX_NUMBER for value in selected_record.http.values()):
                    recorder.issues.add("numeric_metadata")
            except BaseException:
                recorder.issues.add("http_outcome_fault")

        try:
            result = native_request(*args, **kwargs)
        except BaseException:
            finish(None, 3)
            raise
        finish(result, 2)
        return result

    recorder.patch(stack, client, "request", request)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    if item.nodeid not in TARGETS:
        yield
        return
    recorder = Capture(TARGETS[item.nodeid])
    item._claim_acquisition_recorder = recorder
    stack = item._claim_acquisition_stack = ExitStack()
    try:
        client = item.funcargs["client"]
        install(recorder, stack, client.app.state.pallium_service._storage)
        install_http(recorder, stack, client)
    except BaseException:
        recorder.issues.add("installation_fault")
        stack.close()
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    try:
        yield
    finally:
        stack = getattr(item, "_claim_acquisition_stack", None)
        if stack is not None:
            stack.close()  # Ordinary fixture cleanup/storage disposal has completed.


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if item.nodeid not in TARGETS:
        return
    report = outcome.get_result()
    recorder = getattr(item, "_claim_acquisition_recorder", None)
    if recorder is None:
        recorder = Capture(TARGETS[item.nodeid])
        item._claim_acquisition_recorder = recorder
    recorder.failed |= report.failed
    if report.when == "teardown":
        directory = os.environ.get("PALLIUM_CLAIM_DIAGNOSTIC_DIR")
        if directory:
            try:
                path = Path(directory)
                path.mkdir(parents=True, exist_ok=True)
                (path / f"row-{recorder.row}.json").write_text(
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
                "tests/test_agent_relay_hooks.py", "pyproject.toml",
                "scripts/relay_claim_acquisition_diagnostic.py")}}


def evidence_status(directory):
    """Missing/sink-failed capture cannot look complete because runtime exists."""
    files = list(directory.glob("row-*.json"))
    result = {"target_reports": len(files), "complete": False, "issues": ["missing_or_multiple_reports"]}
    if len(files) == 2:
        try:
            reports = []
            for file in files:
                if file.stat().st_size > 1_000_000:
                    raise ValueError
                reports.append(json.loads(file.read_text(encoding="utf-8")))
            if sorted(r["row"] for r in reports) != [1, 2]:
                raise ValueError
            result.update(complete=all(r["complete"] is True for r in reports),
                          failed=any(r["failed"] is True for r in reports),
                          issues=sorted({issue for r in reports for issue in r["issues"]}))
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
