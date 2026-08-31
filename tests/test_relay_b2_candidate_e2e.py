from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from datetime import datetime, timedelta, timezone
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from unittest.mock import patch
from sqlalchemy import text

from api.routes import create_router
from app.mcp.client import PalliumMcpClient
from app.mcp.context import PalliumContext
from core.errors import ImmediateTransactionBusyError
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
    app.state.pallium_service = client.app.state.pallium_service
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


def test_legacy_turn_blocks_unclaimed_parts_without_raw_exposure(client: TestClient, batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    sent = _send_parts(batch_client, "sender", "codex:target", ["one", "two"], "preclaim-parts")
    assert _turn(client, "codex", "target")["deliveries"] == []
    status = client.get(f"/relay/messages/{sent['message_id']}", params=SCOPE).json()
    assert status["payload"] == "onetwo"
    assert "[\"one\",\"two\"]" not in status["payload"]


def test_legacy_barrier_status_projects_parts_and_reports_pending_backlog(client: TestClient, batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    sent = _send_parts(batch_client, "sender", "codex:target", ["one", "two"], "preclaim-status")
    legacy = _turn(client, "codex", "target")
    assert legacy["deliveries"] == []
    assert legacy["has_more"] is True
    assert legacy["remaining_count"] == 1
    status = client.get(f"/relay/messages/{sent['message_id']}", params=SCOPE).json()
    assert status["deliveries"][0]["payload"] == "onetwo"
    assert "[\"one\",\"two\"]" not in status["deliveries"][0]["payload"]


def test_candidate_rejects_oversized_multipart_reply_before_creation(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    _send_parts(batch_client, "sender", "codex:target", ["parent"], "reply-parent")
    parent = _turn(batch_client, "codex", "target")["deliveries"][0]
    assert _publication(batch_client, parent).status_code == 200
    assert _admit(batch_client, parent).status_code == 200
    reply = batch_client.post("/relay/replies", json={
        "delivery_id": parent["delivery_id"], "receipt": parent["receipt"],
        "parts": ["a\n" * 749 + "a"] * 8, **SCOPE,
    })
    assert reply.status_code == 409
    assert _turn(batch_client, "claude-code", "sender")["deliveries"] == []

def test_candidate_admission_is_idempotent_and_late_witness_resolves_uncertain(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    _send(batch_client, "sender", "codex:target", "first", "admit-retry")
    first = _turn(batch_client, "codex", "target")["deliveries"][0]
    assert _publication(batch_client, first).status_code == 200
    assert _admit(batch_client, first).status_code == 200
    assert _admit(batch_client, first).status_code == 200

    _send(batch_client, "sender", "codex:target", "second", "late-witness")
    late = _turn(batch_client, "codex", "target")["deliveries"][0]
    assert _publication(batch_client, late).status_code == 200
    storage = batch_client.app.state.batch_storage
    with storage._engine.begin() as connection:
        connection.execute(text("UPDATE relay_deliveries SET lease_expires_at=:past WHERE id=:id"), {"past": datetime.now(timezone.utc) - timedelta(seconds=1), "id": late["delivery_id"]})
    assert _turn(batch_client, "codex", "target")["deliveries"] == []
    assert _admit(batch_client, late, "late-fixture-readback").status_code == 200
    status = batch_client.get("/relay/messages/late-witness", params=SCOPE).json()
    assert status["deliveries"][0]["state"] == "delivered"


def test_actual_mcp_output_can_be_witnessed_then_replied(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target-small")
    _turn(batch_client, "codex", "target")
    _send_parts(batch_client, "sender", "codex:target-small", ["hello"], "mcp-budget")
    _send_parts(batch_client, "sender", "codex:target", ["hello"], "mcp-witness")
    ctx = PalliumContext(base_url="http://relay.test", container_ref=SCOPE["container_ref"], thread_ref="target", actor_ref=SCOPE["actor_ref"], agent_ref="codex", visibility="private")
    small_ctx = PalliumContext(base_url="http://relay.test", container_ref=SCOPE["container_ref"], thread_ref="target-small", actor_ref=SCOPE["actor_ref"], agent_ref="codex", visibility="private")

    async def exercise() -> tuple[dict, dict]:
        transport = httpx.ASGITransport(app=batch_client.app)
        real_client = httpx.AsyncClient
        with patch("app.mcp.client.httpx.AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs)):
            bounded = await PalliumMcpClient(small_ctx).relay_receive("codex", "target-small", max_chars=1000)
            assert len(json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))) <= 1000
            assert bounded["deliveries"] == []
            mcp = PalliumMcpClient(ctx)
            received = await mcp.relay_receive("codex", "target", max_chars=2000)
            delivery = received["deliveries"][0]
            witnessed_delivery = batch_client.get("/relay/messages/mcp-witness", params=SCOPE).json()["deliveries"][0]
            witnessed = _admit(batch_client, witnessed_delivery)
            assert witnessed.status_code == 200
            replied = await mcp.relay_reply(delivery_id=delivery["delivery_id"], receipt=delivery["receipt"], message="ack")
            return received, replied

    received, replied = asyncio.run(exercise())
    assert received["deliveries"][0]["envelope"].endswith("[End Pallium Relay batch]")
    assert replied["in_reply_to"] == "mcp-witness"

def test_candidate_restart_reconciles_unpublished_and_published_claims(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "unpublished")
    _turn(batch_client, "codex", "published")
    _send(batch_client, "sender", "codex:unpublished", "retry", "restart-retry")
    _send(batch_client, "sender", "codex:published", "uncertain", "restart-uncertain")
    unpublished = _turn(batch_client, "codex", "unpublished")["deliveries"][0]
    published = _turn(batch_client, "codex", "published")["deliveries"][0]
    assert _publication(batch_client, published).status_code == 200
    storage = batch_client.app.state.batch_storage
    with storage._engine.begin() as connection:
        connection.execute(text("UPDATE relay_deliveries SET lease_expires_at=:past WHERE id IN (:unpublished, :published)"), {
            "past": datetime.now(timezone.utc) - timedelta(seconds=1), "unpublished": unpublished["delivery_id"], "published": published["delivery_id"],
        })
    app = FastAPI()
    app.include_router(create_router(batch_client.app.state.pallium_service, relay_service=RelayService(storage, batch_candidate_enabled=True)))
    restarted = TestClient(app)
    replacement = _turn(restarted, "codex", "unpublished")["deliveries"][0]
    assert replacement["claim_generation"] == 2
    assert _turn(restarted, "codex", "published")["deliveries"] == []
    assert restarted.get("/relay/messages/restart-uncertain", params=SCOPE).json()["deliveries"][0]["state"] == "uncertain"


def test_candidate_contended_turn_claims_exactly_one_generation(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    _send(batch_client, "sender", "codex:target", "race", "contention-race")

    def claim() -> dict:
        response = TestClient(batch_client.app).post("/relay/turn", json={"runtime": "codex", "session_ref": "target", **SCOPE})
        assert response.status_code == 200, response.text
        return response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        turns = list(pool.map(lambda _: claim(), range(2)))
    deliveries = [delivery for turn in turns for delivery in turn["deliveries"]]
    assert len(deliveries) == 1
    assert deliveries[0]["claim_generation"] == 1
    assert any(turn["has_more"] for turn in turns)

def test_candidate_busy_is_retryable_and_cleanup_releases_orphaned_claim(batch_client: TestClient, monkeypatch) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    sent = _send(batch_client, "sender", "codex:target", "old", "cleanup-claim")
    delivery = _turn(batch_client, "codex", "target")["deliveries"][0]
    storage = batch_client.app.state.batch_storage
    with storage._engine.begin() as connection:
        connection.execute(text("UPDATE relay_messages SET created_at=:created, expires_at=:expired WHERE id=:id"), {
            "id": sent["message_id"], "created": datetime.now(timezone.utc) - timedelta(days=9), "expired": datetime.now(timezone.utc) - timedelta(days=8),
        })
    _send(batch_client, "sender", "codex:target", "trigger", "cleanup-trigger")
    with storage._engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM relay_batch_claims WHERE delivery_id=:id"), {"id": delivery["delivery_id"]}).scalar_one() == 0

    def busy_transaction():
        raise ImmediateTransactionBusyError("database is locked")

    monkeypatch.setattr(storage, "_begin_immediate", busy_transaction)
    response = batch_client.post("/relay/turn", json={"runtime": "codex", "session_ref": "busy", **SCOPE})
    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "relay_busy", "retryable": True}


def test_candidate_reconciles_wrong_and_late_positive_admission_evidence(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    sent = _send(batch_client, "sender", "codex:target", "evidence", "evidence-timing")
    delivery = _turn(batch_client, "codex", "target")["deliveries"][0]
    assert _publication(batch_client, delivery).status_code == 200
    wrong = {**delivery, "envelope_digest": "0" * 64}
    assert _admit(batch_client, wrong).status_code == 409
    assert batch_client.get(f"/relay/messages/{sent['message_id']}", params=SCOPE).json()["deliveries"][0]["state"] == "claimed"
    storage = batch_client.app.state.batch_storage
    with storage._engine.begin() as connection:
        connection.execute(text("UPDATE relay_messages SET expires_at=:past WHERE id=:id"), {"past": datetime.now(timezone.utc) - timedelta(seconds=1), "id": sent["message_id"]})
    assert batch_client.get(f"/relay/messages/{sent['message_id']}", params=SCOPE).json()["deliveries"][0]["state"] == "uncertain"
    assert _admit(batch_client, delivery, "late-after-expiry").status_code == 200
    assert batch_client.get(f"/relay/messages/{sent['message_id']}", params=SCOPE).json()["deliveries"][0]["state"] == "delivered"

def test_candidate_rejects_mixed_fanout_and_pending_capacity(client: TestClient, batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "candidate")
    _turn(client, "codex", "legacy")
    mixed = batch_client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender", "recipient": "codex",
        "payload": "mixed", "message_id": "mixed", **SCOPE,
    })
    assert mixed.status_code == 409
    for index in range(64):
        _send(batch_client, "sender", "codex:candidate", f"queued {index}", f"queued-{index}")
    full = batch_client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender", "recipient": "codex:candidate",
        "payload": "overflow", "message_id": "queued-overflow", **SCOPE,
    })
    assert full.status_code == 409


def test_candidate_rejects_reply_chains_deeper_than_four(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    parent_id = "depth-0"
    _send(batch_client, "sender", "codex:target", "root", parent_id)
    for depth in range(1, 5):
        response = batch_client.post("/relay/messages", json={
            "sender_runtime": "claude-code", "sender_session_ref": "sender", "recipient": "codex:target",
            "payload": f"depth {depth}", "message_id": f"depth-{depth}", "in_reply_to": parent_id, **SCOPE,
        })
        assert response.status_code == 200, response.text
        parent_id = f"depth-{depth}"
    rejected = batch_client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender", "recipient": "codex:target",
        "payload": "too deep", "message_id": "depth-5", "in_reply_to": parent_id, **SCOPE,
    })
    assert rejected.status_code == 409

def test_candidate_rejects_permanently_oversized_escaped_parts_before_acceptance(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    parts = ["a\n" * 749 + "a"] * 8
    response = batch_client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender",
        "recipient": "codex:target", "parts": parts, "message_id": "oversized", **SCOPE,
    })
    assert response.status_code == 409


def test_request_retry_conflicts_when_serialized_payload_format_changes(batch_client: TestClient) -> None:
    _turn(batch_client, "claude-code", "sender")
    _turn(batch_client, "codex", "target")
    base = {"sender_runtime": "claude-code", "sender_session_ref": "sender", "recipient": "codex:target", "request_id": "same", **SCOPE}
    assert batch_client.post("/relay/messages", json={**base, "payload": '["one","two"]'}).status_code == 200
    assert batch_client.post("/relay/messages", json={**base, "parts": ["one", "two"]}).status_code == 409