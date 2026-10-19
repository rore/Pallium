"""Caller-visible Relay contracts for the experimental Hermes integration."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import create_router
from core.relay import RelayService


SCOPE = {"container_ref": "git:example.test/team/relay"}


def turn(client, session="ses_שלום", **extra):
    response = client.post("/relay/turn", json={
        "runtime": "hermes", "session_ref": session, **SCOPE, **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()


def pending(client, **extra):
    return client.get("/relay/pending-candidate", params={
        "runtime": "hermes", "session_ref": "ses_שלום", **SCOPE, **extra,
    })


def send(client, endpoint, payload="Hello שלום 🌍"):
    registered = client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "sender", **SCOPE,
    })
    assert registered.status_code == 200, registered.text
    response = client.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender",
        "recipient": endpoint, "payload": payload, **SCOPE,
    })
    assert response.status_code == 200, response.text
    return response.json()


def status(client, message):
    response = client.get("/relay/messages/" + message["message_id"], params=SCOPE)
    assert response.status_code == 200, response.text
    return response.json()


def test_hermes_pending_read_and_reply_lifecycle(client):
    assert pending(client).json() is None
    session = turn(client)["session"]
    activation = session["activation"]
    assert activation["runtime"] == "hermes"
    assert activation["behavior"] == "passive"
    assert activation["qualification"] == "unqualified"
    assert activation["qualification_source"] == "none"
    assert activation["supported_evidence"] == []
    assert activation["fallback"] == "unknown"
    message = send(client, session["endpoint_id"])
    before = status(client, message)
    for _ in range(2):
        assert pending(client).json() == {
            "delivery_id": message["deliveries"][0]["delivery_id"],
            "recipient_endpoint_id": session["endpoint_id"], "state": "pending",
        }
    assert status(client, message) == before
    assert pending(client, session_ref="other").json() is None
    assert pending(client, runtime="codex").json() is None
    assert pending(client, container_ref="git:example.test/team/other").json() is None
    claim = turn(client, max_chars=2400, max_messages=1)["deliveries"][0]
    assert claim["payload"] == message["payload"]
    assert claim["recipient_session_ref"] == "ses_שלום"
    assert not claim["content_truncated"]
    assert pending(client).json() is None
    ack_body = {"delivery_id": claim["delivery_id"], "claim_token": claim["claim_token"], **SCOPE}
    assert client.post("/relay/deliveries/ack", json={**ack_body, "claim_token": "wrong"}).status_code == 409
    assert client.post("/relay/deliveries/ack", json=ack_body).status_code == 200
    assert client.post("/relay/deliveries/ack", json=ack_body).status_code == 200
    reply = client.post("/relay/replies", json={
        "delivery_id": claim["delivery_id"], "receipt": claim["receipt"],
        "payload": "reply ✓", **SCOPE,
    })
    assert reply.status_code == 200, reply.text
    received = client.post("/relay/turn", json={
        "runtime": "claude-code", "session_ref": "sender", "max_chars": 2400, **SCOPE,
    }).json()["deliveries"][0]
    assert received["payload"] == "reply ✓"
    assert received["sender_runtime"] == "hermes"
    assert received["in_reply_to"] == message["message_id"]
    assert status(client, message)["deliveries"][0]["state"] == "delivered"
    assert pending(client).json() is None
    closed = client.post("/relay/sessions/close", json={
        "runtime": "hermes", "session_ref": "ses_שלום", **SCOPE,
    })
    assert closed.status_code == 200
    assert closed.json()["state"] == "closed"


@pytest.mark.parametrize("field,value", [
    ("runtime", "unknown"), ("runtime", "Hermes"), ("runtime", ""),
    ("session_ref", ""), ("session_ref", " "), ("session_ref", "s\n"),
    ("session_ref", "s" * 256), ("container_ref", ""),
    ("container_ref", "c" * 513),
])
def test_pending_rejects_invalid_scope(client, field, value):
    assert pending(client, **{field: value}).status_code == 422


def test_pending_boundaries_and_unsupported_backend(client):
    assert pending(client, session_ref="s" * 255).status_code == 200
    assert client.get("/relay/pending-candidate", params=SCOPE).status_code == 422
    app = FastAPI()
    app.include_router(create_router(client.app.state.pallium_service))
    with TestClient(app) as unsupported:
        assert pending(unsupported).status_code == 501


def test_stale_hermes_wake_cannot_reopen_closed_endpoint(client):
    endpoint = turn(client)["session"]["endpoint_id"]
    message = send(client, endpoint)
    response = client.post("/relay/sessions/close", json={
        "runtime": "hermes", "session_ref": "ses_שלום", **SCOPE,
    })
    assert response.status_code == 200
    assert pending(client).json()["recipient_endpoint_id"] == endpoint
    wake = turn(client, register_session=False, max_chars=2400, max_messages=1)
    assert wake["session"]["state"] == "closed"
    assert wake["deliveries"] == []
    delivery = status(client, message)["deliveries"][0]
    assert delivery["state"] == "pending"
    assert delivery["attempts"] == 0
    assert delivery["claim_token"] is None


def test_hermes_callbacks_do_not_use_codex_executor(client):
    callbacks = []

    async def general(operation):
        return operation()

    async def codex(operation):
        pytest.fail("Hermes operation reached the Codex executor")

    service = client.app.state.pallium_service
    app = FastAPI()
    app.include_router(create_router(
        service, relay_service=RelayService(service._storage),
        relay_runner=general, relay_codex_runner=codex,
        relay_ack_callback=lambda result, scope: callbacks.append(result),
    ))
    with TestClient(app) as isolated:
        endpoint = turn(isolated)["session"]["endpoint_id"]
        send(isolated, endpoint)
        claim = turn(isolated, max_chars=2400)["deliveries"][0]
        assert isolated.post("/relay/deliveries/ack", json={
            "delivery_id": claim["delivery_id"], "claim_token": claim["claim_token"], **SCOPE,
        }).status_code == 200
        assert isolated.post("/relay/replies", json={
            "delivery_id": claim["delivery_id"], "receipt": claim["receipt"],
            "payload": "reply", **SCOPE,
        }).status_code == 200
    assert len(callbacks) == 2
    assert all(row["recipient_runtime"] == "hermes" for row in callbacks)
