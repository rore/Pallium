"""Caller-visible redelivery envelopes retain receipt safety and bounded admission."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from storage.sqlite_schema import RelayDeliveryRecord


GUIDANCE = (
    "Check exact delivery_id in context/artifacts. "
    "Skip completed actions; if unknown, inspect target state before irreversible retry. "
    "Attempts do not prove emission/actions. ACK: receipt, not completion"
)
SCOPE = {"container_ref": "git:example.test/envelope"}


def _send(client, payload="Inspect target state 😀", *, message_id=None):
    for runtime, session in (("codex", "sender"), ("codex", "target")):
        response = client.post("/relay/turn", json={"runtime": runtime, "session_ref": session, **SCOPE})
        assert response.status_code == 200, response.text
    response = client.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "sender", "recipient": "codex:target",
        "payload": payload, **({"message_id": message_id} if message_id else {}), **SCOPE,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _status(client, message_id):
    response = client.get(f"/relay/messages/{message_id}", params=SCOPE)
    assert response.status_code == 200, response.text
    return response.json()["deliveries"][0]


@pytest.mark.parametrize("failure", ["emit", "ack"])
def test_hook_redelivery_after_emit_or_ack_gap_preserves_exact_id_and_receipt(
    client, monkeypatch, tmp_path, failure,
):
    from app import codex_wake
    from integrations.codex.hooks import user_prompt_submit as hook

    monkeypatch.setenv("HOME", str(tmp_path / "profile"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    monkeypatch.setattr(hook._common, "STATE_DIR", tmp_path / "hook-state")
    monkeypatch.setattr(hook._common, "SESSIONS_DIR", tmp_path / "hook-state" / "sessions")
    sent = _send(client)
    delivery_id = sent["deliveries"][0]["delivery_id"]
    monkeypatch.setattr(hook, "read_hook_input", lambda: {
        "cwd": str(tmp_path), "session_id": "target", "prompt": codex_wake._wake_prompt(delivery_id),
    })
    monkeypatch.setattr(hook, "get_pending_relay_close_batch", lambda *_: ([], 0))
    monkeypatch.setattr(hook, "resolve_container_ref", lambda *_: SCOPE["container_ref"])
    monkeypatch.setattr(hook, "derive_actor_ref", lambda *_: "actor")
    monkeypatch.setattr(hook, "check_dedup", lambda *_: False)
    monkeypatch.setattr(hook, "pallium_request", lambda *_a, **_k: pytest.fail("wake must not query memory"))
    monkeypatch.setattr(hook, "record_codex_wake_event", lambda **_event: None)
    claims, acknowledgments, outputs = [], [], []
    gap = True

    def request(method, path, body, **_kwargs):
        if path == "/relay/deliveries/ack":
            acknowledgments.append(body)
            if gap and failure == "ack":
                return None
        response = client.request(method, path, json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        if path == "/relay/turn":
            claims.extend(result["deliveries"])
        return result

    def emit(text, _event):
        if gap and failure == "emit":
            raise OSError("test emission unavailable")
        outputs.append(text)

    monkeypatch.setattr(hook, "relay_request", request)
    monkeypatch.setattr(hook._common, "relay_request", request)
    monkeypatch.setattr(hook, "emit_context", emit)
    blocked_exits = []

    def blocked_exit():
        blocked_exits.append(2)
        raise SystemExit(2)

    monkeypatch.setattr(hook, "_exit_blocked_wake", blocked_exit)
    with pytest.raises(SystemExit) as first_exit:
        hook.main()
    assert first_exit.value.code == (2 if failure == "emit" else 0)
    assert blocked_exits == ([2] if failure == "emit" else [])
    first = claims[0]
    assert _status(client, sent["message_id"])["state"] == "claimed"
    assert len(outputs) == (0 if failure == "emit" else 1)
    assert len(acknowledgments) == (0 if failure == "emit" else 1)

    storage = client.app.state.pallium_service._storage
    with storage._begin_relay_immediate() as db:
        record = db.get(RelayDeliveryRecord, delivery_id)
        record.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    gap = False
    with pytest.raises(SystemExit) as retry_exit:
        hook.main()
    assert retry_exit.value.code == 0
    current = claims[-1]
    assert current["delivery_id"] == first["delivery_id"] == delivery_id
    assert current["message_id"] == first["message_id"] == sent["message_id"]
    assert current["receipt"] != first["receipt"]
    assert "claim_attempt: 2\npossible_redelivery: true" in outputs[-1]
    assert GUIDANCE in outputs[-1]
    assert current["claim_token"] not in outputs[-1]
    assert _status(client, sent["message_id"])["state"] == "delivered"
    stale = client.post("/relay/deliveries/mcp-ack", json={
        "delivery_id": delivery_id, "receipt": first["receipt"], **SCOPE,
    })
    assert stale.status_code == 409, stale.text


def test_projected_tenth_claim_reserves_envelope_before_payload_admission(client):
    from integrations.codex.hooks.common import format_relay

    payload = "😀" * 1500
    sent = _send(client, payload, message_id="m" * 128)
    delivery_id = sent["deliveries"][0]["delivery_id"]
    first = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target", "max_chars": 10000, **SCOPE,
    }).json()["deliveries"][0]
    # Independently specify the new envelope budget; the old server admits the whole body.
    old_text = format_relay([{**first, "attempts": 9}])[0]
    if "claim_attempt:" not in old_text:
        old_text = old_text.replace(
            f"delivery_id: {delivery_id}\n", f"delivery_id: {delivery_id}\nclaim_attempt: 9\npossible_redelivery: true\n",
        ).replace("\n\n" + payload, "\n" + GUIDANCE + "\n\n" + payload)
    budget = len(old_text)
    storage = client.app.state.pallium_service._storage
    with storage._begin_relay_immediate() as db:
        record = db.get(RelayDeliveryRecord, delivery_id)
        record.attempts = 9
        record.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    turn = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target", "max_chars": budget, **SCOPE,
    }).json()
    assert len(turn["deliveries"]) == 1
    claimed = turn["deliveries"][0]
    assert claimed["attempts"] == 10
    assert len(claimed["payload"]) < len(payload)
    rendered, emitted = format_relay(turn["deliveries"], budget_chars=budget)
    assert emitted == turn["deliveries"]
    assert len(rendered) <= budget
    assert "claim_attempt: 10\npossible_redelivery: true" in rendered
    assert GUIDANCE in rendered
    assert claimed["content_truncated"] is True
    assert claimed["next_offset"] == len(claimed["payload"])


def test_projected_json_budget_reserves_model_guidance_before_claim(client, monkeypatch):
    import storage.sqlite_relay as relay_storage

    sent = _send(client, "😀" * 1500)
    request = {"runtime": "codex", "session_ref": "target", "max_chars": 10000, **SCOPE}
    projections = []
    measure = relay_storage._compact_json_chars

    def observe(value):
        projections.append(value)
        return measure(value)

    monkeypatch.setattr(relay_storage, "_compact_json_chars", observe)
    first = client.post("/relay/turn", json={**request, "max_response_chars": 10000}).json()
    delivery = first["deliveries"][0]
    projection = projections[-1]
    expected = {**projection, "deliveries": [{
        **projection["deliveries"][0], "attempts": 2, "claim_attempt": 2, "possible_redelivery": True,
        "redelivery_guidance": GUIDANCE,
    }]}
    budget = len(json.dumps(expected, ensure_ascii=False, separators=(",", ":"))) - 1
    with client.app.state.pallium_service._storage._begin_relay_immediate() as db:
        record = db.get(RelayDeliveryRecord, delivery["delivery_id"])
        record.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    response = client.post("/relay/turn", json={**request, "max_response_chars": budget})
    assert response.status_code == 200, response.text
    current = response.json()["deliveries"][0]
    assert current["attempts"] == 2
    assert len(current["payload"]) < len(delivery["payload"])
    assert projections[-1]["deliveries"][0]["redelivery_guidance"] == GUIDANCE
    assert current["receipt"] != delivery["receipt"]
    assert _status(client, sent["message_id"])["state"] == "claimed"
