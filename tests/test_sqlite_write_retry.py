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
        return SQLiteStorageProvider(f"sqlite:///{tmp_path / 'immediate_retry.db'}")

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
        sleep = MagicMock()
        monkeypatch.setattr(sqlite_queue, "time", SimpleNamespace(**{**vars(sqlite_queue.time), "sleep": sleep}))

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
            with pytest.raises(ImmediateTransactionBusyError, match="database is locked"):
                acquire()
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
