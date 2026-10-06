from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from core.codex_wake import CodexWakeRegistry
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
