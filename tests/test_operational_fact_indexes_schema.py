"""W4 PR 2 — schema tests for the operational_fact partial indexes.

Verifies:
- Both new indexes present after schema init on both fresh and populated DBs.
- Migrations are idempotent (running _initialize_schema() twice does not
  duplicate the indexes or mutate data).
- The query planner actually uses the indexes for the two shapes we care
  about (active-lookup and supersession-walk).
- Coexistence with W3 indexes (no accidental drop or rename).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from storage.sqlite import SQLiteStorageProvider


NEW_INDEX_NAMES = (
    "idx_memory_objects_operational_fact_active",
    "idx_memory_objects_operational_fact_supersedes",
)

W3_INDEX_NAMES = (
    "idx_memory_objects_origin",
    "idx_memory_objects_superseded_by",
    "idx_memory_objects_soft_deleted",
)


@pytest.fixture
def fresh_store(tmp_path):
    db = tmp_path / "op_fact_indexes.db"
    yield SQLiteStorageProvider(database_url=f"sqlite:///{db}")


def _index_names(store) -> set[str]:
    with store._engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='memory_objects'"
            )
        ).fetchall()
    return {r[0] for r in rows}


def _seed_operational_fact(store, memory_id: str, *, superseded_by: str | None = None):
    """Insert an operational_fact row with the minimum columns required."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    payload = {"command_family": "python", "artifact_normalized": memory_id}
    with store._engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO memory_objects "
                "(id, container_ref, type, schema_id, schema_version, "
                " freshness_at, payload_json, "
                " lifecycle, superseded_by_id, is_soft_deleted, "
                " origin, created_at) "
                "VALUES "
                "(:id, :ref, 'operational_fact', 'op_fact', 'v1', "
                " :ts, :payload, "
                " 'active', :superseded_by, 0, "
                " 'agent_inferred', :ts)"
            ),
            {
                "id": memory_id,
                "ref": "git:example/repo",
                "ts": now,
                "payload": json.dumps(payload),
                "superseded_by": superseded_by,
            },
        )


class TestOperationalFactIndexMigration:
    def test_migration_creates_both_indexes_on_fresh_db(self, fresh_store):
        names = _index_names(fresh_store)
        for expected in NEW_INDEX_NAMES:
            assert expected in names, f"missing {expected} on fresh DB; got {names}"

    def test_migration_idempotent_on_empty_db(self, tmp_path):
        db = tmp_path / "op_fact_idx_idem_empty.db"
        s1 = SQLiteStorageProvider(database_url=f"sqlite:///{db}")
        # Re-run schema init on the same DB to confirm CREATE INDEX IF NOT EXISTS
        # does not double up or raise.
        s1._initialize_schema()
        names = _index_names(s1)
        for expected in NEW_INDEX_NAMES:
            assert expected in names

    def test_migration_idempotent_on_populated_db(self, fresh_store):
        _seed_operational_fact(fresh_store, "of-1")
        _seed_operational_fact(fresh_store, "of-2", superseded_by="of-1")
        with fresh_store._engine.connect() as conn:
            count_before = conn.execute(
                text("SELECT COUNT(*) FROM memory_objects")
            ).scalar()
        # Rerun schema init — should not touch data, not duplicate index.
        fresh_store._initialize_schema()
        with fresh_store._engine.connect() as conn:
            count_after = conn.execute(
                text("SELECT COUNT(*) FROM memory_objects")
            ).scalar()
        assert count_before == count_after == 2
        # sqlite_master lists each index once.
        names = list(
            r[0]
            for r in fresh_store._engine.connect()
            .execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='index' AND tbl_name='memory_objects'"
                )
            )
            .fetchall()
        )
        assert len([n for n in names if n in NEW_INDEX_NAMES]) == len(NEW_INDEX_NAMES)


class TestOperationalFactIndexPlanner:
    def test_index_used_for_active_lookup(self, fresh_store):
        _seed_operational_fact(fresh_store, "of-active-1")
        with fresh_store._engine.connect() as conn:
            plan = "\n".join(
                r[3]
                for r in conn.execute(
                    text(
                        "EXPLAIN QUERY PLAN "
                        "SELECT id FROM memory_objects "
                        "WHERE type='operational_fact' "
                        "  AND container_ref=:c "
                        "  AND lifecycle='active' "
                        "ORDER BY created_at DESC"
                    ),
                    {"c": "git:example/repo"},
                ).fetchall()
            )
        assert "idx_memory_objects_operational_fact_active" in plan, plan

    def test_index_used_for_supersession_walk(self, fresh_store):
        _seed_operational_fact(fresh_store, "of-super-1")
        _seed_operational_fact(fresh_store, "of-super-2", superseded_by="of-super-1")
        with fresh_store._engine.connect() as conn:
            plan = "\n".join(
                r[3]
                for r in conn.execute(
                    text(
                        "EXPLAIN QUERY PLAN "
                        "SELECT id FROM memory_objects "
                        "WHERE type='operational_fact' "
                        "  AND superseded_by_id IS NOT NULL"
                    )
                ).fetchall()
            )
        assert "idx_memory_objects_operational_fact_supersedes" in plan, plan

    def test_index_scoped_to_operational_fact_type(self, fresh_store):
        # A query for a different type should NOT be able to use the
        # operational_fact-specific partial indexes.
        with fresh_store._engine.connect() as conn:
            plan = "\n".join(
                r[3]
                for r in conn.execute(
                    text(
                        "EXPLAIN QUERY PLAN "
                        "SELECT id FROM memory_objects "
                        "WHERE type='decision' "
                        "  AND container_ref=:c "
                        "  AND lifecycle='active'"
                    ),
                    {"c": "git:example/repo"},
                ).fetchall()
            )
        for op_idx in NEW_INDEX_NAMES:
            assert op_idx not in plan, (
                f"Query planner should NOT use partial op-fact index for "
                f"type='decision'; plan uses {op_idx}"
            )


class TestSchemaCoexistence:
    def test_w3_indexes_still_present_after_w4_migration(self, fresh_store):
        names = _index_names(fresh_store)
        for w3_idx in W3_INDEX_NAMES:
            assert w3_idx in names, f"W3 index {w3_idx} missing"


class TestPartialDBStateSafety:
    def test_query_when_operational_fact_indexes_missing_still_returns_correct_result(
        self, fresh_store
    ):
        _seed_operational_fact(fresh_store, "of-fallback-1")
        # Simulate a partial-DB state: drop the operational_fact indexes.
        with fresh_store._engine.begin() as conn:
            for idx_name in NEW_INDEX_NAMES:
                conn.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
        with fresh_store._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id FROM memory_objects "
                    "WHERE type='operational_fact' "
                    "  AND container_ref=:c "
                    "  AND lifecycle='active'"
                ),
                {"c": "git:example/repo"},
            ).fetchone()
        assert row is not None
        assert row[0] == "of-fallback-1"
