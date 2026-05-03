"""Suppress legacy thread_detection decisions that fail current quality gates.

Targets two categories:
1. Decisions with user/message: evidence prefix (predate dd55287 fix)
2. Decisions that fail the new substance filters (too short, lazy copy)

Usage:
    python -m scripts.suppress_legacy_thread_decisions --dry-run
    python -m scripts.suppress_legacy_thread_decisions
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from semantic.common import _normalize_for_containment


DEFAULT_DB_PATH = Path.home() / ".pallium" / "data" / "pallium.db"


def _fails_substance_filters(decision_text: str, evidence: str) -> str | None:
    """Check if a decision fails the new substance filters. Returns reason or None.

    NOTE: This is a point-in-time snapshot of the filters in _validate_thread_decisions()
    for retroactive cleanup. If the production filters change, this script is NOT
    expected to stay in sync — it's a one-time migration tool.
    """
    norm_dt = _normalize_for_containment(decision_text)
    norm_ev = _normalize_for_containment(evidence)
    if len(norm_dt) < 30:
        return "too_short"
    if norm_dt == norm_ev:
        return "decision_equals_evidence"
    if len(norm_dt) < 50 and norm_dt in norm_ev and norm_dt != norm_ev:
        return "short_contained_in_evidence"
    return None


def find_legacy_decisions(db_path: Path) -> list[dict]:
    """Find active thread_detection decisions that fail current quality gates."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        SELECT id, payload_json, created_at
        FROM memory_objects
        WHERE type = 'decision'
          AND lifecycle = 'active'
          AND json_extract(payload_json, '$.source_type') = 'thread_detection'
    """)
    results = []
    for row in cur.fetchall():
        payload = json.loads(row[1])
        decision_text = payload.get("decision", "")
        evidence = payload.get("decision_evidence_text", "")
        reason = None
        if evidence.strip().startswith("user/"):
            reason = "user_evidence_prefix"
        else:
            reason = _fails_substance_filters(decision_text, evidence)
        if reason:
            results.append({
                "id": row[0],
                "decision_text": decision_text,
                "evidence": evidence,
                "created_at": row[2],
                "reason": reason,
            })
    conn.close()
    return results


def suppress_decisions(db_path: Path, decision_ids: list[str]) -> int:
    """Set lifecycle to 'suppressed' for the given decision IDs."""
    if not decision_ids:
        return 0
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in decision_ids)
    cur.execute(
        f"UPDATE memory_objects SET lifecycle = 'suppressed' WHERE id IN ({placeholders})",
        decision_ids,
    )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def main():
    parser = argparse.ArgumentParser(description="Suppress legacy thread decisions with user/message: evidence")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be suppressed without making changes")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Path to pallium.db")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    decisions = find_legacy_decisions(args.db)

    if not decisions:
        print("No legacy decisions found that fail current quality gates.")
        return

    print(f"Found {len(decisions)} legacy decisions that fail current quality gates:")
    print()
    for d in decisions:
        print(f"  {d['id'][:8]} [{d['reason']}] | {d['decision_text'][:60]}")
        print(f"           | ev: {d['evidence'][:50]}")
        print()

    if args.dry_run:
        print(f"[DRY RUN] Would suppress {len(decisions)} decisions.")
        return

    ids = [d["id"] for d in decisions]
    count = suppress_decisions(args.db, ids)
    print(f"Suppressed {count} decisions.")


if __name__ == "__main__":
    main()
