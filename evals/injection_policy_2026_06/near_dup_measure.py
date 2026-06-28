"""Near-duplicate measurement eval for thread-derived decisions/investigations.

Spec: docs/specs/2026-06-28-thread-near-dup-supersession.md
Companion: evals/injection_policy_2026_06/analyze.py (Phase 0 of the
abstention plan — this script is the write-path quality analogue).

Reads the local Pallium SQLite database (read-only) and reports the
near-duplicate rate among thread-derived
``decision`` / ``investigation_outcome`` memories at multiple similarity
thresholds, broken down by type, container, and source_id (thread).

Useful for:

- before/after measurement when landing the 2026-06-28 near-dup
  supersession fix (or any future supersession-logic change);
- tuning ``NEAR_DUP_THRESHOLD`` against real data instead of guessing;
- spotting threads with pathological accumulation (one source_id ->
  many active near-paraphrases).

Run:
    python -m evals.injection_policy_2026_06.near_dup_measure
    python -m evals.injection_policy_2026_06.near_dup_measure --output report.json
    python -m evals.injection_policy_2026_06.near_dup_measure --db /path/pallium.db
    python -m evals.injection_policy_2026_06.near_dup_measure --thresholds 0.7,0.8,0.85,0.9

Output: stdout always, plus optional JSON. Reports per-bucket counts and
the top-N noisiest source_ids so the reader can spot-check.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# Path setup so we can reuse repo helpers without installing the package.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.text import normalize_for_index  # noqa: E402


DEFAULT_DB = os.path.expanduser("~/.pallium/data/pallium.db")
DEFAULT_THRESHOLDS = (0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00)


@dataclass
class Row:
    id: str
    type: str
    lifecycle: str
    container_ref: str
    source_id: str
    norm_text: str
    canonical_key: str
    created_at: str


@dataclass
class Bucket:
    """A type+container partition; pairs are within-bucket only."""
    type: str
    container_ref: str
    rows: list[Row] = field(default_factory=list)


def _load_rows(db_path: str) -> list[Row]:
    """Read all thread-derived decisions/investigations (any lifecycle)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, type, lifecycle, container_ref, payload_json, created_at
        FROM memory_objects
        WHERE type IN ('decision', 'investigation_outcome')
        ORDER BY created_at ASC
        """
    )
    out: list[Row] = []
    for (mid, mtype, lifecycle, container_ref, payload_json, created_at) in cur.fetchall():
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except json.JSONDecodeError:
            continue
        if payload.get("source_type") != "thread_detection":
            continue
        text = payload.get("decision") or payload.get("investigation_outcome") or ""
        ck = str(payload.get("canonical_key") or "").strip()
        if not text or not ck:
            continue
        out.append(Row(
            id=mid,
            type=mtype,
            lifecycle=lifecycle,
            container_ref=container_ref or "",
            source_id=str(payload.get("source_id") or ""),
            norm_text=normalize_for_index(text),
            canonical_key=ck,
            created_at=str(created_at),
        ))
    con.close()
    return out


def _pair_sim(a: Row, b: Row) -> float:
    """Similarity over the normalized canonical_key — same key used by the
    supersession-hint comprehension in ``build_thread_summary``."""
    if a.canonical_key == b.canonical_key:
        return 1.0
    return SequenceMatcher(None, a.canonical_key, b.canonical_key).ratio()


def _count_pairs(
    rows: list[Row],
    *,
    thresholds: tuple[float, ...],
    active_only: bool,
) -> dict[str, Any]:
    """Per-(type, container) bucket pair counts.

    A "pair" is an unordered pair of rows in the same bucket. For each
    threshold, count pairs whose sim>=threshold. Also break down per type
    and per source_id (thread). Quadratic over each bucket; tractable
    because total rows is ~thousands.
    """
    if active_only:
        rows = [r for r in rows if r.lifecycle == "active"]

    by_bucket: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r in rows:
        by_bucket[(r.type, r.container_ref)].append(r)

    total_pairs = 0
    threshold_hits: dict[float, int] = {t: 0 for t in thresholds}
    per_type_total: dict[str, int] = defaultdict(int)
    per_type_hits: dict[str, dict[float, int]] = defaultdict(
        lambda: {t: 0 for t in thresholds}
    )
    exact_pairs = 0  # sim == 1.0 (already collapsable by exact-equality path)
    same_source_pairs = 0
    same_source_threshold_hits: dict[float, int] = {t: 0 for t in thresholds}

    for (mtype, container_ref), bucket in by_bucket.items():
        n = len(bucket)
        for i in range(n):
            for j in range(i + 1, n):
                total_pairs += 1
                per_type_total[mtype] += 1
                a, b = bucket[i], bucket[j]
                sim = _pair_sim(a, b)
                if a.source_id == b.source_id and a.source_id:
                    same_source_pairs += 1
                if sim >= 1.0:
                    exact_pairs += 1
                for t in thresholds:
                    if sim >= t:
                        threshold_hits[t] += 1
                        per_type_hits[mtype][t] += 1
                        if a.source_id == b.source_id and a.source_id:
                            same_source_threshold_hits[t] += 1

    return {
        "rows_considered": len(rows),
        "total_pairs": total_pairs,
        "exact_pairs": exact_pairs,
        "same_source_pairs": same_source_pairs,
        "threshold_hits": {f"{t:.2f}": threshold_hits[t] for t in thresholds},
        "same_source_threshold_hits": {
            f"{t:.2f}": same_source_threshold_hits[t] for t in thresholds
        },
        "per_type_total": dict(per_type_total),
        "per_type_threshold_hits": {
            mtype: {f"{t:.2f}": cnts[t] for t in thresholds}
            for mtype, cnts in per_type_hits.items()
        },
    }


def _per_source_top_noise(
    rows: list[Row],
    *,
    threshold: float,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Top-N (source_id, type) buckets by active near-dup pair count.

    Surfaces noisy threads — the 48-investigation thread that motivated
    the 2026-06-28 fix lives here.
    """
    active = [r for r in rows if r.lifecycle == "active"]
    by_source: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r in active:
        if r.source_id:
            by_source[(r.source_id, r.type)].append(r)

    out: list[dict[str, Any]] = []
    for (source_id, mtype), items in by_source.items():
        n = len(items)
        if n < 2:
            continue
        dup_pairs = 0
        for i in range(n):
            for j in range(i + 1, n):
                if _pair_sim(items[i], items[j]) >= threshold:
                    dup_pairs += 1
        if dup_pairs == 0:
            continue
        out.append({
            "source_id": source_id,
            "type": mtype,
            "active_count": n,
            "near_dup_pairs": dup_pairs,
            "container_ref": items[0].container_ref,
        })
    out.sort(key=lambda d: (-d["near_dup_pairs"], -d["active_count"]))
    return out[:top_n]


def _simulate_fix_c(rows: list[Row], threshold: float) -> dict[str, Any]:
    """Simulate Fix C (chronological in-thread sim>=threshold) on active rows.

    For each (source_id, type), walk chronologically and supersede a new row
    when sim>=threshold against any winner already kept. Reports counts and
    per-type breakdown.
    """
    active = [r for r in rows if r.lifecycle == "active"]
    by_source: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r in active:
        if r.source_id:
            by_source[(r.source_id, r.type)].append(r)
    for items in by_source.values():
        items.sort(key=lambda r: (r.created_at, r.id))

    demoted = 0
    kept = 0
    demoted_by_type: dict[str, int] = defaultdict(int)
    kept_by_type: dict[str, int] = defaultdict(int)
    for (source_id, mtype), items in by_source.items():
        winners: list[Row] = []
        for item in items:
            superseded = any(
                _pair_sim(prior, item) >= threshold for prior in winners
            )
            if superseded:
                demoted += 1
                demoted_by_type[mtype] += 1
            else:
                winners.append(item)
                kept += 1
                kept_by_type[mtype] += 1
    return {
        "threshold": threshold,
        "demoted": demoted,
        "kept": kept,
        "demoted_by_type": dict(demoted_by_type),
        "kept_by_type": dict(kept_by_type),
    }


def _build_report(db_path: str, thresholds: tuple[float, ...]) -> dict[str, Any]:
    rows = _load_rows(db_path)
    report: dict[str, Any] = {
        "db": db_path,
        "thresholds": list(thresholds),
        "row_counts": {
            "thread_derived_total": len(rows),
            "thread_derived_active": sum(1 for r in rows if r.lifecycle == "active"),
            "thread_derived_superseded": sum(1 for r in rows if r.lifecycle == "superseded"),
            "thread_derived_investigation_outcome_active": sum(
                1 for r in rows if r.type == "investigation_outcome" and r.lifecycle == "active"
            ),
            "thread_derived_decision_active": sum(
                1 for r in rows if r.type == "decision" and r.lifecycle == "active"
            ),
        },
        "all_pairs": _count_pairs(rows, thresholds=thresholds, active_only=False),
        "active_pairs": _count_pairs(rows, thresholds=thresholds, active_only=True),
        "fix_c_simulation": {
            f"{t:.2f}": _simulate_fix_c(rows, t) for t in thresholds
        },
        "noisy_threads_at_0_85": _per_source_top_noise(rows, threshold=0.85, top_n=15),
    }
    return report


def _print_summary(report: dict[str, Any]) -> None:
    rc = report["row_counts"]
    print(f"DB: {report['db']}")
    print(f"Thread-derived rows: total={rc['thread_derived_total']} "
          f"active={rc['thread_derived_active']} "
          f"superseded={rc['thread_derived_superseded']}")
    print(f"  active investigation_outcome: {rc['thread_derived_investigation_outcome_active']}")
    print(f"  active decision: {rc['thread_derived_decision_active']}")

    def _print_pairs(label: str, block: dict[str, Any]) -> None:
        print(f"\n{label} (rows={block['rows_considered']}, "
              f"total_pairs={block['total_pairs']}, exact_pairs={block['exact_pairs']})")
        print("  threshold | pairs | rate    | same-source-pairs")
        for t_str, hits in block["threshold_hits"].items():
            ss_hits = block["same_source_threshold_hits"].get(t_str, 0)
            rate = (100.0 * hits / block["total_pairs"]) if block["total_pairs"] else 0.0
            print(f"  {t_str}     | {hits:5d} | {rate:5.2f}% | {ss_hits:5d}")

    _print_pairs("All-pairs (active+superseded)", report["all_pairs"])
    _print_pairs("Active-only", report["active_pairs"])

    print("\nFix C simulation (active rows, chronological in-thread, by threshold):")
    print("  threshold | demoted | kept | demoted_by_type")
    for t_str, sim in report["fix_c_simulation"].items():
        print(f"  {t_str}     | {sim['demoted']:7d} | {sim['kept']:4d} | {sim['demoted_by_type']}")

    print("\nNoisy threads at threshold 0.85 (top 15):")
    for entry in report["noisy_threads_at_0_85"]:
        print(f"  source_id={entry['source_id']}  type={entry['type']}  "
              f"active={entry['active_count']}  near_dup_pairs={entry['near_dup_pairs']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=DEFAULT_DB, help=f"SQLite DB path (default: {DEFAULT_DB})")
    parser.add_argument("--output", default=None, help="Optional JSON output path")
    parser.add_argument(
        "--thresholds",
        default=",".join(str(t) for t in DEFAULT_THRESHOLDS),
        help="Comma-separated similarity thresholds",
    )
    args = parser.parse_args(argv)

    try:
        thresholds = tuple(float(s.strip()) for s in args.thresholds.split(",") if s.strip())
    except ValueError as exc:
        parser.error(f"--thresholds must be comma-separated floats: {exc}")

    if not os.path.exists(args.db):
        parser.error(f"DB not found: {args.db}")

    report = _build_report(args.db, thresholds)
    _print_summary(report)
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, default=str))
        print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
