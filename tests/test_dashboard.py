from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from core.models import MemoryObject
from storage.sqlite_schema import MemoryFlagRecord
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

    def test_filters_by_flagged_lifecycle(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            mo_flagged = _seed_memory(app, type="decision", lifecycle="active")
            _seed_memory(app, type="decision", lifecycle="active")
            # Insert a flag record for the first memory
            storage = app.state.pallium_service._storage
            with storage._session_factory() as session:
                flag = MemoryFlagRecord(
                    id="test-flag-1",
                    memory_object_id=mo_flagged.id,
                    reason="test flag",
                    source_ref="test",
                    flagged_at=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
                )
                session.add(flag)
                session.commit()
            resp = client.get("/dashboard/api/memories?lifecycle=flagged")
        body = resp.json()
        assert body["total"] == 1
        assert body["memories"][0]["id"] == mo_flagged.id

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


class TestDashboardIntegration:

    def test_dashboard_html_contains_key_elements(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard")
        html = resp.text
        assert "Pallium Dashboard" in html
        assert "Pallium" in html
        assert "fetchStatus" in html
        assert "/dashboard/api/memories" in html

    def test_memories_display_text_extraction(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            service = app.state.pallium_service
            mo = MemoryObject(
                type="investigation_outcome",
                schema_id="test",
                schema_version="1.0",
                payload={"investigation_outcome": "Found root cause in parser", "other": "data"},
                lifecycle="active",
                created_at=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
            )
            service._storage.create_memory_object(mo)
            resp = client.get("/dashboard/api/memories")
        body = resp.json()
        assert body["memories"][0]["display_text"] == "Found root cause in parser"

    def test_memories_default_lifecycle_shows_all(self, tmp_path: Path) -> None:
        """When no lifecycle filter is passed, all lifecycles are returned."""
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_memory(app, type="decision", lifecycle="active")
            _seed_memory(app, type="decision", lifecycle="suppressed")
            _seed_memory(app, type="decision", lifecycle="superseded")
            resp = client.get("/dashboard/api/memories")
        body = resp.json()
        assert body["total"] == 3

    def test_search_filters_by_payload(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            service = app.state.pallium_service
            from core.models import MemoryObject
            mo1 = MemoryObject(
                type="decision", schema_id="test", schema_version="1.0",
                payload={"summary": "Use PostgreSQL for the database"},
                lifecycle="active",
                created_at=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
            )
            mo2 = MemoryObject(
                type="decision", schema_id="test", schema_version="1.0",
                payload={"summary": "Deploy to Kubernetes"},
                lifecycle="active",
                created_at=datetime(2026, 4, 28, 11, 0, 0, tzinfo=timezone.utc),
            )
            service._storage.create_memory_object(mo1)
            service._storage.create_memory_object(mo2)
            resp = client.get("/dashboard/api/memories?search=PostgreSQL")
        body = resp.json()
        assert body["total"] == 1
        assert "PostgreSQL" in body["memories"][0]["display_text"]


class TestDashboardContainersEndpoint:

    def test_returns_distinct_containers(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_memory(app, container_ref="container-a")
            _seed_memory(app, container_ref="container-b")
            _seed_memory(app, container_ref="container-a")
            resp = client.get("/dashboard/api/containers")
        body = resp.json()
        assert set(body["containers"]) == {"container-a", "container-b"}

    def test_empty_when_no_containers(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            resp = client.get("/dashboard/api/containers")
        body = resp.json()
        assert body["containers"] == []


class TestDashboardActivityEndpoint:

    def test_returns_recent_memories(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            _seed_memory(app, type="decision")
            _seed_memory(app, type="atomic_fact")
            resp = client.get("/dashboard/api/activity?limit=5")
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["items"][0]["event"] == "memory_created"
        assert "type" in body["items"][0]
        assert "display_text" in body["items"][0]


class TestDashboardFlagsEndpoint:

    def test_returns_flags_for_memory(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            mo = _seed_memory(app, type="decision")
            storage = app.state.pallium_service._storage
            with storage._session_factory() as session:
                session.add(MemoryFlagRecord(
                    id="flag-test-1",
                    memory_object_id=mo.id,
                    reason="incorrect decision",
                    source_ref="test-agent",
                    flagged_at=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
                ))
                session.commit()
            resp = client.get(f"/dashboard/api/memories/{mo.id}/flags")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["reason"] == "incorrect decision"
        assert body["items"][0]["source_ref"] == "test-agent"
        assert body["items"][0]["flagged_at"] is not None

    def test_returns_empty_when_no_flags(self, tmp_path: Path) -> None:
        app = create_app(_test_config(tmp_path))
        with TestClient(app) as client:
            mo = _seed_memory(app, type="decision")
            resp = client.get(f"/dashboard/api/memories/{mo.id}/flags")
        assert resp.status_code == 200
        assert resp.json()["items"] == []
