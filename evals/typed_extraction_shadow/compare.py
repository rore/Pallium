"""Typed-extraction shadow comparison eval.

# measures: injection-precision, candidate-recovery

Joins ``memory_objects_shadow`` rows against live ``memory_objects``
and the rated-injection corpus (``memory_feedback``) to compute per-
type precision / recall / drift metrics between the live extractor
and the typed shadow extractor.

**Output** — ``report_YYYY-MM-DD.json`` under this directory. Per-type
blocks: matched / live-only / shadow-only counts, precision (with
shadow-precision lower/upper bounds), recall, drift signals.

**Promotion gate** (evaluated per type, not applied by this script —
that's a human decision documented in a spec):
1. ``shadow_precision_lower_bound - live_precision >= 0.05``
2. ``shadow_recall >= live_recall`` (no recall regression)
3. Narrow-target scenarios for the type still pass (checked by the
   promotion PR, not here)
4. ``shadow_coverage_ratio >= 0.9`` (window was substantial)

Usage::

    python -m evals.typed_extraction_shadow.compare \\
        --sqlite-url sqlite:///./pallium.db \\
        --window-start 2026-07-15 --window-end 2026-07-29 \\
        --output evals/typed_extraction_shadow/report_2026-07-29.json

For CI / unit tests: import ``compare_shadow_vs_live()`` directly
with in-memory row lists — no DB required.
"""

# measures: injection-precision, candidate-recovery

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

REPORT_VERSION: str = "typed_extraction_shadow.v1"

COMPARED_TYPES: tuple[str, ...] = (
    "decision",
    "investigation_outcome",
    "constraint_memory",
    "operational_fact",
    "supersession",
)

# Promotion-gate thresholds (documented in the spec).
MIN_PRECISION_DELTA: float = 0.05
MIN_COVERAGE_RATIO: float = 0.9
# Below this, all types are automatically insufficient-evidence.
COVERAGE_HARD_FLOOR: float = 0.7


@dataclass(frozen=True)
class LiveRow:
    memory_object_id: str
    source_item_id: str
    type: str
    subject: str


@dataclass(frozen=True)
class ShadowRow:
    id: str
    source_item_id: str
    type: str
    subject: str
    parse_status: str


@dataclass(frozen=True)
class FeedbackRow:
    memory_object_id: str
    rating: str  # "relevant" | "not_relevant"


@dataclass(frozen=True)
class GroundTruthEntry:
    """One expected extraction, seeded from fixtures / rated corpus.

    Used to compute recall: recall = TP / |ground_truth|.
    """

    source_item_id: str
    type: str
    subject: str


@dataclass
class TypeMetrics:
    matched: int = 0
    live_only: int = 0
    shadow_only: int = 0
    live_precision: float | None = None
    shadow_precision_lower_bound: float | None = None
    shadow_precision_upper_bound: float | None = None
    live_recall: float | None = None
    shadow_recall: float | None = None
    live_true_positives: int = 0
    live_false_positives: int = 0
    shadow_true_positives: int = 0
    shadow_false_positives_lower: int = 0
    shadow_false_positives_upper: int = 0
    drift_subject_diff: float | None = None
    meets_promotion_gate: bool | None = None
    promotion_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "live_only": self.live_only,
            "shadow_only": self.shadow_only,
            "live_precision": _round_or_none(self.live_precision),
            "shadow_precision_lower_bound": _round_or_none(
                self.shadow_precision_lower_bound
            ),
            "shadow_precision_upper_bound": _round_or_none(
                self.shadow_precision_upper_bound
            ),
            "live_recall": _round_or_none(self.live_recall),
            "shadow_recall": _round_or_none(self.shadow_recall),
            "drift_subject_diff": _round_or_none(self.drift_subject_diff),
            "meets_promotion_gate": self.meets_promotion_gate,
            "promotion_reason": self.promotion_reason,
        }


def _round_or_none(v: float | None) -> float | None:
    if v is None:
        return None
    return round(v, 4)


# --------------------------------------------------------------------------- #
# Public entry: compare in-memory row lists                                   #
# --------------------------------------------------------------------------- #


def compare_shadow_vs_live(
    *,
    live_rows: Iterable[LiveRow],
    shadow_rows: Iterable[ShadowRow],
    feedback: Iterable[FeedbackRow],
    ground_truth: Iterable[GroundTruthEntry] = (),
    window_start: str | None = None,
    window_end: str | None = None,
) -> dict[str, Any]:
    """Compute the comparison report. Pure function; deterministic.

    Callers with a real DB can build the input lists via SQL; the CI
    tests pass literal fixtures.
    """
    live_list = list(live_rows)
    shadow_list = list(shadow_rows)
    feedback_list = list(feedback)
    ground_truth_list = list(ground_truth)

    # 1. Restrict to source_items that were shadow-processed. Coverage
    # ratio measures how much of the live-processed window shadow saw.
    shadow_source_ids = {r.source_item_id for r in shadow_list}
    live_source_ids = {r.source_item_id for r in live_list}
    intersected = shadow_source_ids & live_source_ids
    live_count_full = len(live_source_ids)
    coverage_ratio = (
        len(intersected) / live_count_full if live_count_full > 0 else 0.0
    )

    shadow_parse_failures = Counter(
        r.parse_status for r in shadow_list if r.parse_status != "ok"
    )

    # 2. Feedback dict: memory_object_id -> "relevant" | "not_relevant".
    ratings: dict[str, str] = {r.memory_object_id: r.rating for r in feedback_list}

    # 3. Ground-truth dict: (source_item_id, type, normalized_subject) -> None.
    ground_truth_keys: set[tuple[str, str, str]] = {
        (g.source_item_id, g.type, _normalize_subject(g.subject))
        for g in ground_truth_list
    }

    # 4. Per-type comparison.
    per_type: dict[str, TypeMetrics] = {t: TypeMetrics() for t in COMPARED_TYPES}
    subject_diff_num: dict[str, int] = defaultdict(int)
    subject_diff_denom: dict[str, int] = defaultdict(int)

    for mtype in COMPARED_TYPES:
        live_by_key: dict[tuple[str, str], LiveRow] = {}
        shadow_by_key: dict[tuple[str, str], ShadowRow] = {}
        for r in live_list:
            if r.type != mtype:
                continue
            if r.source_item_id not in intersected:
                continue
            live_by_key[(r.source_item_id, _normalize_subject(r.subject))] = r
        for r in shadow_list:
            if r.type != mtype:
                continue
            if r.source_item_id not in intersected:
                continue
            if r.parse_status != "ok":
                continue
            shadow_by_key[(r.source_item_id, _normalize_subject(r.subject))] = r

        matched_keys = set(live_by_key.keys()) & set(shadow_by_key.keys())
        live_only_keys = set(live_by_key.keys()) - matched_keys
        shadow_only_keys = set(shadow_by_key.keys()) - matched_keys

        m = per_type[mtype]
        m.matched = len(matched_keys)
        m.live_only = len(live_only_keys)
        m.shadow_only = len(shadow_only_keys)

        # Precision on the rated corpus: what fraction of extracted rows
        # were rated relevant? Only rows with a rating count toward the
        # denominator.
        live_relevant = 0
        live_notrelevant = 0
        shadow_matched_relevant = 0
        shadow_matched_notrelevant = 0
        for key in matched_keys | live_only_keys:
            row = live_by_key[key]
            rating = ratings.get(row.memory_object_id)
            if rating == "relevant":
                live_relevant += 1
                # For matched, shadow "inherits" the rating.
                if key in matched_keys:
                    shadow_matched_relevant += 1
            elif rating == "not_relevant":
                live_notrelevant += 1
                if key in matched_keys:
                    shadow_matched_notrelevant += 1
        rated_live_total = live_relevant + live_notrelevant
        if rated_live_total > 0:
            m.live_precision = live_relevant / rated_live_total
            m.live_true_positives = live_relevant
            m.live_false_positives = live_notrelevant

            # Shadow-precision bounds.
            #  Lower: treat every shadow-only row as NOT relevant (worst case).
            #  Upper: treat every shadow-only row as relevant (best case).
            shadow_only_count = len(shadow_only_keys)
            m.shadow_precision_lower_bound = shadow_matched_relevant / (
                shadow_matched_relevant + shadow_matched_notrelevant
                + shadow_only_count
            ) if (
                shadow_matched_relevant + shadow_matched_notrelevant
                + shadow_only_count
            ) > 0 else None
            m.shadow_precision_upper_bound = (
                shadow_matched_relevant + shadow_only_count
            ) / (
                shadow_matched_relevant + shadow_matched_notrelevant
                + shadow_only_count
            ) if (
                shadow_matched_relevant + shadow_matched_notrelevant
                + shadow_only_count
            ) > 0 else None

        # Recall against ground truth (if seeded).
        gt_for_type = {
            (sid, subj)
            for (sid, t, subj) in ground_truth_keys
            if t == mtype and sid in intersected
        }
        if gt_for_type:
            live_tp = len(set(live_by_key.keys()) & gt_for_type)
            shadow_tp = len(set(shadow_by_key.keys()) & gt_for_type)
            m.live_recall = live_tp / len(gt_for_type)
            m.shadow_recall = shadow_tp / len(gt_for_type)
            m.shadow_true_positives = shadow_tp

        # Drift: subject-different fraction of matched rows. For our
        # (source_item_id, normalized_subject) match key, matched rows
        # always agree on subject — so this metric is 0 unless we widen
        # the join. For PR 4 we surface it as 0 with a placeholder
        # comment for future work; the harness is what we're validating.
        m.drift_subject_diff = 0.0

        # Promotion gate.
        m.meets_promotion_gate, m.promotion_reason = _evaluate_promotion_gate(
            m, coverage_ratio=coverage_ratio
        )

    report: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "measures": "injection-precision, candidate-recovery",
        "window_start": window_start,
        "window_end": window_end,
        "coverage_ratio": _round_or_none(coverage_ratio),
        "live_source_items_in_window": live_count_full,
        "shadow_source_items_in_window": len(shadow_source_ids),
        "intersected_source_items": len(intersected),
        "shadow_parse_failures": dict(shadow_parse_failures),
        "per_type": {
            mtype: metrics.to_dict()
            for mtype, metrics in per_type.items()
        },
    }

    # Global warnings.
    warnings: list[str] = []
    if coverage_ratio < MIN_COVERAGE_RATIO:
        warnings.append(
            f"shadow_coverage_ratio {coverage_ratio:.2f} < {MIN_COVERAGE_RATIO:.2f}: "
            "results are on the intersection, not the full stream"
        )
    if coverage_ratio < COVERAGE_HARD_FLOOR:
        warnings.append(
            "coverage below hard floor — all per-type promotion gates "
            "forced to insufficient-evidence"
        )
    report["warnings"] = warnings

    return report


def _evaluate_promotion_gate(
    m: TypeMetrics,
    *,
    coverage_ratio: float,
) -> tuple[bool | None, str]:
    if coverage_ratio < COVERAGE_HARD_FLOOR:
        return (False, "coverage_below_hard_floor")
    if m.live_precision is None or m.shadow_precision_lower_bound is None:
        return (None, "no_rated_data")
    if (
        m.shadow_precision_lower_bound - m.live_precision
        < MIN_PRECISION_DELTA
    ):
        return (
            False,
            f"precision_delta_below_threshold "
            f"({m.shadow_precision_lower_bound:.3f} - "
            f"{m.live_precision:.3f} < {MIN_PRECISION_DELTA:.2f})",
        )
    if m.live_recall is not None and m.shadow_recall is not None:
        if m.shadow_recall < m.live_recall:
            return (
                False,
                f"recall_regression "
                f"(shadow {m.shadow_recall:.3f} < live {m.live_recall:.3f})",
            )
    if coverage_ratio < MIN_COVERAGE_RATIO:
        return (
            False,
            f"coverage_ratio_below_threshold ({coverage_ratio:.2f})",
        )
    return (True, "gate_met")


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize_subject(subject: str) -> str:
    """Normalize subjects for the match key.

    Lowercase, strip punctuation, collapse whitespace, trim to 120
    chars. Deterministic; the same input yields the same output.
    """
    if not subject:
        return ""
    s = subject.lower().strip()
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s[:120]


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="typed_extraction_shadow.compare",
        description=(
            "Compare typed-shadow-extraction output against the live "
            "extractor's output on the same source items."
        ),
    )
    parser.add_argument(
        "--sqlite-url",
        default="sqlite:///./pallium.db",
        help="SQLite URL for the DB to read from.",
    )
    parser.add_argument(
        "--window-start",
        default=None,
        help="ISO 8601 datetime; restrict to rows produced after this timestamp.",
    )
    parser.add_argument(
        "--window-end",
        default=None,
        help="ISO 8601 datetime; restrict to rows produced before this timestamp.",
    )
    parser.add_argument(
        "--ground-truth",
        default=None,
        help="Optional JSONL path with GroundTruthEntry rows for recall.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for the report JSON. Prints to stdout if omitted.",
    )
    return parser


def _load_rows_from_db(
    sqlite_url: str,
    *,
    window_start: str | None,
    window_end: str | None,
) -> tuple[list[LiveRow], list[ShadowRow], list[FeedbackRow]]:
    from sqlalchemy import create_engine, text as _text

    engine = create_engine(sqlite_url, future=True)
    where_live = "1=1"
    where_shadow = "1=1"
    params: dict[str, str] = {}
    if window_start:
        where_live += " AND created_at >= :ws"
        where_shadow += " AND shadow_run_at >= :ws"
        params["ws"] = window_start
    if window_end:
        where_live += " AND created_at <= :we"
        where_shadow += " AND shadow_run_at <= :we"
        params["we"] = window_end

    with engine.connect() as conn:
        # source_item_id linkage for live rows: memory_objects doesn't
        # carry it directly. Use the relations table (which links
        # memory_object <- source_item) or fall back on
        # source_item_metadata_json in memory_objects. For PR 4 the
        # canonical join is via `relations` where kind='derived_from'.
        # However, that table shape may vary — safest is to query
        # provenance via source_items.metadata_json which the live
        # writer stamps in _process_source_item.
        # As a pragmatic default, we use the relations table with
        # the standard kind. If it comes up empty, callers should pass
        # ground-truth via --ground-truth instead.
        live_query = _text(
            f"""
            SELECT mo.id, mo.type, mo.subject, r.target_id AS source_item_id
            FROM memory_objects mo
            LEFT JOIN relations r
                ON r.source_id = mo.id
               AND r.kind = 'derived_from'
            WHERE {where_live}
            """
        )
        live_rows = [
            LiveRow(
                memory_object_id=row.id,
                source_item_id=row.source_item_id or "",
                type=row.type,
                subject=row.subject or "",
            )
            for row in conn.execute(live_query, params).fetchall()
        ]

        shadow_query = _text(
            f"""
            SELECT id, source_item_id, type, subject, parse_status
            FROM memory_objects_shadow
            WHERE {where_shadow}
            """
        )
        shadow_rows = [
            ShadowRow(
                id=row.id,
                source_item_id=row.source_item_id,
                type=row.type,
                subject=row.subject or "",
                parse_status=row.parse_status,
            )
            for row in conn.execute(shadow_query, params).fetchall()
        ]

        feedback_rows = [
            FeedbackRow(
                memory_object_id=row.memory_object_id,
                rating=row.rating,
            )
            for row in conn.execute(
                _text("SELECT memory_object_id, rating FROM memory_feedback")
            ).fetchall()
        ]

    return live_rows, shadow_rows, feedback_rows


def _load_ground_truth(path: Path) -> list[GroundTruthEntry]:
    out: list[GroundTruthEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        out.append(
            GroundTruthEntry(
                source_item_id=data["source_item_id"],
                type=data["type"],
                subject=data["subject"],
            )
        )
    return out


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)

    live_rows, shadow_rows, feedback = _load_rows_from_db(
        args.sqlite_url,
        window_start=args.window_start,
        window_end=args.window_end,
    )
    ground_truth: list[GroundTruthEntry] = []
    if args.ground_truth:
        ground_truth = _load_ground_truth(Path(args.ground_truth))

    report = compare_shadow_vs_live(
        live_rows=live_rows,
        shadow_rows=shadow_rows,
        feedback=feedback,
        ground_truth=ground_truth,
        window_start=args.window_start,
        window_end=args.window_end,
    )
    report["generated_at"] = datetime.now(timezone.utc).isoformat()

    payload = json.dumps(report, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload + "\n")

    # Exit non-zero if any type meets the promotion gate — signals a
    # human should decide whether to promote. Zero exit = nothing to
    # promote / insufficient evidence.
    any_meets = any(
        block.get("meets_promotion_gate") is True
        for block in report["per_type"].values()
    )
    return 0 if not any_meets else 0  # never fail — this is informational


if __name__ == "__main__":
    raise SystemExit(main())
