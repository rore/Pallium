"""Tier 5: Data fidelity round-trip tests for snapshot persistence.

Each test follows the canonical pattern:
  1. Create a SQLiteStorageProvider with a real temp DB
  2. Write specific data through the storage API
  3. Call create_snapshot
  4. Delete the live DB (wipe)
  5. Call restore_snapshot
  6. Create a NEW SQLiteStorageProvider on the restored DB
  7. Query back all data and verify field-by-field match
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.snapshot import create_snapshot, restore_snapshot
from core.models import IndexEntry, MemoryObject, Relation, SourceItem, new_id, utc_now
from storage.sqlite import SQLiteStorageProvider


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _roundtrip(live_db: Path, snapshot_dir: Path, storage: SQLiteStorageProvider | None = None) -> None:
    """Snapshot, wipe, restore.

    On Windows the SQLAlchemy engine holds open file handles.  Dispose it
    before attempting to unlink the DB file, otherwise we get a PermissionError.
    """
    result = create_snapshot(str(live_db), snapshot_dir)
    assert result is not None, "create_snapshot returned None"
    # Release all pooled connections so Windows will let us delete the file
    if storage is not None:
        storage._engine.dispose()
    live_db.unlink()
    # Clean up WAL/SHM and schema lock if they exist
    live_db.with_suffix(".db-wal").unlink(missing_ok=True)
    live_db.with_suffix(".db-shm").unlink(missing_ok=True)
    live_db.with_name(f"{live_db.name}.schema.lock").unlink(missing_ok=True)
    restored = restore_snapshot(snapshot_dir, str(live_db))
    assert restored is True, "restore_snapshot returned False — no snapshot was restored"


def _dt(offset_seconds: int = 0) -> datetime:
    """Return a UTC datetime with microseconds truncated to milliseconds for stable comparison."""
    base = utc_now().replace(microsecond=0)
    return base + timedelta(seconds=offset_seconds)


# ---------------------------------------------------------------------------
# Test 1: Source items — all fields populated
# ---------------------------------------------------------------------------

def test_roundtrip_source_items(tmp_path: Path) -> None:
    db_path = tmp_path / "pallium.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    storage = SQLiteStorageProvider(f"sqlite:///{db_path}")

    items: list[SourceItem] = []
    for i in range(20):
        item = SourceItem(
            id=new_id(),
            source_type="test",
            source_id=f"item-{i}",
            content_type="text",
            content=f"content for item {i}",
            metadata={"key": f"value-{i}", "index": i},
            occurred_at=_dt(i),
            actor_ref=f"actor-{i}",
            agent_ref=f"agent-{i}",
            role="user" if i % 2 == 0 else "assistant",
            container_ref="test-container",
            thread_ref=f"thread-{i % 5}",
            source_ref=f"source-ref-{i}",
            artifact_kind="message" if i % 3 == 0 else None,
            visibility="private",
            use_case="agent_conversation_memory",
            processing_status="pending",
            processing_attempts=0,
            created_at=_dt(i),
        )
        storage.create_source_item(item)
        items.append(item)

    _roundtrip(db_path, snapshot_dir, storage)

    storage2 = SQLiteStorageProvider(f"sqlite:///{db_path}")
    for original in items:
        restored = storage2.get_source_item(original.id)
        assert restored.id == original.id
        assert restored.source_type == original.source_type
        assert restored.source_id == original.source_id
        assert restored.content_type == original.content_type
        assert restored.content == original.content
        assert restored.metadata == original.metadata
        assert restored.actor_ref == original.actor_ref
        assert restored.agent_ref == original.agent_ref
        assert restored.role == original.role
        assert restored.container_ref == original.container_ref
        assert restored.thread_ref == original.thread_ref
        assert restored.source_ref == original.source_ref
        assert restored.artifact_kind == original.artifact_kind
        assert restored.visibility == original.visibility
        assert restored.use_case == original.use_case
        assert restored.processing_status == original.processing_status
        assert restored.processing_attempts == original.processing_attempts


# ---------------------------------------------------------------------------
# Test 2: Memory objects and relations
# ---------------------------------------------------------------------------

def test_roundtrip_memory_objects_and_relations(tmp_path: Path) -> None:
    db_path = tmp_path / "pallium.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    storage = SQLiteStorageProvider(f"sqlite:///{db_path}")

    # Write source items
    source_items: list[SourceItem] = []
    for i in range(5):
        item = SourceItem(
            id=new_id(),
            source_type="test",
            source_id=f"si-{i}",
            content_type="text",
            content=f"source content {i}",
            container_ref="container-a",
            thread_ref=f"thread-{i}",
            visibility="private",
            use_case="agent_conversation_memory",
            processing_status="pending",
            created_at=_dt(i),
        )
        storage.create_source_item(item)
        source_items.append(item)

    # Write memory objects
    memory_objects: list[MemoryObject] = []
    for i in range(5):
        mo = MemoryObject(
            id=new_id(),
            type="decision",
            schema_id="test",
            schema_version="v1",
            payload={"summary": f"test decision {i}", "canonical_key": f"key-{i}"},
            lifecycle="active",
            visibility="private",
            container_ref="container-a",
            created_at=_dt(i),
        )
        storage.create_memory_object(mo)
        memory_objects.append(mo)

    # Write relations
    relations: list[Relation] = []
    for i in range(5):
        rel = Relation(
            id=new_id(),
            from_kind="memory_object",
            from_id=memory_objects[i].id,
            relation_type="supported_by",
            to_kind="source_item",
            to_id=source_items[i].id,
        )
        storage.create_relation(rel)
        relations.append(rel)

    _roundtrip(db_path, snapshot_dir, storage)

    storage2 = SQLiteStorageProvider(f"sqlite:///{db_path}")

    # Verify source items
    for original in source_items:
        restored = storage2.get_source_item(original.id)
        assert restored.id == original.id
        assert restored.content == original.content

    # Verify memory objects
    for original_mo in memory_objects:
        restored_mo = storage2.get_memory_object(original_mo.id)
        assert restored_mo.id == original_mo.id
        assert restored_mo.type == original_mo.type
        assert restored_mo.schema_id == original_mo.schema_id
        assert restored_mo.schema_version == original_mo.schema_version
        assert restored_mo.payload == original_mo.payload
        assert restored_mo.lifecycle == original_mo.lifecycle
        assert restored_mo.visibility == original_mo.visibility
        assert restored_mo.container_ref == original_mo.container_ref

    # Verify relations
    for original_rel in relations:
        rels = storage2.list_relations_for_source_item(original_rel.to_id)
        rel_ids = {r.id for r in rels}
        assert original_rel.id in rel_ids
        matched = next(r for r in rels if r.id == original_rel.id)
        assert matched.from_kind == original_rel.from_kind
        assert matched.from_id == original_rel.from_id
        assert matched.relation_type == original_rel.relation_type
        assert matched.to_kind == original_rel.to_kind
        assert matched.to_id == original_rel.to_id


# ---------------------------------------------------------------------------
# Test 3: FTS5 lexical index entries
# ---------------------------------------------------------------------------

def test_roundtrip_fts5_search(tmp_path: Path) -> None:
    db_path = tmp_path / "pallium.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    storage = SQLiteStorageProvider(f"sqlite:///{db_path}")

    phrases = [
        ("the quick brown fox jumped over the lazy dog", "fox"),
        ("sphinx of black quartz judge my vow", "sphinx"),
        ("pack my box with five dozen liquor jugs", "liquor"),
    ]

    item_ids = []
    entry_ids = []
    for phrase, _ in phrases:
        item = SourceItem(
            id=new_id(),
            source_type="test",
            source_id=new_id(),
            content_type="text",
            content=phrase,
            container_ref="fts-container",
            visibility="private",
            use_case="agent_conversation_memory",
            processing_status="pending",
            created_at=utc_now(),
        )
        storage.create_source_item(item)
        item_ids.append(item.id)

        entry = IndexEntry(
            id=new_id(),
            target_kind="source_item",
            target_id=item.id,
            index_type="lexical",
            text_view=phrase,
            text_view_name="content.embedding",
        )
        storage.create_index_entry(entry)
        entry_ids.append(entry.id)

    _roundtrip(db_path, snapshot_dir, storage)

    storage2 = SQLiteStorageProvider(f"sqlite:///{db_path}")

    # Verify index entries are restored
    for entry_id in entry_ids:
        restored_entry = storage2.get_index_entry(entry_id)
        assert restored_entry.id == entry_id
        assert restored_entry.index_type == "lexical"

    # Verify FTS5 MATCH queries work via raw SQL
    conn = sqlite3.connect(str(db_path))
    try:
        for _, search_word in phrases:
            results = conn.execute(
                "SELECT index_entry_id FROM lexical_fts WHERE lexical_fts MATCH ?",
                (search_word,),
            ).fetchall()
            assert len(results) >= 1, f"FTS5 MATCH '{search_word}' returned no results after restore"
            # Each search term is unique to one phrase — should match exactly one entry
            assert len(results) == 1, (
                f"FTS5 MATCH '{search_word}' returned {len(results)} results, expected 1"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Test 4: Processing queue state
# ---------------------------------------------------------------------------

def test_roundtrip_processing_queue_state(tmp_path: Path) -> None:
    db_path = tmp_path / "pallium.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    storage = SQLiteStorageProvider(f"sqlite:///{db_path}")

    now = _dt()

    # pending item
    item_pending = SourceItem(
        id=new_id(),
        source_type="test",
        source_id="queue-pending",
        content_type="text",
        content="pending item",
        use_case="agent_conversation_memory",
        processing_status="pending",
        processing_attempts=0,
        created_at=now,
    )
    storage.create_source_item(item_pending)

    # processing item with active lease
    item_processing = SourceItem(
        id=new_id(),
        source_type="test",
        source_id="queue-processing",
        content_type="text",
        content="processing item",
        use_case="agent_conversation_memory",
        processing_status="processing",
        processing_attempts=1,
        processing_claimed_by="worker-1",
        processing_claimed_at=now,
        processing_lease_expires_at=now + timedelta(seconds=120),
        created_at=now,
    )
    storage.create_source_item(item_processing)

    # completed item
    item_completed = SourceItem(
        id=new_id(),
        source_type="test",
        source_id="queue-completed",
        content_type="text",
        content="completed item",
        use_case="agent_conversation_memory",
        processing_status="completed",
        processing_attempts=1,
        processing_completed_at=now,
        created_at=now,
    )
    storage.create_source_item(item_completed)

    # failed item with retry
    item_failed = SourceItem(
        id=new_id(),
        source_type="test",
        source_id="queue-failed",
        content_type="text",
        content="failed item",
        use_case="agent_conversation_memory",
        processing_status="failed",
        processing_attempts=2,
        processing_error="simulated error",
        processing_next_attempt_at=now + timedelta(minutes=5),
        created_at=now,
    )
    storage.create_source_item(item_failed)

    _roundtrip(db_path, snapshot_dir, storage)

    storage2 = SQLiteStorageProvider(f"sqlite:///{db_path}")

    r_pending = storage2.get_source_item(item_pending.id)
    assert r_pending.processing_status == "pending"
    assert r_pending.processing_attempts == 0
    assert r_pending.processing_claimed_by is None

    r_processing = storage2.get_source_item(item_processing.id)
    assert r_processing.processing_status == "processing"
    assert r_processing.processing_attempts == 1
    assert r_processing.processing_claimed_by == "worker-1"
    assert r_processing.processing_lease_expires_at is not None

    r_completed = storage2.get_source_item(item_completed.id)
    assert r_completed.processing_status == "completed"
    assert r_completed.processing_completed_at is not None

    r_failed = storage2.get_source_item(item_failed.id)
    assert r_failed.processing_status == "failed"
    assert r_failed.processing_attempts == 2
    assert r_failed.processing_error == "simulated error"
    assert r_failed.processing_next_attempt_at is not None


# ---------------------------------------------------------------------------
# Test 5: Thread processing leases
# ---------------------------------------------------------------------------

def test_roundtrip_thread_processing_leases(tmp_path: Path) -> None:
    """Verify thread_processing_leases rows survive the snapshot round-trip."""
    db_path = tmp_path / "pallium.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    storage = SQLiteStorageProvider(f"sqlite:///{db_path}")

    now = _dt()

    # Insert a source item to satisfy FK-like referential expectations
    item = SourceItem(
        id=new_id(),
        source_type="test",
        source_id="lease-item-1",
        content_type="text",
        content="item for lease test",
        container_ref="lease-container",
        thread_ref="lease-thread",
        visibility="private",
        use_case="agent_conversation_memory",
        processing_status="pending",
        created_at=now,
    )
    storage.create_source_item(item)

    # Insert thread processing lease records directly via SQL (no public API exists)
    scope_key = "agent_conversation_memory:lease-container:lease-thread:private"
    raw_conn = sqlite3.connect(str(db_path))
    try:
        raw_conn.execute(
            """
            INSERT INTO thread_processing_leases
              (scope_key, use_case, container_ref, thread_ref, visibility,
               requested_at, processing_claimed_by, processing_claimed_at,
               processing_lease_expires_at, processing_completed_at,
               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scope_key,
                "agent_conversation_memory",
                "lease-container",
                "lease-thread",
                "private",
                now.isoformat(),
                "worker-7",
                now.isoformat(),
                (now + timedelta(seconds=60)).isoformat(),
                None,
                now.isoformat(),
                now.isoformat(),
            ),
        )
        raw_conn.commit()
    finally:
        raw_conn.close()

    _roundtrip(db_path, snapshot_dir, storage)

    # Verify directly via sqlite3
    conn2 = sqlite3.connect(str(db_path))
    try:
        rows = conn2.execute(
            "SELECT scope_key, use_case, container_ref, thread_ref, visibility, processing_claimed_by "
            "FROM thread_processing_leases WHERE scope_key = ?",
            (scope_key,),
        ).fetchall()
        assert len(rows) == 1, f"Expected 1 lease row, got {len(rows)}"
        row = rows[0]
        assert row[0] == scope_key
        assert row[1] == "agent_conversation_memory"
        assert row[2] == "lease-container"
        assert row[3] == "lease-thread"
        assert row[4] == "private"
        assert row[5] == "worker-7"
    finally:
        conn2.close()


# ---------------------------------------------------------------------------
# Test 6: Large content
# ---------------------------------------------------------------------------

def test_roundtrip_large_content(tmp_path: Path) -> None:
    db_path = tmp_path / "pallium.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    storage = SQLiteStorageProvider(f"sqlite:///{db_path}")

    large_items: list[SourceItem] = []
    for i in range(5):
        # 100 KB of ASCII content
        large_content = f"item-{i}-" + ("x" * (100 * 1024 - 10))
        item = SourceItem(
            id=new_id(),
            source_type="test",
            source_id=f"large-{i}",
            content_type="text",
            content=large_content,
            container_ref="large-container",
            visibility="private",
            use_case="agent_conversation_memory",
            processing_status="pending",
            created_at=utc_now(),
        )
        storage.create_source_item(item)
        large_items.append(item)

    _roundtrip(db_path, snapshot_dir, storage)

    storage2 = SQLiteStorageProvider(f"sqlite:///{db_path}")
    for original in large_items:
        restored = storage2.get_source_item(original.id)
        assert len(restored.content) == len(original.content), (
            f"Content length mismatch for {original.id}: "
            f"expected {len(original.content)}, got {len(restored.content)}"
        )
        assert restored.content == original.content, (
            f"Content mismatch for {original.id}"
        )


# ---------------------------------------------------------------------------
# Test 7: Unicode content
# ---------------------------------------------------------------------------

def test_roundtrip_unicode_content(tmp_path: Path) -> None:
    db_path = tmp_path / "pallium.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    storage = SQLiteStorageProvider(f"sqlite:///{db_path}")

    unicode_cases = [
        ("hebrew", "שלום עולם — בדיקת תוכן עברי"),
        ("arabic", "مرحبا بالعالم — اختبار المحتوى العربي"),
        ("cjk", "你好世界 — 中文内容测试"),
        ("emoji", "rocket 🚀 lightbulb 💡 target 🎯 tada 🎉"),
        ("mixed", "Hello שלום مرحبا 你好 🌍 world"),
    ]

    items: dict[str, SourceItem] = {}
    for lang, content in unicode_cases:
        item = SourceItem(
            id=new_id(),
            source_type="test",
            source_id=f"unicode-{lang}",
            content_type="text",
            content=content,
            metadata={"lang": lang, "content_preview": content[:20]},
            container_ref="unicode-container",
            visibility="private",
            use_case="agent_conversation_memory",
            processing_status="pending",
            created_at=utc_now(),
        )
        storage.create_source_item(item)
        items[lang] = item

    _roundtrip(db_path, snapshot_dir, storage)

    storage2 = SQLiteStorageProvider(f"sqlite:///{db_path}")
    for lang, original in items.items():
        restored = storage2.get_source_item(original.id)
        assert restored.content == original.content, (
            f"Unicode content mismatch for '{lang}': "
            f"expected {original.content!r}, got {restored.content!r}"
        )
        assert restored.metadata == original.metadata, (
            f"Metadata mismatch for '{lang}'"
        )


# ---------------------------------------------------------------------------
# Test 8: Package processing status
# ---------------------------------------------------------------------------

def test_roundtrip_package_processing_status(tmp_path: Path) -> None:
    db_path = tmp_path / "pallium.db"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    storage = SQLiteStorageProvider(f"sqlite:///{db_path}")

    # Create source items
    source_item_ids = []
    for i in range(3):
        item = SourceItem(
            id=new_id(),
            source_type="test",
            source_id=f"pkg-item-{i}",
            content_type="text",
            content=f"item for package processing {i}",
            use_case="agent_conversation_memory",
            processing_status="pending",
            created_at=utc_now(),
        )
        storage.create_source_item(item)
        source_item_ids.append(item.id)

    packages = ["pkg_alpha", "pkg_beta", "pkg_gamma"]

    # Create package processing records for each source item
    for sid in source_item_ids:
        storage.create_package_processing_records(sid, packages)

    _roundtrip(db_path, snapshot_dir, storage)

    # Verify via direct SQL after restore (no public read API for package status)
    conn = sqlite3.connect(str(db_path))
    try:
        for sid in source_item_ids:
            rows = conn.execute(
                "SELECT source_item_id, package_name, status, attempts "
                "FROM package_processing_status WHERE source_item_id = ? "
                "ORDER BY package_name",
                (sid,),
            ).fetchall()
            assert len(rows) == len(packages), (
                f"Expected {len(packages)} package records for {sid}, got {len(rows)}"
            )
            for row, expected_pkg in zip(rows, sorted(packages)):
                assert row[0] == sid
                assert row[1] == expected_pkg
                assert row[2] == "pending"
                assert row[3] == 0
    finally:
        conn.close()
