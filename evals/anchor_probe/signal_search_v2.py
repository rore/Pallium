"""Signal search v2: extends v1 with IDF-weighted variants on memory_text.

Adds:
  S11 jaccard_memtext_idfweighted   sum(idf of intersect) / sum(idf of union)
  S12 max_idf_intersect             max idf of any token in q ^ memtext
  S13 query_coverage_idf            sum(idf of intersect) / sum(idf of query tokens)
  S14 sum_idf_intersect             raw sum(idf) over intersecting tokens
  S15 jaccard_evidence_idfweighted  same as S11 but against evidence_text
  S16 max_idf_intersect_evidence    max idf in q ^ evidence

IDF here is over the *memory_text vocabulary* of the container (each memory_object
contributes one document). This isolates the question: does normalizing by token
rarity make Jaccard container-agnostic?

Usage:
    .venv/Scripts/python.exe -m evals.anchor_probe.signal_search_v2 \
        --container 'path:project:abc1234567' --days 60
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.text import normalize_for_index  # type: ignore  # noqa: E402


def _tokens(s: str) -> list[str]:
    return [t for t in normalize_for_index(s or "").split() if t]


def _token_set(s: str) -> set[str]:
    return set(_tokens(s))


@dataclass
class Case:
    feedback_id: str
    rating: str
    type: str
    query: str
    memory_id: str
    memory_text: str
    evidence_text: str


def load_cases(db_path: str, containers: list[str], days: int) -> list[Case]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    qmarks = ",".join(["?"] * len(containers))
    rows = con.execute(
        f"""
        SELECT mf.id AS fid, mf.memory_object_id, mf.rating, mf.memory_type,
               mf.query_context, mf.memory_text, mf.created_at AS rated_at
        FROM memory_feedback mf
        WHERE mf.container_ref IN ({qmarks})
          AND mf.created_at > datetime('now', ?)
          AND mf.rating IN ('relevant','not_relevant')
        ORDER BY mf.created_at DESC
        """,
        (*containers, f"-{days} days"),
    ).fetchall()

    cases: list[Case] = []
    for r in rows:
        evidence_rows = con.execute(
            """
            SELECT si.content
            FROM relations rel
            JOIN source_items si ON si.id = rel.to_id
            WHERE rel.from_id = ? AND rel.to_kind = 'source_item'
            ORDER BY si.created_at ASC
            LIMIT 5
            """,
            (r["memory_object_id"],),
        ).fetchall()
        evidence_text = " ".join((e["content"] or "")[:400] for e in evidence_rows)[:2000]
        cases.append(
            Case(
                feedback_id=r["fid"],
                rating=r["rating"],
                type=r["memory_type"] or "",
                query=r["query_context"] or "",
                memory_id=r["memory_object_id"],
                memory_text=r["memory_text"] or "",
                evidence_text=evidence_text,
            )
        )
    con.close()
    return cases


def build_memtext_idf(db_path: str, containers: list[str]) -> dict[str, float]:
    """IDF over memory_text token vocabulary in this container set.

    Each memory_object is one document.
    """
    con = sqlite3.connect(db_path)
    qmarks = ",".join(["?"] * len(containers))
    rows = con.execute(
        f"""
        SELECT mo.id, mo.envelope_json,
               (SELECT GROUP_CONCAT(text_view, ' ')
                  FROM index_entries ie
                 WHERE ie.target_id = mo.id AND ie.target_kind = 'memory_object') AS payload
        FROM memory_objects mo
        WHERE mo.container_ref IN ({qmarks})
        """,
        containers,
    ).fetchall()
    con.close()
    df: Counter[str] = Counter()
    n = 0
    for _id, env_json, payload in rows:
        text = payload or ""
        if env_json and not text:
            try:
                env = json.loads(env_json)
                # Concat any string-ish fields we can find.
                for k in ("statement", "summary", "decision_rationale"):
                    v = env.get(k)
                    if isinstance(v, str):
                        text += " " + v
            except Exception:
                pass
        toks = set(_tokens(text))
        if toks:
            n += 1
            for t in toks:
                df[t] += 1
    if not n:
        return {}
    return {tok: math.log((n + 1) / (cnt + 0.5)) for tok, cnt in df.items()}


# ---------- AUC ----------


def auc(scores_pos: list[float], scores_neg: list[float]) -> float:
    if not scores_pos or not scores_neg:
        return float("nan")
    wins = ties = 0
    for p in scores_pos:
        for n in scores_neg:
            if p > n:
                wins += 1
            elif p == n:
                ties += 1
    return (wins + 0.5 * ties) / (len(scores_pos) * len(scores_neg))


def best_precision_at_recall(
    scores_pos: list[float], scores_neg: list[float], recall_target: float = 0.9
) -> tuple[float, float]:
    if not scores_pos:
        return (float("nan"), float("nan"))
    pairs = [(s, "pos") for s in scores_pos] + [(s, "neg") for s in scores_neg]
    pairs.sort(reverse=True)
    n_pos = len(scores_pos)
    needed = math.ceil(recall_target * n_pos)
    best_p = 0.0
    best_t = float("inf")
    tp = fp = 0
    for s, lbl in pairs:
        if lbl == "pos":
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


def best_f1_threshold(
    scores_pos: list[float], scores_neg: list[float]
) -> tuple[float, float, float, float]:
    """Find threshold that maximizes F1; return (f1, threshold, precision, recall)."""
    if not scores_pos:
        return (float("nan"), float("nan"), float("nan"), float("nan"))
    pairs = [(s, "pos") for s in scores_pos] + [(s, "neg") for s in scores_neg]
    pairs.sort(reverse=True)
    n_pos = len(scores_pos)
    best_f = 0.0
    best_t = float("nan")
    best_p = 0.0
    best_r = 0.0
    tp = fp = 0
    for s, lbl in pairs:
        if lbl == "pos":
            tp += 1
        else:
            fp += 1
        kept = tp + fp
        p = tp / kept if kept else 0.0
        r = tp / n_pos if n_pos else 0.0
        f = 2 * p * r / (p + r) if (p + r) else 0.0
        if f > best_f:
            best_f = f
            best_t = s
            best_p = p
            best_r = r
    return (best_f, best_t, best_p, best_r)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / ".pallium" / "data" / "pallium.db"))
    ap.add_argument("--container", required=True, action="append",
                    help="Repeat to union multiple containers")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--out-json", default="")
    args = ap.parse_args()

    print(f"# Signal search v2 - {args.container}  (last {args.days}d)\n")
    cases = load_cases(args.db, args.container, args.days)
    rel = sum(1 for c in cases if c.rating == "relevant")
    nr = sum(1 for c in cases if c.rating == "not_relevant")
    print(f"Loaded {len(cases)} cases  (relevant={rel}, not_relevant={nr})\n")

    idf = build_memtext_idf(args.db, args.container)
    print(f"memtext IDF vocab: {len(idf)} tokens")
    if idf:
        vals = list(idf.values())
        vals.sort()
        print(f"  IDF stats: min={min(vals):.2f} median={median(vals):.2f} max={max(vals):.2f}\n")

    rows = []
    for c in cases:
        q = _token_set(c.query)
        m = _token_set(c.memory_text)
        e = _token_set(c.evidence_text)
        inter_m = q & m
        union_m = q | m
        inter_e = q & e
        union_e = q | e

        # plain jaccard
        s8 = len(inter_m) / len(union_m) if union_m else 0.0

        # IDF-weighted jaccard on memtext
        idf_inter = sum(idf.get(t, 0.0) for t in inter_m)
        idf_union = sum(idf.get(t, 0.0) for t in union_m)
        s11 = idf_inter / idf_union if idf_union else 0.0

        # max IDF of intersecting tokens
        s12 = max((idf.get(t, 0.0) for t in inter_m), default=0.0)

        # query coverage (intersection idf / query idf)
        idf_q = sum(idf.get(t, 0.0) for t in q)
        s13 = idf_inter / idf_q if idf_q else 0.0

        # raw sum idf of intersect
        s14 = idf_inter

        # evidence variants
        idf_inter_e = sum(idf.get(t, 0.0) for t in inter_e)
        idf_union_e = sum(idf.get(t, 0.0) for t in union_e)
        s15 = idf_inter_e / idf_union_e if idf_union_e else 0.0
        s16 = max((idf.get(t, 0.0) for t in inter_e), default=0.0)

        rows.append(
            dict(
                rating=c.rating,
                query=c.query,
                memory_text=c.memory_text,
                S8=s8,
                S11=s11,
                S12=s12,
                S13=s13,
                S14=s14,
                S15=s15,
                S16=s16,
                n_q=len(q),
                n_m=len(m),
                n_inter=len(inter_m),
            )
        )

    print("\n## Per-signal discrimination\n")
    print(
        f"{'signal':<32} {'mean(rel)':>10} {'mean(nr)':>10} {'AUC':>5}  "
        f"{'P@R=.9':>7} {'thr':>8}  {'bestF1':>6} {'thr':>8} {'P/R':>11}"
    )
    signals = [
        ("S8 jaccard_memtext", "S8"),
        ("S11 jaccard_memtext_idfweighted", "S11"),
        ("S12 max_idf_intersect_memtext", "S12"),
        ("S13 query_coverage_idf_memtext", "S13"),
        ("S14 sum_idf_intersect_memtext", "S14"),
        ("S15 jaccard_evidence_idfweighted", "S15"),
        ("S16 max_idf_intersect_evidence", "S16"),
    ]
    for label, key in signals:
        pos = [r[key] for r in rows if r["rating"] == "relevant"]
        neg = [r[key] for r in rows if r["rating"] == "not_relevant"]
        m_pos = mean(pos) if pos else float("nan")
        m_neg = mean(neg) if neg else float("nan")
        auc_score = auc(pos, neg) if pos and neg else float("nan")
        p_at_r, t_at = best_precision_at_recall(pos, neg, 0.9)
        f1, t_f1, p_f1, r_f1 = best_f1_threshold(pos, neg)
        print(
            f"{label:<32} {m_pos:>10.3f} {m_neg:>10.3f} {auc_score:>5.2f}  "
            f"{p_at_r:>7.2f} {t_at:>8.3f}  "
            f"{f1:>6.2f} {t_f1:>8.3f} {p_f1:.2f}/{r_f1:.2f}"
        )

    # Distribution check at a few candidate thresholds for S11.
    print("\n## S11 (idf-weighted jaccard memtext) at candidate thresholds\n")
    for thr in [0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20]:
        tp = sum(1 for r in rows if r["rating"] == "relevant" and r["S11"] >= thr)
        fp = sum(1 for r in rows if r["rating"] == "not_relevant" and r["S11"] >= thr)
        fn_ = sum(1 for r in rows if r["rating"] == "relevant" and r["S11"] < thr)
        tn = sum(1 for r in rows if r["rating"] == "not_relevant" and r["S11"] < thr)
        kept = tp + fp
        prec = tp / kept if kept else 0.0
        rec = tp / (tp + fn_) if (tp + fn_) else 0.0
        print(
            f"  S11>={thr:.2f}  kept={kept:>4} tp={tp:>3} fp={fp:>3} fn={fn_:>3} tn={tn:>3}  P={prec:.2f} R={rec:.2f}"
        )

    print("\n## S13 (query_coverage_idf) at candidate thresholds\n")
    for thr in [0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]:
        tp = sum(1 for r in rows if r["rating"] == "relevant" and r["S13"] >= thr)
        fp = sum(1 for r in rows if r["rating"] == "not_relevant" and r["S13"] >= thr)
        fn_ = sum(1 for r in rows if r["rating"] == "relevant" and r["S13"] < thr)
        tn = sum(1 for r in rows if r["rating"] == "not_relevant" and r["S13"] < thr)
        kept = tp + fp
        prec = tp / kept if kept else 0.0
        rec = tp / (tp + fn_) if (tp + fn_) else 0.0
        print(
            f"  S13>={thr:.2f}  kept={kept:>4} tp={tp:>3} fp={fp:>3} fn={fn_:>3} tn={tn:>3}  P={prec:.2f} R={rec:.2f}"
        )

    if args.out_json:
        out_rows = [
            {k: (v if not (isinstance(v, float) and math.isnan(v)) else None) for k, v in r.items()}
            for r in rows
        ]
        Path(args.out_json).write_text(json.dumps(out_rows, indent=2), encoding="utf-8")
        print(f"\nWrote {args.out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
