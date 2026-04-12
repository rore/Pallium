from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
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
