"""Integration test for workstream assignment persistence (Phase 4A, design 014).

Verifies that running the workstream assignment cascade against a SQLite
storage instance produces the expected rows in ``workstreams``,
``memory_workstreams``, and ``source_item_workstreams`` — and that the
flow is idempotent on the composite primary keys.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from capabilities.workstream_signals import signals_from_item
from capabilities.workstreams import (
    WorkstreamCapability,
    WorkstreamRegistry,
    assign_workstream_for_item,
    watermark_for,
)
from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_workstream import SQLiteWorkstreamStore


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _assign_for_items(capability: WorkstreamCapability, *, items, container_ref: str, visibility: str):
    """Run the cascade on a list of (id, thread_ref, content, metadata, created_at, memories)."""
    registry = capability.load_registry(container_ref=container_ref, visibility=visibility)
    assigned: list[tuple[str, str]] = []
    for item in items:
        signals = signals_from_item(
            content_text=item["content"],
            metadata_json=item.get("metadata") or {},
            memory_records=item.get("memory_records") or [],
        )
        wm = watermark_for(item["created_at"])
        result = assign_workstream_for_item(
            item_signals=signals,
            container_ref=container_ref,
            thread_ref=item.get("thread_ref"),
            visibility=visibility,
            created_at=item["created_at"],
            watermark=wm,
            registry=registry,
        )
        ws_id = result.workstream_id
        if ws_id.kind == "unknown":
            capability.record_unknown_workstream(
                ws_id=ws_id, container_ref=container_ref, visibility=visibility, opened_at=item["created_at"],
            )
        capability.link_source_item(
            source_item_id=item["id"],
            workstream_id=ws_id.id,
            watermark=wm,
            assigned_at=item["created_at"],
            stage=result.stage,
        )
        for mem_id in item.get("memory_ids", []):
            capability.link_memory(
                memory_object_id=mem_id,
                workstream_id=ws_id.id,
                assigned_at=item["created_at"],
            )
        assigned.append((item["id"], ws_id.id))
    capability.persist_registry(registry, now=_utcnow())
    return assigned


def test_workstream_assignment_writes_rows(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    capability = WorkstreamCapability(SQLiteWorkstreamStore(storage._session_factory))

    base = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    items = [
        {
            "id": "item-1",
            "thread_ref": "t1",
            "content": "edit core/service.py to fix WorkstreamRegistry init",
            "metadata": {},
            "created_at": base,
            "memory_ids": ["mem-1"],
        },
        {
            "id": "item-2",
            "thread_ref": "t1",
            "content": "more changes in core/service.py for the cascade",
            "metadata": {},
            "created_at": base + timedelta(minutes=10),
            "memory_ids": ["mem-2"],
        },
        {
            "id": "item-3",
            "thread_ref": "t2",
            "content": "now look at storage/sqlite_codec.py for envelope decode",
            "metadata": {},
            "created_at": base + timedelta(minutes=30),
            "memory_ids": ["mem-3"],
        },
    ]
    assigned = _assign_for_items(capability, items=items, container_ref="c1", visibility="private")

    ws_ids = [ws_id for _, ws_id in assigned]
    # items 1 & 2 share a file_dir → same ws; item 3 distinct.
    assert ws_ids[0] == ws_ids[1]
    assert ws_ids[0] != ws_ids[2]

    with storage._session_factory() as session:
        ws_rows = session.execute(text("SELECT id, kind, container_ref, visibility FROM workstreams")).fetchall()
        kinds = {row[1] for row in ws_rows}
        assert "resolved" in kinds  # at least the two resolved workstreams

        siw_rows = session.execute(text(
            "SELECT source_item_id, workstream_id, watermark FROM source_item_workstreams "
            "ORDER BY source_item_id"
        )).fetchall()
        assert len(siw_rows) == 3

        mw_rows = session.execute(text(
            "SELECT memory_object_id, workstream_id FROM memory_workstreams ORDER BY memory_object_id"
        )).fetchall()
        assert len(mw_rows) == 3
        # mem-1 and mem-2 share workstream
        m1 = next(r for r in mw_rows if r[0] == "mem-1")
        m2 = next(r for r in mw_rows if r[0] == "mem-2")
        m3 = next(r for r in mw_rows if r[0] == "mem-3")
        assert m1[1] == m2[1]
        assert m1[1] != m3[1]


def test_workstream_assignment_idempotent_on_rerun(test_db_url: str) -> None:
    storage = SQLiteStorageProvider(test_db_url)
    capability = WorkstreamCapability(SQLiteWorkstreamStore(storage._session_factory))

    base = datetime(2026, 5, 30, 13, 0, 0, tzinfo=timezone.utc)
    items = [
        {
            "id": "iitem-A",
            "thread_ref": "tA",
            "content": "see capabilities/workstreams.py for the cascade",
            "metadata": {},
            "created_at": base,
            "memory_ids": ["mem-A"],
        },
    ]
    _assign_for_items(capability, items=items, container_ref="cX", visibility="private")
    _assign_for_items(capability, items=items, container_ref="cX", visibility="private")

    with storage._session_factory() as session:
        siw_count = session.execute(text(
            "SELECT COUNT(*) FROM source_item_workstreams WHERE source_item_id='iitem-A'"
        )).scalar()
        # Composite PK = (source_item_id, workstream_id, watermark).
        # Re-running with the same (item, watermark) must NOT add a new row.
        assert siw_count == 1

        mw_count = session.execute(text(
            "SELECT COUNT(*) FROM memory_workstreams WHERE memory_object_id='mem-A'"
        )).scalar()
        assert mw_count == 1


def test_assignment_stage_is_persisted_on_junction(test_db_url: str) -> None:
    """Phase 4A telemetry gap fix: ``source_item_workstreams.stage`` must be
    populated with one of the cascade-stage constants on every assignment.

    Without this, the diagnostic surface cannot tell whether a workstream was
    opened via real structural signals (work_refs / file_path / symbol /
    title / anchor) or via continuity (recency / open_new) or fell back to
    ``unknown``. The 2026-05-30 eval bootstrap surfaced this gap; this test
    is the regression guard.
    """
    from capabilities.workstreams import (
        STAGE_FILE_PATH,
        STAGE_OPEN_NEW,
        STAGE_RECENCY,
        STAGE_SELF_REF_ATTACH,
        STAGE_SYMBOL,
        STAGE_TITLE,
        STAGE_UNKNOWN,
        STAGE_WORK_REFS,
        STAGE_ANCHOR,
    )

    valid_stages = {
        STAGE_WORK_REFS, STAGE_FILE_PATH, STAGE_SYMBOL, STAGE_TITLE,
        STAGE_ANCHOR, STAGE_RECENCY, STAGE_OPEN_NEW, STAGE_SELF_REF_ATTACH,
        STAGE_UNKNOWN,
    }

    storage = SQLiteStorageProvider(test_db_url)
    capability = WorkstreamCapability(SQLiteWorkstreamStore(storage._session_factory))

    base = datetime(2026, 5, 30, 16, 0, 0, tzinfo=timezone.utc)
    # Mix of items: file-path-rich (should land STAGE_FILE_PATH on attach),
    # a recency follow-up (STAGE_RECENCY or STAGE_FILE_PATH), and a
    # signal-less item (STAGE_UNKNOWN).
    items = [
        {
            "id": "stage-1",
            "thread_ref": "ts",
            "content": "first edit in core/service.py for the WorkstreamRegistry init",
            "metadata": {},
            "created_at": base,
            "memory_ids": [],
        },
        {
            "id": "stage-2",
            "thread_ref": "ts",
            "content": "follow-up in core/service.py same path same workstream",
            "metadata": {},
            "created_at": base + timedelta(minutes=2),
            "memory_ids": [],
        },
        {
            "id": "stage-3",
            "thread_ref": "tu",
            "content": "no signals nothing structural at all",
            "metadata": {},
            "created_at": base + timedelta(minutes=20),
            "memory_ids": [],
        },
    ]
    _assign_for_items(capability, items=items, container_ref="cStage", visibility="private")

    with storage._session_factory() as session:
        rows = session.execute(text(
            "SELECT source_item_id, stage FROM source_item_workstreams "
            "WHERE source_item_id IN ('stage-1','stage-2','stage-3') "
            "ORDER BY source_item_id"
        )).fetchall()
    assert len(rows) == 3, f"expected 3 rows, got {len(rows)}"
    for sid, stage in rows:
        assert stage is not None, f"row {sid} missing stage"
        assert stage in valid_stages, (
            f"row {sid} has stage={stage!r} which is not a known cascade stage"
        )
    by_id = {sid: stage for sid, stage in rows}
    # Item 3 has no signals → must land in STAGE_UNKNOWN.
    assert by_id["stage-3"] == STAGE_UNKNOWN, (
        f"signal-less item should land in STAGE_UNKNOWN, got {by_id['stage-3']!r}"
    )
    # Items 1 and 2 share a file path → at least one should be STAGE_FILE_PATH
    # (item 1 opens, item 2 attaches via file_path or recency).
    structural_stages = {STAGE_WORK_REFS, STAGE_FILE_PATH, STAGE_SYMBOL,
                         STAGE_TITLE, STAGE_ANCHOR, STAGE_OPEN_NEW}
    assert by_id["stage-1"] in structural_stages, (
        f"item 1 carries a file path; expected a structural stage, got {by_id['stage-1']!r}"
    )


def test_unknown_pseudo_id_non_joining_persistence(test_db_url: str) -> None:
    """Two unknown buckets in different (thread, watermark) tuples MUST never
    compare equal — verified at the DB layer too."""
    storage = SQLiteStorageProvider(test_db_url)
    capability = WorkstreamCapability(SQLiteWorkstreamStore(storage._session_factory))
    base = datetime(2026, 5, 30, 14, 0, 0, tzinfo=timezone.utc)

    # Item with no signals → unknown pseudo-id.
    items = [
        {
            "id": "u-1",
            "thread_ref": "t1",
            "content": "plain text no signals here at all",
            "metadata": {},
            "created_at": base,
            "memory_ids": [],
        },
        {
            "id": "u-2",
            "thread_ref": "t2",
            "content": "another plain item",
            "metadata": {},
            "created_at": base + timedelta(minutes=20),
            "memory_ids": [],
        },
        # Same thread, different watermark.
        {
            "id": "u-3",
            "thread_ref": "t1",
            "content": "still plain",
            "metadata": {},
            "created_at": base + timedelta(minutes=20),
            "memory_ids": [],
        },
    ]
    assigned = _assign_for_items(capability, items=items, container_ref="cZ", visibility="private")
    ids = {ws_id for _, ws_id in assigned}
    assert len(ids) == 3, f"expected 3 distinct unknown ids, got {ids}"
    for i in ids:
        assert i.startswith("unknown:cZ:")
