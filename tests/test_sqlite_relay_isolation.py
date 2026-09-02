from pathlib import Path

import pytest
from sqlalchemy import text

from storage.sqlite import SQLiteStorageProvider


def _dispose(*stores):
    for store in stores:
        store._engine.dispose()
        if store._relay_engine is not store._engine:
            store._relay_engine.dispose()


def test_isolated_relay_schema_and_legacy_import_are_idempotent(tmp_path: Path) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    legacy = SQLiteStorageProvider(f"sqlite:///{main}")
    legacy.relay_turn(runtime="a", session_ref="s", container_ref="c", actor_ref="u", title=None, max_chars=100, max_messages=1, lease_seconds=1)
    split = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    reopened = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    with split._relay_engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert {"relay_sessions", "relay_messages", "relay_deliveries", "relay_migration_metadata"} <= tables
    assert "memory_objects" not in tables
    assert reopened.relay_list_sessions(container_ref="c", actor_ref="u", runtime=None, include_inactive=True, recent_seconds=1)
    _dispose(legacy, split, reopened)


def test_post_marker_missing_legacy_id_fails_closed(tmp_path: Path) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    legacy = SQLiteStorageProvider(f"sqlite:///{main}")
    legacy.relay_turn(runtime="a", session_ref="s", container_ref="c", actor_ref="u", title=None, max_chars=100, max_messages=1, lease_seconds=1)
    split = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    split._engine.dispose()
    split._relay_engine.dispose()
    with pytest.raises(RuntimeError, match="marker"): 
        SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{tmp_path / 'different.db'}")
    _dispose(legacy)

def _pragma(path: Path, name: str):
    import sqlite3
    with sqlite3.connect(path) as connection:
        return connection.execute(f"PRAGMA {name}").fetchone()[0]


def test_sqlite_lifecycle_and_writer_isolation(tmp_path: Path) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    provider = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    assert _pragma(main, "journal_mode").lower() == "wal"
    assert _pragma(relay, "journal_mode").lower() == "wal"
    assert _pragma(main, "auto_vacuum") == 2
    assert _pragma(relay, "auto_vacuum") == 2
    with provider._engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 15000
    with provider._relay_engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 15000

    # A main-file writer must not prevent a short Relay write on its own file.
    import sqlite3
    provider.relay_turn(runtime="codex", session_ref="target", container_ref="c", actor_ref="u", title=None, max_chars=1000, max_messages=3, lease_seconds=60)
    blocker = sqlite3.connect(main, timeout=0)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        result = provider.relay_turn(runtime="codex", session_ref="second", container_ref="c", actor_ref="u", title=None, max_chars=1000, max_messages=3, lease_seconds=60)
        assert result["session"]["session_ref"] == "second"
    finally:
        blocker.rollback()
        blocker.close()
    _dispose(provider)


def test_relay_indexes_support_claim_lookup_plan(tmp_path: Path) -> None:
    provider = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'main.db'}", relay_database_url=f"sqlite:///{tmp_path / 'relay.db'}")
    with provider._relay_engine.connect() as connection:
        plan = connection.execute(text("EXPLAIN QUERY PLAN SELECT * FROM relay_deliveries WHERE recipient_runtime='codex' AND recipient_session_ref='target' AND state='pending'" )).fetchall()
    assert any("idx_relay_deliveries_claim" in str(row) for row in plan)
    _dispose(provider)


def test_populated_legacy_relay_rows_migrate_exactly_once(tmp_path: Path) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    legacy = SQLiteStorageProvider(f"sqlite:///{main}")
    scope = {"container_ref": "c", "actor_ref": "u"}
    for session in ("sender", "target"):
        legacy.relay_turn(runtime="codex", session_ref=session, title=None, max_chars=2000, max_messages=3, lease_seconds=60, **scope)
    legacy.relay_send(message_id="stable-message", sender_runtime="codex", sender_session_ref="sender", recipient="codex:target", recipient_runtime="codex", recipient_kind="session", recipient_value="target", payload="payload", redacted=False, expires_in_seconds=3600, in_reply_to=None, broadcast_recent_seconds=86400, broadcast_max_recipients=10, **scope)
    claimed = legacy.relay_turn(runtime="codex", session_ref="target", title=None, max_chars=2000, max_messages=3, lease_seconds=60, **scope)["deliveries"][0]
    with legacy._engine.connect() as connection:
        before = {table: connection.execute(text(f"SELECT * FROM {table} ORDER BY 1")).fetchall() for table in ("relay_sessions", "relay_messages", "relay_deliveries")}
    legacy._engine.dispose()
    split = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    with split._relay_engine.connect() as connection:
        after = {table: connection.execute(text(f"SELECT * FROM {table} ORDER BY 1")).fetchall() for table in before}
    assert after == before
    assert claimed["state"] == "claimed"
    split._engine.dispose(); split._relay_engine.dispose()
    reopened = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    with reopened._relay_engine.connect() as connection:
        assert {table: connection.execute(text(f"SELECT * FROM {table} ORDER BY 1")).fetchall() for table in before} == before
    _dispose(reopened)

def test_bounded_multi_agent_relay_fan_in_has_no_lost_deliveries(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    provider = SQLiteStorageProvider(
        f"sqlite:///{tmp_path / 'main.db'}",
        relay_database_url=f"sqlite:///{tmp_path / 'relay.db'}",
    )
    common = {"container_ref": "c", "actor_ref": "u"}
    provider.relay_turn(runtime="codex", session_ref="target", title=None, max_chars=10000, max_messages=20, lease_seconds=60, **common)
    for index in range(8):
        provider.relay_turn(runtime="claude-code", session_ref=f"sender-{index}", title=None, max_chars=1000, max_messages=1, lease_seconds=60, **common)

    def send(index: int) -> dict:
        return provider.relay_send(
            message_id=f"fan-in-{index}", sender_runtime="claude-code", sender_session_ref=f"sender-{index}",
            recipient="codex:target", recipient_runtime="codex", recipient_kind="session", recipient_value="target",
            payload=f"finding-{index}", redacted=False, expires_in_seconds=3600, in_reply_to=None,
            broadcast_recent_seconds=86400, broadcast_max_recipients=20, **common,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        sent = list(pool.map(send, range(8)))
    assert {item["message_id"] for item in sent} == {f"fan-in-{i}" for i in range(8)}
    claimed = provider.relay_turn(runtime="codex", session_ref="target", title=None, max_chars=10000, max_messages=20, lease_seconds=60, **common)["deliveries"]
    assert len(claimed) == 8
    assert len({item["delivery_id"] for item in claimed}) == 8
    for delivery in claimed:
        provider.relay_ack_by_receipt(delivery_id=delivery["delivery_id"], receipt=delivery["receipt"], **common)
    assert provider.relay_turn(runtime="codex", session_ref="target", title=None, max_chars=10000, max_messages=20, lease_seconds=60, **common)["deliveries"] == []
    _dispose(provider)

def test_http_relay_remains_available_during_main_writer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from app.config import AppConfig
    from app.main import create_app
    from storage.vector_index import VectorIndexConfig
    from tests.config_helpers import DEMO_SEMANTIC_PACKAGES
    import sqlite3
    import time

    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    monkeypatch.setattr("app.dependencies.schedule_codex_relay_wake", lambda _: None)
    app = create_app(AppConfig(storage_backend="sqlite", sqlite_url=f"sqlite:///{main}", relay_sqlite_url=f"sqlite:///{relay}", default_use_case="demo_agent_memory", semantic_packages=DEMO_SEMANTIC_PACKAGES, vector_index=VectorIndexConfig(enabled=False)))
    with TestClient(app) as client:
        scope = {"container_ref": "c", "actor_ref": "u"}
        for session in ("sender", "target"):
            assert client.post("/relay/turn", json={"runtime": "codex", "session_ref": session, **scope, "max_chars": 1000, "max_messages": 3, "lease_seconds": 60}).status_code == 200
        blocker = sqlite3.connect(main, timeout=0)
        try:
            blocker.execute("BEGIN IMMEDIATE")
            started = time.perf_counter()
            response = client.post("/relay/messages", json={"sender_runtime": "codex", "sender_session_ref": "sender", "recipient": "codex:target", "payload": "under-lock", **scope})
            elapsed = time.perf_counter() - started
            assert response.status_code == 200, response.text
            assert elapsed < 2.0
        finally:
            blocker.rollback()
            blocker.close()


def test_split_marker_detects_missing_target_row(tmp_path: Path) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    legacy = SQLiteStorageProvider(f"sqlite:///{main}")
    legacy.relay_turn(runtime="codex", session_ref="target", container_ref="c", actor_ref="u", title=None, max_chars=1000, max_messages=1, lease_seconds=60)
    legacy._engine.dispose()
    split = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    split._engine.dispose(); split._relay_engine.dispose()
    with __import__("sqlite3").connect(relay) as connection:
        connection.execute("DELETE FROM relay_sessions")
    with pytest.raises(RuntimeError, match="migration|marker"):
        SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")


def test_split_rejects_competing_legacy_writer_within_bound(tmp_path: Path) -> None:
    import sqlite3
    import time

    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    legacy = SQLiteStorageProvider(f"sqlite:///{main}")
    legacy.relay_turn(runtime="codex", session_ref="target", container_ref="c", actor_ref="u", title=None, max_chars=1000, max_messages=1, lease_seconds=60)
    legacy._engine.dispose()
    blocker = sqlite3.connect(main, timeout=0)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        started = time.perf_counter()
        with pytest.raises(Exception, match="locked|busy"):
            SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
        assert time.perf_counter() - started < 10.0
    finally:
        blocker.rollback()
        blocker.close()


def test_split_resume_tolerates_heartbeat_drift(tmp_path: Path) -> None:
    # last_seen_at advances only in the relay DB after the split, so it diverges
    # from the frozen main-DB copy. The resumed-startup verify must not treat that
    # expected drift as corruption.
    import sqlite3

    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    legacy = SQLiteStorageProvider(f"sqlite:///{main}")
    legacy.relay_turn(runtime="codex", session_ref="target", container_ref="c", actor_ref="u", title=None, max_chars=1000, max_messages=1, lease_seconds=60)
    legacy._engine.dispose()
    split = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    split._engine.dispose(); split._relay_engine.dispose()
    with sqlite3.connect(relay) as connection:
        connection.execute("UPDATE relay_sessions SET last_seen_at='2099-01-01 00:00:00.000000'")
    # Must not raise despite the drifted column.
    reopened = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    _dispose(reopened)