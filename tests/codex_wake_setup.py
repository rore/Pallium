"""Opt-in empty offline setup for functional journeys, with native refusal guards."""

from pathlib import Path
import sqlite3

from core.errors import ImmediateTransactionBusyError


def initialize_empty_wake_registry(
    registry, relay, storage, *, expected_database, legacy, monkeypatch, force_refusal=False,
):
    database = Path(storage._relay_engine.url.database)
    assert database == expected_database

    def absent_legacy():
        if legacy is None:
            assert registry._path is None
        else:
            assert not legacy.exists()

    absent_legacy()
    original_initialize = relay.codex_wake_initialize
    attempts = []

    def observe_initialize(reservations):
        assert reservations == ()
        attempt = {}
        attempts.append(attempt)
        try:
            if force_refusal and len(attempts) == 1:
                raise ImmediateTransactionBusyError('controlled empty setup refusal', acquisition_stage='setup_deadline')
            result = original_initialize(reservations)
        except Exception as error:
            attempt['error'] = error
            raise
        attempt['result'] = result
        return result

    # Empty offline setup may repeat only a proven precommit acquisition refusal.
    with monkeypatch.context() as setup_patch:
        setup_patch.setattr(relay, 'codex_wake_initialize', observe_initialize)
        initialized = registry.initialize(old_owner_drained=True)
        if initialized is False and len(attempts) == 1 and type(attempts[0].get('error')) is ImmediateTransactionBusyError:
            assert relay.codex_wake_snapshot() == (False, ())
            absent_legacy()
            with sqlite3.connect(database) as db:
                assert db.execute('SELECT count(*) FROM relay_sessions').fetchone() == (0,)
                assert db.execute('SELECT count(*) FROM relay_deliveries').fetchone() == (0,)
            initialized = registry.initialize(old_owner_drained=True)
        assert initialized is True
        assert attempts[-1] == {'result': True}
        assert len(attempts) == 1 or (len(attempts) == 2 and type(attempts[0].get('error')) is ImmediateTransactionBusyError)
    assert relay.codex_wake_initialize == original_initialize
