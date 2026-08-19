"""One-off data fix: canonicalize non-canonical GitHub container_ref on memory
objects (merges scopes split by casing, e.g. rore/Pallium -> rore/pallium).

Only ``memory_objects.container_ref`` is re-pointed: relations/index_entries key
on the object id (not container), and audit/feedback/funnel rows record
query-context container, not the memory's home scope, so they are left as-is.

Dry-run by default (prints what WOULD change). Pass ``--apply`` to write.
Idempotent: already-canonical rows are skipped, so re-running is a no-op.

    python -m scripts.backfill_container_ref_canonical            # preview
    python -m scripts.backfill_container_ref_canonical --apply    # write
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.container_ref import canonicalize_container_ref  # noqa: E402

_DEFAULT_DB = Path.home() / ".pallium" / "data" / "pallium.db"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(_DEFAULT_DB), help="SQLite DB path")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, container_ref, type, created_at FROM memory_objects "
            "WHERE container_ref LIKE 'git:github.com/%'"
        ).fetchall()
        changes = [
            (r["id"], r["container_ref"], canonicalize_container_ref(r["container_ref"]))
            for r in rows
            if canonicalize_container_ref(r["container_ref"]) != r["container_ref"]
        ]
        if not changes:
            print("Nothing to do — all GitHub container_refs are already canonical.")
            return 0
        print(f"{len(changes)} memory object(s) to re-point:")
        for mid, old, new in changes:
            print(f"  {mid}  {old!r} -> {new!r}")
        if not args.apply:
            print("\nDry-run. Re-run with --apply to write.")
            return 0
        conn.execute("PRAGMA busy_timeout = 5000")
        with conn:  # single transaction
            for mid, _old, new in changes:
                conn.execute(
                    "UPDATE memory_objects SET container_ref = ? WHERE id = ?", (new, mid)
                )
        remaining = conn.execute(
            "SELECT COUNT(*) FROM memory_objects WHERE container_ref LIKE 'git:github.com/%' "
            "AND container_ref != LOWER(container_ref)"
        ).fetchone()[0]
        print(f"\nApplied {len(changes)} update(s). Non-canonical GitHub rows remaining: {remaining}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
