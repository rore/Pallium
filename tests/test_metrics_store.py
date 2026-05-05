"""Tests for MetricsStore — persistent operational event recording."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from storage.metrics import AggregateBucket, MetricRow, MetricsStore
from storage.sqlite_schema import Base


UTC = timezone.utc


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def store(session_factory):
    return MetricsStore(session_factory)


# ---------------------------------------------------------------------------
# Basic record + query
# ---------------------------------------------------------------------------


def test_record_and_query_basic(store: MetricsStore) -> None:
    store.record("query", "injection")
    rows = store.query()
    assert len(rows) == 1
    row = rows[0]
    assert row.category == "query"
    assert row.event_type == "injection"
    assert isinstance(row.id, str) and row.id
    assert isinstance(row.timestamp, datetime)


def test_record_all_fields(store: MetricsStore) -> None:
    store.record(
        "query",
        "injection",
        container_ref="git:repo/foo",
        thread_ref="thread-1",
        actor_ref="user-42",
        value=3.14,
        payload={"key": "val"},
    )
    rows = store.query()
    assert len(rows) == 1
    row = rows[0]
    assert row.container_ref == "git:repo/foo"
    assert row.thread_ref == "thread-1"
    assert row.actor_ref == "user-42"
    assert row.value == pytest.approx(3.14)
    assert row.payload == {"key": "val"}


# ---------------------------------------------------------------------------
# Filter tests
# ---------------------------------------------------------------------------


def test_query_filter_by_category(store: MetricsStore) -> None:
    store.record("query", "injection")
    store.record("processing", "item_processed")
    store.record("system", "service_start")

    rows = store.query(category="processing")
    assert len(rows) == 1
    assert rows[0].category == "processing"


def test_query_filter_by_event_type(store: MetricsStore) -> None:
    store.record("query", "injection")
    store.record("query", "skip")
    store.record("query", "flag")

    rows = store.query(event_type="skip")
    assert len(rows) == 1
    assert rows[0].event_type == "skip"


def test_query_filter_by_container_ref(store: MetricsStore) -> None:
    store.record("query", "injection", container_ref="git:repo/a")
    store.record("query", "injection", container_ref="git:repo/b")
    store.record("query", "injection")  # no container

    rows = store.query(container_ref="git:repo/a")
    assert len(rows) == 1
    assert rows[0].container_ref == "git:repo/a"


def test_query_filter_by_thread_ref(store: MetricsStore) -> None:
    store.record("query", "injection", thread_ref="thread-x")
    store.record("query", "injection", thread_ref="thread-y")

    rows = store.query(thread_ref="thread-x")
    assert len(rows) == 1
    assert rows[0].thread_ref == "thread-x"


def test_query_filter_by_time_range_since(store: MetricsStore, session_factory) -> None:
    past = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    future = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
    cutoff = datetime(2025, 1, 1, tzinfo=UTC)

    # Insert records with explicit timestamps directly
    from storage.sqlite_schema import MetricRecord
    from core.models import new_id

    with session_factory() as session:
        session.add(MetricRecord(
            id=new_id(), timestamp=past, category="query", event_type="injection",
            container_ref=None, thread_ref=None, actor_ref=None, value=None, payload_json=None,
        ))
        session.add(MetricRecord(
            id=new_id(), timestamp=future, category="query", event_type="injection",
            container_ref=None, thread_ref=None, actor_ref=None, value=None, payload_json=None,
        ))
        session.commit()

    rows = store.query(since=cutoff)
    assert len(rows) == 1
    # SQLite returns naive datetimes; compare without tzinfo
    assert rows[0].timestamp.replace(tzinfo=None) == future.replace(tzinfo=None)


def test_query_filter_by_time_range_until(store: MetricsStore, session_factory) -> None:
    past = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    future = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
    cutoff = datetime(2025, 1, 1, tzinfo=UTC)

    from storage.sqlite_schema import MetricRecord
    from core.models import new_id

    with session_factory() as session:
        session.add(MetricRecord(
            id=new_id(), timestamp=past, category="query", event_type="injection",
            container_ref=None, thread_ref=None, actor_ref=None, value=None, payload_json=None,
        ))
        session.add(MetricRecord(
            id=new_id(), timestamp=future, category="query", event_type="injection",
            container_ref=None, thread_ref=None, actor_ref=None, value=None, payload_json=None,
        ))
        session.commit()

    rows = store.query(until=cutoff)
    assert len(rows) == 1
    # SQLite returns naive datetimes; compare without tzinfo
    assert rows[0].timestamp.replace(tzinfo=None) == past.replace(tzinfo=None)


def test_query_filter_by_time_range_window(store: MetricsStore, session_factory) -> None:
    ts1 = datetime(2024, 1, 1, tzinfo=UTC)
    ts2 = datetime(2024, 6, 1, tzinfo=UTC)
    ts3 = datetime(2024, 12, 1, tzinfo=UTC)

    from storage.sqlite_schema import MetricRecord
    from core.models import new_id

    with session_factory() as session:
        for ts in [ts1, ts2, ts3]:
            session.add(MetricRecord(
                id=new_id(), timestamp=ts, category="query", event_type="injection",
                container_ref=None, thread_ref=None, actor_ref=None, value=None, payload_json=None,
            ))
        session.commit()

    since = datetime(2024, 3, 1, tzinfo=UTC)
    until = datetime(2024, 9, 1, tzinfo=UTC)
    rows = store.query(since=since, until=until)
    assert len(rows) == 1
    # SQLite returns naive datetimes; compare without tzinfo
    assert rows[0].timestamp.replace(tzinfo=None) == ts2.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Limit and ordering
# ---------------------------------------------------------------------------


def test_query_limit(store: MetricsStore, session_factory) -> None:
    from storage.sqlite_schema import MetricRecord
    from core.models import new_id

    # Insert 5 records with increasing timestamps
    with session_factory() as session:
        for i in range(5):
            ts = datetime(2024, 1, i + 1, tzinfo=UTC)
            session.add(MetricRecord(
                id=new_id(), timestamp=ts, category="query", event_type="injection",
                container_ref=None, thread_ref=None, actor_ref=None, value=None, payload_json=None,
            ))
        session.commit()

    rows = store.query(limit=3)
    assert len(rows) == 3
    # Should be ordered by timestamp desc — most recent first
    assert rows[0].timestamp > rows[1].timestamp > rows[2].timestamp


def test_query_empty_table(store: MetricsStore) -> None:
    rows = store.query()
    assert rows == []


# ---------------------------------------------------------------------------
# Aggregate tests
# ---------------------------------------------------------------------------


def _insert_metric(session_factory, timestamp: datetime, category: str, event_type: str,
                   value: float | None = None, container_ref: str | None = None) -> None:
    from storage.sqlite_schema import MetricRecord
    from core.models import new_id

    with session_factory() as session:
        session.add(MetricRecord(
            id=new_id(), timestamp=timestamp, category=category, event_type=event_type,
            container_ref=container_ref, thread_ref=None, actor_ref=None,
            value=value, payload_json=None,
        ))
        session.commit()


def test_aggregate_by_day(store: MetricsStore, session_factory) -> None:
    _insert_metric(session_factory, datetime(2024, 6, 1, 10, tzinfo=UTC), "query", "injection")
    _insert_metric(session_factory, datetime(2024, 6, 1, 14, tzinfo=UTC), "query", "injection")
    _insert_metric(session_factory, datetime(2024, 6, 2, 9, tzinfo=UTC), "query", "injection")

    buckets = store.aggregate(category="query", group_by="day")
    assert len(buckets) == 2
    day1 = next(b for b in buckets if b.bucket == "2024-06-01")
    day2 = next(b for b in buckets if b.bucket == "2024-06-02")
    assert day1.count == 2
    assert day2.count == 1


def test_aggregate_by_hour(store: MetricsStore, session_factory) -> None:
    _insert_metric(session_factory, datetime(2024, 6, 1, 10, 0, tzinfo=UTC), "query", "injection")
    _insert_metric(session_factory, datetime(2024, 6, 1, 10, 30, tzinfo=UTC), "query", "injection")
    _insert_metric(session_factory, datetime(2024, 6, 1, 11, 0, tzinfo=UTC), "query", "injection")

    buckets = store.aggregate(category="query", group_by="hour")
    assert len(buckets) == 2
    h10 = next(b for b in buckets if b.bucket == "2024-06-01T10")
    h11 = next(b for b in buckets if b.bucket == "2024-06-01T11")
    assert h10.count == 2
    assert h11.count == 1


def test_aggregate_by_week(store: MetricsStore, session_factory) -> None:
    # 2024-06-03 is Monday of week 23; 2024-06-10 is Monday of week 24
    _insert_metric(session_factory, datetime(2024, 6, 3, tzinfo=UTC), "query", "injection")
    _insert_metric(session_factory, datetime(2024, 6, 4, tzinfo=UTC), "query", "injection")
    _insert_metric(session_factory, datetime(2024, 6, 10, tzinfo=UTC), "query", "injection")

    buckets = store.aggregate(category="query", group_by="week")
    assert len(buckets) == 2
    counts = {b.bucket: b.count for b in buckets}
    total = sum(counts.values())
    assert total == 3


def test_aggregate_returns_count_sum_avg(store: MetricsStore, session_factory) -> None:
    _insert_metric(session_factory, datetime(2024, 6, 1, tzinfo=UTC), "query", "injection", value=10.0)
    _insert_metric(session_factory, datetime(2024, 6, 1, tzinfo=UTC), "query", "injection", value=20.0)
    _insert_metric(session_factory, datetime(2024, 6, 1, tzinfo=UTC), "query", "injection", value=30.0)

    buckets = store.aggregate(category="query", group_by="day")
    assert len(buckets) == 1
    b = buckets[0]
    assert b.count == 3
    assert b.sum_value == pytest.approx(60.0)
    assert b.avg_value == pytest.approx(20.0)


def test_aggregate_with_null_values(store: MetricsStore, session_factory) -> None:
    _insert_metric(session_factory, datetime(2024, 6, 1, tzinfo=UTC), "query", "injection", value=None)
    _insert_metric(session_factory, datetime(2024, 6, 1, tzinfo=UTC), "query", "injection", value=None)

    buckets = store.aggregate(category="query", group_by="day")
    assert len(buckets) == 1
    b = buckets[0]
    assert b.count == 2
    assert b.sum_value == pytest.approx(0.0)
    assert b.avg_value == pytest.approx(0.0)


def test_aggregate_filter_by_container(store: MetricsStore, session_factory) -> None:
    _insert_metric(session_factory, datetime(2024, 6, 1, tzinfo=UTC), "query", "injection",
                   container_ref="git:repo/a")
    _insert_metric(session_factory, datetime(2024, 6, 1, tzinfo=UTC), "query", "injection",
                   container_ref="git:repo/b")

    buckets = store.aggregate(category="query", container_ref="git:repo/a", group_by="day")
    assert len(buckets) == 1
    assert buckets[0].count == 1


def test_aggregate_empty_range(store: MetricsStore, session_factory) -> None:
    _insert_metric(session_factory, datetime(2024, 6, 1, tzinfo=UTC), "query", "injection")

    buckets = store.aggregate(
        category="query",
        since=datetime(2025, 1, 1, tzinfo=UTC),
        until=datetime(2025, 12, 1, tzinfo=UTC),
        group_by="day",
    )
    assert buckets == []


# ---------------------------------------------------------------------------
# Cleanup tests
# ---------------------------------------------------------------------------


def test_cleanup_deletes_old_rows(store: MetricsStore, session_factory) -> None:
    old_ts = datetime.now(UTC) - timedelta(days=100)
    _insert_metric(session_factory, old_ts, "query", "injection")

    deleted = store.cleanup(retention_days=30)
    assert deleted >= 1
    rows = store.query()
    assert len(rows) == 0


def test_cleanup_preserves_recent_rows(store: MetricsStore, session_factory) -> None:
    recent_ts = datetime.now(UTC) - timedelta(days=1)
    _insert_metric(session_factory, recent_ts, "query", "injection")

    deleted = store.cleanup(retention_days=30)
    assert deleted == 0
    rows = store.query()
    assert len(rows) == 1


def test_cleanup_disabled_when_zero(store: MetricsStore, session_factory) -> None:
    old_ts = datetime.now(UTC) - timedelta(days=100)
    _insert_metric(session_factory, old_ts, "query", "injection")

    deleted = store.cleanup(retention_days=0)
    assert deleted == 0
    rows = store.query()
    assert len(rows) == 1


def test_cleanup_returns_count(store: MetricsStore, session_factory) -> None:
    old_ts = datetime.now(UTC) - timedelta(days=100)
    for _ in range(3):
        _insert_metric(session_factory, old_ts, "query", "injection")

    deleted = store.cleanup(retention_days=30)
    assert deleted == 3


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_record_with_none_payload(store: MetricsStore) -> None:
    store.record("query", "injection", payload=None)
    rows = store.query()
    assert len(rows) == 1
    assert rows[0].payload is None


def test_record_generates_unique_ids(store: MetricsStore) -> None:
    for _ in range(5):
        store.record("query", "injection")
    rows = store.query()
    ids = [r.id for r in rows]
    assert len(set(ids)) == 5


def test_record_failure_does_not_raise() -> None:
    def bad_session_factory():
        raise RuntimeError("database unavailable")

    store = MetricsStore(bad_session_factory)
    # Should not raise — fire-and-forget contract
    store.record("query", "injection")
