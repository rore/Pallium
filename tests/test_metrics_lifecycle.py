"""Tests for metrics retention cleanup and system lifecycle events."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig, ObservabilityConfig, RetentionConfig
from app.main import create_app
from storage.metrics import MetricsStore
from storage.sqlite_schema import Base, MetricRecord
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES
from core.models import new_id

UTC = timezone.utc


def _test_config(tmp_path: Path, *, metrics_retention_days: int = 0, retention_enabled: bool = False) -> AppConfig:
    db_path = tmp_path / "test-lifecycle.db"
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{db_path}",
        default_use_case="demo_agent_memory",
        semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
        observability=ObservabilityConfig(
            metrics_retention_days=metrics_retention_days,
        ),
        retention=RetentionConfig(
            enabled=retention_enabled,
        ),
    )


def _insert_old_metric(app, *, days_old: int = 100) -> None:
    """Insert a metric record with a timestamp in the past."""
    storage = app.state.pallium_service._storage
    old_ts = datetime.now(UTC) - timedelta(days=days_old)
    with storage._session_factory() as session:
        session.add(MetricRecord(
            id=new_id(),
            timestamp=old_ts,
            category="query",
            event_type="injection",
            container_ref=None,
            thread_ref=None,
            actor_ref=None,
            value=None,
            payload_json=None,
        ))
        session.commit()


# ---------------------------------------------------------------------------
# test_service_start_records_metric
# ---------------------------------------------------------------------------


def test_service_start_records_metric(tmp_path: Path) -> None:
    """After create_app, a system/service_start metric must exist."""
    app = create_app(_test_config(tmp_path))
    with TestClient(app):
        ms: MetricsStore | None = app.state.metrics_store
        assert ms is not None
        rows = ms.query(category="system", event_type="service_start")
        assert len(rows) >= 1
        row = rows[0]
        assert row.category == "system"
        assert row.event_type == "service_start"
        assert row.payload is not None
        assert "packages_enabled" in row.payload


# ---------------------------------------------------------------------------
# test_retention_run_records_metric
# ---------------------------------------------------------------------------


def test_retention_run_records_metric(tmp_path: Path) -> None:
    """After run_retention_pass completes, a system/retention_run metric is present."""
    app = create_app(_test_config(tmp_path, retention_enabled=True))
    with TestClient(app):
        service = app.state.pallium_service
        ms: MetricsStore | None = app.state.metrics_store
        assert ms is not None

        # Run a retention pass
        service.run_retention_pass(worker_id="test-worker")

        rows = ms.query(category="system", event_type="retention_run")
        assert len(rows) >= 1
        row = rows[0]
        assert row.category == "system"
        assert row.event_type == "retention_run"
        assert row.payload is not None
        assert "deleted_source_items" in row.payload
        assert "deleted_memory_objects" in row.payload


# ---------------------------------------------------------------------------
# test_retention_cleanup_called_when_configured
# ---------------------------------------------------------------------------


def test_retention_cleanup_called_when_configured(tmp_path: Path) -> None:
    """With metrics_retention_days > 0, old metrics are removed during retention pass."""
    app = create_app(_test_config(tmp_path, metrics_retention_days=30, retention_enabled=True))
    with TestClient(app):
        service = app.state.pallium_service
        ms: MetricsStore | None = app.state.metrics_store
        assert ms is not None

        # Insert an old metric (100 days ago) directly
        _insert_old_metric(app, days_old=100)

        # Verify the old metric is present before cleanup
        all_rows_before = ms.query(limit=1000)
        old_rows_before = [r for r in all_rows_before if r.category == "query" and r.event_type == "injection"]
        assert len(old_rows_before) >= 1

        # Run retention pass — this should also trigger metrics cleanup
        service.run_retention_pass(worker_id="test-worker")

        # The old metric (100 days old, retention=30 days) should be gone
        all_rows_after = ms.query(limit=1000)
        old_rows_after = [r for r in all_rows_after if r.category == "query" and r.event_type == "injection"]
        assert len(old_rows_after) == 0


# ---------------------------------------------------------------------------
# test_retention_cleanup_skipped_when_zero
# ---------------------------------------------------------------------------


def test_retention_cleanup_skipped_when_zero(tmp_path: Path) -> None:
    """With metrics_retention_days=0, old metrics are not cleaned up."""
    app = create_app(_test_config(tmp_path, metrics_retention_days=0, retention_enabled=True))
    with TestClient(app):
        service = app.state.pallium_service
        ms: MetricsStore | None = app.state.metrics_store
        assert ms is not None

        # Insert an old metric (100 days ago)
        _insert_old_metric(app, days_old=100)

        # Run retention pass — cleanup should be skipped (retention_days=0)
        service.run_retention_pass(worker_id="test-worker")

        # The old metric should still be present
        all_rows = ms.query(limit=1000)
        old_rows = [r for r in all_rows if r.category == "query" and r.event_type == "injection"]
        assert len(old_rows) >= 1


# ---------------------------------------------------------------------------
# test_status_includes_metrics_summary
# ---------------------------------------------------------------------------


def test_status_includes_metrics_summary(tmp_path: Path) -> None:
    """/status response must include metrics_summary with events_24h."""
    app = create_app(_test_config(tmp_path))
    with TestClient(app) as client:
        resp = client.get("/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "metrics_summary" in body
    summary = body["metrics_summary"]
    assert summary is not None
    assert "events_24h" in summary
    assert "events_24h_by_category" in summary
    # service_start is recorded on startup, so we expect at least 1 event
    assert summary["events_24h"] >= 1
    assert "system" in summary["events_24h_by_category"]
