"""E2E tests for the MCP relay receive/ACK lifecycle.

Tests the /relay/turn + /relay/deliveries/mcp-ack contract:
at-least-once delivery, receipt-bound ACK, idempotence, lease expiry, atomic
reply from claimed state, stale-receipt race (P0 1), and drain-all (RF-008).
No raw claim tokens are required by or exposed to the caller.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

SCOPE = {"container_ref": "git:example.test/relay-mcp"}
RUNTIME = "claude-code"
SESSION = "session-mcp-test"


# ── helpers ────────────────────────────────────────────────────────────────────

def _register(client: TestClient, runtime: str = RUNTIME, session: str = SESSION) -> dict:
    resp = client.post("/relay/turn", json={"runtime": runtime, "session_ref": session, **SCOPE})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _send(
    client: TestClient,
    payload: str = "hello",
    *,
    sender_session: str = "sender-s1",
    expires_in_seconds: int | None = None,
) -> dict:
    client.post("/relay/turn", json={"runtime": "codex", "session_ref": sender_session, **SCOPE})
    body = {
        "sender_runtime": "codex",
        "sender_session_ref": sender_session,
        "recipient": f"{RUNTIME}:{SESSION}",
        "payload": payload,
        **SCOPE,
    }
    if expires_in_seconds is not None:
        body["expires_in_seconds"] = expires_in_seconds
    resp = client.post("/relay/messages", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _turn(client: TestClient, runtime: str = RUNTIME, session: str = SESSION) -> dict:
    resp = client.post("/relay/turn", json={"runtime": runtime, "session_ref": session, **SCOPE})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _mcp_ack(client: TestClient, delivery_id: str, receipt: str, **scope_override):
    return client.post("/relay/deliveries/mcp-ack", json={
        "delivery_id": delivery_id,
        "receipt": receipt,
        **{**SCOPE, **scope_override},
    })


def _reply(client: TestClient, delivery_id: str, receipt: str = "bogus-receipt", payload: str = "reply"):
    return client.post("/relay/replies", json={
        "delivery_id": delivery_id,
        "receipt": receipt,
        "payload": payload,
        **SCOPE,
    })


@pytest.fixture
def relay_storage(client: TestClient):
    return client.app.state.pallium_service._storage


# ── cases ──────────────────────────────────────────────────────────────────────

def test_empty_inbox(client: TestClient):
    result = _register(client)
    assert result["deliveries"] == []
    assert result["has_more"] is False



def test_scope_transition_preserves_endpoint_alias_work_refs_and_deliveries(client: TestClient):
    """Moving A→B keeps the endpoint identity and all endpoint-owned state."""
    a = {"container_ref": "git:example.test/transition-a"}
    b = {"container_ref": "git:example.test/transition-b"}
    sender = {"container_ref": "git:example.test/transition-sender"}
    session = "transition-✓-日本語"

    first = client.post("/relay/turn", json={"runtime": "codex", "session_ref": session, **a})
    assert first.status_code == 200, first.text
    first_session = first.json()["session"]
    endpoint = first_session["endpoint_id"]
    assert first_session["scope_generation"] == 0

    named = client.post("/relay/sessions/name", json={
        "runtime": "codex", "session_ref": session, **a,
        "alias": "transition-owner",
    })
    assert named.status_code == 200, named.text
    attached = client.post("/relay/sessions/work-refs/attach", json={
        "runtime": "codex", "session_ref": session, **a,
        "scope_ref": "tracker:v1:example.test#transition",
        "local_ref": "ticket:unicode-✓",
    })
    assert attached.status_code == 200, attached.text

    client.post("/relay/turn", json={"runtime": "codex", "session_ref": "sender", **sender})
    sent = client.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": endpoint, "payload": "queued before move", **sender,
    })
    assert sent.status_code == 200, sent.text

    moved = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": session, **b,
        "previous_container_ref": a["container_ref"],
        "previous_endpoint_id": endpoint,
        "previous_scope_generation": 0,
    })
    assert moved.status_code == 200, moved.text
    moved_session = moved.json()["session"]
    assert moved_session["endpoint_id"] == endpoint
    assert moved_session["scope_generation"] == 1
    assert moved_session["container_ref"] == b["container_ref"]
    assert moved.json()["deliveries"][0]["payload"] == "queued before move"

    refs = client.get("/relay/sessions/work-refs", params={
        "runtime": "codex", "session_ref": session, **b,
    })
    assert refs.status_code == 200, refs.text
    assert any(row["local_ref"] == "ticket:unicode-✓" for row in refs.json()["work_refs"])
    sessions = client.get("/relay/sessions", params={**b, "include_inactive": True})
    assert sessions.status_code == 200
    assert sessions.json()[0]["alias"] == "transition-owner"

    back = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": session, **a,
        "previous_container_ref": b["container_ref"],
        "previous_endpoint_id": endpoint,
        "previous_scope_generation": 1,
    })
    assert back.status_code == 200, back.text
    assert back.json()["session"]["scope_generation"] == 2

    stale = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": session, **b,
        "previous_container_ref": a["container_ref"],
        "previous_endpoint_id": endpoint,
        "previous_scope_generation": 0,
    })
    assert stale.status_code == 409
    missing = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": session, **sender,
        "previous_container_ref": "git:example.test/no-such",
        "previous_endpoint_id": endpoint,
        "previous_scope_generation": 2,
    })
    assert missing.status_code == 404

    close = client.post("/relay/sessions/close", json={"runtime": "codex", "session_ref": session, **a})
    assert close.status_code == 200
    closed = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": session, **b,
        "previous_container_ref": a["container_ref"],
        "previous_endpoint_id": endpoint,
        "previous_scope_generation": 2,
    })
    assert closed.status_code == 409

@pytest.mark.parametrize(
    "transition_fields",
    [
        {"previous_container_ref": "git:example.test/a"},
        {"previous_endpoint_id": "relay-session-00000000000000000000000000000000"},
        {"previous_scope_generation": 0},
        {"previous_container_ref": "git:example.test/a", "previous_endpoint_id": "relay-session-00000000000000000000000000000000"},
        {"previous_container_ref": "git:example.test/a", "previous_scope_generation": 0},
        {"previous_endpoint_id": "relay-session-00000000000000000000000000000000", "previous_scope_generation": 0},
    ],
)
def test_scope_transition_fields_are_all_or_none(client: TestClient, transition_fields: dict) -> None:
    response = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "partial-transition",
        "container_ref": "git:example.test/b", **transition_fields,
    })
    assert response.status_code == 422


def test_scope_transition_replay_and_same_scope_turn_are_idempotent(client: TestClient) -> None:
    old = {"container_ref": "git:example.test/replay-old"}
    new = {"container_ref": "git:example.test/replay-new"}
    first = client.post("/relay/turn", json={"runtime": "codex", "session_ref": "replay", **old}).json()["session"]
    transition = {
        "runtime": "codex", "session_ref": "replay", **new,
        "previous_container_ref": old["container_ref"],
        "previous_endpoint_id": first["endpoint_id"],
        "previous_scope_generation": 0,
    }
    moved = client.post("/relay/turn", json=transition)
    replayed = client.post("/relay/turn", json=transition)
    assert moved.status_code == replayed.status_code == 200
    assert {key: moved.json()["session"][key] for key in ("endpoint_id", "container_ref", "scope_generation")} == {key: replayed.json()["session"][key] for key in ("endpoint_id", "container_ref", "scope_generation")}
    same_scope = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "replay", **new,
        "previous_container_ref": new["container_ref"],
        "previous_endpoint_id": first["endpoint_id"],
        "previous_scope_generation": 1,
    })
    assert same_scope.status_code == 200
    assert same_scope.json()["session"]["scope_generation"] == 1
    assert client.get("/relay/sessions", params={**old, "include_inactive": True}).json() == []


def test_non_registering_turn_rejects_scope_transition_without_mutation(
    client: TestClient,
) -> None:
    old = {"container_ref": "git:example.test/non-registering-old"}
    new = {"container_ref": "git:example.test/non-registering-new"}
    first = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "non-registering-transition", **old,
    }).json()["session"]

    rejected = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "non-registering-transition", **new,
        "register_session": False,
        "previous_container_ref": old["container_ref"],
        "previous_endpoint_id": first["endpoint_id"],
        "previous_scope_generation": first["scope_generation"],
    })

    assert rejected.status_code == 409
    old_rows = client.get(
        "/relay/sessions", params={**old, "include_inactive": True}
    ).json()
    assert [row["endpoint_id"] for row in old_rows] == [first["endpoint_id"]]
    assert client.get("/relay/sessions", params={**new, "include_inactive": True}).json() == []


def test_same_scope_turn_recovers_unreachable_endpoint_with_fenced_identity(client: TestClient, relay_storage) -> None:
    scope = {"container_ref": "git:example.test/unreachable-recovery"}
    first = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "unreachable-recovery", **scope,
    }).json()["session"]
    assert relay_storage.relay_mark_unreachable(
        runtime="codex",
        session_ref="unreachable-recovery",
        **scope,
        attempt_started_at=datetime.now(timezone.utc) + timedelta(seconds=1),
    ) is True

    stale = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "unreachable-recovery", **scope,
        "previous_container_ref": scope["container_ref"],
        "previous_endpoint_id": first["endpoint_id"],
        "previous_scope_generation": first["scope_generation"] + 1,
    })
    assert stale.status_code == 409
    assert client.get("/relay/sessions", params={**scope, "include_inactive": True}).json()[0]["destination_health"] == "unreachable"

    recovered = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "unreachable-recovery", **scope,
        "previous_container_ref": scope["container_ref"],
        "previous_endpoint_id": first["endpoint_id"],
        "previous_scope_generation": first["scope_generation"],
    })
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["session"]["endpoint_id"] == first["endpoint_id"]
    assert recovered.json()["session"]["scope_generation"] == first["scope_generation"]
    assert recovered.json()["session"]["destination_health"] == "active"

    assert client.post("/relay/sessions/close", json={
        "runtime": "codex", "session_ref": "unreachable-recovery", **scope,
    }).status_code == 200
    closed = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "unreachable-recovery", **scope,
        "previous_container_ref": scope["container_ref"],
        "previous_endpoint_id": first["endpoint_id"],
        "previous_scope_generation": first["scope_generation"],
    })
    assert closed.status_code == 409

def test_scope_transition_destination_conflicts_never_mutate_either_session(client: TestClient) -> None:
    old = {"container_ref": "git:example.test/conflict-old"}
    occupied = {"container_ref": "git:example.test/conflict-destination"}
    session = "same-runtime-session"
    source = client.post("/relay/turn", json={"runtime": "codex", "session_ref": session, **old}).json()["session"]
    destination = client.post("/relay/turn", json={"runtime": "codex", "session_ref": session, **occupied}).json()["session"]
    transition = {
        "runtime": "codex", "session_ref": session, **occupied,
        "previous_container_ref": old["container_ref"],
        "previous_endpoint_id": source["endpoint_id"],
        "previous_scope_generation": 0,
    }
    assert client.post("/relay/turn", json=transition).status_code == 409
    assert client.post("/relay/sessions/close", json={"runtime": "codex", "session_ref": session, **occupied}).status_code == 200
    assert client.post("/relay/turn", json=transition).status_code == 409
    old_rows = client.get("/relay/sessions", params={**old, "include_inactive": True}).json()
    occupied_rows = client.get("/relay/sessions", params={**occupied, "include_inactive": True}).json()
    assert [(row["endpoint_id"], row["state"]) for row in old_rows] == [(source["endpoint_id"], "recent")]
    assert [(row["endpoint_id"], row["state"]) for row in occupied_rows] == [(destination["endpoint_id"], "closed")]

def test_reply_follows_sender_endpoint_after_sender_scope_transition(client: TestClient) -> None:
    recipient_scope = {"container_ref": "git:example.test/reply-recipient"}
    sender_old = {"container_ref": "git:example.test/reply-sender-old"}
    sender_new = {"container_ref": "git:example.test/reply-sender-new"}
    recipient = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "reply-recipient", **recipient_scope,
    }).json()["session"]
    sender = client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "reply-sender", **sender_old,
    }).json()["session"]
    sent = client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "reply-sender",
        "recipient": recipient["endpoint_id"], "payload": "request before move", **sender_old,
    })
    assert sent.status_code == 200, sent.text
    claimed = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "reply-recipient", **recipient_scope,
    }).json()["deliveries"][0]
    moved = client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "reply-sender", **sender_new,
        "previous_container_ref": sender_old["container_ref"],
        "previous_endpoint_id": sender["endpoint_id"],
        "previous_scope_generation": 0,
    })
    assert moved.status_code == 200, moved.text
    reply = client.post("/relay/replies", json={
        "delivery_id": claimed["delivery_id"], "receipt": claimed["receipt"],
        "payload": "reply after sender moved", **recipient_scope,
    })
    assert reply.status_code == 200, reply.text
    received = client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "reply-sender", **sender_new,
    }).json()["deliveries"]
    assert [delivery["payload"] for delivery in received] == ["reply after sender moved"]
    assert received[0]["recipient_endpoint_id"] == sender["endpoint_id"]

def test_receive_one_and_ack(client: TestClient):
    _register(client)
    _send(client, "payload-one")

    turn = _turn(client)
    assert len(turn["deliveries"]) == 1
    d = turn["deliveries"][0]
    assert d["payload"] == "payload-one"
    assert d["receipt"] is not None

    resp = _mcp_ack(client, d["delivery_id"], d["receipt"])
    assert resp.status_code == 200
    assert resp.json()["state"] == "delivered"

    assert _turn(client)["deliveries"] == []


def test_mcp_ack_idempotent(client: TestClient):
    _register(client)
    _send(client)

    d = _turn(client)["deliveries"][0]
    first = _mcp_ack(client, d["delivery_id"], d["receipt"])
    assert first.status_code == 200
    assert first.json()["already_delivered"] is False
    resp2 = _mcp_ack(client, d["delivery_id"], d["receipt"])
    assert resp2.status_code == 200
    assert resp2.json()["state"] == "delivered"
    assert resp2.json()["already_delivered"] is True


def test_mcp_ack_stale_receipt_returns_409(client: TestClient, relay_storage):
    """P0 1: stale ACK from prior claim generation must not mark the new claim delivered."""
    _register(client)
    _send(client)

    d = _turn(client)["deliveries"][0]
    stale_receipt = d["receipt"]

    # Expire the lease — delivery re-enters reclaimable pool
    from storage.sqlite_schema import RelayDeliveryRecord
    with relay_storage._begin_relay_immediate() as db:
        rec = db.get(RelayDeliveryRecord, d["delivery_id"])
        rec.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    # Re-claim (new claim generation → new receipt)
    turn2 = _turn(client)
    assert len(turn2["deliveries"]) == 1
    new_receipt = turn2["deliveries"][0]["receipt"]
    assert new_receipt != stale_receipt

    # Stale receipt from claim A must be rejected during claim B
    assert _mcp_ack(client, d["delivery_id"], stale_receipt).status_code == 409
    # Correct receipt succeeds
    assert _mcp_ack(client, d["delivery_id"], new_receipt).status_code == 200


def test_mcp_ack_same_actor_cross_container_returns_200(client: TestClient):
    _register(client)
    _send(client)
    d = _turn(client)["deliveries"][0]
    assert _mcp_ack(client, d["delivery_id"], d["receipt"], container_ref="git:other/repo").status_code == 200


def test_mcp_ack_not_claimed_returns_409(client: TestClient):
    _register(client)
    msg = _send(client)
    # delivery is pending (never claimed via /relay/turn); any receipt returns 409
    delivery_id = msg["deliveries"][0]["delivery_id"]
    assert _mcp_ack(client, delivery_id, "fake-receipt-not-claimed").status_code == 409


def test_unicode_payload(client: TestClient):
    _register(client)
    payload = "日本語 🦾 αβγδ résumé"
    _send(client, payload)

    turn = _turn(client)
    d = turn["deliveries"][0]
    assert d["payload"] == payload
    assert _mcp_ack(client, d["delivery_id"], d["receipt"]).status_code == 200


def test_backlog_drained_in_multiple_turns(client: TestClient):
    _register(client)
    for i in range(5):
        _send(client, f"msg-{i}")

    seen = set()
    while True:
        turn = _turn(client)
        for d in turn["deliveries"]:
            seen.add(d["delivery_id"])
            assert _mcp_ack(client, d["delivery_id"], d["receipt"]).status_code == 200
        if not turn["has_more"]:
            break

    assert len(seen) == 5
    assert _turn(client)["deliveries"] == []


def test_lease_expiry_causes_redelivery(client: TestClient, relay_storage):
    _register(client)
    _send(client)

    d = _turn(client)["deliveries"][0]

    # Expire the lease without ACKing
    from storage.sqlite_schema import RelayDeliveryRecord
    with relay_storage._begin_relay_immediate() as db:
        rec = db.get(RelayDeliveryRecord, d["delivery_id"])
        rec.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    # ACK fails — lease is expired
    assert _mcp_ack(client, d["delivery_id"], d["receipt"]).status_code == 409

    # Delivery is reclaimable on next turn
    turn2 = _turn(client)
    assert len(turn2["deliveries"]) == 1


def test_atomic_reply_from_claimed_state(client: TestClient):
    """P0 3: reply from claimed state atomically ACKs and sends reply."""
    _register(client)
    _send(client, "needs reply")

    d = _turn(client)["deliveries"][0]
    # delivery is claimed; reply atomically ACKs it (no prior pallium_relay_ack needed)
    resp = _reply(client, d["delivery_id"], d["receipt"])
    assert resp.status_code == 200

    # Delivery is now delivered — cannot ACK again (idempotent → 200) or re-reply
    assert _mcp_ack(client, d["delivery_id"], d["receipt"]).status_code == 200  # idempotent


@pytest.mark.parametrize("lease_delta_seconds", [30, 0], ids=["live-claim", "also-expired"])
def test_reply_rejects_message_expired_at_boundary(
    client: TestClient,
    relay_storage,
    monkeypatch: pytest.MonkeyPatch,
    lease_delta_seconds: int,
):
    _register(client)
    sent = _send(client, "expires after claim", expires_in_seconds=60)
    delivery = _turn(client)["deliveries"][0]
    boundary = datetime.now(timezone.utc)

    import storage.sqlite_relay as sqlite_relay
    from storage.sqlite_schema import RelayDeliveryRecord, RelayMessageRecord
    real_now = sqlite_relay._now
    monkeypatch.setattr(
        sqlite_relay,
        "_now",
        lambda value=None: boundary if value is None else real_now(value),
    )
    with relay_storage._begin_relay_immediate() as db:
        db.get(RelayMessageRecord, sent["message_id"]).expires_at = boundary
        db.get(RelayDeliveryRecord, delivery["delivery_id"]).lease_expires_at = (
            boundary + timedelta(seconds=lease_delta_seconds)
        )

    response = _reply(client, delivery["delivery_id"], delivery["receipt"])
    assert response.status_code == 409
    assert response.json()["detail"] == "message has expired"
    with relay_storage._begin_relay_immediate() as db:
        stored = db.get(RelayDeliveryRecord, delivery["delivery_id"])
        assert stored.state == "expired"
        assert stored.claim_token is None
    status = client.get(f"/relay/messages/{sent['message_id']}", params=SCOPE)
    assert status.status_code == 200, status.text
    assert status.json()["deliveries"][0]["state"] == "expired"
    assert _turn(client, runtime="codex", session="sender-s1")["deliveries"] == []


def test_ack_before_long_work_allows_late_reply(client: TestClient, relay_storage):
    _register(client)
    sent = _send(client, "long work", expires_in_seconds=60)
    delivery = _turn(client)["deliveries"][0]
    assert _mcp_ack(client, delivery["delivery_id"], delivery["receipt"]).status_code == 200

    from storage.sqlite_schema import RelayDeliveryRecord, RelayMessageRecord
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    with relay_storage._begin_relay_immediate() as db:
        db.get(RelayMessageRecord, sent["message_id"]).expires_at = past
        db.get(RelayDeliveryRecord, delivery["delivery_id"]).lease_expires_at = past

    response = _reply(client, delivery["delivery_id"], delivery["receipt"], "finished later")
    assert response.status_code == 200
    status = client.get(f"/relay/messages/{sent['message_id']}", params=SCOPE)
    assert status.status_code == 200, status.text
    assert status.json()["deliveries"][0]["state"] == "delivered"
    replies = _turn(client, runtime="codex", session="sender-s1")["deliveries"]
    assert [item["payload"] for item in replies] == ["finished later"]


def test_reply_requires_receipt(client: TestClient):
    """Reply to a claimed delivery without a receipt is rejected."""
    _register(client)
    _send(client, "reply-test")

    d = _turn(client)["deliveries"][0]
    # Wrong receipt → 409
    resp = client.post("/relay/replies", json={
        "delivery_id": d["delivery_id"],
        "receipt": "wrong-receipt-value",
        "payload": "reply",
        **SCOPE,
    })
    assert resp.status_code == 409


def test_one_active_claim_at_a_time(client: TestClient):
    """Second /relay/turn call while a claim is active returns empty."""
    _register(client)
    _send(client)

    turn1 = _turn(client)
    assert len(turn1["deliveries"]) == 1
    d = turn1["deliveries"][0]

    # Delivery is claimed — second turn sees nothing
    turn2 = _turn(client)
    assert turn2["deliveries"] == []

    assert _mcp_ack(client, d["delivery_id"], d["receipt"]).status_code == 200


def test_no_double_delivery_after_ack(client: TestClient):
    _register(client)
    _send(client, "once only")

    d = _turn(client)["deliveries"][0]
    assert _mcp_ack(client, d["delivery_id"], d["receipt"]).status_code == 200

    for _ in range(3):
        assert _turn(client)["deliveries"] == []


# ── RF-008: drain-all regression ───────────────────────────────────────────────

def test_drain_all_beyond_legacy_char_limit(client: TestClient):
    """All pending deliveries are returned in one turn regardless of combined payload size."""
    _register(client)
    payloads = [f"message-{i}: {'x' * 700}" for i in range(4)]
    for p in payloads:
        _send(client, p, sender_session=f"drain-sender-{payloads.index(p)}")

    response = client.post("/relay/turn", json={
        "runtime": RUNTIME, "session_ref": SESSION,
        "max_chars": 0, "max_messages": 0, **SCOPE,
    })
    assert response.status_code == 200
    turn = response.json()
    assert len(turn["deliveries"]) == 4, f"expected 4, got {len(turn['deliveries'])}"
    assert turn["has_more"] is False
    assert turn["remaining_count"] == 0

    for d in turn["deliveries"]:
        assert _mcp_ack(client, d["delivery_id"], d["receipt"]).status_code == 200
    assert _turn(client)["deliveries"] == []


def test_drain_fifo_order(client: TestClient):
    """Deliveries are returned in send order (FIFO)."""
    _register(client)
    for i in range(3):
        _send(client, f"msg-{i}", sender_session=f"fifo-sender-{i}")

    deliveries = _turn(client)["deliveries"]
    assert len(deliveries) == 3
    payloads = [d["payload"] for d in deliveries]
    assert payloads == ["msg-0", "msg-1", "msg-2"]


def test_explicit_max_chars_still_pages(client: TestClient):
    """A caller-set max_chars > 0 still limits the returned set (paging contract preserved)."""
    _register(client)
    for i in range(3):
        _send(client, f"page-msg-{i}", sender_session=f"page-sender-{i}")

    resp = client.post("/relay/turn", json={
        "runtime": RUNTIME, "session_ref": SESSION, "max_chars": 100, **SCOPE,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["deliveries"]) < 3
    assert data["has_more"] is True


def test_concurrent_session_isolation(client: TestClient):
    """Two MCP sessions with different session_refs cannot receive or ACK each other's mail.

    Proves that pallium_relay_receive's PALLIUM_THREAD_REF binding is load-bearing:
    session B's turn never returns session A's deliveries, and a wrong receipt
    from session B cannot ACK session A's claimed delivery.
    """
    runtime = "claude-code"
    session_a = "iso-session-a"
    session_b = "iso-session-b"
    sender_session = "iso-sender"

    # register all three sessions
    for sess in (session_a, session_b, sender_session):
        rt = runtime if sess != sender_session else "codex"
        client.post("/relay/turn", json={"runtime": rt, "session_ref": sess, **SCOPE})

    # send a message addressed specifically to session A
    resp = client.post("/relay/messages", json={
        "sender_runtime": "codex",
        "sender_session_ref": sender_session,
        "recipient": f"{runtime}:{session_a}",
        "payload": "only-for-a",
        **SCOPE,
    })
    assert resp.status_code == 200

    # session B's turn sees nothing — delivery is not addressed to it
    turn_b = client.post("/relay/turn", json={"runtime": runtime, "session_ref": session_b, **SCOPE}).json()
    assert turn_b["deliveries"] == []

    # session A claims the delivery
    turn_a = client.post("/relay/turn", json={"runtime": runtime, "session_ref": session_a, **SCOPE}).json()
    assert len(turn_a["deliveries"]) == 1
    d = turn_a["deliveries"][0]
    assert d["receipt"] is not None

    # session B cannot ACK with a wrong receipt — 409
    assert _mcp_ack(client, d["delivery_id"], "wrong-receipt-from-b").status_code == 409

    # delivery is still claimed; session A can ACK it correctly
    assert _mcp_ack(client, d["delivery_id"], d["receipt"]).status_code == 200


def test_atomic_reply_redacts_and_keeps_receipt_idempotent(client: TestClient):
    _register(client)
    _send(client, "redact reply")
    delivery = _turn(client)["deliveries"][0]

    response = _reply(
        client,
        delivery["delivery_id"],
        delivery["receipt"],
        "Authorization: Bearer secret-reply-value",
    )
    assert response.status_code == 200
    result = response.json()
    assert result["redacted"] is True
    assert "secret-reply-value" not in result["payload"]

    assert _mcp_ack(client, delivery["delivery_id"], delivery["receipt"]).status_code == 200
    assert _mcp_ack(client, delivery["delivery_id"], "wrong-receipt-after-delivery").status_code == 409


def test_atomic_reply_failure_rolls_back_delivery_claim(client: TestClient, relay_storage):
    _register(client)
    _send(client, "rollback reply", sender_session="closed-original-sender")
    delivery = _turn(client)["deliveries"][0]

    close = client.post(
        "/relay/sessions/close",
        json={"runtime": "codex", "session_ref": "closed-original-sender", **SCOPE},
    )
    assert close.status_code == 200
    response = _reply(client, delivery["delivery_id"], delivery["receipt"], "cannot deliver")
    assert response.status_code == 409
    assert response.json()["detail"] == "recipient session is closed"

    from sqlalchemy import select
    from storage.sqlite_schema import RelayDeliveryRecord, RelayMessageRecord

    with relay_storage._relay_session_factory() as db:
        stored_delivery = db.get(RelayDeliveryRecord, delivery["delivery_id"])
        reply = db.execute(
            select(RelayMessageRecord).where(
                RelayMessageRecord.in_reply_to == delivery["message_id"]
            )
        ).scalar_one_or_none()
    assert stored_delivery.state == "claimed"
    assert reply is None