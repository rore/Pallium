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
        result = claim(client, expected, max_messages=1)
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
    result = claim(client, delivery_id, max_messages=1)
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
    result = claim(client, target["deliveries"][0]["delivery_id"], max_chars=budget, max_messages=1)
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
    result = claim(client, delivery_id, max_response_chars=budget, max_messages=1)
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


@pytest.mark.parametrize("count", [1, 8, 9, 27])
@pytest.mark.parametrize("trigger_last", [False, True])
def test_codex_wake_batch_requires_trigger_first_and_preserves_backlog(exact_client, count, trigger_last):
    client, _ = exact_client
    messages = [send(client, payload=f"finding {index} → 你好") for index in range(count)]
    trigger = messages[-1 if trigger_last else 0]
    trigger_id = trigger["deliveries"][0]["delivery_id"]
    expected = [trigger, *(item for item in messages if item is not trigger)][:8]
    result = claim(client, trigger_id, max_chars=11960, max_messages=8)
    assert [row["message_id"] for row in result["deliveries"]] == [item["message_id"] for item in expected]
    assert (result["remaining_count"], result["has_more"]) == (count - len(expected), count > len(expected))
    assert len({row["claim_token"] for row in result["deliveries"]}) == len(expected)
    for row in result["deliveries"]:
        assert row["attempts"] == 1 and row["state"] == "claimed"
        assert client.post("/relay/deliveries/ack", json={
            "delivery_id": row["delivery_id"], "claim_token": row["claim_token"], **SCOPE,
        }).status_code == 200
    assert all(status(client, item)["state"] == "delivered" for item in expected)
    for item in messages:
        if item not in expected:
            assert (status(client, item)["state"], status(client, item)["attempts"]) == ("pending", 0)
    stale = claim(client, trigger_id, max_chars=11960, max_messages=8)
    assert stale["deliveries"] == [] and stale["remaining_count"] == count - len(expected)


@pytest.mark.parametrize("condition", ["missing", "foreign", "expired", "live_claim", "unsafe", "text_budget", "json_budget"])
def test_codex_batch_never_claims_siblings_without_projected_trigger(exact_client, condition):
    client, storage = exact_client
    neighbor = send(client)
    target = send(client, recipient="other" if condition == "foreign" else "target")
    delivery_id = target["deliveries"][0]["delivery_id"]
    with storage._relay_session_factory.begin() as db:
        delivery = db.get(RelayDeliveryRecord, delivery_id)
        message = db.get(RelayMessageRecord, target["message_id"])
        if condition == "expired":
            message.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        elif condition == "live_claim":
            delivery.state, delivery.attempts = "claimed", 1
            delivery.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
        elif condition == "unsafe":
            message.payload = "unsafe\x00payload"
    if condition == "missing":
        delivery_id = "relay-delivery-" + "0" * 32
    result = claim(client, delivery_id, max_messages=8,
                   max_chars=1 if condition == "text_budget" else 11960,
                   max_response_chars=1 if condition == "json_budget" else 0)
    assert result["deliveries"] == [] and result["has_more"]
    assert (status(client, neighbor)["state"], status(client, neighbor)["attempts"]) == ("pending", 0)


@pytest.mark.parametrize("anchored", [False, True])
def test_codex_batch_fair_prefixes_include_complete_envelopes_and_unicode(exact_client, anchored):
    from integrations.codex.hooks import common

    client, _ = exact_client
    payload = "界😀é" * 5000
    messages = [send(client, payload=payload) for _ in range(4)]
    target = messages[-1]
    result = claim(client, target["deliveries"][0]["delivery_id"] if anchored else None,
                   max_messages=3, max_chars=5960)
    expected = [target, *messages[:2]] if anchored else messages[:3]
    assert [row["message_id"] for row in result["deliveries"]] == [item["message_id"] for item in expected]
    output, rendered = common.format_relay(result["deliveries"], budget_chars=6000,
                                           remaining_count=result["remaining_count"])
    assert len(output) <= 6000 and rendered == result["deliveries"]
    assert result["remaining_count"] == 1 and output.endswith("[Relay: 1 more; Pallium continues.]")
    for row in rendered:
        assert row["content_truncated"] and row["next_offset"] == len(row["payload"])
        assert row["payload"] == payload[:row["next_offset"]] and row["payload_total_chars"] == len(payload)
        complete = client.get(f"/relay/messages/{row['message_id']}", params=SCOPE).json()
        assert complete["payload"] == payload


@pytest.mark.parametrize("anchored", [False, True])
def test_codex_batch_first_envelope_can_use_whole_budget(exact_client, anchored):
    from integrations.codex.hooks import common

    client, _ = exact_client
    messages = [send(client, payload="small →") for _ in range(9)]
    trigger = messages[-1] if anchored else messages[0]
    result = claim(client, trigger["deliveries"][0]["delivery_id"] if anchored else None,
                   max_chars=1200, max_messages=8)
    assert [row["message_id"] for row in result["deliveries"]] == [trigger["message_id"]]
    output, rendered = common.format_relay(result["deliveries"], budget_chars=1240,
                                           remaining_count=result["remaining_count"])
    assert rendered == result["deliveries"] and 150 < len(output) <= 1240
    assert result["remaining_count"] == 8


def test_codex_batch_expiry_after_flush_rolls_back_every_claim(exact_client, monkeypatch):
    import time
    from sqlalchemy.orm import Session
    import storage.sqlite_relay as relay_storage

    client, _ = exact_client
    messages = [send(client) for _ in range(3)]
    expired = [False]
    clock = SimpleNamespace(**vars(time))
    clock.monotonic = lambda: time.monotonic() + (60 if expired[0] else 0)
    monkeypatch.setattr(relay_storage, "time", clock)

    def after_claim_flush(session, _context):
        if any(isinstance(row, RelayDeliveryRecord) and row.state == "claimed" for row in session.identity_map.values()):
            expired[0] = True

    event.listen(Session, "after_flush", after_claim_flush)
    try:
        response = client.post("/relay/turn", json={
            "runtime": "codex", "session_ref": "target", **SCOPE,
            "wake_delivery_id": messages[-1]["deliveries"][0]["delivery_id"],
            "max_messages": 8, "max_chars": 11960,
            "claim_expires_at_ms": int(time.time() * 1000) + 30000,
        })
    finally:
        event.remove(Session, "after_flush", after_claim_flush)
    assert response.status_code == 409 and expired[0]
    for item in messages:
        state = status(client, item)
        assert (state["state"], state["attempts"]) == ("pending", 0)


@pytest.mark.parametrize("limit", [0, 1, 3])
def test_codex_required_batch_preserves_explicit_count_meanings(exact_client, limit):
    client, _ = exact_client
    messages = [send(client) for _ in range(5)]
    trigger = messages[-1]
    expected = [trigger, *messages[:-1]][:limit or 5]
    result = claim(client, trigger["deliveries"][0]["delivery_id"], max_messages=limit)
    assert [row["message_id"] for row in result["deliveries"]] == [item["message_id"] for item in expected]
    assert result["remaining_count"] == 5 - len(expected)


def test_codex_batch_only_trigger_has_captured_wake_generation(exact_client):
    from core.codex_wake import CodexWakeReservation

    client, storage = exact_client
    messages = [send(client) for _ in range(3)]
    trigger_id = messages[-1]["deliveries"][0]["delivery_id"]
    endpoint = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target", "max_chars": 1, **SCOPE,
    }).json()["session"]["endpoint_id"]
    reservation = CodexWakeReservation(endpoint, trigger_id, "target", SCOPE["container_ref"], 42, outcome="uncertain")
    app = FastAPI()
    app.include_router(create_router(SimpleNamespace(), relay_service=RelayService(storage),
                                     relay_turn_snapshot_callback=lambda _: reservation))
    with TestClient(app) as routed:
        response = routed.post("/relay/turn", json={
            "runtime": "codex", "session_ref": "target", "wake_delivery_id": trigger_id,
            "max_messages": 3, **SCOPE,
        })
    assert response.status_code == 200, response.text
    assert response.json()["deliveries"][0]["delivery_id"] == trigger_id
    for item in messages:
        delivery_id = item["deliveries"][0]["delivery_id"]
        assert (status(client, item)["state"], status(client, item)["attempts"]) == ("claimed", 1)
        state = storage.relay_codex_wake_reservation_state(delivery_id=delivery_id)
        assert state["codex_wake_generation"] == (42 if delivery_id == trigger_id else None)


def test_codex_batch_skips_ineligible_siblings_and_rejects_stale_receipt(exact_client):
    client, storage = exact_client
    messages = [send(client, payload=f"item {index}") for index in range(6)]
    foreign = send(client, recipient="other")
    old_token = "relay-claim-old-lease"
    now = datetime.now(timezone.utc)
    with storage._relay_session_factory.begin() as db:
        db.get(RelayMessageRecord, messages[0]["message_id"]).payload = "unsafe\x00body"
        db.get(RelayMessageRecord, messages[1]["message_id"]).expires_at = now - timedelta(seconds=1)
        for index, expiry in ((2, 60), (3, -1)):
            row = db.get(RelayDeliveryRecord, messages[index]["deliveries"][0]["delivery_id"])
            row.state, row.attempts, row.claim_token = "claimed", 1, old_token
            row.lease_expires_at = now + timedelta(seconds=expiry)
    trigger_id = messages[-1]["deliveries"][0]["delivery_id"]
    result = claim(client, trigger_id, max_messages=8, max_chars=11960)
    assert [row["message_id"] for row in result["deliveries"]] == [messages[index]["message_id"] for index in (5, 3, 4)]
    assert result["remaining_count"] == 1  # Unsafe pending row is counted but never emitted.
    assert (status(client, messages[0])["state"], status(client, messages[0])["attempts"]) == ("pending", 0)
    assert status(client, messages[1])["state"] == "expired"
    assert (status(client, messages[2])["state"], status(client, messages[2])["attempts"]) == ("claimed", 1)
    assert (status(client, foreign)["state"], status(client, foreign)["attempts"]) == ("pending", 0)
    renewed = result["deliveries"][1]
    assert renewed["attempts"] == 2 and renewed["claim_token"] != old_token
    rejected = client.post("/relay/deliveries/ack", json={
        "delivery_id": renewed["delivery_id"], "claim_token": old_token, **SCOPE,
    })
    assert rejected.status_code == 409
    for row in result["deliveries"]:
        assert client.post("/relay/deliveries/ack", json={
            "delivery_id": row["delivery_id"], "claim_token": row["claim_token"], **SCOPE,
        }).status_code == 200


@pytest.mark.parametrize("budget", [2400, 6000])
def test_codex_batch_respects_compact_json_projection_limit(exact_client, monkeypatch, budget):
    import storage.sqlite_relay as relay_storage

    client, _ = exact_client
    messages = [send(client, payload="界😀" * 7500) for _ in range(3)]
    projections, measure = [], relay_storage._compact_json_chars

    def observe(value):
        projections.append(value)
        return measure(value)

    monkeypatch.setattr(relay_storage, "_compact_json_chars", observe)
    trigger_id = messages[-1]["deliveries"][0]["delivery_id"]
    result = claim(client, trigger_id, max_messages=3, max_chars=5960, max_response_chars=budget)
    selected = [row["delivery_id"] for row in result["deliveries"]]
    assert selected and selected[0] == trigger_id
    assert result["remaining_count"] == 3 - len(selected)
    assert any([row["delivery_id"] for row in value["deliveries"]] == selected and measure(value) <= budget
               for value in projections)


def test_codex_batch_scope_move_and_stale_generation_remain_atomic(exact_client):
    client, _ = exact_client
    messages = [send(client) for _ in range(3)]
    source = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target", "max_chars": 1, **SCOPE,
    }).json()["session"]
    body = {
        "runtime": "codex", "session_ref": "target", "container_ref": "git:example.test/moved",
        "previous_container_ref": SCOPE["container_ref"], "previous_endpoint_id": source["endpoint_id"],
        "previous_scope_generation": source["scope_generation"] + 1,
        "wake_delivery_id": messages[-1]["deliveries"][0]["delivery_id"], "max_messages": 8,
    }
    rejected = client.post("/relay/turn", json=body)
    assert rejected.status_code == 409
    assert all((status(client, item)["state"], status(client, item)["attempts"]) == ("pending", 0) for item in messages)
    body["previous_scope_generation"] = source["scope_generation"]
    moved = client.post("/relay/turn", json=body)
    assert moved.status_code == 200, moved.text
    assert moved.json()["session"]["endpoint_id"] == source["endpoint_id"]
    assert moved.json()["session"]["scope_generation"] == source["scope_generation"] + 1
    assert [row["message_id"] for row in moved.json()["deliveries"]] == [messages[index]["message_id"] for index in (2, 0, 1)]


def test_codex_overlapping_batch_claims_do_not_double_claim(exact_client):
    from concurrent.futures import ThreadPoolExecutor

    client, _ = exact_client
    messages = [send(client) for _ in range(3)]
    body = {"runtime": "codex", "session_ref": "target", **SCOPE,
            "wake_delivery_id": messages[-1]["deliveries"][0]["delivery_id"], "max_messages": 8}
    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(lambda _: client.post("/relay/turn", json=body), range(2)))
    assert all(response.status_code in {200, 503} for response in responses)
    claimed = [response.json()["deliveries"] for response in responses if response.status_code == 200]
    assert sum(bool(rows) for rows in claimed) == 1 and sum(map(len, claimed)) == 3
    assert all((status(client, item)["state"], status(client, item)["attempts"]) == ("claimed", 1) for item in messages)
