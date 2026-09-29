from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy.exc import OperationalError

from core.codex_wake import CodexWakeRegistry, CodexWakeReservation
from core.relay import RELAY_CLAIM_LEASE_SECONDS, RelayService
from storage.sqlite import SQLiteStorageProvider


SCOPE = {"container_ref": "git:example.test/wake-東京"}


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
