"""Smoke test for workstream schema additions (Phase 4A, design 014).

Verifies that the three new workstream tables and the additive
``query_audit_log.query_workstream_id`` column exist after schema init.
"""
from __future__ import annotations

from sqlalchemy import text

from storage.sqlite import SQLiteStorageProvider


def _columns(connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}


def _indexes(connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(text(f"PRAGMA index_list({table})"))}


def test_workstream_tables_exist(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    with storage._engine.begin() as connection:
        existing_tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        assert "workstreams" in existing_tables
        assert "memory_workstreams" in existing_tables
        assert "source_item_workstreams" in existing_tables

        ws_cols = _columns(connection, "workstreams")
        for c in (
            "id",
            "container_ref",
            "visibility",
            "kind",
            "signature_blob",
            "opened_at",
            "last_touched_at",
            "closed_at",
            "closed_reason",
            "canonical_id",
            "created_by",
        ):
            assert c in ws_cols, f"workstreams missing {c}"

        mw_cols = _columns(connection, "memory_workstreams")
        for c in ("memory_object_id", "workstream_id", "assigned_at"):
            assert c in mw_cols, f"memory_workstreams missing {c}"

        siw_cols = _columns(connection, "source_item_workstreams")
        for c in ("source_item_id", "workstream_id", "watermark", "assigned_at"):
            assert c in siw_cols, f"source_item_workstreams missing {c}"


def test_query_audit_log_workstream_column(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    with storage._engine.begin() as connection:
        cols = _columns(connection, "query_audit_log")
        assert "query_workstream_id" in cols


def test_workstream_indexes_exist(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    with storage._engine.begin() as connection:
        ws_indexes = _indexes(connection, "workstreams")
        assert "idx_workstreams_container_visibility" in ws_indexes
        assert "idx_workstreams_last_touched" in ws_indexes
        mw_indexes = _indexes(connection, "memory_workstreams")
        assert "idx_memory_workstreams_ws" in mw_indexes
        assert "idx_memory_workstreams_mid" in mw_indexes
        siw_indexes = _indexes(connection, "source_item_workstreams")
        assert "idx_source_item_workstreams_si" in siw_indexes
        assert "idx_source_item_workstreams_ws" in siw_indexes
        assert "idx_source_item_workstreams_wm" in siw_indexes
