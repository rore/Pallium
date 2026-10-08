import json
import multiprocessing
import os
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Connection, Engine

from core.errors import ImmediateTransactionBusyError
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


def _closed_pragma(path: Path, name: str):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(f"PRAGMA {name}").fetchone()[0]


def _relay_table_rows(path: Path) -> dict[str, list[tuple]]:
    with closing(sqlite3.connect(path)) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'relay_%' ORDER BY name"
            )
        ]
        return {
            table: sorted(
                connection.execute(f'SELECT * FROM "{table}"').fetchall(), key=repr
            )
            for table in tables
        }


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
    provider.relay_turn(runtime="codex", session_ref="target", container_ref="c", title=None, max_chars=1000, max_messages=3, lease_seconds=60)
    blocker = sqlite3.connect(main, timeout=0)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        result = provider.relay_turn(runtime="codex", session_ref="second", container_ref="c", title=None, max_chars=1000, max_messages=3, lease_seconds=60)
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


def test_relay_index_supports_global_exact_session_lookup_plan(tmp_path: Path) -> None:
    provider = SQLiteStorageProvider(f"sqlite:///{tmp_path / 'main.db'}", relay_database_url=f"sqlite:///{tmp_path / 'relay.db'}")
    with provider._relay_engine.connect() as connection:
        plan = connection.execute(text(
            "EXPLAIN QUERY PLAN SELECT * FROM relay_sessions WHERE runtime='codex' AND session_ref='target'"
        )).fetchall()
    assert any("idx_relay_sessions_global_exact" in str(row) for row in plan)
    _dispose(provider)


def test_bounded_multi_agent_relay_fan_in_has_no_lost_deliveries(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    provider = SQLiteStorageProvider(
        f"sqlite:///{tmp_path / 'main.db'}",
        relay_database_url=f"sqlite:///{tmp_path / 'relay.db'}",
    )
    common = {"container_ref": "c",}
    provider.relay_turn(runtime="codex", session_ref="target", title=None, max_chars=10000, max_messages=20, lease_seconds=60, **common)
    for index in range(8):
        provider.relay_turn(runtime="claude-code", session_ref=f"sender-{index}", title=None, max_chars=1000, max_messages=1, lease_seconds=60, **common)

    def send(index: int) -> dict:
        for attempt in range(12):
            try:
                return provider.relay_send(
                    message_id=f"fan-in-{index}", sender_runtime="claude-code", sender_session_ref=f"sender-{index}",
                    recipient="codex:target", recipient_runtime="codex", recipient_kind="session", recipient_value="target",
                    payload=f"finding-{index}", redacted=False, expires_in_seconds=3600, in_reply_to=None,
                    **common,
                )
            except ImmediateTransactionBusyError:
                if attempt == 11:
                    raise
        raise AssertionError("unreachable")

    with ThreadPoolExecutor(max_workers=4) as pool:
        sent = list(pool.map(send, range(8)))
    assert {item["message_id"] for item in sent} == {f"fan-in-{i}" for i in range(8)}
    claimed = provider.relay_turn(runtime="codex", session_ref="target", title=None, max_chars=10000, max_messages=20, lease_seconds=60, **common)["deliveries"]
    assert len(claimed) == 8
    assert {item["message_id"] for item in claimed} == {f"fan-in-{i}" for i in range(8)}
    assert len({item["delivery_id"] for item in claimed}) == 8
    for delivery in claimed:
        provider.relay_ack_by_receipt(delivery_id=delivery["delivery_id"], receipt=delivery["receipt"], **common)
        status = provider.relay_message_status(message_id=delivery["message_id"], **common)
        assert status["deliveries"][0]["state"] == "delivered"
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
        scope = {"container_ref": "c",}
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




def _initialize_separate_pair_process(
    main_url: str,
    relay_url: str,
    result_queue,
    main_ready=None,
    release=None,
) -> None:
    try:
        if main_ready is not None:
            original = SQLiteStorageProvider._initialize_schema

            def pause_after_main_schema(self, include_relay=True):
                result = original(self, include_relay=include_relay)
                if not include_relay:
                    main_ready.set()
                    if not release.wait(15):
                        raise RuntimeError("timed out waiting to release startup")
                return result

            SQLiteStorageProvider._initialize_schema = pause_after_main_schema
        SQLiteStorageProvider(main_url, relay_database_url=relay_url).close()
    except Exception as exc:  # pragma: no cover - exercised via multiprocessing
        result_queue.put(f"error:{exc!r}")
        raise
    result_queue.put("ok")


def _initialize_main_and_report_work_ref_migration(
    path: Path,
    result_queue,
    *,
    relay_database_url: str | None = None,
    crash_after_version: bool = False,
    ready_event=None,
    release_event=None,
) -> None:
    operations = []

    def observe(connection, _cursor, statement, _parameters, _context, _many):
        if Path(connection.engine.url.database).resolve() != path.resolve():
            return
        sql = " ".join(statement.upper().split())
        if sql == "DELETE FROM SOURCE_ITEM_WORK_REFS":
            operations.append("DELETE")
        elif sql == "SELECT ID, METADATA_JSON FROM SOURCE_ITEMS":
            operations.append("SCAN")
        elif sql.startswith("INSERT INTO SOURCE_ITEM_WORK_REFS"):
            operations.append("INSERT")
        elif crash_after_version and sql == "PRAGMA MAIN.USER_VERSION=1":
            os._exit(73)

    event.listen(Engine, "after_cursor_execute", observe)
    try:
        if ready_event is not None:
            result_queue.put(("ready", os.getpid()))
            ready_event.set()
            if not release_event.wait(15):
                result_queue.put(("error", "startup gate timed out", operations))
                return
        provider = SQLiteStorageProvider(
            f"sqlite:///{path}", relay_database_url=relay_database_url
        )
        provider.close()
    except Exception as exc:  # pragma: no cover - child reports to its parent
        result_queue.put(("error", repr(exc), operations))
    else:
        result_queue.put(("ok", operations))
    finally:
        event.remove(Engine, "after_cursor_execute", observe)


def _start_hidden_owned_process(process: multiprocessing.Process) -> None:
    if os.name != "nt":
        process.start()
        return
    from multiprocessing import popen_spawn_win32

    create_process = popen_spawn_win32._winapi.CreateProcess

    def create_hidden_process(*args, **kwargs):
        arguments = list(args)
        arguments[5] |= 0x08000000
        return create_process(*arguments, **kwargs)

    popen_spawn_win32._winapi.CreateProcess = create_hidden_process
    try:
        process.start()
    finally:
        popen_spawn_win32._winapi.CreateProcess = create_process


def _reap_owned_process(process: multiprocessing.Process) -> tuple[int | None, list[str]]:
    errors = []
    try:
        process.join(timeout=15)
    except Exception as exc:
        errors.append(f"join failed: {exc!r}")
    try:
        if process.is_alive():
            process.terminate()
    except Exception as exc:
        errors.append(f"terminate failed: {exc!r}")
    try:
        process.join(timeout=5)
    except Exception as exc:
        errors.append(f"reap failed: {exc!r}")
    exitcode = None
    try:
        if process.is_alive():
            errors.append("owned child is still alive after termination")
        else:
            exitcode = process.exitcode
            process.close()
    except Exception as exc:
        errors.append(f"process close failed: {exc!r}")
    return exitcode, errors

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
    required = {"relay_sessions", "relay_session_work_refs", "relay_messages", "relay_deliveries", "relay_aliases"}
    for path in (separate_relay, same_path):
        assert required <= _tables(path)
        assert "relay_migration_metadata" not in _tables(path)
        assert "sender_endpoint_id" in _columns(path, "relay_messages")
        assert {"recipient_endpoint_id", "recipient_container_ref"} <= _columns(
            path, "relay_deliveries"
        )
    assert "memory_objects" not in _tables(separate_relay)
    _dispose(separate, same)


def test_concurrent_fresh_separate_pair_startup_is_serialized(tmp_path: Path) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    main_url = f"sqlite:///{main}"
    relay_url = f"sqlite:///{relay}"
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    main_ready = context.Event()
    release = context.Event()
    first = context.Process(
        target=_initialize_separate_pair_process,
        args=(main_url, relay_url, result_queue, main_ready, release),
    )
    started = []
    exitcodes = []
    cleanup_errors = []
    results = []
    try:
        try:
            _start_hidden_owned_process(first)
        finally:
            if first.pid is not None:
                started.append(first)
        if not main_ready.wait(15):
            raise TimeoutError("first pair initializer did not reach the main-schema gate")
        second = context.Process(
            target=_initialize_separate_pair_process,
            args=(main_url, relay_url, result_queue),
        )
        try:
            _start_hidden_owned_process(second)
        finally:
            if second.pid is not None:
                started.append(second)
        with pytest.raises(Empty):
            result_queue.get(timeout=1)
        release.set()
        results = [result_queue.get(timeout=15), result_queue.get(timeout=15)]
    finally:
        release.set()
        for process in started:
            exitcode, errors = _reap_owned_process(process)
            exitcodes.append(exitcode)
            cleanup_errors.extend(errors)
        try:
            result_queue.close()
        except Exception as exc:
            cleanup_errors.append(f"queue close failed: {exc!r}")
        try:
            result_queue.join_thread()
        except Exception as exc:
            cleanup_errors.append(f"queue join failed: {exc!r}")
        assert not cleanup_errors, "; ".join(cleanup_errors)
    assert results == ["ok", "ok"]
    assert exitcodes == [0, 0]
    provider = SQLiteStorageProvider(main_url, relay_database_url=relay_url)
    try:
        for path in (main, relay):
            assert _pragma(path, "auto_vacuum") == 2
            assert _pragma(path, "journal_mode").lower() == "wal"
    finally:
        _dispose(provider)


def test_startup_waits_for_transient_main_database_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    initial = SQLiteStorageProvider(
        f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}"
    )
    _dispose(initial)

    lock_acquired = threading.Event()
    pragma_started = threading.Event()
    release_lock = threading.Event()
    startup = None
    observed_timeouts: list[int] = []
    result: list[object] = []

    original_exec_driver_sql = Connection.exec_driver_sql

    def observe_startup_pragma(self, statement, *args, **kwargs):
        if statement == "PRAGMA auto_vacuum=INCREMENTAL":
            observed_timeouts.append(
                int(original_exec_driver_sql(self, "PRAGMA busy_timeout").scalar() or 0)
            )
            pragma_started.set()
        return original_exec_driver_sql(self, statement, *args, **kwargs)

    monkeypatch.setattr(Connection, "exec_driver_sql", observe_startup_pragma)

    def hold_main_lock() -> None:
        holder = sqlite3.connect(main, timeout=0)
        try:
            holder.execute("BEGIN EXCLUSIVE")
            lock_acquired.set()
            release_lock.wait(15)
        finally:
            holder.rollback()
            holder.close()

    def initialize_pair() -> None:
        try:
            result.append(
                SQLiteStorageProvider(
                    f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}"
                )
            )
        except Exception as exc:  # pragma: no cover - assertion below reports it
            result.append(exc)

    try:
        holder_thread = threading.Thread(target=hold_main_lock)
        holder_thread.start()
        assert lock_acquired.wait(15)
        startup = threading.Thread(target=initialize_pair)
        startup.start()
        assert pragma_started.wait(15)
        assert observed_timeouts[0] == 15000
        release_lock.set()
        startup.join(15)
        assert not startup.is_alive()
        assert len(result) == 1
        assert not isinstance(result[0], Exception), result[0]
        provider = result[0]
        for path in (main, relay):
            assert _pragma(path, "auto_vacuum") == 2
            assert _pragma(path, "journal_mode").lower() == "wal"
    finally:
        release_lock.set()
        if startup is not None:
            startup.join(15)
        if 'holder_thread' in locals():
            holder_thread.join(15)
        if result and isinstance(result[0], SQLiteStorageProvider):
            _dispose(result[0])

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
        ("relay_session_work_refs", "scope_ref"),
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


def test_orphaned_optional_relay_table_fails_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "relay.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE relay_session_work_refs (
                endpoint_id TEXT NOT NULL,
                work_ref TEXT NOT NULL,
                origin TEXT NOT NULL,
                scope_ref TEXT NOT NULL,
                local_ref TEXT NOT NULL,
                position INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (endpoint_id, work_ref, origin)
            )"""
        )
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="Relay schema is incomplete"):
        SQLiteStorageProvider(f"sqlite:///{path}")
    assert path.read_bytes() == before


def test_dormant_legacy_relay_tables_in_main_do_not_block_active_pair(
    tmp_path: Path,
) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    provider = SQLiteStorageProvider(
        f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}"
    )
    provider.close()
    with sqlite3.connect(main) as connection:
        connection.executescript(
            """
            CREATE TABLE relay_messages (
                id TEXT PRIMARY KEY,
                sender_runtime TEXT NOT NULL,
                sender_session_ref TEXT NOT NULL,
                recipient_selector TEXT NOT NULL,
                container_ref TEXT NOT NULL,
                actor_ref TEXT NOT NULL,
                payload TEXT NOT NULL,
                redacted INTEGER NOT NULL,
                in_reply_to TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE relay_deliveries (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                recipient_runtime TEXT NOT NULL,
                recipient_session_ref TEXT NOT NULL,
                state TEXT NOT NULL,
                claim_token TEXT,
                claimed_at TEXT,
                lease_expires_at TEXT,
                delivered_at TEXT,
                attempts INTEGER NOT NULL
            );
            INSERT INTO relay_messages VALUES
                ('legacy-message', 'codex', 'sender', 'codex:target', 'c', 'u', 'payload', 0, NULL, '2026-01-01', '2027-01-01');
            INSERT INTO relay_deliveries VALUES
                ('legacy-delivery', 'legacy-message', 'codex', 'target', 'pending', NULL, NULL, NULL, NULL, 0);
            """
        )
        before_schema = {
            table: connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?", (table,)
            ).fetchone()[0]
            for table in ("relay_messages", "relay_deliveries")
        }
        before_rows = {
            table: connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("relay_messages", "relay_deliveries")
        }
    reopened = SQLiteStorageProvider(
        f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}"
    )
    result = reopened.relay_turn(
        runtime="codex",
        session_ref="target",
        container_ref="c",
        title=None,
        max_chars=100,
        max_messages=1,
        lease_seconds=60,
    )
    assert result["session"]["session_ref"] == "target"
    with sqlite3.connect(main) as connection:
        assert {
            table: connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?", (table,)
            ).fetchone()[0]
            for table in before_schema
        } == before_schema
        assert {
            table: connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in before_rows
        } == before_rows
    reopened.close()

def test_current_relay_rows_alias_removal_unresolved_binding_and_claim_survive_restart(
    tmp_path: Path,
) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    scope = {"container_ref": "c",}
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

def test_relay_generation_schema_upgrade_preserves_existing_sessions(tmp_path: Path) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    main_url = f"sqlite:///{main}"
    relay_url = f"sqlite:///{relay}"
    provider = SQLiteStorageProvider(main_url, relay_database_url=relay_url)
    provider.relay_turn(
        runtime="codex", session_ref="kept", container_ref="scope-a",
        title=None, max_chars=100, max_messages=1, lease_seconds=60,
    )
    provider.close()

    with sqlite3.connect(relay) as connection:
        connection.execute("DROP TABLE relay_endpoint_generations")

    reopened = SQLiteStorageProvider(main_url, relay_database_url=relay_url)
    first = reopened.relay_turn(
        runtime="codex", session_ref="kept", container_ref="scope-a",
        title=None, max_chars=100, max_messages=1, lease_seconds=60,
    )
    assert first["session"]["scope_generation"] == 0
    with sqlite3.connect(relay) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='relay_endpoint_generations'"
        ).fetchone()
        assert connection.execute(
            "SELECT session_ref FROM relay_sessions WHERE session_ref='kept'"
        ).fetchone() == ("kept",)
    reopened.close()

def test_actor_bearing_relay_schema_is_rejected_without_migration(tmp_path: Path) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    provider = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    provider.close()
    with sqlite3.connect(relay) as connection:
        connection.execute("ALTER TABLE relay_sessions ADD COLUMN actor_ref TEXT")
    before = relay.read_bytes()
    with pytest.raises(RuntimeError, match="column|schema|current"):
        SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    assert relay.read_bytes() == before

def test_relay_association_schema_upgrade_preserves_existing_rows(tmp_path: Path) -> None:
    main = tmp_path / "main.db"
    relay = tmp_path / "relay.db"
    provider = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    provider.relay_turn(runtime="codex", session_ref="kept", container_ref="c", title=None, max_chars=100, max_messages=1, lease_seconds=60)
    provider.close()
    with sqlite3.connect(relay) as connection:
        connection.execute("DROP TABLE relay_session_work_refs")
    reopened = SQLiteStorageProvider(f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}")
    with sqlite3.connect(relay) as connection:
        assert connection.execute("SELECT session_ref FROM relay_sessions WHERE session_ref='kept'").fetchone() == ("kept",)
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='relay_session_work_refs'").fetchone()
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_relay_work_refs_lookup'").fetchone()
    reopened.close()


def test_completed_main_reopen_does_not_rebuild_work_refs(tmp_path: Path) -> None:
    from core.models import IndexEntry, SourceItem

    path = tmp_path / "completed.db"
    url = f"sqlite:///{path}"
    source = SourceItem(
        source_type="chat", source_id="unchanged", content_type="text/plain",
        content="alpha", metadata={"pallium_work_refs": ["Straße", "STRASSE"]},
    )
    initial = SQLiteStorageProvider(url)
    try:
        initial.create_source_item(source)
        initial.create_index_entry(IndexEntry(
            id="unchanged-vector", target_kind="source_item", target_id=source.id,
            index_type="vector", text_view="alpha",
        ))
    finally:
        initial.close()

    operations = []

    def observe(connection, _cursor, statement, _parameters, _context, _many):
        if Path(connection.engine.url.database).resolve() != path.resolve():
            return
        sql = " ".join(statement.upper().split())
        if sql == "DELETE FROM SOURCE_ITEM_WORK_REFS":
            operations.append("DELETE")
        elif sql == "SELECT ID, METADATA_JSON FROM SOURCE_ITEMS":
            operations.append("SCAN")
        elif sql.startswith("INSERT INTO SOURCE_ITEM_WORK_REFS"):
            operations.append("INSERT")

    event.listen(Engine, "after_cursor_execute", observe)
    try:
        for _ in range(2):
            reopened = SQLiteStorageProvider(url)
            try:
                assert [entry.id for entry, _projection in
                        reopened.get_source_item_vector_candidates(("strasse",))] == ["unchanged-vector"]
            finally:
                reopened.close()
    finally:
        event.remove(Engine, "after_cursor_execute", observe)
    assert operations == []
    assert _closed_pragma(path, "user_version") == 1


@pytest.mark.parametrize(
    "state",
    [
        "version-minus-one", "version-future", "missing-id",
        "missing-metadata", "bad-projection", "inttext-projection",
    ],
)
def test_main_work_ref_admission_refuses_unknown_or_incompatible_state_without_writes(
    tmp_path: Path, state: str
) -> None:
    main = tmp_path / f"main-{state}.db"
    relay = tmp_path / f"relay-{state}.db"
    provider = SQLiteStorageProvider(
        f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}"
    )
    provider.relay_turn(
        runtime="codex", session_ref="preserved", container_ref="c",
        title=None, max_chars=100, max_messages=1, lease_seconds=60,
    )
    provider.close()

    with closing(sqlite3.connect(main)) as connection, connection:
        if state == "version-minus-one":
            connection.execute("PRAGMA user_version=-1")
        elif state == "version-future":
            connection.execute("PRAGMA user_version=2")
        elif state in {"missing-id", "missing-metadata"}:
            connection.execute("DROP TABLE source_items")
            connection.execute(
                "CREATE TABLE source_items (metadata_json TEXT)"
                if state == "missing-id"
                else "CREATE TABLE source_items (id TEXT PRIMARY KEY)"
            )
        else:
            connection.execute("DROP TABLE source_item_work_refs")
            projection_type = "INTTEXT" if state == "inttext-projection" else "INTEGER"
            connection.execute(
                "CREATE TABLE source_item_work_refs ("
                f"source_item_id TEXT NOT NULL, work_ref {projection_type} NOT NULL, "
                "PRIMARY KEY (source_item_id, work_ref))"
            )

    before_main, before_relay = main.read_bytes(), relay.read_bytes()
    writes = []

    def observe_persistent_write(connection, _cursor, statement, _parameters, _context, _many):
        database = Path(connection.engine.url.database).resolve()
        if database not in {main.resolve(), relay.resolve()}:
            return
        sql = " ".join(statement.upper().split())
        if sql.startswith((
            "PRAGMA AUTO_VACUUM=", "PRAGMA JOURNAL_MODE=", "PRAGMA MAIN.USER_VERSION=",
            "CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ", "REPLACE ",
        )):
            writes.append((database, sql))

    event.listen(Engine, "before_cursor_execute", observe_persistent_write)
    try:
        with pytest.raises(RuntimeError, match="Unsupported main|Incompatible"):
            SQLiteStorageProvider(
                f"sqlite:///{main}", relay_database_url=f"sqlite:///{relay}"
            )
    finally:
        event.remove(Engine, "before_cursor_execute", observe_persistent_write)
    assert writes == []
    assert main.read_bytes() == before_main
    assert relay.read_bytes() == before_relay


def test_version_one_missing_lookup_index_is_restored_without_rebuild(
    tmp_path: Path,
) -> None:
    from core.models import SourceItem

    path = tmp_path / "missing-work-ref-index.db"
    url = f"sqlite:///{path}"
    provider = SQLiteStorageProvider(url)
    try:
        provider.create_source_item(
            SourceItem(
                source_type="chat", source_id="indexed", content_type="text/plain",
                content="alpha", metadata={"pallium_work_refs": ["index-ref"]},
            )
        )
    finally:
        provider.close()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("DROP INDEX idx_source_item_work_refs_lookup")

    operations = []

    def observe(connection, _cursor, statement, _parameters, _context, _many):
        if Path(connection.engine.url.database).resolve() != path.resolve():
            return
        sql = " ".join(statement.upper().split())
        if sql == "DELETE FROM SOURCE_ITEM_WORK_REFS":
            operations.append("DELETE")
        elif sql == "SELECT ID, METADATA_JSON FROM SOURCE_ITEMS":
            operations.append("SCAN")
        elif sql.startswith("INSERT INTO SOURCE_ITEM_WORK_REFS"):
            operations.append("INSERT")

    event.listen(Engine, "after_cursor_execute", observe)
    try:
        reopened = SQLiteStorageProvider(url)
        reopened.close()
    finally:
        event.remove(Engine, "after_cursor_execute", observe)
    assert operations == []
    with closing(sqlite3.connect(path)) as connection, connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_source_item_work_refs_lookup'"
        ).fetchone() is not None


@pytest.mark.parametrize(
    ("failure_point", "version", "missing_table"),
    [
        ("after_create", 1, True),
        ("after_delete", 0, False),
        ("after_insert", 0, False),
        ("after_version", 0, False),
    ],
)
def test_work_ref_migration_failure_rolls_back_and_retry_completes(
    tmp_path: Path, failure_point: str, version: int, missing_table: bool
) -> None:
    from core.models import IndexEntry, SourceItem

    path = tmp_path / f"migration-{failure_point}.db"
    url = f"sqlite:///{path}"
    source = SourceItem(
        source_type="chat", source_id="failure-source", content_type="text/plain",
        content="alpha", metadata={"pallium_work_refs": ["correct-ref"]},
    )
    initial = SQLiteStorageProvider(url)
    try:
        initial.create_source_item(source)
        initial.create_index_entry(
            IndexEntry(
                id="failure-vector", target_kind="source_item", target_id=source.id,
                index_type="vector", text_view="alpha",
            )
        )
    finally:
        initial.close()
    with closing(sqlite3.connect(path)) as connection, connection:
        if missing_table:
            connection.execute("DROP TABLE source_item_work_refs")
        else:
            connection.execute(
                "INSERT INTO source_item_work_refs (source_item_id, work_ref) VALUES (?, ?)",
                (source.id, "stale-ref"),
            )
            connection.execute("PRAGMA user_version=0")

    engines = []
    fired = []

    def fail_after_statement(connection, _cursor, statement, _parameters, _context, _many):
        if Path(connection.engine.url.database).resolve() != path.resolve():
            return
        sql = " ".join(statement.upper().split())
        matches = {
            "after_create": sql.startswith("CREATE TABLE SOURCE_ITEM_WORK_REFS"),
            "after_delete": sql == "DELETE FROM SOURCE_ITEM_WORK_REFS",
            "after_insert": sql.startswith("INSERT INTO SOURCE_ITEM_WORK_REFS"),
            "after_version": sql == "PRAGMA MAIN.USER_VERSION=1",
        }
        if matches[failure_point] and not fired:
            fired.append(sql)
            engines.append(connection.engine)
            raise RuntimeError("injected migration failure")

    event.listen(Engine, "after_cursor_execute", fail_after_statement)
    try:
        with pytest.raises(RuntimeError, match="injected migration failure"):
            SQLiteStorageProvider(url)
    finally:
        event.remove(Engine, "after_cursor_execute", fail_after_statement)
        for engine in engines:
            engine.dispose()
    assert fired

    with closing(sqlite3.connect(path)) as connection, connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == version
        present = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_item_work_refs'"
        ).fetchone() is not None
        assert present is not missing_table
        if present:
            refs = connection.execute(
                "SELECT work_ref FROM source_item_work_refs WHERE source_item_id=? ORDER BY work_ref",
                (source.id,),
            ).fetchall()
            assert refs == ([] if missing_table else [("correct-ref",), ("stale-ref",)])

    retry = SQLiteStorageProvider(url)
    try:
        candidates = retry.get_source_item_vector_candidates(("correct-ref",))
        assert [entry.id for entry, _projection in candidates] == ["failure-vector"]
    finally:
        retry.close()
    assert _closed_pragma(path, "user_version") == 1
    with closing(sqlite3.connect(path)) as connection, connection:
        assert connection.execute(
            "SELECT work_ref FROM source_item_work_refs WHERE source_item_id=? ORDER BY work_ref",
            (source.id,),
        ).fetchall() == [("correct-ref",)]


@pytest.mark.parametrize("failure_point", ["after_delete", "after_insert"])
def test_private_work_ref_repair_failure_rolls_back_and_preserves_version(
    tmp_path: Path, request: pytest.FixtureRequest, failure_point: str
) -> None:
    from core.models import SourceItem

    path = tmp_path / f"repair-{failure_point}.db"
    provider = SQLiteStorageProvider(f"sqlite:///{path}")
    request.addfinalizer(provider.close)
    source = SourceItem(
        source_type="chat", source_id="repair-source", content_type="text/plain",
        content="alpha", metadata={"pallium_work_refs": ["old-ref"]},
    )
    provider.create_source_item(source)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "UPDATE source_items SET metadata_json=? WHERE id=?",
            (json.dumps({"pallium_work_refs": ["new-ref"]}), source.id),
        )

    fired = []

    def fail_after_statement(connection, _cursor, statement, _parameters, _context, _many):
        sql = " ".join(statement.upper().split())
        matches = {
            "after_delete": sql == "DELETE FROM SOURCE_ITEM_WORK_REFS",
            "after_insert": sql.startswith("INSERT INTO SOURCE_ITEM_WORK_REFS"),
        }
        if matches[failure_point] and not fired:
            fired.append(sql)
            raise RuntimeError("injected repair failure")

    event.listen(provider._engine, "after_cursor_execute", fail_after_statement)
    try:
        with pytest.raises(RuntimeError, match="injected repair failure"):
            provider._backfill_source_item_work_refs()
    finally:
        event.remove(provider._engine, "after_cursor_execute", fail_after_statement)
    assert fired
    with provider._engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA main.user_version").scalar_one() == 1
        assert connection.execute(
            text(
                "SELECT work_ref FROM source_item_work_refs "
                "WHERE source_item_id=:source_id ORDER BY work_ref"
            ),
            {"source_id": source.id},
        ).scalars().all() == ["old-ref"]

    provider._backfill_source_item_work_refs()
    provider._backfill_source_item_work_refs()
    with provider._engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA main.user_version").scalar_one() == 1
        assert connection.execute(
            text(
                "SELECT work_ref FROM source_item_work_refs "
                "WHERE source_item_id=:source_id ORDER BY work_ref"
            ),
            {"source_id": source.id},
        ).scalars().all() == ["new-ref"]


@pytest.mark.parametrize("populated", [True, False], ids=["legacy-populated", "fresh-pair"])
def test_concurrent_main_startups_rebuild_once_in_owned_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, populated: bool,
) -> None:
    from app.config import AppConfig
    from core.models import IndexEntry, SourceItem

    path = tmp_path / "concurrent-main.db"
    url = f"sqlite:///{path}"
    relay_url = AppConfig(sqlite_url=url).resolved_relay_sqlite_url
    source = None
    if populated:
        source = SourceItem(
            source_type="chat", source_id="concurrent", content_type="text/plain",
            content="alpha", container_ref="room", thread_ref="thread", visibility="private",
            metadata={"pallium_work_refs": ["concurrent-ref"]},
        )
        initial = SQLiteStorageProvider(url, relay_database_url=relay_url)
        try:
            initial.create_source_item(source)
            initial.create_index_entry(
                IndexEntry(
                    id="concurrent-vector", target_kind="source_item", target_id=source.id,
                    index_type="vector", text_view="alpha",
                )
            )
        finally:
            initial.close()
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                "INSERT INTO source_item_work_refs (source_item_id, work_ref) VALUES (?, ?)",
                (source.id, "stale-ref"),
            )
            connection.execute("PRAGMA user_version=0")

    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    ready_event = context.Event()
    release_event = context.Event()
    processes = [
        context.Process(
            target=_initialize_main_and_report_work_ref_migration,
            args=(path, result_queue),
            kwargs={
                "relay_database_url": relay_url,
                "ready_event": ready_event,
                "release_event": release_event,
            },
            daemon=True,
        )
        for _ in range(2)
    ]
    started = []
    exitcodes = []
    cleanup_errors = []
    try:
        for process in processes:
            try:
                _start_hidden_owned_process(process)
            finally:
                if process.pid is not None:
                    started.append(process)
        deadline = time.monotonic() + 30
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not ready_event.wait(remaining):
            raise TimeoutError("startup workers did not reach the ready gate")
        for _ in processes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("startup workers did not both reach the gate")
            assert result_queue.get(timeout=remaining)[0] == "ready"
        release_event.set()
        results = []
        for _ in processes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("startup workers did not finish within the bound")
            results.append(result_queue.get(timeout=remaining))
    finally:
        release_event.set()
        for process in started:
            exitcode, errors = _reap_owned_process(process)
            exitcodes.append(exitcode)
            cleanup_errors.extend(errors)
        try:
            result_queue.close()
        except Exception as exc:
            cleanup_errors.append(f"queue close failed: {exc!r}")
        try:
            result_queue.join_thread()
        except Exception as exc:
            cleanup_errors.append(f"queue join failed: {exc!r}")
        assert not cleanup_errors, "; ".join(cleanup_errors)
    assert [result[0] for result in results] == ["ok", "ok"]
    operations = [operation for _status, rows in results for operation in rows]
    assert operations.count("DELETE") == 1
    assert operations.count("SCAN") == 1
    assert operations.count("INSERT") == (1 if populated else 0)
    assert exitcodes == [0, 0]
    assert _closed_pragma(path, "user_version") == 1

    reopened = SQLiteStorageProvider(url, relay_database_url=relay_url)
    try:
        if populated:
            candidates = reopened.get_source_item_vector_candidates(("concurrent-ref",))
            assert [entry.id for entry, _projection in candidates] == ["concurrent-vector"]
    finally:
        reopened.close()
    assert _closed_pragma(path, "user_version") == 1
    if populated:
        from fastapi.testclient import TestClient

        from tests.test_exact_work_ref_search import _exact, _http_app_for_sqlite

        app = _http_app_for_sqlite(url, monkeypatch)
        with TestClient(app) as client:
            assert [item["source_item_id"] for item in _exact(client, "", "concurrent-ref")] == [source.id]


def test_abrupt_exit_after_version_write_rolls_back_migration_and_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import AppConfig
    from core.models import IndexEntry, SourceItem

    path = tmp_path / "crashed-main.db"
    url = f"sqlite:///{path}"
    relay_url = AppConfig(sqlite_url=url).resolved_relay_sqlite_url
    source = SourceItem(
        source_type="chat", source_id="crashed", content_type="text/plain",
        content="alpha", container_ref="room", thread_ref="thread", visibility="private",
        metadata={"pallium_work_refs": ["crash-ref"]},
    )
    initial = SQLiteStorageProvider(url, relay_database_url=relay_url)
    try:
        initial.create_source_item(source)
        initial.create_index_entry(
            IndexEntry(
                id="crash-vector", target_kind="source_item", target_id=source.id,
                index_type="vector", text_view="alpha",
            )
        )
    finally:
        initial.close()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "INSERT INTO source_item_work_refs (source_item_id, work_ref) VALUES (?, ?)",
            (source.id, "stale-ref"),
        )
        connection.execute("PRAGMA user_version=0")

    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(
        target=_initialize_main_and_report_work_ref_migration,
        args=(path, result_queue),
        kwargs={"relay_database_url": relay_url, "crash_after_version": True},
        daemon=True,
    )
    started = False
    exitcode = None
    cleanup_errors = []
    try:
        try:
            _start_hidden_owned_process(process)
        finally:
            started = process.pid is not None
        process.join(timeout=30)
    finally:
        if started:
            exitcode, errors = _reap_owned_process(process)
            cleanup_errors.extend(errors)
        try:
            result_queue.close()
        except Exception as exc:
            cleanup_errors.append(f"queue close failed: {exc!r}")
        try:
            result_queue.join_thread()
        except Exception as exc:
            cleanup_errors.append(f"queue join failed: {exc!r}")
        assert not cleanup_errors, "; ".join(cleanup_errors)
    assert exitcode == 73

    with closing(sqlite3.connect(path)) as connection, connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute(
            "SELECT work_ref FROM source_item_work_refs WHERE source_item_id=? ORDER BY work_ref",
            (source.id,),
        ).fetchall() == [("crash-ref",), ("stale-ref",)]

    retry = SQLiteStorageProvider(url, relay_database_url=relay_url)
    try:
        candidates = retry.get_source_item_vector_candidates(("crash-ref",))
        assert [entry.id for entry, _projection in candidates] == ["crash-vector"]
    finally:
        retry.close()
    assert _closed_pragma(path, "user_version") == 1
    from fastapi.testclient import TestClient

    from tests.test_exact_work_ref_search import _exact, _http_app_for_sqlite

    app = _http_app_for_sqlite(url, monkeypatch)
    with TestClient(app) as client:
        assert [item["source_item_id"] for item in _exact(client, "", "crash-ref")] == [source.id]


@pytest.mark.parametrize("scenario", ["valid", "version", "malformed-file"])
def test_readonly_main_preflight_closes_native_handle_on_success_and_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    path = tmp_path / f"preflight-handle-{scenario}.db"
    url = f"sqlite:///{path}"
    if scenario == "malformed-file":
        path.write_bytes(b"not a sqlite database")
    else:
        initial = SQLiteStorageProvider(url)
        initial.close()
    if scenario == "version":
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("PRAGMA user_version=2")

    original_connect = sqlite3.connect
    handles = []

    class ConnectionSpy:
        def __init__(self, connection):
            self.connection = connection
            self.closed = False

        def execute(self, *args, **kwargs):
            return self.connection.execute(*args, **kwargs)

        def close(self):
            self.closed = True
            self.connection.close()

    def connect_spy(database, *args, **kwargs):
        connection = original_connect(database, *args, **kwargs)
        if not handles and kwargs.get("uri") and "?mode=ro" in str(database):
            spy = ConnectionSpy(connection)
            handles.append(spy)
            return spy
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect_spy)
    if scenario == "valid":
        reopened = SQLiteStorageProvider(url)
        reopened.close()
    elif scenario == "malformed-file":
        with pytest.raises(sqlite3.DatabaseError):
            SQLiteStorageProvider(url)
    else:
        with pytest.raises(RuntimeError, match="Unsupported main database user_version"):
            SQLiteStorageProvider(url)
    assert len(handles) == 1
    assert handles[0].closed
    if scenario == "malformed-file":
        assert path.read_bytes() == b"not a sqlite database"


@pytest.mark.parametrize("race", ["version", "missing-metadata"])
def test_main_change_before_pragmas_recheck_refuses_before_engine_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, race: str
) -> None:
    from core.models import SourceItem

    path = tmp_path / f"preflight-{race}-race.db"
    url = f"sqlite:///{path}"
    source = SourceItem(
        source_type="chat", source_id="preflight-race", content_type="text/plain",
        content="alpha", metadata={"pallium_work_refs": ["kept-ref"]},
    )
    initial = SQLiteStorageProvider(url)
    try:
        initial.create_source_item(source)
    finally:
        initial.close()

    original_pragmas = SQLiteStorageProvider._initialize_sqlite_pragmas

    def change_version_after_native_preflight(provider, engine):
        if engine is provider._engine:
            with closing(sqlite3.connect(path)) as connection, connection:
                if race == "version":
                    connection.execute("PRAGMA user_version=2")
                else:
                    connection.execute(
                        "ALTER TABLE source_items RENAME COLUMN metadata_json TO metadata_gone"
                    )
        return original_pragmas(provider, engine)

    monkeypatch.setattr(
        SQLiteStorageProvider,
        "_initialize_sqlite_pragmas",
        change_version_after_native_preflight,
    )
    writes = []

    def observe_persistent_write(connection, _cursor, statement, _parameters, _context, _many):
        if Path(connection.engine.url.database).resolve() != path.resolve():
            return
        sql = " ".join(statement.upper().split())
        if sql.startswith((
            "PRAGMA AUTO_VACUUM=", "PRAGMA JOURNAL_MODE=", "PRAGMA MAIN.USER_VERSION=",
            "CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ", "REPLACE ",
        )):
            writes.append(sql)

    event.listen(Engine, "before_cursor_execute", observe_persistent_write)
    try:
        expected = (
            "Unsupported main database user_version"
            if race == "version"
            else "Incompatible source_items schema"
        )
        with pytest.raises(RuntimeError, match=expected):
            SQLiteStorageProvider(url)
    finally:
        event.remove(Engine, "before_cursor_execute", observe_persistent_write)
    assert writes == []
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (2 if race == "version" else 1)
        assert connection.execute(
            "SELECT work_ref FROM source_item_work_refs WHERE source_item_id=?",
            (source.id,),
        ).fetchall() == [("kept-ref",)]


@pytest.mark.parametrize("race", ["version", "missing-metadata"])
def test_main_change_before_locked_recheck_refuses_without_projection_delete(
    tmp_path: Path, race: str,
) -> None:
    from core.models import SourceItem

    path = tmp_path / f"locked-{race}-race.db"
    url = f"sqlite:///{path}"
    source = SourceItem(
        source_type="chat", source_id="locked-race", content_type="text/plain",
        content="alpha", metadata={"pallium_work_refs": ["kept-ref"]},
    )
    initial = SQLiteStorageProvider(url)
    try:
        initial.create_source_item(source)
    finally:
        initial.close()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "INSERT INTO source_item_work_refs (source_item_id, work_ref) VALUES (?, ?)",
            (source.id, "stale-ref"),
        )
        connection.execute("PRAGMA user_version=0")

    version_changed = []
    projection_deletes = []

    def change_version_before_begin(connection, _cursor, statement, _parameters, _context, _many):
        if Path(connection.engine.url.database).resolve() != path.resolve():
            return
        if " ".join(statement.upper().split()) != "BEGIN IMMEDIATE" or version_changed:
            return
        with closing(sqlite3.connect(path)) as native_connection, native_connection:
            if race == "version":
                native_connection.execute("PRAGMA user_version=2")
            else:
                native_connection.execute(
                    "ALTER TABLE source_items RENAME COLUMN metadata_json TO metadata_gone"
                )
        version_changed.append(True)

    def observe_projection_delete(connection, _cursor, statement, _parameters, _context, _many):
        if (
            Path(connection.engine.url.database).resolve() == path.resolve()
            and " ".join(statement.upper().split()) == "DELETE FROM SOURCE_ITEM_WORK_REFS"
        ):
            projection_deletes.append(statement)

    event.listen(Engine, "before_cursor_execute", change_version_before_begin)
    event.listen(Engine, "after_cursor_execute", observe_projection_delete)
    try:
        expected = (
            "Unsupported main database user_version"
            if race == "version"
            else "Incompatible source_items schema"
        )
        with pytest.raises(RuntimeError, match=expected):
            SQLiteStorageProvider(url)
    finally:
        event.remove(Engine, "before_cursor_execute", change_version_before_begin)
        event.remove(Engine, "after_cursor_execute", observe_projection_delete)
    assert version_changed == [True]
    assert projection_deletes == []
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (2 if race == "version" else 0)
        assert connection.execute(
            "SELECT work_ref FROM source_item_work_refs WHERE source_item_id=? ORDER BY work_ref",
            (source.id,),
        ).fetchall() == [("kept-ref",), ("stale-ref",)]


def test_writer_is_busy_during_backfill_and_provider_write_succeeds_afterward(
    tmp_path: Path,
) -> None:
    from core.models import IndexEntry, SourceItem

    path = tmp_path / "migration-writer-contention.db"
    url = f"sqlite:///{path}"
    source = SourceItem(
        source_type="chat", source_id="migration-contention", content_type="text/plain",
        content="alpha", metadata={"pallium_work_refs": ["migration-ref"]},
    )
    initial = SQLiteStorageProvider(url)
    try:
        initial.create_source_item(source)
        initial.create_index_entry(
            IndexEntry(
                id="migration-contention-vector", target_kind="source_item",
                target_id=source.id, index_type="vector", text_view="alpha",
            )
        )
    finally:
        initial.close()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "INSERT INTO source_item_work_refs (source_item_id, work_ref) VALUES (?, ?)",
            (source.id, "stale-ref"),
        )
        connection.execute("PRAGMA user_version=0")

    write_errors = []

    def observe_delete(connection, _cursor, statement, _parameters, _context, _many):
        if (
            Path(connection.engine.url.database).resolve() != path.resolve()
            or " ".join(statement.upper().split()) != "DELETE FROM SOURCE_ITEM_WORK_REFS"
        ):
            return
        with closing(sqlite3.connect(path, timeout=0)) as blocker:
            try:
                blocker.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                write_errors.append(exc.sqlite_errorcode)
            else:
                blocker.rollback()
                write_errors.append(None)

    event.listen(Engine, "after_cursor_execute", observe_delete)
    try:
        provider = SQLiteStorageProvider(url)
    finally:
        event.remove(Engine, "after_cursor_execute", observe_delete)
    try:
        assert write_errors == [5]
        written = SourceItem(
            source_type="chat", source_id="after-contention", content_type="text/plain",
            content="after", metadata={"pallium_work_refs": ["after-ref"]},
        )
        provider.create_source_item(written)
        provider.create_index_entry(
            IndexEntry(
                id="after-contention-vector", target_kind="source_item",
                target_id=written.id, index_type="vector", text_view="after",
            )
        )
        candidates = provider.get_source_item_vector_candidates(("after-ref",))
        assert [entry.id for entry, _projection in candidates] == ["after-contention-vector"]
    finally:
        provider.close()


def test_busy_migration_failure_preserves_preimage_and_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import OperationalError

    from core.models import IndexEntry, SourceItem

    path = tmp_path / "migration-busy-failure.db"
    url = f"sqlite:///{path}"
    source = SourceItem(
        source_type="chat", source_id="busy-source", content_type="text/plain",
        content="alpha", metadata={"pallium_work_refs": ["correct-ref"]},
    )
    initial = SQLiteStorageProvider(url)
    try:
        initial.create_source_item(source)
        initial.create_index_entry(
            IndexEntry(
                id="busy-vector", target_kind="source_item", target_id=source.id,
                index_type="vector", text_view="alpha",
            )
        )
    finally:
        initial.close()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "INSERT INTO source_item_work_refs (source_item_id, work_ref) VALUES (?, ?)",
            (source.id, "stale-ref"),
        )
        connection.execute("PRAGMA user_version=0")

    original_ensure = SQLiteStorageProvider._ensure_source_item_work_refs
    blocker_ready = []

    def hold_writer_during_migration(provider):
        with closing(sqlite3.connect(path, timeout=0)) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            blocker_ready.append(True)
            try:
                return original_ensure(provider)
            finally:
                blocker.rollback()

    monkeypatch.setattr(
        SQLiteStorageProvider,
        "_ensure_source_item_work_refs",
        hold_writer_during_migration,
    )
    timeouts = []

    def bound_test_connection_timeout(connection, _cursor, statement, _parameters, _context, _many):
        if (
            Path(connection.engine.url.database).resolve() == path.resolve()
            and " ".join(statement.upper().split()) == "BEGIN IMMEDIATE"
        ):
            connection.connection.driver_connection.execute("PRAGMA busy_timeout=100")
            timeouts.append(100)

    event.listen(Engine, "before_cursor_execute", bound_test_connection_timeout)
    try:
        with pytest.raises(OperationalError) as caught:
            SQLiteStorageProvider(url)
    finally:
        event.remove(Engine, "before_cursor_execute", bound_test_connection_timeout)
    assert blocker_ready == [True]
    assert timeouts == [100]
    assert getattr(caught.value.orig, "sqlite_errorcode", None) == 5
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute(
            "SELECT work_ref FROM source_item_work_refs WHERE source_item_id=? ORDER BY work_ref",
            (source.id,),
        ).fetchall() == [("correct-ref",), ("stale-ref",)]

    monkeypatch.setattr(
        SQLiteStorageProvider,
        "_ensure_source_item_work_refs",
        original_ensure,
    )
    retry = SQLiteStorageProvider(url)
    try:
        candidates = retry.get_source_item_vector_candidates(("correct-ref",))
        assert [entry.id for entry, _projection in candidates] == ["busy-vector"]
    finally:
        retry.close()
    assert _closed_pragma(path, "user_version") == 1


def test_memory_sqlite_storage_still_supports_source_work_ref_queries() -> None:
    from core.models import IndexEntry, SourceItem

    provider = SQLiteStorageProvider("sqlite:///:memory:")
    try:
        assert provider.get_source_item_vector_candidates(("memory-ref",)) == []
        source = SourceItem(
            source_type="chat", source_id="memory", content_type="text/plain",
            content="memory", metadata={"pallium_work_refs": ["memory-ref"]},
        )
        provider.create_source_item(source)
        provider.create_index_entry(
            IndexEntry(
                id="memory-vector", target_kind="source_item", target_id=source.id,
                index_type="vector", text_view="memory",
            )
        )
        candidates = provider.get_source_item_vector_candidates(("memory-ref",))
        assert [entry.id for entry, _projection in candidates] == ["memory-vector"]
        with provider._engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA main.user_version").scalar_one() == 1
    finally:
        provider.close()


@pytest.mark.parametrize("same_file", [False, True], ids=["separate-relay", "same-file"])
def test_main_migration_preserves_relay_lifecycle_and_manifest_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, same_file: bool,
) -> None:
    from core.relay import RelayConflictError
    from tests.test_relay_endpoint_repair_e2e import (
        DELIVERY_A,
        DELIVERY_B,
        _apply,
        _clean_wake_stores,
        _manifest,
        _seed,
    )

    main = tmp_path / f"relay-main-{same_file}.db"
    relay = main if same_file else tmp_path / "relay-separate.db"
    main_url = f"sqlite:///{main}"
    relay_url = f"sqlite:///{relay}"

    def seed_preupgrade_relay_and_manifest() -> dict:
        with closing(SQLiteStorageProvider(main_url, relay_database_url=relay_url)) as provider:
            scope = {"container_ref": "migration-scope"}
            for session in ("sender", "target"):
                provider.relay_turn(
                    runtime="codex", session_ref=session, title=None, max_chars=1000,
                    max_messages=1, lease_seconds=60, **scope,
                )

            def send(message_id: str) -> None:
                provider.relay_send(
                    message_id=message_id, sender_runtime="codex", sender_session_ref="sender",
                    recipient="codex:target", recipient_runtime="codex", recipient_kind="session",
                    recipient_value="target", payload=message_id, redacted=False,
                    expires_in_seconds=3600, in_reply_to=None, **scope,
                )

            send("claimed-message")
            claimed = provider.relay_turn(
                runtime="codex", session_ref="target", title=None, max_chars=1000,
                max_messages=1, lease_seconds=60, **scope,
            )["deliveries"][0]
            assert claimed["state"] == "claimed"
            send("delivered-message")
            delivered = provider.relay_turn(
                runtime="codex", session_ref="target", title=None, max_chars=1000,
                max_messages=1, lease_seconds=60, **scope,
            )["deliveries"][0]
            provider.relay_ack_by_receipt(
                delivery_id=delivered["delivery_id"], receipt=delivered["receipt"], **scope,
            )
            send("pending-message")
            assert provider.relay_message_status(message_id="claimed-message", **scope)["deliveries"][0]["state"] == "claimed"
            assert provider.relay_message_status(message_id="delivered-message", **scope)["deliveries"][0]["state"] == "delivered"
            assert provider.relay_message_status(message_id="pending-message", **scope)["deliveries"][0]["state"] == "pending"

            with closing(sqlite3.connect(main)) as connection, connection:
                connection.execute("PRAGMA user_version=0")
            _clean_wake_stores(tmp_path, monkeypatch)
            _seed(provider, datetime.now(timezone.utc))
            # Isolate the main migration from existing Relay statistics setup.
            tables_before_optimize = _tables(relay)
            provider._optimize_query_planner_stats(provider._relay_engine)
            if not same_file:
                assert "sqlite_stat1" not in tables_before_optimize
                assert _tables(relay) - tables_before_optimize == {"sqlite_stat1"}
            return _manifest(
                provider,
                [
                    {"delivery_id": DELIVERY_A, "disposition": "suppress"},
                    {"delivery_id": DELIVERY_B, "disposition": "suppress"},
                ],
            )

    manifest = seed_preupgrade_relay_and_manifest()

    before_relay = _relay_table_rows(relay)
    before_relay_version = _closed_pragma(relay, "user_version")
    reopened = SQLiteStorageProvider(main_url, relay_database_url=relay_url)
    try:
        assert _relay_table_rows(relay) == before_relay
        assert _closed_pragma(main, "user_version") == 1
        if same_file:
            assert before_relay_version == 0
            assert _closed_pragma(relay, "user_version") == 1
            with pytest.raises(RelayConflictError, match="repair database identity drifted"):
                _apply(reopened, manifest, datetime.now(timezone.utc))
            assert _relay_table_rows(relay) == before_relay
        else:
            assert _closed_pragma(relay, "user_version") == before_relay_version
            assert _closed_pragma(relay, "schema_version") == manifest["database_identity"]["schema_version"]
            _apply(reopened, manifest, datetime.now(timezone.utc))
    finally:
        reopened.close()
