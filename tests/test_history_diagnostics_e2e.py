from __future__ import annotations

import json

import pytest

from sqlalchemy import text

DIAGNOSTIC_PATH = "/history/diagnostics"


def _request(*, key="diag-key", text="reservation ordering", limit=5, **filters):
    return {"idempotency_key": key, "text": text, "limit": limit,
            "requester": {"container_ref": "git:example/history", "active_session_ref": "session-diagnostic-caller", "visibility": "private"},
            "source_filters": filters}


def _create(client, **kwargs):
    return client.post(DIAGNOSTIC_PATH, json=_request(**kwargs))


def _read(client, diagnostic_id, **extra):
    return client.post(f"{DIAGNOSTIC_PATH}/{diagnostic_id}/read", json={
        "requester": {"container_ref": "git:example/history", "active_session_ref": "session-diagnostic-caller", "visibility": "private"},
        **extra,
    })


def test_create_and_read_diagnostic_includes_bounded_trace_and_valid_empty(client):
    created = _create(client, key="empty-key", text="no matching evidence")
    assert created.status_code == 201
    payload = created.json()
    assert payload["diagnostic_id"] and payload["outcome"] == "valid_empty"
    assert payload["trace"]["capture_index"]["bounded"] is True
    reread = _read(client, payload["diagnostic_id"])
    assert reread.status_code == 200 and reread.json()["diagnostic_id"] == payload["diagnostic_id"]


def test_diagnostic_requires_requester_tuple_and_unavailable_id_is_non_oracular(client):
    missing = client.post(DIAGNOSTIC_PATH, json={"idempotency_key": "missing", "text": "x", "limit": 1})
    assert missing.status_code == 422 and missing.json()["detail"]["code"] == "invalid_request"
    unavailable = client.post(f"{DIAGNOSTIC_PATH}/not-real/read", json={"requester": {"container_ref": "git:other/history", "active_session_ref": "other", "visibility": "private"}})
    assert unavailable.status_code == 404 and unavailable.json()["detail"]["code"] == "diagnostic_unavailable"


def test_saved_filters_cannot_be_overridden_on_reread(client):
    created = _create(client, key="saved-filter", artifact_kind="message", source_thread_ref="thread-a")
    assert created.status_code == 201
    response = _read(client, created.json()["diagnostic_id"], source_filters={"artifact_kind": "different-kind"})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "invalid_request"


def test_diagnostic_reread_sanitizes_real_source_after_forget(client, drain_queue):
    created = client.post("/items", json=[{"source_type": "chat_thread", "source_id": "diag-source", "content_type": "text/plain", "content": "captured evidence", "container_ref": "git:example/history", "thread_ref": "thread-a", "artifact_kind": "message", "role": "user", "visibility": "private"}])
    assert created.status_code == 200
    source_id = created.json()[0]["source_item_id"]
    drain_queue(client)
    diagnostic = _create(client, key="lifecycle", text="captured evidence")
    assert diagnostic.status_code == 201
    diagnostic_id = diagnostic.json()["diagnostic_id"]
    assert source_id in json.dumps(diagnostic.json())
    forgotten = client.post("/source/forget", json={"source_item_id": source_id, "reason": "user request"})
    assert forgotten.status_code == 200
    reread = _read(client, diagnostic_id)
    assert reread.status_code == 200 and reread.json()["diagnostic_id"] == diagnostic_id
    body = json.dumps(reread.json())
    assert source_id not in body


def test_same_key_changed_request_is_conflict_and_identical_retry_is_stable(client):
    first = _create(client, key="same-key", text="first query", limit=3)
    assert first.status_code == 201
    diagnostic_id = first.json()["diagnostic_id"]
    changed = _create(client, key="same-key", text="changed query", limit=4)
    assert changed.status_code == 409 and changed.json()["detail"]["code"] == "idempotency_conflict"
    retry = _create(client, key="same-key", text="first query", limit=3)
    assert retry.status_code == 200 and retry.json()["diagnostic_id"] == diagnostic_id


def test_diagnostic_create_does_not_write_lookup_funnel_rows(client):
    storage = client.app.state.pallium_service._storage
    with storage._engine.connect() as conn:
        before = conn.execute(
            text("SELECT COUNT(*) FROM historical_lookup_reuse_event")
        ).scalar_one()
    created = _create(client, key="no-funnel")
    assert created.status_code == 201
    with storage._engine.connect() as conn:
        after = conn.execute(
            text("SELECT COUNT(*) FROM historical_lookup_reuse_event")
        ).scalar_one()
    assert after == before


def test_persistence_failure_does_not_expose_diagnostic_id(client, monkeypatch):
    monkeypatch.setattr("storage.sqlite.SQLiteStorageProvider.create_history_diagnostic", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("storage unavailable")), raising=False)
    failed = _create(client, key="persistence-failure")
    assert failed.status_code == 503 and failed.json()["detail"]["code"] == "diagnostic_persistence_failed" and "diagnostic_id" not in failed.text


def test_authorized_corrupt_snapshot_is_distinct_from_unavailable(client, monkeypatch):
    created = _create(client, key="corrupt-snapshot")
    assert created.status_code == 201
    diagnostic_id = created.json()["diagnostic_id"]
    monkeypatch.setattr("storage.sqlite.SQLiteStorageProvider.get_history_diagnostic", lambda *a, **k: {"diagnostic_id": diagnostic_id, "requester": {"container_ref": "git:example/history", "active_session_ref": "session-diagnostic-caller", "visibility": "private"}, "snapshot": "not-json"}, raising=False)
    response = _read(client, diagnostic_id)
    assert response.status_code == 500 and response.json()["detail"]["code"] == "diagnostic_corrupt"


@pytest.mark.parametrize("path", ["/query", "/query/debug"])
def test_ordinary_query_shapes_remain_unchanged(client, path):
    response = client.post(path, json={"text": "ordinary query", "limit": 1, "container_ref": "git:example/history", "active_session_ref": "session-diagnostic-caller", "visibility": "private"})
    assert response.status_code == 200 and "results" in response.json()