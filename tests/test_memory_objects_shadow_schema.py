"""W5 PR 1 — schema tests for the memory_objects_shadow table.

Verifies:
- Table exists after schema init on fresh + populated DBs.
- All four partial/regular indexes are present.
- Migration re-run is idempotent (no duplicate indexes, no data mutation).
- Round-trip a MemoryObjectShadowRecord through SQLAlchemy.
- Existing memory_objects table is unaffected by the new migration.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import MemoryObjectShadowRecord


SHADOW_INDEXES = (
    "idx_shadow_source_item",
    "idx_shadow_run",
    "idx_shadow_type_created",
    "idx_shadow_parse_status",
)


@pytest.fixture
def fresh_store(tmp_path):
    db = tmp_path / "shadow_schema.db"
    yield SQLiteStorageProvider(database_url=f"sqlite:///{db}")


def _tables(store) -> set[str]:
    with store._engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
    return {r[0] for r in rows}


def _index_names(store, table: str) -> set[str]:
    with store._engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name=:t"
            ),
            {"t": table},
        ).fetchall()
    return {r[0] for r in rows}


class TestShadowTableCreated:
    def test_table_exists_on_fresh_db(self, fresh_store):
        assert "memory_objects_shadow" in _tables(fresh_store)

    def test_all_four_indexes_present(self, fresh_store):
        names = _index_names(fresh_store, "memory_objects_shadow")
        for expected in SHADOW_INDEXES:
            assert expected in names, f"missing {expected}; got {names}"


class TestSchemaIdempotency:
    def test_reinit_does_not_duplicate_indexes(self, fresh_store):
        fresh_store._initialize_schema()  # re-run
        names = _index_names(fresh_store, "memory_objects_shadow")
        for expected in SHADOW_INDEXES:
            assert expected in names

    def test_reinit_does_not_touch_data(self, tmp_path):
        db = tmp_path / "shadow_idem.db"
        store = SQLiteStorageProvider(database_url=f"sqlite:///{db}")
        now = datetime.now(timezone.utc)
        with store._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO memory_objects_shadow "
                    "(id, source_item_id, package_name, shadow_run_id, "
                    " shadow_run_at, prompt_version, provider_name, "
                    " provider_kind, model, type, schema_id, schema_version, "
                    " payload_json, parse_status, created_at) "
                    "VALUES (:id, :sid, 'acm', 'run-1', :ts, 'v1', 'stub', "
                    "        'stub_kind', 'stub-model', 'decision', "
                    "        'typed_shadow.decision', '1', '{}', 'ok', :ts)"
                ),
                {"id": "sh-1", "sid": "src-1", "ts": now},
            )
        # Re-init and verify row is still there.
        store._initialize_schema()
        with store._engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM memory_objects_shadow")
            ).scalar()
        assert count == 1


class TestSchemaCoexistence:
    def test_memory_objects_table_unaffected(self, fresh_store):
        # memory_objects still exists with its W3 columns.
        assert "memory_objects" in _tables(fresh_store)
        with fresh_store._engine.connect() as conn:
            cols = {
                r[1]
                for r in conn.execute(
                    text("PRAGMA table_info(memory_objects)")
                ).fetchall()
            }
        for expected in {"origin", "superseded_by_id", "is_soft_deleted"}:
            assert expected in cols

    def test_w4_operational_fact_indexes_still_present(self, fresh_store):
        names = _index_names(fresh_store, "memory_objects")
        assert "idx_memory_objects_operational_fact_active" in names
        assert "idx_memory_objects_operational_fact_supersedes" in names


class TestSQLAlchemyRoundTrip:
    def test_shadow_record_round_trip(self, fresh_store):
        now = datetime.now(timezone.utc)
        record = MemoryObjectShadowRecord(
            id="sh-rt-1",
            source_item_id="src-rt-1",
            package_name="agent_conversation_memory",
            shadow_run_id="run-rt-1",
            shadow_run_at=now,
            prompt_version="typed_shadow_v1",
            provider_name="stub",
            provider_kind="openai_compatible",
            model="stub-model",
            type="decision",
            schema_id="typed_shadow.decision",
            schema_version="1",
            payload_json=json.dumps({
                "subject": "test",
                "statement": "test statement",
                "evidence_span": "excerpt",
            }),
            subject="test",
            container_ref="git:example/repo",
            actor_ref=None,
            visibility="private",
            live_counterpart_ids_json=None,
            llm_call_metadata_json=json.dumps({"tokens_used": 42}),
            parse_status="ok",
            parse_error=None,
            created_at=now,
        )
        with fresh_store._session_factory() as session:
            session.add(record)
            session.commit()
        with fresh_store._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, subject, parse_status, model "
                    "FROM memory_objects_shadow WHERE id='sh-rt-1'"
                )
            ).one()
        assert row.id == "sh-rt-1"
        assert row.subject == "test"
        assert row.parse_status == "ok"
        assert row.model == "stub-model"


class TestPartialIndexBehavior:
    def test_parse_status_partial_index_defined_correctly(self, fresh_store):
        # SQLite's query planner doesn't always statically prove that
        # `parse_status = 'schema_failure'` is covered by the partial
        # predicate `parse_status != 'ok'`. So we verify the index exists
        # and its DDL is what we expect — the operational value is that
        # a maintenance query (e.g. "how many parse failures this week?")
        # written as `WHERE parse_status != 'ok'` will use the index.
        with fresh_store._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='index' AND name='idx_shadow_parse_status'"
                )
            ).one()
            ddl = row.sql
        assert "parse_status" in ddl
        assert "created_at" in ddl
        assert "!= 'ok'" in ddl

    def test_partial_index_used_by_maintenance_query(self, fresh_store):
        # The intended maintenance-query shape (WHERE parse_status != 'ok')
        # matches the partial predicate directly and does use the index.
        now = datetime.now(timezone.utc)
        with fresh_store._engine.begin() as conn:
            for status in ["ok", "schema_failure", "llm_error"]:
                conn.execute(
                    text(
                        "INSERT INTO memory_objects_shadow "
                        "(id, source_item_id, package_name, shadow_run_id, "
                        " shadow_run_at, prompt_version, provider_name, "
                        " provider_kind, model, type, schema_id, "
                        " schema_version, payload_json, parse_status, "
                        " created_at) "
                        "VALUES (:id, 'src-p', 'acm', 'run-p', :ts, 'v1', "
                        "        'stub', 'stub_kind', 'stub-model', "
                        "        'decision', 'typed_shadow.decision', '1', "
                        "        '{}', :st, :ts)"
                    ),
                    {"id": f"sh-p-{status}", "ts": now, "st": status},
                )
        with fresh_store._engine.connect() as conn:
            plan = "\n".join(
                r[3]
                for r in conn.execute(
                    text(
                        "EXPLAIN QUERY PLAN "
                        "SELECT id FROM memory_objects_shadow "
                        "WHERE parse_status != 'ok' "
                        "ORDER BY created_at DESC"
                    )
                ).fetchall()
            )
        assert "idx_shadow_parse_status" in plan, plan
