"""Phase 2a — approximate historical decision-simulation replay.

See: docs/specs/2026-06-27-injection-policy-abstention.md (Phase 2a).

**Framing.** Phase 1 established that no memory type meets the spec's
>=70% precision bar on held-out data. Phase 2a is therefore an
AUDIT-TRAIL artifact, not a validation step. It answers two questions:

1. If we had shipped the spec's original headline thresholds
   (constraint_memory>=20, decision>=22, task_checkpoint>=14), what
   would production have actually done?
2. Does Phase 1's filter-over-injected math under-count what the full
   selection path would have produced under the proposed policy?

It does not — and cannot — rehabilitate any type for proactive
injection. The Phase 1 result stands.

**Approximation.** Historical query_audit_log.candidate_scores_json does
NOT carry the result `score` field (Phase 0.5 started capturing it but
historical rows pre-date that). Phase 2a therefore gates on
`routing_score`, which is what IS in the historical snapshots. Per
Codex's prior review, applying the same numeric thresholds to
routing_score yields ~52% precision versus ~76% on the result score —
i.e. routing_score is a SIGNIFICANTLY WEAKER signal. Phase 2b will
re-run this with the correct field once fresh data accumulates.

**Scope.** Minimum-viable selection simulation:
- type-aware allowlist (only types in the variant's thresholds dict),
- per-type score threshold gate,
- top-K cap (matching production INJECTION_HARD_CEILING).

It explicitly does NOT replay anchor-prefilter tiers, override
strategies, content-overlap gates, set-level should_allow_injection, or
recall-mode-specific dedup. Those depend on data that wasn't
snapshotted.

Two variants are reported side-by-side:
- `spec_headline`: the thresholds the spec was written against
  (constraint_memory>=20, decision>=22, task_checkpoint>=14).
- `phase1_derived`: the thresholds Phase 1 derived from train data
  (constraint_memory>=12, decision>=19, investigation_outcome>=23,
  task_checkpoint>=13). These failed the >=70% holdout bar but are
  the data's best per-type cuts on train.

Run:
    python -m evals.injection_policy_2026_06.decision_replay
    python -m evals.injection_policy_2026_06.decision_replay --output report.json
"""

from __future__ import annotations

import argparse
import json
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
from evals.retrieval_ablation.evaluate import (  # noqa: E402
    FeedbackEntry,
    build_feedback_index,
    majority_rating,
)


# Phase 2a constants --------------------------------------------------------

# Historical candidate snapshots do NOT carry the result `score` field.
# Phase 2a gates on routing_score — see module docstring for the
# precision-cost caveat.
SCORE_FIELD = "routing_score"

# Spec headline thresholds — what the spec was written against.
SPEC_HEADLINE_THRESHOLDS: dict[str, float] = {
    "constraint_memory": 20.0,
    "decision": 22.0,
    "task_checkpoint": 14.0,
}

# Phase 1 holdout-derived thresholds. Sourced from
# evals/injection_policy_2026_06/holdout_2026-06-27.json's train slice.
# These failed the >=70% holdout pass bar; they are the data's best cuts
# on train. Phase 2a reports both side-by-side.
PHASE1_DERIVED_THRESHOLDS: dict[str, float] = {
    "constraint_memory": 12.0,
    "decision": 19.0,
    "investigation_outcome": 23.0,
    "task_checkpoint": 13.0,
}

# Production cap on injected blocks per query. Matches the routing/selection
# top-K bound — exact value is approximate (production may use different
# caps in different lanes). Documented as part of the approximation.
TOP_K_CAP = 5

# Caveat string surfaced into the report and shown to readers.
SCORE_FIELD_CAVEAT = (
    "Phase 2a gates on routing_score because historical "
    "candidate_scores_json rows do NOT carry the result `score` field "
    "(Phase 0.5 started capturing it; historical rows pre-date that). "
    "Per Codex's prior review, the same thresholds applied to "
    "routing_score yield ~52% precision vs ~76% on result score — i.e. "
    "routing_score is a weaker signal. Phase 2b will re-run with the "
    "correct field once fresh data accumulates."
)

FRAMING = (
    "Phase 1 established that no memory type meets the spec's >=70% "
    "precision bar on held-out data. Phase 2a is an audit-trail "
    "artifact, not a validation step. It does not — and cannot — "
    "rehabilitate any type for proactive injection."
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CandidateRecord:
    memory_object_id: str
    memory_type: str
    score: float | None
    injected_in_prod: bool


@dataclass
class ReplayVariant:
    name: str
    thresholds: dict[str, float]
    top_k_cap: int = TOP_K_CAP


@dataclass
class VariantTotals:
    queries_evaluated: int = 0
    queries_skipped_no_candidates: int = 0
    queries_skipped_corrupt_json: int = 0
    candidates_total: int = 0
    candidates_no_score: int = 0
    candidates_passed: int = 0  # type allow + threshold
    candidates_kept_after_topk: int = 0
    rated_relevant: int = 0
    rated_not_relevant: int = 0
    rated_unknown: int = 0  # kept but no feedback
    substituted_in: int = 0  # kept by sim, NOT injected in prod
    prod_dropped_by_sim: int = 0  # injected in prod, NOT kept by sim
    per_type: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(
        lambda: {"kept": 0, "rated_relevant": 0, "rated_not_relevant": 0,
                 "rated_unknown": 0}
    ))


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def load_audit_rows(conn) -> list[dict[str, Any]]:
    """Load audit rows that carry a candidate snapshot.

    Deterministic ordering by created_at, id.
    """
    cur = conn.execute(
        """
        SELECT id              AS query_audit_log_id,
               created_at      AS audit_created_at,
               container_ref   AS audit_container_ref,
               candidate_scores_json,
               injected_blocks_json
        FROM query_audit_log
        WHERE candidate_scores_json IS NOT NULL
        ORDER BY created_at ASC, id ASC
        """
    )
    return [dict(row) for row in cur.fetchall()]


def load_feedback_rows(conn) -> list[dict[str, Any]]:
    """Load all feedback joined to its audit log row, for rating index build."""
    cur = conn.execute(
        """
        SELECT mf.memory_object_id,
               mf.rating,
               mf.memory_type,
               mf.query_context,
               mf.query_audit_log_id
        FROM memory_feedback mf
        WHERE mf.rating IN ('relevant', 'not_relevant')
          AND mf.query_audit_log_id IS NOT NULL
        """
    )
    return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_candidates(
    blob: str | None,
    injected_ids: frozenset[str],
) -> tuple[list[CandidateRecord], int]:
    """Parse one candidate_scores_json blob into typed records.

    Returns (records_with_score, n_skipped_no_score).
    """
    if not blob:
        return [], 0
    try:
        raw = json.loads(blob)
    except (TypeError, ValueError):
        return [], 0
    if not isinstance(raw, list):
        return [], 0
    out: list[CandidateRecord] = []
    no_score = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        mid = item.get("memory_object_id")
        mtype = item.get("memory_type")
        score = item.get(SCORE_FIELD)
        if not mid or not mtype:
            continue
        if score is None:
            no_score += 1
            continue
        out.append(CandidateRecord(
            memory_object_id=mid,
            memory_type=mtype,
            score=float(score),
            injected_in_prod=mid in injected_ids,
        ))
    return out, no_score


def parse_injected_ids(blob: str | None) -> frozenset[str]:
    if not blob:
        return frozenset()
    try:
        raw = json.loads(blob)
    except (TypeError, ValueError):
        return frozenset()
    if not isinstance(raw, list):
        return frozenset()
    out = {item.get("memory_object_id")
           for item in raw
           if isinstance(item, dict) and item.get("memory_object_id")}
    return frozenset(out)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


def simulate_variant_for_query(
    candidates: list[CandidateRecord],
    variant: ReplayVariant,
) -> list[CandidateRecord]:
    """Apply one variant's policy to one query's candidates.

    Rules (in order):
      1. Drop candidates whose memory_type is not in variant.thresholds.
      2. Drop candidates whose score is None or < variant.thresholds[type].
      3. Sort survivors by score DESC, memory_object_id ASC (deterministic
         tie-break).
      4. Keep top variant.top_k_cap.
    """
    survivors: list[CandidateRecord] = []
    for c in candidates:
        thr = variant.thresholds.get(c.memory_type)
        if thr is None:
            continue
        if c.score is None or c.score < thr:
            continue
        survivors.append(c)
    survivors.sort(key=lambda c: (-c.score if c.score is not None else 0.0,
                                   c.memory_object_id))
    return survivors[: variant.top_k_cap]


def rating_for(
    memory_object_id: str,
    query_audit_log_id: str,
    index: dict[tuple[str, str], list[FeedbackEntry]],
) -> str | None:
    """Per-event majority rating using the analytic key (memory, query)."""
    entries = index.get((memory_object_id, query_audit_log_id))
    if not entries:
        return None
    return majority_rating(entries)


def run_variant(
    audit_rows: list[dict[str, Any]],
    feedback_index: dict[tuple[str, str], list[FeedbackEntry]],
    variant: ReplayVariant,
) -> tuple[VariantTotals, list[dict[str, Any]]]:
    """Run one variant across all audit rows.

    Returns (totals, divergence_diagnostics). divergence_diagnostics is a
    list of dicts describing would-have-substituted candidates (kept by
    sim but not injected in prod) — surfaced so reviewers can spot-check.
    """
    totals = VariantTotals()
    diagnostics: list[dict[str, Any]] = []

    for row in audit_rows:
        qa_id = row["query_audit_log_id"]
        injected_ids = parse_injected_ids(row.get("injected_blocks_json"))
        cands, no_score = parse_candidates(
            row.get("candidate_scores_json"), injected_ids
        )
        if not cands and no_score == 0:
            totals.queries_skipped_no_candidates += 1
            continue
        totals.queries_evaluated += 1
        totals.candidates_total += len(cands) + no_score
        totals.candidates_no_score += no_score

        # All scored candidates that pass type + threshold (pre-top-K).
        passing = [c for c in cands
                   if c.memory_type in variant.thresholds
                   and c.score is not None
                   and c.score >= variant.thresholds[c.memory_type]]
        totals.candidates_passed += len(passing)

        kept = simulate_variant_for_query(cands, variant)
        totals.candidates_kept_after_topk += len(kept)

        kept_ids: set[str] = set()
        for c in kept:
            kept_ids.add(c.memory_object_id)
            rating = rating_for(c.memory_object_id, qa_id, feedback_index)
            bucket = totals.per_type[c.memory_type]
            if rating == "relevant":
                totals.rated_relevant += 1
                bucket["rated_relevant"] += 1
            elif rating == "not_relevant":
                totals.rated_not_relevant += 1
                bucket["rated_not_relevant"] += 1
            else:
                totals.rated_unknown += 1
                bucket["rated_unknown"] += 1
            bucket["kept"] += 1
            if not c.injected_in_prod:
                totals.substituted_in += 1
                diagnostics.append({
                    "query_audit_log_id": qa_id,
                    "substituted_memory_object_id": c.memory_object_id,
                    "memory_type": c.memory_type,
                    "score": c.score,
                    "variant": variant.name,
                })

        # Anything injected in prod but NOT kept by the sim is a prod-drop.
        for mid in injected_ids:
            if mid not in kept_ids:
                totals.prod_dropped_by_sim += 1

    # convert defaultdict to plain dict for serialization
    totals.per_type = {k: dict(v) for k, v in totals.per_type.items()}  # type: ignore[assignment]
    return totals, diagnostics


def variant_precision(totals: VariantTotals) -> float | None:
    denom = totals.rated_relevant + totals.rated_not_relevant
    if denom == 0:
        return None
    return totals.rated_relevant / denom


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def build_replay_report(
    audit_rows: list[dict[str, Any]],
    feedback_index: dict[tuple[str, str], list[FeedbackEntry]],
    variants: list[ReplayVariant],
) -> dict[str, Any]:
    per_variant: dict[str, dict[str, Any]] = {}
    for variant in variants:
        totals, diagnostics = run_variant(audit_rows, feedback_index, variant)
        per_variant[variant.name] = {
            "thresholds": variant.thresholds,
            "top_k_cap": variant.top_k_cap,
            "totals": {
                "queries_evaluated": totals.queries_evaluated,
                "queries_skipped_no_candidates": totals.queries_skipped_no_candidates,
                "candidates_total": totals.candidates_total,
                "candidates_no_score": totals.candidates_no_score,
                "candidates_passed_pre_topk": totals.candidates_passed,
                "candidates_kept_after_topk": totals.candidates_kept_after_topk,
                "rated_relevant": totals.rated_relevant,
                "rated_not_relevant": totals.rated_not_relevant,
                "rated_unknown": totals.rated_unknown,
                "substituted_in": totals.substituted_in,
                "prod_dropped_by_sim": totals.prod_dropped_by_sim,
                "precision_rated_subset": variant_precision(totals),
            },
            "per_type": totals.per_type,
            "divergence_diagnostics_sample": diagnostics[:20],
            "n_divergence_total": len(diagnostics),
        }

    return {
        "spec": "docs/specs/2026-06-27-injection-policy-abstention.md",
        "phase": "2a — approximate historical decision-simulation replay",
        "framing": FRAMING,
        "score_field_used": SCORE_FIELD,
        "score_field_caveat": SCORE_FIELD_CAVEAT,
        "top_k_cap": TOP_K_CAP,
        "n_audit_rows": len(audit_rows),
        "n_feedback_keys": len(feedback_index),
        "variants": per_variant,
    }


def format_text_summary(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("=== Phase 2a — Approximate Historical Replay ===")
    lines.append("")
    lines.append(f"score field used: {report['score_field_used']}")
    lines.append(f"top-K cap: {report['top_k_cap']}")
    lines.append(f"n audit rows: {report['n_audit_rows']}  "
                 f"n feedback (mem,query): {report['n_feedback_keys']}")
    lines.append("")
    lines.append("Framing: " + report["framing"])
    lines.append("")
    lines.append("Variants:")
    for vname, vinfo in report["variants"].items():
        t = vinfo["totals"]
        prec = t["precision_rated_subset"]
        prec_str = f"{prec:.2%}" if prec is not None else "n/a"
        lines.append(
            f"  {vname:<18} thresholds={vinfo['thresholds']}"
        )
        lines.append(
            f"    queries={t['queries_evaluated']:>4}  cand_total={t['candidates_total']:>5}  "
            f"passed_pre_topk={t['candidates_passed_pre_topk']:>4}  "
            f"kept_after_topk={t['candidates_kept_after_topk']:>4}"
        )
        lines.append(
            f"    rated_rel={t['rated_relevant']:>4}  rated_bad={t['rated_not_relevant']:>4}  "
            f"unrated_kept={t['rated_unknown']:>4}  precision={prec_str}"
        )
        lines.append(
            f"    substituted_in={t['substituted_in']}  "
            f"prod_dropped_by_sim={t['prod_dropped_by_sim']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_feedback_index_keyed(
    feedback_rows: list[dict[str, Any]],
) -> dict[tuple[str, str], list[FeedbackEntry]]:
    """Build (memory_object_id, query_audit_log_id) -> [FeedbackEntry].

    Unlike build_feedback_index in retrieval_ablation/evaluate.py, this is
    keyed by the (memory, query) PAIR — every rating is anchored to a
    specific injection event, not pooled across all injections of the same
    memory.
    """
    index: dict[tuple[str, str], list[FeedbackEntry]] = defaultdict(list)
    for row in feedback_rows:
        mid = row.get("memory_object_id")
        qa_id = row.get("query_audit_log_id")
        if not mid or not qa_id:
            continue
        index[(mid, qa_id)].append(FeedbackEntry(
            memory_object_id=mid,
            rating=row.get("rating", ""),
            query_context=row.get("query_context") or "",
            memory_type=row.get("memory_type") or "unknown",
        ))
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 2a approximate historical replay of abstention policy."
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH,
        help="Path to pallium.db (default: ~/.pallium/data/pallium.db)",
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
        audit_rows = load_audit_rows(conn)
        feedback_rows = load_feedback_rows(conn)
    finally:
        conn.close()

    feedback_index = _build_feedback_index_keyed(feedback_rows)
    variants = [
        ReplayVariant(name="spec_headline",
                      thresholds=dict(SPEC_HEADLINE_THRESHOLDS)),
        ReplayVariant(name="phase1_derived",
                      thresholds=dict(PHASE1_DERIVED_THRESHOLDS)),
    ]
    report = build_replay_report(audit_rows, feedback_index, variants)

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
