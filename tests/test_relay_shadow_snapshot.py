from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from storage.sqlite_relay import SQLiteRelayMixin


SCOPE = {"container_ref": "git:example.test/shadow"}
RUNTIME = "codex"
SESSION = "shadow-session-✓-日本語"


def _register(client):
    response = client.post("/relay/turn", json={"runtime": RUNTIME, "session_ref": SESSION, **SCOPE})
    assert response.status_code == 200, response.text
    return response.json()["session"]


def _send(client, *, expires_in_seconds=None):
    sender = "shadow-sender"
    client.post("/relay/turn", json={"runtime": "claude-code", "session_ref": sender, **SCOPE})
    body = {
        "sender_runtime": "claude-code",
        "sender_session_ref": sender,
        "recipient": f"{RUNTIME}:{SESSION}",
        "payload": "must never appear in snapshot",
        **SCOPE,
    }
    if expires_in_seconds is not None:
        body["expires_in_seconds"] = expires_in_seconds
    response = client.post("/relay/messages", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _snapshot(storage, session, **overrides):
    values = {
        "endpoint_id": session["endpoint_id"],
        "runtime": RUNTIME,
        "session_ref": SESSION,
        "container_ref": SCOPE["container_ref"],
        "scope_generation": session["scope_generation"],
        "deadline": time.monotonic() + 2,
    }
    values.update(overrides)
    method = getattr(storage, "relay_shadow_snapshot", None)
    if method is None:
        return SQLiteRelayMixin.relay_shadow_snapshot(storage, **values)
    return method(**values)


def _bare_snapshot_store(path, deliveries):
    endpoint_id = "relay-session-" + "1" * 32
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE relay_sessions (
                id TEXT, runtime TEXT, session_ref TEXT, container_ref TEXT, state TEXT
            );
            CREATE TABLE relay_endpoint_generations (endpoint_id TEXT, generation INTEGER);
            CREATE TABLE relay_messages (id TEXT, expires_at TEXT);
            CREATE TABLE relay_deliveries (
                id TEXT, message_id TEXT, state TEXT, claim_token TEXT,
                lease_expires_at TEXT, codex_wake_generation INTEGER,
                recipient_endpoint_id TEXT, recipient_runtime TEXT,
                recipient_session_ref TEXT, recipient_container_ref TEXT
            );
            CREATE TABLE relay_delivery_trace (
                attempt_id TEXT, delivery_id TEXT, stage TEXT, outcome TEXT,
                evidence_json TEXT, native_retry_safe INTEGER, scope_generation INTEGER,
                recorded_sequence INTEGER
            );
        """)
        connection.execute(
            "INSERT INTO relay_sessions VALUES (?, ?, ?, ?, 'active')",
            (endpoint_id, RUNTIME, SESSION, SCOPE["container_ref"]),
        )
        connection.execute("INSERT INTO relay_endpoint_generations VALUES (?, 0)", (endpoint_id,))
        for delivery_id, message_id, state, expires_at in deliveries:
            connection.execute("INSERT INTO relay_messages VALUES (?, ?)", (message_id, expires_at))
            connection.execute(
                "INSERT INTO relay_deliveries VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?)",
                (delivery_id, message_id, state, endpoint_id, RUNTIME, SESSION, SCOPE["container_ref"]),
            )
    store = SimpleNamespace(_relay_engine=SimpleNamespace(url=SimpleNamespace(database=str(path))))
    session = {"endpoint_id": endpoint_id, "scope_generation": 0}
    return store, session


def test_http_created_pending_delivery_is_held_without_native_evidence(client):
    session = _register(client)
    _send(client)
    storage = client.app.state.pallium_service._storage
    db_path = Path(storage._relay_engine.url.database)
    before = hashlib.sha256(db_path.read_bytes()).digest()
    with storage._relay_engine.connect() as db:
        normal_timeout = db.exec_driver_sql("PRAGMA busy_timeout").scalar_one()

    snapshot = _snapshot(storage, session)

    assert snapshot == {"category": "held", "reason": "native_evidence_missing", "endpoint_valid": True}
    assert "payload" not in snapshot and "delivery_id" not in snapshot
    assert hashlib.sha256(db_path.read_bytes()).digest() == before
    with storage._relay_engine.connect() as db:
        assert db.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == normal_timeout


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"scope_generation": 1}, "scope_generation_mismatch"),
        ({"container_ref": "git:example.test/other"}, "endpoint_missing_or_scope_mismatch"),
    ],
)
def test_scope_or_generation_mismatch_is_held(client, overrides, reason):
    session = _register(client)
    _send(client)
    storage = client.app.state.pallium_service._storage
    assert _snapshot(storage, session, **overrides) == {
        "category": "held", "reason": reason, "endpoint_valid": False
    }


def test_missing_endpoint_is_held(client):
    session = _register(client)
    storage = client.app.state.pallium_service._storage
    assert _snapshot(storage, session, endpoint_id="relay-session-" + "f" * 32) == {
        "category": "held",
        "reason": "endpoint_missing_or_scope_mismatch",
        "endpoint_valid": False,
    }


def test_active_endpoint_without_deliveries_is_valid_for_enrollment(client):
    session = _register(client)
    storage = client.app.state.pallium_service._storage
    assert _snapshot(storage, session) == {
        "category": "inactive",
        "reason": "no_live_delivery",
        "endpoint_valid": True,
    }


def test_claimed_delivery_is_held(client):
    session = _register(client)
    _send(client)
    claimed = client.post("/relay/turn", json={"runtime": RUNTIME, "session_ref": SESSION, **SCOPE})
    assert claimed.status_code == 200 and claimed.json()["deliveries"]
    storage = client.app.state.pallium_service._storage
    assert _snapshot(storage, session) == {
        "category": "held", "reason": "delivery_not_pending", "endpoint_valid": True
    }
    delivery = claimed.json()["deliveries"][0]
    ack = client.post("/relay/deliveries/mcp-ack", json={
        "delivery_id": delivery["delivery_id"], "receipt": delivery["receipt"], **SCOPE
    })
    assert ack.status_code == 200, ack.text
    assert _snapshot(storage, session) == {
        "category": "inactive", "reason": "no_live_delivery", "endpoint_valid": True
    }


def test_expired_delivery_is_not_eligible(client):
    session = _register(client)
    _send(client)
    storage = client.app.state.pallium_service._storage
    with sqlite3.connect(storage._relay_engine.url.database) as connection:
        connection.execute("UPDATE relay_messages SET expires_at='2000-01-01 00:00:00'")
    assert _snapshot(storage, session) == {"category": "inactive", "reason": "no_live_delivery", "endpoint_valid": True}


def test_null_expiry_is_a_live_unbounded_message(tmp_path):
    store, session = _bare_snapshot_store(tmp_path / "null-expiry.db", [
        ("relay-delivery-pending", "message", "pending", None),
    ])
    assert _snapshot(store, session) == {
        "category": "held", "reason": "native_evidence_missing", "endpoint_valid": True
    }


def test_terminal_history_does_not_mask_current_pending_message(tmp_path):
    future = "9999-12-31 23:59:59"
    store, session = _bare_snapshot_store(tmp_path / "terminal-history.db", [
        ("relay-delivery-a", "message-a", "delivered", future),
        ("relay-delivery-b", "message-b", "expired", future),
        ("relay-delivery-c", "message-c", "delivered", future),
        ("relay-delivery-z", "message-z", "pending", future),
    ])
    assert _snapshot(store, session) == {
        "category": "held", "reason": "native_evidence_missing", "endpoint_valid": True
    }


@pytest.mark.parametrize(
    "values",
    [
        {"endpoint_id": ""},
        {"runtime": "codex\n"},
        {"session_ref": "x" * 513},
        {"scope_generation": True},
        {"deadline": 0},
    ],
)
def test_invalid_snapshot_input_is_rejected(client, values):
    session = _register(client)
    storage = client.app.state.pallium_service._storage
    with pytest.raises(ValueError):
        _snapshot(storage, session, **values)


def test_complete_retry_safe_native_trace_is_eligible(client):
    session = _register(client)
    sent = _send(client)
    storage = client.app.state.pallium_service._storage
    attempt = "relay-activation-" + "a" * 32
    common = {"attempt_id": attempt, "delivery_id": sent["deliveries"][0]["delivery_id"], "scope_generation": 0}
    storage.relay_trace_record(**common, stage="prepared")
    storage.relay_trace_record(**common, stage="associated")
    storage.relay_trace_record(
        **common,
        stage="completed",
        outcome="deferred",
        reason="transport_unavailable",
        evidence=["submission_attempted"],
        native_retry_safe=True,
    )

    assert _snapshot(storage, session) == {
        "category": "eligible",
        "reason": "complete_retry_safe_native_evidence",
        "endpoint_valid": True,
    }


def test_unanchored_accepted_trace_is_hypothetically_eligible(client):
    session = _register(client)
    sent = _send(client)
    storage = client.app.state.pallium_service._storage
    common = {
        "attempt_id": "relay-activation-" + "b" * 32,
        "delivery_id": sent["deliveries"][0]["delivery_id"],
        "scope_generation": 0,
    }
    storage.relay_trace_record(**common, stage="prepared")
    storage.relay_trace_record(**common, stage="associated")
    storage.relay_trace_record(
        **common,
        stage="completed",
        outcome="accepted",
        reason="transport_accepted",
        evidence=["submission_attempted", "transport_accepted"],
        native_retry_safe=False,
    )

    assert _snapshot(storage, session) == {
        "category": "eligible",
        "reason": "accepted_native_evidence",
        "endpoint_valid": True,
    }


@pytest.mark.parametrize(
    ("outcome", "evidence"),
    [
        ("accepted", ["submission_attempted", "transport_accepted"]),
        ("uncertain", ["submission_attempted"]),
    ],
)
def test_wake_generation_anchor_without_persisted_correlation_stays_held(client, outcome, evidence):
    session = _register(client)
    sent = _send(client)
    storage = client.app.state.pallium_service._storage
    delivery_id = sent["deliveries"][0]["delivery_id"]
    attempt_id = "relay-activation-" + ("c" if outcome == "accepted" else "d") * 32
    common = {"attempt_id": attempt_id, "delivery_id": delivery_id, "scope_generation": 0}
    storage.relay_trace_record(**common, stage="prepared")
    storage.relay_trace_record(**common, stage="associated")
    storage.relay_trace_record(
        **common,
        stage="completed",
        outcome=outcome,
        reason="transport_accepted" if outcome == "accepted" else "transport_uncertain",
        evidence=evidence,
        native_retry_safe=False,
    )
    with sqlite3.connect(storage._relay_engine.url.database) as connection:
        connection.execute(
            "UPDATE relay_deliveries SET codex_wake_generation=41 WHERE id=?",
            (delivery_id,),
        )

    assert _snapshot(storage, session) == {
        "category": "held", "reason": "native_anchor_uncorrelated", "endpoint_valid": True
    }


def test_read_only_connection_fails_closed_when_database_is_exclusively_locked(client, tmp_path, monkeypatch):
    session = _register(client)
    _send(client)
    storage = client.app.state.pallium_service._storage
    db_path = tmp_path / "locked.db"
    setup = sqlite3.connect(db_path)
    setup.execute("CREATE TABLE relay_sessions (id TEXT, runtime TEXT, session_ref TEXT, container_ref TEXT, state TEXT)")
    setup.commit()
    setup.close()
    monkeypatch.setattr(storage, "_relay_engine", SimpleNamespace(url=SimpleNamespace(database=str(db_path))))
    lock = sqlite3.connect(db_path, timeout=0, isolation_level=None)
    try:
        lock.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        snapshot = _snapshot(storage, session, deadline=time.monotonic() + 1)
        assert time.monotonic() - started < 1
        assert snapshot == {"category": "unavailable", "reason": "read_failed_or_deadline", "endpoint_valid": False}
    finally:
        lock.rollback()
        lock.close()
