"""Integration tests for global visibility (cross-container actor-scoped memory)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from tests.config_helpers import build_llm_test_config
from tests.stub_providers import TieredMemorySemanticProvider


def _build_client(monkeypatch, test_db_url: str) -> TestClient:
    monkeypatch.setattr(
        "app.dependencies.build_llm_provider",
        lambda config, **_: TieredMemorySemanticProvider(),
    )
    return TestClient(create_app(build_llm_test_config(default_use_case="agent_conversation_memory", sqlite_url=test_db_url)))


def _ingest(client: TestClient, *, source_id: str, content: str, visibility: str, container_ref: str, actor_ref: str | None = None, thread_ref: str = "thread-1") -> dict:
    payload: dict = {
        "source_type": "chat_message",
        "source_id": source_id,
        "content_type": "text/plain",
        "content": content,
        "role": "user",
        "container_ref": container_ref,
        "thread_ref": thread_ref,
        "visibility": visibility,
        "artifact_kind": "message",
    }
    if actor_ref is not None:
        payload["actor_ref"] = actor_ref
    response = client.post("/items", json=[payload])
    assert response.status_code == 200
    client.app.state.pallium_service.drain_processing_queue(worker_id="global-test")
    return response.json()[0]


def _query(client: TestClient, *, text: str, container_ref: str, visibility: str = "private", actor_ref: str | None = None) -> dict:
    payload: dict = {
        "text": text,
        "limit": 10,
        "container_ref": container_ref,
        "visibility": visibility,
    }
    if actor_ref is not None:
        payload["actor_ref"] = actor_ref
    response = client.post("/query", json=payload)
    assert response.status_code == 200
    return response.json()


def test_ingest_global_memory_and_query_cross_container(monkeypatch, test_db_url: str) -> None:
    """Global memory ingested in container A is visible when querying from container B with matching actor."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(
            client,
            source_id="global-pref-1",
            content="Decision: always use tabs for indentation across all projects",
            visibility="global",
            container_ref="git:repo-a",
            actor_ref="alice",
        )
        result = _query(
            client,
            text="what indentation style should I use?",
            container_ref="git:repo-b",
            actor_ref="alice",
        )
        assert result["results"], "Global memory should appear cross-container for same actor"
        found = any("tabs" in str(r.get("payload", "")).lower() or "tabs" in str(r.get("excerpt", "")).lower() for r in result["results"])
        assert found, f"Expected 'tabs' content in results: {result['results']}"


def test_global_memory_invisible_without_actor_ref_on_query(monkeypatch, test_db_url: str) -> None:
    """Global memory NOT visible when query has no actor_ref (fail-closed)."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(
            client,
            source_id="global-pref-2",
            content="Decision: always use tabs for indentation across all projects",
            visibility="global",
            container_ref="git:repo-a",
            actor_ref="alice",
        )
        result = _query(
            client,
            text="what indentation style should I use?",
            container_ref="git:repo-b",
            actor_ref=None,
        )
        global_results = [r for r in result["results"] if r.get("visibility") == "global"]
        assert not global_results, "Global memory should NOT appear without actor_ref on query"


def test_global_memory_invisible_to_different_actor(monkeypatch, test_db_url: str) -> None:
    """Global memory NOT visible to a different actor."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(
            client,
            source_id="global-pref-3",
            content="Decision: always use tabs for indentation across all projects",
            visibility="global",
            container_ref="git:repo-a",
            actor_ref="alice",
        )
        result = _query(
            client,
            text="what indentation style should I use?",
            container_ref="git:repo-b",
            actor_ref="bob",
        )
        global_results = [r for r in result["results"] if r.get("visibility") == "global"]
        assert not global_results, "Global memory should NOT appear for different actor"


def test_global_memory_visible_in_same_container(monkeypatch, test_db_url: str) -> None:
    """Global memory visible in originating container with matching actor."""
    with _build_client(monkeypatch, test_db_url) as client:
        _ingest(
            client,
            source_id="global-pref-4",
            content="Decision: always use tabs for indentation across all projects",
            visibility="global",
            container_ref="git:repo-a",
            actor_ref="alice",
        )
        result = _query(
            client,
            text="what indentation style should I use?",
            container_ref="git:repo-a",
            actor_ref="alice",
        )
        assert result["results"], "Global memory should be visible in same container with same actor"


def test_global_does_not_appear_in_automatic_extraction(monkeypatch, test_db_url: str) -> None:
    """Automatic extraction never produces global memories -- only explicit ingest does."""
    with _build_client(monkeypatch, test_db_url) as client:
        # Ingest a normal message (not marked as global) -- extraction should produce
        # non-global memory objects
        _ingest(
            client,
            source_id="normal-msg-1",
            content="Decision: always use spaces for YAML files in this project",
            visibility="private",
            container_ref="git:repo-a",
            actor_ref="alice",
        )
        # Check all memory objects -- none should be global
        service = client.app.state.pallium_service
        all_memories = list(service._storage.list_memory_objects())
        global_memories = [m for m in all_memories if m.visibility == "global"]
        assert not global_memories, f"Automatic extraction should never produce global memories, found: {global_memories}"
