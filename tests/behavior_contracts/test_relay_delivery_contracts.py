"""Documented Relay delivery contracts through the public HTTP API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from storage.sqlite_schema import RelayDeliveryRecord
from tests.test_agent_relay_hooks import batch_hook, exact_client


SOURCE = {"container_ref": "git:example.test/relay-source"}
TARGET = {"container_ref": "git:example.test/relay-target"}


def _turn(client, runtime, session, scope=SOURCE, **extra):
    response = client.post("/relay/turn", json={
        "runtime": runtime, "session_ref": session, **scope, **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _send(client, recipient, payload="finding", **extra):
    response = client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender",
        "recipient": recipient, "payload": payload, **SOURCE, **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _status(client, message_id):
    response = client.get(f"/relay/messages/{message_id}", params=SOURCE)
    assert response.status_code == 200, response.text
    return response.json()


def test_response_budget_does_not_claim_pending_delivery(client):
    """docs/agent-relay.md Limits: undersized preclaim budget must not consume work."""
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "target")
    sent = _send(client, "codex:target")

    guarded = _turn(client, "codex", "target", max_response_chars=1)
    assert guarded["deliveries"] == []
    assert guarded["has_more"] is True
    assert guarded["remaining_count"] == 1
    assert _status(client, sent["message_id"])["deliveries"][0]["state"] == "pending"

    recovered = _turn(client, "codex", "target")["deliveries"]
    assert [item["message_id"] for item in recovered] == [sent["message_id"]]


def test_ordinary_pageable_turn_reserves_a_sibling_envelope_before_payload_growth(client):
    """docs/agent-relay.md Limits guards against starving a sibling or claiming a third item."""
    _turn(client, "claude-code", "sender")
    _turn(client, "opencode", "target")
    first = _send(client, "opencode:target", "界" * 4000)
    second = _send(client, "opencode:target", "small")
    third = _send(client, "opencode:target", "wait")

    # Fit two rendered envelopes and grow the first prefix without admitting a third.
    batch = _turn(client, "opencode", "target", max_chars=1401)
    left, right = batch["deliveries"]
    assert [left["message_id"], right["message_id"]] == [first["message_id"], second["message_id"]]
    assert left["content_truncated"] and 1 < left["next_offset"] < 4000
    assert right["payload"] == "small" and not right["content_truncated"]
    assert batch["has_more"] and batch["remaining_count"] == 1
    assert left["receipt"] != right["receipt"]
    ack = client.post("/relay/deliveries/mcp-ack", json={
        "delivery_id": right["delivery_id"], "receipt": right["receipt"], **SOURCE,
    })
    assert ack.status_code == 200, ack.text
    assert _status(client, first["message_id"])["deliveries"][0]["state"] == "claimed"
    assert _status(client, third["message_id"])["deliveries"][0]["state"] == "pending"


def test_default_backlog_drains_after_acknowledged_first_page(client):
    """docs/agent-relay.md Limits: default cap must expose and drain the fourth item."""
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "target")
    sent = [_send(client, "codex:target", f"item-{index}") for index in range(4)]

    first = _turn(client, "codex", "target")
    assert [item["message_id"] for item in first["deliveries"]] == [
        item["message_id"] for item in sent[:3]
    ]
    assert first["has_more"] is True and first["remaining_count"] == 1
    for item in first["deliveries"]:
        ack = client.post("/relay/deliveries/mcp-ack", json={
            "delivery_id": item["delivery_id"], "receipt": item["receipt"], **SOURCE,
        })
        assert ack.status_code == 200, ack.text
    last = _turn(client, "codex", "target")
    assert [item["message_id"] for item in last["deliveries"]] == [sent[3]["message_id"]]
    assert last["has_more"] is False and last["remaining_count"] == 0


def test_codex_prompt_batch_emits_required_trigger_before_individual_receipts(batch_hook):
    """docs/agent-relay.md Limits and docs/codex-integration.md define Codex prompt batching.

    Guard against dropped, reordered, or extra blocks and ACK before emission.
    Codex prompt override batches eight. Ordinary HTTP still defaults to three.
    """
    from app.codex_wake import _wake_prompt
    from tests.test_relay_exact_claim_e2e import send, status

    state = batch_hook
    messages = [send(state.client, payload=f"item {index} →") for index in range(9)]
    trigger = messages[-1]
    selected_message_ids = []

    def before_ack():
        assert state.ack_count == 0
        packet, = state.outputs
        *blocks, _scope = packet.split("\n[End Pallium Relay message]")
        assert len(blocks) == packet.count("[Pallium Relay message from ") == 8
        headers = [block.lstrip("\n").splitlines()[:3] for block in blocks]
        assert all(header[0].startswith("[Pallium Relay message from ") for header in headers)
        assert [header[1:] for header in headers] == [
            [f"message_id: {item['message_id']}", f"delivery_id: {item['deliveries'][0]['delivery_id']}"]
            for item in [trigger, *messages[:7]]
        ]
        for block, item in zip(blocks, [trigger, *messages[:7]]):
            assert item["payload"] in block.splitlines()
        assert f"delivery_id: {messages[7]['deliveries'][0]['delivery_id']}" not in packet.splitlines()

        selected = state.turns[-1]["deliveries"]
        assert selected[0]["message_id"] == trigger["message_id"]
        assert len(selected) == 8
        assert all(status(state.client, item)["state"] == "claimed" for item in [trigger, *messages[:7]])
        selected_message_ids.extend(row["message_id"] for row in selected)

    state.on_emit = before_ack
    assert state.run(_wake_prompt(trigger["deliveries"][0]["delivery_id"])) == 0
    assert selected_message_ids == [trigger["message_id"], *(item["message_id"] for item in messages[:7])]
    assert state.ack_count == 8
    assert all(status(state.client, item)["state"] == "delivered" for item in [trigger, *messages[:7]])
    assert (status(state.client, messages[7])["state"], status(state.client, messages[7])["attempts"]) == ("pending", 0)
    assert state.turns[-1]["remaining_count"] == 1


def test_reply_targets_original_sender_and_retries_once(client):
    """docs/agent-relay.md Replies: changed retry text must conflict, never fork."""
    sender = _turn(client, "claude-code", "sender")["session"]
    _turn(client, "codex", "target")
    parent = _send(client, "codex:target", "question")
    claimed = _turn(client, "codex", "target")["deliveries"][0]
    body = {"delivery_id": claimed["delivery_id"], "receipt": claimed["receipt"],
            "payload": "answer → 你好", **SOURCE}

    first = client.post("/relay/replies", json=body)
    again = client.post("/relay/replies", json=body)
    changed = client.post("/relay/replies", json={**body, "payload": "different"})
    assert first.status_code == again.status_code == 200
    assert changed.status_code == 409
    reply = first.json()
    assert again.json()["message_id"] == reply["message_id"]
    assert reply["in_reply_to"] == parent["message_id"]
    assert reply["deliveries"][0]["recipient_endpoint_id"] == sender["endpoint_id"]
    assert _status(client, parent["message_id"])["deliveries"][0]["state"] == "delivered"
    assert [item["message_id"] for item in _turn(client, "claude-code", "sender")["deliveries"]] == [reply["message_id"]]


def test_stale_receipt_cannot_ack_new_claim(client):
    """docs/agent-relay.md Limits: expired lease must reject its old receipt."""
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "target")
    sent = _send(client, "codex:target")
    first = _turn(client, "codex", "target")["deliveries"][0]
    storage = client.app.state.pallium_service._storage
    with storage._begin_relay_immediate() as db:
        db.get(RelayDeliveryRecord, first["delivery_id"]).lease_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )
    second = _turn(client, "codex", "target")["deliveries"][0]
    assert second["receipt"] != first["receipt"]

    stale = client.post("/relay/deliveries/mcp-ack", json={
        "delivery_id": first["delivery_id"], "receipt": first["receipt"], **SOURCE,
    })
    assert stale.status_code == 409
    assert _status(client, sent["message_id"])["deliveries"][0]["state"] == "claimed"
    current = client.post("/relay/deliveries/mcp-ack", json={
        "delivery_id": second["delivery_id"], "receipt": second["receipt"], **SOURCE,
    })
    assert current.status_code == 200
    assert _status(client, sent["message_id"])["deliveries"][0]["state"] == "delivered"


def test_exact_endpoint_routes_across_containers_without_broadening_session_list(client):
    """docs/agent-relay.md Select a recipient: exact cross-project routing stays scoped."""
    _turn(client, "claude-code", "sender")
    target = _turn(client, "codex", "target", TARGET)["session"]
    sent = _send(client, target["endpoint_id"], "שלום → 你好")
    assert sent["deliveries"][0]["recipient_container_ref"] == TARGET["container_ref"]
    assert [item["endpoint_id"] for item in client.get("/relay/sessions", params=SOURCE).json()] == [
        _turn(client, "claude-code", "sender")["session"]["endpoint_id"]
    ]
    assert [item["endpoint_id"] for item in client.get("/relay/sessions", params=TARGET).json()] == [target["endpoint_id"]]
    received = _turn(client, "codex", "target", TARGET)["deliveries"]
    assert [item["message_id"] for item in received] == [sent["message_id"]]
    assert received[0]["payload"] == "שלום → 你好"
    assert _status(client, sent["message_id"])["deliveries"][0]["state"] == "claimed"
