from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig, SemanticPackageConfig
from app.main import create_app
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES


@pytest.fixture()
def test_db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture()
def client(test_db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from app import main as app_main

    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", lambda *_args, **_kwargs: None)
    from storage.vector_index import VectorIndexConfig
    storages = []
    original_storage = app_main.build_storage_provider

    def owned_storage(*args, **kwargs):
        storage = original_storage(*args, **kwargs)
        storages.append(storage)
        return storage

    # Capture early metrics storage without starting the application's lifespan.
    with monkeypatch.context() as construction:
        construction.setattr(app_main, "build_storage_provider", owned_storage)
        app = create_app(
            AppConfig(
                storage_backend="sqlite",
                sqlite_url=test_db_url,
                default_use_case="demo_agent_memory",
                semantic_packages=DEMO_SEMANTIC_PACKAGES,
                vector_index=VectorIndexConfig(enabled=False),
            )
        )
    service = app.state.pallium_service
    storages.append(service._storage)
    http = TestClient(app)
    with ExitStack() as cleanup:
        for storage in reversed(storages):
            cleanup.callback(storage.close)
        cleanup.callback(service.close)
        cleanup.callback(app.state._wait_for_operations)
        cleanup.callback(http.close)
        yield http


@pytest.fixture()
def drain_queue():
    def _drain(client: TestClient, **kwargs):
        return client.app.state.pallium_service.drain_processing_queue(worker_id="test-worker", **kwargs)

    return _drain

@pytest.fixture(autouse=True)
def isolated_claude_wake_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Keep trusted-local capability tests out of the developer profile."""
    from app import codex_wake

    # Clock mocks must not disable SQLite backoff or unrelated worker timing.
    monkeypatch.setattr(codex_wake, "time", SimpleNamespace(**vars(time)))
    if request.node.path.name.startswith("test_claude_"):
        monkeypatch.setenv("PALLIUM_CLAUDE_WAKE_DIR", str(tmp_path / "claude-wake"))
    else:
        monkeypatch.delenv("PALLIUM_CLAUDE_WAKE_DIR", raising=False)
    monkeypatch.setenv("PALLIUM_CODEX_WAKE_DIR", str(tmp_path / "codex-wake"))
    monkeypatch.delenv("PALLIUM_HOOK_ACTOR_REF", raising=False)
