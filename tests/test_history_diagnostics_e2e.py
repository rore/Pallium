from __future__ import annotations

import json

import pytest

from sqlalchemy import text

from api.routes import _encode_history_diagnostic_snapshot

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
    retry = _create(client, key="lifecycle", text="captured evidence")
    assert retry.status_code == 200
    assert retry.json()["diagnostic_id"] == diagnostic_id
    assert source_id not in json.dumps(retry.json())


def test_same_key_changed_request_is_conflict_and_identical_retry_is_stable(client):
    first = _create(client, key="same-key", text="first query", limit=3)
    assert first.status_code == 201
    diagnostic_id = first.json()["diagnostic_id"]
    changed = _create(client, key="same-key", text="changed query", limit=4)
    assert changed.status_code == 409 and changed.json()["detail"]["code"] == "idempotency_conflict"
    retry = _create(client, key="same-key", text="first query", limit=3)
    assert retry.status_code == 200 and retry.json()["diagnostic_id"] == diagnostic_id


def test_diagnostic_create_does_not_mutate_lookup_usage_or_query_state(client):
    service = client.app.state.pallium_service
    storage = service._storage
    tables = (
        "historical_lookup_reuse_event",
        "query_audit_log",
        "memory_usage_audit",
    )
    with storage._engine.connect() as conn:
        before = {
            table: conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            for table in tables
        }
    stats_before = service._query_stats.snapshot()

    created = _create(client, key="no-state-mutation")

    assert created.status_code == 201
    with storage._engine.connect() as conn:
        after = {
            table: conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            for table in tables
        }
    assert after == before
    assert service._query_stats.snapshot() == stats_before


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

def test_identical_retry_uses_committed_snapshot_without_rerunning_query(client, monkeypatch):
    first = _create(client, key="committed-retry", text="stable query")
    assert first.status_code == 201
    diagnostic_id = first.json()["diagnostic_id"]
    service = client.app.state.pallium_service
    monkeypatch.setattr(service, "query", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("retrieval down")))

    retry = _create(client, key="committed-retry", text="stable query")

    assert retry.status_code == 200
    assert retry.json()["diagnostic_id"] == diagnostic_id


@pytest.mark.parametrize(
    "requester_patch",
    [
        {"container_ref": "git:other/history"},
        {"active_session_ref": "other-session"},
        {"visibility": "container"},
    ],
)
def test_diagnostic_read_is_non_oracular_for_wrong_requester_tuple(
    client, requester_patch,
):
    created = _create(client, key="requester-scope")
    assert created.status_code == 201
    requester = {
        "container_ref": "git:example/history",
        "active_session_ref": "session-diagnostic-caller",
        "visibility": "private",
        **requester_patch,
    }

    response = client.post(
        f"{DIAGNOSTIC_PATH}/{created.json()['diagnostic_id']}/read",
        json={"requester": requester},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "diagnostic_unavailable"


@pytest.mark.parametrize(
    "patch",
    [
        {"limit": 0},
        {"limit": 51},
        {"source_filters": {"artifact_kind": "invalid"}},
    ],
)
def test_diagnostic_rejects_boundary_and_enum_errors_without_persisting(client, patch):
    payload = _request(key="invalid-boundary")
    payload.update(patch)
    response = client.post(DIAGNOSTIC_PATH, json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_request"


def test_diagnostic_accepts_max_limit_and_reports_unicode_trace_contract(client, drain_queue):
    ingested = client.post("/items", json=[{
        "source_type": "chat_thread",
        "source_id": "unicode-source",
        "content_type": "text/plain",
        "content": "予約 順序 😀",
        "container_ref": "git:example/history",
        "thread_ref": "source-thread",
        "artifact_kind": "message",
        "role": "user",
        "visibility": "private",
    }])
    assert ingested.status_code == 200
    drain_queue(client)

    response = _create(client, key="unicode-max", text="予約 😀", limit=50)

    assert response.status_code == 201
    trace = response.json()["trace"]
    assert set(trace) == {
        "scope", "capture_index", "stages", "fusion", "exclusions",
        "ranking", "packaging", "query_limit",
    }
    assert trace["query_limit"]["requested"] == 50
    assert trace["ranking"]["results"][0]["rank"] == 1
    assert trace["packaging"]["observed_at"] == "creation"


def test_corrupt_nested_snapshot_field_is_rejected_not_echoed(client, monkeypatch):
    created = _create(client, key="nested-corrupt")
    assert created.status_code == 201
    diagnostic_id = created.json()["diagnostic_id"]
    storage = client.app.state.pallium_service._storage
    row = storage.get_history_diagnostic(
        diagnostic_id,
        container_ref="git:example/history",
        active_session_ref="session-diagnostic-caller",
        visibility="private",
    )
    snapshot = json.loads(row["snapshot_json"])
    snapshot["trace"]["scope"]["requested"]["raw-private-thread-value"] = True
    corrupt = {**row, "snapshot_json": json.dumps(snapshot)}
    monkeypatch.setattr(storage, "get_history_diagnostic", lambda *a, **k: corrupt)

    response = _read(client, diagnostic_id)

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "diagnostic_corrupt"
    assert "raw-private-thread-value" not in response.text

def test_maximum_candidate_snapshot_is_deterministically_byte_bounded():
    candidate = {
        "source_item_id": "s" * 128,
        "rank": 1,
        "score": 0.5,
        "match_channel": "lexical",
    }
    snapshot = {
        "outcome": "ok",
        "trace": {
            "stages": [
                {"candidates": [{**candidate, "rank": rank} for rank in range(1, 201)], "omitted_count": 0},
                {"candidates": [{**candidate, "rank": rank, "match_channel": "vector"} for rank in range(1, 201)], "omitted_count": 0},
            ],
            "fusion": {
                "candidates": [{**candidate, "rank": rank, "match_channel": "both"} for rank in range(1, 201)],
                "omitted_count": 0,
            },
        },
    }

    encoded = _encode_history_diagnostic_snapshot(snapshot)

    assert len(encoded.encode("utf-8")) <= 65_536
    assert sum(stage["omitted_count"] for stage in snapshot["trace"]["stages"]) + snapshot["trace"]["fusion"]["omitted_count"] > 0

def test_work_filters_are_normalized_once_for_query_fingerprint_and_reread(client, drain_queue):
    ingested = client.post("/items", json=[{
        "source_type": "chat_thread",
        "source_id": "work-source",
        "content_type": "text/plain",
        "content": "normalized work evidence",
        "metadata": {"pallium_work_refs": ["WORK_ITEM"]},
        "container_ref": "git:example/history",
        "thread_ref": "source-thread",
        "artifact_kind": "message",
        "role": "user",
        "visibility": "private",
    }])
    assert ingested.status_code == 200
    source_id = ingested.json()[0]["source_item_id"]
    drain_queue(client)

    first = _create(
        client,
        key="normalized-work",
        text="normalized evidence",
        work_refs=["WORK ITEM"],
    )
    retry = _create(
        client,
        key="normalized-work",
        text="normalized evidence",
        work_refs=["work-item"],
    )

    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.json()["diagnostic_id"] == first.json()["diagnostic_id"]
    assert source_id in json.dumps(first.json())
    assert source_id in json.dumps(retry.json())

def test_query_failure_is_typed_and_does_not_expose_exception_or_id(client, monkeypatch):
    service = client.app.state.pallium_service
    monkeypatch.setattr(
        service,
        "query",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("private query failure")),
    )

    response = _create(client, key="query-failure")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "diagnostic_failed"
    assert "private query failure" not in response.text
    assert "diagnostic_id" not in response.text


@pytest.mark.parametrize("corruption", ["availability", "counts"])
def test_corrupt_nested_snapshot_type_or_counts_fail_closed(client, monkeypatch, corruption):
    created = _create(client, key=f"corrupt-{corruption}")
    assert created.status_code == 201
    diagnostic_id = created.json()["diagnostic_id"]
    storage = client.app.state.pallium_service._storage
    row = storage.get_history_diagnostic(
        diagnostic_id,
        container_ref="git:example/history",
        active_session_ref="session-diagnostic-caller",
        visibility="private",
    )
    snapshot = json.loads(row["snapshot_json"])
    stage = snapshot["trace"]["stages"][0]
    if corruption == "availability":
        stage["available"] = "not-a-bool"
    else:
        stage["selected_count"] = stage["candidate_count"] + 1
    corrupt = {**row, "snapshot_json": json.dumps(snapshot)}
    monkeypatch.setattr(storage, "get_history_diagnostic", lambda *a, **k: corrupt)

    response = _read(client, diagnostic_id)

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "diagnostic_corrupt"

def test_diagnostic_reuses_public_and_global_visibility_without_broadening_actor(client, drain_queue):
    ingested = client.post("/items", json=[
        {
            "source_type": "chat_thread",
            "source_id": "public-source",
            "content_type": "text/plain",
            "content": "shared public diagnostic evidence",
            "container_ref": "git:other/history",
            "thread_ref": "public-thread",
            "artifact_kind": "message",
            "role": "user",
            "visibility": "public",
        },
        {
            "source_type": "chat_thread",
            "source_id": "global-source",
            "content_type": "text/plain",
            "content": "actor global diagnostic evidence",
            "container_ref": "git:other/history",
            "thread_ref": "global-thread",
            "actor_ref": "actor-one",
            "artifact_kind": "message",
            "role": "user",
            "visibility": "global",
        },
    ])
    assert ingested.status_code == 200
    public_id, global_id = [item["source_item_id"] for item in ingested.json()]
    drain_queue(client)

    public = _create(client, key="public-visible", text="shared public evidence")
    omitted_actor_payload = _request(key="global-actor-omitted", text="actor global evidence")
    omitted_actor_payload["requester"]["visibility"] = "global"
    omitted_actor = client.post(DIAGNOSTIC_PATH, json=omitted_actor_payload)
    exact_actor_payload = _request(
        key="global-actor-exact",
        text="actor global evidence",
        actor_ref="actor-one",
    )
    exact_actor_payload["requester"]["visibility"] = "global"
    exact_actor = client.post(DIAGNOSTIC_PATH, json=exact_actor_payload)

    assert public.status_code == omitted_actor.status_code == exact_actor.status_code == 201
    assert public_id in json.dumps(public.json())
    assert global_id not in json.dumps(omitted_actor.json())
    assert global_id in json.dumps(exact_actor.json())
    diagnostic_id = exact_actor.json()["diagnostic_id"]
    assert _read(client, diagnostic_id).json() == _read(client, diagnostic_id).json()