"""Purge existing secrets from persisted Pallium storage.

Motivation (2026-07-02 live audit): Slack tokens, GitHub PAT, env-var
secrets, and connection-string credentials were found embedded in
active ``memory_objects``, ``source_items``, and ``lexical_fts`` rows
that predate the PR 0 write / LLM-response / retrieval barriers.
Those barriers close the leak channel for future ingest; this CLI
purges what's already stored.

Design shape (mirror of
:mod:`app.tools.operational_fact_tightening_cleanup`):

- **Dry-run** — scan every row in scope, classify, write a manifest
  describing the plan. Zero writes. Manifest carries the SQLite
  fingerprint (mtime_ns, size_bytes, path, url, timestamp) so
  ``--commit`` refuses if the DB drifted since the plan was made.

- **Commit** — apply the plan under a single transaction per table.
  Every row gets one of two treatments:

  * **Regenerable types** (``thread_summary``, ``task_checkpoint``,
    ``atomic_fact``, ``fact_summary``, ``pattern_memory``,
    ``continuity_memory``, ``turn_summary``) → soft-delete the row.
    The next thread rebuild regenerates the memory from the redacted
    source, producing a clean version.

  * **Narrative types** (``decision``, ``investigation_outcome``,
    ``task_trace``, ``operational_fact``, ``constraint_memory``,
    ``note``, plus fallback for unknown types) → in-place rewrite:
    walk ``payload_json`` and ``subject``, redact string leaves,
    save back to the row. Preserves surrounding narrative
    ("a GitHub PAT was exposed" is useful; the PAT value is not).

  * **Note carveout** — memories of type ``note`` are user-explicit
    verbatim recall; they are NOT rewritten even if they contain
    secret-shaped content. Same trade-off as the ingest / retrieval
    barriers.

  * **Source items** → in-place rewrite of ``content`` and
    ``metadata_json``. Same note carveout applies via
    ``artifact_kind='note'``.

  * **Index entries + lexical FTS** → rewrite ``text_view`` in
    ``index_entries`` AND ``DELETE + INSERT`` the ``lexical_fts``
    row via ``SqliteStorage.redact_index_entry_text_view``. FTS5
    does not support UPDATE on columns; the pre-existing
    ``update_index_entry_text_view`` leaves FTS stale and would
    keep leaking on lexical search.

- **Undo** — reverse ``--commit`` by replaying the manifest's
  ``pre_redaction_snapshots``. The manifest carries the pre-
  redaction ``payload_json`` / ``subject`` / ``content`` /
  ``metadata_json`` / ``text_view`` for every rewritten row, plus
  the soft-delete IDs. Under ``--allow-mtime-drift`` the mtime
  guard is skipped so undo can run AFTER commit (which changed
  the mtime).

Same manifest-guard pattern as PR C's op-fact cleanup CLI:
``--commit``/``--undo`` refuse if the manifest is stale (>24h),
if the SQLite fingerprint drifted, if the manifest is missing, or
if ``--yes-i-checked-the-dry-run`` is not present.

Usage::

    python -m app.tools.secrets_purge --dry-run
    python -m app.tools.secrets_purge --commit --yes-i-checked-the-dry-run
    python -m app.tools.secrets_purge --undo  --yes-i-checked-the-dry-run --allow-mtime-drift
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
from typing import Any, Sequence

from semantic.redaction import redact_sensitive

logger = logging.getLogger(__name__)


SOFT_DELETE_REASON = "secret_redaction_migration_2026_07_02"
DEFAULT_MANIFEST_PATH = Path(".local/secrets-purge-manifest.json")
MANIFEST_MAX_AGE = timedelta(hours=24)
SQLITE_BUSY_TIMEOUT_S = 15
SIZE_TOLERANCE_BYTES = 1024


REGENERABLE_TYPES: frozenset[str] = frozenset({
    "thread_summary",
    "task_checkpoint",
    "atomic_fact",
    "fact_summary",
    "pattern_memory",
    "continuity_memory",
    "turn_summary",
})

# Memory types where the row's ``artifact_kind`` on the associated
# source_item is 'note' — never rewrite. But since we scan memory rows
# directly and don't join to source_items, we also treat memory
# ``type='note'`` as a hard skip. User-explicit recall wins.
NOTE_TYPES: frozenset[str] = frozenset({"note"})


# --------------------------------------------------------------------------- #
# Row scan + classification                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MemoryRowCandidate:
    memory_object_id: str
    type: str
    subject: str
    payload_json: str
    redacted_subject: str
    redacted_payload_json: str
    bucket: str  # "regenerable" | "narrative" | "note_carveout"


@dataclass(frozen=True)
class SourceItemCandidate:
    source_item_id: str
    artifact_kind: str | None
    content: str
    metadata_json: str | None
    redacted_content: str
    redacted_metadata_json: str | None


@dataclass(frozen=True)
class IndexEntryCandidate:
    index_entry_id: str
    text_view: str
    redacted_text_view: str


@dataclass
class PurgePlan:
    memory_rows: list[MemoryRowCandidate] = field(default_factory=list)
    source_items: list[SourceItemCandidate] = field(default_factory=list)
    index_entries: list[IndexEntryCandidate] = field(default_factory=list)
    regenerable_ids: list[str] = field(default_factory=list)
    note_skipped_ids: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "memory_rewrites": sum(
                1 for r in self.memory_rows if r.bucket == "narrative"
            ),
            "memory_soft_deletes": len(self.regenerable_ids),
            "source_item_rewrites": len(self.source_items),
            "index_entry_rewrites": len(self.index_entries),
            "notes_skipped": len(self.note_skipped_ids),
        }


def _redact_json_leaves(obj: Any) -> Any:
    """Recursively redact string leaves in a JSON-shaped value.

    Same rules as :func:`core.service._redact_ingest_value` — redact
    values not keys, preserve container types, leave numeric/bool/None
    untouched. Kept as a private helper because this module is loaded
    independently of core.service (avoids circular import).
    """
    if isinstance(obj, str):
        return redact_sensitive(obj)
    if obj is None or isinstance(obj, (int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _redact_json_leaves(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_json_leaves(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_redact_json_leaves(v) for v in obj)
    return obj


def _redact_json_string(json_str: str | None) -> str | None:
    """Redact a JSON-serialized dict/list without altering its shape.

    Return the input unchanged unless a string leaf was actually
    redacted. This avoids false-positive "changes" from JSON round-
    trip artifacts (Unicode escape ``\\u2192`` normalizing to the
    literal arrow char under ``ensure_ascii=False``, key-order
    differences, whitespace, etc.) — those are byte-level noise, not
    semantic redaction.

    Detection strategy: parse the input, walk it, apply
    :func:`redact_sensitive` to each string leaf, and check whether
    the walked structure differs from the parsed structure. If not,
    return the original ``json_str`` byte-identical.
    """
    if not json_str:
        return json_str
    try:
        obj = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        # Fall back to plain-text redaction if not valid JSON.
        red = redact_sensitive(json_str)
        return red if red != json_str else json_str
    redacted_obj = _redact_json_leaves(obj)
    if redacted_obj == obj:
        # Structurally unchanged — return the original byte-string
        # to avoid triggering false-positive rewrites from JSON
        # serialization drift.
        return json_str
    return json.dumps(redacted_obj, ensure_ascii=False)


def _scan_memory_rows(conn: sqlite3.Connection) -> tuple[list[MemoryRowCandidate], list[str], list[str]]:
    """Scan every active memory_objects row; return (rewrites, regenerable_ids,
    note_skipped_ids)."""
    rewrites: list[MemoryRowCandidate] = []
    regenerable: list[str] = []
    note_skipped: list[str] = []
    for row in conn.execute(
        "SELECT id, type, subject, payload_json FROM memory_objects "
        "WHERE is_soft_deleted = 0"
    ).fetchall():
        mid, mtype, subject, payload = row
        subject = subject or ""
        payload = payload or ""
        r_subject = redact_sensitive(subject)
        r_payload = _redact_json_string(payload) or ""
        changed = (r_subject != subject) or (r_payload != payload)
        if not changed:
            continue
        if mtype in NOTE_TYPES:
            note_skipped.append(mid)
            continue
        if mtype in REGENERABLE_TYPES:
            regenerable.append(mid)
            continue
        rewrites.append(MemoryRowCandidate(
            memory_object_id=mid,
            type=mtype,
            subject=subject,
            payload_json=payload,
            redacted_subject=r_subject,
            redacted_payload_json=r_payload,
            bucket="narrative",
        ))
    return rewrites, regenerable, note_skipped


def _scan_source_items(conn: sqlite3.Connection) -> list[SourceItemCandidate]:
    out: list[SourceItemCandidate] = []
    for row in conn.execute(
        "SELECT id, artifact_kind, content, metadata_json FROM source_items"
    ).fetchall():
        sid, kind, content, metadata = row
        if kind == "note":
            # Note items are the user-explicit recall surface. Skip.
            continue
        content = content or ""
        r_content = redact_sensitive(content)
        r_metadata = _redact_json_string(metadata)
        if r_content == content and r_metadata == metadata:
            continue
        out.append(SourceItemCandidate(
            source_item_id=sid,
            artifact_kind=kind,
            content=content,
            metadata_json=metadata,
            redacted_content=r_content,
            redacted_metadata_json=r_metadata,
        ))
    return out


def _scan_index_entries(conn: sqlite3.Connection) -> list[IndexEntryCandidate]:
    out: list[IndexEntryCandidate] = []
    for row in conn.execute(
        "SELECT id, text_view FROM index_entries"
    ).fetchall():
        eid, tv = row
        tv = tv or ""
        r_tv = redact_sensitive(tv)
        if r_tv == tv:
            continue
        out.append(IndexEntryCandidate(
            index_entry_id=eid,
            text_view=tv,
            redacted_text_view=r_tv,
        ))
    return out


def build_plan(sqlite_path: Path) -> PurgePlan:
    conn = sqlite3.connect(str(sqlite_path), timeout=SQLITE_BUSY_TIMEOUT_S)
    try:
        rewrites, regenerable, note_skipped = _scan_memory_rows(conn)
        source_items = _scan_source_items(conn)
        index_entries = _scan_index_entries(conn)
    finally:
        conn.close()
    return PurgePlan(
        memory_rows=rewrites,
        source_items=source_items,
        index_entries=index_entries,
        regenerable_ids=regenerable,
        note_skipped_ids=note_skipped,
    )


# --------------------------------------------------------------------------- #
# Apply + undo                                                                #
# --------------------------------------------------------------------------- #


def apply_plan(sqlite_path: Path, db_url: str, plan: PurgePlan) -> dict[str, int]:
    """Apply the redaction plan to the DB. Returns per-bucket rowcounts.

    All rewrites (memory / source_items / index_entries + lexical_fts)
    happen inside ONE sqlite3 transaction so a crash between phases
    cannot leave the DB in an inconsistent half-redacted state.
    Previously the index-entries + FTS rewrite used a separate
    SQLAlchemy session — a crash mid-loop could commit memory rewrites
    while leaving FTS unredacted, defeating the retrieval barrier for
    the surviving rows.
    """
    now = datetime.now(timezone.utc).isoformat()
    modified = {
        "memory_rewrites": 0,
        "memory_soft_deletes": 0,
        "source_item_rewrites": 0,
        "index_entry_rewrites": 0,
    }

    conn = sqlite3.connect(str(sqlite_path), timeout=SQLITE_BUSY_TIMEOUT_S)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")  # exclusive write lock
        try:
            # 1. Memory rewrites (narrative types).
            for row in plan.memory_rows:
                res = cur.execute(
                    "UPDATE memory_objects "
                    "SET subject = ?, payload_json = ? "
                    "WHERE id = ? AND is_soft_deleted = 0",
                    (row.redacted_subject, row.redacted_payload_json, row.memory_object_id),
                )
                modified["memory_rewrites"] += res.rowcount

            # 2. Memory soft-deletes (regenerable types).
            for mid in plan.regenerable_ids:
                res = cur.execute(
                    "UPDATE memory_objects "
                    "SET is_soft_deleted = 1, soft_deleted_at = ?, soft_delete_reason = ? "
                    "WHERE id = ? AND is_soft_deleted = 0",
                    (now, SOFT_DELETE_REASON, mid),
                )
                modified["memory_soft_deletes"] += res.rowcount

            # 3. Source-item rewrites.
            for item in plan.source_items:
                res = cur.execute(
                    "UPDATE source_items "
                    "SET content = ?, metadata_json = ? "
                    "WHERE id = ?",
                    (item.redacted_content, item.redacted_metadata_json, item.source_item_id),
                )
                modified["source_item_rewrites"] += res.rowcount

            # 4. Index entries + lexical_fts — in the SAME transaction
            #    via raw SQL so FTS5 DELETE+INSERT stays atomic with
            #    the memory/source rewrites above. Do NOT use
            #    SqliteStorage.redact_index_entry_text_view here: it
            #    opens a separate SQLAlchemy session which would
            #    commit outside this transaction (and leave a crash
            #    window where memory is redacted but FTS is not).
            for entry in plan.index_entries:
                # Resolve target_kind / target_id / text_view_name /
                # container_ref for the FTS row rebuild. These fields
                # live on the index_entries record.
                row = cur.execute(
                    "SELECT target_kind, target_id, text_view_name, index_type "
                    "FROM index_entries WHERE id = ?",
                    (entry.index_entry_id,),
                ).fetchone()
                if row is None:
                    continue
                target_kind, target_id, text_view_name, index_type = row
                # Update index_entries.text_view.
                res = cur.execute(
                    "UPDATE index_entries SET text_view = ? WHERE id = ?",
                    (entry.redacted_text_view, entry.index_entry_id),
                )
                if index_type != "lexical":
                    # Non-lexical (vector) entries have no lexical_fts
                    # mirror; skip the FTS rebuild.
                    modified["index_entry_rewrites"] += res.rowcount
                    continue
                # container_ref lookup — matches
                # SqliteStorage._resolve_container_ref_in_session.
                container_ref = _resolve_container_ref_in_txn(
                    cur, target_kind, target_id,
                )
                # DELETE + INSERT the lexical_fts row.
                cur.execute(
                    "DELETE FROM lexical_fts WHERE index_entry_id = ?",
                    (entry.index_entry_id,),
                )
                cur.execute(
                    "INSERT INTO lexical_fts"
                    "(text_view, index_entry_id, target_kind, target_id, "
                    " text_view_name, container_ref) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        entry.redacted_text_view,
                        entry.index_entry_id,
                        target_kind,
                        target_id,
                        text_view_name,
                        container_ref,
                    ),
                )
                modified["index_entry_rewrites"] += res.rowcount

            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()

    return modified


def _resolve_container_ref_in_txn(cur, target_kind: str, target_id: str) -> str | None:
    """Resolve the container_ref for an index-entry target inside an
    open sqlite3 cursor. Mirrors
    ``SqliteStorage._resolve_container_ref_in_session`` but uses raw
    SQL against the same transaction so FTS rebuild is atomic with
    the surrounding rewrite.
    """
    if target_kind == "memory_object":
        row = cur.execute(
            "SELECT container_ref FROM memory_objects WHERE id = ?",
            (target_id,),
        ).fetchone()
    elif target_kind == "source_item":
        row = cur.execute(
            "SELECT container_ref FROM source_items WHERE id = ?",
            (target_id,),
        ).fetchone()
    else:
        row = None
    return row[0] if row else None


def undo_plan(sqlite_path: Path, db_url: str, manifest: dict) -> dict[str, int]:
    """Reverse a prior --commit by replaying the pre-redaction snapshots
    stored in the manifest.

    All undo operations (memory / source_items / index_entries + FTS)
    run inside ONE sqlite3 transaction so a crash mid-undo cannot
    leave the DB half-restored. Uses ``BEGIN IMMEDIATE`` for an
    exclusive write lock so concurrent service writes cannot
    interleave.
    """
    snapshots = manifest.get("pre_redaction_snapshots", {})
    memory_snaps = snapshots.get("memory_objects", [])
    regenerable_ids = snapshots.get("regenerable_soft_deleted_ids", [])
    source_item_snaps = snapshots.get("source_items", [])
    index_entry_snaps = snapshots.get("index_entries", [])

    modified = {
        "memory_rewrites_undone": 0,
        "memory_soft_deletes_undone": 0,
        "source_item_rewrites_undone": 0,
        "index_entry_rewrites_undone": 0,
    }

    conn = sqlite3.connect(str(sqlite_path), timeout=SQLITE_BUSY_TIMEOUT_S)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            for snap in memory_snaps:
                res = cur.execute(
                    "UPDATE memory_objects SET subject = ?, payload_json = ? "
                    "WHERE id = ?",
                    (snap["subject"], snap["payload_json"], snap["memory_object_id"]),
                )
                modified["memory_rewrites_undone"] += res.rowcount
            for mid in regenerable_ids:
                res = cur.execute(
                    "UPDATE memory_objects "
                    "SET is_soft_deleted = 0, soft_deleted_at = NULL, "
                    "    soft_delete_reason = NULL "
                    "WHERE id = ? AND soft_delete_reason = ?",
                    (mid, SOFT_DELETE_REASON),
                )
                modified["memory_soft_deletes_undone"] += res.rowcount
            for snap in source_item_snaps:
                res = cur.execute(
                    "UPDATE source_items SET content = ?, metadata_json = ? WHERE id = ?",
                    (snap["content"], snap["metadata_json"], snap["source_item_id"]),
                )
                modified["source_item_rewrites_undone"] += res.rowcount

            # Index entries + FTS — same atomicity as apply_plan.
            for snap in index_entry_snaps:
                entry_id = snap["index_entry_id"]
                orig_text = snap["text_view"]
                row = cur.execute(
                    "SELECT target_kind, target_id, text_view_name, index_type "
                    "FROM index_entries WHERE id = ?",
                    (entry_id,),
                ).fetchone()
                if row is None:
                    continue
                target_kind, target_id, text_view_name, index_type = row
                res = cur.execute(
                    "UPDATE index_entries SET text_view = ? WHERE id = ?",
                    (orig_text, entry_id),
                )
                if index_type == "lexical":
                    container_ref = _resolve_container_ref_in_txn(
                        cur, target_kind, target_id,
                    )
                    cur.execute(
                        "DELETE FROM lexical_fts WHERE index_entry_id = ?",
                        (entry_id,),
                    )
                    cur.execute(
                        "INSERT INTO lexical_fts"
                        "(text_view, index_entry_id, target_kind, target_id, "
                        " text_view_name, container_ref) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            orig_text, entry_id, target_kind, target_id,
                            text_view_name, container_ref,
                        ),
                    )
                modified["index_entry_rewrites_undone"] += res.rowcount

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


def _build_pre_redaction_snapshots(plan: PurgePlan) -> dict[str, list[dict]]:
    return {
        "memory_objects": [
            {
                "memory_object_id": r.memory_object_id,
                "type": r.type,
                "subject": r.subject,
                "payload_json": r.payload_json,
            }
            for r in plan.memory_rows
        ],
        "regenerable_soft_deleted_ids": list(plan.regenerable_ids),
        "source_items": [
            {
                "source_item_id": item.source_item_id,
                "artifact_kind": item.artifact_kind,
                "content": item.content,
                "metadata_json": item.metadata_json,
            }
            for item in plan.source_items
        ],
        "index_entries": [
            {
                "index_entry_id": entry.index_entry_id,
                "text_view": entry.text_view,
            }
            for entry in plan.index_entries
        ],
    }


def write_manifest(
    manifest_path: Path,
    *,
    db_url: str,
    sqlite_path: Path,
    plan: PurgePlan,
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
        "pre_redaction_snapshots": _build_pre_redaction_snapshots(plan),
        "note_skipped_memory_ids": list(plan.note_skipped_ids),
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
    """Return an error string if the manifest is stale or drifted; None on success.

    ``allow_mtime_drift`` — escape hatch for undo after a completed commit
    (commit necessarily bumps mtime_ns).
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
        prog="secrets_purge",
        description=(
            "Purge secrets from persisted Pallium storage — memory_objects, "
            "source_items, index_entries + lexical_fts. Regenerable memory "
            "types (thread_summary, task_checkpoint, ...) are soft-deleted; "
            "narrative types are in-place rewritten. Note items are "
            "preserved verbatim (user-explicit recall)."
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
            "notes_skipped_examples": plan.note_skipped_ids[:5],
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
        # Reconstruct plan from manifest (to keep --commit deterministic
        # against the exact rows the operator reviewed).
        plan = _plan_from_manifest(manifest)
        result = apply_plan(sqlite_path, db_url, plan)
        print(json.dumps({"mode": "commit", "rows_modified": result}, indent=2, sort_keys=True))
        return 0

    if args.undo:
        result = undo_plan(sqlite_path, db_url, manifest)
        print(json.dumps({"mode": "undo", "rows_reverted": result}, indent=2, sort_keys=True))
        return 0

    return 0  # unreachable


def _plan_from_manifest(manifest: dict) -> PurgePlan:
    """Reconstruct the PurgePlan from a manifest so --commit applies the
    exact set the operator dry-ran, not a re-scanned set (which could
    differ if the DB drifted)."""
    snaps = manifest.get("pre_redaction_snapshots", {})
    plan = PurgePlan()
    for row in snaps.get("memory_objects", []):
        subject = row["subject"] or ""
        payload = row["payload_json"] or ""
        plan.memory_rows.append(MemoryRowCandidate(
            memory_object_id=row["memory_object_id"],
            type=row["type"],
            subject=subject,
            payload_json=payload,
            redacted_subject=redact_sensitive(subject),
            redacted_payload_json=_redact_json_string(payload) or "",
            bucket="narrative",
        ))
    plan.regenerable_ids = list(snaps.get("regenerable_soft_deleted_ids", []))
    for item in snaps.get("source_items", []):
        content = item["content"] or ""
        metadata = item.get("metadata_json")
        plan.source_items.append(SourceItemCandidate(
            source_item_id=item["source_item_id"],
            artifact_kind=item.get("artifact_kind"),
            content=content,
            metadata_json=metadata,
            redacted_content=redact_sensitive(content),
            redacted_metadata_json=_redact_json_string(metadata),
        ))
    for entry in snaps.get("index_entries", []):
        tv = entry["text_view"] or ""
        plan.index_entries.append(IndexEntryCandidate(
            index_entry_id=entry["index_entry_id"],
            text_view=tv,
            redacted_text_view=redact_sensitive(tv),
        ))
    return plan


if __name__ == "__main__":
    sys.exit(main())
