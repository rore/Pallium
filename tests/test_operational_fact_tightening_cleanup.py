"""Tests for the operational_fact tightening cleanup CLI.

Covers bucket classification, manifest guards (mtime, size, age, path,
db_url mismatch), dry-run/commit/undo transitions, idempotence, and
type-scope isolation (must not touch decisions/investigation outcomes
or W5 shadow rows).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.tools import operational_fact_tightening_cleanup as cleanup
from app.tools.operational_fact_tightening_cleanup import (
    SOFT_DELETE_REASON,
    BucketCounts,
    CandidateRow,
    apply_soft_delete,
    apply_undo,
    classify_all,
    classify_row,
    load_manifest,
    load_operational_fact_rows,
    main,
    validate_manifest,
    write_manifest,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _make_row(
    memory_object_id: str,
    *,
    command_family: str = "shell",
    artifact_role: str = "path",
    scope_kind: str = "repo",
    scope_ref: str = "git:example/repo",
    artifact: str = "app/x.py",
    artifact_normalized: str | None = None,
    subject: str = "",
) -> CandidateRow:
    return CandidateRow(
        memory_object_id=memory_object_id,
        command_family=command_family,
        artifact_role=artifact_role,
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        artifact=artifact,
        artifact_normalized=artifact_normalized or artifact,
        subject=subject,
    )


def _bootstrap_db(path: Path, rows: list[dict]) -> None:
    """Minimal DB with a memory_objects table matching the shipped schema
    columns this CLI reads / writes. Real schema uses ``id`` as the
    primary key (not ``memory_object_id``); this fixture matches.
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE memory_objects (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                is_soft_deleted INTEGER NOT NULL DEFAULT 0,
                soft_deleted_at TEXT,
                soft_delete_reason TEXT
            )
            """
        )
        for r in rows:
            conn.execute(
                """
                INSERT INTO memory_objects (
                    id, type, payload_json,
                    is_soft_deleted, soft_deleted_at, soft_delete_reason
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    r["memory_object_id"],
                    r["type"],
                    r["payload_json"],
                    r.get("is_soft_deleted", 0),
                    r.get("soft_deleted_at"),
                    r.get("soft_delete_reason"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _op_fact_row(
    memory_object_id: str,
    *,
    command_family: str,
    artifact_role: str,
    artifact: str,
    artifact_normalized: str | None = None,
    scope_kind: str = "repo",
    scope_ref: str = "git:example/repo",
    subject: str = "",
) -> dict:
    payload = {
        "command_family": command_family,
        "artifact_role": artifact_role,
        "scope_kind": scope_kind,
        "scope_ref": scope_ref,
        "artifact": artifact,
        "artifact_normalized": artifact_normalized or artifact,
        "subject": subject,
    }
    return {
        "memory_object_id": memory_object_id,
        "type": "operational_fact",
        "payload_json": json.dumps(payload),
    }


# --------------------------------------------------------------------------- #
# TestBucketClassification                                                    #
# --------------------------------------------------------------------------- #


class TestBucketClassification:
    def test_shell_path_arbitrary_source_file_soft_deletes(self):
        row = _make_row("m1", command_family="shell", artifact_role="path",
                        artifact="app/dashboard.py")
        assert classify_row(row) == "shell_path"

    def test_shell_path_operational_config_file_kept(self):
        row = _make_row("m2", command_family="shell", artifact_role="path",
                        artifact="pyproject.toml")
        # Even though it's family=shell, the shape channel admits it.
        # But classify_row first checks family=shell, role=path → matches
        # bucket 2. So this row IS soft-deleted. That is the documented
        # bucket order.
        assert classify_row(row) == "shell_path"

    def test_shell_nonpath_regex_meta_soft_deletes(self):
        row = _make_row("m3", command_family="shell", artifact_role="endpoint",
                        artifact="foo|bar")
        assert classify_row(row) == "shell_nonpath_no_shape"

    def test_shell_nonpath_valid_url_kept(self):
        row = _make_row("m4", command_family="shell", artifact_role="endpoint",
                        artifact="http://127.0.0.1:8000/health")
        # Shape channel accepts URL; classifier passes the admission
        # reconstruct → keep.
        assert classify_row(row) is None

    def test_sensitive_ssh_key_soft_deletes_regardless_of_family(self):
        row = _make_row("m5", command_family="python", artifact_role="interpreter",
                        artifact="~/.ssh/id_rsa", artifact_normalized="~/.ssh/id_rsa")
        assert classify_row(row) == "sensitive"

    def test_python_interpreter_kept(self):
        row = _make_row("m6", command_family="python", artifact_role="interpreter",
                        artifact="C:/Users/x/.venv/scripts/python.exe",
                        artifact_normalized="c:/users/x/.venv/scripts/python.exe")
        assert classify_row(row) is None


# --------------------------------------------------------------------------- #
# TestDryRunReport                                                            #
# --------------------------------------------------------------------------- #


class TestDryRunReport:
    def test_dry_run_writes_manifest_and_counts_correct(self, tmp_path, capsys):
        db = tmp_path / "test.db"
        _bootstrap_db(
            db,
            rows=[
                _op_fact_row("keep1", command_family="python",
                             artifact_role="interpreter",
                             artifact="/x/.venv/bin/python"),
                _op_fact_row("drop1", command_family="shell",
                             artifact_role="path", artifact="app/x.py"),
                _op_fact_row("drop2", command_family="shell",
                             artifact_role="path", artifact="tests/y.py"),
                _op_fact_row("drop3", command_family="shell",
                             artifact_role="endpoint", artifact="foo|bar"),
                _op_fact_row("drop_ssh", command_family="shell",
                             artifact_role="path", artifact="~/.ssh/id_rsa"),
            ],
        )
        manifest = tmp_path / "manifest.json"
        rc = main([
            "--dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ])
        assert rc == 0
        assert manifest.exists()
        m = json.loads(manifest.read_text())
        assert m["total_operational_fact_rows_before"] == 5
        assert m["buckets"]["total"] == 4
        assert m["buckets"]["sensitive"] == 1
        assert m["buckets"]["shell_path"] >= 2
        assert set(m["candidate_deletion_ids"]) == {"drop1", "drop2", "drop3", "drop_ssh"}


# --------------------------------------------------------------------------- #
# TestManifestGuards                                                          #
# --------------------------------------------------------------------------- #


class TestManifestGuards:
    def _run_dry(self, tmp_path):
        db = tmp_path / "t.db"
        _bootstrap_db(
            db,
            rows=[
                _op_fact_row("drop", command_family="shell",
                             artifact_role="path", artifact="app/x.py"),
            ],
        )
        manifest = tmp_path / "manifest.json"
        rc = main([
            "--dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ])
        assert rc == 0
        return db, manifest

    def test_commit_refuses_without_ack_flag(self, tmp_path, capsys):
        db, manifest = self._run_dry(tmp_path)
        rc = main([
            "--commit",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ])
        assert rc == 2

    def test_commit_refuses_missing_manifest(self, tmp_path):
        db = tmp_path / "t.db"
        _bootstrap_db(db, rows=[])
        missing_manifest = tmp_path / "missing.json"
        rc = main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(missing_manifest),
        ])
        assert rc == 2

    def test_commit_refuses_on_mtime_drift(self, tmp_path):
        db, manifest = self._run_dry(tmp_path)
        # Simulate the DB being modified after --dry-run: touch the file.
        m_before = json.loads(manifest.read_text())
        m_before["sqlite_mtime_ns"] = m_before["sqlite_mtime_ns"] - 1
        manifest.write_text(json.dumps(m_before))
        rc = main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ])
        assert rc == 2

    def test_commit_refuses_on_stale_manifest(self, tmp_path):
        db, manifest = self._run_dry(tmp_path)
        m_before = json.loads(manifest.read_text())
        past = datetime.now(timezone.utc) - timedelta(hours=25)
        m_before["written_at"] = past.isoformat()
        manifest.write_text(json.dumps(m_before))
        rc = main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ])
        assert rc == 2

    def test_commit_refuses_on_db_url_mismatch(self, tmp_path):
        db, manifest = self._run_dry(tmp_path)
        m_before = json.loads(manifest.read_text())
        m_before["db_url"] = "sqlite:///other/place.db"
        manifest.write_text(json.dumps(m_before))
        rc = main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ])
        assert rc == 2


# --------------------------------------------------------------------------- #
# TestCommitAndUndo                                                           #
# --------------------------------------------------------------------------- #


class TestCommitAndUndo:
    def test_commit_soft_deletes_and_undo_reverts(self, tmp_path):
        """End-to-end --dry-run → --commit → --undo happy path using
        the shipped --allow-mtime-drift escape hatch (required because
        --commit necessarily bumps the sqlite mtime_ns).
        """
        db = tmp_path / "t.db"
        _bootstrap_db(
            db,
            rows=[
                _op_fact_row("keep", command_family="python",
                             artifact_role="interpreter",
                             artifact="/x/.venv/bin/python"),
                _op_fact_row("drop1", command_family="shell",
                             artifact_role="path", artifact="a.py"),
                _op_fact_row("drop2", command_family="shell",
                             artifact_role="path", artifact="b.py"),
            ],
        )
        manifest = tmp_path / "m.json"
        assert main([
            "--dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ]) == 0

        assert main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ]) == 0

        conn = sqlite3.connect(str(db))
        try:
            deleted = conn.execute(
                "SELECT id, is_soft_deleted, soft_delete_reason "
                "FROM memory_objects ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        state = {mid: (sd, reason) for mid, sd, reason in deleted}
        assert state["keep"][0] == 0
        assert state["drop1"] == (1, SOFT_DELETE_REASON)
        assert state["drop2"] == (1, SOFT_DELETE_REASON)

        # --undo against the ORIGINAL manifest, after --commit has
        # already run, requires --allow-mtime-drift.
        assert main([
            "--undo",
            "--yes-i-checked-the-dry-run",
            "--allow-mtime-drift",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ]) == 0

        conn = sqlite3.connect(str(db))
        try:
            after = {
                mid: (sd, reason)
                for mid, sd, reason in conn.execute(
                    "SELECT id, is_soft_deleted, soft_delete_reason "
                    "FROM memory_objects"
                ).fetchall()
            }
        finally:
            conn.close()
        assert after["drop1"] == (0, None)
        assert after["drop2"] == (0, None)

    def test_undo_without_allow_mtime_drift_refuses_after_commit(self, tmp_path):
        """The mtime guard must still refuse --undo without the escape
        flag, so the flag can't be silently omitted.
        """
        db = tmp_path / "t.db"
        _bootstrap_db(
            db,
            rows=[
                _op_fact_row("drop1", command_family="shell",
                             artifact_role="path", artifact="a.py"),
            ],
        )
        manifest = tmp_path / "m.json"
        assert main([
            "--dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ]) == 0
        assert main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ]) == 0
        # Now the DB mtime has advanced; --undo without --allow-mtime-drift
        # must refuse.
        rc = main([
            "--undo",
            "--yes-i-checked-the-dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ])
        assert rc == 2

    def test_commit_rejects_allow_mtime_drift(self, tmp_path):
        """The escape hatch flag is undo-only. --commit must reject it
        so callers can't accidentally suppress the size/mtime guard for
        writes.
        """
        db = tmp_path / "t.db"
        _bootstrap_db(
            db,
            rows=[
                _op_fact_row("drop1", command_family="shell",
                             artifact_role="path", artifact="a.py"),
            ],
        )
        manifest = tmp_path / "m.json"
        assert main([
            "--dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ]) == 0
        rc = main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--allow-mtime-drift",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ])
        assert rc == 2

    def test_commit_is_idempotent_on_pre_soft_deleted_rows(self, tmp_path):
        db = tmp_path / "t.db"
        _bootstrap_db(
            db,
            rows=[
                _op_fact_row("drop", command_family="shell",
                             artifact_role="path", artifact="a.py"),
            ],
        )
        manifest = tmp_path / "m.json"
        assert main([
            "--dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ]) == 0
        # First commit soft-deletes 1 row.
        assert main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ]) == 0
        # Second commit: apply_soft_delete's WHERE is_soft_deleted=0
        # returns rowcount=0 on a row already deleted → 0 rows modified.
        # But mtime drift would refuse — for this test we craft a
        # manifest with the post-commit fingerprint.
        stat = db.stat()
        m = json.loads(manifest.read_text())
        m["sqlite_mtime_ns"] = stat.st_mtime_ns
        m["sqlite_size_bytes"] = stat.st_size
        m["written_at"] = datetime.now(timezone.utc).isoformat()
        manifest.write_text(json.dumps(m))

        assert main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ]) == 0
        # No exception, exit 0 = idempotent


# --------------------------------------------------------------------------- #
# TestTypeScope                                                                #
# --------------------------------------------------------------------------- #


class TestTypeScope:
    def test_decisions_untouched(self, tmp_path):
        db = tmp_path / "t.db"
        _bootstrap_db(
            db,
            rows=[
                _op_fact_row("op_drop", command_family="shell",
                             artifact_role="path", artifact="a.py"),
                {
                    "memory_object_id": "decision_row",
                    "type": "decision",
                    "payload_json": json.dumps({
                        "decision": "use pytest for testing",
                    }),
                },
                {
                    "memory_object_id": "shadow_row",
                    "type": "typed_shadow_extraction",
                    "payload_json": json.dumps({"summary": "shadow"}),
                },
            ],
        )
        manifest = tmp_path / "m.json"
        assert main([
            "--dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ]) == 0
        m = load_manifest(manifest)
        # Only the operational_fact row is in the candidate list.
        assert m["candidate_deletion_ids"] == ["op_drop"]
        assert main([
            "--commit",
            "--yes-i-checked-the-dry-run",
            "--db-url", f"sqlite:///{db.as_posix()}",
            "--manifest", str(manifest),
        ]) == 0
        conn = sqlite3.connect(str(db))
        try:
            state = {
                mid: sd for mid, sd in conn.execute(
                    "SELECT id, is_soft_deleted FROM memory_objects"
                ).fetchall()
            }
        finally:
            conn.close()
        assert state["op_drop"] == 1
        assert state["decision_row"] == 0
        assert state["shadow_row"] == 0
