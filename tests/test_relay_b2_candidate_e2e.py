from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.routes import create_router
from core.relay import RelayService
from storage.relay_migration import migrate_relay_batch_claims

SCOPE = {"container_ref": "git:example.test/team/relay", "actor_ref": "local-user"}


def _turn(client: TestClient, runtime: str, session_ref: str, **extra):
    response = client.post("/relay/turn", json={"runtime": runtime, "session_ref": session_ref, **SCOPE, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def _send(client: TestClient, sender: str, recipient: str, payload: str, message_id: str):
    response = client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": sender,
        "recipient": recipient, "payload": payload, "message_id": message_id, **SCOPE,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _publication(client: TestClient, delivery: dict):
    return client.post("/relay/deliveries/publication", json={
        "delivery_id": delivery["delivery_id"], "claim_token": delivery["claim_token"],
        "envelope_digest": delivery["envelope_digest"], **SCOPE,
    })


@pytest.fixture()
def batch_client(client: TestClient) -> TestClient:
    storage = client.app.state.pallium_service._storage
    with storage._engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        migrate_relay_batch_claims(connection)
    app = FastAPI()
    app.include_router(create_router(
        client.app.state.pallium_service,
        relay_service=RelayService(storage, batch_candidate_enabled=True),
    ))
    app.state.batch_storage = storage
    return TestClient(app)


def test_candidate_is_explicitly_migration_gated(client: TestClient) -> None:
    storage = client.app.state.pallium_service._storage
    app = FastAPI()
    app.include_router(create_router(
        client.app.state.pallium_service,
        relay_service=RelayService(storage, batch_candidate_enabled=True),
    ))
    response = TestClient(app).post("/relay/turn", json={"runtime": "codex", "session_ref": "target", **SCOPE})
    assert response.status_code == 409
    assert "explicit B2 migration" in response.json()["detail"]


def test_candidate_claims_complete_fifo_envelopes_with_scope_and_budget(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    for index in range(9):
        _send(batch_client, "sender", "codex:target", f"message {index}", f"batch-{index}")

    turn = _turn(batch_client, "codex", "target")
    assert [delivery["message_id"] for delivery in turn["deliveries"]] == [f"batch-{i}" for i in range(8)]
    assert turn["has_more"] is True
    assert turn["remaining_count"] == 1
    first = turn["deliveries"][0]
    assert first["protocol_version"] == "batch_v2_candidate"
    assert first["claim_generation"] == 1
    assert first["envelope_chars"] == len(first["envelope"])
    assert first["envelope_bytes"] == len(first["envelope"].encode("utf-8"))
    assert '"thread_ref":"target"' in first["envelope"]
    assert first["claim_token"] not in first["envelope"]


def test_candidate_blocks_oldest_that_cannot_fit_without_skipping(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    first = _send(batch_client, "sender", "codex:target", "oldest", "oldest")
    _send(batch_client, "sender", "codex:target", "newer", "newer")

    turn = _turn(batch_client, "codex", "target", max_chars=10)
    assert turn["deliveries"] == []
    assert turn["blocked_reasons"] == ["envelope_exceeds_turn_budget"]
    assert turn["remaining_count"] == 1
    status = batch_client.get(f"/relay/messages/{first['message_id']}", params=SCOPE).json()
    assert status["deliveries"][0]["state"] == "blocked"
    assert status["deliveries"][0]["blocked_reason"] == "envelope_exceeds_turn_budget"


def test_candidate_fences_stale_publication_and_keeps_unconfirmed_output_uncertain(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    sent = _send(batch_client, "sender", "codex:target", "handoff", "handoff")
    first = _turn(batch_client, "codex", "target")["deliveries"][0]
    storage = batch_client.app.state.batch_storage

    with storage._engine.begin() as connection:
        connection.execute(text("UPDATE relay_deliveries SET lease_expires_at=:past WHERE id=:id"), {
            "past": datetime.now(timezone.utc) - timedelta(seconds=1), "id": first["delivery_id"],
        })
    replacement = _turn(batch_client, "codex", "target")["deliveries"][0]
    assert replacement["claim_generation"] == 2
    assert _publication(batch_client, first).status_code == 409
    assert _publication(batch_client, replacement).status_code == 200

    with storage._engine.begin() as connection:
        connection.execute(text("UPDATE relay_deliveries SET lease_expires_at=:past WHERE id=:id"), {
            "past": datetime.now(timezone.utc) - timedelta(seconds=1), "id": replacement["delivery_id"],
        })
    assert _turn(batch_client, "codex", "target")["deliveries"] == []
    status = batch_client.get(f"/relay/messages/{sent['message_id']}", params=SCOPE).json()
    delivery = status["deliveries"][0]
    assert delivery["state"] == "uncertain"
    assert delivery["uncertain_reason"] == "publication_unconfirmed"

def test_legacy_router_stays_usable_after_explicit_b2_migration(client: TestClient, batch_client: TestClient) -> None:
    _turn(client, "claude-code", "legacy-sender")
    _turn(client, "codex", "legacy-target")
    _send(client, "legacy-sender", "codex:legacy-target", "legacy", "legacy")
    turn = _turn(client, "codex", "legacy-target")
    assert turn["deliveries"][0]["protocol_version"] == "text_v1"
    assert turn["deliveries"][0]["payload"] == "legacy"

def test_candidate_does_not_skip_an_earlier_active_claim(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    _send(batch_client, "sender", "codex:target", "first", "first")
    first = _turn(batch_client, "codex", "target")["deliveries"][0]
    _send(batch_client, "sender", "codex:target", "second", "second")

    turn = _turn(batch_client, "codex", "target")
    assert turn["deliveries"] == []
    assert turn["has_more"] is True
    assert turn["remaining_count"] == 2
    assert batch_client.get(f"/relay/messages/{first['message_id']}", params=SCOPE).json()["deliveries"][0]["state"] == "claimed"