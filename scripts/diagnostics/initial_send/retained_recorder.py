"""One private observation of the original settlement subject; no retries."""
import inspect
import json
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import SessionTransaction
from sqlalchemy.pool import QueuePool
from sqlalchemy.pool.base import Pool, _ConnectionRecord

TARGET = "tests/test_relay_work_ref_associations_e2e.py::test_settled_relay_write_releases_gate_before_cleanup[reset-None-rollback]"
STATE = {"node": TARGET, "spans": [], "connection_events": [], "errors": [],
         "overflow": False, "unmatched": False, "b_calls": 0, "profile_restored": False}
STACK = []
PYTHON_CALLS = {}
C_METHODS = {sqlite3.Cursor.execute: "cursor_execute",
             sqlite3.Connection.execute: "connection_execute",
             sqlite3.Connection.create_function: "create_function",
             sqlite3.Connection.rollback: "native_rollback"}
SKIPPED_DEPTH = 0
REGISTERED = []
CONTROL = None


def error(stage, exc):
    if len(STATE["errors"]) < 8:
        STATE["errors"].append({"stage": stage, "type": type(exc).__name__})
    else:
        STATE["overflow"] = True


def add_callable(label, function, depth=0):
    if not inspect.isfunction(function) and not inspect.ismethod(function):
        return
    function = inspect.unwrap(function)
    PYTHON_CALLS[function.__code__] = label
    if depth < 2:
        for index, cell in enumerate(function.__closure__ or ()):
            try:
                value = cell.cell_contents
                if inspect.isfunction(value):
                    add_callable(f"{label}.closure{index}", value, depth + 1)
            except ValueError:
                pass


def sql_category(frame):
    if PYTHON_CALLS.get(frame.f_code, "").startswith("connect_callback"):
        return "connect_callback_sql"
    if frame.f_code is not DefaultDialect.do_execute.__code__:
        return "other"
    statement = frame.f_locals.get("statement")
    if isinstance(statement, str):
        sql = statement.strip().upper()
        for prefix, category in (("PRAGMA BUSY_TIMEOUT", "busy_timeout"),
                                 ("PRAGMA READ_UNCOMMITTED", "read_uncommitted"),
                                 ("BEGIN IMMEDIATE", "begin_immediate"),
                                 ("ROLLBACK", "rollback"), ("COMMIT", "commit")):
            if sql.startswith(prefix):
                return category
    return "other"


def profile(frame, kind, argument):
    global SKIPPED_DEPTH
    try:
        if kind in {"call", "return"}:
            label = PYTHON_CALLS.get(frame.f_code)
            token = frame.f_code
        elif kind in {"c_call", "c_return", "c_exception"}:
            owner = getattr(argument, "__self__", None)
            token = vars(type(owner)).get(getattr(argument, "__name__", ""))
            label = "native_connect" if argument is sqlite3.connect else C_METHODS.get(token)
            if label == "native_connect":
                token = sqlite3.connect
        else:
            return
        if label is None:
            return
        entering = kind in {"call", "c_call"}
        if entering:
            if SKIPPED_DEPTH or len(STATE["spans"]) + len(STATE["connection_events"]) + len(STACK) >= 128:
                SKIPPED_DEPTH += 1
                STATE["overflow"] = True
                return
            STACK.append((token, {"label": label, "category": sql_category(frame),
                                  "depth": len(STACK), "wall_start_ns": time.perf_counter_ns(),
                                  "cpu_start_ns": time.thread_time_ns()}))
        elif SKIPPED_DEPTH:
            SKIPPED_DEPTH -= 1
        elif not STACK or STACK[-1][0] is not token:
            STATE["unmatched"] = True
        else:
            _, span = STACK.pop()
            span.update(wall_end_ns=time.perf_counter_ns(), cpu_end_ns=time.thread_time_ns(),
                        outcome="c_exception" if kind == "c_exception" else "return")
            STATE["spans"].append(span)
    except BaseException as exc:
        error("profile", exc)


def connection_event(stage, connection, record, *_extra):
    if STATE.get("active_thread") != threading.get_ident():
        return
    if len(STATE["connection_events"]) + len(STATE["spans"]) + len(STACK) >= 128:
        STATE["overflow"] = True
        return
    STATE["connection_events"].append({"stage": stage, "driver_identity": id(connection),
                                       "record_identity": id(record),
                                       "native_active": connection.in_transaction,
                                       "wall_ns": time.perf_counter_ns(),
                                       "cpu_ns": time.thread_time_ns()})


def pytest_collection_modifyitems(items):
    if [item.nodeid for item in items] != [TARGET]:
        raise pytest.UsageError("Private observer requires its one exact original parameter")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    global CONTROL
    assert item.nodeid == TARGET
    CONTROL = item.funcargs["relay_settlement_control"]
    store = item.funcargs["client"].app.state.pallium_service._storage
    engine = store._relay_engine
    for label, function in (("session_connection", Session.connection),
                            ("session_bind", SessionTransaction._connection_for_bind),
                            ("pool_connect", Pool.connect), ("pool_get", QueuePool._do_get),
                            ("record_get", _ConnectionRecord.get_connection),
                            ("record_connect", _ConnectionRecord._ConnectionRecord__connect),
                            ("creator", engine.pool._creator), ("dialect_connect", engine.dialect.connect),
                            ("set_isolation", engine.dialect.set_isolation_level),
                            ("get_isolation", engine.dialect.get_isolation_level)):
        add_callable(label, function)
    for index, callback in enumerate(engine.pool.dispatch.connect):
        add_callable(f"connect_callback{index}", callback)
    for stage in ("connect", "checkout"):
        def observe(connection, record, *extra, stage=stage):
            try:
                connection_event(stage, connection, record, *extra)
            except BaseException as exc:
                error("connection_event", exc)
        event.listen(engine, stage, observe)
        REGISTERED.append((engine, stage, observe))
    original = store.relay_attach_work_ref

    def attach(**kwargs):
        if kwargs["work_ref"]["local_ref"] != "item:B":
            return original(**kwargs)
        STATE["b_calls"] += 1
        previous = sys.getprofile()
        STATE["active_thread"] = threading.get_ident()
        STATE["b_wall_start_ns"] = time.perf_counter_ns()
        STATE["b_cpu_start_ns"] = time.thread_time_ns()
        try:
            sys.setprofile(profile)
            return original(**kwargs)
        except BaseException as exc:
            native = getattr(exc, "orig", None) or exc.__cause__ or exc
            STATE["b_exception"] = {"type": type(exc).__name__,
                                    "acquisition_stage": getattr(exc, "acquisition_stage", None),
                                    "native_type": type(native).__name__,
                                    "sqlite_errorcode": getattr(native, "sqlite_errorcode", None)}
            raise
        finally:
            sys.setprofile(previous)
            STATE["profile_restored"] = sys.getprofile() is previous
            STATE["b_wall_end_ns"] = time.perf_counter_ns()
            STATE["b_cpu_end_ns"] = time.thread_time_ns()
            STATE.pop("active_thread", None)
            STATE["unmatched"] |= bool(STACK or SKIPPED_DEPTH)

    item.funcargs["monkeypatch"].setattr(store, "relay_attach_work_ref", attach)
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item):
    try:
        yield
    finally:
        STATE["owned_workers_settled"] = CONTROL is not None and all(
            not worker.is_alive() for worker in tuple(CONTROL.pool._threads))
        if STATE["owned_workers_settled"]:
            for target, stage, callback in REGISTERED:
                try:
                    event.remove(target, stage, callback)
                except BaseException as exc:
                    error("event_remove", exc)
        STATE["events_removed"] = STATE["owned_workers_settled"] and all(
            not event.contains(target, stage, callback) for target, stage, callback in REGISTERED)
        STATE["capture_integrity_complete"] = (STATE["b_calls"] == 1 and STATE["profile_restored"]
                                      and STATE["events_removed"] and not STATE["overflow"]
                                      and not STATE["unmatched"] and not STATE["errors"]
                                      and any(span["label"] == "session_connection" for span in STATE["spans"]))
        STATE["limits"] = "Capture integrity is bounded pairing/cleanup, not complete causal coverage; missing decisive branch spans means unknown. One observed parameter; profiling adds overhead. Python return events alone do not distinguish exceptions. Wall/CPU gaps do not distinguish blocking from descheduling. No reproduction or incomplete discrimination leaves cause unknown."
        with Path(__file__).with_name("observations.json").open("x", encoding="utf-8") as output:
            json.dump(STATE, output, indent=2)
