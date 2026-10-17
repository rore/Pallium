from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from api.routes import create_router
from core.relay import RelayService
from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import RelayDeliveryRecord, RelayMessageRecord


SCOPE = {"container_ref": "git:example.test/relay-東京"}


@pytest.fixture
def exact_client(tmp_path, monkeypatch):
    from itertools import count
    import threading
    import time
    from storage import sqlite_queue

    storage = SQLiteStorageProvider(
        f"sqlite:///{tmp_path / 'main.db'}", f"sqlite:///{tmp_path / 'relay.db'}"
    )
    app = FastAPI()
    app.include_router(create_router(SimpleNamespace(), relay_service=RelayService(storage)))
    try:
        with TestClient(app) as client:
            native_turn, native_time = storage.relay_turn, sqlite_queue.time
            native_monotonic = time.monotonic

            def initial_session(**kwargs):
                provider_thread = threading.get_ident()
                setup_time = SimpleNamespace(**vars(native_time))
                logical_monotonic = count(step=.001).__next__
                setup_time.monotonic = lambda: (logical_monotonic()
                    if threading.get_ident() == provider_thread else native_monotonic())
                with monkeypatch.context() as admission:
                    admission.setattr(sqlite_queue, "time", setup_time)
                    return native_turn(**kwargs)

            with monkeypatch.context() as setup:
                setup.setattr(storage, "relay_turn", initial_session)
                for name in ("sender", "target", "other"):
                    assert client.post("/relay/turn", json={
                        "runtime": "codex", "session_ref": name, **SCOPE,
                    }).status_code == 200
            assert storage.relay_turn == native_turn and sqlite_queue.time is native_time
            assert time.monotonic is native_monotonic
            yield client, storage
    finally:
        storage.close()


def send(client, recipient="target", payload="event → 你好"):
    result = client.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": f"codex:{recipient}", "payload": payload, **SCOPE,
    })
    assert result.status_code == 200, result.text
    return result.json()


def claim(client, delivery_id, **budgets):
    result = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target",
        "wake_delivery_id": delivery_id, **budgets, **SCOPE,
    })
    assert result.status_code == 200, result.text
    return result.json()


def status(client, message):
    result = client.get(f"/relay/messages/{message['message_id']}", params=SCOPE)
    assert result.status_code == 200, result.text
    return result.json()["deliveries"][0]


def test_exact_claim_hydrates_only_requested_payload_and_preserves_backlog(exact_client):
    client, _ = exact_client
    messages = [send(client, payload="界" * 4000) for _ in range(100)]
    expected = messages[-1]["deliveries"][0]["delivery_id"]
    loaded = []

    def loaded_message(record, context):
        loaded.append(record.id)

    event.listen(RelayMessageRecord, "load", loaded_message)
    try:
        result = claim(client, expected)
    finally:
        event.remove(RelayMessageRecord, "load", loaded_message)
    assert [row["delivery_id"] for row in result["deliveries"]] == [expected]
    assert result["deliveries"][0]["payload"] == "界" * 4000
    assert (result["remaining_count"], result["has_more"]) == (99, True)
    assert loaded == [messages[-1]["message_id"]]
    for message in messages[:-1]:
        unchanged = status(client, message)
        assert (unchanged["state"], unchanged["attempts"]) == ("pending", 0)
    selected = status(client, messages[-1])
    assert (selected["state"], selected["attempts"]) == ("claimed", 1)


@pytest.mark.parametrize("condition", ["missing", "wrong_endpoint", "expired", "live_claim", "expired_claim", "unsafe"])
def test_exact_claim_preserves_eligibility_and_never_claims_neighbor(exact_client, condition):
    client, storage = exact_client
    neighbor = send(client)
    target = send(client, recipient="other" if condition == "wrong_endpoint" else "target")
    delivery_id = target["deliveries"][0]["delivery_id"]
    now = datetime.now(timezone.utc)
    if condition in ("expired", "live_claim", "expired_claim", "unsafe"):
        with storage._relay_session_factory.begin() as db:
            delivery = db.get(RelayDeliveryRecord, delivery_id)
            message = db.get(RelayMessageRecord, target["message_id"])
            if condition == "expired":
                message.expires_at = now - timedelta(seconds=1)
            elif condition == "unsafe":
                message.payload = "invalid\x00payload"
            else:
                delivery.state = "claimed"
                delivery.attempts = 1
                delivery.lease_expires_at = now + timedelta(seconds=60 if condition == "live_claim" else -1)
    if condition == "missing":
        delivery_id = "relay-delivery-" + "0" * 32
    result = claim(client, delivery_id)
    if condition == "expired_claim":
        assert [(row["delivery_id"], row["attempts"]) for row in result["deliveries"]] == [(delivery_id, 2)]
    else:
        assert result["deliveries"] == []
    assert result["remaining_count"] == (2 if condition in ("missing", "unsafe") else 1)
    assert result["has_more"] is True
    unchanged = status(client, neighbor)
    assert (unchanged["state"], unchanged["attempts"]) == ("pending", 0)


@pytest.mark.parametrize("budget", [1, 1000, 0])
def test_exact_claim_unicode_budget_and_unsafe_neighbor_count(exact_client, budget):
    client, storage = exact_client
    neighbor = send(client)
    target = send(client, payload="界" * 4000)
    with storage._relay_session_factory.begin() as db:
        db.get(RelayMessageRecord, neighbor["message_id"]).payload = "invalid\x00payload"
    result = claim(client, target["deliveries"][0]["delivery_id"], max_chars=budget)
    assert result["remaining_count"] == (2 if budget == 1 else 1)
    assert result["has_more"] is True
    if budget == 1:
        assert result["deliveries"] == []
    else:
        payload = result["deliveries"][0]["payload"]
        assert result["deliveries"][0]["delivery_id"] == target["deliveries"][0]["delivery_id"]
        assert payload and set(payload) == {"界"}
        assert len(payload) == 4000 if budget == 0 else len(payload) < 1000
    selected = status(client, target)
    assert (selected["state"], selected["attempts"]) == (("pending", 0) if budget == 1 else ("claimed", 1))
    unchanged = status(client, neighbor)
    assert (unchanged["state"], unchanged["attempts"]) == ("pending", 0)


@pytest.mark.parametrize("budget", [1, 4000])
def test_exact_claim_json_budget_preserves_count_metadata(exact_client, monkeypatch, budget):
    import storage.sqlite_relay as relay_storage

    client, _ = exact_client
    neighbor = send(client)
    target = send(client, payload="界" * 4000)
    projections = []
    measure = relay_storage._compact_json_chars

    def observe(value):
        projections.append(value)
        return measure(value)

    monkeypatch.setattr(relay_storage, "_compact_json_chars", observe)
    delivery_id = target["deliveries"][0]["delivery_id"]
    result = claim(client, delivery_id, max_response_chars=budget)
    assert result["remaining_count"] == (2 if budget == 1 else 1)
    assert result["has_more"] is True
    if budget == 1:
        assert result["deliveries"] == []
    else:
        delivery = result["deliveries"][0]
        assert delivery["delivery_id"] == delivery_id
        assert 0 < len(delivery["payload"]) < 4000
        assert any(
            projection["remaining_count"] == 1
            and projection["deliveries"][0]["payload"] == delivery["payload"]
            and measure(projection) <= budget
            for projection in projections
        )
    selected = status(client, target)
    assert (selected["state"], selected["attempts"]) == (("pending", 0) if budget == 1 else ("claimed", 1))
    unchanged = status(client, neighbor)
    assert (unchanged["state"], unchanged["attempts"]) == ("pending", 0)


def test_ordinary_claim_loads_bounded_metadata_and_only_selected_payload(exact_client):
    client, storage = exact_client
    messages = [send(client, payload="界" * 4000) for _ in range(100)]
    loaded, payload_reads = [], []

    def on_load(record, context):
        loaded.append(record.id)
        if "payload" in record.__dict__:
            payload_reads.append(record.id)

    def on_refresh(record, context, attributes):
        if "payload" in attributes:
            payload_reads.append(record.id)

    event.listen(RelayMessageRecord, "load", on_load)
    event.listen(RelayMessageRecord, "refresh", on_refresh)
    try:
        result = claim(client, None, max_messages=1)
    finally:
        event.remove(RelayMessageRecord, "load", on_load)
        event.remove(RelayMessageRecord, "refresh", on_refresh)
    assert [row["delivery_id"] for row in result["deliveries"]] == [messages[0]["deliveries"][0]["delivery_id"]]
    assert result["deliveries"][0]["payload"] == "界" * 4000
    assert result["remaining_count"] == 99 and result["has_more"]
    assert len(loaded) <= 16
    assert payload_reads == [messages[0]["message_id"]]
    assert (status(client, messages[-1])["state"], status(client, messages[-1])["attempts"]) == ("pending", 0)


@pytest.mark.parametrize("limit", [1, 17, 0])
def test_ordinary_claim_crosses_batches_and_preserves_order(exact_client, limit):
    client, storage = exact_client
    rejected = [send(client) for _ in range(20)]
    messages = [send(client) for _ in range(20)]
    with storage._relay_session_factory.begin() as db:
        for item in rejected:
            db.get(RelayMessageRecord, item["message_id"]).payload = "invalid\x00payload"
    result = claim(client, None, max_messages=limit)
    selected = messages[:limit] if limit else messages
    assert [row["delivery_id"] for row in result["deliveries"]] == [item["deliveries"][0]["delivery_id"] for item in selected]
    assert result["remaining_count"] == 40 - len(selected)
    assert result["has_more"]
    for item in rejected + messages[len(selected):]:
        unchanged = status(client, item)
        assert (unchanged["state"], unchanged["attempts"]) == ("pending", 0)


def test_ordinary_claim_lazy_read_failure_closes_cursor_without_partial_claim(exact_client, monkeypatch):
    from sqlalchemy.orm import Session

    client, storage = exact_client
    messages = [send(client) for _ in range(3)]
    results, reads = [], []
    execute = Session.execute

    def capture_result(session, statement, *args, **kwargs):
        result = execute(session, statement, *args, **kwargs)
        if statement.get_execution_options().get("yield_per"):
            results.append(result)
        return result

    def fail_second_payload(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lower().startswith("select relay_messages.payload"):
            reads.append(statement)
            if len(reads) == 2:
                raise RuntimeError("synthetic payload read failure")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "execute", capture_result)
        event.listen(storage._relay_engine, "before_cursor_execute", fail_second_payload)
        try:
            with pytest.raises(RuntimeError, match="synthetic payload read failure"):
                claim(client, None, max_messages=2)
        finally:
            event.remove(storage._relay_engine, "before_cursor_execute", fail_second_payload)
    assert results and all(result.closed for result in results)
    for message in messages:
        unchanged = status(client, message)
        assert (unchanged["state"], unchanged["attempts"]) == ("pending", 0)
    result = claim(client, None, max_messages=2)
    assert [row["delivery_id"] for row in result["deliveries"]] == [item["deliveries"][0]["delivery_id"] for item in messages[:2]]
