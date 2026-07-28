"""Schema tests for the general container+lifecycle retrieval index.

Verifies:
- ``idx_memory_objects_container_lifecycle`` is present after schema init on
  both fresh and populated DBs, and the migration is idempotent.
- The query planner uses it for the hot ``list_memory_objects`` shapes:
  active-by-container, active-by-container with a ``type IN (...)`` filter,
  and candidate-by-container (which the work-trace dedup path issues).
- Coexistence: the pre-existing partial indexes on memory_objects are not
  dropped or renamed by this migration.
- ``PRAGMA optimize`` runs at schema-init so query-planner stats exist
  (sqlite_stat1 present), which is what fixes the join-order regression on
  populated DBs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from storage.sqlite import SQLiteStorageProvider


INDEX_NAME = "idx_memory_objects_container_lifecycle"

# Pre-existing indexes that must survive this migration untouched.
COEXISTING_INDEX_NAMES = (
    "idx_memory_objects_subject_lookup",
    "idx_memory_objects_origin",
    "idx_memory_objects_superseded_by",
    "idx_memory_objects_soft_deleted",
    "idx_memory_objects_operational_fact_active",
    "idx_memory_objects_operational_fact_supersedes",
)


@pytest.fixture
def fresh_store(tmp_path):
    db = tmp_path / "container_lifecycle_index.db"
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


def _seed_memory_object(
    store,
    memory_id: str,
    *,
    mem_type: str = "decision",
    lifecycle: str = "active",
    container_ref: str = "git:example/repo",
) -> None:
    now = datetime.now(timezone.utc)
    payload = {"decision": memory_id}
    with store._engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO memory_objects "
                "(id, container_ref, type, schema_id, schema_version, "
                " freshness_at, payload_json, lifecycle, is_soft_deleted, "
                " origin, created_at) "
                "VALUES "
                "(:id, :ref, :type, 'decision', 'v1', "
                " :ts, :payload, :lifecycle, 0, "
                " 'agent_inferred', :ts)"
            ),
            {
                "id": memory_id,
                "ref": container_ref,
                "type": mem_type,
                "ts": now,
                "payload": json.dumps(payload),
                "lifecycle": lifecycle,
            },
        )


def _plan(store, sql: str, params: dict) -> str:
    with store._engine.connect() as conn:
        return "\n".join(
            r[3]
            for r in conn.execute(text("EXPLAIN QUERY PLAN " + sql), params).fetchall()
        )


class TestContainerLifecycleIndexMigration:
    def test_index_present_on_fresh_db(self, fresh_store):
        assert INDEX_NAME in _index_names(fresh_store)

    def test_migration_idempotent(self, fresh_store):
        _seed_memory_object(fresh_store, "mo-1")
        _seed_memory_object(fresh_store, "mo-2", lifecycle="superseded")
        # Re-run schema init — CREATE INDEX IF NOT EXISTS must not duplicate
        # or raise, and data is untouched.
        fresh_store._initialize_schema()
        with fresh_store._engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM memory_objects")).scalar()
        assert count == 2
        names = [
            r[0]
            for r in fresh_store._engine.connect()
            .execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='index' AND tbl_name='memory_objects'"
                )
            )
            .fetchall()
        ]
        assert names.count(INDEX_NAME) == 1


class TestContainerLifecycleIndexPlanner:
    def test_index_used_for_active_by_container(self, fresh_store):
        _seed_memory_object(fresh_store, "mo-a")
        plan = _plan(
            fresh_store,
            "SELECT * FROM memory_objects "
            "WHERE container_ref=:c AND lifecycle='active' AND is_soft_deleted=0",
            {"c": "git:example/repo"},
        )
        assert INDEX_NAME in plan, plan
        assert "SCAN memory_objects" not in plan, plan

    def test_index_used_for_active_by_container_and_type(self, fresh_store):
        _seed_memory_object(fresh_store, "mo-b", mem_type="atomic_fact")
        plan = _plan(
            fresh_store,
            "SELECT * FROM memory_objects "
            "WHERE type IN ('atomic_fact','fact_summary') "
            "  AND container_ref=:c AND lifecycle='active' AND is_soft_deleted=0",
            {"c": "git:example/repo"},
        )
        assert INDEX_NAME in plan, plan
        assert "SCAN memory_objects" not in plan, plan

    def test_index_used_for_candidate_by_container(self, fresh_store):
        # Work-trace dedup issues lifecycle='candidate' + container_ref.
        _seed_memory_object(
            fresh_store, "mo-c", mem_type="operational_fact", lifecycle="candidate"
        )
        plan = _plan(
            fresh_store,
            "SELECT * FROM memory_objects "
            "WHERE type IN ('operational_fact') "
            "  AND container_ref=:c AND lifecycle='candidate' AND is_soft_deleted=0",
            {"c": "git:example/repo"},
        )
        assert INDEX_NAME in plan, plan
        assert "SCAN memory_objects" not in plan, plan


class TestSchemaCoexistence:
    def test_preexisting_indexes_still_present(self, fresh_store):
        names = _index_names(fresh_store)
        for idx in COEXISTING_INDEX_NAMES:
            assert idx in names, f"pre-existing index {idx} missing after migration"


class TestQueryPlannerStats:
    def test_optimize_runs_without_error(self, fresh_store):
        # _optimize_query_planner_stats must not raise on an empty or small DB.
        # PRAGMA optimize is adaptive — it skips ANALYZE when the table is too
        # small to bother, so sqlite_stat1 may not exist on a tiny test DB.
        # The contract is "no error" on small DBs and "stats populated" on
        # large ones; we only test the former here.
        _seed_memory_object(fresh_store, "mo-stats")
        fresh_store._initialize_schema()  # must not raise

    def test_analyze_stats_populated_on_large_db(self, tmp_path):
        # PRAGMA optimize creates sqlite_stat1 once the table is large enough
        # for the planner to bother. Seed enough rows to cross the threshold.
        db = tmp_path / "large.db"
        store = SQLiteStorageProvider(database_url=f"sqlite:///{db}")
        for i in range(200):
            _seed_memory_object(store, f"mo-{i}")
        store._initialize_schema()
        with store._engine.connect() as conn:
            has_stat = conn.execute(
                text("SELECT name FROM sqlite_master WHERE name='sqlite_stat1'")
            ).fetchone()
        assert has_stat is not None, "sqlite_stat1 should exist after optimize on a populated DB"
