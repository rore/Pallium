"""Soft-delete legacy pre-PR-3 ``operational_fact`` rows.

Motivation (PR 5 of the operational_fact redesign, 2026-07-02):
PR 3 replaced the permissive discovery+use pairing extractor with a
closed-verb reconnaissance predicate, and PR 4 added the candidate →
active promotion gate driven by ``supported_by`` relations. Any row
that predates PR 4 that is currently ``lifecycle='active'`` was
emitted by the old extractor with no ``supported_by`` witness — by
construction it cannot represent a cross-thread promotion and is
noise from the old permissive gate.

The discriminator is deliberately narrow: rows that HAVE a
``supported_by`` relation are legitimate post-PR-4 promotions and
MUST NOT be touched. Only rows without such a relation are soft-
deleted here.

Design shape (mirror of :mod:`app.tools.secrets_purge`):

- **Dry-run** — scan matching rows, write a manifest with the
  SQLite fingerprint (mtime_ns, size_bytes, path, url, timestamp,
  row-count witness) so ``--commit`` refuses if the DB drifted.

- **Commit** — soft-delete each row with reason tag
  :data:`SOFT_DELETE_REASON`. Rewrites are not needed; the ``lifecycle``
  and ``payload_json`` stay intact so ``--undo`` is a simple
  ``is_soft_deleted = 0`` flip.

- **Undo** — reverse a prior commit by flipping ``is_soft_deleted``
  back to 0 for every row in the manifest whose current
  ``soft_delete_reason`` matches the reason tag (so an unrelated
  post-commit soft-delete on the same id is preserved).
  ``--allow-mtime-drift`` escape hatch skips the mtime guard so undo
  can run AFTER commit (commit necessarily bumps mtime).

Usage::

    python -m app.tools.operational_fact_migration_pr5 --dry-run
    python -m app.tools.operational_fact_migration_pr5 --commit --yes-i-checked-the-dry-run
    python -m app.tools.operational_fact_migration_pr5 --undo  --yes-i-checked-the-dry-run --allow-mtime-drift
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

logger = logging.getLogger(__name__)


SOFT_DELETE_REASON = "operational_fact_redesign_migration_2026_07"
DEFAULT_MANIFEST_PATH = Path(".local/operational-fact-migration-pr5-manifest.json")
MANIFEST_MAX_AGE = timedelta(hours=24)
SQLITE_BUSY_TIMEOUT_S = 15
SIZE_TOLERANCE_BYTES = 1024


# Discriminator: legacy pre-PR-3 rows lack any ``supported_by`` relation.
# Post-PR-4 promoted rows ship with the relation, so filtering them out
# here isolates the legacy set. See PR 5 plan.
_LEGACY_ROW_SQL = (
    "SELECT id, subject, lifecycle "
    "FROM memory_objects "
    "WHERE type = 'operational_fact' "
    "  AND lifecycle = 'active' "
    "  AND is_soft_deleted = 0 "
    "  AND id NOT IN ("
    "      SELECT from_id FROM relations "
    "      WHERE relation_type = 'supported_by' "
    "        AND from_kind = 'memory_object'"
    "  )"
)


# --------------------------------------------------------------------------- #
# Row scan + plan                                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LegacyRow:
    memory_object_id: str
    subject: str
    lifecycle: str


@dataclass
class MigrationPlan:
    rows: list[LegacyRow] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {"legacy_active_rows_to_soft_delete": len(self.rows)}


def _scan_legacy_rows(conn: sqlite3.Connection) -> list[LegacyRow]:
    out: list[LegacyRow] = []
    for row in conn.execute(_LEGACY_ROW_SQL).fetchall():
        mid, subject, lifecycle = row
        out.append(
            LegacyRow(
                memory_object_id=mid,
                subject=subject or "",
                lifecycle=lifecycle or "",
            )
        )
    return out


def build_plan(sqlite_path: Path) -> MigrationPlan:
    conn = sqlite3.connect(str(sqlite_path), timeout=SQLITE_BUSY_TIMEOUT_S)
    try:
        rows = _scan_legacy_rows(conn)
    finally:
        conn.close()
    return MigrationPlan(rows=rows)


# --------------------------------------------------------------------------- #
# Apply + undo                                                                #
# --------------------------------------------------------------------------- #


def apply_plan(sqlite_path: Path, plan: MigrationPlan) -> dict[str, int]:
    """Soft-delete every row in the plan. Returns per-bucket rowcounts.

    A single sqlite3 transaction encloses every update so a crash mid-
    apply cannot leave the DB half-migrated. Uses BEGIN IMMEDIATE for
    an exclusive write lock.
    """
    now = datetime.now(timezone.utc).isoformat()
    modified = {"soft_deleted": 0}

    conn = sqlite3.connect(str(sqlite_path), timeout=SQLITE_BUSY_TIMEOUT_S)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            for row in plan.rows:
                res = cur.execute(
                    "UPDATE memory_objects "
                    "SET is_soft_deleted = 1, "
                    "    soft_deleted_at = ?, "
                    "    soft_delete_reason = ? "
                    "WHERE id = ? "
                    "  AND is_soft_deleted = 0",
                    (now, SOFT_DELETE_REASON, row.memory_object_id),
                )
                modified["soft_deleted"] += res.rowcount
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()

    return modified


def undo_plan(sqlite_path: Path, manifest: dict) -> dict[str, int]:
    """Reverse a prior --commit by flipping ``is_soft_deleted`` back to 0
    for every id whose current ``soft_delete_reason`` matches this
    migration's tag (so unrelated concurrent soft-deletes are preserved).
    """
    ids: list[str] = list(manifest.get("legacy_row_ids", []))
    modified = {"undone": 0}
    conn = sqlite3.connect(str(sqlite_path), timeout=SQLITE_BUSY_TIMEOUT_S)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            for mid in ids:
                res = cur.execute(
                    "UPDATE memory_objects "
                    "SET is_soft_deleted = 0, "
                    "    soft_deleted_at = NULL, "
                    "    soft_delete_reason = NULL "
                    "WHERE id = ? "
                    "  AND soft_delete_reason = ?",
                    (mid, SOFT_DELETE_REASON),
                )
                modified["undone"] += res.rowcount
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()
    return modified


# --------------------------------------------------------------------------- #
# Manifest                                                                    #
# --------------------------------------------------------------------------- #


def write_manifest(
    manifest_path: Path,
    *,
    db_url: str,
    sqlite_path: Path,
    plan: MigrationPlan,
) -> None:
    stat = sqlite_path.stat()
    manifest = {
        "reason_tag": SOFT_DELETE_REASON,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "db_url": db_url,
        "sqlite_path": str(sqlite_path),
        "sqlite_size_bytes": stat.st_size,
        "sqlite_mtime_ns": stat.st_mtime_ns,
        "counts": plan.counts(),
        "legacy_row_ids": [r.memory_object_id for r in plan.rows],
        "legacy_row_subjects_sample": [
            {"id": r.memory_object_id, "subject": r.subject[:200]}
            for r in plan.rows[:20]
        ],
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
        if size_delta > SIZE_TOLERANCE_BYTES:
            return (
                f"sqlite size drift: manifest={manifest.get('sqlite_size_bytes')} "
                f"vs current={stat.st_size} (delta={size_delta} bytes > "
                f"{SIZE_TOLERANCE_BYTES} bytes). DB was modified since --dry-run."
            )
    return None


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _resolve_sqlite_path(db_url: str) -> Path:
    if db_url.startswith("sqlite:///"):
        raw = db_url[len("sqlite:///"):]
    elif db_url.startswith("sqlite://"):
        raw = db_url[len("sqlite://"):]
    else:
        raise ValueError(f"only sqlite:// URLs supported here, got {db_url!r}")
    return Path(raw)


def _default_db_url() -> str:
    env = os.environ.get("PALLIUM_DATABASE_URL")
    if env:
        return env
    home = Path.home()
    return f"sqlite:///{home.as_posix()}/.pallium/data/pallium.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="operational_fact_migration_pr5",
        description=(
            "Soft-delete pre-PR-3 legacy 'operational_fact' rows (rows in "
            "lifecycle=active WITHOUT a supported_by relation, which by "
            "construction cannot be a post-PR-4 promotion). Reason tag: "
            f"{SOFT_DELETE_REASON!r}. Reversible via --undo."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true",
                       help="Report plan and write manifest under .local/. No writes.")
    group.add_argument("--commit", action="store_true",
                       help="Apply the plan. Requires --yes-i-checked-the-dry-run + valid manifest.")
    group.add_argument("--undo", action="store_true",
                       help="Reverse a prior commit. Requires --yes-i-checked-the-dry-run + valid manifest.")
    parser.add_argument("--yes-i-checked-the-dry-run", action="store_true",
                        help="Acknowledge that --dry-run was reviewed. Required for --commit / --undo.")
    parser.add_argument("--allow-mtime-drift", action="store_true",
                        help="Escape hatch for --undo after --commit (commit changed the mtime). Refused under --commit.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH),
                        help=f"Path to the manifest file (default {DEFAULT_MANIFEST_PATH}).")
    parser.add_argument("--db-url", default=None,
                        help="sqlite:// URL. Defaults to $PALLIUM_DATABASE_URL or ~/.pallium/data/pallium.db.")
    return parser


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
        plan = build_plan(sqlite_path)
        report = {
            "mode": "dry-run",
            "db_url": db_url,
            "sqlite_path": str(sqlite_path),
            "counts": plan.counts(),
            "sample_row_subjects": [
                {"id": r.memory_object_id, "subject": r.subject[:120]}
                for r in plan.rows[:10]
            ],
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        write_manifest(manifest_path, db_url=db_url, sqlite_path=sqlite_path, plan=plan)
        print(f"\nmanifest written: {manifest_path}", file=sys.stderr)
        return 0

    # --commit or --undo
    if not args.yes_i_checked_the_dry_run:
        print(
            "refusing: --yes-i-checked-the-dry-run is required for --commit / --undo.",
            file=sys.stderr,
        )
        return 2

    if args.commit and args.allow_mtime_drift:
        print(
            "refusing: --allow-mtime-drift is only valid for --undo (--commit must run against a fresh manifest).",
            file=sys.stderr,
        )
        return 2

    if not manifest_path.exists():
        print(f"refusing: manifest missing at {manifest_path}. run --dry-run first.", file=sys.stderr)
        return 2

    manifest = load_manifest(manifest_path)
    err = validate_manifest(
        manifest,
        db_url=db_url,
        sqlite_path=sqlite_path,
        allow_mtime_drift=bool(args.undo and args.allow_mtime_drift),
    )
    if err is not None:
        print(f"refusing: {err}", file=sys.stderr)
        return 2

    if args.commit:
        plan = _plan_from_manifest(manifest)
        result = apply_plan(sqlite_path, plan)
        print(json.dumps({"mode": "commit", "rows_modified": result}, indent=2, sort_keys=True))
        return 0

    if args.undo:
        result = undo_plan(sqlite_path, manifest)
        print(json.dumps({"mode": "undo", "rows_reverted": result}, indent=2, sort_keys=True))
        return 0

    return 0  # unreachable


def _plan_from_manifest(manifest: dict) -> MigrationPlan:
    """Reconstruct the MigrationPlan from a manifest so --commit applies
    the exact set the operator dry-ran, not a re-scanned set."""
    plan = MigrationPlan()
    subjects_by_id = {
        entry["id"]: entry.get("subject", "")
        for entry in manifest.get("legacy_row_subjects_sample", [])
    }
    for mid in manifest.get("legacy_row_ids", []):
        plan.rows.append(LegacyRow(
            memory_object_id=mid,
            subject=subjects_by_id.get(mid, ""),
            lifecycle="active",
        ))
    return plan


if __name__ == "__main__":
    sys.exit(main())
