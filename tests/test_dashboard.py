from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from core.models import MemoryObject
from storage.vector_index import VectorIndexConfig


def _test_config(tmp_path: Path) -> AppConfig:
    db_path = tmp_path / "test-dashboard.db"
    return AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{db_path}",
        default_use_case="demo_agent_memory",
        vector_index=VectorIndexConfig(enabled=False),
    )


def _seed_memory(app, *, type: str = "decision", lifecycle: str = "active", container_ref: str = "test-container") -> MemoryObject:
    service = app.state.pallium_service
    mo = MemoryObject(
        type=type,
        schema_id="test",
        schema_version="1.0",
        payload={"summary": f"Test {type} memory"},
        lifecycle=lifecycle,
        container_ref=container_ref,
        created_at=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
    )
    service._storage.create_memory_object(mo)
    return mo


class TestDashboardMemoriesEndpoint:

    def test_returns_empty_list_when_no_memories(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/memories")
        assert resp.status_code == 200
        body = resp.json()
        assert body["memories"] == []
        assert body["total"] == 0
        assert body["offset"] == 0
        assert body["limit"] == 50

    def test_returns_seeded_memories(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_memory(app, type="decision")
            _seed_memory(app, type="atomic_fact")
            resp = client.get("/dashboard/api/memories")
        body = resp.json()
        assert body["total"] == 2
        assert len(body["memories"]) == 2
        mem = body["memories"][0]
        assert "id" in mem
        assert "type" in mem
        assert "display_text" in mem
        assert "created_at" in mem

    def test_filters_by_type(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_memory(app, type="decision")
            _seed_memory(app, type="atomic_fact")
            resp = client.get("/dashboard/api/memories?type=decision")
        body = resp.json()
        assert body["total"] == 1
        assert body["memories"][0]["type"] == "decision"

    def test_filters_by_lifecycle(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_memory(app, type="decision", lifecycle="active")
            _seed_memory(app, type="decision", lifecycle="suppressed")
            resp = client.get("/dashboard/api/memories?lifecycle=suppressed")
        body = resp.json()
        assert body["total"] == 1
        assert body["memories"][0]["lifecycle"] == "suppressed"

    def test_pagination_limit_and_offset(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            for i in range(5):
                _seed_memory(app, type="decision")
            resp = client.get("/dashboard/api/memories?limit=2&offset=2")
        body = resp.json()
        assert body["total"] == 5
        assert len(body["memories"]) == 2
        assert body["offset"] == 2
        assert body["limit"] == 2

    def test_limit_capped_at_200(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/memories?limit=999")
        body = resp.json()
        assert body["limit"] == 200


class TestDashboardPage:

    def test_dashboard_returns_html(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_static_logo_served(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/static/logo/pallium_header.png")
        assert resp.status_code == 200
        assert "image" in resp.headers["content-type"]
