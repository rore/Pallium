from datetime import datetime, timedelta, timezone
import sqlite3
import sys
import threading

import pytest

from core.codex_wake import CodexWakeRegistry
from core.relay import RELAY_CLAIM_LEASE_SECONDS
from tests.test_codex_retained_wake import (
    SCOPE, TARGET, _hook_runner, http_wake, recover, retained as retained_fixture,
)


@pytest.fixture
def retained(monkeypatch, tmp_path):
    yield from retained_fixture.__wrapped__(monkeypatch, tmp_path)


def _freeze_clock(monkeypatch, now):
    import storage.sqlite_relay as sqlite_relay

    def controlled_now(value=None):
        current = value or now[0]
        return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)

    monkeypatch.setattr(sqlite_relay, "_now", controlled_now)


def test_retry_deadline_clamps_once_across_rollback_restart_and_due_wake(
    http_wake, monkeypatch,
):
    http, relay, registry, service, desktop, send, workers = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]
    _freeze_clock(monkeypatch, now)
    desktop.state = "notLoaded"
    delivery = send()
    initial = registry.snapshot(delivery["recipient_endpoint_id"])
    assert initial is not None and initial.outcome == "uncertain"
    deadline = initial.retry_not_before
    assert deadline is not None and len(desktop.owners) == 1

    now[0] -= timedelta(seconds=30)
    recover(http_wake)
    assert registry.snapshot(initial.recipient_endpoint_id).retry_not_before == deadline
    assert len(desktop.owners) == 1

    now[0] -= timedelta(seconds=180)
    recover(http_wake)
    clamped = registry.snapshot(initial.recipient_endpoint_id)
    assert clamped is not None and clamped.retry_not_before == now[0].timestamp() + 60
    recover(http_wake)
    assert registry.snapshot(initial.recipient_endpoint_id) == clamped
    assert len(desktop.owners) == 1

    restarted = CodexWakeRegistry(relay_service=relay)
    restarted.retained_service = service
    assert restarted.snapshot(initial.recipient_endpoint_id) == clamped
    restarted_journey = (http, relay, restarted, service, desktop, send, workers)
    now[0] += timedelta(seconds=61)
    recover(restarted_journey)
    assert len(desktop.owners) == 2


def test_due_retry_reads_moved_scope_and_hook_acks_same_delivery(http_wake, monkeypatch, tmp_path):
    http, relay, registry, _, desktop, send, _ = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]
    _freeze_clock(monkeypatch, now)
    delivery = send()
    now[0] += timedelta(seconds=61)
    moved_scope = {"container_ref": "git:example.test/retry-current-scope"}
    moved = http.post("/relay/turn", json={
        "runtime": "codex", "session_ref": TARGET, "max_chars": 1,
        "max_messages": 1, "previous_container_ref": SCOPE["container_ref"],
        "previous_endpoint_id": delivery["recipient_endpoint_id"],
        "previous_scope_generation": 0, **moved_scope,
    })
    assert moved.status_code == 200 and moved.json()["deliveries"] == []
    recover(http_wake)
    reservation = registry.snapshot(delivery["recipient_endpoint_id"])
    assert reservation is not None and reservation.container_ref == moved_scope["container_ref"]
    assert len(desktop.owners) == 2
    reads = [item for item in desktop.writes
             if item.get("params", {}).get("tool") == "read_thread"]
    assert reads[-1]["params"]["arguments"]["threadId"] == TARGET
    assert desktop.owners[-1]["params"]["arguments"]["threadId"] == TARGET

    events = []
    monkeypatch.setitem(SCOPE, "container_ref", moved_scope["container_ref"])
    run_hook = _hook_runner(http, monkeypatch, "idle", events, tmp_path)
    run_hook()
    assert events[-1] == ("ack",)
    current = http.get("/relay/messages/retained-journey", params=moved_scope)
    assert current.status_code == 200
    assert current.json()["deliveries"][0]["state"] == "delivered"


def test_nullable_legacy_retry_deadline_recovers_and_hook_acks(http_wake, monkeypatch, tmp_path):
    http, relay, registry, _, desktop, send, _ = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]
    _freeze_clock(monkeypatch, now)
    delivery = send()
    with sqlite3.connect(relay._store._relay_engine.url.database) as connection:
        connection.execute(
            "UPDATE relay_codex_wake_reservations SET retry_not_before = NULL WHERE recipient_endpoint_id = ?",
            (delivery["recipient_endpoint_id"],),
        )
    restarted = CodexWakeRegistry(relay_service=relay)
    restarted.retained_service = http_wake[3]
    journey = (*http_wake[:2], restarted, *http_wake[3:])
    assert restarted.snapshot(delivery["recipient_endpoint_id"]).retry_not_before is None
    recover(journey)
    assert len(desktop.owners) == 2

    events = []
    run_hook = _hook_runner(http, monkeypatch, "idle", events, tmp_path)
    run_hook()
    assert events[-1] == ("ack",)
    assert http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"][0]["state"] == "delivered"


@pytest.mark.parametrize("fault", ["claim-response", "ack-before-commit", "ack-response"])
@pytest.mark.parametrize("moved", [False, True])
@pytest.mark.parametrize("restart", [False, True])
def test_unloaded_hook_claim_failure_recovers_original_and_backlog(
    client, http_wake, monkeypatch, tmp_path, capsys, fault, moved, restart,
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.dependencies import build_router

    http, relay, registry, service, desktop, _, workers = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]
    _freeze_clock(monkeypatch, now)
    sender_scope = dict(SCOPE)
    target = http.post("/relay/turn", json={
        "runtime": "codex", "session_ref": TARGET, "max_chars": 1, **SCOPE,
    }).json()["session"]
    if moved:
        destination = "git:example.test/moved-claim-東京"
        response = http.post("/relay/turn", json={
            "runtime": "codex", "session_ref": TARGET, "max_chars": 1,
            "previous_container_ref": SCOPE["container_ref"],
            "previous_endpoint_id": target["endpoint_id"],
            "previous_scope_generation": target["scope_generation"],
            "container_ref": destination,
        })
        assert response.status_code == 200, response.text
        assert response.json()["session"]["endpoint_id"] == target["endpoint_id"]
        monkeypatch.setitem(SCOPE, "container_ref", destination)

    events = []
    run_hook = _hook_runner(http, monkeypatch, "notLoaded", events, tmp_path)
    hook = sys.modules["relay_test_retained_session_start"]
    request, acknowledge = hook.relay_request, hook.acknowledge_relay

    def lose_claim_response(*args, **kwargs):
        response = request(*args, **kwargs)
        assert response["deliveries"] and "wake_delivery_id" not in args[2]
        raise TimeoutError("isolated claim response loss")

    def fail_ack(deliveries, **kwargs):
        if fault == "ack-response":
            acknowledge(deliveries, **kwargs)
        raise TimeoutError("isolated ACK failure")

    if fault == "claim-response":
        monkeypatch.setattr(hook, "relay_request", lose_claim_response)
    else:
        monkeypatch.setattr(hook, "acknowledge_relay", fail_ack)
    desktop.on_owner = lambda request: run_hook(request["params"]["arguments"]["prompt"])

    def send(message_id, payload):
        response = http.post("/relay/messages", json={
            "sender_runtime": "claude-code", "sender_session_ref": "sender",
            "recipient": target["endpoint_id"], "message_id": message_id,
            "payload": payload, **sender_scope,
        })
        assert response.status_code == 200, response.text
        for worker in workers:
            worker.join(2)
            assert not worker.is_alive()
        return response.json()["deliveries"][0]

    first = send("claim-failure-original", "original-marker-東京")
    observed = http.get("/relay/messages/claim-failure-original", params=sender_scope).json()["deliveries"][0]
    assert observed["state"] == ("delivered" if fault == "ack-response" else "claimed")
    assert observed["attempts"] == 1
    if fault != "ack-response":
        fence = registry.snapshot(first["recipient_endpoint_id"])
        assert fence is not None and fence.correlated_claim_attempts is None
        state = relay.codex_wake_reservation_state(delivery_id=first["delivery_id"])
        assert state["codex_wake_generation"] is None
    else:
        assert registry.reservations() == ()
    monkeypatch.setattr(hook, "relay_request", request)
    monkeypatch.setattr(hook, "acknowledge_relay", acknowledge)

    if restart:
        registry = CodexWakeRegistry(relay_service=relay)
        registry.retained_service = service
        app = FastAPI()
        app.include_router(build_router(
            client.app.state.pallium_service,
            relay_storage=client.app.state.pallium_service._storage,
            codex_wake_registry=registry,
        ))
        http.close()
        http = TestClient(app)
        run_hook = _hook_runner(http, monkeypatch, "notLoaded", events, tmp_path)
    send("claim-failure-backlog", "backlog-marker-東京")
    journey = (http, relay, registry, service, desktop, None, workers)
    if fault != "ack-response":
        assert len(desktop.owners) == 1
        now[0] += timedelta(seconds=RELAY_CLAIM_LEASE_SECONDS - 0.001)
        recover(journey)
        assert len(desktop.owners) == 1  # Active claim is excluded, even after restart.
        now[0] += timedelta(seconds=0.001)
        recover(journey)  # Exactly at lease expiry, not only after it.
    else:
        recover(journey)
    for message_id in ("claim-failure-original", "claim-failure-backlog"):
        result = http.get(f"/relay/messages/{message_id}", params=sender_scope)
        assert result.status_code == 200, result.text
        delivery = result.json()["deliveries"][0]
        assert delivery["state"] == "delivered"
        assert delivery["attempts"] == (2 if message_id.endswith("original") and fault != "ack-response" else 1)
    assert registry.reservations() == ()
    output = capsys.readouterr().out
    assert "original-marker-東京" in output and "backlog-marker-東京" in output
    if restart:
        http.close()


@pytest.mark.parametrize("moved", [False, True])
def test_expired_claim_survives_repeated_lost_notifications_and_scope_move(
    http_wake, monkeypatch, tmp_path, capsys, moved,
):
    http, relay, registry, service, desktop, send, workers = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]
    _freeze_clock(monkeypatch, now)
    sender_scope = dict(SCOPE)
    first = send()  # Native submission is simulated; no payload hook runs yet.
    claim = http.post("/relay/turn", json={
        "runtime": "codex", "session_ref": TARGET, **SCOPE,
    })
    assert claim.status_code == 200, claim.text
    assert claim.json()["deliveries"][0]["delivery_id"] == first["delivery_id"]
    response = http.post("/relay/messages", json={
        "sender_runtime": "claude-code", "sender_session_ref": "sender",
        "recipient": first["recipient_endpoint_id"], "message_id": "expired-claim-backlog",
        "payload": "later-payload-東京", **sender_scope,
    })
    assert response.status_code == 200, response.text
    if moved:
        session = claim.json()["session"]
        response = http.post("/relay/turn", json={
            "runtime": "codex", "session_ref": TARGET, "max_chars": 1,
            "previous_container_ref": SCOPE["container_ref"],
            "previous_endpoint_id": first["recipient_endpoint_id"],
            "previous_scope_generation": session["scope_generation"],
            "container_ref": "git:example.test/expired-move-東京",
        })
        assert response.status_code == 200, response.text
        assert response.json()["deliveries"] == []
        monkeypatch.setitem(SCOPE, "container_ref", "git:example.test/expired-move-東京")

    restarted = CodexWakeRegistry(relay_service=relay)
    restarted.retained_service = service
    journey = (http, relay, restarted, service, desktop, send, workers)
    for missed in range(3):
        stale = restarted.snapshot(first["recipient_endpoint_id"])
        now[0] += timedelta(seconds=59)
        recover(journey)
        assert len(desktop.owners) == missed + 1
        now[0] += timedelta(seconds=1)
        recover(journey)
        current = restarted.snapshot(first["recipient_endpoint_id"])
        assert current.generation > stale.generation
        assert current.container_ref == SCOPE["container_ref"]
        assert len(desktop.owners) == missed + 2
        assert restarted.retry_target(stale) is None
        assert restarted.rearm_for_retry(stale, session_ref=TARGET, **SCOPE) is None
        assert registry.begin_native_attempt(stale) is None
    events = []
    run_hook = _hook_runner(http, monkeypatch, "notLoaded", events, tmp_path)
    desktop.on_owner = lambda request: run_hook(request["params"]["arguments"]["prompt"])
    now[0] += timedelta(seconds=60)
    recover(journey)
    assert len(desktop.owners) == 5
    assert [event[0] for event in events] == ["emit", "ack"]
    assert "private-payload-東京" in events[0][2] and "later-payload-東京" in events[0][2]
    for message_id in ("retained-journey", "expired-claim-backlog"):
        result = http.get(f"/relay/messages/{message_id}", params=sender_scope)
        assert result.status_code == 200, result.text
        assert result.json()["deliveries"][0]["state"] == "delivered"
    assert restarted.reservations() == ()
    capsys.readouterr()


def test_expired_claim_clock_rollback_clamps_without_replaying_active_lease(
    http_wake, monkeypatch,
):
    http, relay, registry, _, desktop, send, _ = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]
    _freeze_clock(monkeypatch, now)
    first = send()
    claim = http.post("/relay/turn", json={
        "runtime": "codex", "session_ref": TARGET, **SCOPE,
    })
    assert claim.status_code == 200, claim.text
    now[0] += timedelta(seconds=60)
    recover(http_wake)
    current = registry.snapshot(first["recipient_endpoint_id"])
    assert len(desktop.owners) == 2
    # A backward step crossing the claim lease makes it active again: no retry/clamp.
    now[0] -= timedelta(seconds=180)
    recover(http_wake)
    assert registry.snapshot(first["recipient_endpoint_id"]) == current
    assert len(desktop.owners) == 2
    # Retrying far later and stepping back while remaining past the lease must clamp.
    now[0] += timedelta(seconds=600)
    recover(http_wake)
    now[0] -= timedelta(seconds=180)
    recover(http_wake)
    clamped = registry.snapshot(first["recipient_endpoint_id"])
    assert clamped.retry_not_before == now[0].timestamp() + 60
    recover(http_wake)
    assert registry.snapshot(first["recipient_endpoint_id"]) == clamped
    assert len(desktop.owners) == 3
    now[0] += timedelta(seconds=60)
    recover(http_wake)
    assert len(desktop.owners) == 4


@pytest.mark.parametrize("change", ["working", "unknown", "closed", "claim", "acked", "unresolved"])
def test_expired_claim_retry_still_obeys_target_claim_ack_and_custody_guards(
    http_wake, monkeypatch, change,
):
    http, relay, registry, service, desktop, send, _ = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]
    _freeze_clock(monkeypatch, now)
    first = send()
    claim = http.post("/relay/turn", json={
        "runtime": "codex", "session_ref": TARGET, **SCOPE,
    })
    assert claim.status_code == 200, claim.text
    initial = registry.snapshot(first["recipient_endpoint_id"])
    now[0] += timedelta(seconds=60)
    if change in {"working", "unknown"}:
        desktop.state = change
    elif change == "closed":
        response = http.post("/relay/sessions/close", json={
            "runtime": "codex", "session_ref": TARGET, **SCOPE,
        })
        assert response.status_code == 200, response.text
    elif change == "unresolved":
        desktop.unresolved = True
    else:
        def competing_hook():
            desktop.on_state = None
            response = http.post("/relay/turn", json={
                "runtime": "codex", "session_ref": TARGET, **SCOPE,
            })
            assert response.status_code == 200, response.text
            delivery = response.json()["deliveries"][0]
            assert delivery["attempts"] == 2
            if change == "acked":
                response = http.post("/relay/deliveries/ack", json={
                    "delivery_id": delivery["delivery_id"],
                    "claim_token": delivery["claim_token"], **SCOPE,
                })
                assert response.status_code == 200, response.text
        desktop.on_state = competing_hook
    recover(http_wake)
    assert len(desktop.owners) == 1
    if change == "acked":
        assert registry.reservations() == ()
    else:
        assert registry.snapshot(first["recipient_endpoint_id"]) == initial
    if change == "unresolved":
        assert service.retained_registration is None
    observed = http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"][0]
    assert observed["state"] == ("delivered" if change == "acked" else "claimed")


def test_concurrent_expired_claim_recovery_spends_one_new_generation(http_wake, monkeypatch):
    http, _, registry, _, desktop, send, _ = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]
    _freeze_clock(monkeypatch, now)
    first = send()
    response = http.post("/relay/turn", json={
        "runtime": "codex", "session_ref": TARGET, **SCOPE,
    })
    assert response.status_code == 200, response.text
    initial = registry.snapshot(first["recipient_endpoint_id"])
    now[0] += timedelta(seconds=60)
    barrier, errors = threading.Barrier(3), []
    def sweep():
        barrier.wait(timeout=2)
        try:
            recover(http_wake)
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=sweep) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=2)
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()
    assert errors == []
    assert len(desktop.owners) == 2
    assert registry.snapshot(first["recipient_endpoint_id"]).generation > initial.generation
