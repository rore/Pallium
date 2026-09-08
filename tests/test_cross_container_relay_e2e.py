"""Caller-level coverage for service-global, cross-container Relay endpoints."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.routes import create_router
from core.relay import RelayService
from storage.sqlite_schema import RelayDeliveryRecord, RelayMessageRecord


SOURCE = "git:example.test/source"
TARGET = "git:example.test/target"


def _turn(client: TestClient, runtime: str, session: str, container: str, actor: str | None = None):
    body = {"runtime": runtime, "session_ref": session, "container_ref": container}
    if actor is not None:
        body["actor_ref"] = actor
    response = client.post("/relay/turn", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _send(client: TestClient, sender: str, recipient: str, container: str = SOURCE, payload: str = "hello", actor: str | None = None):
    body = {
        "sender_runtime": "codex", "sender_session_ref": sender, "recipient": recipient,
        "payload": payload, "container_ref": container,
    }
    if actor is not None:
        body["actor_ref"] = actor
    return client.post("/relay/messages", json=body)


def _name(client: TestClient, session: str, alias: str | None, container: str, **extra):
    return client.post("/relay/sessions/name", json={
        "runtime": "codex", "session_ref": session, "alias": alias,
        "container_ref": container, **extra,
    })


def _counts(client: TestClient) -> tuple[int, int]:
    with client.app.state.pallium_service._storage._relay_session_factory() as db:
        return (
            db.scalar(select(func.count()).select_from(RelayMessageRecord)),
            db.scalar(select(func.count()).select_from(RelayDeliveryRecord)),
        )


def test_actor_variation_does_not_partition_cross_container_lifecycle(client):
    sender = _turn(client, "codex", "sender", SOURCE, actor="actor-register-sender")["session"]
    target = _turn(client, "codex", "target", TARGET, actor="actor-register-target")["session"]
    assert _name(client, "target", "review", TARGET, actor_ref="actor-name").status_code == 200

    exact = _send(client, "sender", target["endpoint_id"], payload="exact → שלום 你好", actor="actor-send-exact")
    assert exact.status_code == 200, exact.text
    exact_message = exact.json()
    assert exact_message["sender_endpoint_id"] == sender["endpoint_id"]
    assert exact_message["deliveries"][0]["recipient_endpoint_id"] == target["endpoint_id"]
    assert exact_message["deliveries"][0]["recipient_container_ref"] == TARGET
    assert client.get(
        f"/relay/messages/{exact_message['message_id']}",
        params={"container_ref": TARGET, "actor_ref": "actor-status-exact"},
    ).status_code == 200

    exact_claim = _turn(client, "codex", "target", TARGET, actor="actor-receive-exact")["deliveries"][0]
    ack = client.post("/relay/deliveries/ack", json={
        "delivery_id": exact_claim["delivery_id"], "claim_token": exact_claim["claim_token"],
        "container_ref": TARGET, "actor_ref": "actor-ack",
    })
    assert ack.status_code == 200, ack.text

    moved_sender = _turn(client, "codex", "sender", TARGET, actor="actor-register-moved")["session"]
    assert moved_sender["endpoint_id"] != sender["endpoint_id"]
    assert client.get(
        f"/relay/messages/{exact_message['message_id']}",
        params={"container_ref": TARGET, "actor_ref": "actor-status-exact"},
    ).json()["sender_endpoint_id"] == sender["endpoint_id"]

    alias = _send(client, "sender", "@review", payload="alias → Δ", actor="actor-send-name")
    assert alias.status_code == 200, alias.text
    alias_message = alias.json()
    assert alias_message["deliveries"][0]["recipient_endpoint_id"] == target["endpoint_id"]
    claim = _turn(client, "codex", "target", TARGET, actor="actor-receive-name")["deliveries"][0]
    reply = client.post("/relay/replies", json={
        "delivery_id": claim["delivery_id"], "receipt": claim["receipt"], "payload": "received → תודה",
        "container_ref": TARGET, "actor_ref": "actor-reply",
    })
    assert reply.status_code == 200, reply.text
    assert reply.json()["deliveries"][0]["recipient_endpoint_id"] == sender["endpoint_id"]
    assert _turn(client, "codex", "sender", SOURCE, actor="actor-receive-reply")["deliveries"][0]["message_id"] == reply.json()["message_id"]

    assert _send(client, "sender", target["endpoint_id"], actor="actor-send-final").status_code == 200
    assert client.get(
        f"/relay/messages/{alias_message['message_id']}",
        params={"container_ref": SOURCE, "actor_ref": "actor-status-name"},
    ).status_code == 200
    source_sessions = client.get("/relay/sessions", params={
        "container_ref": SOURCE, "actor_ref": "actor-discovery-source",
    }).json()
    target_sessions = client.get("/relay/sessions", params={
        "container_ref": TARGET, "actor_ref": "actor-discovery-target",
    }).json()
    assert {item["endpoint_id"] for item in source_sessions} == {sender["endpoint_id"]}
    assert {item["endpoint_id"] for item in target_sessions} == {
        target["endpoint_id"], moved_sender["endpoint_id"],
    }


def test_name_takeover_ignores_actor_variation_and_only_moves_the_name(client):
    _turn(client, "codex", "sender", SOURCE)
    old = _turn(client, "codex", "old", TARGET)["session"]
    new = _turn(client, "codex", "new", SOURCE)["session"]
    assert _name(client, "old", "review", TARGET, actor_ref="actor-old-owner").status_code == 200
    pending = _send(client, "sender", "@review").json()

    conflict = _name(client, "new", "review", SOURCE, actor_ref="actor-new-owner")
    assert conflict.status_code == 409
    assert _send(client, "sender", "@review").json()["deliveries"][0]["recipient_endpoint_id"] == old["endpoint_id"]
    assert _name(client, "new", "review", SOURCE, replace_existing=True, actor_ref="actor-takeover").status_code == 200
    assert _send(client, "sender", "@review").json()["deliveries"][0]["recipient_endpoint_id"] == new["endpoint_id"]
    assert client.get(
        f"/relay/messages/{pending['message_id']}", params={"container_ref": SOURCE},
    ).json()["deliveries"][0]["recipient_endpoint_id"] == old["endpoint_id"]

    assert _name(client, "new", None, SOURCE).status_code == 200
    assert _send(client, "sender", "@review").status_code == 404
    assert _name(client, "new", "review", SOURCE).status_code == 200
    claimed = _turn(client, "codex", "new", SOURCE)["deliveries"][-1]
    closed = client.post("/relay/sessions/close", json={
        "runtime": "codex", "session_ref": "new", "container_ref": SOURCE,
    })
    assert closed.status_code == 200 and closed.json()["alias"] is None
    assert client.post("/relay/replies", json={
        "delivery_id": claimed["delivery_id"], "receipt": claimed["receipt"], "payload": "too late",
        "container_ref": SOURCE,
    }).status_code == 409
    assert _send(client, "sender", "@review").status_code == 404
    assert _turn(client, "codex", "new", SOURCE)["session"]["alias"] is None
    assert _send(client, "sender", "@review").status_code == 404


def test_rejected_legacy_and_runtime_selectors_have_no_delivery_or_wake_side_effects(client):
    wakes: list[dict] = []
    app = FastAPI()
    app.include_router(create_router(
        client.app.state.pallium_service,
        relay_service=RelayService(client.app.state.pallium_service._storage),
        relay_send_callback=lambda result, _scope: wakes.append(result),
    ))
    caller = TestClient(app)
    _turn(caller, "codex", "sender", SOURCE)
    first = _turn(caller, "codex", "duplicate", SOURCE)["session"]
    second = _turn(caller, "codex", "duplicate", TARGET)["session"]
    assert _name(caller, "duplicate", "review", SOURCE).status_code == 200
    before = _counts(client)

    assert _send(caller, "sender", "codex").status_code == 422
    assert _send(caller, "sender", "codex:duplicate").status_code == 409
    assert _send(caller, "sender", "opencode:@review").status_code == 409
    assert _counts(client) == before
    assert wakes == []
    assert _turn(caller, "codex", "duplicate", SOURCE)["deliveries"] == []
    assert _turn(caller, "codex", "duplicate", TARGET)["deliveries"] == []
    assert first["endpoint_id"] != second["endpoint_id"]


def test_actor_global_alias_takeover_can_cross_runtimes_without_rebinding_pending_delivery(client):
    _turn(client, "codex", "sender", SOURCE)
    old = _turn(client, "codex", "codex-owner", TARGET)["session"]
    new = _turn(client, "claude-code", "claude-owner", SOURCE)["session"]
    assert _name(client, "codex-owner", "handoff", TARGET).status_code == 200
    pending = _send(client, "sender", "@handoff").json()

    body = {
        "runtime": "claude-code", "session_ref": "claude-owner", "alias": "handoff",
        "container_ref": SOURCE,
    }
    assert client.post("/relay/sessions/name", json=body).status_code == 409
    assert client.post("/relay/sessions/name", json={**body, "replace_existing": True}).status_code == 200
    future = _send(client, "sender", "@handoff")
    assert future.status_code == 200, future.text
    assert future.json()["deliveries"][0]["recipient_endpoint_id"] == new["endpoint_id"]
    assert client.get(
        f"/relay/messages/{pending['message_id']}",
        params={"container_ref": SOURCE},
    ).json()["deliveries"][0]["recipient_endpoint_id"] == old["endpoint_id"]

def test_concurrent_first_claim_of_global_alias_has_one_owner_and_one_route(client):
    _turn(client, "codex", "sender", SOURCE)
    codex = _turn(client, "codex", "codex-contender", TARGET)["session"]
    claude = _turn(client, "claude-code", "claude-contender", SOURCE)["session"]
    contenders = (
        {"runtime": "codex", "session_ref": "codex-contender", "container_ref": TARGET},
        {"runtime": "claude-code", "session_ref": "claude-contender", "container_ref": SOURCE},
    )

    def claim(body: dict):
        return client.post("/relay/sessions/name", json={**body, "alias": "race"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(claim, contenders))
    assert sorted(response.status_code for response in responses) == [200, 409]
    routed = _send(client, "sender", "@race")
    assert routed.status_code == 200, routed.text
    owner = routed.json()["deliveries"][0]["recipient_endpoint_id"]
    assert owner in {codex["endpoint_id"], claude["endpoint_id"]}
    sessions = [
        *client.get("/relay/sessions", params={"container_ref": SOURCE, "include_inactive": True}).json(),
        *client.get("/relay/sessions", params={"container_ref": TARGET, "include_inactive": True}).json(),
    ]
    assert [session["endpoint_id"] for session in sessions if session["alias"] == "race"] == [owner]

def test_cross_container_reply_chain_and_bounded_backlog_continuation(client):
    sender = _turn(client, "codex", "chain-sender", SOURCE)["session"]
    target = _turn(client, "codex", "chain-target", TARGET)["session"]
    initial = _send(
        client, "chain-sender", target["endpoint_id"], payload="chain-0"
    ).json()

    target_claim = _turn(client, "codex", "chain-target", TARGET)["deliveries"][0]
    reply_one = client.post("/relay/replies", json={
        "delivery_id": target_claim["delivery_id"],
        "receipt": target_claim["receipt"],
        "payload": "chain-1",
        "container_ref": TARGET,
    }).json()
    sender_claim = _turn(client, "codex", "chain-sender", SOURCE)["deliveries"][0]
    reply_two = client.post("/relay/replies", json={
        "delivery_id": sender_claim["delivery_id"],
        "receipt": sender_claim["receipt"],
        "payload": "chain-2",
        "container_ref": SOURCE,
    }).json()
    final_claim = _turn(client, "codex", "chain-target", TARGET)["deliveries"][0]

    assert reply_one["in_reply_to"] == initial["message_id"]
    assert reply_two["in_reply_to"] == reply_one["message_id"]
    assert final_claim["message_id"] == reply_two["message_id"]
    assert reply_one["deliveries"][0]["recipient_endpoint_id"] == sender["endpoint_id"]
    assert reply_two["deliveries"][0]["recipient_endpoint_id"] == target["endpoint_id"]
    assert client.post("/relay/deliveries/ack", json={
        "delivery_id": final_claim["delivery_id"],
        "claim_token": final_claim["claim_token"],
        "container_ref": TARGET,
    }).status_code == 200

    for index in range(3):
        assert _send(
            client,
            "chain-sender",
            target["endpoint_id"],
            payload=f"backlog-{index}",
        ).status_code == 200
    first = client.post("/relay/turn", json={
        "runtime": "codex",
        "session_ref": "chain-target",
        "container_ref": TARGET,
        "max_messages": 1,
        "max_chars": 1000,
    }).json()
    assert len(first["deliveries"]) == 1
    assert first["has_more"] is True
    assert first["remaining_count"] == 2

    second = client.post("/relay/turn", json={
        "runtime": "codex",
        "session_ref": "chain-target",
        "container_ref": TARGET,
        "max_messages": 2,
        "max_chars": 1000,
    }).json()
    assert [item["payload"] for item in second["deliveries"]] == [
        "backlog-1",
        "backlog-2",
    ]
    assert second["has_more"] is False
    assert second["remaining_count"] == 0
