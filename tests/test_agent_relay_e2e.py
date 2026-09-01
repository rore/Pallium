from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.routes import create_router
from core.errors import ImmediateTransactionBusyError
from storage.sqlite_schema import RelayMessageRecord


SCOPE = {"container_ref": "git:example.test/team/relay", "actor_ref": "local-user"}


def _turn(client, runtime: str, session: str, **extra):
    body = {"runtime": runtime, "session_ref": session, **SCOPE, **extra}
    response = client.post("/relay/turn", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _send(client, sender_runtime: str, sender: str, recipient: str, payload: str = "finding", **extra):
    body = {
        "sender_runtime": sender_runtime,
        "sender_session_ref": sender,
        "recipient": recipient,
        "payload": payload,
        **SCOPE,
        **extra,
    }
    return client.post("/relay/messages", json=body)


def _name(client, runtime: str, session: str, alias, **extra):
    return client.post(
        "/relay/sessions/name",
        json={"runtime": runtime, "session_ref": session, "alias": alias, **SCOPE, **extra},
    )


def _reply(client, delivery_id: str, payload: str = "reply", receipt: str | None = None, **extra):
    body = {"delivery_id": delivery_id, "payload": payload, **SCOPE, **extra}
    if receipt is not None:
        body["receipt"] = receipt
    return client.post("/relay/replies", json=body)


def _status(client, message_id: str, **scope):
    return client.get("/relay/messages/" + message_id, params={**SCOPE, **scope})


def _ack(client, delivery, token=None, **scope):
    return client.post(
        "/relay/deliveries/ack",
        json={
            "delivery_id": delivery["delivery_id"],
            "claim_token": token or delivery["claim_token"],
            **SCOPE,
            **scope,
        },
    )


@pytest.fixture
def relay_storage(client):
    return client.app.state.pallium_service._storage


def test_full_broadcast_snapshot_alias_transfer_reply_and_lifecycle(client):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "review-old", title="review")
    _turn(client, "codex", "review-new", title="review")

    assert _name(client, "codex", "review-old", "review").status_code == 200
    old = _send(client, "claude-code", "sender", "codex:@review", "old target").json()
    assert old["deliveries"][0]["recipient_session_ref"] == "review-old"

    conflict = _name(client, "codex", "review-new", "review")
    assert conflict.status_code == 409
    assert "replace_existing=true" in conflict.json()["detail"]
    assert _name(client, "codex", "review-new", "review", replace_existing=True).status_code == 200

    new = _send(client, "claude-code", "sender", "codex:@review", "new target").json()
    assert new["deliveries"][0]["recipient_session_ref"] == "review-new"
    assert _status(client, old["message_id"]).json()["deliveries"][0]["recipient_session_ref"] == "review-old"

    broadcast = _send(client, "claude-code", "sender", "codex", "all current").json()
    assert {d["recipient_session_ref"] for d in broadcast["deliveries"]} == {"review-old", "review-new"}
    _turn(client, "codex", "later")
    assert {d["recipient_session_ref"] for d in _status(client, broadcast["message_id"]).json()["deliveries"]} == {
        "review-old",
        "review-new",
    }

    first_claim = _turn(client, "codex", "review-old")["deliveries"][0]
    assert _ack(client, first_claim).status_code == 200
    assert _ack(client, first_claim).status_code == 200

    reply1 = _send(
        client, "codex", "review-old", "claude-code:sender", "reply one",
        in_reply_to=old["message_id"],
    ).json()
    reply2 = _send(
        client, "claude-code", "sender", "codex:review-old", "reply two",
        in_reply_to=reply1["message_id"],
    ).json()
    reply3 = _send(
        client, "codex", "review-old", "claude-code:sender", "reply three",
        in_reply_to=reply2["message_id"],
    )
    assert reply3.status_code == 200

    close = client.post(
        "/relay/sessions/close",
        json={"runtime": "codex", "session_ref": "review-new", **SCOPE},
    )
    assert close.status_code == 200
    assert close.json()["alias"] is None
    assert _send(client, "claude-code", "sender", "codex:review-new").status_code in (404, 409)
    assert _turn(client, "codex", "review-new")["session"]["state"] == "recent"
    assert _name(client, "codex", "review-new", "review").status_code == 200


def test_aliases_are_actor_scoped_and_replacement_cannot_clear_another_actor(client):
    _turn(client, "codex", "actor-one-old", actor_ref="actor-one")
    _turn(client, "codex", "actor-one-new", actor_ref="actor-one")
    _turn(client, "codex", "actor-two-target", actor_ref="actor-two")
    _turn(client, "claude-code", "actor-two-sender", actor_ref="actor-two")

    assert _name(
        client, "codex", "actor-one-old", "review", actor_ref="actor-one"
    ).status_code == 200
    assert _name(
        client, "codex", "actor-two-target", "review", actor_ref="actor-two"
    ).status_code == 200
    assert _name(
        client, "codex", "actor-one-new", "review",
        actor_ref="actor-one", replace_existing=True,
    ).status_code == 200

    sent = _send(
        client, "claude-code", "actor-two-sender", "codex:@review", actor_ref="actor-two"
    ).json()
    assert sent["deliveries"][0]["recipient_session_ref"] == "actor-two-target"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("", 422),
        ("   ", 422),
        ("x" * 1500, 200),
        ("x" * 1501, 422),
        ("😀" * 1500, 200),
        ("😀" * 1501, 422),
        ("line one\nline two\tvalue", 200),
        ("unsafe\x00value", 422),
        ("unsafe\x1fvalue", 422),
        ("unsafe\u2028value", 422),
    ],
)
def test_payload_boundaries_unicode_and_controls(client, payload, expected):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "target")
    response = _send(client, "claude-code", "sender", "codex:target", payload)
    assert response.status_code == expected, response.text


def test_identity_selector_scope_and_state_errors_are_visible(client):
    _turn(client, "claude-code", "sender")
    assert client.post("/relay/turn", json={"runtime": "other", "session_ref": "x", **SCOPE}).status_code == 422
    assert client.post("/relay/turn", json={"runtime": "codex", "session_ref": "bad\x00", **SCOPE}).status_code == 422
    assert _send(client, "claude-code", "sender", "codex:missing").status_code in (404, 409)
    assert _send(client, "claude-code", "sender", "codex:@missing").status_code in (404, 409)
    assert _send(client, "claude-code", "sender", "codex").status_code == 409
    assert _send(client, "claude-code", "sender", "bad").status_code == 422
    assert _name(client, "codex", "missing", "alias").status_code == 404
    assert _status(client, "missing").status_code == 404

    _turn(client, "codex", "target")
    message = _send(client, "claude-code", "sender", "codex:target").json()
    assert _status(client, message["message_id"], actor_ref="different").status_code == 404
    assert client.get(
        "/relay/sessions", params={**SCOPE, "container_ref": "git:other"}
    ).json() == []


def test_message_id_idempotency_redaction_and_reply_scope(client):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "target")
    first = _send(
        client,
        "claude-code",
        "sender",
        "codex:target",
        "Authorization: Bearer secret-value",
        message_id="stable-message",
    )
    assert first.status_code == 200
    assert first.json()["redacted"] is True
    assert "secret-value" not in first.json()["payload"]

    same = _send(
        client,
        "claude-code",
        "sender",
        "codex:target",
        "Authorization: Bearer secret-value",
        message_id="stable-message",
    )
    assert same.status_code == 200
    changed = _send(
        client, "claude-code", "sender", "codex:target", "changed", message_id="stable-message"
    )
    assert changed.status_code == 409
    changed_expiry = _send(
        client, "claude-code", "sender", "codex:target",
        "Authorization: Bearer secret-value", message_id="stable-message",
        expires_in_seconds=60,
    )
    assert changed_expiry.status_code == 409

    _turn(client, "claude-code", "other-scope-sender", container_ref="git:other")
    collision = _send(
        client, "claude-code", "other-scope-sender", "codex:missing",
        message_id="stable-message", container_ref="git:other",
    )
    assert collision.status_code == 404
    assert collision.json()["detail"] == "relay entity not found in the requested scope"

    wrong_scope_parent = _send(
        client, "claude-code", "sender", "codex:target", "reply", in_reply_to="missing"
    )
    assert wrong_scope_parent.status_code == 404


def test_delivery_derived_reply_is_attributed_scoped_and_idempotent(client):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "target")
    parent = _send(client, "claude-code", "sender", "codex:target", "question").json()
    delivery = parent["deliveries"][0]

    assert _reply(client, delivery["delivery_id"]).status_code == 409
    claimed = _turn(client, "codex", "target")["deliveries"][0]
    assert _reply(client, claimed["delivery_id"]).status_code == 409
    first_ack = _ack(client, claimed)
    assert first_ack.status_code == 200
    assert first_ack.json()["already_delivered"] is False
    retry_ack = _ack(client, claimed)
    assert retry_ack.status_code == 200
    assert retry_ack.json()["already_delivered"] is True

    first = _reply(client, claimed["delivery_id"], "תשובה → 你好")
    assert first.status_code == 200
    body = first.json()
    assert body["sender_runtime"] == "codex"
    assert body["sender_session_ref"] == "target"
    assert body["recipient"] == "claude-code:sender"
    assert body["in_reply_to"] == parent["message_id"]
    assert body["payload"] == "תשובה → 你好"

    duplicate = _reply(client, claimed["delivery_id"], "תשובה → 你好")
    assert duplicate.status_code == 200
    assert duplicate.json()["message_id"] == body["message_id"]
    assert len(duplicate.json()["deliveries"]) == 1
    assert _reply(
        client, claimed["delivery_id"], "תשובה → 你好", expires_in_seconds=60
    ).status_code == 409
    assert _reply(client, claimed["delivery_id"], "different").status_code == 409

    assert _reply(client, "missing").status_code == 404
    assert _reply(client, claimed["delivery_id"], actor_ref="different").status_code == 404
    assert _reply(client, claimed["delivery_id"], container_ref="git:other").status_code == 404


def test_delivery_derived_reply_chain_and_boundaries(client):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "target")
    parent = _send(client, "claude-code", "sender", "codex:target", "question").json()
    delivered = _turn(client, "codex", "target")["deliveries"][0]
    assert _ack(client, delivered).status_code == 200

    assert _reply(client, delivered["delivery_id"], "x" * 1500, expires_in_seconds=60).status_code == 200
    assert _reply(client, delivered["delivery_id"], "x" * 1501).status_code == 422
    assert _reply(client, delivered["delivery_id"], "x", expires_in_seconds=59).status_code == 422
    assert _reply(client, delivered["delivery_id"], "x", expires_in_seconds=604801).status_code == 422

    reply_delivery = _turn(client, "claude-code", "sender")["deliveries"][0]
    assert _ack(client, reply_delivery).status_code == 200
    second = _reply(client, reply_delivery["delivery_id"], "second reply")
    assert second.status_code == 200
    assert second.json()["sender_runtime"] == "claude-code"
    assert second.json()["sender_session_ref"] == "sender"
    assert second.json()["recipient"] == "codex:target"
    assert second.json()["in_reply_to"].startswith("relay-reply-")


def test_broadcast_zero_exact_max_and_over_max(client):
    _turn(client, "claude-code", "sender")
    assert _send(client, "claude-code", "sender", "codex").status_code == 409
    for index in range(25):
        _turn(client, "codex", f"target-{index:02d}")
    at_max = _send(client, "claude-code", "sender", "codex", message_id="at-max")
    assert at_max.status_code == 200
    assert len(at_max.json()["deliveries"]) == 25
    _turn(client, "codex", "target-25")
    over = _send(client, "claude-code", "sender", "codex", message_id="over-max")
    assert over.status_code == 409
    assert _status(client, "over-max").status_code == 404


def test_concurrent_claim_lease_recovery_stale_token_and_expiry(client, relay_storage):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "target")
    message = _send(client, "claude-code", "sender", "codex:target").json()

    def claim():
        return client.post("/relay/turn", json={"runtime": "codex", "session_ref": "target", **SCOPE}).json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    claimed = [delivery for result in results for delivery in result["deliveries"]]
    assert len(claimed) == 1
    old = claimed[0]

    for _ in range(2):
        with relay_storage._relay_engine.begin() as connection:
            connection.execute(
                text("UPDATE relay_deliveries SET lease_expires_at=:past WHERE id=:id"),
                {"past": datetime.now(timezone.utc) - timedelta(seconds=1), "id": old["delivery_id"]},
            )
        fresh = _turn(client, "codex", "target")["deliveries"][0]
        assert fresh["delivery_id"] == old["delivery_id"]
        assert fresh["claim_token"] != old["claim_token"]
        assert _ack(client, old).status_code == 409
        old = fresh

    assert _ack(client, old).status_code == 200
    assert _ack(client, old).status_code == 200

    expiring = _send(client, "claude-code", "sender", "codex:target", message_id="expiring").json()
    with relay_storage._relay_engine.begin() as connection:
        connection.execute(
            text("UPDATE relay_messages SET expires_at=:past WHERE id=:id"),
            {"past": datetime.now(timezone.utc) - timedelta(seconds=1), "id": "expiring"},
        )
    expired = _status(client, expiring["message_id"])
    assert expired.status_code == 200
    assert expired.json()["deliveries"][0]["state"] == "expired"
    assert _turn(client, "codex", "target")["deliveries"] == []


def test_dormant_hidden_default_exact_addressable_and_reactivated(client, relay_storage):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "dormant")
    with relay_storage._relay_engine.begin() as connection:
        connection.execute(
            text("UPDATE relay_sessions SET last_seen_at=:old WHERE session_ref=:session_ref"),
            {"old": datetime.now(timezone.utc) - timedelta(days=2), "session_ref": "dormant"},
        )
    visible = client.get("/relay/sessions", params=SCOPE).json()
    assert "dormant" not in {row["session_ref"] for row in visible}
    all_rows = client.get("/relay/sessions", params={**SCOPE, "include_inactive": True}).json()
    assert next(row for row in all_rows if row["session_ref"] == "dormant")["state"] == "dormant"

    direct = _send(client, "claude-code", "sender", "codex:dormant")
    assert direct.status_code == 200
    assert _send(client, "claude-code", "sender", "codex").status_code == 409
    reactivated = _turn(client, "codex", "dormant")
    assert reactivated["session"]["state"] == "recent"
    assert len(reactivated["deliveries"]) == 1


def test_relay_has_no_memory_retrieval_or_processing_side_effects(client, relay_storage):
    count_queries = {
        "source_items": text("SELECT COUNT(*) FROM source_items"),
        "memory_objects": text("SELECT COUNT(*) FROM memory_objects"),
        "query_audit_log": text("SELECT COUNT(*) FROM query_audit_log"),
        "historical_lookup_reuse_event": text(
            "SELECT COUNT(*) FROM historical_lookup_reuse_event"
        ),
        "package_processing_status": text("SELECT COUNT(*) FROM package_processing_status"),
        "index_entries": text("SELECT COUNT(*) FROM index_entries"),
    }
    with relay_storage._engine.begin() as connection:
        before = {
            name: connection.execute(statement).scalar_one()
            for name, statement in count_queries.items()
        }

    _turn(client, "claude-code", "sender")
    _turn(client, "opencode", "target")
    sent = _send(client, "claude-code", "sender", "opencode:target", "durable handoff").json()
    claimed = _turn(client, "opencode", "target")["deliveries"][0]
    assert _ack(client, claimed).status_code == 200
    assert _status(client, sent["message_id"]).json()["deliveries"][0]["state"] == "delivered"

    with relay_storage._engine.begin() as connection:
        after = {
            name: connection.execute(statement).scalar_one()
            for name, statement in count_queries.items()
        }
    assert after == before


def test_maximum_message_and_identity_envelope_is_claimable(client):
    sender = "s" * 255
    _turn(client, "claude-code", sender)
    _turn(client, "codex", "target")
    parent_id = "p" * 128
    parent = _send(
        client, "claude-code", sender, "codex:target", "parent", message_id=parent_id,
    )
    assert parent.status_code == 200
    parent_claim = _turn(client, "codex", "target")["deliveries"][0]
    assert _ack(client, parent_claim).status_code == 200

    message_id = "m" * 128
    sent = _send(
        client,
        "claude-code",
        sender,
        "codex:target",
        "😀" * 1500,
        message_id=message_id,
        in_reply_to=parent_id,
    )
    assert sent.status_code == 200
    turn = client.post(
        "/relay/turn",
        json={"runtime": "codex", "session_ref": "target", "max_chars": 2400, **SCOPE},
    )
    assert turn.status_code == 200
    claimed = turn.json()["deliveries"]
    assert [delivery["message_id"] for delivery in claimed] == [message_id]
    assert _ack(client, claimed[0]).status_code == 200

def test_expiry_boundaries_and_complete_message_turn_budget(client):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "target")
    assert _send(client, "claude-code", "sender", "codex:target", expires_in_seconds=59).status_code == 422
    assert _send(client, "claude-code", "sender", "codex:target", expires_in_seconds=60).status_code == 200
    assert _send(client, "claude-code", "sender", "codex:target", expires_in_seconds=604800).status_code == 200
    assert _send(client, "claude-code", "sender", "codex:target", expires_in_seconds=604801).status_code == 422

    _turn(client, "codex", "budget-target")
    for index in range(3):
        response = _send(
            client, "claude-code", "sender", "codex:budget-target",
            "x" * 1000, message_id=f"budget-{index}",
        )
        assert response.status_code == 200
    first_turn = client.post(
        "/relay/turn",
        json={"runtime": "codex", "session_ref": "budget-target", "max_chars": 2000, **SCOPE},
    )
    assert first_turn.status_code == 200
    claimed = first_turn.json()["deliveries"]
    assert len(claimed) == 1
    assert len(claimed[0]["payload"]) == 1000
    assert _ack(client, claimed[0]).status_code == 200
    assert _turn(client, "codex", "budget-target")["deliveries"]


def test_turn_message_cap_alias_release_and_queued_close_reactivation(client):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "target")
    assert _name(client, "codex", "target", "review").status_code == 200
    for index in range(4):
        assert _send(
            client, "claude-code", "sender", "codex:@review",
            f"message {index}", message_id=f"cap-{index}",
        ).status_code == 200

    close = client.post(
        "/relay/sessions/close",
        json={"runtime": "codex", "session_ref": "target", **SCOPE},
    )
    assert close.status_code == 200
    assert close.json()["alias"] is None
    assert client.post(
        "/relay/sessions/close",
        json={"runtime": "codex", "session_ref": "target", **SCOPE},
    ).status_code == 200

    first = _turn(client, "codex", "target")["deliveries"]
    assert len(first) == 4
    for delivery in first:
        assert _ack(client, delivery).status_code == 200
    assert _turn(client, "codex", "target")["deliveries"] == []

    assert _name(client, "codex", "target", "review").status_code == 200
    released = _name(client, "codex", "target", None)
    assert released.status_code == 200
    assert released.json()["alias"] is None
    assert _send(client, "claude-code", "sender", "codex:@review").status_code == 404


@pytest.mark.parametrize("max_chars", [-1, -100])
def test_turn_budget_rejects_negative_values(client, max_chars):
    response = client.post(
        "/relay/turn",
        json={"runtime": "codex", "session_ref": "target", "max_chars": max_chars, **SCOPE},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("max_chars", [0, 2401, 100_000])
def test_turn_budget_accepts_zero_and_large_values(client, max_chars):
    response = client.post(
        "/relay/turn",
        json={
            "runtime": "codex",
            "session_ref": f"budget-{max_chars}",
            "max_chars": max_chars,
            **SCOPE,
        },
    )
    assert response.status_code == 200

def test_small_turn_budget_skips_oversized_message_without_blocking_later_delivery(client):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "small-budget-target")
    assert _send(
        client, "claude-code", "sender", "codex:small-budget-target",
        "x" * 1000, message_id="oversized-first",
    ).status_code == 200
    assert _send(
        client, "claude-code", "sender", "codex:small-budget-target",
        "fits", message_id="fits-second",
    ).status_code == 200
    claimed = _turn(client, "codex", "small-budget-target", max_chars=400)["deliveries"]
    assert [delivery["message_id"] for delivery in claimed] == ["fits-second"]
    assert _ack(client, claimed[0]).status_code == 200
    assert (
        _turn(client, "codex", "small-budget-target")["deliveries"][0]["message_id"]
        == "oversized-first"
    )

def test_non_relay_router_returns_501_only_for_relay(client):
    app = FastAPI()
    app.include_router(create_router(client.app.state.pallium_service))
    fallback = TestClient(app)
    assert fallback.post("/relay/turn", json={"runtime": "codex", "session_ref": "s", **SCOPE}).status_code == 501
    assert fallback.get("/items/missing/processing").status_code == 404


def test_turn_reports_backlog_and_only_claims_rendered_deliveries(client):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "backlog-target")
    for index in range(3):
        assert _send(
            client, "claude-code", "sender", "codex:backlog-target",
            "x" * 1000, message_id=f"backlog-{index}",
        ).status_code == 200

    delivered: list[str] = []
    while True:
        turn = _turn(client, "codex", "backlog-target")
        claimed = turn["deliveries"]
        assert claimed
        assert turn["remaining_count"] == 3 - len(delivered) - len(claimed)
        assert turn["has_more"] is (turn["remaining_count"] > 0)
        for delivery in claimed:
            assert _ack(client, delivery).status_code == 200
            delivered.append(delivery["message_id"])
        if not turn["has_more"]:
            break

    assert delivered == ["backlog-0", "backlog-1", "backlog-2"]


def test_relay_busy_is_retryable_and_does_not_expose_sqlite_details(client, relay_storage, monkeypatch):
    def busy_transaction():
        raise ImmediateTransactionBusyError("database is locked")

    monkeypatch.setattr(relay_storage, "_begin_relay_immediate", busy_transaction)
    response = client.post("/relay/turn", json={"runtime": "codex", "session_ref": "busy", **SCOPE})
    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.json()["detail"] == {"code": "relay_busy", "retryable": True}

def test_atomic_reply_busy_uses_retryable_contract(client, relay_storage, monkeypatch):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "target")
    sent = _send(client, "claude-code", "sender", "codex:target").json()
    delivery = _turn(client, "codex", "target")["deliveries"][0]

    def busy_transaction():
        raise ImmediateTransactionBusyError("database is locked")

    monkeypatch.setattr(relay_storage, "_begin_relay_immediate", busy_transaction)
    response = client.post("/relay/replies", json={
        "delivery_id": delivery["delivery_id"],
        "receipt": delivery["receipt"],
        "payload": "reply",
        **SCOPE,
    })

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.json()["detail"] == {"code": "relay_busy", "retryable": True}
    monkeypatch.undo()
    status = client.get(f"/relay/messages/{sent['message_id']}", params=SCOPE)
    assert status.status_code == 200, status.text
    assert status.json()["deliveries"][0]["state"] == "claimed"


def test_retrying_busy_send_with_same_id_creates_one_delivery(client, relay_storage, monkeypatch):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "target")
    original = relay_storage._begin_relay_immediate
    attempts = 0

    @contextmanager
    def busy_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ImmediateTransactionBusyError("database is locked")
        with original() as db:
            yield db

    monkeypatch.setattr(relay_storage, "_begin_relay_immediate", busy_once)
    body = {
        "message_id": "relay-msg-stable-retry",
        "sender_runtime": "claude-code",
        "sender_session_ref": "sender",
        "recipient": "codex:target",
        "payload": "once",
        **SCOPE,
    }
    first = client.post("/relay/messages", json=body)
    second = client.post("/relay/messages", json=body)
    repeated = client.post("/relay/messages", json=body)

    assert first.status_code == 503
    assert second.status_code == 200
    assert repeated.status_code == 200
    assert second.json()["message_id"] == repeated.json()["message_id"]
    assert len(second.json()["deliveries"]) == 1
    assert second.json()["deliveries"][0]["delivery_id"] == repeated.json()["deliveries"][0]["delivery_id"]

def test_turn_does_not_claim_a_legacy_payload_that_the_formatter_rejects(client, relay_storage):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "legacy-target")
    sent = _send(client, "claude-code", "sender", "codex:legacy-target", "safe").json()
    with relay_storage._relay_session_factory.begin() as db:
        db.get(RelayMessageRecord, sent["message_id"]).payload = "unsafe\u2028legacy"

    turn = _turn(client, "codex", "legacy-target")
    assert turn["deliveries"] == []
    assert turn["has_more"] is False
    assert turn["remaining_count"] == 0

def test_turn_skips_legacy_unsafe_rows_and_drains_later_safe_delivery(client, relay_storage):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "mixed-legacy-target")
    unsafe = _send(client, "claude-code", "sender", "codex:mixed-legacy-target", "unsafe").json()
    safe = _send(client, "claude-code", "sender", "codex:mixed-legacy-target", "safe").json()
    with relay_storage._relay_session_factory.begin() as db:
        db.get(RelayMessageRecord, unsafe["message_id"]).payload = "unsafe\u2028legacy"

    turn = _turn(client, "codex", "mixed-legacy-target")
    assert [delivery["message_id"] for delivery in turn["deliveries"]] == [safe["message_id"]]
    assert turn["has_more"] is False
    assert turn["remaining_count"] == 0
    assert _ack(client, turn["deliveries"][0]).status_code == 200
    assert _turn(client, "codex", "mixed-legacy-target")["deliveries"] == []
