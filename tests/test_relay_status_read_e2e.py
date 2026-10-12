from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from api.routes import create_router
from core.relay import RelayService
from storage.sqlite import SQLiteStorageProvider


SCOPE = {"container_ref": "git:example.test/team/relay"}


@pytest.fixture
def relay_client(tmp_path):
    relay_path = tmp_path / "relay.db"
    storage = SQLiteStorageProvider(
        f"sqlite:///{tmp_path / 'main.db'}", f"sqlite:///{relay_path}"
    )
    relay = RelayService(storage)
    app = FastAPI()
    app.include_router(create_router(SimpleNamespace(), relay_service=relay))
    with TestClient(app) as client:
        yield client, relay, relay_path
    storage.close()


def _send(client, *, payload="event → 你好", expiry=60):
    return client.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": "claude-code:receiver", "payload": payload,
        **SCOPE, "expires_in_seconds": expiry,
    })


def _register(client):
    for runtime, session in (("codex", "sender"), ("claude-code", "receiver")):
        response = client.post("/relay/turn", json={
            "runtime": runtime, "session_ref": session, **SCOPE,
        })
        assert response.status_code == 200, response.text


@pytest.mark.parametrize("state", ["pending", "claimed", "delivered"])
@pytest.mark.parametrize("expiry", [60, None], ids=["finite", "durable"])
def test_unexpired_status_and_trace_succeed_while_private_relay_writer_is_held(
    relay_client, state, expiry
):
    client, _, relay_path = relay_client
    _register(client)
    sent = _send(client, expiry=expiry)
    assert sent.status_code == 200, sent.text
    message = sent.json()
    if state in {"claimed", "delivered"}:
        turn = client.post("/relay/turn", json={
            "runtime": "claude-code", "session_ref": "receiver", **SCOPE,
        })
        delivery = turn.json()["deliveries"][0]
        if state == "delivered":
            ack = client.post("/relay/deliveries/ack", json={
                "delivery_id": delivery["delivery_id"],
                "claim_token": delivery["claim_token"], **SCOPE,
            })
            assert ack.status_code == 200, ack.text

    url = f"/relay/messages/{message['message_id']}"
    baseline = client.get(url, params=SCOPE)
    assert baseline.status_code == 200, baseline.text
    expected_full = baseline.json()
    params = {**SCOPE, "offset": 0, "page_size": 8}
    baseline_page = client.get(url, params=params)
    assert baseline_page.status_code == 200, baseline_page.text
    expected_page = baseline_page.json()

    writer = sqlite3.connect(relay_path, timeout=0)
    try:
        writer.execute("BEGIN IMMEDIATE")
        status = client.get(url, params=SCOPE)
        page = client.get(url, params=params)
        trace = client.get(f"{url}/trace", params=SCOPE)
        assert trace.status_code == 200, trace.text
        assert trace.json()["delivery_snapshots"][0]["stored_state"] == state
        assert status.status_code == 200, status.text
        assert status.json() == expected_full
        assert page.status_code == 200, page.text
        assert page.json() == expected_page
    finally:
        writer.rollback()
        writer.close()


@pytest.mark.parametrize("state", ["pending", "claimed", "delivered"])
@pytest.mark.parametrize("boundary", ["before", "equal", "after"])
def test_status_expiry_boundary_cleans_claim_state_through_http_and_trace(
    relay_client, monkeypatch, state, boundary
):
    client, relay, _ = relay_client
    _register(client)
    sent = _send(client)
    assert sent.status_code == 200, sent.text
    message = sent.json()
    delivery = None
    if state in {"claimed", "delivered"}:
        turn = client.post("/relay/turn", json={
            "runtime": "claude-code", "session_ref": "receiver", **SCOPE,
        })
        delivery = turn.json()["deliveries"][0]
        if state == "delivered":
            ack = client.post("/relay/deliveries/ack", json={
                "delivery_id": delivery["delivery_id"],
                "claim_token": delivery["claim_token"], **SCOPE,
            })
            assert ack.status_code == 200, ack.text

    expires_at = datetime.fromisoformat(message["expires_at"].replace("Z", "+00:00"))
    fixed_now = {
        "before": expires_at - timedelta(microseconds=1),
        "equal": expires_at,
        "after": expires_at + timedelta(microseconds=1),
    }[boundary]
    original_status = relay._store.relay_message_status
    monkeypatch.setattr(
        relay._store, "relay_message_status",
        lambda **kwargs: original_status(**{**kwargs, "now": fixed_now}),
    )
    response = client.get(f"/relay/messages/{message['message_id']}", params=SCOPE)
    assert response.status_code == 200, response.text
    actual_state = response.json()["deliveries"][0]["state"]
    expected_state = state if boundary == "before" or state == "delivered" else "expired"
    assert actual_state == expected_state
    if state == "claimed" and boundary != "before":
        assert response.json()["deliveries"][0]["claim_token"] is None
        assert response.json()["deliveries"][0]["receipt"] is None
        stale_ack = client.post("/relay/deliveries/ack", json={
            "delivery_id": delivery["delivery_id"],
            "claim_token": delivery["claim_token"], **SCOPE,
        })
        assert stale_ack.status_code == 409

    trace = client.get(f"/relay/messages/{message['message_id']}/trace")
    assert trace.status_code == 200, trace.text
    snapshot = trace.json()["delivery_snapshots"][0]
    assert snapshot["stored_state"] == expected_state


def test_status_scope_missing_and_pagination_contract(relay_client):
    client, _, _ = relay_client
    _register(client)
    payload = "界" * 16000
    sent = _send(client, payload=payload)
    assert sent.status_code == 200, sent.text
    message_id = sent.json()["message_id"]

    end = client.get(f"/relay/messages/{message_id}", params={
        **SCOPE, "offset": 16000, "page_size": 1,
    })
    assert end.status_code == 200
    assert end.json()["payload"] == ""
    last = client.get(f"/relay/messages/{message_id}", params={
        **SCOPE, "offset": 15999, "page_size": 1,
    })
    assert last.status_code == 200
    assert last.json()["payload"] == "界"
    maximum = client.get(f"/relay/messages/{message_id}", params={
        **SCOPE, "offset": 0, "page_size": 16000,
    })
    assert maximum.status_code == 200
    assert maximum.json()["payload"] == payload
    over = client.get(f"/relay/messages/{message_id}", params={
        **SCOPE, "page_size": 16001,
    })
    assert over.status_code == 422

    other_valid_scope = client.get(f"/relay/messages/{message_id}", params={
        "container_ref": "git:example.test/another/project",
    })
    assert other_valid_scope.status_code == 200
    assert other_valid_scope.json()["payload"] == payload
    blank_scope = client.get(f"/relay/messages/{message_id}", params={"container_ref": " "})
    assert blank_scope.status_code == 422
    missing = client.get("/relay/messages/missing", params=SCOPE)
    assert missing.status_code == 404


@pytest.mark.parametrize("transition", ["claim", "ack", "reactivate"])
def test_status_snapshot_stays_before_a_concurrent_delivery_transition(
    relay_client, transition
):
    client, relay, _ = relay_client
    _register(client)
    sent = _send(client).json()
    url = f"/relay/messages/{sent['message_id']}"
    delivery = None
    if transition == "ack":
        response = client.post("/relay/turn", json={
            "runtime": "claude-code", "session_ref": "receiver", **SCOPE,
        })
        assert response.status_code == 200, response.text
        delivery = response.json()["deliveries"][0]
    elif transition == "reactivate":
        response = client.post("/relay/sessions/close", json={
            "runtime": "claude-code", "session_ref": "receiver", **SCOPE,
        })
        assert response.status_code == 200, response.text
    expected = client.get(url, params=SCOPE).json()
    paused = threading.Event()
    resume = threading.Event()
    engine = relay._store._relay_engine
    endpoint_id = sent["deliveries"][0]["recipient_endpoint_id"]
    hook = "before_cursor_execute" if transition == "reactivate" else "after_cursor_execute"

    def pause_snapshot(connection, cursor, statement, parameters, context, many):
        table = "relay_sessions" if transition == "reactivate" else "relay_messages"
        identity = endpoint_id if transition == "reactivate" else sent["message_id"]
        if f"FROM {table}" in statement and parameters == (identity,) and not paused.is_set():
            paused.set()
            assert resume.wait(10), "concurrent transition did not release status read"

    event.listen(engine, hook, pause_snapshot)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            status = pool.submit(client.get, url, params=SCOPE)
            try:
                assert paused.wait(10), "status never reached its read snapshot"
                if transition == "ack":
                    changed = client.post("/relay/deliveries/ack", json={
                        "delivery_id": delivery["delivery_id"],
                        "claim_token": delivery["claim_token"], **SCOPE,
                    })
                else:
                    changed = client.post("/relay/turn", json={
                        "runtime": "claude-code", "session_ref": "receiver", **SCOPE,
                    })
                    assert len(changed.json()["deliveries"]) == 1
                assert changed.status_code == 200, changed.text
            finally:
                resume.set()
            response = status.result(timeout=10)
            assert response.status_code == 200, response.text
            assert response.json() == expected
    finally:
        resume.set()
        event.remove(engine, hook, pause_snapshot)
    current = client.get(url, params=SCOPE).json()["deliveries"][0]
    assert current["state"] == ("delivered" if transition == "ack" else "claimed")
    if transition == "reactivate":
        assert expected["deliveries"][0]["destination_health"] is None
        assert current["destination_health"] == "active"


def test_expired_status_rereads_ack_committed_before_writer_acquisition(
    relay_client, monkeypatch
):
    client, relay, _ = relay_client
    _register(client)
    sent = _send(client).json()
    response = client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "receiver", **SCOPE,
    })
    assert response.status_code == 200, response.text
    delivery = response.json()["deliveries"][0]
    expires_at = datetime.fromisoformat(sent["expires_at"].replace("Z", "+00:00"))
    storage = relay._store
    original_status = storage.relay_message_status
    original_ack = storage.relay_ack
    monkeypatch.setattr(storage, "relay_message_status", lambda **kwargs: original_status(
        **{**kwargs, "now": expires_at}
    ))
    # Model an ACK admitted before expiry whose commit wins the writer handoff.
    monkeypatch.setattr(storage, "relay_ack", lambda **kwargs: original_ack(
        **{**kwargs, "now": expires_at - timedelta(microseconds=1)}
    ))
    paused = threading.Event()
    resume = threading.Event()
    reads = []
    original_begin = storage._begin_relay_immediate

    @contextmanager
    def pause_before_writer_acquisition():
        # Let ACK win before status owns either local or SQLite writer admission.
        if not paused.is_set():
            paused.set()
            assert resume.wait(10), "ACK did not release expiry writer"
        with original_begin() as session:
            yield session

    monkeypatch.setattr(storage, "_begin_relay_immediate", pause_before_writer_acquisition)

    def observe_reads(connection, cursor, statement, parameters, context, many):
        if "FROM relay_messages" in statement and parameters == (sent["message_id"],):
            reads.append(connection)

    event.listen(storage._relay_engine, "before_cursor_execute", observe_reads)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.get, f"/relay/messages/{sent['message_id']}", params=SCOPE)
            try:
                assert paused.wait(10), "expired status never reached writer fallback"
                assert len(reads) == 1
                assert not storage._relay_writer_lock.locked()
                ack = client.post("/relay/deliveries/ack", json={
                    "delivery_id": delivery["delivery_id"],
                    "claim_token": delivery["claim_token"], **SCOPE,
                })
                assert ack.status_code == 200, ack.text
            finally:
                resume.set()
            response = pending.result(timeout=10)
            assert response.status_code == 200, response.text
            assert len(reads) == 2
            assert reads[0] is not reads[1]
    finally:
        resume.set()
        event.remove(storage._relay_engine, "before_cursor_execute", observe_reads)
    returned = response.json()["deliveries"][0]
    assert returned["state"] == "delivered"
    assert returned["delivered_at"] is not None
    assert returned["claim_token"] is None and returned["receipt"] is None
    trace = client.get(f"/relay/messages/{sent['message_id']}/trace", params=SCOPE).json()
    assert trace["delivery_snapshots"][0]["stored_state"] == "delivered"
