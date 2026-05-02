"""Tests for SQLite write retry logic (_with_retry).

Verifies that the storage layer handles transient 'database is locked' errors
correctly by retrying, and propagates non-transient errors immediately.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError as SAOperationalError

from core.contracts import build_source_item
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
            db_path = str(storage._engine.url).replace("sqlite:///", "")
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
