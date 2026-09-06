from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig, SemanticPackageConfig
from app.main import create_app
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


@pytest.fixture()
def test_db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture()
def client(test_db_url: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", lambda *_args, **_kwargs: None)
    from storage.vector_index import VectorIndexConfig
    app = create_app(
        AppConfig(
            storage_backend="sqlite",
            sqlite_url=test_db_url,
            default_use_case="demo_agent_memory",
            semantic_packages=DEMO_SEMANTIC_PACKAGES,
            vector_index=VectorIndexConfig(enabled=False),
        )
    )
    return TestClient(app)


@pytest.fixture()
def drain_queue():
    def _drain(client: TestClient, **kwargs):
        return client.app.state.pallium_service.drain_processing_queue(worker_id="test-worker", **kwargs)

    return _drain

@pytest.fixture(autouse=True)
def isolated_claude_wake_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep trusted-local capability tests out of the developer profile."""
    monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(tmp_path / "claude-wake"))