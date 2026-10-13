from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from core.codex_wake import CodexWakeRegistry, CodexWakeReservation
from core.relay import RELAY_CLAIM_LEASE_SECONDS, RelayService
from storage.sqlite import SQLiteStorageProvider
from app import codex_wake
from app.main import create_app
from app.config import AppConfig
from storage.vector_index import VectorIndexConfig
from tests.config_helpers import DEMO_SEMANTIC_PACKAGES
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.dependencies import build_router


SCOPE = {"container_ref": "git:example.test/wake-東京"}


@pytest.mark.parametrize("generation", [None, 7])
@pytest.mark.parametrize("sql_shape", ["joined_scope", "expiry_no_returning"])
def test_http_exact_claim_avoids_redundant_writer_reads(
    relay_store, tmp_path, monkeypatch, generation, sql_shape,
):
    from sqlalchemy import event
    from app import dependencies

    relay, storage, database = relay_store
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM relay_endpoint_generations WHERE endpoint_id=?",
                   (reservation.recipient_endpoint_id,))
        if generation is not None:
            db.execute("INSERT INTO relay_endpoint_generations(endpoint_id,generation) VALUES (?,?)",
                       (reservation.recipient_endpoint_id, generation))
    statements = []
    original_router = dependencies.create_router

    def observe_sql(_connection, _cursor, statement, *_args):
        statements.append(statement)

    def observe_router(service, **kwargs):
        target = kwargs["relay_service"]
        original_turn = target.turn
        def turn(*args, **kw):
            event.listen(storage._relay_engine, "before_cursor_execute", observe_sql)
            try:
                return original_turn(*args, **kw)
            finally:
                event.remove(storage._relay_engine, "before_cursor_execute", observe_sql)
        monkeypatch.setattr(target, "turn", turn)
        return original_router(service, **kwargs)

    monkeypatch.setattr(dependencies, "create_router", observe_router)
    monkeypatch.setattr(dependencies, "current_platform", lambda: "windows")
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(), relay_storage=storage, codex_wake_registry=registry))
    with TestClient(app) as http:
        claim = http.post("/relay/turn", json={"runtime": "codex", "session_ref": "target",
            "wake_delivery_id": reservation.delivery_id, **SCOPE})
        assert claim.status_code == 200, claim.text
        session = claim.json()["session"]
        assert session["endpoint_id"] == reservation.recipient_endpoint_id
        assert session["container_ref"] == SCOPE["container_ref"]
        assert session["scope_generation"] == (generation or 0)
        delivery, = claim.json()["deliveries"]
        assert delivery["delivery_id"] == reservation.delivery_id and delivery["attempts"] == 1
        ack = http.post("/relay/deliveries/ack", json={"delivery_id": delivery["delivery_id"],
            "claim_token": delivery["claim_token"], **SCOPE})
        assert ack.status_code == 200, ack.text
        observed, = http.get(f"/relay/messages/{delivery['message_id']}", params=SCOPE).json()["deliveries"]
        assert observed["state"] == "delivered" and observed["attempts"] == 1
    if sql_shape == "joined_scope":
        lookups = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")
                   and ("FROM relay_sessions" in sql or "FROM relay_endpoint_generations" in sql)]
        assert len(lookups) == 1 and "LEFT OUTER JOIN relay_endpoint_generations" in lookups[0], lookups
    else:
        expiry, = [sql for sql in statements if sql.lstrip().startswith("UPDATE relay_deliveries")
                   and "relay_messages.expires_at" in sql]
        assert "RETURNING" not in expiry.upper(), expiry


@pytest.mark.parametrize("generation", [None, 7])
@pytest.mark.parametrize("authority_transport", ["json", "missing_array", "missing_group"])
def test_http_delivery_projection_reads_fresh_endpoint_once(
    relay_store, tmp_path, monkeypatch, generation, authority_transport,
):
    from sqlalchemy import event
    from app import dependencies

    relay, storage, database = relay_store
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    endpoint = reservation.recipient_endpoint_id
    fallback_attempts = []
    if authority_transport != "json":
        from storage import sqlite_relay
        original_envelope = sqlite_relay._wake_snapshot_envelope
        missing = "json_array" if authority_transport == "missing_array" else "json_group_array"
        class MissingJSONCursor:
            def __init__(self, cursor):
                self.cursor = cursor
            def execute(self, statement):
                if statement == sqlite_relay._WAKE_SNAPSHOT_ENVELOPE_SQL:
                    fallback_attempts.append(True)
                    raise sqlite3.OperationalError(f"no such function: {missing}")
                return self.cursor.execute(statement)
            def __getattr__(self, name):
                return getattr(self.cursor, name)
        monkeypatch.setattr(sqlite_relay, "_wake_snapshot_envelope",
            lambda cursor: original_envelope(MissingJSONCursor(cursor)))
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM relay_endpoint_generations WHERE endpoint_id=?", (endpoint,))
        if generation is not None:
            db.execute("INSERT INTO relay_endpoint_generations(endpoint_id,generation) VALUES (?,?)", (endpoint, generation))
    statements, projected, views = [], [], []
    original_router = dependencies.create_router

    def observe_sql(_connection, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    def observe_router(service, **kwargs):
        original_view = kwargs["relay_service"].session_view_by_endpoint
        def view(endpoint_id):
            result = original_view(endpoint_id)
            views.append(result)
            return result
        monkeypatch.setattr(kwargs["relay_service"], "session_view_by_endpoint", view)
        original_admission = kwargs["relay_turn_admission_callback"]
        def admission(request, result, captured):
            original_admission(request, result, captured)
            with sqlite3.connect(database) as db:
                db.execute("UPDATE relay_sessions SET container_ref=?,title=?,alias=? WHERE id=?",
                    ("git:example.test/current-東京", "Post-admission title", "fresh", endpoint))
                db.execute("DELETE FROM relay_endpoint_generations WHERE endpoint_id=?", (endpoint,))
                if generation is not None:
                    db.execute("INSERT INTO relay_endpoint_generations(endpoint_id,generation) VALUES (?,?)", (endpoint, generation))
        kwargs["relay_turn_admission_callback"] = admission
        original_factory = kwargs["relay_activation_callback_factory"]
        def factory(actual_callback):
            projector = original_factory(actual_callback)
            def project(row):
                if "recipient_endpoint_id" not in row:
                    return projector(row)
                event.listen(storage._relay_engine, "before_cursor_execute", observe_sql)
                try:
                    result = projector(row)
                    projected.append(result)
                    return result
                finally:
                    event.remove(storage._relay_engine, "before_cursor_execute", observe_sql)
            return project
        kwargs["relay_activation_callback_factory"] = factory
        return original_router(service, **kwargs)

    monkeypatch.setattr(dependencies, "create_router", observe_router)
    monkeypatch.setattr(dependencies, "current_platform", lambda: "windows")
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(), relay_storage=storage, codex_wake_registry=registry))
    with TestClient(app) as http:
        claim = http.post("/relay/turn", json={"runtime": "codex", "session_ref": "target",
            "wake_delivery_id": reservation.delivery_id, **SCOPE})
        assert claim.status_code == 200, claim.text
        assert len(fallback_attempts) == (0 if authority_transport == "json" else 2)
        delivery, = claim.json()["deliveries"]
        assert delivery["delivery_id"] == reservation.delivery_id and delivery["attempts"] == 1
        assert projected == [delivery["activation"]]
        assert len(views) == 1
        assert views[0]["container_ref"] == "git:example.test/current-東京"
        assert views[0]["title"] == "Post-admission title" and views[0]["alias"] == "fresh"
        assert views[0]["scope_generation"] == (generation or 0)
        assert delivery["activation"]["availability"] == "attempt_inflight"
        ack = http.post("/relay/deliveries/ack", json={"delivery_id": delivery["delivery_id"],
            "claim_token": delivery["claim_token"], **SCOPE})
        assert ack.status_code == 200, ack.text
        observed, = http.get(f"/relay/messages/{delivery['message_id']}", params=SCOPE).json()["deliveries"]
        assert observed["state"] == "delivered" and observed["attempts"] == 1
    assert len(statements) == 1, statements


@pytest.mark.parametrize("generation", [None, 7])
@pytest.mark.parametrize("state", ["idle", "busy", "closed", "dormant", "moved"])
def test_endpoint_view_preserves_current_session_fields_and_generation(
    relay_store, generation, state,
):
    from sqlalchemy import event

    relay, storage, database = relay_store
    endpoint = _send(relay)["recipient_endpoint_id"]
    now = datetime.now(timezone.utc)
    container = "git:example.test/moved-東京" if state == "moved" else SCOPE["container_ref"]
    seen = now - timedelta(days=2) if state == "dormant" else now
    with sqlite3.connect(database) as db:
        db.execute("UPDATE relay_sessions SET container_ref=?,title=?,alias=?,state=?,last_seen_at=?,closed_at=? WHERE id=?",
            (container, "Fresh title 東京", "current", "closed" if state == "closed" else "busy" if state == "busy" else "idle",
             seen.strftime("%Y-%m-%d %H:%M:%S.%f"), now.strftime("%Y-%m-%d %H:%M:%S.%f") if state == "closed" else None, endpoint))
        db.execute("DELETE FROM relay_endpoint_generations WHERE endpoint_id=?", (endpoint,))
        if generation is not None:
            db.execute("INSERT INTO relay_endpoint_generations(endpoint_id,generation) VALUES (?,?)", (endpoint, generation))
    expected, = relay.list_sessions(runtime="codex", session_ref="target", container_ref=container,
        include_inactive=True, now=now)
    statements = []
    def observe_sql(_connection, _cursor, statement, *_args):
        statements.append(statement)
    event.listen(storage._relay_engine, "before_cursor_execute", observe_sql)
    try:
        current = relay.session_view_by_endpoint(endpoint, now=now)
    finally:
        event.remove(storage._relay_engine, "before_cursor_execute", observe_sql)
    assert current == expected
    assert current["scope_generation"] == (generation or 0)
    assert len(statements) == 1 and "LEFT OUTER JOIN" in statements[0]
    assert "relay_messages" not in statements[0]
    assert relay.session_scope_by_endpoint(endpoint) == {
        "runtime": "codex", "session_ref": "target", "container_ref": container,
    }


def test_endpoint_view_missing_endpoint_and_legacy_provider_fallback(relay_store, monkeypatch):
    from core.relay import RelayNotFoundError

    relay, storage, _ = relay_store
    endpoint = _send(relay)["recipient_endpoint_id"]
    now = datetime.now(timezone.utc)
    expected = relay.session_view_by_endpoint(endpoint, now=now)
    monkeypatch.setattr(storage, "relay_session_view_by_endpoint", None)
    assert relay.session_view_by_endpoint(endpoint, now=now) == expected
    missing = "relay-session-" + "0" * 32
    with pytest.raises(RelayNotFoundError):
        relay.session_view_by_endpoint(missing)
    with pytest.raises(ValueError):
        relay.session_view_by_endpoint("invalid")
    monkeypatch.undo()
    with pytest.raises(RelayNotFoundError):
        relay.session_view_by_endpoint(missing)


@pytest.mark.parametrize("damage", ["wrong_endpoint", "container", "session", "runtime"])
def test_endpoint_view_refuses_provider_identity_or_malformed_scope(relay_store, monkeypatch, damage):
    from core.relay import RelayNotFoundError

    relay, storage, database = relay_store
    endpoint = _send(relay)["recipient_endpoint_id"]
    if damage == "wrong_endpoint":
        current = relay.session_view_by_endpoint(endpoint)
        monkeypatch.setattr(storage, "relay_session_view_by_endpoint",
            lambda *_args, **_kwargs: {**current, "endpoint_id": "relay-session-" + "0" * 32})
    else:
        column = {"container": "container_ref", "session": "session_ref", "runtime": "runtime"}[damage]
        value = {"container": " " + SCOPE["container_ref"], "session": " target ", "runtime": "invalid"}[damage]
        with sqlite3.connect(database) as db:
            db.execute(f"UPDATE relay_sessions SET {column}=? WHERE id=?", (value, endpoint))
    with pytest.raises((ValueError, RelayNotFoundError)):
        relay.session_view_by_endpoint(endpoint)


@pytest.mark.parametrize("column,value,valid", [
    ("retry_not_before", None, True), ("retry_not_before", float("nan"), True),
    ("retry_not_before", 1.2345678901234567, True),
    ("retry_not_before", 1700000000.1234567, True), ("retry_not_before", 5e-324, True),
    ("retry_not_before", 1.7976931348623157e308, True),
    ("retry_not_before", float("inf"), False), ("retry_not_before", float("-inf"), False),
    ("retry_not_before", "invalid", False), ("retry_not_before", b"invalid", False),
    ("generation", 1.25, False), ("generation", "invalid", False),
    ("correlated_claim_attempts", 1.25, False), ("correlated_claim_attempts", "invalid", False),
    ("session_ref", "target-東京-😀", True), ("session_ref", "target\0東京", False),
    ("session_ref", b"target", False), ("outcome", b"reserved", False),
])
def test_authority_snapshot_preserves_native_types_and_exact_retry_values(relay_store, tmp_path, column, value, valid):
    from storage.sqlite_relay import _WAKE_SNAPSHOT_ROWS_SQL

    relay, _, database = relay_store
    item = CodexWakeReservation("relay-session-" + "1" * 32, "relay-delivery-" + "1" * 32,
        "target", SCOPE["container_ref"], 1)
    values = asdict(item)
    values[column] = value
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO relay_codex_wake_state(id,generation) VALUES(1,1)")
        db.execute("INSERT INTO relay_codex_wake_reservations (" + ",".join(values) + ") VALUES (" +
            ",".join("?" for _ in values) + ")", tuple(values.values()))
        raw, = db.execute(_WAKE_SNAPSHOT_ROWS_SQL).fetchall()
    expected = CodexWakeReservation(*raw)
    assert CodexWakeRegistry._valid_item(expected) is valid
    if valid:
        initialized, observed = relay.codex_wake_snapshot()
        assert initialized and observed == (expected,)
        assert type(observed[0].retry_not_before) is type(expected.retry_not_before)
    else:
        with pytest.raises((ValueError, sqlite3.OperationalError)):
            relay.codex_wake_snapshot()
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.reservations_if_usable() == ((expected,) if valid else ())
    assert registry.usable is valid


@pytest.mark.parametrize("encoded", ["{}", "[[1]]", '[[' + ','.join(['null'] * 8) + ',"unknown"]]',
    '[[' + ','.join(['null'] * 7) + ',1.25,"real"]]'])
def test_authority_aggregate_refuses_malformed_shape_or_storage_tag(encoded):
    from storage.sqlite_relay import _wake_snapshot_rows
    cursor = SimpleNamespace(execute=lambda _statement: None, fetchone=lambda: (encoded,))
    with pytest.raises(ValueError):
        _wake_snapshot_rows(cursor)


@pytest.mark.parametrize("error", ["JSON cannot hold BLOB values", "disk I/O error", "no such function: other"])
def test_authority_aggregate_does_not_fallback_on_data_or_other_sql_failure(error):
    from storage.sqlite_relay import _wake_snapshot_rows
    attempted = []
    def execute(statement):
        attempted.append(statement)
        raise sqlite3.OperationalError(error)
    with pytest.raises(sqlite3.OperationalError, match=error):
        _wake_snapshot_rows(SimpleNamespace(execute=execute))
    assert len(attempted) == 1


def test_http_ack_release_validates_current_authority_once(relay_store, tmp_path, monkeypatch):
    relay, storage, _ = relay_store
    registry = _registry(relay, tmp_path / 'legacy')
    assert registry.initialize(old_owner_drained=True)
    sent = _send(relay)
    reservation = _reserve(registry, sent)
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(), relay_storage=storage, codex_wake_registry=registry))
    snapshots, validations = [], []
    original_snapshot, original_validate = relay.codex_wake_snapshot, storage._validate_wake_authority
    armed = False
    def observe_snapshot():
        if armed:
            snapshots.append('snapshot')
        return original_snapshot()
    def observe_validate(*args, **kwargs):
        if armed:
            validations.append('validation')
        return original_validate(*args, **kwargs)
    monkeypatch.setattr(relay, 'codex_wake_snapshot', observe_snapshot)
    monkeypatch.setattr(storage, '_validate_wake_authority', observe_validate)
    with TestClient(app) as http:
        claim = http.post('/relay/turn', json={'runtime': 'codex', 'session_ref': 'target',
            'wake_delivery_id': reservation.delivery_id, **SCOPE})
        assert claim.status_code == 200, claim.text
        delivery, = claim.json()['deliveries']
        assert delivery['attempts'] == 1
        armed = True
        try:
            ack = http.post('/relay/deliveries/ack', json={'delivery_id': reservation.delivery_id,
                'claim_token': delivery['claim_token'], **SCOPE})
        finally:
            armed = False
        assert ack.status_code == 200, ack.text
        assert ack.json()['state'] == 'delivered'
        assert registry.reservations_if_usable() == ()
        readback = http.get(f'/relay/messages/{sent["message_id"]}', params=SCOPE)
        assert readback.status_code == 200, readback.text
        observed, = readback.json()['deliveries']
        assert observed['delivery_id'] == reservation.delivery_id
        assert observed['state'] == 'delivered' and observed['attempts'] == 1
        assert snapshots == [] and validations == ['validation'], (snapshots, validations)


@pytest.mark.parametrize('race', ['different_delivery', 'same_delivery', 'commit_before', 'commit_after', 'corrupt_unrelated'])
def test_http_ack_release_preserves_successor_and_commit_failure_boundaries(relay_store, tmp_path, monkeypatch, race):
    from app import dependencies
    relay, storage, database = relay_store
    registry = _registry(relay, tmp_path / 'legacy')
    assert registry.initialize(old_owner_drained=True)
    sent = _send(relay)
    reservation = _reserve(registry, sent)
    successor = relay.send(sender_runtime='codex', sender_session_ref='sender',
        recipient='codex:target', payload='A successor message', **SCOPE)['deliveries'][0] if race == 'different_delivery' else sent
    if race == 'corrupt_unrelated':
        unrelated = _reserve(registry, _send(relay, target='unrelated'), target='unrelated')
    cleared, transitions = [], []
    monkeypatch.setattr(codex_wake, '_clear_schedule', lambda item, _registry: cleared.append(item))
    monkeypatch.setattr(dependencies, 'schedule_codex_relay_wake', lambda *_args, **_kwargs: None)
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(), relay_storage=storage, codex_wake_registry=registry))
    original_transition, original_begin = relay.codex_wake_transition, storage._begin_relay_immediate
    replacement = replace(reservation, delivery_id=successor['delivery_id'], generation=reservation.generation + 1)
    @contextmanager
    def commit_fault():
        with original_begin() as db:
            yield db
            if race == 'commit_before':
                raise OperationalError('COMMIT', {}, sqlite3.OperationalError('controlled before commit'))
        if race == 'commit_after':
            raise OperationalError('COMMIT', {}, sqlite3.OperationalError('controlled after commit'))
    def race_before_transition(operation, **kwargs):
        transitions.append(operation)
        if race in {'same_delivery', 'different_delivery'}:
            values = asdict(replacement)
            with sqlite3.connect(database) as db:
                db.execute('UPDATE relay_codex_wake_state SET generation=? WHERE id=1', (replacement.generation,))
                db.execute('UPDATE relay_codex_wake_reservations SET delivery_id=?,generation=? WHERE recipient_endpoint_id=?',
                    (values['delivery_id'], values['generation'], reservation.recipient_endpoint_id))
        elif race == 'corrupt_unrelated':
            with sqlite3.connect(database) as db:
                db.execute('UPDATE relay_codex_wake_reservations SET outcome=? WHERE recipient_endpoint_id=?',
                    ('invalid', unrelated.recipient_endpoint_id))
        with monkeypatch.context() as fault:
            if race in {'commit_before', 'commit_after'}:
                fault.setattr(storage, '_begin_relay_immediate', commit_fault)
            return original_transition(operation, **kwargs)
    with TestClient(app) as http:
        claim = http.post('/relay/turn', json={'runtime':'codex', 'session_ref':'target',
            'wake_delivery_id':reservation.delivery_id, **SCOPE})
        assert claim.status_code == 200, claim.text
        delivery, = claim.json()['deliveries']
        assert delivery['attempts'] == 1
        monkeypatch.setattr(relay, 'codex_wake_transition', race_before_transition)
        ack = http.post('/relay/deliveries/ack', json={'delivery_id':reservation.delivery_id,
            'claim_token':delivery['claim_token'], **SCOPE})
        assert ack.status_code == 200, ack.text
        assert ack.json()['state'] == 'delivered'
        monkeypatch.setattr(relay, 'codex_wake_transition', original_transition)
        assert transitions == ['release_delivery']
        current = _stored_items(database)
        if race == 'different_delivery':
            assert current == {replacement} and cleared == []
        elif race == 'same_delivery':
            assert current == set() and cleared == [replacement]
        elif race == 'commit_after':
            assert current == set() and cleared == []
        else:
            assert reservation in current and cleared == []
        readback = http.get(f'/relay/messages/{sent["message_id"]}', params=SCOPE)
        assert readback.status_code == 200, readback.text
        observed, = readback.json()['deliveries']
        assert observed['delivery_id'] == reservation.delivery_id
        assert observed['state'] == 'delivered' and observed['attempts'] == 1


@pytest.mark.parametrize('state', ['claimed', 'expired_claim', 'delivered', 'read_failed'])
def test_http_committed_claim_prevents_old_guarded_native_operation(relay_store, tmp_path, monkeypatch, state):
    from app import dependencies
    relay, storage, database = relay_store
    registry = _registry(relay, tmp_path / 'legacy')
    assert registry.initialize(old_owner_drained=True)
    reservation = registry.begin_native_attempt(_reserve(registry, _send(relay)))
    assert reservation is not None
    original_router = dependencies.create_router
    def observe_router(service, **kwargs):
        kwargs['relay_ack_callback'] = None  # Witness durable ACK before queued Native cleanup.
        return original_router(service, **kwargs)
    monkeypatch.setattr(dependencies, 'create_router', observe_router)
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(), relay_storage=storage, codex_wake_registry=registry))
    with TestClient(app) as http:
        claim = http.post('/relay/turn', json={'runtime':'codex', 'session_ref':'target',
                                             'wake_delivery_id':reservation.delivery_id, **SCOPE})
        assert claim.status_code == 200, claim.text
        delivery, = claim.json()['deliveries']
        assert delivery['attempts'] == 1
        if state == 'expired_claim':
            with sqlite3.connect(database) as db:
                db.execute('UPDATE relay_deliveries SET lease_expires_at=? WHERE id=?',
                           ((datetime.now(timezone.utc)-timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S.%f'),reservation.delivery_id))
        elif state == 'delivered':
            ack = http.post('/relay/deliveries/ack', json={'delivery_id':reservation.delivery_id,
                                                         'claim_token':delivery['claim_token'], **SCOPE})
            assert ack.status_code == 200, ack.text
        elif state == 'read_failed':
            def unavailable(**_kwargs):
                raise TimeoutError('controlled state read failure')
            monkeypatch.setattr(relay, 'codex_wake_reservation_state', unavailable)
        assert registry.snapshot(reservation.recipient_endpoint_id) == reservation
        operations = []
        guarded = registry.run_if_current(reservation, lambda: operations.append('native-write'))
        assert guarded == (False, None) and operations == []
        assert registry.snapshot(reservation.recipient_endpoint_id) == reservation


def test_actual_native_closure_rechecks_claim_committed_after_state_observation(relay_store, tmp_path, monkeypatch):
    relay, storage, _ = relay_store
    registry = _registry(relay, tmp_path / 'legacy')
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(), relay_storage=storage, codex_wake_registry=registry))
    original_state = relay.codex_wake_reservation_state
    claims, writes = [], []
    monkeypatch.setattr(codex_wake, 'time', SimpleNamespace(**{**vars(codex_wake.time), 'sleep': lambda _: None}))
    monkeypatch.setattr('app.codex_bridge_pipe.retained_wake_enabled', lambda: False)
    monkeypatch.setattr(codex_wake, '_start_launch', lambda *args: writes.append(args))
    with TestClient(app) as http:
        def claim_after_observation(**kwargs):
            observed = original_state(**kwargs)
            if not claims:
                claims.append(http.post('/relay/turn', json={'runtime':'codex', 'session_ref':'target',
                    'wake_delivery_id':reservation.delivery_id, **SCOPE}))
            return observed
        monkeypatch.setattr(relay, 'codex_wake_reservation_state', claim_after_observation)
        codex_wake._wake_after_debounce(reservation, registry)
        assert len(claims) == 1 and claims[0].status_code == 200, [r.text for r in claims]
        claimed, = claims[0].json()['deliveries']
        assert claimed['delivery_id'] == reservation.delivery_id and claimed['attempts'] == 1
        assert writes == []
        assert registry.snapshot(reservation.recipient_endpoint_id) == reservation


@pytest.mark.parametrize('outcome', ['prepared', 'accepted', 'uncertain'])
def test_http_exact_claim_generation_is_the_durable_native_fence(
    relay_store, tmp_path, monkeypatch, outcome,
):
    relay, storage, database = relay_store
    registry = _registry(relay, tmp_path / 'legacy')
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    if outcome != 'prepared':
        reservation = registry.begin_native_attempt(reservation)
        assert reservation is not None
        if outcome == 'accepted':
            assert registry.record_outcome(reservation, 'accepted')
            reservation = registry.snapshot(reservation.recipient_endpoint_id)
    original_transition = storage.relay_codex_wake_transition
    correlations = []
    def observe_transition(*, operation, **kwargs):
        if operation == 'correlate':
            correlations.append(kwargs)
        return original_transition(operation=operation, **kwargs)
    monkeypatch.setattr(storage, 'relay_codex_wake_transition', observe_transition)
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(), relay_storage=storage, codex_wake_registry=registry))
    with TestClient(app) as http:
        response = http.post('/relay/turn', json={
            'runtime': 'codex', 'session_ref': 'target', 'wake_delivery_id': reservation.delivery_id, **SCOPE,
        })
        assert response.status_code == 200, response.text
        claimed, = response.json()['deliveries']
        assert claimed['delivery_id'] == reservation.delivery_id and claimed['attempts'] == 1
        with sqlite3.connect(database) as db:
            assert db.execute('SELECT codex_wake_generation, attempts FROM relay_deliveries WHERE id=?',
                              (reservation.delivery_id,)).fetchone() == (reservation.generation, 1)
        current = registry.snapshot(reservation.recipient_endpoint_id)
        assert replace(current, correlated_claim_attempts=None) == reservation
        assert current.correlated_claim_attempts is None
        assert registry.begin_native_attempt(current) is None
        # Expired claim evidence requires a new generation, never resume/spend of the old one.
        with sqlite3.connect(database) as db:
            db.execute('UPDATE relay_deliveries SET lease_expires_at=? WHERE id=?',
                       ((datetime.now(timezone.utc) - timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S.%f'), reservation.delivery_id))
        assert registry.begin_native_attempt(current) is None
        reconciled = registry.reconcile(current)
        assert reconciled is not None and reconciled[0] == 'replaced'
        replacement = reconciled[1]
        assert replacement.delivery_id == reservation.delivery_id and replacement.generation > reservation.generation
        spent = registry.begin_native_attempt(replacement)
        assert spent is not None and spent.generation == replacement.generation
        assert registry.begin_native_attempt(replacement) is None
        redelivery = http.post('/relay/turn', json={
            'runtime': 'codex', 'session_ref': 'target', 'wake_delivery_id': replacement.delivery_id, **SCOPE,
        })
        assert redelivery.status_code == 200, redelivery.text
        repeated, = redelivery.json()['deliveries']
        assert repeated['delivery_id'] == claimed['delivery_id'] and repeated['attempts'] == 2
        ack = http.post('/relay/deliveries/ack', json={
            'delivery_id': repeated['delivery_id'], 'claim_token': repeated['claim_token'], **SCOPE,
        })
        assert ack.status_code == 200, ack.text
        retained = http.get(f"/relay/messages/{claimed['message_id']}", params=SCOPE)
        assert retained.status_code == 200, retained.text
        final, = retained.json()['deliveries']
        assert (final['delivery_id'], final['state'], final['attempts']) == (claimed['delivery_id'], 'delivered', 2)
        assert correlations == [], 'built-in persistent exact claims must not duplicate committed generation authority'


@pytest.mark.parametrize('change', ['replacement', 'unrelated_corruption', 'callback_failure', 'exhausted_generation'])
def test_http_committed_generation_preserves_current_authority_boundaries(
    relay_store, tmp_path, monkeypatch, change,
):
    from app import dependencies
    relay, storage, database = relay_store
    registry = _registry(relay, tmp_path / 'legacy')
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    other = _reserve(registry, _send(relay, target='other'), target='other')
    expected = [reservation]
    callback_calls = []
    original_turn, original_router = RelayService.turn, dependencies.create_router
    def turn_after_capture(self, **kwargs):
        if kwargs.get('exact_delivery_id') == reservation.delivery_id:
            assert kwargs['codex_wake_generation'] == reservation.generation
            if change == 'replacement':
                expected[0] = registry.replace_generation(reservation, session_ref='target', container_ref=SCOPE['container_ref'])
                assert expected[0] is not None and expected[0].generation > reservation.generation
            elif change == 'unrelated_corruption':
                with sqlite3.connect(database) as db:
                    db.execute('UPDATE relay_codex_wake_reservations SET generation=0 WHERE recipient_endpoint_id=?', (other.recipient_endpoint_id,))
            elif change == 'exhausted_generation':
                with sqlite3.connect(database) as db:
                    db.execute('UPDATE relay_codex_wake_state SET generation=?', (2**63 - 1,))
        return original_turn(self, **kwargs)
    def observe_router(service, **kwargs):
        if change == 'callback_failure':
            def failed_callback(request, result, captured):
                callback_calls.append((captured, result['deliveries'][0]['delivery_id'], result['deliveries'][0]['attempts']))
                raise RuntimeError('controlled postcommit callback failure')
            kwargs['relay_turn_admission_callback'] = failed_callback
        return original_router(service, **kwargs)
    monkeypatch.setattr(RelayService, 'turn', turn_after_capture)
    monkeypatch.setattr(dependencies, 'create_router', observe_router)
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(), relay_storage=storage, codex_wake_registry=registry))
    with TestClient(app) as http:
        response = http.post('/relay/turn', json={
            'runtime': 'codex', 'session_ref': 'target', 'wake_delivery_id': reservation.delivery_id, **SCOPE,
        })
        assert response.status_code == 200, response.text
        claimed, = response.json()['deliveries']
        assert claimed['delivery_id'] == reservation.delivery_id and claimed['attempts'] == 1
        assert callback_calls == ([(reservation, reservation.delivery_id, 1)] if change == 'callback_failure' else [])
        stored = {item.recipient_endpoint_id: item for item in _stored_items(database)}
        assert stored[reservation.recipient_endpoint_id] == expected[0]
        assert stored[other.recipient_endpoint_id] == (replace(other, generation=0) if change == 'unrelated_corruption' else other)
        state = relay.codex_wake_reservation_state(delivery_id=reservation.delivery_id)
        assert state['codex_wake_generation'] == reservation.generation and state['attempts'] == 1
        assert registry.begin_native_attempt(expected[0]) is None
        if change == 'exhausted_generation':
            with sqlite3.connect(database) as db:
                db.execute('UPDATE relay_deliveries SET lease_expires_at=? WHERE id=?',
                           ((datetime.now(timezone.utc) - timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S.%f'), reservation.delivery_id))
            assert registry.reconcile(expected[0]) is None
            assert registry.begin_native_attempt(expected[0]) is None
            assert registry.snapshot(reservation.recipient_endpoint_id) == expected[0]
        retained = http.get(f"/relay/messages/{claimed['message_id']}", params=SCOPE)
        assert retained.status_code == 200, retained.text
        row, = retained.json()['deliveries']
        assert row['delivery_id'] == reservation.delivery_id and row['attempts'] == 1
        if change != 'exhausted_generation':
            ack = http.post('/relay/deliveries/ack', json={
                'delivery_id': claimed['delivery_id'], 'claim_token': claimed['claim_token'], **SCOPE,
            })
            assert ack.status_code == 200, ack.text
            final = http.get(f"/relay/messages/{claimed['message_id']}", params=SCOPE)
            assert final.status_code == 200, final.text
            assert final.json()['deliveries'][0]['state'] == 'delivered'


@pytest.mark.parametrize('phase', ['preclaim', 'projection'])
def test_http_fresh_authority_observation_does_not_wait_for_native_owner(
    relay_store, tmp_path, monkeypatch, phase,
):
    import sys
    import time
    import anyio
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor
    from app import dependencies

    arrival = deque(maxlen=32)

    def record(stage):
        arrival.append({'stage': stage, 'at': time.perf_counter(), 'thread': threading.get_ident()})

    original_run_sync = anyio.to_thread.run_sync

    async def observe_run_sync(function, *args, **kwargs):
        record('runner_submitted')
        def run(*values):
            record('worker_entered')
            try:
                return function(*values)
            finally:
                record('worker_finished')
        return await original_run_sync(run, *args, **kwargs)

    if phase == 'preclaim':
        monkeypatch.setattr(anyio.to_thread, 'run_sync', observe_run_sync)
    relay, storage, _ = relay_store
    registry = _registry(relay, tmp_path / 'legacy')
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    captured, gate_errors = [], []
    entered, observed, held, release = (threading.Event() for _ in range(4))
    original_router = dependencies.create_router

    def observe_router(service, **kwargs):
        key = 'relay_turn_snapshot_callback' if phase == 'preclaim' else 'relay_activation_callback'
        original = kwargs[key]
        def observation(*args):
            record('observation_entered')
            entered.set()
            value = original(*args)
            if phase == 'preclaim':
                captured.append(value)
            observed.set()
            return value
        kwargs[key] = observation
        return original_router(service, **kwargs)
    monkeypatch.setattr(dependencies, 'create_router', observe_router)
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(), relay_storage=storage, codex_wake_registry=registry))

    def hold_native_owner():
        with registry._lock:
            held.set()
            if not release.wait(5):
                gate_errors.append('native owner gate watchdog expired')
    holder = threading.Thread(target=hold_native_owner, name='test-native-owner')
    with TestClient(app) as http, ThreadPoolExecutor(max_workers=1) as pool:
        request = None

        def post(*args, **kwargs):
            record('request_entered')
            try:
                return http.post(*args, **kwargs)
            finally:
                record('request_finished')

        holder.start()
        try:
            assert held.wait(2)
            if phase == 'preclaim':
                record('request_submitted')
                request = pool.submit(post, '/relay/turn', json={
                    'runtime': 'codex', 'session_ref': 'target',
                    'wake_delivery_id': reservation.delivery_id, **SCOPE,
                })
            else:
                request = pool.submit(http.get, '/relay/sessions', params={
                    'runtime': 'codex', 'session_ref': 'target', **SCOPE,
                })
            assert entered.wait(2), 'actual observation callback was not entered'
            progressed = observed.wait(1)
            completed_while_held = None
            if phase == 'projection':
                completed_while_held = False
                if progressed:
                    try:
                        request.result(1)
                        completed_while_held = True
                    except TimeoutError:
                        pass
        finally:
            try:
                if phase == 'preclaim':
                    done = request is not None and request.done()
                    error = request.exception() if done and not request.cancelled() else None
                    print('fresh authority arrival: ' + json.dumps({
                        'events': list(arrival), 'future_done': done,
                        'future_error_type': type(error).__name__ if error else None,
                    }), file=sys.stderr)
            finally:
                release.set()
                holder.join(5)
        response = request.result(5)
        assert not holder.is_alive() and not gate_errors, gate_errors
        assert response.status_code == 200, response.text
        if phase == 'preclaim':
            assert captured == [reservation]
            claimed, = response.json()['deliveries']
            assert claimed['delivery_id'] == reservation.delivery_id and claimed['attempts'] == 1
            current = registry.snapshot(reservation.recipient_endpoint_id)
            assert current == reservation
            ack = http.post('/relay/deliveries/ack', json={
                'delivery_id': claimed['delivery_id'], 'claim_token': claimed['claim_token'], **SCOPE,
            })
            assert ack.status_code == 200, ack.text
            retained = http.get(f"/relay/messages/{claimed['message_id']}", params=SCOPE)
            assert retained.status_code == 200, retained.text
            row, = retained.json()['deliveries']
            assert (row['delivery_id'], row['state'], row['attempts']) == (reservation.delivery_id, 'delivered', 1)
        else:
            row, = response.json()
            assert row['endpoint_id'] == reservation.recipient_endpoint_id
            assert row['activation']['availability'] == 'attempt_inflight'
        assert progressed and (phase != 'projection' or completed_while_held), {
            'fresh_observation_completed_while_owner_held': progressed,
            'projection_http_completed_while_owner_held': completed_while_held,
        }


@pytest.mark.parametrize('accessor', ['snapshot', 'reservations'])
def test_persistent_observation_preserves_cached_state_and_action_authority(
    relay_store, tmp_path, accessor,
):
    relay, _, database = relay_store
    registry = _registry(relay, tmp_path / 'legacy')
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    other = _reserve(registry, _send(relay, target='other'), target='other')
    assert reservation is not None and other is not None
    registry._usable, registry._initialized, registry._reservations = False, None, {}
    cache = registry._reservations

    def observe():
        return (registry.snapshot_if_usable(reservation.recipient_endpoint_id) if accessor == 'snapshot'
                else registry.reservations_if_usable())
    observed = observe()
    if accessor == 'snapshot':
        assert observed == reservation
    else:
        assert len(observed) == 2 and set(observed) == {reservation, other}
    assert registry._usable is False and registry._initialized is None
    assert registry._reservations is cache and cache == {}
    # An earlier valid observation cannot authorize a later action against corrupt authority.
    with sqlite3.connect(database) as db:
        db.execute('UPDATE relay_codex_wake_reservations SET generation=0 WHERE recipient_endpoint_id=?',
                   (other.recipient_endpoint_id,))
    assert observe() == (None if accessor == 'snapshot' else ())
    assert registry._usable is False and registry._initialized is None
    assert registry._reservations is cache and cache == {}
    assert registry.begin_native_attempt(reservation) is None
    stored = {item.recipient_endpoint_id: item for item in _stored_items(database)}
    assert stored[reservation.recipient_endpoint_id] == reservation
    assert stored[other.recipient_endpoint_id] == replace(other, generation=0)


def test_persistent_observation_preserves_endpoint_canonicalization_and_full_validation():
    first = CodexWakeReservation('relay-session-' + 'a' * 32, 'delivery-first', 'target', SCOPE['container_ref'], 1)
    last = replace(first, delivery_id='delivery-last', generation=2)
    provider = SimpleNamespace(codex_wake_snapshot=lambda: (True, (first, last)))
    registry = CodexWakeRegistry(relay_service=provider)
    registry._usable, registry._initialized, registry._reservations = False, None, {}
    cache = registry._reservations
    assert registry.snapshot_if_usable(first.recipient_endpoint_id) == last
    assert registry.reservations_if_usable() == (last,)
    # Canonicalization never hides an invalid earlier entry from full validation.
    provider.codex_wake_snapshot = lambda: (True, (replace(first, generation=0), last))
    assert registry.snapshot_if_usable(first.recipient_endpoint_id) is None
    assert registry.reservations_if_usable() == ()
    assert registry._usable is False and registry._initialized is None
    assert registry._reservations is cache and cache == {}


@pytest.mark.parametrize("count, damage", [
    (0, None), (1, None), (50, None), (256, None),
    (257, "overflow"), (50, "unrelated"), (1, "absent_marker"),
    (1, "high_water"), (0, "extra_marker"), (0, "absent_marker"),
])
def test_authority_reads_preserve_all_fields_without_global_orm_hydration(
    relay_store, tmp_path, count, damage,
):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from storage.sqlite_schema import RelayCodexWakeReservationRecord, RelayCodexWakeStateRecord

    relay, storage, database = relay_store
    invalid = damage is not None and not (count == 0 and damage == "absent_marker")
    items = tuple(CodexWakeReservation(
        recipient_endpoint_id=f"relay-session-{index:032x}",
        delivery_id=f"relay-delivery-{index:032x}",
        session_ref=f"target-東京-{index}", container_ref=SCOPE["container_ref"],
        generation=index + 1, outcome=("prepared", "reserved", "accepted", "uncertain")[index % 4],
        correlated_claim_attempts=index + 1 if index % 2 else None,
        retry_not_before=1.25 + index if index % 3 else None,
    ) for index in range(count))
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO relay_codex_wake_state (id, generation) VALUES (1, ?)", (count,))
        db.executemany(
            "INSERT INTO relay_codex_wake_reservations "
            "(recipient_endpoint_id, delivery_id, session_ref, container_ref, generation, "
            "outcome, correlated_claim_attempts, retry_not_before) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [tuple(asdict(item).values()) for item in items],
        )
        if damage == "unrelated":
            db.execute("UPDATE relay_codex_wake_reservations SET outcome='invalid' WHERE recipient_endpoint_id=?",
                       (items[-1].recipient_endpoint_id,))
        elif damage == "absent_marker":
            db.execute("DELETE FROM relay_codex_wake_state")
        elif damage == "high_water":
            db.execute("UPDATE relay_codex_wake_state SET generation=0")
        elif damage == "extra_marker":
            db.execute("INSERT INTO relay_codex_wake_state (id, generation) VALUES (2, 0)")

    hydrated, statements, raw_statements = [], [], []

    def observe_checkout(connection, *_args):
        connection.set_trace_callback(raw_statements.append)

    def observe_checkin(connection, *_args):
        if connection is not None:
            connection.set_trace_callback(None)

    def observe_load(_session, row):
        if isinstance(row, (RelayCodexWakeReservationRecord, RelayCodexWakeStateRecord)):
            hydrated.append(type(row).__name__)

    def observe_sql(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(Session, "loaded_as_persistent", observe_load)
    event.listen(storage._relay_engine, "before_cursor_execute", observe_sql)
    event.listen(storage._relay_engine, "checkout", observe_checkout)
    event.listen(storage._relay_engine, "checkin", observe_checkin)
    try:
        if invalid:
            with pytest.raises(ValueError, match="invalid persisted Codex wake authority"):
                relay.codex_wake_snapshot()
        else:
            initialized, observed = relay.codex_wake_snapshot()
            assert initialized is (damage != "absent_marker")
            assert set(observed) == set(items)
            assert len(observed) == count
        assert [statement.split()[0] for statement in statements] == ["BEGIN"], statements
        assert sum(statement.lstrip().upper().startswith("SELECT") for statement in raw_statements) == 1
        assert sum("LIMIT" in statement and "relay_codex_wake_reservations" in statement
                   for statement in raw_statements) == 1
        assert hydrated == [], hydrated
        # All unrelated rows remain validated during a write transition too.
        statements.clear()
        hydrated.clear()
        if invalid:
            with pytest.raises(ValueError, match="invalid persisted Codex wake authority"):
                storage.relay_codex_wake_transition(operation="release", reservations=())
        else:
            released = storage.relay_codex_wake_transition(operation="release", reservations=())
            assert released == (None if damage == "absent_marker" else ())
        assert [statement.split()[0] for statement in statements] == [
            "PRAGMA", "BEGIN", "SELECT", "SELECT", "SELECT",
            "ROLLBACK" if invalid else "COMMIT", "PRAGMA",
        ], statements
        assert hydrated == ["RelayCodexWakeStateRecord"] * (damage != "absent_marker"), hydrated
    finally:
        event.remove(storage._relay_engine, "checkout", observe_checkout)
        event.remove(storage._relay_engine, "checkin", observe_checkin)
        event.remove(Session, "loaded_as_persistent", observe_load)
        event.remove(storage._relay_engine, "before_cursor_execute", observe_sql)
    registry = _registry(relay, tmp_path / "absent-legacy")
    assert set(registry.reservations_if_usable()) == (set() if damage else set(items))
    assert registry.usable is (damage is None)


@pytest.mark.parametrize("generation, valid", [(0, True), (7, True), (1.5, False), ("invalid", False), (None, False), (b"\x00", False)])
def test_authority_envelope_preserves_native_marker_generation(relay_store, generation, valid):
    relay, _, database = relay_store
    with sqlite3.connect(database) as db:
        # A corrupted schema permits NULL/BLOB values that healthy constraints forbid.
        db.execute("DROP TABLE relay_codex_wake_state")
        db.execute("CREATE TABLE relay_codex_wake_state(id INTEGER PRIMARY KEY, generation)")
        db.execute("INSERT INTO relay_codex_wake_state VALUES(1, ?)", (generation,))
    if valid:
        assert relay.codex_wake_snapshot() == (True, ())
    else:
        with pytest.raises(ValueError, match="invalid persisted Codex wake authority"):
            relay.codex_wake_snapshot()


@pytest.mark.parametrize("error", ["no such function: json_array", "no such function: json_group_array", "database disk image is malformed"])
def test_authority_envelope_fallback_keeps_global_validation(relay_store, monkeypatch, error):
    from storage import sqlite_relay
    relay, _, database = relay_store
    item = CodexWakeReservation("relay-session-" + "1" * 32, "relay-delivery-" + "1" * 32,
                               "target-東京", SCOPE["container_ref"], 1, "reserved",
                               retry_not_before=1.0000000000000002)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO relay_codex_wake_state VALUES(1, 1)")
        db.execute("INSERT INTO relay_codex_wake_reservations (" + ", ".join(asdict(item)) +
                   ") VALUES(?,?,?,?,?,?,?,?)", tuple(asdict(item).values()))
    attempted = []
    def unavailable(_cursor):
        attempted.append(True)
        raise sqlite3.OperationalError(error)
    monkeypatch.setattr(sqlite_relay, "_wake_snapshot_envelope", unavailable)
    if error.startswith("no such function:"):
        assert relay.codex_wake_snapshot() == (True, (item,))
        with sqlite3.connect(database) as db:
            db.execute("INSERT INTO relay_codex_wake_state VALUES(2, 0)")
        with pytest.raises(ValueError, match="invalid persisted Codex wake authority"):
            relay.codex_wake_snapshot()
        assert len(attempted) == 2
    else:
        with pytest.raises(sqlite3.OperationalError, match=error):
            relay.codex_wake_snapshot()
        assert len(attempted) == 1


def test_http_exact_claim_uses_fresh_authority_and_committed_generation(
    relay_store, tmp_path, monkeypatch,
):
    relay, storage, _ = relay_store
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    spent = registry.begin_native_attempt(reservation)
    assert spent is not None and registry.record_outcome(spent, "accepted")
    before = registry.snapshot(reservation.recipient_endpoint_id)
    original_snapshot = relay.codex_wake_snapshot
    reads = []
    armed = False

    def snapshot():
        if armed:
            reads.append(1)
        return original_snapshot()

    monkeypatch.setattr(relay, "codex_wake_snapshot", snapshot)
    monkeypatch.setattr("app.dependencies.current_platform", lambda: "windows")
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(), relay_storage=storage, codex_wake_registry=registry))
    with TestClient(app) as http:
        armed = True
        try:
            response = http.post("/relay/turn", json={
                "runtime": "codex", "session_ref": "target",
                "wake_delivery_id": reservation.delivery_id, **SCOPE,
            })
        finally:
            armed = False
        assert response.status_code == 200, response.text
        claimed, = response.json()["deliveries"]
        assert claimed["delivery_id"] == reservation.delivery_id
        assert claimed["attempts"] == 1
        assert registry.snapshot(reservation.recipient_endpoint_id) == before
        acknowledged = http.post("/relay/deliveries/ack", json={
            "delivery_id": claimed["delivery_id"], "claim_token": claimed["claim_token"], **SCOPE,
        })
        assert acknowledged.status_code == 200, acknowledged.text
        readback = http.get(f"/relay/messages/{claimed['message_id']}", params=SCOPE)
        assert readback.status_code == 200, readback.text
        retained, = readback.json()["deliveries"]
        assert retained["delivery_id"] == reservation.delivery_id
        assert retained["state"] == "delivered" and retained["attempts"] == 1
    # One preclaim read and one fresh post-admission view shared by default projections.
    assert len(reads) == 2, reads


@pytest.mark.parametrize("authority", [
    "reserved", "removed", "malformed", "uninitialized", "read_failed", "health", "scope_unavailable",
])
def test_http_response_projection_uses_fresh_authority_and_distinct_health(
    relay_store, tmp_path, monkeypatch, authority,
):
    from app import dependencies
    from core.relay import RelayNotFoundError

    relay, storage, database = relay_store
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    spent = registry.begin_native_attempt(reservation)
    assert spent is not None and registry.record_outcome(spent, "accepted")
    other = None
    if authority == "malformed":
        other = _reserve(registry, _send(relay, target="other"), target="other")
        assert other is not None
    original_router = dependencies.create_router
    changed = []
    monkeypatch.setattr("app.dependencies.current_platform", lambda: "windows")

    def observe_router(service, **kwargs):
        admission = kwargs["relay_turn_admission_callback"]
        route_relay = kwargs["relay_service"]

        def change_after_admission(request, result, captured):
            admission(request, result, captured)
            assert registry.snapshot(reservation.recipient_endpoint_id).correlated_claim_attempts is None
            if authority in {"removed", "health"}:
                assert registry.release_generation(registry.snapshot(reservation.recipient_endpoint_id))
                if authority == "health":
                    assert relay.mark_unreachable(runtime="codex", session_ref="target", attempt_started_at=datetime.now(timezone.utc), **SCOPE)
            elif authority == "malformed":
                with sqlite3.connect(database) as db:
                    db.execute("UPDATE relay_codex_wake_reservations SET generation=0 WHERE recipient_endpoint_id=?", (other.recipient_endpoint_id,))
            elif authority == "uninitialized":
                with sqlite3.connect(database) as db:
                    db.execute("DELETE FROM relay_codex_wake_reservations")
                    db.execute("DELETE FROM relay_codex_wake_state")
            elif authority == "read_failed":
                def unavailable():
                    raise RuntimeError("authority unavailable after admission")
                monkeypatch.setattr(relay, "codex_wake_snapshot", unavailable)
            elif authority == "scope_unavailable":
                def absent(_endpoint):
                    raise RelayNotFoundError("scope unavailable after admission")
                monkeypatch.setattr(route_relay, "session_view_by_endpoint", absent)
            changed.append(authority)

        kwargs["relay_turn_admission_callback"] = change_after_admission
        return original_router(service, **kwargs)

    monkeypatch.setattr(dependencies, "create_router", observe_router)
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(), relay_storage=storage, codex_wake_registry=registry))
    with TestClient(app) as http:
        response = http.post("/relay/turn", json={
            "runtime": "codex", "session_ref": "target",
            "wake_delivery_id": reservation.delivery_id, **SCOPE,
        })
        assert response.status_code == 200, response.text
        assert changed == [authority]
        claimed, = response.json()["deliveries"]
        assert claimed["delivery_id"] == reservation.delivery_id and claimed["attempts"] == 1
        assert claimed["recipient_container_ref"] == SCOPE["container_ref"]
        session_availability = response.json()["session"]["activation"]["availability"]
        delivery_availability = claimed["activation"]["availability"]
        expected = "attempt_inflight" if authority == "reserved" else "unknown"
        assert session_availability == ("attempt_inflight" if authority == "scope_unavailable" else expected)
        assert delivery_availability == ("unreachable" if authority == "health" else expected)
        readback = http.get(f"/relay/messages/{claimed['message_id']}", params=SCOPE)
        assert readback.status_code == 200, readback.text
        retained, = readback.json()["deliveries"]
        assert retained["delivery_id"] == reservation.delivery_id
        assert retained["state"] == "claimed" and retained["attempts"] == 1


@pytest.mark.parametrize("callback_mode", ["custom", "delegate", "factory_raises", "factory_invalid"])
def test_http_projection_factory_preserves_overrides_and_error_fallback(
    relay_store, tmp_path, monkeypatch, caplog, callback_mode,
):
    from app import dependencies

    relay, storage, _ = relay_store
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    spent = registry.begin_native_attempt(reservation)
    assert spent is not None and registry.record_outcome(spent, "accepted")
    original_router, original_snapshot = dependencies.create_router, relay.codex_wake_snapshot
    reads, callbacks = [], []
    armed = False
    monkeypatch.setattr("app.dependencies.current_platform", lambda: "windows")

    def snapshot():
        if armed:
            reads.append(1)
        return original_snapshot()

    def observe_router(service, **kwargs):
        callback = kwargs["relay_activation_callback"]
        if callback_mode in {"custom", "delegate"}:
            def override(row):
                callbacks.append(row)
                result = callback(row)
                return ({**result, "availability": "unknown", "availability_source": "none"}
                        if callback_mode == "custom" else result)
            kwargs["relay_activation_callback"] = override
        else:
            def failed_factory(_actual_callback):
                if callback_mode == "factory_raises":
                    raise RuntimeError("controlled projector factory failure")
                return None
            kwargs["relay_activation_callback_factory"] = failed_factory
        return original_router(service, **kwargs)

    monkeypatch.setattr(relay, "codex_wake_snapshot", snapshot)
    monkeypatch.setattr(dependencies, "create_router", observe_router)
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(), relay_storage=storage, codex_wake_registry=registry))
    with TestClient(app) as http:
        armed = True
        try:
            response = http.post("/relay/turn", json={
                "runtime": "codex", "session_ref": "target",
                "wake_delivery_id": reservation.delivery_id, **SCOPE,
            })
        finally:
            armed = False
        assert response.status_code == 200, response.text
        claimed, = response.json()["deliveries"]
        assert claimed["delivery_id"] == reservation.delivery_id and claimed["attempts"] == 1
        expected = "unknown" if callback_mode == "custom" else "attempt_inflight"
        assert response.json()["session"]["activation"]["availability"] == expected
        assert claimed["activation"]["availability"] == expected
        assert len(callbacks) == (2 if callback_mode in {"custom", "delegate"} else 0)
        assert len(reads) == 3  # One preclaim plus two preserved fallback row reads.
        if callback_mode.startswith("factory_"):
            assert any("projector preparation failed" in record.message for record in caplog.records)
        assert registry.snapshot(reservation.recipient_endpoint_id).correlated_claim_attempts is None


@pytest.mark.parametrize("change", [
    "outcome", "replacement", "attempt_conflict", "unrelated_corruption",
    "commit_before", "commit_after", "endpoint", "delivery", "session", "container",
])
def test_http_claim_correlation_uses_fresh_identity_and_preserves_authority(
    relay_store, tmp_path, monkeypatch, change,
):
    from app import dependencies

    relay, storage, database = relay_store
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    current = registry.begin_native_attempt(reservation)
    assert current is not None
    other = _reserve(registry, _send(relay, target="other"), target="other")
    assert other is not None
    original_router = dependencies.create_router
    original_correlate = registry.correlate_claim
    original_begin = storage._begin_relay_immediate
    results = []
    expected = [current]

    def correlate(**kwargs):
        mismatches = {
            "endpoint": ("recipient_endpoint_id", "relay-session-" + "f" * 32),
            "delivery": ("delivery_id", "relay-delivery-" + "f" * 32),
            "session": ("session_ref", "different-session"),
            "container": ("container_ref", "git:example.test/different"),
        }
        if change in mismatches:
            key, value = mismatches[change]
            kwargs[key] = value
        result = original_correlate(**kwargs)
        results.append(result)
        return result

    def observe_router(service, **kwargs):
        # Explicit correlation remains a supported postcommit callback/failure path.
        def admission(request, result, captured):
            codex_wake.correlate_codex_relay_wake_claim(
                request['wake_delivery_id'], request['session_ref'], request['container_ref'],
                result, captured, registry=registry,
            )

        def change_before_correlation(request, result, captured):
            assert captured == current
            assert result["deliveries"][0]["attempts"] == 1
            if change == "outcome":
                assert registry.record_outcome(current, "accepted")
                expected[0] = replace(current, outcome="accepted", correlated_claim_attempts=1)
            elif change == "replacement":
                expected[0] = registry.replace_generation(current, session_ref=current.session_ref, container_ref=current.container_ref)
                assert expected[0] is not None and expected[0].generation > current.generation
            elif change == "attempt_conflict":
                assert original_correlate(
                    delivery_id=current.delivery_id, recipient_endpoint_id=current.recipient_endpoint_id,
                    session_ref=current.session_ref, container_ref=current.container_ref,
                    attempts=2, expected_generation=current.generation,
                )
                expected[0] = replace(current, correlated_claim_attempts=2)
            elif change == "unrelated_corruption":
                with sqlite3.connect(database) as db:
                    db.execute("UPDATE relay_codex_wake_reservations SET generation=0 WHERE recipient_endpoint_id=?", (other.recipient_endpoint_id,))
            if change in {"commit_before", "commit_after"}:
                @contextmanager
                def ambiguous():
                    with original_begin() as db:
                        yield db
                        if change == "commit_before":
                            raise OperationalError("COMMIT", {}, sqlite3.OperationalError("before commit"))
                    raise OperationalError("COMMIT", {}, sqlite3.OperationalError("after commit"))
                with monkeypatch.context() as fault:
                    fault.setattr(storage, "_begin_relay_immediate", ambiguous)
                    admission(request, result, captured)
                if change == "commit_after":
                    expected[0] = replace(current, correlated_claim_attempts=1)
            else:
                admission(request, result, captured)

        kwargs["relay_turn_admission_callback"] = change_before_correlation
        return original_router(service, **kwargs)

    monkeypatch.setattr(registry, "correlate_claim", correlate)
    monkeypatch.setattr(dependencies, "create_router", observe_router)
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(), relay_storage=storage, codex_wake_registry=registry))
    with TestClient(app) as http:
        response = http.post("/relay/turn", json={
            "runtime": "codex", "session_ref": "target",
            "wake_delivery_id": current.delivery_id, **SCOPE,
        })
        assert response.status_code == 200, response.text
        claimed, = response.json()["deliveries"]
        assert claimed["delivery_id"] == current.delivery_id and claimed["attempts"] == 1
        assert results == [change == "outcome"]
        stored = {item.recipient_endpoint_id: item for item in _stored_items(database)}
        assert stored[current.recipient_endpoint_id] == expected[0]
        assert stored[other.recipient_endpoint_id] == (replace(other, generation=0) if change == "unrelated_corruption" else other)
        if change == "unrelated_corruption":
            assert not registry.usable
        readback = http.get(f"/relay/messages/{claimed['message_id']}", params=SCOPE)
        assert readback.status_code == 200, readback.text
        retained, = readback.json()["deliveries"]
        assert retained["delivery_id"] == current.delivery_id
        assert retained["state"] == "claimed" and retained["attempts"] == 1


@pytest.mark.parametrize("authority", ["reserved", "absent", "uninitialized", "malformed", "failed"])
@pytest.mark.parametrize("runtime", ["codex", "claude-code"])
def test_http_activation_reads_authority_once_and_fails_closed(relay_store, tmp_path, monkeypatch, authority, runtime):
    relay, storage, _ = relay_store
    endpoint = relay.turn(runtime=runtime, session_ref="target", **SCOPE)["session"]["endpoint_id"]
    registry = _registry(relay, tmp_path / "legacy")
    reservation = CodexWakeReservation(endpoint, "delivery", "target", SCOPE["container_ref"], 1)
    reads = []

    def snapshot():
        reads.append(1)
        if authority == "failed":
            raise RuntimeError("authority unavailable")
        items = [] if authority == "absent" else [reservation]
        if authority == "malformed":
            items = [replace(reservation, generation=0)]
        return authority != "uninitialized", items

    monkeypatch.setattr(relay, "codex_wake_snapshot", snapshot)
    monkeypatch.setattr("app.dependencies.current_platform", lambda: "windows")
    app = FastAPI()
    app.include_router(build_router(SimpleNamespace(), relay_storage=storage, codex_wake_registry=registry))
    with TestClient(app) as http:
        response = http.get("/relay/sessions", params={**SCOPE, "runtime": runtime, "session_ref": "target"})
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1 and rows[0]["endpoint_id"] == endpoint
    expected = "attempt_inflight" if runtime == "codex" and authority == "reserved" else "unknown"
    assert rows[0]["activation"]["availability"] == expected
    assert len(reads) == (1 if runtime == "codex" else 0)


def test_existing_relay_database_adds_trial_endpoint_marker_without_enrolling(tmp_path):
    relay_db = tmp_path / "relay.db"
    main_db = tmp_path / "main.db"
    storage = SQLiteStorageProvider(f"sqlite:///{main_db}", f"sqlite:///{relay_db}")
    endpoint = RelayService(storage).turn(runtime="codex", session_ref="target", **SCOPE)["session"]["endpoint_id"]
    storage.close()
    with sqlite3.connect(relay_db) as db:
        db.execute("ALTER TABLE relay_sessions DROP COLUMN trial_enrolled")
        db.execute("DROP TABLE relay_codex_trial")

    reopened = SQLiteStorageProvider(f"sqlite:///{main_db}", f"sqlite:///{relay_db}")
    try:
        relay = RelayService(reopened)
        assert not relay.codex_trial_native_suppressed(endpoint)
        assert relay.enroll_codex_trial(
            endpoint_id=endpoint, session_ref="target", container_ref=SCOPE["container_ref"],
            trial_id="migrated-trial",
        )
        assert relay.codex_trial_native_suppressed(endpoint)
    finally:
        reopened.close()


def test_app_uses_sqlite_authority_and_does_not_implicitly_import(tmp_path, monkeypatch):
    monkeypatch.delenv("PALLIUM_CODEX_WAKE_DIR", raising=False)
    config = AppConfig(
        storage_backend="sqlite", sqlite_url=f"sqlite:///{tmp_path / 'app.db'}",
        default_use_case="demo_agent_memory", semantic_packages=DEMO_SEMANTIC_PACKAGES,
        vector_index=VectorIndexConfig(enabled=False),
    )
    app = create_app(config)
    assert app.state.codex_wake_registry.persistent
    assert not app.state.codex_wake_registry.usable
    assert app.state.codex_wake_registry.reservations() == ()


def test_app_recreate_uses_new_storage_and_shared_initiation_guard(tmp_path, monkeypatch):
    monkeypatch.delenv("PALLIUM_CODEX_WAKE_DIR", raising=False)
    config = AppConfig(storage_backend="sqlite", sqlite_url=f"sqlite:///{tmp_path / 'app.db'}",
                       default_use_case="demo_agent_memory", semantic_packages=DEMO_SEMANTIC_PACKAGES,
                       vector_index=VectorIndexConfig(enabled=False))
    first = create_app(config)
    first_registry = first.state.codex_wake_registry
    first.state.pallium_service._storage.close()
    second = create_app(config)
    second_registry = second.state.codex_wake_registry
    assert second_registry is not first_registry
    assert second_registry._relay._store is second.state.pallium_service._storage
    assert second_registry._lock is first_registry._lock


def test_unavailable_relay_factory_never_writes_legacy_json(tmp_path):
    database = tmp_path / "relay.db"
    registry = codex_wake.get_codex_wake_registry_for_relay_database(f"sqlite:///{database}")
    assert not registry.usable
    assert registry.reserve(recipient_endpoint_id="relay-session-" + "1" * 32,
                            delivery_id="delivery", session_ref="target", **SCOPE) is None
    assert not (tmp_path / "relay.db-codex-wake" / "reservations.json").exists()


def test_decision_callback_does_not_run_inside_sql_transaction(relay_store):
    relay, _, database = relay_store
    delivery = _send(relay)

    def decision(state):
        with sqlite3.connect(database, timeout=0) as second_writer:
            second_writer.execute("BEGIN IMMEDIATE")
            second_writer.rollback()
        return state["delivery_id"] == delivery["delivery_id"]

    assert relay.reconcile_codex_wake_reservation(delivery_id=delivery["delivery_id"], decision=decision)


def test_storage_failure_logs_bounded_metadata_without_sql_values(relay_store, tmp_path, monkeypatch, caplog):
    relay, _, _ = relay_store
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    delivery = _send(relay)

    def denied(*args, **kwargs):
        raise OperationalError("secret-sql-payload", {"secret_scope": "secret-scope-value"}, sqlite3.OperationalError("secret-database-path"))

    monkeypatch.setattr(relay, "codex_wake_transition", denied)
    with caplog.at_level(logging.WARNING, logger="core.codex_wake"):
        assert _reserve(registry, delivery) is None
    assert "codex_wake_transition_failed operation=reserve error_type=OperationalError" in caplog.text
    assert "secret-" not in caplog.text and "secret_scope" not in caplog.text


@pytest.mark.parametrize("native_outcome,persisted_outcome", [("queued", "accepted"), ("ambiguous", "uncertain")])
def test_http_send_restart_exact_claim_ack_preserves_sqlite_fence(
    client, tmp_path, monkeypatch, native_outcome, persisted_outcome,
):
    # This lifecycle asserts the legacy queue launcher and persisted fence.
    monkeypatch.setattr("app.codex_bridge_pipe.retained_wake_enabled", lambda: False)
    storage = client.app.state.pallium_service._storage
    relay = RelayService(storage)
    directory = tmp_path / "legacy"
    registry = _registry(relay, directory)
    assert registry.initialize(old_owner_drained=True)
    workers, native_calls = [], []
    original_schedule = codex_wake._schedule_reserved_codex_relay_wake
    # This lifecycle test asserts persisted trace facts, separately from the
    # best-effort async diagnostic queue's contention/drop contract below.
    monkeypatch.setattr(
        client.app.state.pallium_service, "enqueue_relay_trace_event",
        lambda writer, event: bool(writer(event)),
    )

    def launch(*args):
        native_calls.append(args)
        return None, (native_outcome, None, 0)

    def schedule(*args, **kwargs):
        worker = original_schedule(*args, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", codex_wake.schedule_codex_relay_wake)
    monkeypatch.setattr(codex_wake, "_schedule_reserved_codex_relay_wake", schedule)
    monkeypatch.setattr(codex_wake, "_start_launch", launch)
    monkeypatch.setattr(codex_wake, "_DEBOUNCE_SECONDS", 0)

    def route(actual_registry):
        app = FastAPI()
        app.include_router(build_router(client.app.state.pallium_service, relay_storage=storage,
                                       codex_wake_registry=actual_registry))
        return TestClient(app)

    http = route(registry)
    for session in ("sender", "target"):
        assert http.post("/relay/turn", json={"runtime": "codex", "session_ref": session, **SCOPE}).status_code == 200
    body = {"sender_runtime": "codex", "sender_session_ref": "sender", "recipient": "codex:target",
            "message_id": "sqlite-wake-lifecycle", "payload": "Unicode payload 東京", **SCOPE}
    sent = http.post("/relay/messages", json=body)
    assert sent.status_code == 200, sent.text
    for worker in workers:
        assert worker is not None
        worker.join(2)
        assert not worker.is_alive()
    delivery = sent.json()["deliveries"][0]
    current = registry.snapshot(delivery["recipient_endpoint_id"])
    assert current is not None and current.outcome == persisted_outcome
    assert http.post("/relay/messages", json=body).status_code == 200
    assert len(native_calls) == 1
    restarted = _registry(relay, directory)
    assert restarted.snapshot(current.recipient_endpoint_id) == current
    http = route(restarted)
    assert http.post("/relay/messages", json=body).status_code == 200
    assert len(native_calls) == 1
    claim = http.post("/relay/turn", json={"runtime": "codex", "session_ref": "target",
                                             "wake_delivery_id": current.delivery_id, **SCOPE})
    assert claim.status_code == 200, claim.text
    claimed = claim.json()["deliveries"][0]
    assert claimed["payload"] == body["payload"]
    assert restarted.snapshot(current.recipient_endpoint_id).correlated_claim_attempts is None
    state = relay.codex_wake_reservation_state(delivery_id=current.delivery_id)
    assert state['codex_wake_generation'] == current.generation and state['attempts'] == claimed['attempts'] == 1
    acknowledged = http.post("/relay/deliveries/ack", json={"delivery_id": current.delivery_id,
                                                              "claim_token": claimed["claim_token"], **SCOPE})
    assert acknowledged.status_code == 200, acknowledged.text
    observed = http.get(f"/relay/messages/{body['message_id']}", params=SCOPE).json()["deliveries"][0]
    assert observed["state"] == "delivered" and observed["attempts"] == 1
    assert restarted.reservations() == ()
    assert http.post("/relay/turn", json={"runtime": "codex", "session_ref": "target", **SCOPE}).json()["deliveries"] == []
    trace = http.get(f"/relay/messages/{body['message_id']}/trace", params=SCOPE)
    assert trace.status_code == 200
    assert any(event["stage"] == "completed" for event in trace.json()["events"])


def test_http_recovery_resumes_prepared_fence_after_restart(client, tmp_path, monkeypatch):
    from app.dependencies import recover_expired_relay_wakes
    from core.claude_wake import ClaudeWakeRegistry

    monkeypatch.setattr("app.codex_bridge_pipe.retained_wake_enabled", lambda: False)
    storage = client.app.state.pallium_service._storage
    relay = RelayService(storage)
    directory = tmp_path / "legacy"
    first_registry = _registry(relay, directory)
    assert first_registry.initialize(old_owner_drained=True)
    scheduled = []
    completed = threading.Event()
    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", codex_wake.schedule_codex_relay_wake)
    monkeypatch.setattr(
        codex_wake, "_wake_after_debounce",
        lambda reservation, *_: (scheduled.append(reservation), completed.set()),
    )

    def route(registry):
        app = FastAPI()
        app.include_router(build_router(
            client.app.state.pallium_service, relay_storage=storage,
            codex_wake_registry=registry,
        ))
        return TestClient(app)

    http = route(first_registry)
    for session in ("sender", "target"):
        assert http.post("/relay/turn", json={
            "runtime": "codex", "session_ref": session, **SCOPE,
        }).status_code == 200
    first = http.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": "codex:target", "message_id": "prepared-before-restart",
        "payload": "first pending delivery", **SCOPE,
    })
    assert first.status_code == 200, first.text
    delivery_a = first.json()["deliveries"][0]
    assert completed.wait(2)
    prepared = first_registry.snapshot(delivery_a["recipient_endpoint_id"])
    assert prepared is not None
    assert scheduled == [prepared]

    scheduled.clear()
    restarted = _registry(relay, directory)
    http = route(restarted)
    second = http.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": "codex:target", "message_id": "behind-prepared-fence",
        "payload": "second pending delivery", **SCOPE,
    })
    assert second.status_code == 200, second.text
    delivery_b = second.json()["deliveries"][0]
    recover_expired_relay_wakes(
        relay, ClaudeWakeRegistry(), codex_registry=restarted,
    )
    recover_expired_relay_wakes(
        relay, ClaudeWakeRegistry(), codex_registry=restarted,
    )
    assert scheduled == [restarted.snapshot(delivery_a["recipient_endpoint_id"])]
    assert scheduled[0].delivery_id == delivery_a["delivery_id"]
    assert scheduled[0].outcome == "prepared"
    status = http.get(f"/relay/messages/{second.json()['message_id']}", params=SCOPE)
    assert status.status_code == 200
    assert status.json()["deliveries"][0]["delivery_id"] == delivery_b["delivery_id"]
    assert status.json()["deliveries"][0]["state"] == "pending"
    claim = http.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target",
        "wake_delivery_id": delivery_a["delivery_id"], **SCOPE,
    })
    assert claim.status_code == 200, claim.text
    claimed = claim.json()["deliveries"][0]
    assert claimed["delivery_id"] == delivery_a["delivery_id"]
    recover_expired_relay_wakes(
        relay, ClaudeWakeRegistry(), codex_registry=restarted,
    )
    assert len(scheduled) == 1
    acknowledged = http.post("/relay/deliveries/ack", json={
        "delivery_id": delivery_a["delivery_id"],
        "claim_token": claimed["claim_token"], **SCOPE,
    })
    assert acknowledged.status_code == 200, acknowledged.text
    status = http.get(f"/relay/messages/{first.json()['message_id']}", params=SCOPE)
    assert status.json()["deliveries"][0]["state"] == "delivered"
    status = http.get(f"/relay/messages/{second.json()['message_id']}", params=SCOPE)
    assert status.json()["deliveries"][0]["state"] == "pending"
    following = restarted.snapshot(delivery_a["recipient_endpoint_id"])
    assert following is None or following.delivery_id == delivery_b["delivery_id"]


def test_prepared_native_cas_allows_one_sqlite_registry_and_rejects_active_claim(relay_store, tmp_path):
    relay, _, _ = relay_store
    first_registry = _registry(relay, tmp_path / "legacy")
    assert first_registry.initialize(old_owner_drained=True)
    reservation = _reserve(first_registry, _send(relay))
    second_registry = _registry(relay, tmp_path / "legacy")
    assert second_registry.usable
    barrier = threading.Barrier(3)
    results = []

    def spend(registry):
        barrier.wait()
        results.append(registry.begin_native_attempt(reservation))

    threads = [threading.Thread(target=spend, args=(registry,)) for registry in (first_registry, second_registry)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert sum(result is not None for result in results) == 1
    assert first_registry.snapshot(reservation.recipient_endpoint_id).outcome == "uncertain"

    pending = _reserve(first_registry, _send(relay, target="other"), target="other")
    assert pending is not None
    relay.turn(runtime="codex", session_ref="other", **SCOPE,
               exact_delivery_id=pending.delivery_id,
               codex_wake_endpoint_id=pending.recipient_endpoint_id,
               codex_wake_generation=pending.generation)
    assert first_registry.begin_native_attempt(pending) is None
    assert _registry(relay, tmp_path / "legacy").begin_native_attempt(pending) is None


def test_http_restart_prepares_new_generation_after_expired_hook_claim(client, tmp_path, monkeypatch):
    import storage.sqlite_relay as sqlite_relay
    from app.dependencies import recover_expired_relay_wakes
    from core.claude_wake import ClaudeWakeRegistry

    clock = [datetime(2031, 2, 3, tzinfo=timezone.utc)]
    def controlled_now(value=None):
        current = value or clock[0]
        return current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)
    monkeypatch.setattr(sqlite_relay, "_now", controlled_now)
    monkeypatch.setattr("app.codex_bridge_pipe.retained_wake_enabled", lambda: False)
    storage = client.app.state.pallium_service._storage
    relay = RelayService(storage)
    directory = tmp_path / "legacy"
    registry = _registry(relay, directory)
    assert registry.initialize(old_owner_drained=True)
    scheduled = []
    completed = threading.Event()
    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", codex_wake.schedule_codex_relay_wake)
    monkeypatch.setattr(codex_wake, "_wake_after_debounce",
                        lambda reservation, *_: (scheduled.append(reservation), completed.set()))

    def route(actual_registry):
        app = FastAPI()
        app.include_router(build_router(client.app.state.pallium_service, relay_storage=storage,
                                       codex_wake_registry=actual_registry))
        return TestClient(app)

    http = route(registry)
    for session in ("sender", "target"):
        assert http.post("/relay/turn", json={"runtime": "codex", "session_ref": session, **SCOPE}).status_code == 200
    sent = http.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": "codex:target", "message_id": "expired-claim-restart",
        "payload": "resumable replacement", **SCOPE,
    })
    assert sent.status_code == 200, sent.text
    delivery = sent.json()["deliveries"][0]
    assert completed.wait(2)
    prepared = registry.snapshot(delivery["recipient_endpoint_id"])
    assert prepared is not None and prepared.outcome == "prepared"
    uncertain = registry.begin_native_attempt(prepared)
    assert uncertain is not None
    assert registry.record_outcome(uncertain, "accepted")

    claim = http.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target",
        "wake_delivery_id": delivery["delivery_id"], **SCOPE,
    })
    assert claim.status_code == 200, claim.text
    assert claim.json()["deliveries"][0]["attempts"] == 1
    claimed = registry.snapshot(delivery["recipient_endpoint_id"])
    assert claimed is not None and claimed.correlated_claim_attempts is None
    assert relay.codex_wake_reservation_state(delivery_id=delivery['delivery_id'])['codex_wake_generation'] == claimed.generation
    clock[0] += timedelta(seconds=RELAY_CLAIM_LEASE_SECONDS + 1)

    restarted = _registry(relay, directory)
    http = route(restarted)
    recover_expired_relay_wakes(relay, ClaudeWakeRegistry(), codex_registry=restarted)
    replacement = restarted.snapshot(delivery["recipient_endpoint_id"])
    assert replacement is not None
    assert replacement.generation > claimed.generation
    assert replacement.outcome == "prepared" and replacement.correlated_claim_attempts is None
    recover_expired_relay_wakes(relay, ClaudeWakeRegistry(), codex_registry=restarted)
    assert len(scheduled) == 2
    assert scheduled[-1] == replacement
    spent = restarted.begin_native_attempt(replacement)
    assert spent == replace(replacement, outcome="uncertain", retry_not_before=spent.retry_not_before)
    assert spent.retry_not_before is not None


def test_http_pre_cas_worker_exception_clears_marker_for_same_process_resume(client, tmp_path, monkeypatch):
    from app.dependencies import recover_expired_relay_wakes
    from core.claude_wake import ClaudeWakeRegistry

    monkeypatch.setattr("app.codex_bridge_pipe.retained_wake_enabled", lambda: False)
    monkeypatch.setattr(codex_wake, "_DEBOUNCE_SECONDS", 0)
    monkeypatch.setattr(codex_wake.time, "sleep", lambda _: None)
    storage = client.app.state.pallium_service._storage
    relay = RelayService(storage)
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    app = FastAPI()
    app.include_router(build_router(client.app.state.pallium_service, relay_storage=storage,
                                   codex_wake_registry=registry))
    http = TestClient(app)
    for session in ("sender", "target"):
        assert http.post("/relay/turn", json={"runtime": "codex", "session_ref": session, **SCOPE}).status_code == 200

    original_begin = registry.begin_native_attempt
    fail_once = [True]
    def begin_with_one_pre_write_failure(reservation):
        if fail_once[0]:
            fail_once[0] = False
            raise RuntimeError("before native write")
        return original_begin(reservation)
    monkeypatch.setattr(registry, "begin_native_attempt", begin_with_one_pre_write_failure)
    launches = []
    monkeypatch.setattr(codex_wake, "_start_launch",
                        lambda *args: (launches.append(args), (None, ("queued", None, 0)))[1])
    workers = []
    original_schedule = codex_wake._schedule_reserved_codex_relay_wake
    def schedule(*args, **kwargs):
        worker = original_schedule(*args, **kwargs)
        workers.append(worker)
        return worker
    monkeypatch.setattr(codex_wake, "_schedule_reserved_codex_relay_wake", schedule)
    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", codex_wake.schedule_codex_relay_wake)

    sent = http.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": "codex:target", "message_id": "pre-cas-exception",
        "payload": "retry only before spend", **SCOPE,
    })
    assert sent.status_code == 200, sent.text
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    reservation = registry.snapshot(sent.json()["deliveries"][0]["recipient_endpoint_id"])
    assert reservation is not None and reservation.outcome == "prepared"
    assert launches == []

    recover_expired_relay_wakes(relay, ClaudeWakeRegistry(), codex_registry=registry)
    assert len(workers) == 2
    workers[-1].join(2)
    assert not workers[-1].is_alive()
    current = registry.snapshot(reservation.recipient_endpoint_id)
    assert current is not None and current.outcome == "accepted"
    assert current.generation == reservation.generation
    assert len(launches) == 1


@pytest.mark.parametrize("first_failure", ["thread_start", "retained_prewrite"])
def test_http_worker_start_or_prewrite_release_failure_resumes_same_generation_to_ack(client, tmp_path, monkeypatch, first_failure):
    from app.dependencies import recover_expired_relay_wakes
    from core.claude_wake import ClaudeWakeRegistry
    from core.relay_activation import ActivationAttemptResult
    from types import SimpleNamespace

    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", codex_wake.schedule_codex_relay_wake)
    monkeypatch.setattr(codex_wake, "_DEBOUNCE_SECONDS", 0)
    monkeypatch.setattr("app.codex_bridge_pipe.retained_wake_enabled",
                        lambda: first_failure == "retained_prewrite")
    storage = client.app.state.pallium_service._storage
    relay = RelayService(storage)
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    app = FastAPI()
    app.include_router(build_router(client.app.state.pallium_service, relay_storage=storage,
                                   codex_wake_registry=registry))
    http = TestClient(app)
    for session in ("sender", "target"):
        assert http.post("/relay/turn", json={"runtime": "codex", "session_ref": session, **SCOPE}).status_code == 200

    workers = []
    original_schedule = codex_wake._schedule_reserved_codex_relay_wake
    def capture_worker(*args, **kwargs):
        worker = original_schedule(*args, **kwargs)
        if worker is not None:
            workers.append(worker)
        return worker
    monkeypatch.setattr(codex_wake, "_schedule_reserved_codex_relay_wake", capture_worker)
    original_start = threading.Thread.start
    fail_start = [first_failure == "thread_start"]
    def start(thread, *args, **kwargs):
        if fail_start[0] and thread._target is codex_wake._wake_after_debounce:
            fail_start[0] = False
            raise RuntimeError("can't start new thread")
        return original_start(thread, *args, **kwargs)
    monkeypatch.setattr(threading.Thread, "start", start)

    original_transition = relay.codex_wake_transition
    fail_release = [True]
    def transition(operation, **kwargs):
        if operation == "release" and fail_release[0]:
            fail_release[0] = False
            raise RuntimeError("transient release failure")
        return original_transition(operation, **kwargs)
    monkeypatch.setattr(relay, "codex_wake_transition", transition)
    if first_failure == "retained_prewrite":
        registry.retained_service = SimpleNamespace(dispatch=lambda reservation, _registry: (
            ActivationAttemptResult("deferred", "target_not_idle", native_retry_safe=True),
            reservation,
        ))
    launches = []
    monkeypatch.setattr(codex_wake, "_start_launch",
                        lambda *args: (launches.append(args), (None, ("queued", None, 0)))[1])
    sent = http.post("/relay/messages", json={
        "sender_runtime": "codex", "sender_session_ref": "sender",
        "recipient": "codex:target", "message_id": f"worker-release-failure-{first_failure}",
        "payload": "recover without restart", **SCOPE,
    })
    assert sent.status_code == 200, sent.text
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    monkeypatch.setattr(threading.Thread, "start", original_start)
    monkeypatch.setattr(relay, "codex_wake_transition", original_transition)
    assert fail_release == [False]

    delivery = sent.json()["deliveries"][0]
    reservation = registry.snapshot(delivery["recipient_endpoint_id"])
    assert reservation is not None and reservation.outcome == "prepared"
    assert launches == []

    monkeypatch.setattr("app.codex_bridge_pipe.retained_wake_enabled", lambda: False)
    recover_expired_relay_wakes(relay, ClaudeWakeRegistry(), codex_registry=registry)
    expected_workers = 1 if first_failure == "thread_start" else 2
    assert len(workers) == expected_workers
    workers[-1].join(2)
    assert not workers[-1].is_alive()
    current = registry.snapshot(reservation.recipient_endpoint_id)
    assert current is not None and current.generation == reservation.generation
    assert current.outcome == "accepted"
    assert len(launches) == 1

    recover_expired_relay_wakes(relay, ClaudeWakeRegistry(), codex_registry=registry)
    assert len(workers) == expected_workers and len(launches) == 1

    claim = http.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target",
        "wake_delivery_id": delivery["delivery_id"], **SCOPE,
    })
    assert claim.status_code == 200, claim.text
    claimed = claim.json()["deliveries"][0]
    assert claimed["delivery_id"] == delivery["delivery_id"]
    assert claimed["payload"] == "recover without restart"
    ack = http.post("/relay/deliveries/ack", json={
        "delivery_id": delivery["delivery_id"],
        "claim_token": claimed["claim_token"], **SCOPE,
    })
    assert ack.status_code == 200, ack.text
    observed = http.get(f"/relay/messages/{sent.json()['message_id']}", params=SCOPE).json()["deliveries"][0]
    assert observed["state"] == "delivered" and observed["attempts"] == 1
    assert registry.snapshot(delivery["recipient_endpoint_id"]) is None


def test_draining_trace_queue_does_not_restore_sqlite_contention_drop(client):
    service = client.app.state.pallium_service
    storage = service._storage
    relay = RelayService(storage)
    for session in ("sender", "target"):
        relay.turn(runtime="codex", session_ref=session, **SCOPE)
    sent = relay.send(sender_runtime="codex", sender_session_ref="sender",
                      recipient="codex:target", payload="Trace contention", **SCOPE)
    delivery = sent["deliveries"][0]
    results = []

    def writer(event):
        result = relay.record_trace_event(event)
        results.append(result)
        return result

    def emit():
        codex_wake._emit_trace(
            lambda event: service.enqueue_relay_trace_event(writer, event),
            "relay-activation-" + "a" * 32,
            delivery["delivery_id"], delivery["recipient_endpoint_id"], "prepared",
        )

    database_args, connect_options = storage._relay_engine.dialect.create_connect_args(storage._relay_engine.url)
    with sqlite3.connect(*database_args, **connect_options) as competing:
        competing.execute("BEGIN IMMEDIATE")
        competing_file = competing.execute("PRAGMA database_list").fetchone()[2]
        with storage._relay_engine.connect() as observed:
            relay_file = observed.exec_driver_sql("PRAGMA database_list").fetchone()[2]
        diagnostics = {"database": database_args[0], "engine_database": storage._relay_engine.url.database,
                       "competing_file": competing_file, "relay_file": relay_file}
        assert Path(competing_file).samefile(relay_file), diagnostics
        assert competing.in_transaction, diagnostics
        with sqlite3.connect(*database_args, **{**connect_options, "timeout": 0}) as witness:
            with pytest.raises(sqlite3.OperationalError) as caught:
                witness.execute("BEGIN IMMEDIATE")
            assert caught.value.sqlite_errorcode == sqlite3.SQLITE_BUSY, diagnostics
        emit()
        service._relay_trace_executor.submit(lambda: None).result(timeout=2)
        assert competing.in_transaction, diagnostics
        assert results == [False], diagnostics
        competing.rollback()
    trace = client.get(f"/relay/messages/{sent['message_id']}/trace", params=SCOPE)
    assert trace.status_code == 200 and trace.json()["events"] == []
    emit()
    service._relay_trace_executor.submit(lambda: None).result(timeout=2)
    assert results == [False, True]
    trace = client.get(f"/relay/messages/{sent['message_id']}/trace", params=SCOPE)
    assert [event["stage"] for event in trace.json()["events"]] == ["prepared"]


def test_reconciliation_commits_replacement_before_worker_schedule(relay_store, tmp_path, monkeypatch):
    relay, _, database = relay_store
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    reservation = registry.begin_native_attempt(reservation)
    assert reservation is not None
    assert registry.record_outcome(reservation, "accepted")
    relay.turn(runtime="codex", session_ref="target", **SCOPE,
               exact_delivery_id=reservation.delivery_id,
               codex_wake_endpoint_id=reservation.recipient_endpoint_id,
               codex_wake_generation=reservation.generation,
               now=datetime.now(timezone.utc) - timedelta(seconds=RELAY_CLAIM_LEASE_SECONDS + 1))
    calls = []

    def schedule(item, actual_registry, **kwargs):
        with sqlite3.connect(database, timeout=0) as writer:
            writer.execute("BEGIN IMMEDIATE")
            assert actual_registry.snapshot(item.recipient_endpoint_id) == item
            writer.rollback()
        calls.append(item)

    monkeypatch.setattr(codex_wake, "_schedule_reserved_codex_relay_wake", schedule)
    assert codex_wake.reconcile_codex_relay_wake_reservations(relay, registry=registry) == 1
    assert len(calls) == 1 and calls[0].generation > reservation.generation


@pytest.mark.parametrize("state", ["delivered", "expired_claim"])
def test_imported_mismatched_recipient_fence_is_not_reconciled(
    relay_store, tmp_path, monkeypatch, state,
):
    relay, _, database = relay_store
    delivery = _send(relay)
    claim_time = datetime.now(timezone.utc)
    if state == "expired_claim":
        claim_time -= timedelta(seconds=RELAY_CLAIM_LEASE_SECONDS + 1)
    claimed = relay.turn(
        runtime="codex", session_ref="target", **SCOPE,
        exact_delivery_id=delivery["delivery_id"], now=claim_time,
    )["deliveries"][0]
    if state == "delivered":
        relay.ack_by_receipt(delivery_id=delivery["delivery_id"], receipt=claimed["receipt"], **SCOPE)
    item = replace(
        _item(delivery, outcome="uncertain"),
        recipient_endpoint_id="relay-session-" + "f" * 32,
        correlated_claim_attempts=1,
    )
    assert item.recipient_endpoint_id != delivery["recipient_endpoint_id"]
    path = _legacy(tmp_path / "legacy", [item])
    source = path.read_bytes()
    registry = _registry(relay, path.parent)
    assert registry.initialize(old_owner_drained=True)
    monkeypatch.setattr(
        codex_wake, "_schedule_reserved_codex_relay_wake",
        lambda *args, **kwargs: pytest.fail("mismatched recipient scheduled a wake"),
    )
    assert codex_wake.reconcile_codex_relay_wake_reservations(relay, registry=registry) == 0
    assert registry.snapshot(item.recipient_endpoint_id) == item
    assert _stored_items(database) == {item}
    assert path.read_bytes() == source


def test_release_waits_for_native_initiation_ownership(relay_store, tmp_path):
    relay, _, _ = relay_store
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    entered, finish, released = threading.Event(), threading.Event(), threading.Event()

    def native():
        entered.set()
        assert finish.wait(2)

    worker = threading.Thread(target=lambda: registry.run_if_current(reservation, native))
    release = threading.Thread(target=lambda: (registry.release_generation(reservation), released.set()))
    worker.start()
    assert entered.wait(2)
    release.start()
    try:
        assert not released.wait(.05)
    finally:
        finish.set()
        worker.join(2)
        release.join(2)
    assert released.is_set()
    assert registry.run_if_current(reservation, lambda: pytest.fail("stale native launch")) == (False, None)


def test_invalid_generation_authority_disables_native_launch(relay_store, tmp_path):
    relay, _, database = relay_store
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE relay_codex_wake_state SET generation=-1")
    assert not registry.usable
    assert registry.run_if_current(reservation, lambda: pytest.fail("invalid-authority native launch")) == (False, None)


def test_uninspectable_legacy_file_fails_closed(relay_store, tmp_path, monkeypatch):
    relay, _, database = relay_store
    directory = tmp_path / "legacy"
    registry = _registry(relay, directory)
    original = Path.open

    def denied(path, *args, **kwargs):
        if path == directory / "reservations.json":
            raise PermissionError("injected metadata denial")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", lambda path: False)
    monkeypatch.setattr(Path, "open", denied)
    assert not registry.initialize(old_owner_drained=True)
    assert not registry.usable
    _assert_uninitialized_database(database)


@pytest.mark.parametrize("root", [[], None, 1])
def test_non_object_legacy_input_fails_closed(relay_store, tmp_path, root):
    relay, _, database = relay_store
    path = _legacy(tmp_path / "legacy", [])
    path.write_text(json.dumps(root), encoding="utf-8")
    assert not _registry(relay, path.parent).initialize(old_owner_drained=True)
    _assert_uninitialized_database(database)


def test_wake_tables_are_only_in_relay_database(relay_store):
    _, _, database = relay_store
    with sqlite3.connect(database.with_name("main.db")) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "relay_codex_wake_reservations" not in tables
    assert "relay_codex_wake_state" not in tables


def test_maximum_legacy_unicode_rows_fit_bounded_import(relay_store, tmp_path):
    relay, _, database = relay_store
    rows = [CodexWakeReservation(
        recipient_endpoint_id=f"relay-session-{index:032x}",
        delivery_id=f"{index:04x}" + "😀" * 124,
        session_ref="😀" * 512, container_ref="😀" * 512, generation=index + 1,
    ) for index in range(256)]
    path = _legacy(tmp_path / "legacy", rows)
    assert _registry(relay, path.parent).initialize(old_owner_drained=True)
    assert _stored_items(database) == set(rows)


def test_authority_read_error_never_consults_legacy_after_migration(relay_store, tmp_path, monkeypatch):
    relay, _, _ = relay_store
    path = _legacy(tmp_path / "legacy", [])
    registry = _registry(relay, path.parent)
    assert registry.initialize(old_owner_drained=True)
    original_open = Path.open

    def trap(path_arg, *args, **kwargs):
        if path_arg == path:
            pytest.fail("unreadable authority caused legacy reimport")
        return original_open(path_arg, *args, **kwargs)

    def unavailable():
        raise OperationalError("SELECT", {}, sqlite3.OperationalError("injected read failure"))

    monkeypatch.setattr(relay, "codex_wake_snapshot", unavailable)
    monkeypatch.setattr(Path, "open", trap)
    assert not registry.initialize(old_owner_drained=True)


def test_natural_claim_wins_before_reserve_without_starting_worker(relay_store, tmp_path, monkeypatch):
    relay, _, _ = relay_store
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    delivery = _send(relay)
    relay.turn(runtime="codex", session_ref="target", **SCOPE)
    monkeypatch.setattr(codex_wake, "_schedule_reserved_codex_relay_wake", lambda *a, **kw: pytest.fail("active claim scheduled worker"))
    assert codex_wake.schedule_codex_relay_wake(
        {"recipient": "codex:target", "deliveries": [delivery]}, SCOPE,
        registry=registry, relay_service=relay,
    ) is None
    assert registry.reservations() == ()


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("operation", ["outcome", "correlate", "release", "reconcile"])
def test_ambiguous_settlement_keeps_durable_authority_and_prevents_reschedule(
    relay_store, tmp_path, monkeypatch, operation, committed,
):
    relay, storage, database = relay_store
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    if operation == "reconcile":
        relay.turn(runtime="codex", session_ref="target", **SCOPE,
                   exact_delivery_id=reservation.delivery_id,
                   codex_wake_endpoint_id=reservation.recipient_endpoint_id,
                   codex_wake_generation=reservation.generation,
                   now=datetime.now(timezone.utc) - timedelta(seconds=RELAY_CLAIM_LEASE_SECONDS + 1))
    original = storage._begin_relay_immediate

    @contextmanager
    def ambiguous():
        with original() as session:
            yield session
            if not committed:
                raise OperationalError("COMMIT", {}, sqlite3.OperationalError("before commit"))
        raise OperationalError("COMMIT", {}, sqlite3.OperationalError("after commit"))

    monkeypatch.setattr(storage, "_begin_relay_immediate", ambiguous)
    monkeypatch.setattr(codex_wake, "_schedule_reserved_codex_relay_wake", lambda *a, **kw: pytest.fail("ambiguous settlement scheduled worker"))
    if operation == "outcome":
        assert registry.begin_native_attempt(reservation) is None
    elif operation == "correlate":
        assert not registry.correlate_claim(
            delivery_id=reservation.delivery_id, recipient_endpoint_id=reservation.recipient_endpoint_id,
            session_ref=reservation.session_ref, container_ref=reservation.container_ref,
            attempts=1, expected_generation=reservation.generation,
        )
    elif operation == "release":
        assert not registry.release_generation(reservation)
    else:
        assert codex_wake.reconcile_codex_relay_wake_reservations(relay, registry=registry) == 0
    current = registry.snapshot(reservation.recipient_endpoint_id)
    assert _stored_items(database) == ({current} if current else set())
    if not committed:
        assert current == reservation
    elif operation == "release":
        assert current is None
    elif operation == "outcome":
        assert current == replace(reservation, outcome="uncertain", retry_not_before=current.retry_not_before)
        assert current.retry_not_before is not None
    elif operation == "correlate":
        assert current == replace(reservation, correlated_claim_attempts=1)
    else:
        assert current.generation > reservation.generation
        assert replace(current, generation=reservation.generation) == reservation
    # A committed stale generation can never initiate native I/O.
    if committed:
        assert registry.run_if_current(reservation, lambda: pytest.fail("stale generation launch")) == (False, None)


@pytest.mark.parametrize("committed", [False, True])
def test_reserve_failure_never_starts_worker_or_native_effect(relay_store, tmp_path, monkeypatch, committed):
    relay, storage, _ = relay_store
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    delivery = _send(relay)
    original = storage._begin_relay_immediate

    @contextmanager
    def ambiguous():
        with original() as session:
            yield session
            if not committed:
                raise OperationalError("COMMIT", {}, sqlite3.OperationalError("before commit"))
        raise OperationalError("COMMIT", {}, sqlite3.OperationalError("after commit"))

    monkeypatch.setattr(storage, "_begin_relay_immediate", ambiguous)
    monkeypatch.setattr(codex_wake, "_schedule_reserved_codex_relay_wake", lambda *a, **kw: pytest.fail("failed reserve scheduled worker"))
    monkeypatch.setattr(codex_wake, "_start_launch", lambda *a, **kw: pytest.fail("failed reserve native launch"))
    assert codex_wake.schedule_codex_relay_wake(
        {"recipient": "codex:target", "deliveries": [delivery]}, SCOPE,
        registry=registry, relay_service=relay,
    ) is None
    assert (registry.snapshot(delivery["recipient_endpoint_id"]) is not None) is committed


@pytest.fixture
def relay_store(tmp_path):
    database = tmp_path / "relay.db"
    storage = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'main.db'}", f"sqlite:///{database}")
    try:
        yield RelayService(storage), storage, database
    finally:
        storage.close()


def _send(relay, target="target"):
    for session in ("sender", target):
        relay.turn(runtime="codex", session_ref=session, **SCOPE)
    return relay.send(
        sender_runtime="codex", sender_session_ref="sender",
        recipient=f"codex:{target}", payload="A bounded message", **SCOPE,
    )["deliveries"][0]


def _item(delivery, *, target="target", generation=1, outcome="reserved"):
    return CodexWakeReservation(
        recipient_endpoint_id=delivery["recipient_endpoint_id"],
        delivery_id=delivery["delivery_id"], session_ref=target,
        container_ref=SCOPE["container_ref"], generation=generation, outcome=outcome,
    )


def _legacy_row(item):
    row = asdict(item)
    row.pop("retry_not_before", None)
    return row


def _legacy(directory, items, *, version=2):
    directory.mkdir(parents=True, exist_ok=True)
    rows = [_legacy_row(item) for item in items]
    if version == 1:
        for row in rows:
            row.pop("correlated_claim_attempts")
    path = directory / "reservations.json"
    path.write_text(json.dumps({"version": version, "reservations": rows}), encoding="utf-8")
    return path


def _registry(relay, directory):
    # Migration is explicit; this construction must never import or dispatch.
    return CodexWakeRegistry(relay_service=relay, legacy_state_dir=directory)


def _reserve(registry, delivery, target="target"):
    return registry.reserve(
        recipient_endpoint_id=delivery["recipient_endpoint_id"],
        delivery_id=delivery["delivery_id"], session_ref=target, **SCOPE,
    )


def _stored_items(database):
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        return {
            CodexWakeReservation(**dict(row))
            for row in connection.execute(
                "SELECT recipient_endpoint_id, delivery_id, session_ref, container_ref, "
                "generation, outcome, correlated_claim_attempts, retry_not_before "
                "FROM relay_codex_wake_reservations"
            )
        }


def _assert_uninitialized_database(database):
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM relay_codex_wake_reservations").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM relay_codex_wake_state").fetchone() == (0,)


def test_schema_bootstrap_does_not_claim_completed_legacy_import(relay_store):
    _, _, database = relay_store
    _assert_uninitialized_database(database)


def test_import_requires_verified_old_owner_drain_and_preserves_source(relay_store, tmp_path):
    relay, _, database = relay_store
    item = _item(_send(relay), outcome="uncertain")
    path = _legacy(tmp_path / "legacy", [item])
    source = path.read_bytes()
    registry = _registry(relay, path.parent)
    assert not registry.usable
    assert not registry.initialize(old_owner_drained=False)
    assert registry.reservations() == ()
    _assert_uninitialized_database(database)
    assert not _registry(relay, path.parent).usable
    # The offline caller obtains this precondition from strict stop/drain proof.
    assert registry.initialize(old_owner_drained=True)
    assert registry.reservations() == (item,)
    assert _stored_items(database) == {item}
    assert path.read_bytes() == source


@pytest.mark.parametrize("version", [1, 2])
def test_import_preserves_all_outcomes_and_marker_prevents_resurrection(
    relay_store, tmp_path, version,
):
    relay, _, database = relay_store
    items = [
        _item(_send(relay, target), target=target, generation=index + 11, outcome=outcome)
        for index, (target, outcome) in enumerate(
            (("reserved", "reserved"), ("accepted", "accepted"), ("uncertain", "uncertain"))
        )
    ]
    if version == 2:
        items[1] = replace(items[1], correlated_claim_attempts=2)
    path = _legacy(tmp_path / "legacy", items, version=version)
    source = path.read_bytes()
    registry = _registry(relay, path.parent)
    assert registry.initialize(old_owner_drained=True)
    assert set(registry.reservations()) == set(items)
    assert _stored_items(database) == set(items)
    assert registry.release_delivery(items[0].delivery_id) == items[0]
    assert path.read_bytes() == source
    # Completed migration never consults or imports a stale leftover file again.
    path.write_text("{", encoding="utf-8")
    restarted = _registry(relay, path.parent)
    assert restarted.usable
    assert restarted.initialize(old_owner_drained=False)
    assert set(restarted.reservations()) == set(items[1:])
    assert _stored_items(database) == set(items[1:])


def test_explicit_empty_initialization_and_stored_claim_generation_high_water(
    relay_store, tmp_path,
):
    relay, _, database = relay_store
    prior = _send(relay, "previous")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE relay_deliveries SET codex_wake_generation = 800 WHERE id = ?",
            (prior["delivery_id"],),
        )
    registry = _registry(relay, tmp_path / "absent-legacy")
    assert not registry.usable
    assert registry.initialize(old_owner_drained=True)
    current = _reserve(registry, _send(relay))
    assert current is not None and current.generation > 800
    assert not (tmp_path / "absent-legacy").exists()


@pytest.mark.parametrize("bad_input", ["corrupt", "duplicate_endpoint", "duplicate_delivery", "invalid_outcome", "invalid_generation", "unsupported_version", "over_capacity"])
def test_invalid_legacy_import_leaves_no_marker_or_partial_rows(relay_store, tmp_path, bad_input):
    relay, _, database = relay_store
    item = _item(_send(relay), outcome="accepted")
    path = _legacy(tmp_path / "legacy", [item])
    data = json.loads(path.read_text(encoding="utf-8"))
    if bad_input == "corrupt":
        path.write_text("{", encoding="utf-8")
    else:
        if bad_input == "invalid_outcome":
            data["reservations"][0]["outcome"] = "failed"
        elif bad_input == "invalid_generation":
            data["reservations"][0]["generation"] = True
        elif bad_input == "unsupported_version":
            data["version"] = 3
        elif bad_input == "over_capacity":
            data["reservations"] = [
                {**_legacy_row(item), "recipient_endpoint_id": f"relay-session-{index:032x}",
                 "delivery_id": f"relay-delivery-{index:032x}"}
                for index in range(257)
            ]
        else:
            duplicate = _legacy_row(item)
            duplicate["delivery_id" if bad_input == "duplicate_endpoint" else "recipient_endpoint_id"] = (
                "relay-delivery-" + "e" * 32 if bad_input == "duplicate_endpoint" else "relay-session-" + "e" * 32
            )
            data["reservations"].append(duplicate)
        path.write_text(json.dumps(data), encoding="utf-8")
    source = path.read_bytes()
    registry = _registry(relay, path.parent)
    assert not registry.initialize(old_owner_drained=True)
    assert not registry.usable and registry.reservations() == ()
    _assert_uninitialized_database(database)
    assert not _registry(relay, path.parent).usable
    assert path.read_bytes() == source


@pytest.mark.parametrize("count", [0, 256])
def test_empty_and_maximum_legacy_files_migrate_without_discarding_fences(
    relay_store, tmp_path, count,
):
    relay, _, _ = relay_store
    items = [
        CodexWakeReservation(
            recipient_endpoint_id=f"relay-session-{index:032x}",
            delivery_id=f"relay-delivery-{index:032x}", session_ref=f"target-{index}",
            container_ref=SCOPE["container_ref"], generation=index + 1, outcome="uncertain",
        )
        for index in range(count)
    ]
    # Unresolved legacy references are preserved, not filtered/cascaded away.
    path = _legacy(tmp_path / "legacy", items)
    registry = _registry(relay, path.parent)
    assert registry.initialize(old_owner_drained=True)
    assert set(registry.reservations()) == set(items)


def test_unreadable_legacy_file_cannot_be_mistaken_for_empty_initialization(
    relay_store, tmp_path, monkeypatch,
):
    relay, _, _ = relay_store
    path = _legacy(tmp_path / "legacy", [])
    original = Path.open

    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError("injected unreadable legacy state")
        return original(self, *args, **kwargs)

    registry = _registry(relay, path.parent)
    with monkeypatch.context() as fault:
        fault.setattr(Path, "open", denied)
        assert not registry.initialize(old_owner_drained=True)
    assert not registry.usable and registry.reservations() == ()
    assert not _registry(relay, path.parent).usable


def test_import_rows_and_marker_rollback_together_on_transaction_failure(
    relay_store, tmp_path, monkeypatch,
):
    relay, storage, database = relay_store
    item = _item(_send(relay), outcome="accepted")
    path = _legacy(tmp_path / "legacy", [item])
    original = storage._begin_relay_immediate

    @contextmanager
    def fail_before_commit():
        with original() as session:
            yield session
            raise OperationalError("COMMIT", {}, sqlite3.OperationalError("injected disk error"))

    registry = _registry(relay, path.parent)
    with monkeypatch.context() as fault:
        fault.setattr(storage, "_begin_relay_immediate", fail_before_commit)
        assert not registry.initialize(old_owner_drained=True)
    reopened = _registry(relay, path.parent)
    assert not reopened.usable and reopened.reservations() == ()
    _assert_uninitialized_database(database)
    assert reopened.initialize(old_owner_drained=True)
    assert reopened.reservations() == (item,)


def test_database_busy_defers_reserve_without_disabling_later_attempts(relay_store, tmp_path):
    relay, _, database = relay_store
    delivery = _send(relay)
    registry = _registry(relay, tmp_path / "absent-legacy")
    assert registry.initialize(old_owner_drained=True)
    with sqlite3.connect(database, timeout=0) as blocked_writer:
        blocked_writer.execute("BEGIN IMMEDIATE")
        assert _reserve(registry, delivery) is None
        assert registry.reservations() == ()
        blocked_writer.rollback()
    reservation = _reserve(registry, delivery)
    assert reservation is not None
    assert _registry(relay, tmp_path / "absent-legacy").snapshot(reservation.recipient_endpoint_id) == reservation


def test_committed_import_survives_return_failure_without_reimport(
    relay_store, tmp_path, monkeypatch,
):
    relay, storage, _ = relay_store
    item = _item(_send(relay), outcome="uncertain")
    path = _legacy(tmp_path / "legacy", [item])
    original = storage._begin_relay_immediate

    @contextmanager
    def commit_then_fail():
        with original() as session:
            yield session
        raise OperationalError("COMMIT", {}, sqlite3.OperationalError("injected return failure"))

    registry = _registry(relay, path.parent)
    with monkeypatch.context() as fault:
        fault.setattr(storage, "_begin_relay_immediate", commit_then_fail)
        registry.initialize(old_owner_drained=True)
    path.write_text("{", encoding="utf-8")
    reopened = _registry(relay, path.parent)
    assert reopened.usable
    assert reopened.initialize(old_owner_drained=False)
    assert reopened.reservations() == (item,)


def test_native_initiation_runs_after_sql_commit_and_stale_generation_cannot_submit(
    relay_store, tmp_path,
):
    relay, _, database = relay_store
    registry = _registry(relay, tmp_path / "absent-legacy")
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
    assert reservation is not None
    calls = []

    def fake_native_initiation():
        # A second writer acquires immediately; no SQL write transaction spans native I/O.
        with sqlite3.connect(database, timeout=0) as second_writer:
            second_writer.execute("BEGIN IMMEDIATE")
            persisted = _registry(relay, tmp_path / "absent-legacy").snapshot(reservation.recipient_endpoint_id)
            assert persisted == spent[-1]
            second_writer.rollback()
        calls.append(reservation.generation)
        return "initiated"

    spent = []
    def fenced_native_initiation():
        current = registry.begin_native_attempt(reservation)
        assert current is not None
        spent.append(current)
        return fake_native_initiation()
    assert registry.run_if_current(reservation, fenced_native_initiation) == (True, "initiated")
    assert registry.record_outcome(spent[0], "accepted")
    claim = relay.turn(
        runtime="codex", session_ref=reservation.session_ref, **SCOPE,
        exact_delivery_id=reservation.delivery_id,
        codex_wake_endpoint_id=reservation.recipient_endpoint_id,
        codex_wake_generation=reservation.generation,
        now=datetime.now(timezone.utc) - timedelta(seconds=RELAY_CLAIM_LEASE_SECONDS + 1),
    )["deliveries"][0]
    assert registry.correlate_claim(
        delivery_id=reservation.delivery_id,
        recipient_endpoint_id=reservation.recipient_endpoint_id,
        session_ref=reservation.session_ref, container_ref=reservation.container_ref,
        attempts=claim["attempts"], expected_generation=reservation.generation,
    )
    current = registry.snapshot(reservation.recipient_endpoint_id)
    assert current is not None and current.correlated_claim_attempts == claim["attempts"]
    evidence = relay.codex_wake_reservation_state(delivery_id=reservation.delivery_id)
    assert evidence["state"] == "pending" and evidence["stored_state"] == "claimed"
    assert evidence["codex_wake_generation"] == current.generation
    replacement = registry.replace_generation(
        current, session_ref=current.session_ref, container_ref=current.container_ref,
    )
    assert replacement is not None and replacement.generation > reservation.generation
    assert replacement.outcome == "reserved"
    assert registry.begin_native_attempt(replacement) is None
    assert registry.run_if_current(reservation, fake_native_initiation) == (False, None)
    assert not registry.record_outcome(reservation, "accepted")
    assert not registry.release_generation(reservation)
    assert registry.release_generation(replacement)
    assert registry.run_if_current(replacement, fake_native_initiation) == (False, None)
    assert calls == [reservation.generation]
