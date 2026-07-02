"""Tests for :mod:`app.tools.secrets_purge` (PR 0 step 9).

Covers:
- Bucket classification: regenerable vs narrative vs note carveout
- Dry-run writes manifest with counts + pre-redaction snapshots
- Commit rewrites narrative types + soft-deletes regenerable types +
  rewrites source items + rewrites index entries via FTS-safe helper
- Manifest guards: missing / stale / mtime drift / db_url mismatch
- --commit rejects --allow-mtime-drift
- --undo replays pre-redaction snapshots correctly
- --undo after --commit requires --allow-mtime-drift
- Note memory type is skipped (never rewritten)
- Source item with artifact_kind='note' is skipped
- FTS lexical_fts is updated (not just index_entries.text_view)
- Type-scope isolation: unrelated types not touched
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from core.models import new_id, utc_now
from storage.sqlite import SQLiteStorageProvider
from storage.sqlite_schema import (
    IndexEntryRecord,
    MemoryObjectRecord,
    SourceItemRecord,
    insert_lexical_fts_row,
)

from app.tools import secrets_purge as sp


CONTAINER = "git:example/secrets-purge-test"


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def test_db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'purge_test.db'}"


@pytest.fixture
def sqlite_path(test_db_url):
    return sp._resolve_sqlite_path(test_db_url)


@pytest.fixture
def storage(test_db_url):
    """Provisions SQLite schema by instantiating the storage provider."""
    return SQLiteStorageProvider(test_db_url)


@pytest.fixture
def manifest_path(tmp_path):
    return tmp_path / "manifest.json"


def _seed_memory(
    storage,
    *,
    memory_id: str | None = None,
    type: str,
    subject: str = "",
    payload: dict | None = None,
) -> str:
    """Seed a memory_object row and return its id."""
    mid = memory_id or new_id()
    now = utc_now()
    with storage._session_factory() as session:
        session.add(
            MemoryObjectRecord(
                id=mid,
                type=type,
                schema_id="test",
                schema_version="1",
                payload_json=json.dumps(payload or {}),
                envelope_json=None,
                lifecycle="active",
                visibility="private",
                container_ref=CONTAINER,
                actor_ref=None,
                freshness_at=now,
                subject=subject,
                created_at=now,
            )
        )
        session.commit()
    return mid


def _seed_source_item(
    storage, *, artifact_kind: str, content: str, metadata: dict | None = None,
) -> str:
    sid = new_id()
    now = utc_now()
    with storage._session_factory() as session:
        session.add(
            SourceItemRecord(
                id=sid,
                source_type="claude-code",
                source_id=f"src-{sid[:8]}",
                content_type="text/plain",
                content=content,
                metadata_json=json.dumps(metadata) if metadata else None,
                artifact_kind=artifact_kind,
                role="assistant" if artifact_kind == "assistant_output" else "user",
                visibility="private",
                container_ref=CONTAINER,
                actor_ref=None,
                processing_status="completed",
                processing_attempts=1,
                created_at=now,
            )
        )
        session.commit()
    return sid


def _seed_lexical_index(storage, *, target_id: str, text_view: str) -> str:
    eid = new_id()
    with storage._session_factory() as session:
        session.add(
            IndexEntryRecord(
                id=eid,
                target_kind="memory_object",
                target_id=target_id,
                index_type="lexical",
                text_view=text_view,
                text_view_name="test",
                provider_name="test",
                provider_version="1",
            )
        )
        session.flush()
        insert_lexical_fts_row(
            session,
            index_entry_id=eid,
            target_kind="memory_object",
            target_id=target_id,
            text_view=text_view,
            text_view_name="test",
            container_ref=CONTAINER,
        )
        session.commit()
    return eid


# --------------------------------------------------------------------------- #
# TestBucketClassification                                                     #
# --------------------------------------------------------------------------- #


class TestBucketClassification:
    def test_regenerable_type_marked_for_soft_delete(self, storage, sqlite_path):
        _seed_memory(
            storage,
            type="thread_summary",
            subject="leaked ghp_" + ("A" * 36),
            payload={"summary": "contains ghp_" + ("A" * 36)},
        )
        plan = sp.build_plan(sqlite_path)
        assert len(plan.regenerable_ids) == 1
        assert not plan.memory_rows

    def test_narrative_type_marked_for_rewrite(self, storage, sqlite_path):
        _seed_memory(
            storage,
            type="investigation_outcome",
            subject="leaked ghp_" + ("A" * 36),
            payload={"outcome": "found ghp_" + ("A" * 36)},
        )
        plan = sp.build_plan(sqlite_path)
        assert not plan.regenerable_ids
        assert len(plan.memory_rows) == 1
        row = plan.memory_rows[0]
        assert "ghp_" not in row.redacted_subject
        assert "ghp_" not in row.redacted_payload_json

    def test_note_type_never_rewritten(self, storage, sqlite_path):
        _seed_memory(
            storage,
            type="note",
            subject="note with password=hunter2 placeholder",
            payload={"content": "step: use password=hunter2"},
        )
        plan = sp.build_plan(sqlite_path)
        # No rewrite, no soft-delete — just tracked as skipped.
        assert not plan.memory_rows
        assert not plan.regenerable_ids
        assert len(plan.note_skipped_ids) == 1

    def test_clean_row_ignored(self, storage, sqlite_path):
        _seed_memory(
            storage, type="investigation_outcome",
            subject="clean subject", payload={"outcome": "no secrets here"},
        )
        plan = sp.build_plan(sqlite_path)
        assert not plan.memory_rows
        assert not plan.regenerable_ids

    def test_soft_deleted_row_ignored(self, storage, sqlite_path):
        # Directly mark a memory as soft-deleted; purge should skip.
        mid = _seed_memory(
            storage, type="thread_summary",
            subject="ghp_" + ("A" * 36), payload={},
        )
        conn = sqlite3.connect(str(sqlite_path))
        conn.execute(
            "UPDATE memory_objects SET is_soft_deleted=1, soft_deleted_at=?, soft_delete_reason=? WHERE id=?",
            (utc_now().isoformat(), "other", mid),
        )
        conn.commit()
        conn.close()
        plan = sp.build_plan(sqlite_path)
        assert not plan.regenerable_ids
        assert not plan.memory_rows


class TestSourceItemAndIndex:
    def test_source_item_content_rewritten(self, storage, sqlite_path):
        _seed_source_item(
            storage, artifact_kind="assistant_output",
            content="leaked ghp_" + ("A" * 36),
        )
        plan = sp.build_plan(sqlite_path)
        assert len(plan.source_items) == 1
        assert "ghp_" not in plan.source_items[0].redacted_content

    def test_source_item_note_skipped(self, storage, sqlite_path):
        _seed_source_item(
            storage, artifact_kind="note",
            content="note contains ghp_" + ("A" * 36),
        )
        plan = sp.build_plan(sqlite_path)
        assert not plan.source_items

    def test_source_item_metadata_rewritten(self, storage, sqlite_path):
        _seed_source_item(
            storage, artifact_kind="assistant_output",
            content="clean",
            metadata={"headers": {"Authorization": "Bearer abc123abc123abc123abc"}},
        )
        plan = sp.build_plan(sqlite_path)
        assert len(plan.source_items) == 1
        assert "abc123abc123abc123abc" not in (plan.source_items[0].redacted_metadata_json or "")

    def test_index_entry_text_view_rewritten(self, storage, sqlite_path):
        mid = _seed_memory(storage, type="task_trace", subject="x", payload={"x": 1})
        _seed_lexical_index(
            storage, target_id=mid, text_view="banana ghp_" + ("A" * 36),
        )
        plan = sp.build_plan(sqlite_path)
        assert len(plan.index_entries) == 1


# --------------------------------------------------------------------------- #
# TestDryRun + Commit + Undo                                                   #
# --------------------------------------------------------------------------- #


class TestDryRun:
    def test_dry_run_writes_manifest_with_snapshots(
        self, storage, test_db_url, manifest_path,
    ):
        _seed_memory(
            storage, type="investigation_outcome",
            subject="ghp_" + ("A" * 36), payload={"outcome": "leaked"},
        )
        _seed_memory(
            storage, type="thread_summary",
            subject="ghp_" + ("A" * 36), payload={"summary": "leaked"},
        )
        _seed_source_item(
            storage, artifact_kind="assistant_output",
            content="leaked ghp_" + ("A" * 36),
        )
        rc = sp.main([
            "--dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        assert rc == 0
        assert manifest_path.exists()
        m = json.loads(manifest_path.read_text())
        assert m["reason_tag"] == sp.SOFT_DELETE_REASON
        assert m["counts"]["memory_rewrites"] == 1
        assert m["counts"]["memory_soft_deletes"] == 1
        assert m["counts"]["source_item_rewrites"] == 1
        snaps = m["pre_redaction_snapshots"]
        assert len(snaps["memory_objects"]) == 1
        # Snapshot contains the pre-redaction payload.
        assert "ghp_" in snaps["memory_objects"][0]["subject"]


class TestCommit:
    def test_commit_rewrites_narrative_and_soft_deletes_regenerable(
        self, storage, test_db_url, sqlite_path, manifest_path,
    ):
        gh = "ghp_" + ("A" * 36)
        narr_id = _seed_memory(
            storage, type="investigation_outcome",
            subject=f"leaked {gh}", payload={"outcome": f"see {gh}"},
        )
        regen_id = _seed_memory(
            storage, type="thread_summary",
            subject=f"leaked {gh}", payload={"summary": f"see {gh}"},
        )
        sp.main([
            "--dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        rc = sp.main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        assert rc == 0

        conn = sqlite3.connect(str(sqlite_path))
        # Narrative row rewritten.
        row = conn.execute(
            "SELECT subject, payload_json, is_soft_deleted "
            "FROM memory_objects WHERE id = ?",
            (narr_id,),
        ).fetchone()
        assert gh not in row[0]
        assert gh not in row[1]
        assert row[2] == 0
        # Regenerable row soft-deleted.
        row = conn.execute(
            "SELECT is_soft_deleted, soft_delete_reason FROM memory_objects WHERE id = ?",
            (regen_id,),
        ).fetchone()
        assert row[0] == 1
        assert row[1] == sp.SOFT_DELETE_REASON

    def test_commit_updates_lexical_fts(
        self, storage, test_db_url, sqlite_path, manifest_path,
    ):
        gh = "ghp_" + ("Z" * 36)
        mid = _seed_memory(
            storage, type="task_trace",
            subject="x", payload={"trace": "clean"},
        )
        eid = _seed_lexical_index(
            storage, target_id=mid, text_view=f"seed {gh} more",
        )
        sp.main([
            "--dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        sp.main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        conn = sqlite3.connect(str(sqlite_path))
        # index_entries.text_view updated.
        (tv,) = conn.execute(
            "SELECT text_view FROM index_entries WHERE id = ?", (eid,),
        ).fetchone()
        assert gh not in tv
        # lexical_fts.text_view ALSO updated (load-bearing — this is
        # what retrieval reads).
        (fts_tv,) = conn.execute(
            "SELECT text_view FROM lexical_fts WHERE index_entry_id = ?",
            (eid,),
        ).fetchone()
        assert gh not in fts_tv

    def test_commit_refuses_without_ack_flag(
        self, storage, test_db_url, manifest_path,
    ):
        _seed_memory(storage, type="thread_summary", subject="ghp_" + ("A" * 36))
        sp.main([
            "--dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        rc = sp.main([
            "--commit",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        assert rc == 2

    def test_commit_refuses_missing_manifest(
        self, storage, test_db_url, tmp_path,
    ):
        rc = sp.main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", test_db_url,
            "--manifest", str(tmp_path / "missing.json"),
        ])
        assert rc == 2

    def test_commit_refuses_mtime_drift(
        self, storage, test_db_url, manifest_path, sqlite_path,
    ):
        _seed_memory(storage, type="thread_summary", subject="ghp_" + ("A" * 36))
        sp.main([
            "--dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        # Simulate DB modification.
        m = json.loads(manifest_path.read_text())
        m["sqlite_mtime_ns"] = m["sqlite_mtime_ns"] - 1
        manifest_path.write_text(json.dumps(m))
        rc = sp.main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        assert rc == 2

    def test_commit_rejects_allow_mtime_drift_flag(
        self, storage, test_db_url, manifest_path,
    ):
        _seed_memory(storage, type="thread_summary", subject="ghp_" + ("A" * 36))
        sp.main([
            "--dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        rc = sp.main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--allow-mtime-drift",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        assert rc == 2

    def test_commit_refuses_stale_manifest(
        self, storage, test_db_url, manifest_path,
    ):
        _seed_memory(storage, type="thread_summary", subject="ghp_" + ("A" * 36))
        sp.main([
            "--dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        m = json.loads(manifest_path.read_text())
        past = datetime.now(timezone.utc) - timedelta(hours=25)
        m["written_at"] = past.isoformat()
        manifest_path.write_text(json.dumps(m))
        rc = sp.main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        assert rc == 2

    def test_commit_refuses_db_url_mismatch(
        self, storage, test_db_url, manifest_path,
    ):
        _seed_memory(storage, type="thread_summary", subject="ghp_" + ("A" * 36))
        sp.main([
            "--dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        m = json.loads(manifest_path.read_text())
        m["db_url"] = "sqlite:///other/place.db"
        manifest_path.write_text(json.dumps(m))
        rc = sp.main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        assert rc == 2


class TestUndo:
    def test_undo_replays_snapshots_with_allow_mtime_drift(
        self, storage, test_db_url, sqlite_path, manifest_path,
    ):
        gh = "ghp_" + ("A" * 36)
        narr_id = _seed_memory(
            storage, type="investigation_outcome",
            subject=f"leaked {gh}", payload={"outcome": f"see {gh}"},
        )
        regen_id = _seed_memory(
            storage, type="thread_summary",
            subject=f"leaked {gh}", payload={"summary": f"see {gh}"},
        )
        sp.main([
            "--dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        sp.main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        # Now undo — commit changed mtime, need --allow-mtime-drift.
        rc = sp.main([
            "--undo",
            "--yes-i-checked-the-dry-run",
            "--allow-mtime-drift",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        assert rc == 0

        conn = sqlite3.connect(str(sqlite_path))
        # Narrative row restored.
        row = conn.execute(
            "SELECT subject, payload_json, is_soft_deleted "
            "FROM memory_objects WHERE id = ?",
            (narr_id,),
        ).fetchone()
        assert gh in row[0]
        assert gh in row[1]
        # Regenerable row un-soft-deleted.
        row = conn.execute(
            "SELECT is_soft_deleted, soft_delete_reason FROM memory_objects WHERE id = ?",
            (regen_id,),
        ).fetchone()
        assert row[0] == 0
        assert row[1] is None

    def test_undo_without_allow_flag_refuses_post_commit(
        self, storage, test_db_url, manifest_path, sqlite_path,
    ):
        import os
        import time
        _seed_memory(storage, type="thread_summary", subject="ghp_" + ("A" * 36))
        sp.main([
            "--dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        sp.main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        # Force a distinguishable mtime — on some filesystems (Windows
        # sub-second granularity, NTFS ticks) two writes in the same
        # test can share an mtime_ns value, defeating the drift check.
        # Force a delta so the drift guard reliably triggers.
        time.sleep(0.05)
        current_stat = sqlite_path.stat()
        os.utime(sqlite_path, ns=(current_stat.st_atime_ns, current_stat.st_mtime_ns + 1_000_000))
        rc = sp.main([
            "--undo",
            "--yes-i-checked-the-dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        assert rc == 2

    def test_undo_only_reverts_matching_reason_tag(
        self, storage, test_db_url, manifest_path, sqlite_path,
    ):
        """Regression pin: undo must NOT resurrect rows soft-deleted
        for other reasons (e.g. by a different cleanup CLI)."""
        gh = "ghp_" + ("A" * 36)
        our_regen = _seed_memory(
            storage, type="thread_summary",
            subject=f"leaked {gh}", payload={},
        )
        other_soft = _seed_memory(
            storage, type="thread_summary",
            subject="unrelated", payload={},
        )
        # Soft-delete the second row for a DIFFERENT reason before we run.
        conn = sqlite3.connect(str(sqlite_path))
        conn.execute(
            "UPDATE memory_objects SET is_soft_deleted=1, soft_deleted_at=?, soft_delete_reason=? WHERE id=?",
            (utc_now().isoformat(), "different_reason", other_soft),
        )
        conn.commit()
        conn.close()

        sp.main([
            "--dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        sp.main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        sp.main([
            "--undo",
            "--yes-i-checked-the-dry-run",
            "--allow-mtime-drift",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        conn = sqlite3.connect(str(sqlite_path))
        (unrelated,) = conn.execute(
            "SELECT is_soft_deleted FROM memory_objects WHERE id = ?", (other_soft,),
        ).fetchone()
        # The other-reason soft-delete stays intact.
        assert unrelated == 1


class TestTypeScopeIsolation:
    def test_unrelated_types_never_touched(
        self, storage, test_db_url, sqlite_path, manifest_path,
    ):
        gh = "ghp_" + ("A" * 36)
        # A row with no secrets, unrelated to the purge.
        clean_id = _seed_memory(
            storage, type="decision",
            subject="clean decision",
            payload={"decision": "use pytest"},
        )
        # A row with a secret.
        dirty_id = _seed_memory(
            storage, type="task_trace",
            subject=f"see {gh}", payload={},
        )
        sp.main([
            "--dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        sp.main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        conn = sqlite3.connect(str(sqlite_path))
        (clean_subj,) = conn.execute(
            "SELECT subject FROM memory_objects WHERE id = ?", (clean_id,),
        ).fetchone()
        assert clean_subj == "clean decision"

    def test_note_memory_never_rewritten_even_with_secret_shape(
        self, storage, test_db_url, sqlite_path, manifest_path,
    ):
        gh = "ghp_" + ("A" * 36)
        note_id = _seed_memory(
            storage, type="note",
            subject=f"remembered: {gh}",
            payload={"content": f"the token was {gh}"},
        )
        sp.main([
            "--dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        sp.main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", test_db_url,
            "--manifest", str(manifest_path),
        ])
        conn = sqlite3.connect(str(sqlite_path))
        row = conn.execute(
            "SELECT subject, payload_json, is_soft_deleted FROM memory_objects WHERE id = ?",
            (note_id,),
        ).fetchone()
        # Verbatim survives.
        assert gh in row[0]
        assert gh in row[1]
        assert row[2] == 0
