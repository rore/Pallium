from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import text

from storage.sqlite import SQLiteStorageProvider


def _dispose(*stores):
    for store in stores:
        store._engine.dispose()
        if store._relay_engine is not store._engine:
            store._relay_engine.dispose()


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
            **common,
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




def _tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }


def _columns(path: Path, table: str) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def test_fresh_separate_and_same_databases_use_current_schema(tmp_path: Path) -> None:
    separate_main = tmp_path / "main.db"
    separate_relay = tmp_path / "relay.db"
    separate = SQLiteStorageProvider(
        f"sqlite:///{separate_main}",
        relay_database_url=f"sqlite:///{separate_relay}",
    )
    same_path = tmp_path / "same.db"
    same = SQLiteStorageProvider(f"sqlite:///{same_path}")
    required = {"relay_sessions", "relay_messages", "relay_deliveries", "relay_aliases"}
    for path in (separate_relay, same_path):
        assert required <= _tables(path)
        assert "relay_migration_metadata" not in _tables(path)
        assert "sender_endpoint_id" in _columns(path, "relay_messages")
        assert {"recipient_endpoint_id", "recipient_container_ref"} <= _columns(
            path, "relay_deliveries"
        )
    assert "memory_objects" not in _tables(separate_relay)
    _dispose(separate, same)


@pytest.mark.parametrize("missing", ["main", "relay"])
def test_existing_one_file_only_pair_fails_without_creating_other(
    tmp_path: Path, missing: str
) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    provider = SQLiteStorageProvider(
        f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}"
    )
    provider.close()
    (main if missing == "main" else relay).unlink()
    with pytest.raises(RuntimeError, match="partial|pair"):
        SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    assert main.exists() == (missing != "main")
    assert relay.exists() == (missing != "relay")


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("relay_messages", "sender_endpoint_id"),
        ("relay_deliveries", "recipient_endpoint_id"),
        ("relay_deliveries", "recipient_container_ref"),
    ],
)
def test_missing_current_endpoint_column_fails_without_mutation(
    tmp_path: Path, table: str, column: str
) -> None:
    path = tmp_path / "relay.db"
    provider = SQLiteStorageProvider(f"sqlite:///{path}")
    provider.close()
    with sqlite3.connect(path) as connection:
        if table == "relay_deliveries" and column == "recipient_endpoint_id":
            connection.execute("DROP INDEX IF EXISTS idx_relay_deliveries_recipient_endpoint")
        connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="column|schema|current"):
        SQLiteStorageProvider(f"sqlite:///{path}")
    assert path.read_bytes() == before
    assert column not in _columns(path, table)


def test_existing_empty_relay_file_fails_without_initializing_or_mutating_it(
    tmp_path: Path,
) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    main_store = SQLiteStorageProvider(f"sqlite:///{main}")
    main_store.close()
    with sqlite3.connect(relay) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO unrelated VALUES (1)")
    before = relay.read_bytes()
    with pytest.raises(RuntimeError, match="Relay|relay|schema|table|incomplete"):
        SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    assert relay.read_bytes() == before
    assert _tables(relay) == {"unrelated"}


def test_dormant_legacy_relay_table_in_main_does_not_block_active_pair(
    tmp_path: Path,
) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    provider = SQLiteStorageProvider(
        f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}"
    )
    provider.close()
    with sqlite3.connect(main) as connection:
        connection.execute("CREATE TABLE relay_migration_metadata (key TEXT)")
    before = _columns(main, "relay_migration_metadata")
    reopened = SQLiteStorageProvider(
        f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}"
    )
    result = reopened.relay_turn(
        runtime="codex",
        session_ref="target",
        container_ref="c",
        actor_ref="u",
        title=None,
        max_chars=100,
        max_messages=1,
        lease_seconds=60,
    )
    assert result["session"]["session_ref"] == "target"
    assert _columns(main, "relay_migration_metadata") == before
    reopened.close()


def test_current_relay_rows_alias_removal_unresolved_binding_and_claim_survive_restart(
    tmp_path: Path,
) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    scope = {"container_ref": "c", "actor_ref": "u"}
    provider = SQLiteStorageProvider(
        f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}"
    )
    for session in ("sender", "target"):
        provider.relay_turn(
            runtime="codex",
            session_ref=session,
            title=None,
            max_chars=1000,
            max_messages=3,
            lease_seconds=60,
            **scope,
        )
    provider.relay_name_session(
        runtime="codex",
        session_ref="target",
        alias="gone",
        replace_existing=False,
        **scope,
    )
    provider.relay_send(
        message_id="stable",
        sender_runtime="codex",
        sender_session_ref="sender",
        recipient="codex:target",
        recipient_runtime="codex",
        recipient_kind="session",
        recipient_value="target",
        payload="payload",
        redacted=False,
        expires_in_seconds=3600,
        in_reply_to=None,
        **scope,
    )
    claimed = provider.relay_turn(
        runtime="codex",
        session_ref="target",
        title=None,
        max_chars=1000,
        max_messages=3,
        lease_seconds=60,
        **scope,
    )["deliveries"][0]
    provider.relay_name_session(
        runtime="codex",
        session_ref="target",
        alias=None,
        replace_existing=False,
        **scope,
    )
    with provider._relay_engine.begin() as connection:
        connection.execute(
            text("UPDATE relay_messages SET sender_endpoint_id = NULL WHERE id = :id"),
            {"id": "stable"},
        )
        connection.execute(
            text("UPDATE relay_deliveries SET recipient_endpoint_id = NULL WHERE message_id = :id"),
            {"id": "stable"},
        )
    with provider._relay_engine.connect() as connection:
        before = {
            table: connection.execute(text(f"SELECT * FROM {table} ORDER BY 1")).fetchall()
            for table in ("relay_sessions", "relay_messages", "relay_deliveries", "relay_aliases")
        }
    provider.close()
    reopened = SQLiteStorageProvider(
        f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}"
    )
    with reopened._relay_engine.connect() as connection:
        assert {
            table: connection.execute(text(f"SELECT * FROM {table} ORDER BY 1")).fetchall()
            for table in before
        } == before
    assert reopened.relay_message_status(message_id="stable", **scope)["deliveries"][0]["state"] == "claimed"
    assert claimed["state"] == "claimed"
    reopened.relay_ack_by_receipt(
        delivery_id=claimed["delivery_id"], receipt=claimed["receipt"], **scope
    )
    assert reopened.relay_message_status(message_id="stable", **scope)["deliveries"][0]["state"] == "delivered"
    assert reopened.relay_turn(
        runtime="codex",
        session_ref="target",
        title=None,
        max_chars=1000,
        max_messages=3,
        lease_seconds=60,
        **scope,
    )["deliveries"] == []
    reopened.close()