"""Managed expiry through the cleaner CLI and the normal Relay HTTP read path."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app import relay_expiry_cleaner
from app.relay_expiry_cleaner import run_cleaner
import storage.sqlite_relay as relay_storage
from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import RelayMessageRecord


SCOPE = {"container_ref": "git:example.test/managed-expiry-東京"}


@pytest.fixture(autouse=True)
def expiry_clock(monkeypatch):
    # Keep HTTP reads before message expiry: they must observe, not perform, cleanup.
    cutoff = datetime.now(timezone.utc) + timedelta(days=1)

    class MaintenanceClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cutoff.astimezone(tz) if tz is not None else cutoff.replace(tzinfo=None)

    monkeypatch.setattr(relay_expiry_cleaner, "datetime", MaintenanceClock)
    return cutoff


def _future_turn(client, monkeypatch, cutoff, **options):
    normalize = relay_storage._now
    with monkeypatch.context() as clock:
        clock.setattr(relay_storage, "_now", lambda now=None: cutoff if now is None else normalize(now))
        return client.post("/relay/turn", json={
            "runtime": "codex", "session_ref": "target", **options, **SCOPE,
        })


def _messages(client, count):
    for session in ("sender", "target"):
        response = client.post("/relay/turn", json={
            "runtime": "codex", "session_ref": session, **SCOPE,
        })
        assert response.status_code == 200, response.text
    messages = []
    for number in range(count):
        response = client.post("/relay/messages", json={
            "sender_runtime": "codex", "sender_session_ref": "sender",
            "recipient": "codex:target", "payload": f"bounded expiry {number} 東京", **SCOPE,
        })
        assert response.status_code == 200, response.text
        messages.append(response.json()["message_id"])
    storage = client.app.state.pallium_service._storage
    with storage._relay_session_factory.begin() as session:
        session.execute(update(RelayMessageRecord).where(RelayMessageRecord.id.in_(messages)).values(
            expires_at=datetime.max.replace(tzinfo=timezone.utc),
        ))
    return messages


def _states(client, messages):
    states = []
    for message_id in messages:
        response = client.get(f"/relay/messages/{message_id}", params=SCOPE)
        assert response.status_code == 200, response.text
        states.extend(row["state"] for row in response.json()["deliveries"])
    return states


def _expire(storage, messages):
    with storage._relay_session_factory.begin() as session:
        session.execute(update(RelayMessageRecord).where(RelayMessageRecord.id.in_(messages)).values(
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))


def _once(database_url):
    return run_cleaner(["--database-url", database_url, "--once"], install_signal_handlers=False)


def test_managed_turn_defers_expiry_to_existing_database_cleaner(client, monkeypatch, expiry_clock):
    storage = client.app.state.pallium_service._storage
    database_url = str(storage._relay_engine.url)
    messages = _messages(client, 2)
    storage.enable_managed_relay_expiry(database_url)
    _expire(storage, messages[:1])
    response = _future_turn(client, monkeypatch, expiry_clock, max_response_chars=1)
    assert response.status_code == 200, response.text
    assert _states(client, messages[:1]) == ["pending"]

    def no_migration(*_args, **_kwargs):
        pytest.fail("maintenance must not initialize or migrate schema")

    monkeypatch.setattr(SQLiteStorageProvider, "_initialize_schema", no_migration)
    monkeypatch.setattr(SQLiteStorageProvider, "_initialize_relay_schema", no_migration)
    assert _once(database_url) == 0
    assert _states(client, messages) == ["expired", "pending"]
    assert _once(database_url) == 0
    assert _states(client, messages) == ["expired", "pending"]
    response = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target", **SCOPE,
    })
    assert response.status_code == 200, response.text
    assert len(response.json()["deliveries"]) == 1
    assert _states(client, messages) == ["expired", "claimed"]


@pytest.mark.parametrize("count", (0, 1, 64, 65))
def test_cleaner_once_is_one_bounded_window_and_continuous_sweep_finishes(client, count):
    storage = client.app.state.pallium_service._storage
    database_url = str(storage._relay_engine.url)
    messages = _messages(client, count)
    _expire(storage, messages)
    assert _once(database_url) == 0
    states = _states(client, messages)
    assert states.count("expired") == min(count, 64)
    assert states.count("pending") == max(0, count - 64)
    # A fresh --once invocation starts a fresh scan; only continuous mode retains its cursor.
    stopped, sleeps = [False], []

    def yield_window(delay):
        sleeps.append(delay)
        if len(sleeps) == 2:
            stopped[0] = True

    assert run_cleaner(["--database-url", database_url], sleep_fn=yield_window,
                      should_stop=lambda: stopped[0], install_signal_handlers=False) == 0
    assert _states(client, messages) == ["expired"] * count


@pytest.mark.parametrize("limit", (0, -1, 65, True, 1.5))
def test_expiry_window_rejects_invalid_limits_without_mutation(client, limit):
    storage = client.app.state.pallium_service._storage
    messages = _messages(client, 1)
    _expire(storage, messages)
    with pytest.raises(ValueError, match="limit"):
        storage.relay_expire_window(limit=limit)
    assert _states(client, messages) == ["pending"]


@pytest.mark.parametrize("cursors", ({"after_id": ""}, {"upper_id": ""}, {"after_id": 1}, {"upper_id": False}))
def test_expiry_window_rejects_invalid_cursors_without_mutation(client, cursors):
    storage = client.app.state.pallium_service._storage
    messages = _messages(client, 1)
    _expire(storage, messages)
    with pytest.raises(ValueError, match="cursors"):
        storage.relay_expire_window(**cursors)
    assert _states(client, messages) == ["pending"]


def test_expiry_window_cancellation_rolls_back_and_resume_preserves_scan_cursor(client, expiry_clock):
    storage = client.app.state.pallium_service._storage
    messages = _messages(client, 3)
    _expire(storage, messages)
    checks = []

    def stopping_after_mutation():
        checks.append(None)
        return len(checks) == 3

    with pytest.raises(InterruptedError):
        storage.relay_expire_window(limit=1, cutoff=expiry_clock, should_stop=stopping_after_mutation)
    assert _states(client, messages) == ["pending"] * 3
    after_id = upper_id = None
    cutoff = expiry_clock
    scanned = expired = 0
    while True:
        result = storage.relay_expire_window(after_id=after_id, upper_id=upper_id, cutoff=cutoff, limit=1)
        after_id, upper_id = result["after_id"], result["upper_id"]
        scanned += result["scanned"]
        expired += result["expired"]
        if result["sweep_complete"]:
            break
        assert scanned < 3
    assert scanned == expired == 3
    assert _states(client, messages) == ["expired"] * 3


@pytest.mark.parametrize("database", ("sqlite:///:memory:", "sqlite:///{missing}", "sqlite:///file:{missing}?uri=true"))
def test_cleaner_rejects_nonexisting_or_nonfile_database_without_creating_it(tmp_path, database):
    missing = tmp_path / "missing-東京.db"
    assert _once(database.format(missing=missing.as_posix())) == 1
    assert not missing.exists()


def test_managed_enablement_rejects_other_database_and_leaves_inline_expiry_enabled(client, tmp_path, monkeypatch, expiry_clock):
    storage = client.app.state.pallium_service._storage
    messages = _messages(client, 1)
    with pytest.raises(ValueError, match="actual file-backed"):
        storage.enable_managed_relay_expiry(f"sqlite:///{tmp_path / 'other.db'}")
    assert storage._relay_expiry_managed is False
    _expire(storage, messages)
    response = _future_turn(client, monkeypatch, expiry_clock)
    assert response.status_code == 200, response.text
    assert _states(client, messages) == ["expired"]


@pytest.mark.parametrize("contents", (b"", b"not a SQLite database"))
def test_cleaner_rejects_existing_invalid_schema_without_rewriting_database(tmp_path, contents):
    database = tmp_path / "incomplete-東京.db"
    database.write_bytes(contents)
    assert _once(f"sqlite:///{database}") == 1
    assert database.read_bytes() == contents


def test_cleaner_stop_before_open_acquires_nothing(monkeypatch):
    def unexpected_open(_database):
        pytest.fail("stop before startup must not acquire storage")

    monkeypatch.setattr(SQLiteStorageProvider, "open_relay_maintenance", staticmethod(unexpected_open))
    assert run_cleaner(["--database-url", "sqlite:///unused.db"], should_stop=lambda: True,
                       install_signal_handlers=False) == 0


@pytest.mark.parametrize("contention", (False, True))
def test_cleaner_cli_failure_closes_its_storage_once_without_logging_error_text(monkeypatch, capsys, contention):
    import sqlite3

    class FailingStorage:
        calls = closed = 0

        def relay_expire_window(self, **_kwargs):
            self.calls += 1
            if contention:
                raise sqlite3.OperationalError("database is locked")
            raise ValueError("controlled-sensitive-error-text")

        def close(self):
            self.closed += 1

    storage = FailingStorage()
    monkeypatch.setattr(SQLiteStorageProvider, "open_relay_maintenance", staticmethod(lambda _url: storage))
    assert _once("sqlite:///unused.db") == 1
    assert storage.calls == storage.closed == 1
    output = capsys.readouterr()
    assert "controlled-sensitive-error-text" not in output.out + output.err


def _owned_maintenance(client, monkeypatch):
    database_url = str(client.app.state.pallium_service._storage._relay_engine.url)
    maintenance = SQLiteStorageProvider.open_relay_maintenance(database_url)
    original_close = maintenance.close
    closed = []

    def close():
        closed.append(True)
        original_close()

    def open_existing(expected):
        assert expected == database_url
        return maintenance

    monkeypatch.setattr(maintenance, "close", close)
    monkeypatch.setattr(SQLiteStorageProvider, "open_relay_maintenance", staticmethod(open_existing))
    return database_url, maintenance, closed


@pytest.mark.parametrize("cleanup_raises", (False, True))
def test_cleaner_window_acquisition_failure_closes_session_and_preserves_original_error(
    client, monkeypatch, expiry_clock, cleanup_raises,
):
    storage = client.app.state.pallium_service._storage
    messages = _messages(client, 1)
    _expire(storage, messages)
    database_url, maintenance, closed = _owned_maintenance(client, monkeypatch)
    sentinel = RuntimeError("controlled acquisition failure")
    observed, sessions_closed = [], []

    class FailedSession:
        def connection(self, **options):
            assert options == {"execution_options": {"isolation_level": "AUTOCOMMIT"}}
            raise sentinel

        def close(self):
            sessions_closed.append(True)
            if cleanup_raises:
                raise RuntimeError("controlled session cleanup failure")

    original_window = maintenance.relay_expire_window

    def window(**kwargs):
        try:
            return original_window(**kwargs)
        except BaseException as error:
            observed.append(error)
            raise

    monkeypatch.setattr(maintenance, "_relay_session_factory", FailedSession)
    monkeypatch.setattr(maintenance, "relay_expire_window", window)
    assert _once(database_url) == 1
    assert len(observed) == 1 and observed[0] is sentinel
    assert sessions_closed == [True]
    assert closed == [True]
    assert _states(client, messages) == ["pending"]


@pytest.mark.parametrize("fault", ("busy", "transient"))
@pytest.mark.parametrize("failures_per_window", (1, 9))
def test_cleaner_continuous_recovery_preserves_cursor_and_resets_error_budget(
    client, monkeypatch, expiry_clock, capsys, fault, failures_per_window,
):
    import sqlite3

    storage = client.app.state.pallium_service._storage
    messages = _messages(client, 2)
    _expire(storage, messages)
    database_url, maintenance, closed = _owned_maintenance(client, monkeypatch)
    original_window = maintenance.relay_expire_window
    calls, sleeps = [], []
    progress = {"failures": 0, "pages": 0, "stopped": False}

    def window(**kwargs):
        calls.append(dict(kwargs))
        assert len(calls) <= 2 * (failures_per_window + 1)
        assert kwargs["limit"] == 64
        if progress["failures"] < failures_per_window:
            progress["failures"] += 1
            if fault == "busy":
                error = sqlite3.OperationalError("controlled-sensitive-error-text")
                error.sqlite_errorcode = sqlite3.SQLITE_BUSY | (1 << 8)
            else:
                error = sqlite3.OperationalError("disk I/O error: controlled-sensitive-error-text")
            raise error
        # Use the real window's supported one-row bound to exercise multiple CLI cursors.
        result = original_window(**{**kwargs, "limit": 1})
        progress["failures"] = 0
        progress["pages"] += 1
        progress["stopped"] = result["sweep_complete"]
        return result

    monkeypatch.setattr(maintenance, "relay_expire_window", window)
    result = run_cleaner(["--database-url", database_url], sleep_fn=sleeps.append,
                         should_stop=lambda: progress["stopped"], install_signal_handlers=False)
    assert result == 0
    assert progress["pages"] == 2 and closed == [True]
    assert len(calls) == 2 * (failures_per_window + 1)
    for start in (0, failures_per_window + 1):
        batch = calls[start:start + failures_per_window + 1]
        cursors = [(item["after_id"], item["upper_id"], item["cutoff"]) for item in batch]
        assert cursors == [cursors[0]] * len(cursors)
    assert calls[0]["after_id"] is None and calls[0]["upper_id"] is None
    assert calls[failures_per_window + 1]["after_id"] is not None
    assert calls[failures_per_window + 1]["upper_id"] is not None
    assert all(item["cutoff"] == expiry_clock for item in calls)
    assert sleeps.count(0.25) == 2 * failures_per_window and sleeps.count(0.05) == 1
    assert _states(client, messages) == ["expired", "expired"]
    output = capsys.readouterr()
    text = output.out + output.err
    assert "outcome=resumed" in text
    assert ("outcome=deferred" if fault == "busy" else "outcome=transient_error") in text
    assert "controlled-sensitive-error-text" not in text


def test_cleaner_continuous_transient_limit_preserves_committed_progress_and_closes(
    client, monkeypatch, expiry_clock, capsys,
):
    import sqlite3

    storage = client.app.state.pallium_service._storage
    messages = _messages(client, 2)
    _expire(storage, messages)
    database_url, maintenance, closed = _owned_maintenance(client, monkeypatch)
    original_window = maintenance.relay_expire_window
    calls, sleeps = [], []

    def window(**kwargs):
        calls.append(dict(kwargs))
        assert len(calls) <= 11
        if len(calls) == 1:
            return original_window(**{**kwargs, "limit": 1})
        raise sqlite3.OperationalError("disk I/O error: controlled-sensitive-error-text")

    monkeypatch.setattr(maintenance, "relay_expire_window", window)
    result = run_cleaner(["--database-url", database_url], sleep_fn=sleeps.append,
                         should_stop=lambda: False, install_signal_handlers=False)
    assert result == 1 and closed == [True]
    assert len(calls) == 11
    cursors = [(item["after_id"], item["upper_id"], item["cutoff"]) for item in calls[1:]]
    assert cursors == [cursors[0]] * 10
    assert cursors[0][0] is not None and cursors[0][1] is not None
    assert cursors[0][2] == expiry_clock
    assert sleeps == [0.05] + [0.25] * 9
    assert sorted(_states(client, messages)) == ["expired", "pending"]
    output = capsys.readouterr()
    assert "controlled-sensitive-error-text" not in output.out + output.err


def test_cleaner_expires_claimed_receipt_but_preserves_acknowledged_and_durable_deliveries(client):
    storage = client.app.state.pallium_service._storage
    messages = _messages(client, 3)
    claimed = client.post("/relay/turn", json={
        "runtime": "codex", "session_ref": "target", "max_messages": 2, **SCOPE,
    })
    assert claimed.status_code == 200, claimed.text
    receipts = claimed.json()["deliveries"]
    assert len(receipts) == 2
    doomed, acknowledged = receipts
    acknowledged_response = client.post("/relay/deliveries/ack", json={
        "delivery_id": acknowledged["delivery_id"], "claim_token": acknowledged["claim_token"], **SCOPE,
    })
    assert acknowledged_response.status_code == 200, acknowledged_response.text
    durable = next(message for message in messages if message not in {
        doomed["message_id"], acknowledged["message_id"],
    })
    _expire(storage, [doomed["message_id"], acknowledged["message_id"]])
    assert _once(str(storage._relay_engine.url)) == 0
    assert _states(client, [doomed["message_id"], acknowledged["message_id"], durable]) == [
        "expired", "delivered", "pending",
    ]
    stale = client.post("/relay/deliveries/ack", json={
        "delivery_id": doomed["delivery_id"], "claim_token": doomed["claim_token"], **SCOPE,
    })
    assert stale.status_code == 409, stale.text
    replay = client.post("/relay/deliveries/ack", json={
        "delivery_id": acknowledged["delivery_id"], "claim_token": acknowledged["claim_token"], **SCOPE,
    })
    assert replay.status_code == 200 and replay.json()["already_delivered"] is True
    remaining = client.post("/relay/turn", json={"runtime": "codex", "session_ref": "target", **SCOPE})
    assert remaining.status_code == 200, remaining.text
    assert [row["message_id"] for row in remaining.json()["deliveries"]] == [durable]
