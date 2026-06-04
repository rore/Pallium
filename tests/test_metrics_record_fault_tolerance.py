"""Regression tests for `MetricsStore.record()` fault tolerance.

T1 design — proposed_metrics_patch.py. Two regressions:

1. Concurrent processor-side writers must not silently drop events. Either the
   row persists, OR a structured WARNING is emitted naming the metric. The old
   implementation swallowed the exception with a bare `pass`, so dropped events
   were invisible.

2. Single-threaded record + query (the `service_start` lifecycle path) must
   still produce exactly one row with the expected payload — i.e. the new
   retry/log shape is backward-compatible for the dominant non-contended case.

Uses a real `SQLiteStorageProvider` against a `tmp_path` SQLite file (NOT
`:memory:`) so WAL + busy_timeout are live and concurrency is realistic.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest

from storage.metrics import MetricsStore
from storage.sqlite import SQLiteStorageProvider


@pytest.fixture
def sqlite_storage(tmp_path: Path) -> SQLiteStorageProvider:
    db_path = tmp_path / "metrics_fault_tolerance.db"
    return SQLiteStorageProvider(database_url=f"sqlite:///{db_path}")


@pytest.fixture
def store(sqlite_storage: SQLiteStorageProvider) -> MetricsStore:
    return MetricsStore(sqlite_storage._session_factory)


def test_record_persists_under_processor_concurrency(
    store: MetricsStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Concurrent writers: every event either persists or surfaces a WARNING.

    The old implementation silently dropped under contention. The new shape
    must guarantee `persisted + warned >= total_attempts` so dropped events
    are never invisible.
    """
    threads_count = 2
    events_per_thread = 20
    total_expected = threads_count * events_per_thread

    caplog.set_level(logging.WARNING, logger="storage.metrics")

    def writer(thread_idx: int) -> None:
        for i in range(events_per_thread):
            store.record(
                "processing",
                "item_processed",
                container_ref=f"git:repo/concurrency-test",
                thread_ref=f"thread-{thread_idx}",
                value=float(i),
                payload={"thread_idx": thread_idx, "i": i},
            )

    threads = [
        threading.Thread(target=writer, args=(idx,))
        for idx in range(threads_count)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = store.query(category="processing", event_type="item_processed")
    warnings_for_record = [
        rec for rec in caplog.records
        if rec.levelno == logging.WARNING
        and "metrics.record dropped event" in rec.getMessage()
    ]

    # Either the row persisted or a WARNING surfaced — never both lost.
    assert len(rows) + len(warnings_for_record) >= total_expected, (
        f"Expected at least {total_expected} persisted-or-warned events; "
        f"got rows={len(rows)} warnings={len(warnings_for_record)}"
    )


def test_record_backward_compat_service_start(store: MetricsStore) -> None:
    """Single-threaded record + query: the dominant non-contended path is preserved."""
    store.record(
        "system",
        "service_start",
        payload={"packages_enabled": ["agent_conversation_memory"]},
    )

    rows = store.query(category="system", event_type="service_start")
    assert len(rows) == 1
    row = rows[0]
    assert row.category == "system"
    assert row.event_type == "service_start"
    assert row.payload == {"packages_enabled": ["agent_conversation_memory"]}


def test_record_does_not_raise_on_non_serializable_payload(store: MetricsStore, caplog) -> None:
    """Non-JSON-serializable payload must NOT raise out of `record()`.

    Codex P3 regression: the old implementation built `MetricRecord` (and ran
    `json.dumps(payload)`) before entering the try/except retry block, so a
    `TypeError` from the dumps call escaped the fire-and-forget contract.
    The fix moves serialization inside the guarded block; failure produces a
    structured WARNING and a dropped event, never a raise.
    """
    caplog.set_level(logging.WARNING, logger="storage.metrics")

    # Object instances are not JSON-serializable; this used to raise TypeError.
    store.record("processing", "item_processed", payload={"bad": object()})

    rows = store.query(category="processing", event_type="item_processed")
    assert rows == []
    warnings_for_record = [
        rec for rec in caplog.records
        if rec.levelno == logging.WARNING
        and "metrics.record dropped event" in rec.getMessage()
    ]
    assert len(warnings_for_record) == 1, (
        f"Expected exactly one drop-warning for the unserializable payload; "
        f"got {[r.getMessage() for r in warnings_for_record]}"
    )
    assert "TypeError" in warnings_for_record[0].getMessage()
