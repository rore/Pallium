from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


SCOPE = {"container_ref": "git:example.test/team/relay"}


def _turn(client, session="native", runtime="opencode"):
    response = client.post("/relay/turn", json={"runtime": runtime, "session_ref": session, **SCOPE})
    assert response.status_code == 200, response.text
    return response.json()


def _wake(client, base, operation, **extra):
    body = {**base, "operation": operation, **extra}
    return client.post("/relay/opencode/wake", json=body)


def _setup(client, session="native", location="C:/work/session.json"):
    turn = _turn(client, session)
    base = {
        **SCOPE,
        "session_ref": session,
        "endpoint_id": turn["session"]["endpoint_id"],
        "scope_generation": turn["session"]["scope_generation"],
        "native_location": location,
        "owner_id": "opencode-owner-0123456789abcdef0123456789abcdef",
    }
    enrolled = _wake(client, base, "enroll")
    assert enrolled.status_code == 200, enrolled.text
    return base


def _send(client, base, payload="hello", expires_in_seconds=86400):
    _turn(client, "sender", "codex")
    return client.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": "opencode:" + base["session_ref"], "payload": payload, "expires_in_seconds": expires_in_seconds, **SCOPE,
    })


def _snapshot(base, wake):
    return {**base, "generation": wake["generation"], "delivery_id": wake["delivery_id"],
            "native_input_id": wake["native_input_id"]}


def _activation(client, base):
    rows = client.get("/relay/sessions", params={**SCOPE, "runtime": "opencode"}).json()
    return next(row["activation"] for row in rows if row["endpoint_id"] == base["endpoint_id"])


def test_idle_then_pending_backlog_is_drained_one_at_a_time(client):
    base = _setup(client)
    assert _activation(client, base)["behavior"] == "busy_queue"
    idle = _wake(client, base, "poll").json()
    assert idle["wake"] is None
    sent = [_send(client, base, str(i)).json() for i in range(4)]
    for index, message in enumerate(sent):
        wake = _wake(client, base, "poll").json()["wake"]
        assert wake["delivery_id"] == message["deliveries"][0]["delivery_id"]
        snap = _snapshot(base, wake)
        context = _wake(client, base, "context", **snap)
        assert context.status_code == 200, context.text
        delivery = context.json()["deliveries"][0]
        assert delivery["message_id"] == message["message_id"]
        ack = client.post("/relay/deliveries/ack", json={
            "delivery_id": delivery["delivery_id"], "claim_token": delivery["claim_token"], **SCOPE,
        })
        assert ack.status_code == 200, ack.text
        terminal = _wake(client, base, "terminal", **snap, terminal_message_id=f"msg_terminal_{index}")
        assert terminal.status_code == 200, terminal.text
        assert terminal.json()["wake"]["delivery_id"] == wake["delivery_id"]
    assert _wake(client, base, "poll").json()["wake"] is None


def test_admit_terminal_retains_anchor_until_poll_then_retries(client, monkeypatch):
    import storage.sqlite_relay as sqlite_relay

    base = _setup(client)
    _send(client, base)
    wake = _wake(client, base, "poll").json()["wake"]
    snap = _snapshot(base, wake)
    assert _wake(client, base, "admitted", **snap).status_code == 200
    terminal = _wake(client, base, "terminal", **snap, terminal_message_id="msg_terminal_1")
    assert terminal.status_code == 200, terminal.text
    assert terminal.json()["wake"]["delivery_id"] == wake["delivery_id"]
    real_now = sqlite_relay._now
    clock = [datetime.now(timezone.utc)]
    monkeypatch.setattr(sqlite_relay, "_now", lambda value=None: real_now(value) if value is not None else clock[0])
    clock[0] += timedelta(seconds=3)
    assert _wake(client, base, "poll").json()["wake"]["generation"] == wake["generation"] + 1


def test_terminal_before_claim_suppresses_context_until_poll_rotates(client, monkeypatch):
    import storage.sqlite_relay as sqlite_relay

    base = _setup(client)
    sent = _send(client, base).json()
    wake = _wake(client, base, "poll").json()["wake"]
    snap = _snapshot(base, wake)
    terminal = _wake(client, base, "terminal", **snap, terminal_message_id="msg_terminal_unclaimed")
    assert terminal.status_code == 200, terminal.text
    blocked = _wake(client, base, "context", **snap)
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["deliveries"] == []
    assert client.get("/relay/messages/" + sent["message_id"], params=SCOPE).json()["deliveries"][0]["state"] == "pending"
    real_now = sqlite_relay._now
    clock = [datetime.now(timezone.utc)]
    monkeypatch.setattr(sqlite_relay, "_now", lambda value=None: real_now(value) if value is not None else clock[0])
    clock[0] += timedelta(seconds=3)
    rotated = _wake(client, base, "poll").json()["wake"]
    assert rotated["generation"] == wake["generation"] + 1
    assert rotated["delivery_id"] == wake["delivery_id"]


def test_context_exact_claim_ack_and_response_loss_are_idempotent(client):
    base = _setup(client)
    sent = _send(client, base).json()
    wake = _wake(client, base, "poll").json()["wake"]
    snap = _snapshot(base, wake)
    claimed = _wake(client, base, "context", **snap)
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["deliveries"][0]["delivery_id"] == wake["delivery_id"]
    delivery = claimed.json()["deliveries"][0]
    ack = client.post("/relay/deliveries/ack", json={"delivery_id": delivery["delivery_id"], "claim_token": delivery["claim_token"], **SCOPE})
    assert ack.status_code == 200, ack.text
    restored = _wake(client, base, "context", **snap)
    assert restored.status_code == 200, restored.text
    assert restored.json()["restored"] is True
    assert _wake(client, base, "context", **snap).json()["restored"] is True
    assert client.get("/relay/messages/" + sent["message_id"], params=SCOPE).json()["deliveries"][0]["state"] == "delivered"


def test_expired_claim_lease_can_be_recovered_through_context(client, monkeypatch):
    import storage.sqlite_relay as sqlite_relay

    base = _setup(client)
    _send(client, base)
    wake = _wake(client, base, "poll").json()["wake"]
    snap = _snapshot(base, wake)
    first = _wake(client, base, "context", **snap).json()["deliveries"][0]
    real_now = sqlite_relay._now
    clock = [datetime.now(timezone.utc)]
    monkeypatch.setattr(sqlite_relay, "_now", lambda value=None: real_now(value) if value is not None else clock[0])
    for _ in range(4):
        clock[0] += timedelta(seconds=14)
        assert _wake(client, base, "poll").status_code == 200
    clock[0] += timedelta(seconds=5)
    assert _wake(client, base, "poll").status_code == 200
    stale = _wake(client, base, "context", **snap)
    assert stale.status_code == 200, stale.text
    assert stale.json()["deliveries"] == []
    terminal = _wake(client, base, "terminal", **snap, terminal_message_id="msg_terminal_expired_lease")
    assert terminal.status_code == 200, terminal.text
    clock[0] += timedelta(seconds=3)
    rotated = _wake(client, base, "poll").json()["wake"]
    assert rotated["generation"] == wake["generation"] + 1
    recovered = _wake(client, base, "context", **_snapshot(base, rotated))
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["deliveries"][0]["delivery_id"] == first["delivery_id"]
    assert recovered.json()["deliveries"][0]["attempts"] == first["attempts"] + 1


def test_owner_lease_expiry_allows_rebind_without_losing_anchor(client, monkeypatch):
    import storage.sqlite_relay as sqlite_relay

    base = _setup(client)
    _send(client, base)
    wake = _wake(client, base, "poll").json()["wake"]
    real_now = sqlite_relay._now
    clock = [datetime.now(timezone.utc)]
    monkeypatch.setattr(sqlite_relay, "_now", lambda value=None: real_now(value) if value is not None else clock[0])
    next_owner = {**base, "owner_id": "opencode-owner-abcdef0123456789abcdef0123456789"}
    clock[0] += timedelta(seconds=16)
    assert _activation(client, base)["behavior"] == "passive"
    enrolled = _wake(client, next_owner, "enroll")
    assert enrolled.status_code == 200, enrolled.text
    rebound = _wake(client, next_owner, "poll").json()["wake"]
    assert rebound["delivery_id"] == wake["delivery_id"]


@pytest.mark.parametrize("field,value", [
    ("session_ref", "elsewhere"), ("container_ref", "git:example.test/other/repo"),
    ("endpoint_id", "relay-session-00000000000000000000000000000000"),
    ("scope_generation", 99), ("native_location", "C:/other/session.json"),
    ("owner_id", "opencode-owner-ffffffffffffffffffffffffffffffff"),
])
def test_stale_or_wrong_binding_is_rejected(client, field, value):
    base = _setup(client)
    invalid = {**base, field: value}
    assert _wake(client, invalid, "poll").status_code in (404, 409)


@pytest.mark.parametrize("body", [
    {}, {"operation": "unknown"}, {"operation": "enroll", "scope_generation": True},
    {"operation": "enroll", "scope_generation": 1.5},
    {"operation": "enroll", "scope_generation": 2**63},
    {"operation": "context", "generation": 1},
    {"operation": "terminal", "terminal_message_id": "msg_same"},
    {"operation": "detach", "unexpected": True},
])
def test_invalid_or_incomplete_requests_are_rejected(client, body):
    base = _setup(client)
    assert client.post("/relay/opencode/wake", json={**base, **body}).status_code in (409, 422)


def test_max_chars_boundary_and_unicode_payload(client):
    base = _setup(client)
    _send(client, base, "界" * 2400)
    wake = _wake(client, base, "poll").json()["wake"]
    assert _wake(client, base, "context", **_snapshot(base, wake), max_chars=2400).status_code == 200
    assert _wake(client, base, "context", **_snapshot(base, wake), max_chars=2401).status_code == 422


def test_detach_blocks_old_owner_and_reenroll_allows_same_anchor(client):
    base = _setup(client)
    _send(client, base)
    wake = _wake(client, base, "poll").json()["wake"]
    assert _wake(client, base, "detach").status_code == 200
    assert _activation(client, base)["behavior"] == "passive"
    assert _wake(client, base, "poll").status_code == 409
    enrolled = _wake(client, base, "enroll")
    assert enrolled.status_code == 200, enrolled.text
    rebound = _wake(client, base, "poll").json()["wake"]
    assert rebound["delivery_id"] == wake["delivery_id"]


def test_scope_move_invalidates_old_context(client):
    base = _setup(client)
    _send(client, base)
    wake = _wake(client, base, "poll").json()["wake"]
    moved = client.post("/relay/turn", json={"runtime": "opencode", "session_ref": base["session_ref"],
        "container_ref": "git:example.test/team/moved", "previous_container_ref": SCOPE["container_ref"],
        "previous_endpoint_id": base["endpoint_id"], "previous_scope_generation": base["scope_generation"]})
    assert moved.status_code == 200, moved.text
    assert _wake(client, base, "context", **_snapshot(base, wake)).status_code in (404, 409, 422)


def test_closed_reopened_session_cannot_restore_old_wake(client):
    base = _setup(client)
    _send(client, base)
    wake = _wake(client, base, "poll").json()["wake"]
    snap = _snapshot(base, wake)
    delivery = _wake(client, base, "context", **snap).json()["deliveries"][0]
    assert client.post("/relay/deliveries/ack", json={**SCOPE,
        "delivery_id": delivery["delivery_id"], "claim_token": delivery["claim_token"]}).status_code == 200
    assert client.post("/relay/sessions/close", json={**SCOPE,
        "runtime": "opencode", "session_ref": base["session_ref"]}).status_code == 200
    assert _wake(client, base, "context", **snap).status_code == 409
    _turn(client)
    assert _wake(client, base, "enroll").status_code == 200
    assert _wake(client, base, "context", **snap).status_code == 409
    assert _wake(client, base, "poll").json()["wake"] is None


def test_claim_response_loss_reuses_token_but_not_after_expiry(client, monkeypatch):
    import storage.sqlite_relay as sqlite_relay

    base = _setup(client)
    sent = _send(client, base, expires_in_seconds=60).json()
    real_now = sqlite_relay._now
    clock = [real_now(datetime.fromisoformat(sent["expires_at"])) - timedelta(seconds=10)]
    monkeypatch.setattr(sqlite_relay, "_now", lambda value=None: real_now(value) if value is not None else clock[0])
    assert _wake(client, base, "enroll").status_code == 200
    wake = _wake(client, base, "poll").json()["wake"]
    snap = _snapshot(base, wake)
    first = _wake(client, base, "context", **snap).json()["deliveries"][0]
    repeated = _wake(client, base, "context", **snap).json()["deliveries"][0]
    assert (repeated["claim_token"], repeated["attempts"]) == (first["claim_token"], first["attempts"])
    # Message expiry and owner expiry are independent: reenroll before expiry,
    # then assert the earlier finite claim cannot return an expired envelope.
    assert _wake(client, base, "enroll").status_code == 200
    clock[0] += timedelta(seconds=11)
    result = _wake(client, base, "context", **snap)
    assert result.status_code == 200 and result.json()["deliveries"] == []
    status = client.get("/relay/messages/" + sent["message_id"], params=SCOPE).json()
    assert status["deliveries"][0]["state"] == "expired"
