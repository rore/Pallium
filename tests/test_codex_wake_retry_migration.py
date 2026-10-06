from __future__ import annotations

import sqlite3

import pytest

from core.relay import RelayService
from storage.sqlite import SQLiteStorageProvider
from tests.test_codex_wake_sqlite import _registry, _reserve, _send


@pytest.mark.parametrize("isolated_relay", [False, True], ids=["shared", "isolated"])
def test_retry_cooldown_column_migrates_existing_reservations(
    tmp_path, isolated_relay,
):
    main_db = tmp_path / "main.db"
    relay_db = tmp_path / "relay.db" if isolated_relay else main_db
    urls = (f"sqlite:///{main_db}", f"sqlite:///{relay_db}")
    storage = SQLiteStorageProvider(*urls)
    relay = RelayService(storage)
    registry = _registry(relay, tmp_path / "legacy")
    assert registry.initialize(old_owner_drained=True)

    expected = {}
    for target, outcome in (("accepted", "accepted"), ("uncertain", "uncertain")):
        delivery = _send(relay, target)
        reservation = _reserve(registry, delivery, target)
        assert reservation is not None
        prepared = registry.begin_native_attempt(reservation)
        assert prepared is not None
        assert registry.record_outcome(prepared, outcome)
        expected[reservation.recipient_endpoint_id] = (delivery["delivery_id"], outcome)
    storage.close()

    with sqlite3.connect(relay_db) as connection:
        connection.execute(
            "ALTER TABLE relay_codex_wake_reservations DROP COLUMN retry_not_before"
        )

    for _ in range(2):
        reopened = SQLiteStorageProvider(*urls)
        try:
            restarted = _registry(RelayService(reopened), tmp_path / "legacy")
            actual = {item.recipient_endpoint_id: item for item in restarted.reservations()}
            assert {
                endpoint: (item.delivery_id, item.outcome)
                for endpoint, item in actual.items()
            } == expected
            assert all(item.retry_not_before is None for item in actual.values())
        finally:
            reopened.close()
