from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest
from sqlalchemy import create_engine, text

from storage.relay_migration import migrate_relay_commit_sequences


def _migrate(path: str) -> None:
    engine = create_engine(f"sqlite:///{path}", future=True)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        migrate_relay_commit_sequences(connection)


def test_helper_allocates_all_writes_and_rejects_explicit_sequences(tmp_path):
    path = str(tmp_path / "relay.db")
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE relay_messages (id TEXT PRIMARY KEY, created_at TEXT NOT NULL)")
    _migrate(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO relay_messages (id, created_at) VALUES ('old-1', '2026-01-01')")
        with pytest.raises(sqlite3.IntegrityError, match="database assigned"):
            db.execute("INSERT INTO relay_messages (id, created_at, commit_seq) VALUES ('new-7', '2026-01-01', 7)")
        db.execute("INSERT INTO relay_messages (id, created_at) VALUES ('old-2', '2026-01-01')")
        assert db.execute("SELECT id, commit_seq FROM relay_messages ORDER BY commit_seq").fetchall() == [("old-1", 1), ("old-2", 2)]


def test_helper_concurrent_legacy_writers_receive_unique_sequences(tmp_path):
    path = str(tmp_path / "relay.db")
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE relay_messages (id TEXT PRIMARY KEY, created_at TEXT NOT NULL)")
    _migrate(path)
    def insert(index: int) -> None:
        with sqlite3.connect(path, timeout=5) as db:
            db.execute("INSERT INTO relay_messages (id, created_at) VALUES (?, '2026-01-01')", (f"old-{index}",))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(insert, range(16)))
    with sqlite3.connect(path) as db:
        seqs = [row[0] for row in db.execute("SELECT commit_seq FROM relay_messages ORDER BY commit_seq")]
    assert seqs == list(range(1, 17))


def test_helper_preserves_positive_rows_counter_ahead_ties_and_cleanup(tmp_path):
    path = str(tmp_path / "mixed.db")
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE relay_messages (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, commit_seq INTEGER NOT NULL DEFAULT 0)")
        db.executemany("INSERT INTO relay_messages VALUES (?, '2026-01-01', ?)", [("one", 1), ("a", 0), ("b", 0)])
        db.execute("CREATE TABLE relay_commit_counters (key TEXT PRIMARY KEY, next_seq INTEGER NOT NULL)")
        db.execute("INSERT INTO relay_commit_counters VALUES ('relay', 100)")
    _migrate(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT id, commit_seq FROM relay_messages ORDER BY id").fetchall() == [("a", 101), ("b", 102), ("one", 1)]
        db.execute("DELETE FROM relay_messages WHERE commit_seq=102")
        db.execute("INSERT INTO relay_messages (id, created_at) VALUES ('next', '2026-01-02')")
        assert db.execute("SELECT commit_seq FROM relay_messages WHERE id='next'").fetchone() == (103,)
@pytest.mark.parametrize("fault", ["ddl", "backfill", "seed", "index"])
def test_explicit_migration_rolls_back_every_fault_boundary(tmp_path, fault):
    path = tmp_path / f"{fault}.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE relay_messages (id TEXT PRIMARY KEY, created_at TEXT NOT NULL)")
        db.execute("INSERT INTO relay_messages VALUES ('legacy', '2026-01-01')")
    engine = create_engine(f"sqlite:///{path}", future=True)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        with pytest.raises(RuntimeError, match=fault):
            migrate_relay_commit_sequences(connection, fail_at=fault)
    with sqlite3.connect(path) as db:
        assert [row[1] for row in db.execute("PRAGMA table_info(relay_messages)")] == ["id", "created_at"]
        assert db.execute("SELECT name FROM sqlite_master WHERE name='relay_commit_counters'").fetchone() is None
    _migrate(str(path))
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT commit_seq FROM relay_messages WHERE id='legacy'").fetchone() == (1,)


def test_migration_backfills_and_old_relay_surfaces_keep_writing(client):
    relay_storage = client.app.state.pallium_service._storage
    from tests.test_agent_relay_e2e import _reply, _send, _turn
    _turn(client, "claude-code", "sender")
    _turn(client, "codex", "target")
    before = _send(client, "claude-code", "sender", "codex:target", "before").json()
    with relay_storage._engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        migrate_relay_commit_sequences(connection)
    after = _send(client, "claude-code", "sender", "codex:target", "after").json()
    claim = _turn(client, "codex", "target")["deliveries"][0]
    assert _reply(client, claim["delivery_id"], receipt=claim["receipt"]).status_code == 200
    with relay_storage._engine.connect() as connection:
        sequences = connection.execute(text("SELECT commit_seq FROM relay_messages ORDER BY commit_seq")).scalars().all()
    assert sequences == list(range(1, len(sequences) + 1))
    assert before["message_id"] != after["message_id"]

def test_repeated_and_concurrent_migration_initialization_is_idempotent(tmp_path):
    path = tmp_path / "repeat.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE relay_messages (id TEXT PRIMARY KEY, created_at TEXT NOT NULL)")
        db.execute("INSERT INTO relay_messages VALUES ('legacy', '2026-01-01')")

    def migrate() -> None:
        engine = create_engine(f"sqlite:///{path}", future=True)
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            migrate_relay_commit_sequences(connection)

    migrate()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: migrate(), range(2)))
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT commit_seq FROM relay_messages").fetchone() == (1,)
        assert db.execute("SELECT next_seq FROM relay_commit_counters WHERE key='relay'").fetchone() == (1,)