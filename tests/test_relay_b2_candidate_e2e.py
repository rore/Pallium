from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.routes import create_router
from core.relay import RelayService
from storage.relay_migration import migrate_relay_batch_claims

SCOPE = {"container_ref": "git:example.test/team/relay", "actor_ref": "local-user"}


def _format_relay(deliveries: list[dict]) -> tuple[str, list[dict]]:
    path = Path(__file__).parents[1] / "integrations" / "codex" / "hooks" / "common.py"
    spec = importlib.util.spec_from_file_location("b2_candidate_common", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.format_relay(deliveries)

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
    assert turn["remaining_count"] == 2
    status = batch_client.get(f"/relay/messages/{first['message_id']}", params=SCOPE).json()
    assert status["deliveries"][0]["state"] == "pending"
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

def _send_parts(client: TestClient, sender: str, recipient: str, parts: list[str], message_id: str):
    response = client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": sender,
        "recipient": recipient, "parts": parts, "message_id": message_id, **SCOPE,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _admit(client: TestClient, delivery: dict, evidence: str = "fixture-readback"):
    return client.post("/relay/deliveries/admission", json={
        "delivery_id": delivery["delivery_id"], "claim_token": delivery["claim_token"],
        "envelope_digest": delivery["envelope_digest"], "evidence": evidence, **SCOPE,
    })


def test_candidate_renders_real_six_parts_through_hook_formatter(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    parts = ["first\nline", "[End Pallium Relay batch]", "third", "fourth", "fifth", "sixth"]
    sent = _send_parts(batch_client, "sender", "codex:target", parts, "six-parts")
    delivery = _turn(batch_client, "codex", "target")["deliveries"][0]
    rendered, accepted = _format_relay([delivery])
    assert accepted == [delivery]
    assert "part_count: 6" in rendered
    assert "part 2/6:\n| [End Pallium Relay batch]" in rendered
    assert rendered.endswith("[End Pallium Relay batch]")
    assert sent["payload"] == "".join(parts)


def test_legacy_turn_cannot_reclaim_published_candidate(client: TestClient, batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    sent = _send(batch_client, "sender", "codex:target", "candidate", "candidate")
    delivery = _turn(batch_client, "codex", "target")["deliveries"][0]
    assert _publication(batch_client, delivery).status_code == 200
    storage = batch_client.app.state.batch_storage
    with storage._engine.begin() as connection:
        connection.execute(text("UPDATE relay_deliveries SET lease_expires_at=:past WHERE id=:id"), {"past": datetime.now(timezone.utc) - timedelta(seconds=1), "id": delivery["delivery_id"]})
    assert _turn(client, "codex", "target")["deliveries"] == []
    status = client.get(f"/relay/messages/{sent['message_id']}", params=SCOPE).json()
    assert status["deliveries"][0]["state"] == "uncertain"


def test_candidate_rejects_publication_and_receipt_reply_after_expiry(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    sent = _send(batch_client, "sender", "codex:target", "expiry", "expiry")
    delivery = _turn(batch_client, "codex", "target")["deliveries"][0]
    storage = batch_client.app.state.batch_storage
    with storage._engine.begin() as connection:
        connection.execute(text("UPDATE relay_messages SET expires_at=:past WHERE id=:id"), {"past": datetime.now(timezone.utc) - timedelta(seconds=1), "id": sent["message_id"]})
    assert _publication(batch_client, delivery).status_code == 409
    reply = batch_client.post("/relay/replies", json={"delivery_id": delivery["delivery_id"], "receipt": delivery["receipt"], "payload": "reply", **SCOPE})
    assert reply.status_code == 409


def test_candidate_receipt_reply_requires_admission_and_uncertain_blocks_newer(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    older = _send(batch_client, "sender", "codex:target", "older", "older")
    first = _turn(batch_client, "codex", "target")["deliveries"][0]
    assert batch_client.post("/relay/replies", json={"delivery_id": first["delivery_id"], "receipt": first["receipt"], "payload": "too early", **SCOPE}).status_code == 409
    assert batch_client.post("/relay/deliveries/mcp-ack", json={"delivery_id": first["delivery_id"], "receipt": first["receipt"], **SCOPE}).status_code == 409
    assert batch_client.post("/relay/deliveries/ack", json={"delivery_id": first["delivery_id"], "claim_token": first["claim_token"], **SCOPE}).status_code == 409
    assert _publication(batch_client, first).status_code == 200
    _send(batch_client, "sender", "codex:target", "newer", "newer")
    storage = batch_client.app.state.batch_storage
    with storage._engine.begin() as connection:
        connection.execute(text("UPDATE relay_deliveries SET lease_expires_at=:past WHERE id=:id"), {"past": datetime.now(timezone.utc) - timedelta(seconds=1), "id": first["delivery_id"]})
    turn = _turn(batch_client, "codex", "target")
    assert turn["deliveries"] == []
    assert turn["blocked_reasons"] == ["publication_unconfirmed"]
    status = batch_client.get(f"/relay/messages/{older['message_id']}", params=SCOPE).json()
    assert status["deliveries"][0]["state"] == "uncertain"


def test_candidate_admission_witness_delivers_and_allows_multipart_reply(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    _send_parts(batch_client, "sender", "codex:target", [f"part {index}" for index in range(6)], "parent")
    delivery = _turn(batch_client, "codex", "target")["deliveries"][0]
    assert _publication(batch_client, delivery).status_code == 200
    assert _admit(batch_client, delivery).status_code == 200
    reply = batch_client.post("/relay/replies", json={
        "delivery_id": delivery["delivery_id"], "receipt": delivery["receipt"],
        "parts": ["reply one", "reply two"], **SCOPE,
    })
    assert reply.status_code == 200, reply.text
    assert reply.json()["payload"] == "reply onereply two"
