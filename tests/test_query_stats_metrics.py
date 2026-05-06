"""Tests for QueryStats → MetricsStore persistence integration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.observability import QueryStats
from storage.metrics import MetricsStore
from storage.sqlite_schema import Base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeResult:
    should_inject: bool = False
    decision_reason: str = "unknown"
    injectable_blocks: list = field(default_factory=list)
    container_ref: str | None = None
    thread_ref: str | None = None


def _injection_result(
    block_count: int = 2,
    container_ref: str | None = None,
    thread_ref: str | None = None,
) -> _FakeResult:
    return _FakeResult(
        should_inject=True,
        decision_reason="inject",
        injectable_blocks=[object() for _ in range(block_count)],
        container_ref=container_ref,
        thread_ref=thread_ref,
    )


def _skip_result(
    reason: str = "gate_blocked",
    container_ref: str | None = None,
    thread_ref: str | None = None,
) -> _FakeResult:
    return _FakeResult(
        should_inject=False,
        decision_reason=reason,
        container_ref=container_ref,
        thread_ref=thread_ref,
    )


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def store(session_factory):
    return MetricsStore(session_factory)


@pytest.fixture
def stats(store):
    return QueryStats(metrics_store=store)


# ---------------------------------------------------------------------------
# test_record_query_injection_persists
# ---------------------------------------------------------------------------


def test_record_query_injection_persists(stats: QueryStats, store: MetricsStore) -> None:
    stats.record_query(_injection_result(block_count=3))

    rows = store.query(category="query", event_type="injection")
    assert len(rows) == 1
    row = rows[0]
    assert row.category == "query"
    assert row.event_type == "injection"
    assert row.value == pytest.approx(3.0)
    assert row.payload is not None
    assert row.payload.get("decision_reason") == "inject"


def test_record_query_injection_persists_with_refs(stats: QueryStats, store: MetricsStore) -> None:
    stats.record_query(_injection_result(
        block_count=2,
        container_ref="git:repo/foo",
        thread_ref="thread-abc",
    ))

    rows = store.query(category="query", event_type="injection")
    assert len(rows) == 1
    assert rows[0].container_ref == "git:repo/foo"
    assert rows[0].thread_ref == "thread-abc"


# ---------------------------------------------------------------------------
# test_record_query_skip_persists
# ---------------------------------------------------------------------------


def test_record_query_skip_persists(stats: QueryStats, store: MetricsStore) -> None:
    stats.record_query(_skip_result(reason="no_relevant_memory"))

    rows = store.query(category="query", event_type="skip")
    assert len(rows) == 1
    row = rows[0]
    assert row.category == "query"
    assert row.event_type == "skip"
    assert row.payload is not None
    assert row.payload.get("decision_reason") == "no_relevant_memory"
    assert row.payload.get("skip_reason") == "no_relevant_memory"


def test_record_query_skip_persists_with_refs(stats: QueryStats, store: MetricsStore) -> None:
    stats.record_query(_skip_result(
        reason="gate_blocked",
        container_ref="git:repo/bar",
        thread_ref="thread-xyz",
    ))

    rows = store.query(category="query", event_type="skip")
    assert len(rows) == 1
    assert rows[0].container_ref == "git:repo/bar"
    assert rows[0].thread_ref == "thread-xyz"


# ---------------------------------------------------------------------------
# test_record_flag_persists
# ---------------------------------------------------------------------------


def test_record_flag_persists_not_suppressed(stats: QueryStats, store: MetricsStore) -> None:
    stats.record_flag(suppressed=False)

    rows = store.query(category="query", event_type="flag")
    assert len(rows) == 1
    assert rows[0].payload == {"suppressed": False}


def test_record_flag_persists_suppressed(stats: QueryStats, store: MetricsStore) -> None:
    stats.record_flag(suppressed=True)

    rows = store.query(category="query", event_type="flag")
    assert len(rows) == 1
    assert rows[0].payload == {"suppressed": True}


def test_record_flag_persists_multiple(stats: QueryStats, store: MetricsStore) -> None:
    stats.record_flag(suppressed=True)
    stats.record_flag(suppressed=False)
    stats.record_flag(suppressed=True)

    rows = store.query(category="query", event_type="flag")
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# test_record_feedback_persists
# ---------------------------------------------------------------------------


def test_record_feedback_persists(stats: QueryStats, store: MetricsStore) -> None:
    stats.record_feedback(
        "mem-123",
        "relevant",
        container_ref="git:repo/foo",
        thread_ref="thread-1",
    )

    rows = store.query(category="query", event_type="feedback")
    assert len(rows) == 1
    row = rows[0]
    assert row.payload == {"memory_object_id": "mem-123", "rating": "relevant"}
    assert row.container_ref == "git:repo/foo"
    assert row.thread_ref == "thread-1"


def test_record_feedback_not_relevant(stats: QueryStats, store: MetricsStore) -> None:
    stats.record_feedback("mem-456", "not_relevant")

    rows = store.query(category="query", event_type="feedback")
    assert len(rows) == 1
    assert rows[0].payload == {"memory_object_id": "mem-456", "rating": "not_relevant"}
    assert rows[0].container_ref is None
    assert rows[0].thread_ref is None


# ---------------------------------------------------------------------------
# test_metrics_store_none_graceful
# ---------------------------------------------------------------------------


def test_metrics_store_none_graceful() -> None:
    stats = QueryStats()  # metrics_store=None by default

    # None of these should raise
    stats.record_query(_injection_result())
    stats.record_query(_skip_result())
    stats.record_flag(suppressed=True)
    stats.record_feedback("mem-001", "relevant")

    snap = stats.snapshot()
    assert snap["total_queries"] == 2
    assert snap["total_injections"] == 1
    assert snap["total_skips"] == 1
    assert snap["total_flags"] == 1


# ---------------------------------------------------------------------------
# test_metrics_failure_does_not_block_query
# ---------------------------------------------------------------------------


def test_metrics_failure_does_not_block_query() -> None:
    """A broken MetricsStore must not affect in-memory counters."""
    class BrokenStore:
        def record(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("database is down")

    stats = QueryStats(metrics_store=BrokenStore())

    stats.record_query(_injection_result(block_count=2))
    stats.record_query(_skip_result())
    stats.record_flag(suppressed=False)

    snap = stats.snapshot()
    assert snap["total_queries"] == 2
    assert snap["total_injections"] == 1
    assert snap["total_skips"] == 1
    assert snap["total_flags"] == 1
    assert snap["total_suppressions"] == 0


# ---------------------------------------------------------------------------
# test_in_memory_and_persistent_stay_consistent
# ---------------------------------------------------------------------------


def test_in_memory_and_persistent_stay_consistent(stats: QueryStats, store: MetricsStore) -> None:
    """In-memory counters and persisted event count must agree."""
    stats.record_query(_injection_result(block_count=1))
    stats.record_query(_injection_result(block_count=3))
    stats.record_query(_skip_result("no_relevant_memory"))
    stats.record_query(_skip_result("gate_blocked"))
    stats.record_flag(suppressed=False)
    stats.record_flag(suppressed=True)

    snap = stats.snapshot()
    assert snap["total_queries"] == 4
    assert snap["total_injections"] == 2
    assert snap["total_skips"] == 2
    assert snap["total_flags"] == 2
    assert snap["total_suppressions"] == 1

    persisted_injections = store.query(category="query", event_type="injection")
    persisted_skips = store.query(category="query", event_type="skip")
    persisted_flags = store.query(category="query", event_type="flag")

    assert len(persisted_injections) == snap["total_injections"]
    assert len(persisted_skips) == snap["total_skips"]
    assert len(persisted_flags) == snap["total_flags"]

    # Block count values match
    total_blocks_from_metrics = sum(
        r.value for r in persisted_injections if r.value is not None
    )
    assert total_blocks_from_metrics == pytest.approx(snap["total_blocks_injected"])
