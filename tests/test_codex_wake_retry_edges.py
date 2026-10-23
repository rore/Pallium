from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import sys
import threading

import pytest

from core.codex_wake import CodexWakeRegistry, WAKE_RETRY_COOLDOWN_SECONDS
from core.relay import RELAY_CLAIM_LEASE_SECONDS
from tests.test_codex_retained_wake import (
    SCOPE, TARGET, _hook_runner, http_wake, recover, retained as retained_fixture,
    _observe_transition_attempts, _single_typed_transition_refusal,
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


def _observe_relay_busy_acquisition(provider, monkeypatch, request, tmp_path):
    import json
    import time
    from collections import deque
    from contextlib import contextmanager
    from itertools import count
    from pathlib import Path
    from sqlalchemy import event

    events, context_ids, begin_ids = deque(maxlen=128), count(1), count(1)
    local, buffer_lock = threading.local(), threading.Lock()
    total, closed = 0, False
    original_outer = provider._begin_relay_immediate
    original_inner = provider._begin_immediate_for

    def record(phase, **values):
        nonlocal total
        row = {"phase": phase, "thread": threading.get_ident(),
               "at": time.perf_counter(), **values}
        # Only diagnostic-buffer access uses this lock; delegates run outside it.
        with buffer_lock:
            if not closed:
                total += 1
                events.append(row)

    @contextmanager
    def observe(delegate, phase, *args, **kwargs):
        previous = getattr(local, "context_id", None)
        if phase == "relay":
            local.context_id = next(context_ids)
            local.last_begin_id = None
        context_id = getattr(local, "context_id", None)
        if context_id is None:
            with delegate(*args, **kwargs) as db:
                yield db
            return
        record(phase + "_entered", context=context_id)
        try:
            with delegate(*args, **kwargs) as db:
                record(phase + "_acquired", context=context_id)
                try:
                    yield db
                finally:
                    record(phase + "_body_finished", context=context_id)
        except BaseException as exc:
            origins, cause, native, seen = [], exc, [], set()
            tb = exc.__traceback__
            while tb is not None:
                if Path(tb.tb_frame.f_code.co_filename).name == "sqlite_queue.py":
                    origins.append({"function": tb.tb_frame.f_code.co_name, "line": tb.tb_lineno})
                tb = tb.tb_next
            while cause is not None and id(cause) not in seen:
                seen.add(id(cause))
                original = getattr(cause, "orig", cause)
                if getattr(original, "sqlite_errorcode", None) is not None:
                    native.append({"code": original.sqlite_errorcode,
                                   "name": getattr(original, "sqlite_errorname", None)})
                cause = cause.__cause__ or cause.__context__
            record(phase + "_error", context=context_id, last_begin=getattr(local, "last_begin_id", None),
                   error_type=type(exc).__name__, origins=origins, native=native)
            raise
        finally:
            record(phase + "_settled", context=context_id)
            if phase == "relay":
                local.context_id = previous

    def before_begin(conn, cursor, statement, parameters, context, many):
        if closed:
            return
        context_id = getattr(local, "context_id", None)
        if context_id is not None and statement.strip().upper() == "BEGIN IMMEDIATE":
            local.last_begin_id = next(begin_ids)
            record("begin_entered", context=context_id, begin=local.last_begin_id)

    def after_begin(conn, cursor, statement, parameters, context, many):
        if closed:
            return
        context_id = getattr(local, "context_id", None)
        if context_id is not None and statement.strip().upper() == "BEGIN IMMEDIATE":
            record("begin_returned", context=context_id, begin=local.last_begin_id)

    event.listen(provider._relay_engine, "before_cursor_execute", before_begin)
    event.listen(provider._relay_engine, "after_cursor_execute", after_begin)
    monkeypatch.setattr(provider, "_begin_relay_immediate",
                        lambda *args, **kwargs: observe(original_outer, "relay", *args, **kwargs))
    monkeypatch.setattr(provider, "_begin_immediate_for",
                        lambda *args, **kwargs: observe(original_inner, "native_and_setup", *args, **kwargs))

    def finish():
        nonlocal closed
        # Fixture-owned workers may still dispatch; leave callbacks inert until disposal.
        with buffer_lock:
            closed = True
            metadata = json.dumps({"events": list(events), "dropped": max(0, total - len(events)),
                                   "qualification": "Observer-inclusive, including callback work before the post-BEGIN deadline check."})
        try:
            (tmp_path / "busy-acquisition.json").write_text(metadata, encoding="utf-8")
        finally:
            print("relay busy acquisition: " + metadata, file=sys.stderr)

    request.addfinalizer(finish)


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


def test_due_retry_reads_moved_scope_and_hook_acks_same_delivery(
    http_wake, monkeypatch, tmp_path, force_refusal=False, force_target_refusal=False,
):
    assert not (force_refusal and force_target_refusal)
    http, relay, registry, _, desktop, send, _ = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]
    _freeze_clock(monkeypatch, now)
    delivery = send()
    original_scope = SCOPE["container_ref"]
    initial = registry.snapshot(delivery["recipient_endpoint_id"])
    assert initial is not None and initial.outcome == "uncertain"
    assert len(desktop.owners) == 1
    now[0] += timedelta(seconds=61)
    moved_scope = {"container_ref": "git:example.test/retry-current-scope"}
    moved = http.post("/relay/turn", json={
        "runtime": "codex", "session_ref": TARGET, "max_chars": 1,
        "max_messages": 1, "previous_container_ref": SCOPE["container_ref"],
        "previous_endpoint_id": delivery["recipient_endpoint_id"],
        "previous_scope_generation": 0, **moved_scope,
    })
    assert moved.status_code == 200 and moved.json()["deliveries"] == []
    targets = _observe_transition_attempts(
        http_wake, monkeypatch, "retry_target", force_refusal=force_target_refusal,
    )
    attempts = _observe_transition_attempts(
        http_wake, monkeypatch, "retry", force_refusal=force_refusal,
    )
    native_before = (len(desktop.writes), len(desktop.owners))
    recover(http_wake)
    assert len(targets) == 1
    target_refused = (_single_typed_transition_refusal(targets)
                      and targets[0].get("acquisition_stage") == "late_begin")
    assert not force_target_refusal or (target_refused and targets[0].get("forced") is True)
    if target_refused:
        assert attempts == []
        assert (len(desktop.writes), len(desktop.owners)) == native_before
    else:
        assert "error_type" not in targets[0]
        assert isinstance(targets[0].get("result"), dict)
        assert targets[0]["result"]["session_ref"] == TARGET
        assert targets[0]["result"]["container_ref"] == moved_scope["container_ref"]
    assert not force_refusal or (attempts and attempts[0].get("forced") is True)
    if target_refused or _single_typed_transition_refusal(attempts):
        refused = targets[0] if target_refused else attempts[0]
        assert refused["reservation"] == initial
        assert registry.snapshot(initial.recipient_endpoint_id) == initial
        assert initial.container_ref == SCOPE["container_ref"]
        assert len(desktop.owners) == 1
        response = http.get("/relay/messages/retained-journey", params={"container_ref": original_scope})
        assert response.status_code == 200, response.text
        pending = response.json()["deliveries"][0]
        assert pending["delivery_id"] == delivery["delivery_id"]
        assert pending["state"] == "pending" and pending["attempts"] == 0
        recover(http_wake)
        if target_refused:
            assert len(targets) == 2 and "error_type" not in targets[1]
            assert isinstance(targets[1].get("result"), dict)
            assert targets[1]["result"]["session_ref"] == TARGET
            assert targets[1]["result"]["container_ref"] == moved_scope["container_ref"]
            assert len(attempts) == 1 and "error_type" not in attempts[0]
            assert isinstance(attempts[0].get("result"), type(initial))
    else:
        assert len(attempts) == 1 and "error_type" not in attempts[0]
        assert isinstance(attempts[0].get("result"), type(initial))
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
    assert not any(event[0] == "ack" or event[0] == "emit" and "private-payload-東京" in event[2]
                   for event in events)
    pending = http.get("/relay/messages/retained-journey", params={"container_ref": original_scope})
    assert pending.status_code == 200
    assert pending.json()["deliveries"][0]["state"] == "pending"
    assert pending.json()["deliveries"][0]["attempts"] == 0

    returned = http.post("/relay/turn", json={
        "runtime": "codex", "session_ref": TARGET, "container_ref": original_scope,
        "previous_container_ref": moved_scope["container_ref"],
        "previous_endpoint_id": moved.json()["session"]["endpoint_id"],
        "previous_scope_generation": moved.json()["session"]["scope_generation"],
        "max_chars": 1, "max_messages": 1,
    })
    assert returned.status_code == 200 and returned.json()["deliveries"] == []
    assert returned.json()["session"]["endpoint_id"] == delivery["recipient_endpoint_id"]
    monkeypatch.setitem(SCOPE, "container_ref", original_scope)
    events.clear()
    run_hook()
    assert [event for event in events if event[0] == "ack"] == [("ack",)]
    assert sum(event[0] == "emit" and "private-payload-東京" in event[2] for event in events) == 1
    current = http.get("/relay/messages/retained-journey", params={"container_ref": original_scope})
    assert current.status_code == 200
    assert current.json()["deliveries"][0]["state"] == "delivered"
    assert current.json()["deliveries"][0]["attempts"] == 1
    events.clear()
    run_hook()
    assert not any(event[0] == "ack" or event[0] == "emit" and "private-payload-東京" in event[2]
                   for event in events)


def test_due_retry_refusal_preserves_authority_then_hook_acks_moved_delivery(
    http_wake, monkeypatch, tmp_path,
):
    test_due_retry_reads_moved_scope_and_hook_acks_same_delivery(
        http_wake, monkeypatch, tmp_path, force_refusal=True,
    )


def test_due_retry_target_refusal_preserves_authority_then_hook_acks_moved_delivery(
    http_wake, monkeypatch, tmp_path,
):
    test_due_retry_reads_moved_scope_and_hook_acks_same_delivery(
        http_wake, monkeypatch, tmp_path, force_target_refusal=True,
    )


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
    client, http_wake, monkeypatch, tmp_path, capsys, fault, moved, restart, request,
    *, force_backlog_refusal=False, force_retry_refusal=False,
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from app.dependencies import build_router
    from storage.sqlite_schema import (
        RelayDeliveryRecord, RelayCodexWakeStateRecord, RelayCodexWakeReservationRecord,
    )

    assert not force_retry_refusal or (moved and restart and fault == "claim-response")
    test_request = request
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
    owner_finished = threading.Event()

    def on_owner(request):
        try:
            run_hook(request["params"]["arguments"]["prompt"])
        finally:
            owner_finished.set()

    desktop.on_owner = on_owner

    def send(message_id, payload, *, retry_busy=False):
        from contextlib import contextmanager
        import json
        import time
        from sqlalchemy import select
        from core.errors import ImmediateTransactionBusyError
        from storage.sqlite_schema import (
            RelayMessageRecord, RelayDeliveryRecord, RelaySessionRecord,
            RelaySessionWorkRefRecord, RelayEndpointGenerationRecord,
            RelayCodexWakeStateRecord, RelayCodexWakeReservationRecord,
        )

        body = {
            "sender_runtime": "claude-code", "sender_session_ref": "sender",
            "recipient": target["endpoint_id"], "message_id": message_id,
            "payload": payload, **sender_scope,
        }
        try:
            if not retry_busy:
                response = http.post("/relay/messages", json=body)
            else:
                storage = relay._store
                begin, original_send = storage._begin_relay_immediate, storage.relay_send
                local, attempts = threading.local(), []

                def authority():
                    values = []
                    with storage._relay_engine.connect() as db:
                        assert db.execute(select(RelayMessageRecord.id).where(RelayMessageRecord.id == message_id)).first() is None
                        assert db.execute(select(RelayDeliveryRecord.id).where(RelayDeliveryRecord.message_id == message_id)).first() is None
                        original = db.execute(select(
                            RelayDeliveryRecord.state, RelayDeliveryRecord.attempts,
                            RelayDeliveryRecord.lease_expires_at,
                        ).where(RelayDeliveryRecord.id == first["delivery_id"])).one()
                        assert original.state == ("delivered" if fault == "ack-response" else "claimed")
                        assert original.attempts == 1
                        if fault != "ack-response":
                            lease = original.lease_expires_at
                            lease = lease if lease.tzinfo else lease.replace(tzinfo=timezone.utc)
                            assert lease > now[0]
                        for model in (RelayMessageRecord, RelayDeliveryRecord, RelaySessionRecord,
                                      RelaySessionWorkRefRecord, RelayEndpointGenerationRecord,
                                      RelayCodexWakeStateRecord, RelayCodexWakeReservationRecord):
                            columns = [column for column in model.__table__.columns
                                       if column.name not in {"trace_version", "trace_truncated", "trace_pruned"}]
                            values.append(tuple(db.execute(select(*columns).order_by(*model.__table__.primary_key.columns)).all()))
                    return (tuple(values), registry.reservations(), now[0],
                            json.dumps(desktop.owners, sort_keys=True), tuple(id(worker) for worker in workers),
                            json.dumps(events, sort_keys=True))

                def observe_send(*args, **kwargs):
                    previous = getattr(local, "active", False)
                    local.active = kwargs.get("message_id") == message_id
                    try:
                        return original_send(*args, **kwargs)
                    finally:
                        local.active = previous

                @contextmanager
                def observe_begin():
                    if not getattr(local, "active", False):
                        with begin() as db:
                            yield db
                        return
                    attempt = {"acquired": False}
                    attempts.append(attempt)
                    try:
                        if force_backlog_refusal and len(attempts) == 1:
                            attempt["forced"] = True
                            raise ImmediateTransactionBusyError("controlled backlog refusal", acquisition_stage="late_begin")
                        with begin() as db:
                            attempt["acquired"] = True
                            yield db
                    except BaseException as error:
                        attempt["error"] = error
                        raise

                before = authority()
                with monkeypatch.context() as admission:
                    admission.setattr(storage, "relay_send", observe_send)
                    admission.setattr(storage, "_begin_relay_immediate", observe_begin)
                    deadline = time.monotonic() + 5
                    response = http.post("/relay/messages", json=body)
                    expected_attempts = 1
                    if response.status_code == 503:
                        assert len(attempts) == 1 and attempts[0]["acquired"] is False
                        assert type(attempts[0].get("error")) is ImmediateTransactionBusyError
                        assert response.json() == {"detail": {"code": "relay_busy", "retryable": True}}
                        assert authority() == before
                        delay = response.headers.get("Retry-After", "")
                        assert delay.isascii() and delay.isdecimal()
                        assert 0 < int(delay) < deadline - time.monotonic()
                        time.sleep(int(delay))
                        assert time.monotonic() < deadline
                        assert authority() == before
                        response = http.post("/relay/messages", json=body)
                        expected_attempts = 2
                    assert len(attempts) == expected_attempts
                    assert attempts[-1]["acquired"] is True and "error" not in attempts[-1]
                    assert not force_backlog_refusal or attempts[0].get("forced") is True
            assert response.status_code == 200, response.text
            if message_id == "claim-failure-original":
                for worker in workers:
                    worker.join(5)
                    assert not worker.is_alive()
                recover(http_wake)  # Model the omitted production sweep after initial settlement.
                # Synchronize real hook work before checking worker settlement below.
                assert owner_finished.wait(5), "first owner hook did not finish"
            for worker in workers:
                worker.join(2)
                assert not worker.is_alive()
            return response.json()["deliveries"][0]
        finally:
            for worker in workers:
                worker.join()

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
        if moved and fault == "ack-response":
            assert relay._store is client.app.state.pallium_service._storage
            _observe_relay_busy_acquisition(relay._store, monkeypatch, test_request, tmp_path)
    try:
        send("claim-failure-backlog", "backlog-marker-東京", retry_busy=True)
        journey = (http, relay, registry, service, desktop, None, workers)
        if fault != "ack-response":
            assert len(desktop.owners) == 1
            now[0] += timedelta(seconds=RELAY_CLAIM_LEASE_SECONDS - 0.001)
            recover(journey)
            assert len(desktop.owners) == 1  # Active claim is excluded, even after restart.
            now[0] += timedelta(seconds=0.001)

            def authority():
                with relay._store._relay_engine.connect() as db:
                    return tuple(tuple(db.execute(select(*[
                        column for column in model.__table__.columns
                        if column.name not in {"trace_version", "trace_truncated", "trace_pruned"}
                    ]).order_by(*model.__table__.primary_key.columns)).all()) for model in (
                        RelayCodexWakeStateRecord, RelayCodexWakeReservationRecord, RelayDeliveryRecord,
                    ))

            def deliveries():
                result = []
                for message_id in ("claim-failure-original", "claim-failure-backlog"):
                    response = http.get(f"/relay/messages/{message_id}", params=sender_scope)
                    assert response.status_code == 200, response.text
                    delivery, = response.json()["deliveries"]
                    result.append(delivery)
                return result

            before = authority()
            fence = registry.snapshot(first["recipient_endpoint_id"])
            assert fence is not None and fence.delivery_id == first["delivery_id"]
            before_deliveries = deliveries()
            assert before_deliveries[0]["delivery_id"] == first["delivery_id"]
            assert [(row["state"], row["attempts"]) for row in before_deliveries] == [("claimed", 1), ("pending", 0)]
            native_before = len(desktop.writes)
            owners_before, events_before = tuple(desktop.owners), tuple(events)
            attempts = _observe_transition_attempts(
                journey, monkeypatch, "retry", force_refusal=force_retry_refusal,
            )
            from app import dependencies as wake_dependencies

            reconcile = wake_dependencies.reconcile_codex_relay_wake_reservations
            phase_refusals = []

            def settled_original_reconcile(actual_relay, **kwargs):
                if actual_relay is not relay or kwargs.get("registry") is not registry:
                    return reconcile(actual_relay, **kwargs)
                assert kwargs.get("reservations") == (fence,) and not phase_refusals
                previous_workers = len(workers)
                result = reconcile(actual_relay, **kwargs)
                phase_workers = workers[previous_workers:]
                assert len(phase_workers) == 1, attempts
                for worker in phase_workers:
                    worker.join(5)
                    assert not worker.is_alive(), attempts
                assert len(attempts) == 1 and attempts[0]["reservation"] == fence, attempts
                refused = (_single_typed_transition_refusal(attempts)
                           and attempts[0].get("acquisition_stage") == "late_begin")
                assert not force_retry_refusal or (refused and attempts[0].get("forced") is True), attempts
                if refused:
                    assert authority() == before and registry.snapshot(first["recipient_endpoint_id"]) == fence, attempts
                    assert deliveries() == before_deliveries, attempts
                    assert tuple(desktop.owners) == owners_before and tuple(events) == events_before, attempts
                    assert all(row["method"] == "tools/list" or (
                        row["method"] == "tools/call" and row["params"]["tool"] == "read_thread"
                    ) for row in desktop.writes[native_before:]), attempts
                else:
                    assert "error_type" not in attempts[0], attempts
                phase_refusals.append(refused)
                return result

            # Observe settled refusal before a coalesced backlog can legitimately rearm.
            with monkeypatch.context() as phase:
                phase.setattr(wake_dependencies, "reconcile_codex_relay_wake_reservations", settled_original_reconcile)
                recover(journey)  # Exactly at lease expiry; candidate enumeration stays real.
            assert wake_dependencies.reconcile_codex_relay_wake_reservations is reconcile
            assert len(phase_refusals) == 1, attempts
            refused, = phase_refusals
            later_sweep = refused and len(attempts) == 1
            if later_sweep:
                candidate = relay.pending_candidate(
                    runtime="codex", session_ref=TARGET, container_ref=SCOPE["container_ref"],
                    delivery_id=first["delivery_id"],
                )
                assert candidate == {
                    "delivery_id": first["delivery_id"], "recipient_endpoint_id": first["recipient_endpoint_id"],
                    "state": "pending",
                }, attempts
                recover(journey)
            assert len(attempts) == (2 if refused else 1), attempts
            assert all(attempt["reservation"] == fence for attempt in attempts), attempts
            assert "error_type" not in attempts[-1], attempts
            replacement = attempts[-1].get("result")
            assert isinstance(replacement, type(fence)) and replacement.generation > fence.generation, attempts
            assert (replacement.delivery_id, replacement.recipient_endpoint_id,
                    replacement.session_ref, replacement.container_ref) == (
                first["delivery_id"], first["recipient_endpoint_id"], TARGET, SCOPE["container_ref"],
            ), attempts
            added_owners = desktop.owners[len(owners_before):]
            assert len(added_owners) == 1, attempts
            assert added_owners[0]["params"]["arguments"]["threadId"] == TARGET, attempts
            assert first["delivery_id"] in added_owners[0]["params"]["arguments"]["prompt"], attempts
            assert tuple(events[:len(events_before)]) == events_before, attempts
            assert [event[0] for event in events[len(events_before):]] == ["emit", "ack"], attempts
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
        if fault != "ack-response":
            (tmp_path / "retry-refusal-boundary.json").write_text(json.dumps({
                "nodeid": test_request.node.nodeid, "fault": fault, "moved": moved, "restart": restart,
                "forced_refusal_requested": force_retry_refusal,
                "refusal_observed": refused, "later_sweep": later_sweep,
                "attempts": [{key: repr(value) for key, value in attempt.items()} for attempt in attempts],
                "boundary_safety_passed": True, "wrapper_restored": True,
                "native_owners_added": len(added_owners), "final_delivery_ack_checks_passed": True,
            }, indent=2), encoding="utf-8")
    finally:
        for worker in workers:
            worker.join()
        if restart:
            http.close()


def test_unloaded_backlog_precommit_refusal_preserves_claim_and_recovery(
    client, http_wake, monkeypatch, tmp_path, capsys, request,
):
    test_unloaded_hook_claim_failure_recovers_original_and_backlog(
        client, http_wake, monkeypatch, tmp_path, capsys,
        "ack-before-commit", True, True, request, force_backlog_refusal=True,
    )


def test_unloaded_expired_retry_refusal_preserves_claim_and_recovers_backlog(
    client, http_wake, monkeypatch, tmp_path, capsys, request,
):
    test_unloaded_hook_claim_failure_recovers_original_and_backlog(
        client, http_wake, monkeypatch, tmp_path, capsys,
        "claim-response", True, True, request, force_retry_refusal=True,
    )


@pytest.mark.parametrize("moved", [False, True])
def test_expired_claim_survives_repeated_lost_notifications_and_scope_move(
    http_wake, monkeypatch, tmp_path, capsys, moved, request,
):
    http, relay, registry, service, desktop, send, workers = http_wake
    _observe_relay_busy_acquisition(relay._store, monkeypatch, request, tmp_path)
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
    http_wake, monkeypatch, change, *, force_initial_refusal=False,
):
    http, relay, registry, service, desktop, send, _ = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]
    _freeze_clock(monkeypatch, now)
    with monkeypatch.context() as setup_patch:
        attempts = _observe_transition_attempts(
            http_wake, setup_patch, "begin_native_attempt", force_refusal=force_initial_refusal,
        )
        releases = _observe_transition_attempts(http_wake, setup_patch, "release")
        first = send()
        assert not force_initial_refusal or attempts[0].get("forced") is True
        if _single_typed_transition_refusal(attempts):
            prepared = attempts[0]["reservation"]
            assert prepared.outcome == "prepared"
            assert len(releases) == 1 and releases[0]["reservations"] == (prepared,)
            assert "error_type" not in releases[0] and releases[0].get("result") == (prepared,)
            assert relay.codex_wake_snapshot() == (True, ())
            assert prepared.delivery_id == first["delivery_id"] and desktop.owners == []
            pending, = http.get("/relay/messages/retained-journey", params=SCOPE).json()["deliveries"]
            assert pending["state"] == "pending" and pending["attempts"] == 0
            recover(http_wake)
            assert len(attempts) == 2 and attempts[1]["reservation"] == replace(
                prepared, generation=prepared.generation + 1,
            )
        else:
            assert len(attempts) == 1 and "error_type" not in attempts[0]
            assert releases == []
        assert "error_type" not in attempts[-1]
        uncertain = replace(attempts[-1]["reservation"], outcome="uncertain",
                            retry_not_before=now[0].timestamp() + WAKE_RETRY_COOLDOWN_SECONDS)
        assert attempts[-1].get("result") == uncertain
        assert len(desktop.owners) == 1
        assert registry.snapshot(first["recipient_endpoint_id"]) == uncertain
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


def test_expired_claim_guards_recover_initial_native_refusal(http_wake, monkeypatch):
    test_expired_claim_retry_still_obeys_target_claim_ack_and_custody_guards(
        http_wake, monkeypatch, "closed", force_initial_refusal=True,
    )


def test_concurrent_expired_claim_recovery_spends_one_new_generation(http_wake, monkeypatch):
    import traceback
    from itertools import count
    from types import SimpleNamespace
    from storage import sqlite_queue
    from tests import test_codex_retained_wake as wake_fixture

    http, _, registry, _, desktop, send, workers = http_wake
    now = [datetime(2030, 9, 5, tzinfo=timezone.utc)]
    _freeze_clock(monkeypatch, now)
    first = send()
    assert len(desktop.owners) == 1
    initial = registry.snapshot(first["recipient_endpoint_id"])
    assert initial is not None and initial.delivery_id == first["delivery_id"]
    assert initial.outcome == "uncertain"
    # This claim prepares the concurrency journey; native deadline coverage is separate.
    native_queue_time = sqlite_queue.time
    with monkeypatch.context() as claim_patch:
        claim_time = SimpleNamespace(**vars(native_queue_time))
        claim_time.monotonic = count(step=0.001).__next__
        claim_patch.setattr(sqlite_queue, "time", claim_time)
        response = http.post("/relay/turn", json={
            "runtime": "codex", "session_ref": TARGET, **SCOPE,
        })
    assert sqlite_queue.time is native_queue_time
    assert response.status_code == 200, response.text
    assert response.json()["deliveries"][0]["delivery_id"] == first["delivery_id"]
    assert registry.snapshot(first["recipient_endpoint_id"]) == initial
    now[0] += timedelta(seconds=60)
    barrier, errors = threading.Barrier(3), []
    phases = {}
    original_recovery = wake_fixture.recover_expired_relay_wakes

    def observed_recovery(*args, **kwargs):
        ident = threading.get_ident()
        phases[ident] = "production recovery"
        try:
            return original_recovery(*args, **kwargs)
        finally:
            phases[ident] = "native worker joins"

    monkeypatch.setattr(wake_fixture, "recover_expired_relay_wakes", observed_recovery)

    def timeout_diagnostics():
        frames = sys._current_frames()
        targets = (*threads, *tuple(workers)[-8:])
        return {
            "phases": dict(phases), "errors": [repr(error)[:256] for error in errors],
            "threads": [{
                "name": target.name, "ident": target.ident, "alive": target.is_alive(),
                "stack": traceback.format_stack(frames[target.ident], limit=12)
                if target.ident in frames else [],
            } for target in targets],
        }

    def sweep():
        phases[threading.get_ident()] = "start barrier"
        barrier.wait(timeout=2)
        try:
            recover(http_wake)
        except Exception as exc:
            errors.append(exc)
        finally:
            phases[threading.get_ident()] = "finished"
    threads = [threading.Thread(target=sweep) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        barrier.wait(timeout=2)
        for thread in threads:
            thread.join(3)
            assert not thread.is_alive(), timeout_diagnostics()
        assert errors == []
        assert len(desktop.owners) == 2
        assert registry.snapshot(first["recipient_endpoint_id"]).generation > initial.generation
    finally:
        for thread in threads:
            if thread.ident is not None:
                thread.join()
        for worker in workers:
            worker.join()
