"""Phase 6 measurement script — proactive-precision rollups.

See: docs/specs/2026-06-27-injection-policy-abstention.md (Phase 6).

Phase 6 is the measurement window — 4 weeks of live data, then a
decision. This script is the analysis surface that turns the
memory_usage_audit + query_audit_log + memory_feedback tables into
the metrics the spec asks for:

1. Per-type proactive-precision rate, measured by **usage**:
   among proactive injections (trigger_origin IS NULL), what fraction
   of rows ended up with referenced_in_next_turn=true after the
   populator ran?

2. Per-type proactive-precision rate, measured by **rating**:
   among proactive injections, what fraction of rated rows ended up
   with rating=relevant? (Phase 1 baseline.)

3. Per-trigger on-demand hit rate: for each non-NULL trigger_origin,
   how often did the agent actually use the injected memory? If a
   trigger fires often but produces 0% usage, it should be retired.

4. On-demand-type discovery rate: for types that were demoted to
   non-proactive modes (Phase 3b), how often were they retrieved at
   all by a trigger? If never, the type is dead code and should be
   deleted (per Phase 6 decision gate).

Phase 6 is data-driven: this script's job is to surface the numbers,
not to make policy decisions.

Run:
    python -m evals.injection_policy_2026_06.phase6_measurement
    python -m evals.injection_policy_2026_06.phase6_measurement \\
        --output evals/injection_policy_2026_06/phase6_measurement_<date>.json
    python -m evals.injection_policy_2026_06.phase6_measurement \\
        --since 2026-06-27T00:00:00Z

Pre-requisites for meaningful output:
- Phase 0.5 audit instrumentation has been live for the measurement window.
- Phase 4 trigger hooks are deployed (post_tool_use.py).
- Phase 5b populator hook is deployed and writing
  memory_usage_audit.referenced_in_next_turn.
- The measurement window has accumulated enough rows per type to
  produce useful sample sizes (rule of thumb: >=30 per cell).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from evals.injection_policy_2026_06.analyze import (  # noqa: E402
    DEFAULT_DB_PATH,
    open_db_readonly,
)


# ---------------------------------------------------------------------------
# Data loading (read-only)
# ---------------------------------------------------------------------------


def load_usage_audit_rows(
    conn: sqlite3.Connection,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Pull memory_usage_audit rows; optionally filter by created_at >= since."""
    sql = (
        "SELECT id, query_audit_log_id, memory_object_id, memory_type, "
        "       container_ref, thread_ref, trigger_origin, "
        "       referenced_in_next_turn, reference_kind, "
        "       observation_window_turns, created_at, populated_at "
        "FROM memory_usage_audit "
    )
    params: dict[str, Any] = {}
    if since:
        sql += "WHERE created_at >= :since "
        params["since"] = since
    sql += "ORDER BY created_at ASC, id ASC"
    cur = conn.execute(sql, params)
    return [dict(row) for row in cur.fetchall()]


def load_feedback_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT memory_object_id, query_audit_log_id, rating "
        "FROM memory_feedback "
        "WHERE rating IN ('relevant', 'not_relevant') "
        "  AND query_audit_log_id IS NOT NULL"
    )
    return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Pure rollup logic
# ---------------------------------------------------------------------------


@dataclass
class CellStats:
    total: int = 0
    populated: int = 0
    referenced: int = 0
    rated_relevant: int = 0
    rated_bad: int = 0

    def usage_rate(self) -> float | None:
        if self.populated == 0:
            return None
        return self.referenced / self.populated

    def rating_precision(self) -> float | None:
        denom = self.rated_relevant + self.rated_bad
        if denom == 0:
            return None
        return self.rated_relevant / denom


def rollup_proactive_usage(
    usage_rows: list[dict[str, Any]],
    feedback_index: dict[tuple[str, str], str],
) -> dict[str, dict[str, Any]]:
    """Per-memory-type proactive (trigger_origin IS NULL) precision.

    Returns: {memory_type: {usage_rate, rating_precision, n_total,
    n_populated, n_referenced, n_rated}}.
    """
    cells: dict[str, CellStats] = defaultdict(CellStats)
    for row in usage_rows:
        if row.get("trigger_origin") is not None:
            continue
        mtype = row.get("memory_type") or "unknown"
        c = cells[mtype]
        c.total += 1
        if row.get("populated_at") is not None:
            c.populated += 1
            if row.get("referenced_in_next_turn"):
                c.referenced += 1
        key = (row.get("memory_object_id"), row.get("query_audit_log_id"))
        rating = feedback_index.get(key)
        if rating == "relevant":
            c.rated_relevant += 1
        elif rating == "not_relevant":
            c.rated_bad += 1
    out: dict[str, dict[str, Any]] = {}
    for mtype, stats in sorted(cells.items()):
        out[mtype] = {
            "n_total": stats.total,
            "n_populated": stats.populated,
            "n_referenced": stats.referenced,
            "usage_rate": stats.usage_rate(),
            "n_rated_relevant": stats.rated_relevant,
            "n_rated_bad": stats.rated_bad,
            "rating_precision": stats.rating_precision(),
        }
    return out


def rollup_by_trigger(
    usage_rows: list[dict[str, Any]],
    feedback_index: dict[tuple[str, str], str],
) -> dict[str, dict[str, Any]]:
    """Per-trigger_origin breakdown (including NULL = proactive default)."""
    by_trigger: dict[str | None, CellStats] = defaultdict(CellStats)
    for row in usage_rows:
        origin = row.get("trigger_origin")
        c = by_trigger[origin]
        c.total += 1
        if row.get("populated_at") is not None:
            c.populated += 1
            if row.get("referenced_in_next_turn"):
                c.referenced += 1
        key = (row.get("memory_object_id"), row.get("query_audit_log_id"))
        rating = feedback_index.get(key)
        if rating == "relevant":
            c.rated_relevant += 1
        elif rating == "not_relevant":
            c.rated_bad += 1
    out: dict[str, dict[str, Any]] = {}
    for origin, stats in by_trigger.items():
        out[origin or "(proactive_default)"] = {
            "n_total": stats.total,
            "n_populated": stats.populated,
            "n_referenced": stats.referenced,
            "usage_rate": stats.usage_rate(),
            "rating_precision": stats.rating_precision(),
        }
    return out


def rollup_demoted_type_discovery(
    usage_rows: list[dict[str, Any]],
    demoted_types: tuple[str, ...] = (
        "investigation_outcome", "thread_summary", "fact_summary", "task_checkpoint",
    ),
) -> dict[str, dict[str, Any]]:
    """For each demoted type, count discovery via trigger vs no discovery.

    A type that never appears with a non-NULL trigger_origin is a
    candidate for permanent deletion (Phase 6 decision gate).
    """
    out: dict[str, dict[str, Any]] = {}
    for mtype in demoted_types:
        by_origin: dict[str | None, int] = defaultdict(int)
        for row in usage_rows:
            if row.get("memory_type") != mtype:
                continue
            by_origin[row.get("trigger_origin")] += 1
        proactive = by_origin.get(None, 0)
        triggered = sum(v for k, v in by_origin.items() if k is not None)
        out[mtype] = {
            "n_proactive_injections": proactive,
            "n_triggered_injections": triggered,
            "trigger_breakdown": {
                (k or "(null)"): v for k, v in by_origin.items()
            },
        }
    return out


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def build_report(
    usage_rows: list[dict[str, Any]],
    feedback_rows: list[dict[str, Any]],
    since: str | None,
) -> dict[str, Any]:
    feedback_index = {
        (row["memory_object_id"], row["query_audit_log_id"]): row["rating"]
        for row in feedback_rows
    }
    return {
        "spec": "docs/specs/2026-06-27-injection-policy-abstention.md",
        "phase": "6 — measurement",
        "window": {
            "since": since,
            "n_usage_rows": len(usage_rows),
            "n_feedback_rows": len(feedback_rows),
            "n_populated_rows": sum(
                1 for r in usage_rows if r.get("populated_at") is not None
            ),
        },
        "per_type_proactive": rollup_proactive_usage(
            usage_rows, feedback_index
        ),
        "per_trigger": rollup_by_trigger(usage_rows, feedback_index),
        "demoted_type_discovery": rollup_demoted_type_discovery(usage_rows),
    }


def format_text_summary(report: dict[str, Any]) -> str:
    lines: list[str] = ["=== Phase 6 — Measurement Window Rollup ==="]
    w = report["window"]
    lines.append(
        f"since={w['since']}  n_usage_rows={w['n_usage_rows']}  "
        f"populated={w['n_populated_rows']}  n_feedback={w['n_feedback_rows']}"
    )
    lines.append("")
    lines.append("Per-type proactive precision (trigger_origin IS NULL):")
    for mtype, info in report["per_type_proactive"].items():
        usage = info["usage_rate"]
        rating = info["rating_precision"]
        usage_str = f"{usage:.2%}" if usage is not None else "n/a"
        rating_str = f"{rating:.2%}" if rating is not None else "n/a"
        lines.append(
            f"  {mtype:<24} n_total={info['n_total']:<5} "
            f"populated={info['n_populated']:<5} "
            f"usage={usage_str:<7} rating={rating_str:<7} "
            f"rated={info['n_rated_relevant']}/{info['n_rated_relevant']+info['n_rated_bad']}"
        )
    lines.append("")
    lines.append("Per-trigger usage/rating:")
    for trigger, info in report["per_trigger"].items():
        usage = info["usage_rate"]
        usage_str = f"{usage:.2%}" if usage is not None else "n/a"
        lines.append(
            f"  {trigger:<28} n_total={info['n_total']:<5} "
            f"populated={info['n_populated']:<5} usage={usage_str}"
        )
    lines.append("")
    lines.append("Demoted-type discovery (trigger vs proactive):")
    for mtype, info in report["demoted_type_discovery"].items():
        lines.append(
            f"  {mtype:<24} proactive={info['n_proactive_injections']:<5} "
            f"triggered={info['n_triggered_injections']:<5}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 6 measurement rollup — per-type proactive precision, "
            "per-trigger usage rates, and demoted-type discovery."
        )
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH,
        help="Path to pallium.db",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="ISO-8601 cutoff for created_at (e.g. 2026-06-27T00:00:00).",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Optional JSON output path.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="JSON-only on stdout; suppress text summary.",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 2

    conn = open_db_readonly(args.db)
    try:
        usage_rows = load_usage_audit_rows(conn, since=args.since)
        feedback_rows = load_feedback_rows(conn)
    finally:
        conn.close()

    report = build_report(usage_rows, feedback_rows, since=args.since)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str))
        print(f"Wrote report -> {args.output}", file=sys.stderr)

    if args.quiet:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True, default=str))
        sys.stdout.write("\n")
    else:
        print(format_text_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
