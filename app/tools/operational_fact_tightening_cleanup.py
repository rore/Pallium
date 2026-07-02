"""operational_fact tightening cleanup — soft-delete noisy live rows.

Live-data motivation (2026-07-02): 86% of the shipped operational_fact
predicate's 187 live rows are the fallback ``family='shell' +
role='path'`` slot (arbitrary source files, argv fragments, regex
meta), plus a handful of secret paths that bypassed W3 redaction and
one ``127.0.0`` IPv4-prefix row admitted at role=version.

PR A shipped the sensitivity predicate at emission time. PR B shipped
the admission gate that prevents new noise from being written. This
tool handles the pre-existing rows the two upstream defenses cannot
reach.

Usage::

    python -m app.tools.operational_fact_tightening_cleanup --dry-run
    python -m app.tools.operational_fact_tightening_cleanup --commit --yes-i-checked-the-dry-run
    python -m app.tools.operational_fact_tightening_cleanup --undo  --yes-i-checked-the-dry-run --allow-mtime-drift

Guards against accidental writes:

- ``--commit`` refuses unless a manifest file exists at
  ``.local/op-fact-cleanup-manifest.json`` produced by a prior
  ``--dry-run`` **on the same SQLite file**. It matches on:
  the SQLite path, size, mtime_ns, and DB URL. Any drift → refuse.
- Manifest must be < 24h old.
- ``--yes-i-checked-the-dry-run`` must be present.
- Soft-deletion runs in a single transaction. Idempotent: rows already
  soft-deleted (any reason) are left alone.
- ``--undo`` reverses only the exact rows the manifest recorded,
  under the same set of guards.
- ``--undo --allow-mtime-drift`` skips the mtime/size drift check but
  keeps the path/URL/age/reason-tag guards. Required when running
  ``--undo`` after a completed ``--commit`` because ``--commit``
  necessarily changed the SQLite mtime. Rejected under ``--commit``.

Buckets soft-deleted (OR'd, ``operational_fact`` type only):

1. ``family='shell' AND role='path'`` — the fallback catch-all bucket.
2. ``family='shell' AND role != 'path'`` where the artifact fails the
   admission-gate shape check (curl flags, port fragments, regex meta).
3. ``is_sensitive_artifact(artifact)`` returns True — SSH keys, PEMs,
   AWS creds, etc. that bypassed W3 redaction.
4. Any row where ``_is_admissible_candidate`` reconstruction returns
   False (defense in depth: catches drift between the shipped predicate
   and stored data).

Buckets NOT touched: any type other than ``operational_fact``, and any
row already soft-deleted.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from semantic.operational_fact import (
    OperationalFactCandidate,
    _is_admissible_candidate,
    _is_operational_shape_artifact,
)
from semantic.redaction import is_sensitive_artifact

logger = logging.getLogger(__name__)


SOFT_DELETE_REASON = "operational_fact_tightening_2026_07_02"
DEFAULT_MANIFEST_PATH = Path(".local/op-fact-cleanup-manifest.json")
MANIFEST_MAX_AGE = timedelta(hours=24)
# Match storage/sqlite.py's PRAGMA busy_timeout so we don't race the
# live service on a lock and fail where the storage layer would retry.
SQLITE_BUSY_TIMEOUT_S = 15


# --------------------------------------------------------------------------- #
# Bucket classifier                                                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CandidateRow:
    """A row extracted from the live DB for classification.

    Fields mirror what the classifier consults; no other row state
    (embedding, evidence, etc.) is loaded.
    """

    memory_object_id: str
    command_family: str
    artifact_role: str
    scope_kind: str
    scope_ref: str
    artifact: str
    artifact_normalized: str
    subject: str


@dataclass
class BucketCounts:
    shell_path: int = 0
    shell_nonpath_no_shape: int = 0
    sensitive: int = 0
    admission_reconstruct_fail: int = 0

    def total(self) -> int:
        return (
            self.shell_path
            + self.shell_nonpath_no_shape
            + self.sensitive
            + self.admission_reconstruct_fail
        )

    def as_dict(self) -> dict:
        return {
            "shell_path": self.shell_path,
            "shell_nonpath_no_shape": self.shell_nonpath_no_shape,
            "sensitive": self.sensitive,
            "admission_reconstruct_fail": self.admission_reconstruct_fail,
            "total": self.total(),
        }


def classify_row(row: CandidateRow) -> str | None:
    """Return the bucket name the row falls into, or None if the row
    should be kept.

    Buckets are OR'd — first match wins in the order documented at
    the top of this module.  The order is stable so undo/redo
    manifest keys stay consistent.
    """
    # 1. Sensitive artifacts — highest priority, PR A skips these
    # at emission time but rows written pre-PR-A survive here.
    if is_sensitive_artifact(row.artifact) or is_sensitive_artifact(
        row.artifact_normalized
    ):
        return "sensitive"

    # 2. Shell/path fallback bucket — the 86% noise slot.
    if row.command_family == "shell" and row.artifact_role == "path":
        return "shell_path"

    # 3. Shell/non-path without a valid shape.
    if row.command_family == "shell" and row.artifact_role != "path":
        if not _is_operational_shape_artifact(
            row.artifact_normalized, row.command_family, row.artifact_role
        ):
            return "shell_nonpath_no_shape"

    # 4. Admission-gate reconstruct — defense in depth.
    cand = OperationalFactCandidate(
        command_family=row.command_family,
        artifact_role=row.artifact_role,
        scope_kind=row.scope_kind,
        scope_ref=row.scope_ref,
        subject=row.subject,
        artifact=row.artifact,
        artifact_normalized=row.artifact_normalized,
        evidence=(),
    )
    admit, _reason = _is_admissible_candidate(cand)
    if not admit:
        return "admission_reconstruct_fail"

    return None


# --------------------------------------------------------------------------- #
# DB access                                                                   #
# --------------------------------------------------------------------------- #


def _resolve_sqlite_path(db_url: str) -> Path:
    """Extract the sqlite file path from a URL like ``sqlite:///...``."""
    if db_url.startswith("sqlite:///"):
        raw = db_url[len("sqlite:///") :]
    elif db_url.startswith("sqlite://"):
        raw = db_url[len("sqlite://") :]
    else:
        raise ValueError(
            f"only sqlite:// URLs supported here, got {db_url!r}"
        )
    return Path(raw)


def load_operational_fact_rows(sqlite_path: Path) -> list[CandidateRow]:
    """Read all ``type='operational_fact'`` rows that are not already
    soft-deleted.
    """
    conn = sqlite3.connect(str(sqlite_path), timeout=SQLITE_BUSY_TIMEOUT_S)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT
                id,
                json_extract(payload_json, '$.command_family'),
                json_extract(payload_json, '$.artifact_role'),
                json_extract(payload_json, '$.scope_kind'),
                json_extract(payload_json, '$.scope_ref'),
                json_extract(payload_json, '$.artifact'),
                json_extract(payload_json, '$.artifact_normalized'),
                json_extract(payload_json, '$.subject')
            FROM memory_objects
            WHERE type = 'operational_fact'
              AND is_soft_deleted = 0
            """
        ).fetchall()
    finally:
        conn.close()

    out: list[CandidateRow] = []
    for r in rows:
        out.append(
            CandidateRow(
                memory_object_id=r[0],
                command_family=r[1] or "",
                artifact_role=r[2] or "",
                scope_kind=r[3] or "",
                scope_ref=r[4] or "",
                artifact=r[5] or "",
                artifact_normalized=r[6] or "",
                subject=r[7] or "",
            )
        )
    return out


def apply_soft_delete(sqlite_path: Path, memory_object_ids: list[str]) -> int:
    """Soft-delete the given rows in a single transaction.

    Returns the number of rows actually modified. Rows already
    soft-deleted (any reason) are left alone.
    """
    if not memory_object_ids:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(str(sqlite_path), timeout=SQLITE_BUSY_TIMEOUT_S)
    try:
        cur = conn.cursor()
        n = 0
        cur.execute("BEGIN")
        try:
            for mid in memory_object_ids:
                res = cur.execute(
                    """
                    UPDATE memory_objects
                       SET is_soft_deleted = 1,
                           soft_deleted_at = ?,
                           soft_delete_reason = ?
                     WHERE id = ?
                       AND is_soft_deleted = 0
                    """,
                    (now, SOFT_DELETE_REASON, mid),
                )
                n += res.rowcount
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()
    return n


def apply_undo(sqlite_path: Path, memory_object_ids: list[str]) -> int:
    """Reverse the tightening soft-delete for the given IDs.

    Only rows whose ``soft_delete_reason == SOFT_DELETE_REASON`` are
    reverted; rows soft-deleted for other reasons are not touched.
    Returns the number of rows modified.
    """
    if not memory_object_ids:
        return 0
    conn = sqlite3.connect(str(sqlite_path), timeout=SQLITE_BUSY_TIMEOUT_S)
    try:
        cur = conn.cursor()
        n = 0
        cur.execute("BEGIN")
        try:
            for mid in memory_object_ids:
                res = cur.execute(
                    """
                    UPDATE memory_objects
                       SET is_soft_deleted = 0,
                           soft_deleted_at = NULL,
                           soft_delete_reason = NULL
                     WHERE id = ?
                       AND soft_delete_reason = ?
                    """,
                    (mid, SOFT_DELETE_REASON),
                )
                n += res.rowcount
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()
    return n


# --------------------------------------------------------------------------- #
# Manifest                                                                    #
# --------------------------------------------------------------------------- #


def write_manifest(
    manifest_path: Path,
    *,
    db_url: str,
    sqlite_path: Path,
    buckets: BucketCounts,
    candidate_ids: list[str],
    total_op_fact_rows: int,
) -> None:
    """Serialize the manifest atomically. Overwrites any prior manifest."""
    stat = sqlite_path.stat()
    manifest = {
        "reason_tag": SOFT_DELETE_REASON,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "db_url": db_url,
        "sqlite_path": str(sqlite_path),
        "sqlite_size_bytes": stat.st_size,
        "sqlite_mtime_ns": stat.st_mtime_ns,
        "total_operational_fact_rows_before": total_op_fact_rows,
        "buckets": buckets.as_dict(),
        "candidate_deletion_ids": candidate_ids,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    tmp.replace(manifest_path)


def load_manifest(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def validate_manifest(
    manifest: dict,
    *,
    db_url: str,
    sqlite_path: Path,
    allow_mtime_drift: bool = False,
) -> str | None:
    """Return an error string if the manifest is stale or drifted;
    None on success.

    ``allow_mtime_drift``: escape hatch for the undo path. After a
    successful ``--commit`` the sqlite mtime necessarily advanced, so
    validating the SAME manifest against post-commit state would
    otherwise refuse. When True, mtime/size drift is downgraded to a
    warning; the db_url/sqlite_path/age guards still apply.
    """
    written_at_raw = manifest.get("written_at")
    if not written_at_raw:
        return "manifest missing written_at"
    try:
        written_at = datetime.fromisoformat(written_at_raw)
    except ValueError as exc:
        return f"manifest written_at not parseable: {exc}"
    age = datetime.now(timezone.utc) - written_at
    if age > MANIFEST_MAX_AGE:
        return (
            f"manifest is {age.total_seconds() / 3600:.1f}h old — "
            f"stale (limit {MANIFEST_MAX_AGE.total_seconds() / 3600:.0f}h). "
            "re-run --dry-run."
        )

    if manifest.get("db_url") != db_url:
        return (
            f"manifest db_url mismatch: manifest={manifest.get('db_url')!r} "
            f"vs current={db_url!r}"
        )
    if manifest.get("sqlite_path") != str(sqlite_path):
        return (
            f"manifest sqlite_path mismatch: "
            f"manifest={manifest.get('sqlite_path')!r} vs current={str(sqlite_path)!r}"
        )
    try:
        stat = sqlite_path.stat()
    except FileNotFoundError:
        return f"sqlite file missing at {sqlite_path}"
    if not allow_mtime_drift:
        if manifest.get("sqlite_mtime_ns") != stat.st_mtime_ns:
            return (
                f"sqlite mtime drift: manifest={manifest.get('sqlite_mtime_ns')} "
                f"vs current={stat.st_mtime_ns}. DB was modified since --dry-run. "
                "For undo after a completed commit, pass --allow-mtime-drift."
            )
        size_delta = abs(manifest.get("sqlite_size_bytes", 0) - stat.st_size)
        if size_delta > 1024:
            return (
                f"sqlite size drift: manifest={manifest.get('sqlite_size_bytes')} "
                f"vs current={stat.st_size} (delta={size_delta} bytes > 1KB). "
                "DB was modified since --dry-run."
            )
    return None


# --------------------------------------------------------------------------- #
# Dry-run + commit orchestration                                              #
# --------------------------------------------------------------------------- #


def classify_all(rows: list[CandidateRow]) -> tuple[BucketCounts, list[str], dict[str, list[str]]]:
    """Return (bucket counts, ordered candidate IDs, per-bucket IDs).

    Ordering: rows are returned in the order the DB emitted them. This
    is deterministic per DB state and stable across runs so the
    manifest fingerprint is reproducible.
    """
    counts = BucketCounts()
    ids: list[str] = []
    per_bucket: dict[str, list[str]] = {
        "shell_path": [],
        "shell_nonpath_no_shape": [],
        "sensitive": [],
        "admission_reconstruct_fail": [],
    }
    for row in rows:
        bucket = classify_row(row)
        if bucket is None:
            continue
        ids.append(row.memory_object_id)
        per_bucket[bucket].append(row.memory_object_id)
        setattr(counts, bucket, getattr(counts, bucket) + 1)
    return counts, ids, per_bucket


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="operational_fact_tightening_cleanup",
        description=(
            "Soft-delete operational_fact rows that fail the tightened "
            "admission gate. See module docstring for guarded workflow."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the buckets and write a manifest under .local/. No writes.",
    )
    group.add_argument(
        "--commit",
        action="store_true",
        help="Apply the soft-delete. Requires --yes-i-checked-the-dry-run + valid manifest.",
    )
    group.add_argument(
        "--undo",
        action="store_true",
        help="Reverse the soft-delete. Requires --yes-i-checked-the-dry-run + valid manifest.",
    )
    parser.add_argument(
        "--yes-i-checked-the-dry-run",
        action="store_true",
        help="Acknowledge that --dry-run was reviewed. Required for --commit / --undo.",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST_PATH),
        help=f"Path to the manifest file (default {DEFAULT_MANIFEST_PATH}).",
    )
    parser.add_argument(
        "--allow-mtime-drift",
        action="store_true",
        help=(
            "Escape hatch for --undo: allow mtime/size drift between the "
            "manifest and current DB state. Required when running --undo "
            "after --commit succeeded (commit changed mtime_ns). "
            "Refuses --commit."
        ),
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help=(
            "sqlite:// URL. Defaults to $PALLIUM_DATABASE_URL or "
            "sqlite:///~/.pallium/data/pallium.db"
        ),
    )
    return parser


def _default_db_url() -> str:
    env = os.environ.get("PALLIUM_DATABASE_URL")
    if env:
        return env
    home = Path.home()
    return f"sqlite:///{home.as_posix()}/.pallium/data/pallium.db"


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)

    db_url = args.db_url or _default_db_url()
    sqlite_path = _resolve_sqlite_path(db_url)
    manifest_path = Path(args.manifest)

    if not sqlite_path.exists():
        print(f"sqlite file missing at {sqlite_path}", file=sys.stderr)
        return 2

    if args.dry_run:
        rows = load_operational_fact_rows(sqlite_path)
        counts, ids, per_bucket = classify_all(rows)
        report = {
            "mode": "dry-run",
            "db_url": db_url,
            "sqlite_path": str(sqlite_path),
            "total_operational_fact_rows": len(rows),
            "would_soft_delete": counts.as_dict(),
            "per_bucket_first_5_examples": {
                k: v[:5] for k, v in per_bucket.items()
            },
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        write_manifest(
            manifest_path,
            db_url=db_url,
            sqlite_path=sqlite_path,
            buckets=counts,
            candidate_ids=ids,
            total_op_fact_rows=len(rows),
        )
        print(f"\nmanifest written: {manifest_path}", file=sys.stderr)
        return 0

    # --commit or --undo
    if not args.yes_i_checked_the_dry_run:
        print(
            "refusing: --yes-i-checked-the-dry-run is required for "
            "--commit / --undo. re-run --dry-run and confirm the plan.",
            file=sys.stderr,
        )
        return 2

    if not manifest_path.exists():
        print(
            f"refusing: manifest missing at {manifest_path}. run --dry-run first.",
            file=sys.stderr,
        )
        return 2

    manifest = load_manifest(manifest_path)
    # Only --undo accepts --allow-mtime-drift (the flag is meaningless
    # for --commit, which requires a fresh manifest).
    if args.commit and args.allow_mtime_drift:
        print(
            "refusing: --allow-mtime-drift is only valid for --undo. "
            "for --commit, run --dry-run first to refresh the manifest.",
            file=sys.stderr,
        )
        return 2
    err = validate_manifest(
        manifest,
        db_url=db_url,
        sqlite_path=sqlite_path,
        allow_mtime_drift=bool(args.undo and args.allow_mtime_drift),
    )
    if err is not None:
        print(f"refusing: {err}", file=sys.stderr)
        return 2

    candidate_ids: list[str] = list(manifest.get("candidate_deletion_ids", []))

    if args.commit:
        n = apply_soft_delete(sqlite_path, candidate_ids)
        print(json.dumps({
            "mode": "commit",
            "rows_marked_soft_deleted": n,
            "manifest_candidate_count": len(candidate_ids),
        }, indent=2, sort_keys=True))
        return 0

    if args.undo:
        n = apply_undo(sqlite_path, candidate_ids)
        print(json.dumps({
            "mode": "undo",
            "rows_reverted": n,
            "manifest_candidate_count": len(candidate_ids),
        }, indent=2, sort_keys=True))
        return 0

    return 0  # unreachable


if __name__ == "__main__":
    sys.exit(main())
