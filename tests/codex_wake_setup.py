"""Opt-in empty offline setup for functional journeys, with native refusal guards."""

from pathlib import Path
import sqlite3

from core.errors import ImmediateTransactionBusyError


class _SetupObservation:
    """Temporary WIP probe; completed phases cannot be reconstructed by stacks."""

    def __init__(self, storage, monkeypatch):
        import inspect
        import threading
        import time
        import weakref
        from sqlalchemy import event
        from sqlalchemy.engine import Connection
        from storage.sqlite_queue import SQLiteQueueMixin

        self.active, self.threads, self.calls = {}, {}, []
        self.connection_count = 0
        self.cost_ns = self.recording_errors = self.dropped = 0
        self.clock, self.cpu, self.ident = time.perf_counter_ns, time.thread_time_ns, threading.get_ident
        self.connections = weakref.WeakKeyDictionary()
        self.engine = weakref.ref(storage._relay_engine)
        self.limit = storage._RELAY_IMMEDIATE_BUSY_TIMEOUT_MS
        owner = SQLiteQueueMixin._begin_immediate_for.__wrapped__
        lines, start = inspect.getsourcelines(owner)
        self.owner_code = owner.__code__
        self.setup_line = start + next(i for i, line in enumerate(lines) if 'acquire_phase("setup_pragma"' in line)
        original_execute, original_close = Connection.execute, storage.close

        def execute(connection, statement, *args, **kwargs):
            call = None
            try:
                attempt = self.active.get(self.ident())
                sql = getattr(statement, "text", None)
                if (connection.engine is self.engine() and attempt is not None
                        and type(sql) is str and sql.startswith("PRAGMA busy_timeout=")
                        and sql[20:].isdigit() and 0 < int(sql[20:]) <= self.limit):
                    call = self.record(attempt, connection)
            except Exception:
                self.recording_errors += 1
            try:
                return original_execute(connection, statement, *args, **kwargs)
            finally:
                if call is not None:
                    self.safe(lambda: call.update(returned=self.stamp()))
                    attempt.pop("current", None)

        def before(connection, _cursor, statement, _parameters, _context, _many):
            self.cursor(connection, statement, "before")

        def after(connection, _cursor, statement, _parameters, _context, _many):
            self.cursor(connection, statement, "after")

        engine = storage._relay_engine
        event.listen(engine, "before_cursor_execute", before)
        event.listen(engine, "after_cursor_execute", after)

        def close():
            try:
                return original_close()
            finally:
                target = self.engine()
                if target is not None:
                    for name, callback in (("before_cursor_execute", before), ("after_cursor_execute", after)):
                        try:
                            event.remove(target, name, callback)
                        except Exception:
                            self.recording_errors += 1
                self.active.clear()

        monkeypatch.setattr(Connection, "execute", execute)
        monkeypatch.setattr(storage, "close", close)

    def stamp(self):
        return [self.clock(), self.cpu()]

    def safe(self, operation):
        started = self.clock()
        try:
            return operation()
        except Exception:
            self.recording_errors += 1
        finally:
            self.cost_ns += self.clock() - started

    def start(self):
        ident = self.ident()
        if ident not in self.threads and len(self.threads) < 16:
            self.threads[ident] = "t" + str(len(self.threads) + 1)
        attempt = {"thread": self.threads.get(ident, "unassigned"), "calls": []}
        if len(self.active) < 16:
            self.active[ident] = attempt
        else:
            self.dropped += 1
        return attempt

    def record(self, attempt, connection):
        if len(self.calls) >= 32:
            self.dropped += 1
            return None
        if connection not in self.connections:
            if len(self.connections) >= 16:
                self.dropped += 1
                return None
            self.connection_count += 1
            self.connections[connection] = "c" + str(self.connection_count)
        call = {"thread": attempt["thread"], "connection": self.connections[connection], "entry": self.stamp()}
        self.calls.append(call)
        attempt["calls"].append(call)
        attempt["current"] = call
        return call

    def cursor(self, connection, statement, phase):
        def record():
            attempt = self.active.get(self.ident())
            call = None if attempt is None else attempt.get("current")
            if call is not None and connection.engine is self.engine() and statement.startswith("PRAGMA busy_timeout="):
                call[phase] = self.stamp()
        self.safe(record)

    def snapshot(self, attempt):
        import sys

        stacks, frames = [], sys._current_frames()
        try:
            for ident, active in tuple(self.active.items())[:8]:
                frame, rows, holder = frames.get(ident), [], False
                try:
                    for _ in range(32):
                        if frame is None:
                            break
                        code = frame.f_code
                        filename = Path(code.co_filename)
                        # No source text, values, raw identifiers or absolute paths.
                        rows.append([filename.name, code.co_name, frame.f_lineno])
                        if (active.get("current") is not None and code is self.owner_code
                                and frame.f_lineno == self.setup_line):
                            holder = True
                        frame = frame.f_back
                finally:
                    del frame
                stacks.append({"thread": active["thread"], "setup_gate_holder_candidate": holder, "frames": rows})
        finally:
            frames.clear()
            del frames
        return {"provider": "p1", "setup_calls": list(attempt["calls"]), "active_same_provider": stacks,
                "recording_cost_ns_lower_bound": self.cost_ns, "recording_errors": self.recording_errors,
                "dropped": self.dropped, "residual": "unassigned; construction, cleanup, rounding and observer overhead",
                "limits": "cursor envelope includes callbacks; late sample cannot reconstruct completed work"}


def observe_relay_acquisition_failures(storage, monkeypatch):
    """Bounded CI evidence; timings include observation and failed-entry cleanup."""
    from contextlib import contextmanager
    from itertools import count
    import json
    import sys
    import time
    import os

    probe = _SetupObservation(storage, monkeypatch) if os.environ.get("PALLIUM_WIP_ACQUISITION") == "1" else None
    if probe is not None:
        import hashlib
        worker = os.environ.get("PYTEST_XDIST_WORKER", "controller")
        assert worker == "controller" or (worker.startswith("gw") and worker[2:].isdigit())
        print("WIP observer loaded: " + json.dumps({"worker": worker,
              "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}), file=sys.stderr)

    original, emissions = storage._begin_relay_immediate, count()

    def stamp(clock):
        try:
            value = clock()
            return value if type(value) is int and value >= 0 else None
        except Exception:
            return None

    @contextmanager
    def observed():
        started, cpu = stamp(time.perf_counter_ns), stamp(time.thread_time_ns)
        attempt = None if probe is None else probe.safe(probe.start)
        admitted = False
        try:
            with original() as session:
                admitted = True
                yield session
        except ImmediateTransactionBusyError as error:
            if not admitted and next(emissions) < 4:
                try:
                    finished, cpu_finished = stamp(time.perf_counter_ns), stamp(time.thread_time_ns)
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
                        "acquisition_and_cleanup_wall_ns": None if started is None or finished is None or finished < started else finished - started,
                        "acquisition_and_cleanup_thread_cpu_ns": None if cpu is None or cpu_finished is None or cpu_finished < cpu else cpu_finished - cpu,
                        "native_sqlite_errors": native,
                    }
                    if probe is not None and attempt is not None:
                        metadata["wip_setup"] = probe.snapshot(attempt)
                    print("relay acquisition failure: " + json.dumps(metadata, sort_keys=True), file=sys.stderr)
                except Exception:
                    pass  # Diagnostics must preserve the original refusal, including a failed sink.
            raise
        finally:
            if probe is not None:
                probe.active.pop(probe.ident(), None)

    monkeypatch.setattr(storage, "_begin_relay_immediate", observed)


def _self_check_setup_observation():
    """One hosted cheap check, before the sole development node invocation."""
    import json
    import logging
    import time
    from types import SimpleNamespace
    from unittest import TestCase
    from unittest.mock import patch
    import pytest
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import Connection

    engine = create_engine("sqlite://")
    storage = SimpleNamespace(_relay_engine=engine, _RELAY_IMMEDIATE_BUSY_TIMEOUT_MS=150, close=engine.dispose)
    original_execute, calls = Connection.execute, []
    sentinel, failure = object(), RuntimeError("controlled native call failure")

    def native(connection, statement, *args, **kwargs):
        calls.append((connection, statement, args, kwargs))
        if kwargs.get("controlled_failure"):
            raise failure
        return sentinel

    started = time.perf_counter_ns()
    checks = TestCase()
    with checks.assertRaises(AssertionError):
        with checks.assertNoLogs(level=logging.WARNING):
            logging.getLogger("sqlalchemy.pool").error("controlled cleanup error")
    # Pool reset can log an error without raising; gate success on clean teardown.
    with checks.assertNoLogs(level=logging.WARNING), patch.object(Connection, "execute", native):
        with pytest.MonkeyPatch.context() as monkeypatch:
            probe = _SetupObservation(storage, monkeypatch)
            with engine.connect() as connection:
                attempt = probe.start()
                statement = text("PRAGMA busy_timeout=150")
                assert connection.execute(statement, "argument", flag=True) is sentinel
                assert calls[-1] == (connection, statement, ("argument",), {"flag": True})
                saved_record = probe.record
                probe.record = lambda *_: (_ for _ in ()).throw(RuntimeError("controlled recording failure"))
                try:
                    connection.execute(statement, controlled_failure=True)
                except RuntimeError as error:
                    assert error is failure
                else:
                    raise AssertionError("native error was swallowed")
                assert len(calls) == 2 and probe.recording_errors == 1
                probe.record = saved_record
                probe.snapshot(attempt)
            storage.close()
            assert not probe.active
            assert not engine.dispatch.before_cursor_execute and not engine.dispatch.after_cursor_execute
        assert Connection.execute is native
    assert Connection.execute is original_execute
    with checks.assertNoLogs(level=logging.WARNING), pytest.MonkeyPatch.context() as monkeypatch:
        probe = _SetupObservation(storage, monkeypatch)
        with engine.connect() as connection:
            attempt = probe.start()
            connection.execute(text("PRAGMA busy_timeout=150"))
            connection.execute(text("PRAGMA busy_timeout=15000"))
            call, = attempt["calls"]
            assert set(call) == {"thread", "connection", "entry", "before", "after", "returned"}
            assert all(call[a][0] <= call[b][0] for a, b in zip(("entry", "before", "after"), ("before", "after", "returned")))
            assert "setup_gate_holder_candidate" in json.dumps(probe.snapshot(attempt))
            assert len(probe.calls) <= 32 and len(probe.threads) <= 16
            original_stamp, stamps = probe.stamp, []
            def failed_callback_stamp():
                stamps.append(None)
                if len(stamps) > 1:
                    raise RuntimeError("controlled cursor recording failure")
                return original_stamp()
            probe.stamp = failed_callback_stamp
            assert connection.execute(text("PRAGMA busy_timeout=150")).scalar() == 150
            assert probe.recording_errors >= 2
            probe.stamp = original_stamp
        storage.close()
        assert not probe.active
        assert not engine.dispatch.before_cursor_execute and not engine.dispatch.after_cursor_execute
    assert Connection.execute is original_execute
    print(json.dumps({"self_check": "passed", "elapsed_ns": time.perf_counter_ns() - started,
                      "cost_limit": "single invocation; no worst-case or historical-load equivalence"}))


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
