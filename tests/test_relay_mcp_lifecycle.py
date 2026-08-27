"""E2E tests for the MCP relay receive/ACK lifecycle.

Tests the /relay/turn + /relay/deliveries/mcp-ack contract:
at-least-once delivery, scope-gated ACK, idempotence, lease expiry, and
reply-as-atomic-ACK. No claim tokens are required by the caller.
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
    # Sender must be a registered relay session
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


def _mcp_ack(client: TestClient, delivery_id: str, *,
             runtime: str = RUNTIME, session: str = SESSION, **scope_override) -> "Response":
    return client.post("/relay/deliveries/mcp-ack", json={
        "delivery_id": delivery_id,
        "runtime": runtime,
        "session_ref": session,
        **{**SCOPE, **scope_override},
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

    resp = _mcp_ack(client, d["delivery_id"])
    assert resp.status_code == 200
    assert resp.json()["state"] == "delivered"

    assert _turn(client)["deliveries"] == []


def test_mcp_ack_idempotent(client: TestClient):
    _register(client)
    _send(client)

    delivery_id = _turn(client)["deliveries"][0]["delivery_id"]
    assert _mcp_ack(client, delivery_id).status_code == 200
    resp2 = _mcp_ack(client, delivery_id)
    assert resp2.status_code == 200
    assert resp2.json()["state"] == "delivered"


def test_mcp_ack_wrong_session_returns_404(client: TestClient):
    _register(client)
    _send(client)
    delivery_id = _turn(client)["deliveries"][0]["delivery_id"]
    assert _mcp_ack(client, delivery_id, session="wrong-session").status_code == 404


def test_mcp_ack_wrong_container_returns_404(client: TestClient):
    _register(client)
    _send(client)
    delivery_id = _turn(client)["deliveries"][0]["delivery_id"]
    assert _mcp_ack(client, delivery_id, container_ref="git:other/repo").status_code == 404


def test_mcp_ack_not_claimed_returns_409(client: TestClient):
    _register(client)
    msg = _send(client)
    # delivery is pending (never claimed via /relay/turn)
    delivery_id = msg["deliveries"][0]["delivery_id"]
    assert _mcp_ack(client, delivery_id).status_code == 409


def test_unicode_payload(client: TestClient):
    _register(client)
    payload = "日本語 🦾 αβγδ résumé"
    _send(client, payload)

    turn = _turn(client)
    assert turn["deliveries"][0]["payload"] == payload
    assert _mcp_ack(client, turn["deliveries"][0]["delivery_id"]).status_code == 200


def test_backlog_drained_in_multiple_turns(client: TestClient):
    _register(client)
    for i in range(5):
        _send(client, f"msg-{i}")

    seen = set()
    while True:
        turn = _turn(client)
        for d in turn["deliveries"]:
            seen.add(d["delivery_id"])
            assert _mcp_ack(client, d["delivery_id"]).status_code == 200
        if not turn["has_more"]:
            break

    assert len(seen) == 5
    assert _turn(client)["deliveries"] == []


def test_lease_expiry_causes_redelivery(client: TestClient, relay_storage):
    _register(client)
    _send(client)

    delivery_id = _turn(client)["deliveries"][0]["delivery_id"]

    # Expire the lease without ACKing
    from storage.sqlite_schema import RelayDeliveryRecord
    with relay_storage._begin_immediate() as db:
        d = db.get(RelayDeliveryRecord, delivery_id)
        d.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    # ACK fails — lease is expired
    assert _mcp_ack(client, delivery_id).status_code == 409

    # Delivery is reclaimable on next turn
    turn2 = _turn(client)
    assert len(turn2["deliveries"]) == 1


def test_reply_after_ack(client: TestClient):
    _register(client)
    _send(client, "needs reply")

    delivery_id = _turn(client)["deliveries"][0]["delivery_id"]

    # Must ACK (delivered) before reply
    assert _mcp_ack(client, delivery_id).status_code == 200

    resp = client.post("/relay/replies", json={"delivery_id": delivery_id, "payload": "reply", **SCOPE})
    assert resp.status_code == 200

    # Reply to a claimed (unacked) delivery is rejected
    _send(client, "reply-test-2")
    delivery_id2 = _turn(client)["deliveries"][0]["delivery_id"]
    resp409 = client.post("/relay/replies", json={"delivery_id": delivery_id2, "payload": "too-soon", **SCOPE})
    assert resp409.status_code == 409


def test_one_active_claim_at_a_time(client: TestClient):
    """Second /relay/turn call while a claim is active returns empty."""
    _register(client)
    _send(client)

    turn1 = _turn(client)
    assert len(turn1["deliveries"]) == 1
    delivery_id = turn1["deliveries"][0]["delivery_id"]

    # Delivery is claimed — second turn sees nothing
    turn2 = _turn(client)
    assert turn2["deliveries"] == []

    assert _mcp_ack(client, delivery_id).status_code == 200


def test_no_double_delivery_after_ack(client: TestClient):
    _register(client)
    _send(client, "once only")

    delivery_id = _turn(client)["deliveries"][0]["delivery_id"]
    assert _mcp_ack(client, delivery_id).status_code == 200

    for _ in range(3):
        assert _turn(client)["deliveries"] == []
