"""Public Session History contracts from docs/session-history.md and docs/http-api.md."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from storage.vector_index import VectorIndexConfig


@pytest.fixture()
def history(tmp_path: Path):
    app = create_app(AppConfig(
        sqlite_url=f"sqlite:///{tmp_path / 'history.db'}",
        semantic_packages={},
        vector_index=VectorIndexConfig(enabled=False),
    ))
    with TestClient(app) as client:
        yield client


def _item(source_id: str, *, container="container-a", thread="source-a", work="task-a", actor=None):
    return {
        "source_type": "chat_message", "source_id": source_id,
        "content_type": "text/plain", "content": f"distinct history marker {source_id}",
        "role": "user", "artifact_kind": "message", "container_ref": container,
        "thread_ref": thread, "visibility": "private", "actor_ref": actor,
        "metadata": {"pallium_work_refs": [work]},
    }


def _ingest(client, *items):
    response = client.post("/items", json=list(items))
    assert response.status_code == 200, response.text
    client.app.state.pallium_service.drain_processing_queue(worker_id="protected-history")
    return [row["source_item_id"] for row in response.json()]


def _query(client, text="distinct history marker", **overrides):
    payload = {
        "text": text, "source_only": True, "trigger_origin": "agent_pull",
        "container_ref": "container-a", "visibility": "private",
        "active_session_ref": "requesting-session", "limit": 20,
    }
    payload.update(overrides)
    response = client.post("/query", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(result):
    return {row["source_item_id"] for row in result["results"]}


def test_history_missing_visibility_context_fails_closed(history):
    """docs/http-api.md /query: missing scope must not expose a private History hit."""
    (source_id,) = _ingest(history, _item("visible-only-with-scope"))
    assert source_id in _ids(_query(history, "distinct history marker visible-only-with-scope"))
    for missing in ("container_ref", "visibility"):
        payload = {
            "text": "distinct history marker visible-only-with-scope",
            "source_only": True, "trigger_origin": "agent_pull",
            "container_ref": "container-a", "visibility": "private",
            "active_session_ref": "requesting-session",
        }
        del payload[missing]
        response = history.post("/query", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["decision_reason"] == "visibility_context_required"
        assert response.json()["results"] == []
    assert source_id not in _ids(_query(history, "distinct history marker visible-only-with-scope", container_ref="container-b"))


def test_history_forget_hides_search_and_expansion(history):
    """docs/session-history.md Scope and governance: forgetting must revoke public re-query and expansion."""
    (source_id,) = _ingest(history, _item("forget-this-turn"))
    assert source_id in _ids(_query(history, "distinct history marker forget-this-turn"))
    response = history.post("/source/forget", json={"source_item_id": source_id, "reason": "contract"})
    assert response.status_code == 200, response.text
    assert source_id not in _ids(_query(history, "distinct history marker forget-this-turn"))
    expanded = history.get(f"/source/{source_id}/context", params={
        "container_ref": "container-a", "query_visibility": "private",
        "active_session_ref": "requesting-session",
    })
    assert expanded.status_code == 404, expanded.text


def test_history_exact_work_ref_does_not_broaden(history):
    """docs/session-history.md Basic use: exact work search must exclude related text under another reference."""
    wanted, other = _ingest(history, _item("work-one", work="TASK-42"), _item("work-two", work="TASK-43"))
    assert {wanted, other} <= _ids(_query(history))
    exact = _query(history, trigger_origin="agent_pull_work", work_refs=["task-42"])
    assert _ids(exact) == {wanted}
    assert _ids(_query(history, "", trigger_origin="agent_pull_work", work_refs=["task-42"])) == {wanted}


def test_history_source_filters_do_not_replace_requester_scope(history):
    """docs/session-history.md Scope and governance: source thread and actor filters narrow cross-session search."""
    a, b, foreign = _ingest(
        history,
        _item("source-a", thread="prior-a", actor="actor-a"),
        _item("source-b", thread="prior-b", actor="actor-b"),
        _item("foreign", container="container-b", thread="prior-a", actor="actor-a"),
    )
    assert _ids(_query(history)) == {a, b}
    assert _ids(_query(history, thread_ref="prior-a")) == {a}
    assert _ids(_query(history, actor_ref="actor-b")) == {b}
    assert _ids(_query(history, thread_ref="prior-a", actor_ref="actor-b")) == set()
    assert foreign not in _ids(_query(history, thread_ref="prior-a"))
