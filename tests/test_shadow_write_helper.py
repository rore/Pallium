"""W5 PR 1 — insert_shadow_extraction helper tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import MemoryObjectShadowRecord


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "shadow_helper.db"
    return SQLiteStorageProvider(database_url=f"sqlite:///{db}")


def _make_row(
    *,
    row_id: str,
    run_id: str,
    parse_status: str = "ok",
    parse_error: str | None = None,
    payload: dict | None = None,
    subject: str = "test-subject",
) -> MemoryObjectShadowRecord:
    now = datetime.now(timezone.utc)
    return MemoryObjectShadowRecord(
        id=row_id,
        source_item_id="src-helper",
        package_name="agent_conversation_memory",
        shadow_run_id=run_id,
        shadow_run_at=now,
        prompt_version="typed_shadow_v1",
        provider_name="stub",
        provider_kind="openai_compatible",
        model="stub-model",
        type="decision",
        schema_id="typed_shadow.decision",
        schema_version="1",
        payload_json=json.dumps(payload or {"statement": "hi"}),
        subject=subject,
        container_ref="git:example/repo",
        actor_ref=None,
        visibility="private",
        live_counterpart_ids_json=None,
        llm_call_metadata_json=None,
        parse_status=parse_status,
        parse_error=parse_error,
        created_at=now,
    )


class TestInsertShadowExtraction:
    def test_happy_path_writes_rows(self, store):
        rows = [
            _make_row(row_id="sh-1", run_id="run-1"),
            _make_row(row_id="sh-2", run_id="run-1"),
        ]
        store.insert_shadow_extraction(rows=rows)
        with store._engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM memory_objects_shadow "
                     "WHERE shadow_run_id='run-1'")
            ).scalar()
        assert count == 2

    def test_empty_rows_no_op(self, store):
        store.insert_shadow_extraction(rows=[])
        with store._engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM memory_objects_shadow")
            ).scalar()
        assert count == 0

    def test_schema_failure_row_persisted(self, store):
        rows = [
            _make_row(
                row_id="sh-sf-1",
                run_id="run-sf",
                parse_status="schema_failure",
                parse_error="missing required key 'statement'",
                payload={},
            ),
        ]
        store.insert_shadow_extraction(rows=rows)
        with store._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT parse_status, parse_error FROM memory_objects_shadow "
                    "WHERE id='sh-sf-1'"
                )
            ).one()
        assert row.parse_status == "schema_failure"
        assert "missing required key" in row.parse_error

    def test_llm_error_row_persisted(self, store):
        rows = [
            _make_row(
                row_id="sh-le-1",
                run_id="run-le",
                parse_status="llm_error",
                parse_error="timeout after 30s",
                payload={},
            ),
        ]
        store.insert_shadow_extraction(rows=rows)
        with store._engine.connect() as conn:
            status = conn.execute(
                text(
                    "SELECT parse_status FROM memory_objects_shadow "
                    "WHERE id='sh-le-1'"
                )
            ).scalar()
        assert status == "llm_error"

    def test_unicode_subject_round_trip(self, store):
        rows = [_make_row(row_id="sh-uc-1", run_id="run-uc", subject="résumé π_env")]
        store.insert_shadow_extraction(rows=rows)
        with store._engine.connect() as conn:
            subject = conn.execute(
                text(
                    "SELECT subject FROM memory_objects_shadow "
                    "WHERE id='sh-uc-1'"
                )
            ).scalar()
        assert subject == "résumé π_env"

    def test_concurrent_writes_serialize(self, store):
        # Two "concurrent" runs on the same source item — the helper
        # uses _with_retry which serializes on session.begin().
        rows_a = [_make_row(row_id=f"sh-a-{i}", run_id="run-a") for i in range(3)]
        rows_b = [_make_row(row_id=f"sh-b-{i}", run_id="run-b") for i in range(3)]
        store.insert_shadow_extraction(rows=rows_a)
        store.insert_shadow_extraction(rows=rows_b)
        with store._engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM memory_objects_shadow")
            ).scalar()
        assert count == 6

    def test_shadow_write_does_not_touch_memory_objects(self, store):
        rows = [_make_row(row_id="sh-iso-1", run_id="run-iso")]
        with store._engine.connect() as conn:
            before = conn.execute(
                text("SELECT COUNT(*) FROM memory_objects")
            ).scalar()
        store.insert_shadow_extraction(rows=rows)
        with store._engine.connect() as conn:
            after = conn.execute(
                text("SELECT COUNT(*) FROM memory_objects")
            ).scalar()
        assert before == after == 0

    def test_shadow_write_does_not_touch_relations_or_index_entries(self, store):
        rows = [_make_row(row_id="sh-iso-2", run_id="run-iso-2")]
        store.insert_shadow_extraction(rows=rows)
        with store._engine.connect() as conn:
            rel_count = conn.execute(
                text("SELECT COUNT(*) FROM relations")
            ).scalar()
            idx_count = conn.execute(
                text("SELECT COUNT(*) FROM index_entries")
            ).scalar()
        assert rel_count == 0
        assert idx_count == 0
