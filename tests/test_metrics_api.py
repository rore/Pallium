"""Tests for metrics API endpoints in the dashboard."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from storage.metrics import MetricsStore
from storage.sqlite_schema import Base, MetricRecord
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES
from core.models import new_id


UTC = timezone.utc


def _test_config(tmp_path: Path) -> AppConfig:
    db_path = tmp_path / "test-metrics-api.db"
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{db_path}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )


def _seed_metric(
    app,
    *,
    category: str = "query",
    event_type: str = "injection",
    container_ref: str | None = None,
    thread_ref: str | None = None,
    value: float | None = None,
    payload: dict | None = None,
    timestamp: datetime | None = None,
) -> None:
    storage = app.state.pallium_service._storage
    ts = timestamp or datetime.now(UTC)
    with storage._session_factory() as session:
        session.add(MetricRecord(
            id=new_id(),
            timestamp=ts,
            category=category,
            event_type=event_type,
            container_ref=container_ref,
            thread_ref=thread_ref,
            actor_ref=None,
            value=value,
            payload_json=None,
        ))
        session.commit()


# ---------------------------------------------------------------------------
# /dashboard/api/metrics/query
# ---------------------------------------------------------------------------


class TestMetricsQueryEndpoint:

    def test_get_query_empty(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/metrics/query?category=query")
        assert resp.status_code == 200
        body = resp.json()
        assert body["metrics"] == []
        assert body["count"] == 0

    def test_get_query_returns_seeded_metrics(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_metric(app, category="query", event_type="injection")
            _seed_metric(app, category="query", event_type="skip")
            resp = client.get("/dashboard/api/metrics/query?category=query")
        body = resp.json()
        assert body["count"] == 2
        assert len(body["metrics"]) == 2
        m = body["metrics"][0]
        assert "id" in m
        assert "timestamp" in m
        assert "category" in m
        assert "event_type" in m

    def test_get_query_filters(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_metric(app, category="query", event_type="injection")
            _seed_metric(app, category="processing", event_type="item_processed")
            resp = client.get("/dashboard/api/metrics/query?category=processing")
        body = resp.json()
        assert body["count"] == 1
        assert body["metrics"][0]["category"] == "processing"
        assert body["metrics"][0]["event_type"] == "item_processed"

    def test_get_query_filter_by_event_type(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_metric(app, category="query", event_type="injection")
            _seed_metric(app, category="query", event_type="skip")
            _seed_metric(app, category="query", event_type="flag")
            resp = client.get("/dashboard/api/metrics/query?event_type=skip")
        body = resp.json()
        assert body["count"] == 1
        assert body["metrics"][0]["event_type"] == "skip"

    def test_get_query_filter_by_container_ref(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_metric(app, container_ref="git:repo/a")
            _seed_metric(app, container_ref="git:repo/b")
            resp = client.get("/dashboard/api/metrics/query?container_ref=git:repo/a")
        body = resp.json()
        assert body["count"] == 1
        assert body["metrics"][0]["container_ref"] == "git:repo/a"

    def test_get_query_filter_by_thread_ref(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_metric(app, thread_ref="thread-1")
            _seed_metric(app, thread_ref="thread-2")
            resp = client.get("/dashboard/api/metrics/query?thread_ref=thread-1")
        body = resp.json()
        assert body["count"] == 1
        assert body["metrics"][0]["thread_ref"] == "thread-1"

    def test_get_query_default_limit(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            for _ in range(5):
                _seed_metric(app)
            resp = client.get("/dashboard/api/metrics/query?category=query")
        body = resp.json()
        # Default limit is 100, we only seeded 5 query-category events
        assert body["count"] == 5

    def test_get_query_limit_capped_at_1000(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            for _ in range(3):
                _seed_metric(app)
            resp = client.get("/dashboard/api/metrics/query?limit=9999&category=query")
        body = resp.json()
        # Still returns all 3 — cap only matters when rows exceed 1000
        assert body["count"] == 3

    def test_get_query_since_filter(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_metric(app, timestamp=datetime(2024, 1, 1, tzinfo=UTC))
            _seed_metric(app, timestamp=datetime(2025, 6, 1, tzinfo=UTC))
            resp = client.get("/dashboard/api/metrics/query?since=2025-01-01T00:00:00&category=query")
        body = resp.json()
        assert body["count"] == 1

    def test_get_query_invalid_since_returns_422(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/metrics/query?since=not-a-date")
        assert resp.status_code == 422

    def test_get_query_invalid_until_returns_422(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/metrics/query?until=bad-date")
        assert resp.status_code == 422

    def test_get_query_metric_shape(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_metric(app, category="query", event_type="injection",
                         container_ref="git:repo/x", thread_ref="t-1", value=2.5)
            resp = client.get("/dashboard/api/metrics/query")
        body = resp.json()
        m = body["metrics"][0]
        assert m["category"] == "query"
        assert m["event_type"] == "injection"
        assert m["container_ref"] == "git:repo/x"
        assert m["thread_ref"] == "t-1"
        assert m["value"] == pytest.approx(2.5)
        assert "actor_ref" in m
        assert "payload" in m


# ---------------------------------------------------------------------------
# /dashboard/api/metrics/aggregate
# ---------------------------------------------------------------------------


class TestMetricsAggregateEndpoint:

    def test_get_aggregate_day(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_metric(app, timestamp=datetime(2026, 5, 1, 10, tzinfo=UTC))
            _seed_metric(app, timestamp=datetime(2026, 5, 1, 14, tzinfo=UTC))
            _seed_metric(app, timestamp=datetime(2026, 5, 2, 9, tzinfo=UTC))
            resp = client.get("/dashboard/api/metrics/aggregate?category=query")
        assert resp.status_code == 200
        body = resp.json()
        assert "buckets" in body
        day1 = next((b for b in body["buckets"] if b["bucket"] == "2026-05-01"), None)
        day2 = next((b for b in body["buckets"] if b["bucket"] == "2026-05-02"), None)
        assert day1 is not None and day1["count"] == 2
        assert day2 is not None and day2["count"] == 1

    def test_get_aggregate_hour(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_metric(app, timestamp=datetime(2026, 5, 1, 10, 0, tzinfo=UTC))
            _seed_metric(app, timestamp=datetime(2026, 5, 1, 10, 30, tzinfo=UTC))
            _seed_metric(app, timestamp=datetime(2026, 5, 1, 11, 0, tzinfo=UTC))
            resp = client.get("/dashboard/api/metrics/aggregate?category=query&group_by=hour")
        assert resp.status_code == 200
        body = resp.json()
        h10 = next((b for b in body["buckets"] if b["bucket"] == "2026-05-01T10"), None)
        h11 = next((b for b in body["buckets"] if b["bucket"] == "2026-05-01T11"), None)
        assert h10 is not None and h10["count"] == 2
        assert h11 is not None and h11["count"] == 1

    def test_get_aggregate_invalid_group_by(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/metrics/aggregate?category=query&group_by=month")
        assert resp.status_code == 422

    def test_get_aggregate_empty_when_no_data(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/metrics/aggregate?category=query")
        assert resp.status_code == 200
        assert resp.json()["buckets"] == []

    def test_get_aggregate_category_required(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/metrics/aggregate")
        # category is required — FastAPI returns 422
        assert resp.status_code == 422

    def test_get_aggregate_bucket_shape(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_metric(app, timestamp=datetime(2026, 5, 1, tzinfo=UTC), value=10.0)
            resp = client.get("/dashboard/api/metrics/aggregate?category=query")
        body = resp.json()
        b = body["buckets"][0]
        assert "bucket" in b
        assert "event_type" in b
        assert "count" in b
        assert "sum_value" in b
        assert "avg_value" in b


# ---------------------------------------------------------------------------
# /dashboard/api/metrics/totals
# ---------------------------------------------------------------------------


class TestMetricsTotalsEndpoint:
    """The /totals endpoint backs the dashboard's dual-time pattern.
    It returns per-event_type counts for two windows (recent + alltime) in
    one round-trip so the UI doesn't run multiple aggregates."""

    def test_category_required(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/metrics/totals")
        assert resp.status_code == 422

    def test_empty_returns_empty_dicts(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/metrics/totals?category=query")
        assert resp.status_code == 200
        body = resp.json()
        assert body["category"] == "query"
        assert body["window_hours"] == 24
        assert body["recent"] == {}
        assert body["alltime"] == {}
        assert "as_of" in body

    def test_separates_recent_from_alltime(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        old = datetime.now(UTC) - __import__("datetime").timedelta(days=10)
        recent = datetime.now(UTC)
        with TestClient(app) as client:
            # 1 old, 2 recent — both 'injection'
            _seed_metric(app, event_type="injection", timestamp=old)
            _seed_metric(app, event_type="injection", timestamp=recent)
            _seed_metric(app, event_type="injection", timestamp=recent)
            resp = client.get("/dashboard/api/metrics/totals?category=query")
        body = resp.json()
        assert body["recent"]["injection"]["count"] == 2
        assert body["alltime"]["injection"]["count"] == 3

    def test_sum_value_per_event_type(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_metric(app, event_type="injection", value=2.0)
            _seed_metric(app, event_type="injection", value=5.0)
            _seed_metric(app, event_type="skip", value=None)
            resp = client.get("/dashboard/api/metrics/totals?category=query")
        body = resp.json()
        assert body["recent"]["injection"]["count"] == 2
        assert body["recent"]["injection"]["sum_value"] == pytest.approx(7.0)
        assert body["recent"]["skip"]["count"] == 1
        assert body["recent"]["skip"]["sum_value"] == pytest.approx(0.0)

    def test_window_hours_param(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        from datetime import timedelta as _td
        now = datetime.now(UTC)
        with TestClient(app) as client:
            _seed_metric(app, timestamp=now - _td(hours=2))
            _seed_metric(app, timestamp=now - _td(hours=8))
            resp = client.get("/dashboard/api/metrics/totals?category=query&window_hours=4")
        body = resp.json()
        # Only the 2-hours-old metric is in the 4-hour window
        assert body["window_hours"] == 4
        assert body["recent"]["injection"]["count"] == 1
        assert body["alltime"]["injection"]["count"] == 2

    def test_window_hours_validated(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/metrics/totals?category=query&window_hours=0")
        assert resp.status_code == 422

    def test_container_ref_filter(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_metric(app, container_ref="git:repo/a", event_type="injection")
            _seed_metric(app, container_ref="git:repo/b", event_type="injection")
            resp = client.get(
                "/dashboard/api/metrics/totals?category=query&container_ref=git:repo/a"
            )
        body = resp.json()
        assert body["container_ref"] == "git:repo/a"
        assert body["recent"]["injection"]["count"] == 1
        assert body["alltime"]["injection"]["count"] == 1
