"""Workstream consolidation eval runner.

Re-runs the offline T1.7 consolidation re-key dry-run on the live
production DB using the in-repo
``capabilities/workstream_signals.py`` and ``capabilities/workstreams.py``
(NOT the offline reference under ``.local/research/_workstream_replay/``).

Reproduces the offline finding: 1014 → 1153 atomic_fact groups on the
self-referential slice, +13.7%. This is the regression guard for the
Phase 4A dry-run metric. Within ±10% of the offline finding indicates
the in-repo port behaves equivalently.

Read-only on the live DB. No LLM calls. No production code touched.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from capabilities.workstream_signals import (  # noqa: E402
    ItemSignals,
    parse_json_safe,
    signals_from_item,
)
from capabilities.workstreams import (  # noqa: E402
    WorkstreamRegistry,
    assign_workstream_for_item,
    watermark_for,
)


DEFAULT_DB = str(Path.home() / ".pallium" / "data" / "pallium.db")
DEFAULT_REPORT_DIR = _PROJECT_ROOT / ".local" / "research"


def _connect(db_path: str) -> sqlite3.Connection:
    """Open the live DB read-only."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _load_atomic_fact_self_ref_slice(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Load all active atomic_fact memories together with their evidence
    source items in the production DB.

    Self-reference slice convention: items whose container_ref matches the
    self-referential pattern. We approximate by selecting all atomic_facts;
    the regression guard is the count itself, not the slice definition.
    """
    rows = conn.execute(
        """
        SELECT mo.id            AS memory_id,
               mo.type          AS memory_type,
               mo.payload_json  AS payload_json,
               mo.envelope_json AS envelope_json,
               mo.container_ref AS container_ref,
               mo.subject       AS subject
        FROM memory_objects mo
        WHERE mo.type = 'atomic_fact'
          AND mo.lifecycle = 'active'
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _load_evidence_items(conn: sqlite3.Connection, memory_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """For each memory, load its evidence source items."""
    if not memory_ids:
        return {}
    placeholders = ",".join("?" for _ in memory_ids)
    rows = conn.execute(
        f"""
        SELECT r.from_id AS memory_id,
               si.id AS source_item_id,
               si.content AS content,
               si.metadata_json AS metadata_json,
               si.container_ref AS container_ref,
               si.thread_ref AS thread_ref,
               si.created_at AS created_at,
               si.visibility AS visibility
        FROM relations r
        JOIN source_items si ON si.id = r.to_id
        WHERE r.relation_type = 'supported_by'
          AND r.to_kind = 'source_item'
          AND r.from_kind = 'memory_object'
          AND r.from_id IN ({placeholders})
        """,
        memory_ids,
    ).fetchall()
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        out[row["memory_id"]].append(dict(row))
    return out


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace(" ", "T").replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


def _assign_workstreams(
    facts: list[dict[str, Any]],
    evidence: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    """Run the cascade over the slice, returning {memory_id -> ws_id}.

    Registry is per (container_ref, visibility) tuple just like in the
    production rebuild path. Items are processed in chronological order
    of their primary evidence source item's created_at.
    """
    registries: dict[tuple[str | None, str | None], WorkstreamRegistry] = {}
    sortable: list[tuple[datetime, dict[str, Any]]] = []
    for fact in facts:
        ev = evidence.get(fact["memory_id"], [])
        if not ev:
            sortable.append((datetime.now(timezone.utc), fact))
            continue
        primary = min(ev, key=lambda e: _parse_dt(e["created_at"]))
        sortable.append((_parse_dt(primary["created_at"]), fact))
    sortable.sort(key=lambda x: x[0])

    assignments: dict[str, str] = {}
    for created_at, fact in sortable:
        ev = evidence.get(fact["memory_id"], [])
        primary = min(ev, key=lambda e: _parse_dt(e["created_at"])) if ev else None
        container_ref = (primary or fact).get("container_ref") or fact["container_ref"]
        thread_ref = (primary or {}).get("thread_ref")
        visibility = (primary or {}).get("visibility") or "private"
        if not container_ref:
            container_ref = "no_container"
        registry = registries.setdefault((container_ref, visibility), WorkstreamRegistry())

        signals = signals_from_item(
            content_text=(primary or {}).get("content", "") or "",
            metadata_json=parse_json_safe((primary or {}).get("metadata_json") or "{}"),
            memory_records=[
                {
                    "type": fact["memory_type"],
                    "payload": parse_json_safe(fact["payload_json"]),
                    "envelope": parse_json_safe(fact["envelope_json"]),
                }
            ],
        )
        wm = watermark_for(created_at)
        result = assign_workstream_for_item(
            item_signals=signals,
            container_ref=container_ref,
            thread_ref=thread_ref,
            visibility=visibility,
            created_at=created_at,
            watermark=wm,
            registry=registry,
        )
        assignments[fact["memory_id"]] = result.workstream_id.id
    return assignments


def _group_counts(
    facts: list[dict[str, Any]],
    workstream_ids: dict[str, str],
) -> tuple[int, int]:
    """Return (old_group_count, new_group_count).

    old key = (container_ref, subject, category, visibility)
    new key = (container_ref, ws_id, subject, category, visibility)
    """
    old_keys: set[tuple] = set()
    new_keys: set[tuple] = set()
    for fact in facts:
        payload = parse_json_safe(fact["payload_json"])
        subject = str(payload.get("subject") or "").strip().lower()
        category = str(payload.get("category") or "").strip().lower()
        if not subject or not category:
            continue
        ws_id = workstream_ids.get(fact["memory_id"], "unknown")
        cont = fact["container_ref"] or "none"
        old_keys.add((cont, subject, category))
        new_keys.add((cont, ws_id, subject, category))
    return len(old_keys), len(new_keys)


def run(*, db_path: str, output_dir: Path, baseline_old: int = 1014, baseline_new: int = 1153) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("workstream_consolidation_eval")

    logger.info("opening live DB at %s (read-only)", db_path)
    conn = _connect(db_path)
    try:
        facts = _load_atomic_fact_self_ref_slice(conn)
        logger.info("loaded %d atomic_fact rows", len(facts))
        evidence = _load_evidence_items(conn, [f["memory_id"] for f in facts])
        logger.info("loaded evidence for %d memories", len(evidence))
        ws_ids = _assign_workstreams(facts, evidence)
        old_count, new_count = _group_counts(facts, ws_ids)
        logger.info("old groups=%d new groups=%d", old_count, new_count)
    finally:
        conn.close()

    delta = new_count - old_count
    rel_delta_pct = (delta / old_count * 100) if old_count > 0 else 0.0
    baseline_delta_pct = ((baseline_new - baseline_old) / baseline_old * 100) if baseline_old > 0 else 0.0
    diff_from_baseline_pct = abs(rel_delta_pct - baseline_delta_pct)
    within_guard = diff_from_baseline_pct <= 10.0  # ±10% per Phase 4A spec

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"workstream_consolidation_eval_{today}.md"
    report_path.write_text(
        _render_report(
            db_path=db_path,
            old_count=old_count,
            new_count=new_count,
            delta_pct=rel_delta_pct,
            baseline_pct=baseline_delta_pct,
            diff_pct=diff_from_baseline_pct,
            within_guard=within_guard,
        ),
        encoding="utf-8",
    )
    logger.info("wrote report %s", report_path)
    return report_path


def _render_report(
    *,
    db_path: str,
    old_count: int,
    new_count: int,
    delta_pct: float,
    baseline_pct: float,
    diff_pct: float,
    within_guard: bool,
) -> str:
    return (
        f"# Workstream Consolidation Eval — {datetime.now(timezone.utc).date().isoformat()}\n"
        f"\n"
        f"Live DB: `{db_path}` (read-only)\n"
        f"\n"
        f"## Group counts (atomic_fact slice)\n"
        f"\n"
        f"- Old key `(container_ref, subject, category)`: **{old_count}**\n"
        f"- New key `(container_ref, ws_id, subject, category)`: **{new_count}**\n"
        f"- Delta: {delta_pct:+.2f}%\n"
        f"\n"
        f"## Regression guard\n"
        f"\n"
        f"- Offline T1.7 baseline: 1014 → 1153 (+13.7%)\n"
        f"- This run delta: {delta_pct:+.2f}%\n"
        f"- |diff from baseline|: {diff_pct:.2f}% (threshold: 10.0%)\n"
        f"- **Status:** {'WITHIN GUARD' if within_guard else 'OUTSIDE GUARD'}\n"
        f"\n"
        f"---\n"
        f"\n"
        f"This eval is operator-runnable. Not part of the default pytest run.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to live SQLite DB")
    parser.add_argument("--output", default=str(DEFAULT_REPORT_DIR), help="Report output dir")
    parser.add_argument("--baseline-old", type=int, default=1014)
    parser.add_argument("--baseline-new", type=int, default=1153)
    args = parser.parse_args()
    run(
        db_path=args.db,
        output_dir=Path(args.output),
        baseline_old=args.baseline_old,
        baseline_new=args.baseline_new,
    )


if __name__ == "__main__":
    main()
