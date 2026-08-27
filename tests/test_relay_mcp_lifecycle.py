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

SCOPE = {"container_ref": "git:example.test/relay-mcp", "actor_ref": "test-actor"}
RUNTIME = "claude-code"
SESSION = "session-mcp-test"


# ── helpers ────────────────────────────────────────────────────────────────────

def _register(client: TestClient, runtime: str = RUNTIME, session: str = SESSION) -> dict:
    resp = client.post("/relay/turn", json={"runtime": runtime, "session_ref": session, **SCOPE})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _send(client: TestClient, payload: str = "hello", *, sender_session: str = "sender-s1") -> dict:
    client.post("/relay/turn", json={"runtime": "codex", "session_ref": sender_session, **SCOPE})
    resp = client.post("/relay/messages", json={
        "sender_runtime": "codex",
        "sender_session_ref": sender_session,
        "recipient": f"{RUNTIME}:{SESSION}",
        "payload": payload,
        **SCOPE,
    })
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
    assert _mcp_ack(client, d["delivery_id"], d["receipt"]).status_code == 200
    resp2 = _mcp_ack(client, d["delivery_id"], d["receipt"])
    assert resp2.status_code == 200
    assert resp2.json()["state"] == "delivered"


def test_mcp_ack_stale_receipt_returns_409(client: TestClient, relay_storage):
    """P0 1: stale ACK from prior claim generation must not mark the new claim delivered."""
    _register(client)
    _send(client)

    d = _turn(client)["deliveries"][0]
    stale_receipt = d["receipt"]

    # Expire the lease — delivery re-enters reclaimable pool
    from storage.sqlite_schema import RelayDeliveryRecord
    with relay_storage._begin_immediate() as db:
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


def test_mcp_ack_wrong_container_returns_404(client: TestClient):
    _register(client)
    _send(client)
    d = _turn(client)["deliveries"][0]
    assert _mcp_ack(client, d["delivery_id"], d["receipt"], container_ref="git:other/repo").status_code == 404


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
    with relay_storage._begin_immediate() as db:
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

    turn = _turn(client)
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
    assert response.status_code == 404

    from sqlalchemy import select
    from storage.sqlite_schema import RelayDeliveryRecord, RelayMessageRecord

    with relay_storage._session_factory() as db:
        stored_delivery = db.get(RelayDeliveryRecord, delivery["delivery_id"])
        reply = db.execute(
            select(RelayMessageRecord).where(
                RelayMessageRecord.in_reply_to == delivery["message_id"]
            )
        ).scalar_one_or_none()
    assert stored_delivery.state == "claimed"
    assert reply is None