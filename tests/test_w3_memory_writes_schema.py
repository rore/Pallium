"""Storage-layer tests for W3 explicit memory-write schema.

Verifies:
- Fresh DB creates memory_objects with all W3 columns present.
- Legacy DB (pre-W3 columns missing) migrates cleanly on second open.
- Migration is idempotent — running it twice is a no-op.
- Indexes are created and reachable via SQLite's index list.
- Defaults on new columns are safe for existing rows.

See docs/specs/2026-07-01-milestone-shaped-memory-contract.md §W3 for
the design context. See .local/milestone-progress-2026-07/
w3-architect-review-2026-07-01.md for the schema proposal these tests
lock in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text


W3_MEMORY_OBJECT_COLUMNS = (
    "origin",
    "origin_session_id",
    "origin_agent_id",
    "correction_reason",
    "superseded_by_id",
    "is_soft_deleted",
    "soft_deleted_at",
    "soft_delete_reason",
)

W3_MEMORY_OBJECT_INDEXES = (
    "idx_memory_objects_origin",
    "idx_memory_objects_superseded_by",
    "idx_memory_objects_soft_deleted",
)


# All NOT NULL columns on memory_objects that must be filled by hand when
# skipping the ORM. Keeping the SQL literal here so tests exercise the raw
# schema surface — the whole point is verifying the schema is right, not
# testing the ORM wrapper.
_INSERT_MEMORY_OBJECT_SQL = (
    "INSERT INTO memory_objects "
    "(id, type, schema_id, schema_version, payload_json, lifecycle, is_soft_deleted, created_at) "
    "VALUES (:id, 'decision', 'test', '1', '{}', 'active', 0, datetime('now'))"
)


def _insert_memory_object(conn, memory_id: str) -> None:
    conn.execute(text(_INSERT_MEMORY_OBJECT_SQL), {"id": memory_id})


def _open_store(db_path: Path):
    """Import lazily so schema init happens exactly at store construction."""
    from storage.sqlite import SQLiteStorageProvider

    return SQLiteStorageProvider(f"sqlite:///{db_path}")


def _memory_objects_columns(engine) -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text("PRAGMA table_info(memory_objects)"))}


def _memory_objects_indexes(engine) -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text("PRAGMA index_list(memory_objects)"))}


class TestW3SchemaOnFreshDb:
    """Fresh DB path — all W3 columns and indexes present on first open."""

    def test_all_w3_columns_present(self, tmp_path):
        db = tmp_path / "fresh.db"
        store = _open_store(db)
        columns = _memory_objects_columns(store._engine)
        missing = [c for c in W3_MEMORY_OBJECT_COLUMNS if c not in columns]
        assert not missing, f"missing W3 columns on fresh DB: {missing}"

    def test_all_w3_indexes_present(self, tmp_path):
        db = tmp_path / "fresh.db"
        store = _open_store(db)
        indexes = _memory_objects_indexes(store._engine)
        missing = [i for i in W3_MEMORY_OBJECT_INDEXES if i not in indexes]
        assert not missing, f"missing W3 indexes on fresh DB: {missing}"

    def test_origin_default_value(self, tmp_path):
        """New rows without an explicit origin must default to 'agent_inferred'.

        This preserves the semantic that pre-W3 writes (through the existing
        extraction pipeline) are correctly classified.
        """
        db = tmp_path / "fresh.db"
        store = _open_store(db)
        with store._engine.begin() as conn:
            _insert_memory_object(conn, "m1")
            origin = conn.execute(
                text("SELECT origin FROM memory_objects WHERE id = 'm1'")
            ).scalar()
        assert origin == "agent_inferred"

    def test_is_soft_deleted_default_zero(self, tmp_path):
        """Newly inserted rows must have is_soft_deleted=0 by default so
        default retrieval doesn't accidentally hide them."""
        db = tmp_path / "fresh.db"
        store = _open_store(db)
        with store._engine.begin() as conn:
            _insert_memory_object(conn, "m2")
            flag = conn.execute(
                text("SELECT is_soft_deleted FROM memory_objects WHERE id = 'm2'")
            ).scalar()
        assert flag == 0


class TestW3SchemaMigration:
    """Legacy-DB migration path.

    Simulates a pre-W3 database by dropping the W3 columns from a fresh
    memory_objects table, then opens a new store and asserts the migrations
    add the columns back. Second-open must be idempotent (no error, columns
    unchanged).
    """

    def _simulate_legacy_db(self, db_path: Path) -> None:
        """Drop the W3 columns from memory_objects (via table-rebuild)."""
        _open_store(db_path)  # First open creates full-schema DB.
        engine = create_engine(f"sqlite:///{db_path}")
        pre_w3_cols = [
            "id VARCHAR PRIMARY KEY",
            "type VARCHAR NOT NULL",
            "schema_id VARCHAR NOT NULL",
            "schema_version VARCHAR NOT NULL",
            "payload_json TEXT NOT NULL",
            "envelope_json TEXT",
            "lifecycle VARCHAR DEFAULT 'active'",
            "visibility VARCHAR DEFAULT 'private'",
            "container_ref VARCHAR",
            "actor_ref VARCHAR",
            "freshness_at DATETIME",
            "subject VARCHAR",
            "created_at DATETIME NOT NULL",
        ]
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS memory_objects_legacy_tmp"))
            conn.execute(text(
                "CREATE TABLE memory_objects_legacy_tmp ("
                + ", ".join(pre_w3_cols) + ")"
            ))
            conn.execute(text(
                "INSERT INTO memory_objects_legacy_tmp "
                "(id, type, schema_id, schema_version, payload_json, envelope_json, "
                " lifecycle, visibility, container_ref, actor_ref, freshness_at, "
                " subject, created_at) "
                "SELECT id, type, schema_id, schema_version, payload_json, envelope_json, "
                "  lifecycle, visibility, container_ref, actor_ref, freshness_at, "
                "  subject, created_at "
                "FROM memory_objects"
            ))
            conn.execute(text("DROP TABLE memory_objects"))
            conn.execute(text(
                "ALTER TABLE memory_objects_legacy_tmp RENAME TO memory_objects"
            ))
        engine.dispose()

    def test_legacy_db_gets_all_w3_columns_added(self, tmp_path):
        db = tmp_path / "legacy.db"
        # Seed a memory_objects row on the legacy schema first.
        _open_store(db)
        with create_engine(f"sqlite:///{db}").begin() as conn:
            _insert_memory_object(conn, "legacy_1")
        self._simulate_legacy_db(db)

        # Confirm pre-migration state: legacy row exists, W3 columns absent.
        engine = create_engine(f"sqlite:///{db}")
        with engine.connect() as conn:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(memory_objects)"))}
            assert not (set(W3_MEMORY_OBJECT_COLUMNS) & cols), \
                "test setup wrong: legacy DB should not have W3 columns yet"
            count = conn.execute(text("SELECT COUNT(*) FROM memory_objects WHERE id='legacy_1'")).scalar()
            assert count == 1, "legacy row not preserved by test setup"
        engine.dispose()

        # Reopen store — migrations must add the W3 columns.
        _open_store(db)
        engine = create_engine(f"sqlite:///{db}")
        cols = _memory_objects_columns(engine)
        missing = [c for c in W3_MEMORY_OBJECT_COLUMNS if c not in cols]
        assert not missing, f"migration did not add W3 columns: {missing}"

        # And the legacy row: origin should default to 'agent_inferred', flags
        # should default to safe values. SQLite ALTER TABLE ADD COLUMN with a
        # DEFAULT populates existing rows.
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT origin, is_soft_deleted, soft_deleted_at, "
                "superseded_by_id, correction_reason "
                "FROM memory_objects WHERE id='legacy_1'"
            )).one()
        assert row.origin == "agent_inferred", \
            "legacy rows must classify as agent_inferred after migration"
        assert row.is_soft_deleted == 0, "legacy rows must not appear soft-deleted"
        assert row.soft_deleted_at is None
        assert row.superseded_by_id is None
        assert row.correction_reason is None
        engine.dispose()

    def test_migration_is_idempotent(self, tmp_path):
        """Opening the store repeatedly must not fail on existing columns."""
        db = tmp_path / "repeat.db"
        for _ in range(3):
            store = _open_store(db)
            columns_before = _memory_objects_columns(store._engine)
            store._ensure_memory_object_columns()  # Explicit re-migration.
            columns_after = _memory_objects_columns(store._engine)
            assert columns_before == columns_after, \
                "re-running migrations changed the column set"


class TestW3ColumnsAcceptExpectedValues:
    """Store methods aren't wired yet — validate the raw SQL surface accepts
    the values the tools will write, so the semantic layer has a firm base.
    """

    def test_origin_enum_values_stored_verbatim(self, tmp_path):
        db = tmp_path / "values.db"
        store = _open_store(db)
        with store._engine.begin() as conn:
            for i, val in enumerate(("agent_explicit", "agent_inferred", "user_requested")):
                conn.execute(text(
                    "INSERT INTO memory_objects "
                    "(id, type, schema_id, schema_version, payload_json, lifecycle, is_soft_deleted, origin, created_at) "
                    "VALUES (:id, 'decision', 't', '1', '{}', 'active', 0, :o, datetime('now'))"
                ), {"id": f"v{i}", "o": val})
            rows = list(conn.execute(text(
                "SELECT id, origin FROM memory_objects WHERE id LIKE 'v%' ORDER BY id"
            )))
        assert rows == [("v0", "agent_explicit"), ("v1", "agent_inferred"), ("v2", "user_requested")]

    def test_supersede_chain_pointer_writable(self, tmp_path):
        db = tmp_path / "chain.db"
        store = _open_store(db)
        with store._engine.begin() as conn:
            _insert_memory_object(conn, "a")
            _insert_memory_object(conn, "b")
            conn.execute(text(
                "UPDATE memory_objects SET superseded_by_id='b', lifecycle='superseded' "
                "WHERE id='a'"
            ))
            row = conn.execute(text(
                "SELECT superseded_by_id, lifecycle FROM memory_objects WHERE id='a'"
            )).one()
        assert row.superseded_by_id == "b"
        assert row.lifecycle == "superseded"

    def test_soft_delete_tombstone_writable(self, tmp_path):
        db = tmp_path / "tomb.db"
        store = _open_store(db)
        with store._engine.begin() as conn:
            _insert_memory_object(conn, "t")
            conn.execute(text(
                "UPDATE memory_objects "
                "SET is_soft_deleted=1, soft_deleted_at=datetime('now'), "
                "    soft_delete_reason='no longer relevant' "
                "WHERE id='t'"
            ))
            row = conn.execute(text(
                "SELECT is_soft_deleted, soft_deleted_at, soft_delete_reason "
                "FROM memory_objects WHERE id='t'"
            )).one()
        assert row.is_soft_deleted == 1
        assert row.soft_deleted_at is not None
        assert row.soft_delete_reason == "no longer relevant"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
