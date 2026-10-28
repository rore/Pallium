"""Opt-in empty offline setup for functional journeys, with native refusal guards."""

from pathlib import Path
import sqlite3

from core.errors import ImmediateTransactionBusyError


def observe_relay_acquisition_failures(storage, monkeypatch):
    """Bounded CI evidence; timings include observation and failed-entry cleanup."""
    from contextlib import contextmanager
    from itertools import count
    import json
    import sys
    import time

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
                    print("relay acquisition failure: " + json.dumps(metadata, sort_keys=True), file=sys.stderr)
                except Exception:
                    pass  # Diagnostics must preserve the original refusal, including a failed sink.
            raise

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
