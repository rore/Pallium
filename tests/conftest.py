from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from tests.config_helpers import _vector_index_path_for_sqlite


@pytest.fixture()
def test_db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture()
def client(test_db_url: str) -> TestClient:
    from storage.vector_index import VectorIndexConfig
    app = create_app(
        AppConfig(
            storage_backend="sqlite",
            sqlite_url=test_db_url,
            default_use_case="demo_agent_memory",
            vector_index=VectorIndexConfig(index_path=_vector_index_path_for_sqlite(test_db_url)),
        )
    )
    return TestClient(app)


@pytest.fixture()
def drain_queue():
    def _drain(client: TestClient, **kwargs):
        return client.app.state.pallium_service.drain_processing_queue(worker_id="test-worker", **kwargs)

    return _drain
