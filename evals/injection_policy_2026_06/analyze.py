"""Phase 0 snapshot analysis for the injection-policy abstention spec.

See: docs/specs/2026-06-27-injection-policy-abstention.md

Reads the local Pallium SQLite database, joins memory_feedback to
query_audit_log on (memory_object_id, query_audit_log_id), extracts the
per-block result `score` from injected_blocks_json, and computes:

- per-container bad-injection rate
- per-type score distributions (min/p25/median/p75/max) split by rating
- per-type precision/recall frontier
- per-type ">=70% precision" threshold + kept counts + recall
- the proposed-policy overall precision/recall numbers
- a sanity-check report applying the same thresholds to `routing_score`

Reproducibility: deterministic ordering by (created_at, feedback id).
Read-only (URI mode=ro). No production code is touched.

`majority_rating` and `FeedbackEntry` from
`evals/retrieval_ablation/evaluate.py` are imported here but NOT used by
Phase 0. Phase 0 reports per-rating counts and treats each rating as a
separate event so duplicate ratings on the same (memory_object_id,
query_audit_log_id) pair surface in the distributions. Phase 1's holdout
work will need a single rating per memory and is where majority_rating
applies. The import is kept as a contract anchor for the spec.

Run:
    python -m evals.injection_policy_2026_06.analyze
    python -m evals.injection_policy_2026_06.analyze --output report.json
    python -m evals.injection_policy_2026_06.analyze --db /path/pallium.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Path setup so we can reuse repo helpers without installing the package.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from evals.retrieval_ablation.evaluate import (  # noqa: E402
    FeedbackEntry,
    build_feedback_index,
    majority_rating,
)


DEFAULT_DB_PATH = Path.home() / ".pallium" / "data" / "pallium.db"

# Proposed policy thresholds from spec (these match the analysis numbers we
# expect to reproduce against the snapshot DB).
PROPOSED_POLICY: dict[str, float] = {
    "constraint_memory": 20.0,
    "decision": 22.0,
    "task_checkpoint": 14.0,
}

# Precision target used to derive per-type "best" thresholds.
PRECISION_TARGET = 0.70


# ---------------------------------------------------------------------------
# I/O layer (impure)
# ---------------------------------------------------------------------------


def open_db_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the local DB in read-only URI mode. Defensive: never write."""
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_joined_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Load feedback rows joined to their audit log row.

    Deterministic ordering: (mf.created_at ASC, mf.id ASC).
    Filters out feedback with no audit join and rows without
    injected_blocks_json. Does NOT filter on rating or memory_type — those
    are surface-level enums that the compute layer handles.
    """
    cur = conn.execute(
        """
        SELECT
            mf.id              AS feedback_id,
            mf.memory_object_id,
            mf.rating,
            mf.memory_type     AS feedback_memory_type,
            mf.container_ref   AS feedback_container_ref,
            mf.query_audit_log_id,
            mf.created_at      AS feedback_created_at,
            mf.query_context,
            qa.container_ref   AS audit_container_ref,
            qa.injected_blocks_json,
            qa.candidate_scores_json,
            qa.decision_reason
        FROM memory_feedback mf
        JOIN query_audit_log qa ON qa.id = mf.query_audit_log_id
        WHERE qa.injected_blocks_json IS NOT NULL
        ORDER BY mf.created_at ASC, mf.id ASC
        """
    )
    return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Compute layer (pure)
# ---------------------------------------------------------------------------


@dataclass
class InjectionRecord:
    """One rated injection event with the resolved per-block + per-candidate scores."""
    rating: str  # "relevant" | "not_relevant" (other values dropped upstream)
    memory_type: str
    container_ref: str
    block_score: float | None       # injected_blocks_json[*].score
    retrieval_source: str | None     # injected_blocks_json[*].retrieval_source
    routing_score: float | None     # candidate_scores_json[*].routing_score
    lexical_score: float | None     # candidate_scores_json[*].lexical_score
    vector_score: float | None      # candidate_scores_json[*].vector_score


@dataclass
class SkipCounts:
    no_block_match: int = 0
    no_block_score: int = 0
    other_rating: int = 0


_VALID_RATINGS: tuple[str, ...] = ("relevant", "not_relevant")


def _find_in_list(items: list[dict[str, Any]] | None, mid: str) -> dict[str, Any] | None:
    if not items:
        return None
    for item in items:
        if isinstance(item, dict) and item.get("memory_object_id") == mid:
            return item
    return None


def extract_records(
    joined_rows: list[dict[str, Any]],
) -> tuple[list[InjectionRecord], SkipCounts]:
    """Project (row, injected block, candidate) into typed records.

    Defensive: tolerates missing fields and unknown rating values.
    """
    skips = SkipCounts()
    records: list[InjectionRecord] = []

    for row in joined_rows:
        rating = row.get("rating")
        if rating not in _VALID_RATINGS:
            skips.other_rating += 1
            continue

        mid = row.get("memory_object_id")
        if not mid:
            skips.no_block_match += 1
            continue

        try:
            blocks = json.loads(row.get("injected_blocks_json") or "[]")
        except (TypeError, ValueError):
            blocks = []
        try:
            candidates_raw = row.get("candidate_scores_json")
            candidates = json.loads(candidates_raw) if candidates_raw else []
        except (TypeError, ValueError):
            candidates = []

        block = _find_in_list(blocks, mid)
        cand = _find_in_list(candidates, mid)
        if block is None and cand is None:
            skips.no_block_match += 1
            continue

        block_score = block.get("score") if block else None
        if block_score is None:
            # Required by the policy — count separately. We still keep the
            # record for routing-score sanity checks, but block_score=None
            # excludes it from the score-based policy.
            skips.no_block_score += 1

        record = InjectionRecord(
            rating=rating,
            memory_type=(
                (block.get("memory_type") if block else None)
                or (cand.get("memory_type") if cand else None)
                or row.get("feedback_memory_type")
                or "unknown"
            ),
            container_ref=(
                row.get("feedback_container_ref")
                or row.get("audit_container_ref")
                or ""
            ),
            block_score=float(block_score) if block_score is not None else None,
            retrieval_source=(block.get("retrieval_source") if block else None),
            routing_score=(
                float(cand["routing_score"])
                if cand and cand.get("routing_score") is not None
                else None
            ),
            lexical_score=(
                float(cand["lexical_score"])
                if cand and cand.get("lexical_score") is not None
                else None
            ),
            vector_score=(
                float(cand["vector_score"])
                if cand and cand.get("vector_score") is not None
                else None
            ),
        )
        records.append(record)

    return records, skips


def _summary(vals: list[float]) -> dict[str, float] | None:
    if not vals:
        return None
    vs = sorted(vals)
    n = len(vs)
    return {
        "n": n,
        "min": vs[0],
        "p25": vs[n // 4],
        "median": statistics.median(vs),
        "p75": vs[(3 * n) // 4],
        "max": vs[-1],
        "mean": round(statistics.mean(vs), 3),
    }


def compute_container_rates(records: list[InjectionRecord]) -> dict[str, dict[str, Any]]:
    by_container: dict[str, dict[str, int]] = defaultdict(lambda: {"relevant": 0, "not_relevant": 0})
    for r in records:
        by_container[r.container_ref][r.rating] += 1
    out: dict[str, dict[str, Any]] = {}
    for container, counts in sorted(by_container.items()):
        total = counts["relevant"] + counts["not_relevant"]
        if total == 0:
            continue
        out[container] = {
            "total": total,
            "relevant": counts["relevant"],
            "not_relevant": counts["not_relevant"],
            "precision": counts["relevant"] / total,
            "bad_rate": counts["not_relevant"] / total,
        }
    return out


def compute_type_distributions(
    records: list[InjectionRecord], score_field: str = "block_score"
) -> dict[str, dict[str, Any]]:
    by_type: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"relevant": [], "not_relevant": []}
    )
    for r in records:
        if r.rating not in _VALID_RATINGS:
            continue
        score = getattr(r, score_field)
        if score is None:
            continue
        by_type[r.memory_type][r.rating].append(score)
    out: dict[str, dict[str, Any]] = {}
    for mtype, buckets in sorted(by_type.items()):
        out[mtype] = {
            "relevant": _summary(buckets["relevant"]),
            "not_relevant": _summary(buckets["not_relevant"]),
            "coverage": {
                "n_relevant": len(buckets["relevant"]),
                "n_bad": len(buckets["not_relevant"]),
                "total": len(buckets["relevant"]) + len(buckets["not_relevant"]),
            },
        }
    return out


def compute_pr_frontier(
    records: list[InjectionRecord], score_field: str = "block_score"
) -> dict[str, dict[str, Any]]:
    """For each type, return list of (threshold, precision, recall, kept_rel, kept_bad)."""
    out: dict[str, dict[str, Any]] = {}
    by_type: dict[str, list[InjectionRecord]] = defaultdict(list)
    for r in records:
        if r.rating not in _VALID_RATINGS:
            continue
        if getattr(r, score_field) is None:
            continue
        by_type[r.memory_type].append(r)

    for mtype, items in sorted(by_type.items()):
        scores = sorted({getattr(r, score_field) for r in items})
        rel_total = sum(1 for r in items if r.rating == "relevant")
        frontier: list[dict[str, Any]] = []
        for thr in scores:
            kept = [r for r in items if getattr(r, score_field) >= thr]
            kept_rel = sum(1 for r in kept if r.rating == "relevant")
            kept_bad = sum(1 for r in kept if r.rating == "not_relevant")
            denom = kept_rel + kept_bad
            if denom == 0:
                break
            frontier.append({
                "threshold": thr,
                "kept_total": denom,
                "kept_relevant": kept_rel,
                "kept_bad": kept_bad,
                "precision": kept_rel / denom,
                "recall": (kept_rel / rel_total) if rel_total else 0.0,
            })
        out[mtype] = {
            "n_relevant": rel_total,
            "n_total": len(items),
            "frontier": frontier,
        }
    return out


def derive_target_thresholds(
    pr_frontier: dict[str, dict[str, Any]], precision_target: float = PRECISION_TARGET
) -> dict[str, dict[str, Any]]:
    """For each type, find lowest threshold reaching precision_target.

    Among thresholds meeting the precision target, prefer the one with
    the highest recall (= lowest threshold). If none reach the target,
    return None for threshold.
    """
    out: dict[str, dict[str, Any]] = {}
    for mtype, info in pr_frontier.items():
        best = None
        for point in info["frontier"]:
            if point["precision"] >= precision_target and point["kept_relevant"] >= 1:
                if best is None or point["recall"] > best["recall"]:
                    best = point
        out[mtype] = {
            "n_relevant": info["n_relevant"],
            "n_total": info["n_total"],
            "target_precision": precision_target,
            "best": best,
        }
    return out


def apply_proposed_policy(
    records: list[InjectionRecord],
    policy: dict[str, float],
    score_field: str = "block_score",
) -> dict[str, Any]:
    """Apply per-type score thresholds and compute overall precision/recall.

    Types not in the policy are excluded from the proactive set entirely
    (= moved to on-demand). The reported "kept" set is what would survive
    as proactive injections under this policy.
    """
    total_relevant = 0
    total_bad = 0
    kept_relevant = 0
    kept_bad = 0
    excluded_relevant = 0
    excluded_bad = 0
    per_type: dict[str, dict[str, int]] = defaultdict(lambda: {
        "relevant": 0, "not_relevant": 0,
        "kept_relevant": 0, "kept_bad": 0,
    })

    for r in records:
        if r.rating not in _VALID_RATINGS:
            continue
        total_relevant += int(r.rating == "relevant")
        total_bad += int(r.rating == "not_relevant")
        bucket = per_type[r.memory_type]
        bucket["relevant"] += int(r.rating == "relevant")
        bucket["not_relevant"] += int(r.rating == "not_relevant")

        thr = policy.get(r.memory_type)
        score = getattr(r, score_field)
        keeps = thr is not None and score is not None and score >= thr
        if keeps:
            if r.rating == "relevant":
                kept_relevant += 1
                bucket["kept_relevant"] += 1
            else:
                kept_bad += 1
                bucket["kept_bad"] += 1
        else:
            if r.rating == "relevant":
                excluded_relevant += 1
            else:
                excluded_bad += 1

    overall = {
        "score_field": score_field,
        "policy": policy,
        "total_relevant_original": total_relevant,
        "total_bad_original": total_bad,
        "base_precision": (total_relevant / (total_relevant + total_bad))
        if (total_relevant + total_bad)
        else 0.0,
        "kept_total": kept_relevant + kept_bad,
        "kept_relevant": kept_relevant,
        "kept_bad": kept_bad,
        "new_precision": (kept_relevant / (kept_relevant + kept_bad))
        if (kept_relevant + kept_bad)
        else None,
        "recall_of_relevant_signal": (kept_relevant / total_relevant)
        if total_relevant
        else None,
        "bad_eliminated_fraction": (excluded_bad / total_bad) if total_bad else None,
    }
    overall["per_type"] = dict(per_type)
    return overall


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def build_report(
    records: list[InjectionRecord],
    skips: SkipCounts,
) -> dict[str, Any]:
    pr_block = compute_pr_frontier(records, score_field="block_score")
    pr_routing = compute_pr_frontier(records, score_field="routing_score")
    return {
        "spec": "docs/specs/2026-06-27-injection-policy-abstention.md",
        "phase": "0 — snapshot",
        "records": {
            "n_records": len(records),
            "n_relevant": sum(1 for r in records if r.rating == "relevant"),
            "n_bad": sum(1 for r in records if r.rating == "not_relevant"),
            "n_with_block_score": sum(1 for r in records if r.block_score is not None),
            "n_with_routing_score": sum(1 for r in records if r.routing_score is not None),
        },
        "skips": {
            "no_block_match": skips.no_block_match,
            "no_block_score": skips.no_block_score,
            "other_rating": skips.other_rating,
        },
        "by_container": compute_container_rates(records),
        "block_score": {
            "distributions": compute_type_distributions(records, "block_score"),
            "pr_frontier_threshold_at_target": derive_target_thresholds(pr_block),
            "proposed_policy": apply_proposed_policy(records, PROPOSED_POLICY, "block_score"),
        },
        "routing_score_sanity_check": {
            "distributions": compute_type_distributions(records, "routing_score"),
            "pr_frontier_threshold_at_target": derive_target_thresholds(pr_routing),
            "same_thresholds_on_routing_score": apply_proposed_policy(
                records, PROPOSED_POLICY, "routing_score"
            ),
        },
    }


def format_text_summary(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("=== Injection-Policy Phase 0 Snapshot ===")
    lines.append("")
    lines.append("Records:")
    for k, v in report["records"].items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("Skips:")
    for k, v in report["skips"].items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("Per-container precision (relevant/total):")
    for c, info in report["by_container"].items():
        lines.append(
            f"  {c or '<empty>':<48} n={info['total']:>4} "
            f"prec={info['precision']:.2%} bad={info['bad_rate']:.2%}"
        )
    lines.append("")
    lines.append("Per-type score (block_score) distribution medians:")
    dist = report["block_score"]["distributions"]
    for mtype, info in dist.items():
        cov = info["coverage"]
        med_rel = info["relevant"]["median"] if info["relevant"] else None
        med_bad = info["not_relevant"]["median"] if info["not_relevant"] else None
        lines.append(
            f"  {mtype:<22} n={cov['total']:>4} rel={cov['n_relevant']:>3} "
            f"bad={cov['n_bad']:>3} med_rel={med_rel} med_bad={med_bad}"
        )
    lines.append("")
    lines.append("Per-type best threshold at >=70% precision (block_score):")
    targets = report["block_score"]["pr_frontier_threshold_at_target"]
    for mtype, info in targets.items():
        best = info["best"]
        if best:
            lines.append(
                f"  {mtype:<22} thr>={best['threshold']:<6} "
                f"prec={best['precision']:.2%} recall={best['recall']:.2%} "
                f"kept_rel={best['kept_relevant']} kept_bad={best['kept_bad']}"
            )
        else:
            lines.append(f"  {mtype:<22} (unreachable at target)")
    lines.append("")
    pol = report["block_score"]["proposed_policy"]
    lines.append("Proposed policy applied to block_score:")
    lines.append(f"  policy: {pol['policy']}")
    lines.append(
        f"  base precision: {pol['base_precision']:.2%} "
        f"(rel={pol['total_relevant_original']} bad={pol['total_bad_original']})"
    )
    if pol["new_precision"] is not None:
        lines.append(
            f"  kept proactively: {pol['kept_total']} "
            f"(rel={pol['kept_relevant']} bad={pol['kept_bad']})"
        )
        lines.append(f"  new precision: {pol['new_precision']:.2%}")
        lines.append(f"  recall of relevant signal: {pol['recall_of_relevant_signal']:.2%}")
        lines.append(f"  bad eliminated: {pol['bad_eliminated_fraction']:.2%}")
    lines.append("")
    rpol = report["routing_score_sanity_check"]["same_thresholds_on_routing_score"]
    lines.append("SANITY CHECK — same thresholds applied to routing_score:")
    if rpol["new_precision"] is not None:
        lines.append(
            f"  precision={rpol['new_precision']:.2%} "
            f"(kept_total={rpol['kept_total']} kept_rel={rpol['kept_relevant']})"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 0 snapshot of injection-policy abstention plan."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to pallium.db (default: ~/.pallium/data/pallium.db)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the full JSON report (in addition to stdout).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the human-readable text summary on stdout; emit JSON only.",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 2

    conn = open_db_readonly(args.db)
    try:
        rows = load_joined_rows(conn)
    finally:
        conn.close()

    records, skips = extract_records(rows)
    report = build_report(records, skips)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True))
        print(f"Wrote report → {args.output}", file=sys.stderr)

    if args.quiet:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        sys.stdout.write("\n")
    else:
        print(format_text_summary(report))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
