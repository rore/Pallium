"""Opt-in empty offline setup for functional journeys, with native refusal guards."""

from contextlib import contextmanager
from pathlib import Path
import os
import re
import sqlite3
import sys
import threading
import time

from core.errors import ImmediateTransactionBusyError


_REPLY_CHAIN_NODE = (
    "tests/test_cross_container_relay_e2e.py::"
    "test_cross_container_reply_chain_and_bounded_backlog_continuation[semantic]"
)


def relay_acquisition_split_enabled(nodeid):
    return os.environ.get("GITHUB_ACTIONS") == "true" and sys.platform == "linux" and nodeid == _REPLY_CHAIN_NODE


def _stamp(clock):
    try:
        value = clock()
        return value if type(value) is int and value >= 0 else None
    except Exception:
        return None


def _duration(start, end):
    return end - start if start is not None and end is not None and end >= start else None


def _bind_acquisition_spans(storage, monkeypatch, active):
    """Wrap only this fixture's SQLAlchemy boundaries; never take over SQL dispatch."""
    from sqlalchemy.engine import Connection
    from sqlalchemy.sql.elements import TextClause

    engine = storage._relay_engine
    pool, dialect = engine.pool, engine.dialect
    session_type = storage._relay_session_factory.class_
    original_connection = session_type.connection
    original_checkout = pool.connect
    original_execute = Connection.execute
    original_driver = dialect.do_execute
    setup_sql = re.compile(r"PRAGMA busy_timeout=([0-9]{1,3})")
    max_timeout = storage._RELAY_IMMEDIATE_BUSY_TIMEOUT_MS

    @contextmanager
    def span(trace, label, target=None):
        spans = trace["spans"]
        # Bound storage for three normal attempts (four measured calls each).
        if len(spans) >= 12:
            trace["overflow"] = True
            yield
            return
        parent = trace["parent"]
        row = {"phase": label, "parent": None if parent is None else parent[0]}
        trace["parent"] = (len(spans), label, target)
        spans.append(row)
        wall, cpu = _stamp(time.perf_counter_ns), _stamp(time.thread_time_ns)
        try:
            yield
        finally:
            end_wall, end_cpu = _stamp(time.perf_counter_ns), _stamp(time.thread_time_ns)
            trace["parent"] = parent
            row["wall_ns"] = _duration(wall, end_wall)
            row["thread_cpu_ns"] = _duration(cpu, end_cpu)

    def connection(session, *args, **kwargs):
        trace = getattr(active, "trace", None)
        if trace is not None and session.bind is engine and trace["parent"] is None:
            with span(trace, "session_connection"):
                return original_connection(session, *args, **kwargs)
        return original_connection(session, *args, **kwargs)

    def checkout(*args, **kwargs):
        trace = getattr(active, "trace", None)
        parent = trace["parent"] if trace is not None else None
        if parent is not None and parent[1] == "session_connection":
            with span(trace, "pool_checkout"):
                return original_checkout(*args, **kwargs)
        return original_checkout(*args, **kwargs)

    def execute(conn, statement, *args, **kwargs):
        trace = getattr(active, "trace", None)
        if trace is not None and conn.engine is engine and trace["parent"] is None and type(statement) is TextClause:
            match = setup_sql.fullmatch(statement.text)
            # Expired checkout can skip setup: its first execute may restore 15,000 ms.
            if match and 0 < int(match[1]) <= max_timeout:
                with span(trace, "setup_execute", (conn, statement.text)):
                    return original_execute(conn, statement, *args, **kwargs)
        return original_execute(conn, statement, *args, **kwargs)

    def driver(cursor, statement, parameters, context=None):
        trace = getattr(active, "trace", None)
        parent = trace["parent"] if trace is not None else None
        if (parent is not None and parent[1] == "setup_execute"
                and getattr(context, "root_connection", None) is parent[2][0] and statement == parent[2][1]):
            with span(trace, "setup_driver"):
                return original_driver(cursor, statement, parameters, context)
        return original_driver(cursor, statement, parameters, context)

    monkeypatch.setattr(session_type, "connection", connection)
    monkeypatch.setattr(pool, "connect", checkout)
    monkeypatch.setattr(Connection, "execute", execute)
    monkeypatch.setattr(dialect, "do_execute", driver)


def _acquisition_split_report(trace):
    spans = trace["spans"]
    phases = {row["phase"] for row in spans}
    expected_children = {"session_connection": "pool_checkout", "setup_execute": "setup_driver"}
    missing = (expected_children.keys() | expected_children.values()) - phases
    roots = [row["phase"] for row in spans if row["parent"] is None]
    attempts_paired = bool(roots) and roots == ["session_connection", "setup_execute"] * (len(roots) // 2)
    unpaired = [
        index for index, row in enumerate(spans)
        if row["phase"] in expected_children and sum(
            child["parent"] == index and child["phase"] == expected_children[row["phase"]]
            for child in spans
        ) != 1
    ]
    complete = attempts_paired and not unpaired and not missing and not trace["overflow"] and all(
        row["wall_ns"] is not None and row["thread_cpu_ns"] is not None for row in spans
    )
    return {"status": "complete" if complete else "incomplete",
            "missing": sorted(missing), "unpaired": unpaired, "attempts_paired": attempts_paired,
            "overflow": trace["overflow"], "spans": spans}


def observe_relay_acquisition_failures(storage, monkeypatch, *, split=False):
    """Bounded CI evidence; timings include observation and failed-entry cleanup."""
    from itertools import count
    import json

    original, emissions = storage._begin_relay_immediate, count()
    active = threading.local() if split else None
    if split:
        from storage import sqlite_queue

        native_monotonic = time.monotonic
        _bind_acquisition_spans(storage, monkeypatch, active)

    @contextmanager
    def observed():
        started, cpu = _stamp(time.perf_counter_ns), _stamp(time.thread_time_ns)
        trace = previous = None
        if split:
            previous = getattr(active, "trace", None)
            if sqlite_queue.time is time and time.monotonic is native_monotonic:
                trace = {"spans": [], "parent": None, "overflow": False}
            active.trace = trace
        admitted = False
        try:
            with original() as session:
                admitted = True
                if split:
                    active.trace = None
                yield session
        except ImmediateTransactionBusyError as error:
            if not admitted and next(emissions) < 4:
                try:
                    finished, cpu_finished = _stamp(time.perf_counter_ns), _stamp(time.thread_time_ns)
                    phases = error.acquisition_phase_ms
                    phases = {name: value for name, value in phases.items()
                              if name in {"session_factory", "session_connection", "setup_pragma", "begin_immediate"}
                              and type(value) is int and 0 <= value < 2**63} if type(phases) is dict else None
                    native, cause = [], error
                    for _ in range(4):
                        if cause is None:
                            break
                        underlying = getattr(cause, "orig", cause)
                        if isinstance(underlying, sqlite3.Error):
                            code, name = getattr(underlying, "sqlite_errorcode", None), getattr(underlying, "sqlite_errorname", None)
                            if type(code) is int and type(name) is str and name.startswith("SQLITE_") and getattr(sqlite3, name, None) == code:
                                native.append({"code": code, "name": name})
                        cause = cause.__cause__ or cause.__context__
                    metadata = {
                        "stage": error.acquisition_stage if type(error.acquisition_stage) is str and error.acquisition_stage in ImmediateTransactionBusyError.ACQUISITION_STAGES else None,
                        "wall_phase_ms": phases,
                        "acquisition_and_cleanup_wall_ns": _duration(started, finished),
                        "acquisition_and_cleanup_thread_cpu_ns": _duration(cpu, cpu_finished),
                        "native_sqlite_errors": native,
                    }
                    if trace is not None:
                        metadata["split_timing"] = _acquisition_split_report(trace)
                    print("relay acquisition failure: " + json.dumps(metadata, sort_keys=True), file=sys.stderr)
                except Exception:
                    pass  # Diagnostics must preserve the original refusal, including a failed sink.
            raise
        finally:
            if split:
                active.trace = previous

    monkeypatch.setattr(storage, "_begin_relay_immediate", observed)


def initialize_empty_wake_registry(
    registry, relay, storage, *, expected_database, legacy, monkeypatch, force_refusal=False,
):
    database = Path(storage._relay_engine.url.database)
    assert database == expected_database

    def absent_legacy():
        if legacy is None:
            assert registry._path is None
        else:
            assert not legacy.exists()

    absent_legacy()
    original_initialize = relay.codex_wake_initialize
    attempts = []

    def observe_initialize(reservations):
        assert reservations == ()
        attempt = {}
        attempts.append(attempt)
        try:
            if force_refusal and len(attempts) == 1:
                raise ImmediateTransactionBusyError('controlled empty setup refusal', acquisition_stage='setup_deadline')
            result = original_initialize(reservations)
        except Exception as error:
            attempt['error'] = error
            raise
        attempt['result'] = result
        return result

    # Empty offline setup may repeat only a proven precommit acquisition refusal.
    with monkeypatch.context() as setup_patch:
        setup_patch.setattr(relay, 'codex_wake_initialize', observe_initialize)
        initialized = registry.initialize(old_owner_drained=True)
        if initialized is False and len(attempts) == 1 and type(attempts[0].get('error')) is ImmediateTransactionBusyError:
            assert relay.codex_wake_snapshot() == (False, ())
            absent_legacy()
            with sqlite3.connect(database) as db:
                assert db.execute('SELECT count(*) FROM relay_sessions').fetchone() == (0,)
                assert db.execute('SELECT count(*) FROM relay_deliveries').fetchone() == (0,)
            initialized = registry.initialize(old_owner_drained=True)
        assert initialized is True
        assert attempts[-1] == {'result': True}
        assert len(attempts) == 1 or (len(attempts) == 2 and type(attempts[0].get('error')) is ImmediateTransactionBusyError)
    assert relay.codex_wake_initialize == original_initialize
