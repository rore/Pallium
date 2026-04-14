from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppConfig, SnapshotConfig
from app.main import create_app
from core.models import MemoryObject, SourceItem
from storage.vector_index import VectorIndexConfig


def _no_vector_config() -> AppConfig:
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url="sqlite:///:memory:",
        default_use_case="demo_agent_memory",
        vector_index=VectorIndexConfig(enabled=False),
    )


class TestHealthNoVector:

    def test_health_returns_200_when_no_vector_index(self) -> None:
        app = create_app(_no_vector_config())
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["vector_index_ready"] is True

    def test_health_json_body_shape(self) -> None:
        app = create_app(_no_vector_config())
        with TestClient(app) as client:
            body = client.get("/health").json()
        assert set(body.keys()) == {"status", "vector_index_ready"}


class TestHealthLifecycle:

    def test_lifespan_flag_starts_false(self) -> None:
        app = create_app(_no_vector_config())
        assert app.state._lifespan_complete is False
        assert app.state._reconcile_done is None

    def test_health_returns_503_before_lifespan(self) -> None:
        app = create_app(_no_vector_config())
        # Do NOT use context manager — lifespan will not run.
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "initializing"

    def test_health_returns_200_after_lifespan(self) -> None:
        app = create_app(_no_vector_config())
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestHealthWithVectorIndex:

    def test_health_503_when_vector_configured_but_reconcile_not_done(self) -> None:
        app = create_app(_no_vector_config())
        # Simulate: lifespan has run, vector index is configured, but reconcile
        # has not completed yet.
        app.state._lifespan_complete = True
        app.state._reconcile_done = threading.Event()  # not set
        service = app.state.pallium_service
        original_vi = service._vector_index
        service._vector_index = object()  # truthy sentinel

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "initializing"
        assert body["vector_index_ready"] is False

        service._vector_index = original_vi

    def test_health_200_when_vector_configured_and_reconcile_done(self) -> None:
        app = create_app(_no_vector_config())
        # Simulate: lifespan has run, vector index configured, reconcile done.
        app.state._lifespan_complete = True
        reconcile_done = threading.Event()
        reconcile_done.set()
        app.state._reconcile_done = reconcile_done
        service = app.state.pallium_service
        original_vi = service._vector_index
        service._vector_index = object()

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["vector_index_ready"] is True

        service._vector_index = original_vi

    def test_vector_index_ready_true_when_no_vector_configured(self) -> None:
        app = create_app(_no_vector_config())
        with TestClient(app) as client:
            body = client.get("/health").json()
        assert body["vector_index_ready"] is True


class TestHealthEndpointLocation:

    def test_old_router_health_removed(self) -> None:
        from api.routes import create_router
        from app.dependencies import build_service

        config = _no_vector_config()
        service = build_service(config)
        router = create_router(service)
        route_paths = [route.path for route in router.routes]
        assert "/health" not in route_paths


# ── /status endpoint tests ──────────────────────────────────────────────


def _file_db_config(tmp_path: Path, **overrides) -> AppConfig:
    """Create an AppConfig with a file-based temporary SQLite database.

    Using :memory: with SQLAlchemy's default pool can create separate
    in-memory databases per connection, which breaks direct SQL queries
    in the /status endpoint.
    """
    db_path = tmp_path / "test-status.db"
    defaults = dict(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{db_path}",
        default_use_case="demo_agent_memory",
        vector_index=VectorIndexConfig(enabled=False),
    )
    defaults.update(overrides)
    return AppConfig(**defaults)


class TestStatusResponseShape:

    def test_status_returns_200_always(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            response = client.get("/status")
        assert response.status_code == 200

    def test_status_response_has_all_top_level_keys(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        expected_keys = {
            "pending_items",
            "oldest_pending_age_seconds",
            "total_source_items",
            "total_memory_objects",
            "snapshot",
            "vector_index_ready",
            "uptime_seconds",
        }
        assert set(body.keys()) == expected_keys

    def test_status_snapshot_sub_keys(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        snapshot = body["snapshot"]
        assert set(snapshot.keys()) == {"enabled", "last_snapshot_at", "snapshot_count"}


class TestStatusEmptyDatabase:

    def test_counts_are_zero_on_empty_db(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        assert body["pending_items"] == 0
        assert body["oldest_pending_age_seconds"] is None
        assert body["total_source_items"] == 0
        assert body["total_memory_objects"] == 0

    def test_snapshot_disabled_by_default(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        assert body["snapshot"]["enabled"] is False
        assert body["snapshot"]["last_snapshot_at"] is None
        assert body["snapshot"]["snapshot_count"] == 0

    def test_uptime_is_positive(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        assert body["uptime_seconds"] >= 0

    def test_vector_index_ready_when_not_configured(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        with TestClient(app) as client:
            body = client.get("/status").json()
        assert body["vector_index_ready"] is True


class TestStatusWithData:

    def test_counts_after_ingesting_source_items(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        service = app.state.pallium_service
        storage = service._storage

        # Create two source items: one pending, one completed
        pending_item = SourceItem(
            source_type="chat_message",
            source_id="status-test-1",
            content_type="text/plain",
            content="hello",
            role="user",
            container_ref="c1",
            thread_ref="t1",
            processing_status="pending",
        )
        completed_item = SourceItem(
            source_type="chat_message",
            source_id="status-test-2",
            content_type="text/plain",
            content="world",
            role="assistant",
            container_ref="c1",
            thread_ref="t1",
            processing_status="completed",
        )
        storage.create_source_item(pending_item)
        storage.create_source_item(completed_item)

        with TestClient(app) as client:
            body = client.get("/status").json()

        assert body["pending_items"] == 1
        assert body["total_source_items"] == 2
        assert body["oldest_pending_age_seconds"] is not None
        assert body["oldest_pending_age_seconds"] >= 0

    def test_counts_after_creating_memory_objects(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        service = app.state.pallium_service
        storage = service._storage

        storage.create_source_item(SourceItem(
            source_type="chat_message",
            source_id="status-mo-test",
            content_type="text/plain",
            content="test",
            role="user",
            container_ref="c1",
            thread_ref="t1",
        ))

        mo = MemoryObject(
            type="decision",
            schema_id="test",
            schema_version="1",
            payload={"summary": "test decision"},
            container_ref="c1",
        )
        storage.create_memory_object(mo)

        with TestClient(app) as client:
            body = client.get("/status").json()

        assert body["total_source_items"] == 1
        assert body["total_memory_objects"] == 1

    def test_multiple_pending_reports_oldest_age(self, tmp_path: Path) -> None:
        app = create_app(_file_db_config(tmp_path))
        service = app.state.pallium_service
        storage = service._storage

        # Create an item with an older timestamp
        old_item = SourceItem(
            source_type="chat_message",
            source_id="status-old-1",
            content_type="text/plain",
            content="old",
            role="user",
            container_ref="c1",
            thread_ref="t1",
            processing_status="pending",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        new_item = SourceItem(
            source_type="chat_message",
            source_id="status-new-1",
            content_type="text/plain",
            content="new",
            role="user",
            container_ref="c1",
            thread_ref="t1",
            processing_status="pending",
        )
        storage.create_source_item(old_item)
        storage.create_source_item(new_item)

        with TestClient(app) as client:
            body = client.get("/status").json()

        assert body["pending_items"] == 2
        # The oldest is from Jan 2026, should be many seconds old
        assert body["oldest_pending_age_seconds"] > 0


class TestStatusSnapshot:

    def test_snapshot_enabled_with_files(self, tmp_path: Path) -> None:
        # Create fake snapshot files in a subdirectory
        snapshot_dir = tmp_path / "snapshots"
        snapshot_dir.mkdir()
        (snapshot_dir / "pallium-20260414T100000Z.db").write_bytes(b"fake")
        (snapshot_dir / "pallium-20260414T103000Z.db").write_bytes(b"fake")

        config = _file_db_config(
            tmp_path,
            snapshot=SnapshotConfig(
                enabled=True,
                snapshot_path=str(snapshot_dir),
            ),
        )
        app = create_app(config)

        with TestClient(app) as client:
            body = client.get("/status").json()

        assert body["snapshot"]["enabled"] is True
        assert body["snapshot"]["snapshot_count"] == 2
        assert body["snapshot"]["last_snapshot_at"] is not None

    def test_snapshot_enabled_no_files(self, tmp_path: Path) -> None:
        snapshot_dir = tmp_path / "snapshots"
        snapshot_dir.mkdir()

        config = _file_db_config(
            tmp_path,
            snapshot=SnapshotConfig(
                enabled=True,
                snapshot_path=str(snapshot_dir),
            ),
        )
        app = create_app(config)

        with TestClient(app) as client:
            body = client.get("/status").json()

        assert body["snapshot"]["enabled"] is True
        assert body["snapshot"]["snapshot_count"] == 0
        assert body["snapshot"]["last_snapshot_at"] is None
