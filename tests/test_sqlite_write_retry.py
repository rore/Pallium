"""Tests for SQLite write retry logic (_with_retry).

Verifies that the storage layer handles transient 'database is locked' errors
correctly by retrying, and propagates non-transient errors immediately.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError as SAOperationalError

from core.contracts import build_source_item
from core.errors import ImmediateTransactionBusyError
from storage.sqlite import SQLiteStorageProvider


def _make_sa_operational_error(message: str) -> SAOperationalError:
    """Create a SQLAlchemy OperationalError wrapping a sqlite3.OperationalError."""
    import sqlite3
    orig = sqlite3.OperationalError(message)
    return SAOperationalError("", "", orig)


# ── Unit tests for _with_retry ──────────────────────────────────────────


class TestWithRetryUnit:
    @pytest.fixture
    def storage(self, tmp_path):
        return SQLiteStorageProvider(f"sqlite:///{tmp_path / 'retry_test.db'}")

    def test_succeeds_on_first_attempt(self, storage):
        calls = []

        def _fn(session):
            calls.append(1)
            return "ok"

        result = storage._with_retry(_fn)
        assert result == "ok"
        assert len(calls) == 1

    def test_retries_on_database_locked(self, storage):
        attempts = []

        def _fn(session):
            attempts.append(1)
            if len(attempts) < 2:
                raise _make_sa_operational_error("database is locked")
            return "recovered"

        with patch("storage.sqlite.time.sleep") as mock_sleep:
            result = storage._with_retry(_fn)

        assert result == "recovered"
        assert len(attempts) == 2
        mock_sleep.assert_called_once()

    def test_gives_up_after_max_retries(self, storage):
        attempts = []

        def _fn(session):
            attempts.append(1)
            raise _make_sa_operational_error("database is locked")

        with patch("storage.sqlite.time.sleep"):
            with pytest.raises(SAOperationalError, match="database is locked"):
                storage._with_retry(_fn)

        assert len(attempts) == storage._LOCKED_MAX_RETRIES

    def test_does_not_retry_non_transient_error(self, storage):
        attempts = []

        def _fn(session):
            attempts.append(1)
            raise _make_sa_operational_error("no such table: foo")

        with pytest.raises(SAOperationalError, match="no such table"):
            storage._with_retry(_fn)

        assert len(attempts) == 1

    def test_does_not_retry_non_operational_error(self, storage):
        attempts = []

        def _fn(session):
            attempts.append(1)
            raise ValueError("something else")

        with pytest.raises(ValueError, match="something else"):
            storage._with_retry(_fn)

        assert len(attempts) == 1

    def test_exponential_backoff(self, storage):
        attempts = []

        def _fn(session):
            attempts.append(1)
            if len(attempts) < 3:
                raise _make_sa_operational_error("database is locked")
            return "ok"

        with patch("storage.sqlite.time.sleep") as mock_sleep:
            storage._with_retry(_fn)

        assert mock_sleep.call_count == 2
        first_delay = mock_sleep.call_args_list[0][0][0]
        second_delay = mock_sleep.call_args_list[1][0][0]
        assert second_delay > first_delay


# ── Integration test: concurrent writer ─────────────────────────────────


class TestConcurrentWriteDoesNotFail:
    @pytest.fixture
    def storage(self, tmp_path):
        return SQLiteStorageProvider(f"sqlite:///{tmp_path / 'concurrent_write.db'}")

    def test_feedback_during_concurrent_write(self, storage):
        """Simulate the original bug: a feedback write while another writer holds the lock."""
        from core.contracts import build_source_item
        from core.models import new_id

        item = build_source_item(
            source_type="test",
            source_id="concurrent-test-1",
            content_type="text/plain",
            content="test content",
            metadata=None,
            use_case="demo",
            processing_status="pending",
        )
        storage.create_source_item(item)

        memory_id = new_id()
        barrier = threading.Barrier(2, timeout=10)
        errors = []

        def hold_write_lock():
            """Hold a write lock for 2 seconds using BEGIN IMMEDIATE."""
            import sqlite3
            db_path = storage._engine.url.database
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA busy_timeout=0")
            conn.execute("BEGIN IMMEDIATE")
            barrier.wait()
            time.sleep(2)
            conn.execute("COMMIT")
            conn.close()

        def write_feedback():
            """Try to write feedback while lock is held."""
            barrier.wait()
            time.sleep(0.1)
            try:
                storage.record_memory_feedback(
                    memory_object_id=memory_id,
                    rating="relevant",
                    reason="test",
                    query_context="concurrent test",
                    query_audit_log_id=None,
                    rater_ref="test-worker",
                )
            except Exception as exc:
                errors.append(exc)

        lock_thread = threading.Thread(target=hold_write_lock)
        feedback_thread = threading.Thread(target=write_feedback)

        lock_thread.start()
        feedback_thread.start()
        lock_thread.join(timeout=15)
        feedback_thread.join(timeout=15)

        assert not errors, f"Feedback write failed: {errors[0]}"


class TestImmediateTransactionRetry:
    @pytest.fixture
    def storage(self, tmp_path):
        storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'immediate_retry.db'}")
        try:
            yield storage
        finally:
            storage.close()

    def test_relay_native_wait_uses_remaining_local_acquisition_budget(self, storage, monkeypatch):
        from storage import sqlite_queue
        clock = [0.0]
        local = MagicMock()
        def admitted(*, timeout):
            assert timeout == pytest.approx(0.45)
            clock[0] = 0.35
            return True
        local.acquire.side_effect = admitted
        storage._relay_writer_lock = local
        monkeypatch.setattr(sqlite_queue, "time", SimpleNamespace(
            **{**vars(sqlite_queue.time), "monotonic": lambda: clock[0]},
        ))
        session, connection = MagicMock(), MagicMock()
        session.connection.return_value = connection
        storage._relay_session_factory = lambda: session
        bodies = []
        with storage._begin_relay_immediate():
            bodies.append(1)
        statements = [str(call.args[0]) for call in connection.execute.call_args_list]
        assert bodies == [1] and session.flush.call_count == 1
        assert statements.count("BEGIN IMMEDIATE") == statements.count("COMMIT") == 1
        assert statements[-1] == "PRAGMA busy_timeout=15000" and session.close.call_count == 1
        assert "PRAGMA busy_timeout=100" in statements, statements
        local.acquire.assert_called_once()
        local.release.assert_called_once()

    @pytest.mark.parametrize("boundary", ["local_refusal", "local_expired", "setup_expired", "begin_expired", "pause_does_not_fit", "second_pause_does_not_fit", "setup_expired_last", "begin_expired_last"])
    def test_relay_acquisition_deadline_refuses_without_replaying_work(self, storage, monkeypatch, boundary):
        from storage import sqlite_queue
        if boundary.endswith("_last"):
            monkeypatch.setattr(storage, "_RELAY_IMMEDIATE_ATTEMPTS", 1)
            boundary = boundary.removesuffix("_last")
        clock, attempts, bodies, sleeps, sessions = [0.0], [], [], [], []
        local = MagicMock()
        def admit(*, timeout):
            assert timeout <= .45
            clock[0] = {"local_expired": .45, "pause_does_not_fit": .41,
                        "second_pause_does_not_fit": .32}.get(boundary, 0.0)
            return boundary != "local_refusal"
        local.acquire.side_effect = admit
        storage._relay_writer_lock = local
        def sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds
        monkeypatch.setattr(sqlite_queue, "time", SimpleNamespace(
            **{**vars(sqlite_queue.time), "monotonic": lambda: clock[0], "sleep": sleep},
        ))
        def factory():
            session, connection = MagicMock(), MagicMock()
            def connect(**_kwargs):
                if boundary == "setup_expired":
                    clock[0] = .46
                return connection
            session.connection.side_effect = connect
            def execute(statement):
                if str(statement) != "BEGIN IMMEDIATE":
                    return
                attempts.append(1)
                if boundary == "begin_expired":
                    clock[0] = .46
                elif boundary in {"pause_does_not_fit", "second_pause_does_not_fit"}:
                    raise _make_sa_operational_error("disk I/O error")
            connection.execute.side_effect = execute
            sessions.append((session, connection))
            return session
        storage._relay_session_factory = factory
        with pytest.raises(ImmediateTransactionBusyError, match="database is locked") as refusal:
            with storage._begin_relay_immediate():
                bodies.append(1)
        assert refusal.value.acquisition_stage == {
            "local_refusal": "local_gate", "local_expired": "pre_attempt_deadline",
            "setup_expired": "setup_deadline", "begin_expired": "late_begin",
            "pause_does_not_fit": "backoff_no_fit", "second_pause_does_not_fit": "backoff_no_fit",
        }[boundary]
        assert refusal.value.args == ("database is locked (immediate transaction retry exhausted)",)
        assert bodies == []
        expected = {"begin_expired": 1, "pause_does_not_fit": 1, "second_pause_does_not_fit": 2}.get(boundary, 0)
        assert len(attempts) == expected
        assert sleeps == ([.05] if boundary == "second_pause_does_not_fit" else [])
        assert local.release.call_count == (0 if boundary == "local_refusal" else 1)
        assert len(sessions) == (0 if boundary in {"local_refusal", "local_expired"} else max(1, expected))
        for session, connection in sessions:
            assert session.close.call_count == 1 and not session.flush.called
            statements = [str(call.args[0]) for call in connection.execute.call_args_list]
            assert "COMMIT" not in statements and statements[-1] == "PRAGMA busy_timeout=15000"
            if boundary == "begin_expired":
                assert statements.count("ROLLBACK") == 1

    @pytest.mark.parametrize("failure", ["setup", "begin", "body", "flush", "commit", "rollback", "close"])
    def test_relay_writer_releases_on_every_exception_before_fresh_acquisition(self, storage, failure, monkeypatch):
        from storage import sqlite_queue

        # Exception cleanup is modeled here; native deadlines have separate coverage.
        native_monotonic = time.monotonic
        monkeypatch.setattr(sqlite_queue, "time", SimpleNamespace(
            **{**vars(time), "monotonic": lambda: 0.0},
        ))
        assert time.monotonic is native_monotonic
        assert sqlite_queue.time.sleep is time.sleep
        session, connection = MagicMock(), MagicMock()
        session.connection.return_value = connection
        storage._relay_session_factory = lambda: session
        bodies = []
        def execute(statement):
            if failure == "begin" and str(statement) == "BEGIN IMMEDIATE":
                raise KeyboardInterrupt("controlled begin interruption")
            if failure == "commit" and str(statement) == "COMMIT":
                raise RuntimeError("controlled commit failure")
            if failure == "rollback" and str(statement) == "ROLLBACK":
                raise RuntimeError("controlled rollback failure")
        connection.execute.side_effect = execute
        if failure == "setup":
            session.connection.side_effect = KeyboardInterrupt("controlled setup interruption")
        elif failure == "flush":
            session.flush.side_effect = RuntimeError("controlled flush failure")
        elif failure == "close":
            session.close.side_effect = RuntimeError("controlled close failure")
        error = KeyboardInterrupt if failure in {"setup", "begin", "body"} else (ValueError if failure == "rollback" else RuntimeError)
        with pytest.raises(error):
            with storage._begin_relay_immediate():
                bodies.append(1)
                if failure == "body":
                    raise KeyboardInterrupt("controlled body interruption")
                if failure == "rollback":
                    raise ValueError("controlled body failure")
        assert bodies == ([] if failure in {"setup", "begin"} else [1])
        assert not storage._relay_writer_lock.locked()
        assert session.close.call_count == 1
        fresh = MagicMock()
        storage._relay_session_factory = lambda: fresh
        with storage._begin_relay_immediate() as active:
            assert active is fresh
        assert fresh.flush.call_count == fresh.close.call_count == 1
        assert not storage._relay_writer_lock.locked()
        assert time.monotonic is native_monotonic
        assert sqlite_queue.time.sleep is time.sleep

    def test_same_provider_writer_waits_locally_before_native_begin(self, storage):
        from sqlalchemy import event
        started, native, finished = threading.Event(), threading.Event(), threading.Event()
        errors = []
        owner = storage._relay_writer_lock
        def acquire(*args, **kwargs):
            if threading.current_thread().name == "relay-local-contender":
                started.set()
            return owner.acquire(*args, **kwargs)
        storage._relay_writer_lock = SimpleNamespace(acquire=acquire, release=owner.release, locked=owner.locked)
        def observe(_conn, _cursor, statement, _params, _context, _many):
            if threading.current_thread().name == "relay-local-contender" and statement == "BEGIN IMMEDIATE":
                native.set()
        event.listen(storage._relay_engine, "before_cursor_execute", observe)
        def contender():
            try:
                with storage._begin_relay_immediate() as db:
                    assert db.execute(text("SELECT 1")).scalar_one() == 1
                finished.set()
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=contender, name="relay-local-contender")
        try:
            with storage._begin_relay_immediate():
                thread.start()
                assert started.wait(2)
                native_entered_while_held = native.wait(.05)
            thread.join(2)
        finally:
            if thread.ident is not None:
                thread.join(2)
            event.remove(storage._relay_engine, "before_cursor_execute", observe)
        assert not thread.is_alive() and errors == [] and finished.is_set()
        assert not native_entered_while_held
        assert native.is_set() and not storage._relay_writer_lock.locked()

    def test_maintenance_provider_keeps_independent_mutex_and_sqlite_arbitration(self, storage):
        maintenance = SQLiteStorageProvider.open_relay_maintenance(str(storage._relay_engine.url))
        bodies = []
        try:
            assert maintenance._relay_writer_lock is not storage._relay_writer_lock
            with storage._begin_relay_immediate():
                with pytest.raises(ImmediateTransactionBusyError):
                    with maintenance._begin_relay_immediate():
                        bodies.append(1)
                assert not maintenance._relay_writer_lock.locked()
            assert bodies == []
            with maintenance._begin_relay_immediate() as db:
                assert db.execute(text("SELECT 1")).scalar_one() == 1
            assert not maintenance._relay_writer_lock.locked()
        finally:
            maintenance.close()

    def test_immediate_transaction_retries_acquisition_without_replaying_work(self, storage):
        attempts = []
        sessions = []

        def session_factory():
            session = MagicMock()
            connection = MagicMock()
            session.connection.return_value = connection

            def execute(statement):
                if str(statement) == "BEGIN IMMEDIATE":
                    attempts.append(1)
                    if len(attempts) < 3:
                        raise _make_sa_operational_error("database is locked")

            connection.execute.side_effect = execute
            sessions.append(session)
            return session

        storage._session_factory = session_factory
        with patch("storage.sqlite_queue.time.sleep") as sleep:
            with storage._begin_immediate() as active:
                assert active is sessions[-1]

        assert len(attempts) == 3
        assert sleep.call_count == 2
        assert [call.args[0] for call in sleep.call_args_list] == [0.05, 0.1]
        assert sessions[0].close.called and sessions[1].close.called
        assert sessions[-1].flush.call_count == 1
        for session in sessions:
            statements = [
                str(call.args[0])
                for call in session.connection.return_value.execute.call_args_list
            ]
            assert "PRAGMA busy_timeout=1000" in statements

    def test_relay_transaction_retains_short_busy_timeout(self, storage):
        session = MagicMock()
        connection = MagicMock()
        session.connection.return_value = connection
        storage._relay_session_factory = lambda: session

        with storage._begin_relay_immediate() as active:
            assert active is session

        statements = [str(call.args[0]) for call in connection.execute.call_args_list]
        assert "PRAGMA busy_timeout=150" in statements
        assert "PRAGMA busy_timeout=1000" not in statements

    @pytest.mark.parametrize("failure", ["locked_twice", "locked_all", "nontransient", "body", "unknown", "io", "table_locked", "busy_snapshot"])
    def test_relay_acquisition_retains_native_wait_without_outer_backoff(self, storage, monkeypatch, failure):
        from storage import sqlite_queue
        sessions, attempts, bodies = [], [], []
        clock = [0.0]
        def advance(seconds):
            clock[0] += seconds
        sleep = MagicMock(side_effect=advance)
        monkeypatch.setattr(sqlite_queue, "time", SimpleNamespace(
            **{**vars(sqlite_queue.time), "monotonic": lambda: clock[0], "sleep": sleep},
        ))

        def factory():
            session, connection = MagicMock(), MagicMock()
            session.connection.return_value = connection
            def execute(statement):
                if str(statement) != "BEGIN IMMEDIATE":
                    return None
                attempts.append(1)
                if failure == "nontransient":
                    raise _make_sa_operational_error("no such table: missing")
                if failure == "locked_all" or (failure == "locked_twice" and len(attempts) < 3):
                    import sqlite3
                    error = _make_sa_operational_error("database is locked")
                    error.orig.sqlite_errorcode = sqlite3.SQLITE_BUSY
                    raise error
                if failure in {"unknown", "io", "table_locked", "busy_snapshot"} and len(attempts) < 3:
                    import sqlite3
                    error = _make_sa_operational_error("disk I/O error" if failure == "io" else "database is locked")
                    codes = {"io": sqlite3.SQLITE_IOERR, "table_locked": sqlite3.SQLITE_LOCKED,
                             "busy_snapshot": sqlite3.SQLITE_BUSY_SNAPSHOT}
                    if failure in codes:
                        error.orig.sqlite_errorcode = codes[failure]
                    raise error
            connection.execute.side_effect = execute
            sessions.append(session)
            return session
        storage._relay_session_factory = factory
        def acquire():
            with storage._begin_relay_immediate():
                bodies.append(1)
                if failure == "body":
                    raise ValueError("controlled body refusal")
        if failure == "locked_all":
            import sqlite3
            with pytest.raises(ImmediateTransactionBusyError, match="database is locked") as refusal:
                acquire()
            assert refusal.value.acquisition_stage == "retry_exhausted"
            assert refusal.value.__cause__.orig.sqlite_errorcode == sqlite3.SQLITE_BUSY
        elif failure == "nontransient":
            with pytest.raises(SAOperationalError, match="no such table"):
                acquire()
        elif failure == "body":
            with pytest.raises(ValueError, match="controlled body refusal"):
                acquire()
        else:
            acquire()
        assert len(attempts) == (1 if failure in {"nontransient", "body"} else 3)
        assert bodies == ([] if failure in {"locked_all", "nontransient"} else [1])
        assert all(session.close.call_count == 1 for session in sessions)
        for session in sessions:
            statements = [str(call.args[0]) for call in session.connection.return_value.execute.call_args_list]
            assert "PRAGMA busy_timeout=150" in statements
            assert statements[-1] == "PRAGMA busy_timeout=15000"
        final = [str(call.args[0]) for call in sessions[-1].connection.return_value.execute.call_args_list]
        if failure not in {"locked_all", "nontransient", "body"}:
            assert final.count("COMMIT") == 1 and sessions[-1].flush.call_count == 1
        else:
            assert "COMMIT" not in final
        if failure == "body":
            assert "ROLLBACK" in final
        if failure in {"unknown", "io", "table_locked", "busy_snapshot"}:
            assert [call.args[0] for call in sleep.call_args_list] == [0.05, 0.1]
        else:
            assert sleep.call_count == 0
        assert storage._RELAY_IMMEDIATE_ATTEMPTS * storage._RELAY_IMMEDIATE_BUSY_TIMEOUT_MS == 450

    def test_immediate_transaction_restores_the_pooled_busy_timeout(self, storage):
        def timeout() -> int:
            with storage._session_factory() as session:
                return session.execute(text("PRAGMA busy_timeout")).scalar_one()

        before = timeout()
        with storage._begin_immediate():
            pass
        assert timeout() == before == 15_000

    def test_immediate_transaction_busy_rolls_back_without_partial_commit(self, storage):
        session = MagicMock()
        connection = MagicMock()
        session.connection.return_value = connection
        storage._session_factory = lambda: session

        with pytest.raises(ValueError, match="abort"):
            with storage._begin_immediate():
                raise ValueError("abort")

        statements = [str(call.args[0]) for call in connection.execute.call_args_list]
        assert "BEGIN IMMEDIATE" in statements
        assert "ROLLBACK" in statements
        assert "COMMIT" not in statements

    def test_immediate_transaction_busy_has_a_stable_error(self, storage):
        legacy = ImmediateTransactionBusyError("legacy", 7)
        annotated = ImmediateTransactionBusyError("legacy", 7, acquisition_stage="retry_exhausted")
        assert legacy.args == annotated.args == ("legacy", 7)
        assert str(legacy) == str(annotated) == str(RuntimeError("legacy", 7))
        assert legacy.acquisition_stage is None and annotated.acquisition_stage == "retry_exhausted"
        session = MagicMock()
        connection = MagicMock()
        session.connection.return_value = connection
        connection.execute.side_effect = lambda statement: (_ for _ in ()).throw(
            _make_sa_operational_error("database is locked")
        ) if str(statement) == "BEGIN IMMEDIATE" else None
        storage._session_factory = lambda: session

        with patch("storage.sqlite_queue.time.sleep"):
            with pytest.raises(ImmediateTransactionBusyError, match="database is locked"):
                with storage._begin_immediate():
                    pass
