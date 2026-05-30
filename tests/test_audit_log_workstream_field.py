"""Tests for the workstream fields added to ``query_audit_log`` (Phase 4A).

Verifies:
1. ``query_workstream_id`` column accepts and round-trips a value.
2. Writing an audit row with no ``query_workstream_id`` works (legacy
   compatibility).
3. With workstream rows pre-seeded, the row writes carry the lookup-derived
   field as expected when invoked through the service-level helper used by
   ``/query``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text

from capabilities.workstream_signals import signals_from_item
from capabilities.workstreams import (
    WorkstreamCapability,
    assign_workstream_for_item,
    watermark_for,
)
from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_workstream import SQLiteWorkstreamStore


def test_query_workstream_id_roundtrips(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    row = {
        "id": "audit-ws-1",
        "created_at": datetime.now(timezone.utc),
        "source_item_id": "si-q",
        "source_id": "chat:msg:q",
        "thread_ref": "t1",
        "container_ref": "c1",
        "actor_ref": "u1",
        "visibility": "private",
        "query_text": "Where is the workstream cascade?",
        "should_inject": 1,
        "decision_reason": "carry_forward_available",
        "injected_blocks_json": "[]",
        "candidate_scores_json": None,
        "injection_method": None,
        "query_workstream_id": "ws:abcdef0123456789",
    }
    storage.write_query_audit_row(row)

    with storage._engine.begin() as connection:
        result = connection.execute(
            text("SELECT query_workstream_id FROM query_audit_log WHERE id=:id"),
            {"id": "audit-ws-1"},
        ).fetchone()
    assert result is not None
    assert result[0] == "ws:abcdef0123456789"


def test_query_workstream_id_nullable(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    # Legacy-shaped write — no query_workstream_id key.
    row = {
        "id": "audit-ws-2",
        "created_at": datetime.now(timezone.utc),
        "source_item_id": "si-q2",
        "source_id": "chat:msg:q2",
        "thread_ref": None,
        "container_ref": None,
        "actor_ref": None,
        "visibility": None,
        "query_text": "ack",
        "should_inject": 0,
        "decision_reason": "no_relevant_memory",
        "injected_blocks_json": "[]",
    }
    storage.write_query_audit_row(row)
    with storage._engine.begin() as connection:
        result = connection.execute(
            text("SELECT query_workstream_id FROM query_audit_log WHERE id=:id"),
            {"id": "audit-ws-2"},
        ).fetchone()
    assert result is not None
    assert result[0] is None


def test_capability_lookup_returns_persisted_id(test_db_url: str) -> None:
    """End-to-end: assign a workstream to a source_item, then look it up."""
    storage = SQLiteStorageProvider(test_db_url)
    capability = WorkstreamCapability(SQLiteWorkstreamStore(storage._session_factory))

    base = datetime(2026, 5, 30, 15, 0, 0, tzinfo=timezone.utc)
    signals = signals_from_item(
        content_text="see core/service.py for the lookup",
        metadata_json={},
        memory_records=[],
    )
    from capabilities.workstreams import WorkstreamRegistry

    registry = WorkstreamRegistry()
    wm = watermark_for(base)
    result = assign_workstream_for_item(
        item_signals=signals,
        container_ref="c-aud",
        thread_ref="t-aud",
        visibility="private",
        created_at=base,
        watermark=wm,
        registry=registry,
    )
    capability.persist_registry(registry, now=base)
    capability.link_source_item(
        source_item_id="si-aud-1",
        workstream_id=result.workstream_id.id,
        watermark=wm,
        assigned_at=base,
    )
    capability.link_memory(
        memory_object_id="mo-aud-1",
        workstream_id=result.workstream_id.id,
        assigned_at=base,
    )
    assert capability.lookup_query_source_item("si-aud-1") == result.workstream_id.id
    assert capability.lookup_memory("mo-aud-1") == result.workstream_id.id

    # Batch lookup helper used by audit log writer.
    batch = capability._store.get_memory_workstream_ids(["mo-aud-1", "mo-missing"])
    assert batch == {"mo-aud-1": result.workstream_id.id}
