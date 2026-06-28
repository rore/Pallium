"""Phase 1 — chronological holdout validation for the injection-policy spec.

See: docs/specs/2026-06-27-injection-policy-abstention.md

Reads the same live SQLite database as Phase 0, but treats duplicate
ratings on a single (memory_object_id, query_audit_log_id) pair as one
event via `majority_rating` from evals/retrieval_ablation/evaluate.py
(ties resolve to "not_relevant" — the conservative choice).

Splits events chronologically 80/20 by event timestamp with deterministic
tie-break, derives per-type thresholds on the train slice, and reports
precision/recall on the held-out tail.

Pass bar per spec:
  - constraint_memory, decision: held-out precision >= 70% with >=10 kept
    -> recommended `proactive`. Else `demote_to_on_demand`.
  - task_checkpoint: report-only; Phase 4 event triggers are the real gate.
  - investigation_outcome, thread_summary: always `demote_to_on_demand`.
  - fact_summary: always `suspend_insufficient_data`.

Phase 1 REPORTS and RECOMMENDS. It does NOT land config changes — that's
Phase 3a. The recommended_final_policy block in the report is what Phase
3a will copy into pallium.local.toml.

Run:
    python -m evals.injection_policy_2026_06.holdout
    python -m evals.injection_policy_2026_06.holdout --output report.json
    python -m evals.injection_policy_2026_06.holdout --db /path/pallium.db
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from evals.injection_policy_2026_06.analyze import (  # noqa: E402
    DEFAULT_DB_PATH,
    InjectionRecord,
    PRECISION_TARGET,
    SkipCounts,
    _VALID_RATINGS,
    apply_proposed_policy,
    compute_pr_frontier,
    derive_target_thresholds,
    extract_records,
    load_joined_rows,
    open_db_readonly,
)
from evals.retrieval_ablation.evaluate import (  # noqa: E402
    FeedbackEntry,
    majority_rating,
)


# Phase 1 constants ---------------------------------------------------------

TRAIN_FRACTION = 0.8
# Minimum kept_relevant on the TRAIN slice before a threshold counts as a
# recommendation. Phase 0's `derive_target_thresholds` accepts >=1; here
# we tighten to >=5 to refuse statistically-empty thresholds.
MIN_TRAIN_KEPT_RELEVANT = 5
# Minimum kept_total on the HOLDOUT slice for the spec's pass bar.
MIN_HOLDOUT_KEPT = 10
# Type-level minimum to bother deriving a threshold at all.
MIN_EVENTS_FOR_REPORTING = 6

# Spec types that have a pre-decided disposition regardless of numbers.
_ALWAYS_ON_DEMAND: frozenset[str] = frozenset({
    "investigation_outcome",
    "thread_summary",
})
_ALWAYS_SUSPENDED: frozenset[str] = frozenset({"fact_summary"})
_REFERENCE_ONLY: frozenset[str] = frozenset({"task_checkpoint"})
# Types in the spec's proposed proactive policy.
_PROACTIVE_CANDIDATES: frozenset[str] = frozenset({
    "constraint_memory",
    "decision",
})


# ---------------------------------------------------------------------------
# Event = deduped InjectionRecord with a chronological key
# ---------------------------------------------------------------------------


@dataclass
class InjectionEvent:
    """One injection event (one (memory_object_id, query_audit_log_id) pair),
    rated by majority of its feedback rows.

    The other fields are constant across duplicates by construction (they
    come from the same audit-log + memory pair) — Phase 1 asserts this.
    """
    rating: str
    memory_type: str
    container_ref: str
    block_score: float | None
    routing_score: float | None
    event_created_at: str  # min across duplicates; used as split sort key
    memory_object_id: str
    query_audit_log_id: str
    n_underlying_ratings: int  # for audit
    tie_resolved: bool  # True if majority_rating saw a tie (-> not_relevant)


@dataclass
class DedupSummary:
    n_events_before: int
    n_events_after: int
    n_collapsed_pairs: int
    n_ties_to_not_relevant: int


# ---------------------------------------------------------------------------
# I/O — joined rows, but keyed for dedup
# ---------------------------------------------------------------------------


def load_joined_rows_keyed(conn) -> list[dict[str, Any]]:
    """Like analyze.load_joined_rows but also carries the join key fields.

    Phase 0 already does this — load_joined_rows returns dicts including
    `memory_object_id` and `query_audit_log_id`. Reuse it directly.
    """
    return load_joined_rows(conn)


# ---------------------------------------------------------------------------
# Compute layer — pure
# ---------------------------------------------------------------------------


def dedup_to_events(
    records: list[InjectionRecord],
    *,
    join_keys: dict[tuple[str, str], list[dict[str, Any]]] | None = None,
) -> tuple[list[InjectionEvent], DedupSummary]:
    """Collapse duplicate ratings on the same (memory_object_id, query_audit_log_id)
    pair into one event via majority_rating.

    The InjectionRecord stream from extract_records does NOT carry
    query_audit_log_id directly; the caller supplies the original joined
    rows so we can recover it. join_keys is a map keyed by the rating's
    feedback_id (carried as a tag if you go that route) — but since
    InjectionRecord is the projection of one joined row, the simpler path
    is to receive (record, join_key, created_at) tuples. To keep the
    pure-compute layer clean, we accept records+rows side-by-side.
    """
    raise NotImplementedError(
        "Use dedup_from_rows() directly — it has the join key information."
    )


def dedup_from_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[InjectionEvent], DedupSummary, SkipCounts]:
    """Run extract_records-equivalent projection AND group by
    (memory_object_id, query_audit_log_id) AND collapse via majority_rating.

    Returns a list of one InjectionEvent per join-key pair, plus a summary
    and the skip counter (forwarded from extract_records semantics).

    Pre-dedup ratings outside the {relevant, not_relevant} enum are
    dropped, matching Phase 0.
    """
    # Project each row exactly as extract_records does, plus carry the
    # join key + created_at.
    skips = SkipCounts()
    projected: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rating = row.get("rating")
        if rating not in _VALID_RATINGS:
            skips.other_rating += 1
            continue
        mid = row.get("memory_object_id")
        qa_id = row.get("query_audit_log_id")
        if not mid or not qa_id:
            skips.no_block_match += 1
            continue
        # Reuse extract_records for the per-row projection so the dedup
        # path stays bug-for-bug compatible with Phase 0's record shape.
        rec_list, sub_skips = extract_records([row])
        if not rec_list:
            # extract_records already incremented its skip counters for
            # this row — surface them.
            skips.no_block_match += sub_skips.no_block_match
            skips.no_block_score += sub_skips.no_block_score
            continue
        skips.no_block_score += sub_skips.no_block_score
        rec = rec_list[0]
        projected[(mid, qa_id)].append({
            "rating": rec.rating,
            "memory_type": rec.memory_type,
            "container_ref": rec.container_ref,
            "block_score": rec.block_score,
            "routing_score": rec.routing_score,
            "created_at": row.get("feedback_created_at") or "",
        })

    n_events_before = sum(len(v) for v in projected.values())
    n_collapsed_pairs = sum(1 for v in projected.values() if len(v) > 1)
    n_ties = 0
    events: list[InjectionEvent] = []
    for (mid, qa_id), group in projected.items():
        # Sanity-assert constant fields. If they ever diverge it indicates
        # a data-integrity bug we want to surface, not silently merge.
        memory_types = {g["memory_type"] for g in group}
        if len(memory_types) > 1:
            raise ValueError(
                f"Inconsistent memory_type within join key "
                f"(memory_object_id={mid}, query_audit_log_id={qa_id}): "
                f"{sorted(memory_types)}"
            )
        block_scores = {g["block_score"] for g in group}
        if len(block_scores) > 1:
            raise ValueError(
                f"Inconsistent block_score within join key "
                f"(memory_object_id={mid}, query_audit_log_id={qa_id}): "
                f"{sorted(block_scores, key=lambda x: -1 if x is None else x)}"
            )
        entries = [
            FeedbackEntry(
                memory_object_id=mid,
                rating=g["rating"],
                query_context="",
                memory_type=g["memory_type"],
            )
            for g in group
        ]
        rating = majority_rating(entries)
        if rating is None:
            # majority_rating returns None only for an empty list, which
            # we filtered out.
            continue
        # Detect tie (relevant_count == not_relevant_count and >0).
        rel = sum(1 for e in entries if e.rating == "relevant")
        nrel = sum(1 for e in entries if e.rating == "not_relevant")
        is_tie = rel == nrel and rel > 0
        if is_tie:
            n_ties += 1
        # Pick the minimum created_at across the group as the event time.
        earliest = min(g["created_at"] for g in group)
        first = group[0]
        events.append(InjectionEvent(
            rating=rating,
            memory_type=first["memory_type"],
            container_ref=first["container_ref"],
            block_score=first["block_score"],
            routing_score=first["routing_score"],
            event_created_at=earliest,
            memory_object_id=mid,
            query_audit_log_id=qa_id,
            n_underlying_ratings=len(group),
            tie_resolved=is_tie,
        ))

    summary = DedupSummary(
        n_events_before=n_events_before,
        n_events_after=len(events),
        n_collapsed_pairs=n_collapsed_pairs,
        n_ties_to_not_relevant=n_ties,
    )
    return events, summary, skips


def chronological_split(
    events: list[InjectionEvent], train_fraction: float = TRAIN_FRACTION
) -> tuple[list[InjectionEvent], list[InjectionEvent]]:
    """Deterministic chronological split.

    Sort key: (event_created_at, memory_object_id, query_audit_log_id).
    Cutoff is floor(train_fraction * n_events); events [0, cutoff) go
    to train, [cutoff, n) to holdout. With timestamp ties the tie-break
    fields decide which side an event lands on.
    """
    sorted_events = sorted(
        events,
        key=lambda e: (e.event_created_at, e.memory_object_id, e.query_audit_log_id),
    )
    cutoff = int(train_fraction * len(sorted_events))
    return sorted_events[:cutoff], sorted_events[cutoff:]


def _events_to_records(events: list[InjectionEvent]) -> list[InjectionRecord]:
    """Project events back into the InjectionRecord shape so we can reuse
    Phase 0's pure compute kernels unchanged.
    """
    return [
        InjectionRecord(
            rating=e.rating,
            memory_type=e.memory_type,
            container_ref=e.container_ref,
            block_score=e.block_score,
            retrieval_source=None,
            routing_score=e.routing_score,
            lexical_score=None,
            vector_score=None,
        )
        for e in events
    ]


def derive_thresholds_with_min_kept(
    train_records: list[InjectionRecord],
    *,
    score_field: str = "block_score",
    precision_target: float = PRECISION_TARGET,
    min_kept_relevant: int = MIN_TRAIN_KEPT_RELEVANT,
) -> dict[str, dict[str, Any]]:
    """Like analyze.derive_target_thresholds but enforces a minimum
    kept_relevant count on the train slice. Refuses to return a threshold
    whose best frontier point has kept_relevant < min_kept_relevant.
    """
    frontier = compute_pr_frontier(train_records, score_field=score_field)
    naive = derive_target_thresholds(frontier, precision_target=precision_target)
    out: dict[str, dict[str, Any]] = {}
    for mtype, info in naive.items():
        best = info.get("best")
        if best is None or best["kept_relevant"] < min_kept_relevant:
            out[mtype] = {
                "n_relevant_train": info["n_relevant"],
                "n_total_train": info["n_total"],
                "target_precision": precision_target,
                "min_kept_relevant_required": min_kept_relevant,
                "best": None,
                "reason_no_threshold": (
                    "unreachable_at_target" if best is None
                    else f"kept_relevant={best['kept_relevant']} < {min_kept_relevant}"
                ),
            }
        else:
            out[mtype] = {
                "n_relevant_train": info["n_relevant"],
                "n_total_train": info["n_total"],
                "target_precision": precision_target,
                "min_kept_relevant_required": min_kept_relevant,
                "best": best,
                "reason_no_threshold": None,
            }
    return out


def evaluate_on_holdout(
    holdout_records: list[InjectionRecord],
    thresholds_by_type: dict[str, dict[str, Any]],
    *,
    score_field: str = "block_score",
) -> dict[str, dict[str, Any]]:
    """For each type with a derived train threshold, compute holdout
    precision/recall against that threshold. Types without a derived
    threshold are reported as None.
    """
    by_type: dict[str, list[InjectionRecord]] = defaultdict(list)
    for r in holdout_records:
        by_type[r.memory_type].append(r)

    out: dict[str, dict[str, Any]] = {}
    for mtype, train_info in thresholds_by_type.items():
        train_best = train_info.get("best")
        thr = train_best["threshold"] if train_best else None
        rel_total = sum(1 for r in by_type.get(mtype, []) if r.rating == "relevant")
        if thr is None:
            out[mtype] = {
                "applied_threshold": None,
                "kept_total": 0,
                "kept_relevant": 0,
                "kept_bad": 0,
                "precision": None,
                "recall": None,
                "n_holdout": len(by_type.get(mtype, [])),
                "n_relevant_holdout": rel_total,
            }
            continue
        kept_rel = 0
        kept_bad = 0
        for r in by_type.get(mtype, []):
            score = getattr(r, score_field)
            if score is None or score < thr:
                continue
            if r.rating == "relevant":
                kept_rel += 1
            elif r.rating == "not_relevant":
                kept_bad += 1
        kept_total = kept_rel + kept_bad
        precision = (kept_rel / kept_total) if kept_total else None
        recall = (kept_rel / rel_total) if rel_total else None
        out[mtype] = {
            "applied_threshold": thr,
            "kept_total": kept_total,
            "kept_relevant": kept_rel,
            "kept_bad": kept_bad,
            "precision": precision,
            "recall": recall,
            "n_holdout": len(by_type.get(mtype, [])),
            "n_relevant_holdout": rel_total,
        }
    return out


def assemble_dispositions(
    thresholds_by_type: dict[str, dict[str, Any]],
    holdout_by_type: dict[str, dict[str, Any]],
    counts_by_type: dict[str, int],
) -> dict[str, dict[str, Any]]:
    """Compute the Phase 1 disposition recommendation per type.

    Rules (per spec):
      - investigation_outcome, thread_summary: always demote_to_on_demand.
      - fact_summary: always suspend_insufficient_data.
      - task_checkpoint: reference_only (Phase 4 event triggers are the
        real gate).
      - constraint_memory, decision: proactive iff holdout precision >= 0.70
        AND holdout kept_total >= MIN_HOLDOUT_KEPT, else demote_to_on_demand.
      - Other types: report-only.
    """
    out: dict[str, dict[str, Any]] = {}
    all_types = set(thresholds_by_type) | set(holdout_by_type) | set(counts_by_type)
    for mtype in sorted(all_types):
        n_total = counts_by_type.get(mtype, 0)
        if n_total < MIN_EVENTS_FOR_REPORTING:
            out[mtype] = {
                "disposition": None,
                "insufficient_for_reporting": True,
                "reason": f"n_total={n_total} < {MIN_EVENTS_FOR_REPORTING}",
            }
            continue
        if mtype in _ALWAYS_SUSPENDED:
            out[mtype] = {
                "disposition": "suspend_insufficient_data",
                "reason": "spec: fact_summary suspended; pipeline known broken",
            }
            continue
        if mtype in _ALWAYS_ON_DEMAND:
            out[mtype] = {
                "disposition": "demote_to_on_demand",
                "reason": "spec: pre-decided on-demand regardless of numbers",
            }
            continue
        if mtype in _REFERENCE_ONLY:
            out[mtype] = {
                "disposition": "reference_only",
                "reason": "spec: phase 4 event-trigger is the real gate",
            }
            continue
        if mtype in _PROACTIVE_CANDIDATES:
            holdout = holdout_by_type.get(mtype) or {}
            precision = holdout.get("precision")
            kept = holdout.get("kept_total") or 0
            if precision is None or precision < PRECISION_TARGET or kept < MIN_HOLDOUT_KEPT:
                out[mtype] = {
                    "disposition": "demote_to_on_demand",
                    "reason": (
                        f"holdout precision={precision}, kept={kept} below pass bar "
                        f"(>= {PRECISION_TARGET}, >= {MIN_HOLDOUT_KEPT})"
                    ),
                }
            else:
                out[mtype] = {
                    "disposition": "proactive",
                    "reason": (
                        f"holdout precision={precision:.4f} >= {PRECISION_TARGET}; "
                        f"kept={kept} >= {MIN_HOLDOUT_KEPT}"
                    ),
                }
            continue
        out[mtype] = {
            "disposition": "report_only",
            "reason": "type not in spec final policy",
        }
    return out


def assemble_recommended_policy(
    thresholds_by_type: dict[str, dict[str, Any]],
    dispositions: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Final policy dict that Phase 3a will copy into TOML.

    Only includes types whose disposition is `proactive`.
    """
    out: dict[str, dict[str, Any]] = {}
    for mtype, info in dispositions.items():
        if info.get("disposition") != "proactive":
            continue
        thr_info = thresholds_by_type.get(mtype) or {}
        best = thr_info.get("best")
        if best is None:
            continue
        out[mtype] = {"mode": "proactive", "min_score": best["threshold"]}
    return out


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def build_holdout_report(
    events: list[InjectionEvent],
    dedup: DedupSummary,
    skips: SkipCounts,
    *,
    train_fraction: float = TRAIN_FRACTION,
) -> dict[str, Any]:
    train, holdout = chronological_split(events, train_fraction=train_fraction)
    train_records = _events_to_records(train)
    holdout_records = _events_to_records(holdout)

    thresholds_by_type = derive_thresholds_with_min_kept(
        train_records, score_field="block_score"
    )
    holdout_by_type = evaluate_on_holdout(
        holdout_records, thresholds_by_type, score_field="block_score"
    )

    counts_by_type: dict[str, int] = defaultdict(int)
    for e in events:
        counts_by_type[e.memory_type] += 1
    dispositions = assemble_dispositions(
        thresholds_by_type, holdout_by_type, dict(counts_by_type)
    )
    recommended_policy = assemble_recommended_policy(
        thresholds_by_type, dispositions
    )

    per_type: dict[str, dict[str, Any]] = {}
    for mtype in sorted(set(thresholds_by_type) | set(counts_by_type)):
        n_train = sum(1 for e in train if e.memory_type == mtype)
        n_holdout = sum(1 for e in holdout if e.memory_type == mtype)
        per_type[mtype] = {
            "n_train": n_train,
            "n_holdout": n_holdout,
            "n_total": counts_by_type.get(mtype, 0),
            "train_threshold": thresholds_by_type.get(mtype),
            "holdout": holdout_by_type.get(mtype),
            "disposition": dispositions.get(mtype),
        }

    return {
        "spec": "docs/specs/2026-06-27-injection-policy-abstention.md",
        "phase": "1 — chronological holdout",
        "config": {
            "train_fraction": train_fraction,
            "split_tie_break": ["event_created_at", "memory_object_id", "query_audit_log_id"],
            "precision_target": PRECISION_TARGET,
            "min_train_kept_relevant": MIN_TRAIN_KEPT_RELEVANT,
            "min_holdout_kept": MIN_HOLDOUT_KEPT,
            "min_events_for_reporting": MIN_EVENTS_FOR_REPORTING,
            "dedup_tie_resolution": "majority_rating: tie -> not_relevant",
        },
        "dedup": {
            "n_events_before": dedup.n_events_before,
            "n_events_after": dedup.n_events_after,
            "n_collapsed_pairs": dedup.n_collapsed_pairs,
            "n_ties_to_not_relevant": dedup.n_ties_to_not_relevant,
        },
        "skips": {
            "no_block_match": skips.no_block_match,
            "no_block_score": skips.no_block_score,
            "other_rating": skips.other_rating,
        },
        "split_summary": {
            "n_train": len(train),
            "n_holdout": len(holdout),
            "train_window": [
                (train[0].event_created_at if train else None),
                (train[-1].event_created_at if train else None),
            ],
            "holdout_window": [
                (holdout[0].event_created_at if holdout else None),
                (holdout[-1].event_created_at if holdout else None),
            ],
        },
        "per_type": per_type,
        "recommended_final_policy": recommended_policy,
    }


def format_text_summary(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("=== Phase 1 — Chronological Holdout Validation ===")
    lines.append("")
    cfg = report["config"]
    lines.append(
        f"Train fraction: {cfg['train_fraction']}  "
        f"precision target: {cfg['precision_target']}  "
        f"min train kept_rel: {cfg['min_train_kept_relevant']}  "
        f"min holdout kept: {cfg['min_holdout_kept']}"
    )
    dedup = report["dedup"]
    lines.append(
        f"Dedup: {dedup['n_events_before']} -> {dedup['n_events_after']} "
        f"({dedup['n_collapsed_pairs']} pairs collapsed; "
        f"{dedup['n_ties_to_not_relevant']} ties -> not_relevant)"
    )
    split = report["split_summary"]
    lines.append(
        f"Split: train n={split['n_train']}  holdout n={split['n_holdout']}"
    )
    lines.append("")
    lines.append("Per-type:")
    for mtype, info in report["per_type"].items():
        disp = info.get("disposition") or {}
        if disp.get("insufficient_for_reporting"):
            lines.append(
                f"  {mtype:<24} n_total={info['n_total']:<3} "
                f"INSUFFICIENT_FOR_REPORTING"
            )
            continue
        train_thr = info.get("train_threshold") or {}
        thr_best = train_thr.get("best")
        hd = info.get("holdout") or {}
        hd_prec = hd.get("precision")
        hd_recall = hd.get("recall")
        thr_val = thr_best["threshold"] if thr_best else "-"
        lines.append(
            f"  {mtype:<24} n_train={info['n_train']:<3} n_hd={info['n_holdout']:<3} "
            f"thr={thr_val}  hd_prec={('%.2f%%' % (hd_prec*100)) if hd_prec is not None else '-'}  "
            f"hd_recall={('%.2f%%' % (hd_recall*100)) if hd_recall is not None else '-'}  "
            f"kept={hd.get('kept_total', 0)}  -> {disp.get('disposition')}"
        )
    lines.append("")
    lines.append("Recommended final policy:")
    for mtype, p in report["recommended_final_policy"].items():
        lines.append(f"  {mtype:<24} mode={p['mode']} min_score={p['min_score']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 1 chronological holdout validation of the abstention "
            "policy thresholds."
        )
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
        help="Optional path to write the full JSON report.",
    )
    parser.add_argument(
        "--train-fraction",
        type=float,
        default=TRAIN_FRACTION,
        help=f"Train fraction (default: {TRAIN_FRACTION})",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="JSON-only output to stdout.",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 2

    conn = open_db_readonly(args.db)
    try:
        rows = load_joined_rows_keyed(conn)
    finally:
        conn.close()

    events, dedup, skips = dedup_from_rows(rows)
    report = build_holdout_report(events, dedup, skips, train_fraction=args.train_fraction)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True))
        print(f"Wrote report -> {args.output}", file=sys.stderr)

    if args.quiet:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        sys.stdout.write("\n")
    else:
        print(format_text_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
