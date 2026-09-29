from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sqlite3
import threading

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
    storage = client.app.state.pallium_service._storage
    relay = RelayService(storage)
    directory = tmp_path / "legacy"
    registry = _registry(relay, directory)
    assert registry.initialize(old_owner_drained=True)
    workers, native_calls = [], []
    original_schedule = codex_wake._schedule_reserved_codex_relay_wake

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
    assert restarted.snapshot(current.recipient_endpoint_id).correlated_claim_attempts == claimed["attempts"]
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


def test_reconciliation_commits_replacement_before_worker_schedule(relay_store, tmp_path, monkeypatch):
    relay, _, database = relay_store
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)
    reservation = _reserve(registry, _send(relay))
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
        assert not registry.record_outcome(reservation, "uncertain")
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
        assert current == replace(reservation, outcome="uncertain")
    elif operation == "correlate":
        assert current == replace(reservation, correlated_claim_attempts=1)
    else:
        assert current.generation > reservation.generation
        assert current.outcome == "reserved"
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


def _legacy(directory, items, *, version=2):
    directory.mkdir(parents=True, exist_ok=True)
    rows = [asdict(item) for item in items]
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
                "generation, outcome, correlated_claim_attempts FROM relay_codex_wake_reservations"
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
                {**asdict(item), "recipient_endpoint_id": f"relay-session-{index:032x}",
                 "delivery_id": f"relay-delivery-{index:032x}"}
                for index in range(257)
            ]
        else:
            duplicate = {**asdict(item)}
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
            assert persisted == reservation
            second_writer.rollback()
        calls.append(reservation.generation)
        return "initiated"

    assert registry.run_if_current(reservation, fake_native_initiation) == (True, "initiated")
    assert registry.record_outcome(reservation, "accepted")
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
    assert registry.run_if_current(reservation, fake_native_initiation) == (False, None)
    assert not registry.record_outcome(reservation, "accepted")
    assert not registry.release_generation(reservation)
    assert registry.release_generation(replacement)
    assert registry.run_if_current(replacement, fake_native_initiation) == (False, None)
    assert calls == [reservation.generation]
