"""Audit signal probe: pull the saved per-candidate scores Pallium computed at
inject-time (routing_score, lexical_score, vector_score, routing_rank, layer)
and check how well they predict the relevant/not_relevant rating that the user
applied to the target memory.

We're looking for an existing internal score that already separates the labels
- if so the fix is at scoring/threshold not at gate.

Usage:
    .venv/Scripts/python.exe -m evals.anchor_probe.audit_signal_probe \
        --container 'path:project:abc1234567' --days 60
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from pathlib import Path
from statistics import mean, median


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def load(db: str, container: str, days: int):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT mf.id AS fid, mf.memory_object_id AS mid, mf.rating, mf.memory_type,
               mf.query_context,
               qal.candidate_scores_json, qal.injection_method, qal.decision_reason
        FROM memory_feedback mf
        LEFT JOIN query_audit_log qal ON qal.id = mf.query_audit_log_id
        WHERE mf.container_ref = ?
          AND mf.created_at > datetime('now', ?)
          AND mf.rating IN ('relevant','not_relevant')
        ORDER BY mf.created_at DESC
        """,
        (container, f"-{days} days"),
    ).fetchall()
    con.close()
    return rows


def auc(pos, neg):
    if not pos or not neg:
        return float("nan")
    wins = ties = 0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1
            elif p == n:
                ties += 1
    return (wins + 0.5 * ties) / (len(pos) * len(neg))


def best_p_at_r(pos, neg, target=0.9):
    if not pos:
        return (float("nan"), float("nan"))
    pairs = [(s, "p") for s in pos] + [(s, "n") for s in neg]
    pairs.sort(reverse=True)
    needed = math.ceil(target * len(pos))
    best_p = 0.0
    best_t = float("nan")
    tp = fp = 0
    for s, lbl in pairs:
        if lbl == "p":
            tp += 1
        else:
            fp += 1
        if tp >= needed:
            kept = tp + fp
            p = tp / kept if kept else 0.0
            if p > best_p:
                best_p = p
                best_t = s
    return (best_p, best_t)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / ".pallium" / "data" / "pallium.db"))
    ap.add_argument("--container", required=True, action="append")
    ap.add_argument("--days", type=int, default=60)
    args = ap.parse_args()

    rows = []
    for cont in args.container:
        rows.extend(load(args.db, cont, args.days))
    print(f"# Audit-signal probe - {args.container} (last {args.days}d)\n")
    print(f"loaded {len(rows)} rated cases")

    by_method: dict[str, int] = {}
    targets = []  # one row per rated case (the target candidate)
    target_rank_dist = {"rel": [], "nr": []}
    n_no_audit = 0
    n_no_target = 0
    layer_count = {"rel": {}, "nr": {}}

    for r in rows:
        cs_json = r["candidate_scores_json"]
        method = r["injection_method"] or "?"
        by_method.setdefault(method, 0)
        by_method[method] += 1
        if not cs_json:
            n_no_audit += 1
            continue
        cs = json.loads(cs_json)
        target = next((c for c in cs if c.get("memory_object_id") == r["mid"]), None)
        if not target:
            n_no_target += 1
            continue
        rating = r["rating"]
        bucket = "rel" if rating == "relevant" else "nr"
        target_rank_dist[bucket].append(target.get("routing_rank") or -1)
        layer = target.get("layer") or "?"
        layer_count[bucket].setdefault(layer, 0)
        layer_count[bucket][layer] += 1
        # gather scores from cohort (all candidates) for context
        cohort_scores = [c.get("routing_score") for c in cs if c.get("routing_score") is not None]
        cohort_lex = [c.get("lexical_score") for c in cs if c.get("lexical_score") is not None]
        cohort_vec = [c.get("vector_score") for c in cs if c.get("vector_score") is not None]
        targets.append(
            dict(
                rating=rating,
                fid=r["fid"],
                method=method,
                memory_type=r["memory_type"],
                routing_score=target.get("routing_score"),
                lexical_score=target.get("lexical_score"),
                vector_score=target.get("vector_score"),
                routing_rank=target.get("routing_rank"),
                layer=target.get("layer"),
                support_grade=target.get("support_grade"),
                cohort_max_routing=max(cohort_scores) if cohort_scores else None,
                cohort_max_lexical=max(cohort_lex) if cohort_lex else None,
                cohort_max_vector=max(cohort_vec) if cohort_vec else None,
                cohort_size=len(cs),
            )
        )

    print(f"  no audit join: {n_no_audit}")
    print(f"  audit but target missing: {n_no_target}")
    print(f"  injection_method breakdown: {by_method}")
    print(
        f"  cases scored: {len(targets)} (rel={sum(1 for t in targets if t['rating']=='relevant')} "
        f"nr={sum(1 for t in targets if t['rating']=='not_relevant')})\n"
    )

    print("layer distribution (target memory):")
    print(f"  relevant     : {layer_count['rel']}")
    print(f"  not_relevant : {layer_count['nr']}\n")

    print("target routing_rank distribution:")
    for b in ("rel", "nr"):
        ranks = target_rank_dist[b]
        if ranks:
            print(
                f"  {b:<3}: n={len(ranks)} min={min(ranks)} max={max(ranks)} "
                f"mean={mean(ranks):.1f} median={median(ranks):.1f}"
            )

    print("\n## Per-signal AUC (target candidate)\n")
    print(f"{'signal':<28} {'n_pos':>5} {'n_neg':>5} {'mean(rel)':>10} {'mean(nr)':>10} {'AUC':>5}  {'P@R=.9':>7} {'thr':>9}")
    keys = [
        "routing_score",
        "lexical_score",
        "vector_score",
        "routing_rank",  # lower is better
        "cohort_max_routing",
        "cohort_max_lexical",
        "cohort_max_vector",
    ]
    for k in keys:
        pos = [t[k] for t in targets if t["rating"] == "relevant" and t[k] is not None]
        neg = [t[k] for t in targets if t["rating"] == "not_relevant" and t[k] is not None]
        if not pos and not neg:
            print(f"{k:<28}  no data")
            continue
        m_p = mean(pos) if pos else float("nan")
        m_n = mean(neg) if neg else float("nan")
        a = auc(pos, neg) if pos and neg else float("nan")
        # for routing_rank, lower=better; flip for AUC reporting
        if k == "routing_rank" and not math.isnan(a) and a < 0.5:
            a_alt = 1.0 - a
            note = " (lower=better, AUC inverted)"
        else:
            a_alt = a
            note = ""
        p_at_r, t_at = best_p_at_r(pos, neg, 0.9)
        print(
            f"{k:<28} {len(pos):>5} {len(neg):>5} {m_p:>10.3f} {m_n:>10.3f} {a_alt:>5.2f}  "
            f"{p_at_r:>7.2f} {t_at:>9.3f}{note}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
