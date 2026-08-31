"""Manager acceptance regressions: committed contract, disposable real surfaces."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import text

from app.mcp.client import PalliumMcpClient
from app.mcp.context import PalliumContext
from storage.sqlite_relay import _render_batch_envelope
from tests.test_relay_b2_candidate_e2e import (
    SCOPE, batch_client, _turn, _send, _send_parts, _publication, _admit,
)


def _receive(client, target):
    async def run():
        transport = httpx.ASGITransport(app=client.app)
        constructor = httpx.AsyncClient
        context = PalliumContext(base_url="http://relay.test", thread_ref=target,
                                 agent_ref="codex", visibility="private", **SCOPE)
        with patch("app.mcp.client.httpx.AsyncClient",
                   lambda **kwargs: constructor(transport=transport, **kwargs)):
            return await PalliumMcpClient(context).relay_receive("codex", target)
    return asyncio.run(run())


def _register(client, target):
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", target)


@pytest.mark.parametrize("count,size", [(6, 490), (8, 1490)])
def test_default_mcp_delivers_complete_parts(batch_client, count, size):
    _register(batch_client, "six")
    parts = [f"part-{index}:" + "x" * size for index in range(count)]
    _send_parts(batch_client, "sender", "codex:six", parts, "six")
    received = _receive(batch_client, "six")
    assert len(received["deliveries"]) == 1
    envelope = received["deliveries"][0]["envelope"]
    assert f"part_count: {count}" in envelope
    assert all(part in envelope for part in parts)
    assert envelope.endswith("[End Pallium Relay batch]")
    assert "claim_token" not in received["deliveries"][0]
    output = json.dumps(received, ensure_ascii=False, separators=(",", ":"))
    assert len(output) <= 16_384 and len(output.encode("utf-8")) <= 65_536


def test_maximum_accepted_batch_fits_default_mcp_or_rejects_atomically(batch_client):
    _register(batch_client, "big")
    largest = None
    for lines in range(300):
        parts = ["a\n" * lines + "x" * (1500 - 2 * lines)] * 8
        envelope = _render_batch_envelope(
            parts, sender_runtime="claude-code", sender_session_ref="sender",
            message_id="maximum", delivery_id="relay-delivery-" + "0" * 32,
            recipient_session_ref="big", recipient_runtime="codex", generation=1,
            in_reply_to=None, **SCOPE,
        )
        if len(envelope) <= 16_384:
            largest = parts
    assert largest is not None
    sent = batch_client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender",
        "recipient": "codex:big", "parts": largest, "message_id": "maximum", **SCOPE,
    })
    if sent.status_code != 200:
        assert sent.status_code == 409
        assert "budget" in sent.json()["detail"].lower()
        assert batch_client.get("/relay/messages/maximum", params=SCOPE).status_code == 404
        return
    received = _receive(batch_client, "big")
    assert len(received["deliveries"]) == 1, "accepted batch must fit a maximum-budget empty MCP turn"
    assert "part_count: 8" in received["deliveries"][0]["envelope"]
    output = json.dumps(received, ensure_ascii=False, separators=(",", ":"))
    assert len(output) <= 16_384 and len(output.encode("utf-8")) <= 65_536


def _release_request(client):
    _register(client, "negative")
    _send(client, "sender", "codex:negative", "work", "negative")
    delivery = _turn(client, "codex", "negative")["deliveries"][0]
    assert _publication(client, delivery).status_code == 200
    with client.app.state.batch_storage._engine.begin() as db:
        db.execute(text("UPDATE relay_deliveries SET lease_expires_at=:past WHERE id=:id"), {
            "past": datetime.now(timezone.utc) - timedelta(seconds=1), "id": delivery["delivery_id"],
        })
    _turn(client, "codex", "negative")
    # Explicit simulated runtime attestations; lease expiry itself is NOT fencing proof.
    return {
        "delivery_id": delivery["delivery_id"], "claim_token": delivery["claim_token"],
        "envelope_digest": delivery["envelope_digest"],
        "non_admission_evidence": "fixture-runtime-confirmed-not-admitted",
        "publication_fence_evidence": "fixture-runtime-confirmed-publisher-stopped", **SCOPE,
    }


def test_same_negative_reconciliation_retry_is_idempotent(batch_client):
    request = _release_request(batch_client)
    first = batch_client.post("/relay/deliveries/non-admission", json=request)
    assert first.status_code == 200, first.text
    repeated = batch_client.post("/relay/deliveries/non-admission", json=request)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == first.json()


def test_expiry_after_proven_non_admission_does_not_restore_uncertainty(batch_client):
    request = _release_request(batch_client)
    assert batch_client.post("/relay/deliveries/non-admission", json=request).status_code == 200
    with batch_client.app.state.batch_storage._engine.begin() as db:
        db.execute(text("UPDATE relay_messages SET expires_at=:past WHERE id='negative'"), {
            "past": datetime.now(timezone.utc) - timedelta(seconds=1),
        })
    status = batch_client.get("/relay/messages/negative", params=SCOPE).json()
    assert status["deliveries"][0]["state"] == "expired"
    assert _turn(batch_client, "codex", "negative")["deliveries"] == []

@pytest.mark.parametrize("field,bad", [("claim_token", "wrong"), ("envelope_digest", "0" * 64)])
def test_negative_retry_still_validates_attempt(batch_client, field, bad):
    request = _release_request(batch_client)
    assert batch_client.post("/relay/deliveries/non-admission", json=request).status_code == 200
    assert batch_client.post("/relay/deliveries/non-admission", json={**request, field: bad}).status_code == 409
    assert batch_client.get("/relay/messages/negative", params=SCOPE).json()["deliveries"][0]["state"] == "pending"


def test_resolved_expiry_is_stable_and_cleanup_releases_claim(batch_client):
    request = _release_request(batch_client)
    assert batch_client.post("/relay/deliveries/non-admission", json=request).status_code == 200
    with batch_client.app.state.batch_storage._engine.begin() as db:
        db.execute(text("UPDATE relay_messages SET expires_at=:past WHERE id='negative'"), {
            "past": datetime.now(timezone.utc) - timedelta(days=8),
        })
    for _ in range(3):
        status = batch_client.get("/relay/messages/negative", params=SCOPE).json()
        assert status["deliveries"][0]["state"] == "expired"
    _send(batch_client, "sender", "codex:negative", "cleanup", "cleanup")
    assert batch_client.get("/relay/messages/negative", params=SCOPE).status_code == 404
    with batch_client.app.state.batch_storage._engine.connect() as db:
        assert db.execute(text("SELECT COUNT(*) FROM relay_batch_claims WHERE delivery_id=:id"), {
            "id": request["delivery_id"],
        }).scalar_one() == 0


@pytest.mark.parametrize("lines", [0, 80, 120, 140, 160, 200])
def test_every_accepted_escaped_boundary_fits_mcp(batch_client, lines):
    _register(batch_client, "boundary")
    parts = ["a\n" * lines + "x" * (1500 - 2 * lines)] * 8
    response = batch_client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender",
        "recipient": "codex:boundary", "parts": parts, "message_id": "boundary", **SCOPE,
    })
    if response.status_code == 409:
        assert "budget" in response.json()["detail"].lower()
        assert batch_client.get("/relay/messages/boundary", params=SCOPE).status_code == 404
    else:
        assert response.status_code == 200, response.text
        received = _receive(batch_client, "boundary")
        assert len(received["deliveries"]) == 1
        assert "part_count: 8" in received["deliveries"][0]["envelope"]
        output = json.dumps(received, ensure_ascii=False, separators=(",", ":"))
        assert len(output) <= 16_384 and len(output.encode("utf-8")) <= 65_536


def test_mcp_fifo_prefix_eventually_drains_without_publication_of_suffix(batch_client):
    _register(batch_client, "prefix")
    for index in range(3):
        _send_parts(batch_client, "sender", "codex:prefix", ["🌍\n" * 400] * 3, f"prefix-{index}")
    seen = []
    for _ in range(3):
        received = _receive(batch_client, "prefix")
        assert received["deliveries"]
        output = json.dumps(received, ensure_ascii=False, separators=(",", ":"))
        assert len(output) <= 16_384 and len(output.encode("utf-8")) <= 65_536
        for delivery in received["deliveries"]:
            seen.append(delivery["message_id"])
            private = batch_client.get(f"/relay/messages/{delivery['message_id']}", params=SCOPE).json()["deliveries"][0]
            assert _admit(batch_client, private).status_code == 200
        with batch_client.app.state.batch_storage._engine.begin() as db:
            # A claimed-but-unexposed suffix may safely retry after lease expiry.
            rows = db.execute(text("SELECT c.publication_started_at FROM relay_batch_claims c JOIN relay_deliveries d ON d.id=c.delivery_id WHERE d.state='claimed'")).all()
            assert all(row[0] is None for row in rows)
            db.execute(text("UPDATE relay_deliveries SET lease_expires_at=:past WHERE state='claimed'"), {
                "past": datetime.now(timezone.utc) - timedelta(seconds=1),
            })
        if not received["has_more"]:
            break
    assert seen == [f"prefix-{index}" for index in range(3)]
    assert _receive(batch_client, "prefix")["deliveries"] == []


def test_cleanup_retains_unresolved_exposure_and_its_ancestry(batch_client):
    _register(batch_client, "ancestry")
    _send(batch_client, "sender", "codex:ancestry", "parent", "ancestor")
    parent = _turn(batch_client, "codex", "ancestry")["deliveries"][0]
    assert _publication(batch_client, parent).status_code == 200
    assert _admit(batch_client, parent).status_code == 200
    reply = batch_client.post("/relay/replies", json={
        "delivery_id": parent["delivery_id"], "receipt": parent["receipt"], "payload": "child", **SCOPE,
    })
    assert reply.status_code == 200, reply.text
    child = _turn(batch_client, "claude-code", "sender")["deliveries"][0]
    assert _publication(batch_client, child).status_code == 200
    with batch_client.app.state.batch_storage._engine.begin() as db:
        db.execute(text("UPDATE relay_messages SET expires_at=:past"), {"past": datetime.now(timezone.utc) - timedelta(days=8)})
    _send(batch_client, "sender", "codex:ancestry", "trigger cleanup", "trigger")
    assert batch_client.get("/relay/messages/ancestor", params=SCOPE).status_code == 200
    status = batch_client.get(f"/relay/messages/{child['message_id']}", params=SCOPE)
    assert status.status_code == 200
    assert status.json()["deliveries"][0]["state"] == "uncertain"
