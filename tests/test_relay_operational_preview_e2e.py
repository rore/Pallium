from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from api.routes import create_router
from app.dashboard import mount_dashboard
from core.codex_wake import CodexWakeRegistry
from core.relay import RelayService
from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import (
    RelayCodexWakeReservationRecord, RelayDeliveryRecord, RelayDeliveryTraceRecord,
    RelayMessageRecord, RelaySessionRecord,
)


URL = "/dashboard/api/relay/operational-preview"
NOW = datetime(2026, 10, 20, 18, tzinfo=timezone.utc)
DURABLE = datetime.max.replace(tzinfo=timezone.utc)
SECRET = "private-body-token-and-title-東京"


@pytest.fixture
def preview(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    from storage import sqlite_relay
    original_now = sqlite_relay._now
    monkeypatch.setattr(sqlite_relay, "_now", lambda value=None: original_now(value) if value is not None else NOW)
    storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'main.db'}", f"sqlite:///{tmp_path / 'relay.db'}")
    relay = RelayService(storage)
    service = SimpleNamespace(_storage=storage)
    app = FastAPI()
    app.state.pallium_service = service
    app.include_router(create_router(service, relay_service=relay))
    mount_dashboard(app, relay_service=relay, codex_wake_registry=CodexWakeRegistry())
    monkeypatch.setattr("app.dashboard.datetime", Clock)
    try:
        with TestClient(app) as client:
            yield client, storage
    finally:
        storage.close()


def _seed(storage, *specs):
    """Stage persisted boundary evidence; the caller always reads through HTTP."""
    messages = set()
    with storage._relay_session_factory() as session:
        for spec in specs:
            ident = spec["id"]
            message_id = spec.get("message_id", "message-" + ident)
            endpoint_id = "endpoint-" + ident
            if spec.get("message_available", True) and message_id not in messages:
                session.add(RelayMessageRecord(
                    id=message_id, sender_runtime="codex", sender_session_ref=SECRET,
                    sender_endpoint_id="sender", recipient_selector=endpoint_id,
                    container_ref=spec.get("container_ref", "workspace-東京"), payload=SECRET,
                    created_at=spec.get("created_at", NOW - timedelta(days=8)),
                    expires_at=spec.get("expires_at", DURABLE), in_reply_to=spec.get("in_reply_to"),
                ))
                messages.add(message_id)
            if spec.get("recipient_state", "active") is not None:
                session.add(RelaySessionRecord(
                    id=endpoint_id, runtime=spec.get("runtime", "codex"), session_ref=SECRET + ident,
                    container_ref="destination-" + ident, title=SECRET,
                    state=spec.get("recipient_state", "active"), first_seen_at=NOW - timedelta(days=9),
                    last_seen_at=spec.get("last_seen_at", NOW - timedelta(days=8)),
                ))
            session.add(RelayDeliveryRecord(
                id=ident, message_id=message_id, recipient_runtime=spec.get("runtime", "codex"),
                recipient_session_ref=SECRET + ident, recipient_endpoint_id=endpoint_id,
                recipient_container_ref="destination-" + ident, state=spec.get("state", "pending"),
                claim_token=SECRET, claimed_at=spec.get("claimed_at"), lease_expires_at=spec.get("lease_expires_at"),
                delivered_at=spec.get("delivered_at"), trace_version=spec.get("trace_version", 1),
                trace_pruned=spec.get("trace_pruned", 0), trace_truncated=spec.get("trace_truncated", 0),
            ))
        session.commit()


def _trace(storage, delivery_id, stage="completed", outcome="failed", **extra):
    with storage._relay_session_factory() as session:
        row = RelayDeliveryTraceRecord(
            id=uuid4().hex, attempt_id=uuid4().hex, delivery_id=delivery_id,
            message_id=extra.get("message_id", "message-" + delivery_id), stage=stage,
            outcome=outcome if stage == "completed" else None, reason=SECRET, evidence_json='["' + SECRET + '"]',
            recorded_at=extra.get("recorded_at", NOW - timedelta(days=2)),
        )
        session.add(row)
        session.flush()
        sequence = row.recorded_sequence
        session.commit()
        return sequence


def _next(page, **filters):
    return {**filters, "until": page["until"], "trace_through_sequence": page["trace_through_sequence"],
            "before_created_at": page["next_before_created_at"], "before_id": page["next_before_id"]}


@pytest.mark.parametrize("count", [0, 1, 200, 201])
def test_output_bound_equal_time_multidelivery_and_creation_cutoff(preview, count):
    client, storage = preview
    _seed(storage, *({"id": f"delivery-{n:03}", "message_id": "shared"} for n in range(count)))
    first = client.get(URL, params={"limit": 200})
    assert first.status_code == 200, first.text
    page = first.json()
    assert len(page["items"]) == min(count, 200)
    assert page["has_more"] is (count > 200)
    ids = [row["delivery_id"] for row in page["items"]]
    assert ids == sorted(ids, reverse=True)
    if page["has_more"]:
        _seed(storage, {"id": "later", "created_at": NOW + timedelta(seconds=1)})
        following = client.get(URL, params=_next(page, limit=200)).json()
        assert [row["delivery_id"] for row in following["items"]] == ["delivery-000"]
        assert following["has_more"] is False
        assert following["until"] == page["until"]
        assert following["consistency"] == "creation_cutoff_trace_highwater_live_state"
        assert "later" not in ids + [row["delivery_id"] for row in following["items"]]
    else:
        assert page["next_before_id"] is page["next_before_created_at"] is None


@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": 201}, {"limit": "bad"}, {"runtime": "invalid"}, {"container_ref": ""},
    {"trace_through_sequence": -1}, {"trace_through_sequence": 2**63}, {"trace_through_sequence": "bad"},
    {"trace_through_sequence": 1}, {"until": "bad"}, {"until": (NOW + timedelta(seconds=1)).isoformat()},
    {"before_id": "id"}, {"before_created_at": NOW.isoformat()},
    {"before_id": "", "before_created_at": NOW.isoformat()},
    {"before_id": "x" * 129, "before_created_at": NOW.isoformat()},
    {"before_id": "id", "before_created_at": NOW.isoformat(), "until": NOW.isoformat()},
    {"before_id": "id", "before_created_at": NOW.isoformat(), "trace_through_sequence": 0},
    {"before_id": "id", "before_created_at": NOW.isoformat(), "until": (NOW - timedelta(seconds=1)).isoformat(), "trace_through_sequence": 0},
])
def test_invalid_preview_inputs_are_rejected_without_state_change(preview, params):
    client, _ = preview
    assert client.get(URL, params=params).status_code == 422
    assert client.get(URL).json()["items"] == []


@pytest.mark.parametrize("state,expiry,lease,effective,kind,lease_state", [
    ("pending", DURABLE, None, "pending", "durable", "not_claimed"),
    ("pending", NOW + timedelta(microseconds=1), None, "pending", "finite_live", "not_claimed"),
    ("pending", NOW, None, "expired", "finite_expired", "not_claimed"),
    ("claimed", NOW - timedelta(microseconds=1), NOW + timedelta(seconds=1), "expired", "finite_expired", "active"),
    ("claimed", DURABLE, NOW + timedelta(microseconds=1), "claimed", "durable", "active"),
    ("claimed", DURABLE, NOW, "claimed", "durable", "expired"),
    ("claimed", DURABLE, NOW - timedelta(microseconds=1), "claimed", "durable", "expired"),
    ("claimed", DURABLE, None, "claimed", "durable", "unknown"),
    ("delivered", NOW - timedelta(days=1), None, "delivered", "finite_expired", "not_claimed"),
    ("expired", DURABLE, None, "expired", "durable", "not_claimed"),
    ("suppressed", DURABLE, None, "suppressed", "durable", "not_claimed"),
    (SECRET, DURABLE, None, "unknown", "durable", "unknown"),
])
def test_stored_state_expiry_and_lease_are_independent_readonly_facts(preview, state, expiry, lease, effective, kind, lease_state):
    client, storage = preview
    _seed(storage, {"id": "state", "state": state, "expires_at": expiry, "lease_expires_at": lease})
    with storage._relay_session_factory() as session:
        before = session.execute(select(RelayDeliveryRecord.state, RelayDeliveryRecord.claim_token, RelayDeliveryRecord.lease_expires_at)).all()
    row = client.get(URL, params={"until": (NOW - timedelta(days=1)).isoformat()}).json()["items"][0]
    assert row["stored_state"] == ("unknown" if state == SECRET else state)
    assert (row["effective_state"], row["expiry_kind"], row["lease_state"]) == (effective, kind, lease_state)
    assert (row["expires_at"] is None) is (expiry == DURABLE)
    with storage._relay_session_factory() as session:
        assert session.execute(select(RelayDeliveryRecord.state, RelayDeliveryRecord.claim_token, RelayDeliveryRecord.lease_expires_at)).all() == before


@pytest.mark.parametrize("state,seen,expected_state,recency", [
    ("active", NOW, "active", "recent"),
    ("active", NOW - timedelta(hours=24), "active", "recent"),
    ("active", NOW - timedelta(hours=24, microseconds=1), "active", "dormant"),
    ("unreachable", NOW - timedelta(days=8), "unreachable", "dormant"),
    ("closed", NOW, "closed", "recent"),
    (None, NOW, "unknown", "unknown"),
    (SECRET, NOW + timedelta(seconds=1), "unknown", "unknown"),
])
def test_recipient_state_and_checkin_are_not_liveness(preview, state, seen, expected_state, recency):
    client, storage = preview
    _seed(storage, {"id": "recipient", "recipient_state": state, "last_seen_at": seen})
    row = client.get(URL).json()["items"][0]
    assert row["recipient"]["stored_state"] == expected_state
    assert row["recipient"]["recency"] == recency
    assert row["recipient"]["liveness"] == "not_verified"
    assert row["effective_state"] == "pending"


@pytest.mark.parametrize("outcome", [None, "prepared", "reserved", "accepted", "uncertain", SECRET])
def test_persisted_reservation_is_metadata_only_not_runtime_probe(preview, outcome):
    client, storage = preview
    _seed(storage, {"id": "reserved"})
    if outcome is not None:
        with storage._relay_session_factory() as session:
            session.add(RelayCodexWakeReservationRecord(
                recipient_endpoint_id="endpoint-reserved", delivery_id="reserved", session_ref=SECRET,
                container_ref=SECRET, generation=7, outcome=outcome,
            ))
            session.commit()
    body = client.get(URL).json()
    expected = "absent" if outcome is None else ("unknown" if outcome == SECRET else outcome)
    assert body["items"][0]["reservation"] == {"outcome": expected, "evidence": "persisted_codex_only"}
    assert SECRET not in str(body)


def test_privacy_is_enforced_in_sql_and_preview_uses_one_read_snapshot(preview):
    client, storage = preview
    _seed(storage, {"id": "secret"})
    _trace(storage, "secret")
    statements, read_transactions = [], []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        if statement.lstrip().upper().startswith("SELECT"):
            read_transactions.append(connection.connection.driver_connection.in_transaction)

    event.listen(storage._relay_engine, "before_cursor_execute", capture)
    try:
        first = client.get(URL)
        second = client.get(URL)
    finally:
        event.remove(storage._relay_engine, "before_cursor_execute", capture)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.headers["cache-control"] == "no-store"
    assert SECRET not in first.text
    sql = "\n".join(statements).lower()
    for column in (".payload", ".claim_token", ".title", ".session_ref", ".reason", ".evidence_json", ".native_location"):
        assert column not in sql
    assert all(statement.lstrip().upper().startswith(("BEGIN", "SELECT")) for statement in statements)
    assert read_transactions and all(read_transactions)
    assert len(read_transactions) == 6  # high-water, bounded page, bounded trace projection per request


def test_trace_boundary_preserves_last_result_and_unknown_uncompleted_attempt(preview):
    client, storage = preview
    _seed(storage, {"id": "trace"})
    failed = _trace(storage, "trace")
    baseline = client.get(URL).json()
    prepared = _trace(storage, "trace", "prepared")
    associated = _trace(storage, "trace", "associated")
    fresh = client.get(URL).json()
    fact = fresh["items"][0]["trace"]
    assert fact["latest"]["sequence"] == associated > prepared > failed
    assert fact["latest_completed"]["sequence"] == failed
    assert fact["latest_completed"]["outcome"] == "failed"
    assert fact["attempt_status"] == "unknown"
    old = client.get(URL, params={"until": baseline["until"], "trace_through_sequence": baseline["trace_through_sequence"]}).json()
    assert old["items"][0]["trace"]["latest"]["sequence"] == failed
    accepted = _trace(storage, "trace", outcome="accepted")
    assert client.get(URL).json()["items"][0]["trace"]["latest_completed"]["sequence"] == accepted


@pytest.mark.parametrize("spec,trace_stage,availability", [
    ({"trace_version": None}, None, "not_recorded"),
    ({}, None, "missing"),
    ({}, "prepared", "available"),
    ({}, "associated", "available"),
    ({"trace_pruned": 1}, None, "partial"),
    ({"trace_truncated": 1}, "completed", "partial"),
    ({"trace_version": 99}, "completed", "unknown"),
])
def test_missing_pruned_and_stale_trace_is_never_proof_of_activity(preview, spec, trace_stage, availability):
    client, storage = preview
    _seed(storage, {"id": "incomplete", **spec})
    if trace_stage:
        _trace(storage, "incomplete", trace_stage)
    fact = client.get(URL).json()["items"][0]["trace"]
    assert fact["availability"] == availability
    assert fact["attempt_status"] == "unknown"
    if trace_stage != "completed":
        assert fact["latest_completed"] is None


def test_dangling_graph_and_mismatched_trace_stay_unknown(preview):
    client, storage = preview
    _seed(storage, {"id": "missing", "message_available": False, "recipient_state": None},
          {"id": "reply", "in_reply_to": "message-missing"})
    _trace(storage, "missing", message_id="unrelated")
    items = {row["delivery_id"]: row for row in client.get(URL).json()["items"]}
    assert items["missing"]["message_available"] is False
    assert items["missing"]["durable"] is None
    assert items["missing"]["expiry_kind"] == items["missing"]["effective_state"] == "unknown"
    assert items["missing"]["reply"]["linked_reply_count"] == 1
    assert items["missing"]["trace"]["availability"] == "unknown"
    assert items["missing"]["trace"]["latest_completed"] is None
    assert items["reply"]["reply"]["parent_exists"] is False


def test_global_access_exact_filters_and_unsupported_backend(preview):
    client, storage = preview
    _seed(storage, {"id": "one", "container_ref": "workspace-東京", "runtime": "codex"},
          {"id": "two", "container_ref": "workspace-עברית", "runtime": "claude-code"})
    assert len(client.get(URL).json()["items"]) == 2
    row = client.get(URL, params={"container_ref": "workspace-עברית", "runtime": "claude-code"}).json()["items"][0]
    assert row["delivery_id"] == "two"
    assert row["reservation"]["evidence"] == "not_recorded_for_runtime"
    assert client.get(URL, params={"container_ref": "unknown"}).json()["items"] == []
    assert client.get(URL, params={"runtime": "opencode"}).json()["items"] == []
    client.app.state.pallium_service._storage = object()
    assert client.get(URL).status_code == 501


@pytest.mark.parametrize("runtime", ["codex", "claude-code", "opencode", "hermes"])
def test_every_supported_runtime_is_filterable_and_preserved(preview, runtime):
    client, storage = preview
    _seed(storage, {"id": "runtime", "runtime": runtime})
    response = client.get(URL, params={"runtime": runtime})
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["recipient_runtime"] == runtime


def test_caller_saved_baseline_lifecycle_new_failure_and_terminal_resolution(preview):
    client, storage = preview
    scope = {"container_ref": "journey-東京"}
    for runtime, name in (("codex", "sender"), ("claude-code", "receiver")):
        registered = client.post("/relay/turn", json={"runtime": runtime, "session_ref": name, **scope})
        assert registered.status_code == 200, registered.text
    sent = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": "claude-code:receiver", "payload": "你好 → שלום", "expires_in_seconds": None, **scope})
    assert sent.status_code == 200, sent.text
    baseline = client.get(URL).json()
    first_id = baseline["items"][0]["delivery_id"]
    assert client.get(URL).json()["items"] == baseline["items"]
    failure = _trace(storage, first_id, message_id=sent.json()["message_id"])
    changed = client.get(URL).json()
    assert changed["items"][0]["trace"]["latest_completed"]["sequence"] == failure > baseline["trace_through_sequence"]
    current_runtime, current_name = "claude-code", "receiver"
    chain = []
    for n in range(3):
        turn = client.post("/relay/turn", json={"runtime": current_runtime, "session_ref": current_name, **scope})
        assert turn.status_code == 200, turn.text
        delivery = turn.json()["deliveries"][0]
        ack = client.post("/relay/deliveries/ack", json={"delivery_id": delivery["delivery_id"], "claim_token": delivery["claim_token"], **scope})
        assert ack.status_code == 200, ack.text
        reply = client.post("/relay/replies", json={"delivery_id": delivery["delivery_id"], "payload": f"返信 {n}", "expires_in_seconds": None, **scope})
        assert reply.status_code == 200, reply.text
        chain.append(reply.json()["message_id"])
        current_runtime, current_name = ("codex", "sender") if current_runtime == "claude-code" else ("claude-code", "receiver")
    after = client.get(URL).json()
    rows = {row["delivery_id"]: row for row in after["items"]}
    assert rows[first_id]["stored_state"] == "delivered"
    assert rows[first_id]["reply"]["linked_reply_count"] == 1
    assert len(set(rows) - {first_id}) == 3
    assert {row["message_id"] for row in rows.values()} >= set(chain)
    assert all(row["reply"]["parent_exists"] for row in rows.values() if row["reply"]["in_reply_to"])
    assert client.post("/relay/sessions/close", json={"runtime": "codex", "session_ref": "sender", **scope}).status_code == 200
    assert any(row["recipient"]["stored_state"] == "closed" for row in client.get(URL).json()["items"])
