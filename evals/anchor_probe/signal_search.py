"""Signal search: rank candidate discriminators of relevant vs not_relevant
on real rated injection data.

For each rated case in a container, computes multiple candidate signals and
reports which ones actually separate the labels. Outputs:
  - per-signal mean(relevant) vs mean(not_relevant)
  - per-signal AUC (probability that a random relevant scores above a random
    not_relevant on this signal)
  - per-signal best precision@recall>=0.9 with the threshold that achieves it
  - simple combined-rule check: does (anchor overlap OR same-thread) help?

Signals tested:
  S1  anchor_overlap_full      binary    any token in any anchor value matches a query token
  S2  anchor_overlap_top7      binary    same, restricted to top-7 anchors by IDF
  S3  query_vs_memtext_cos     numeric   cosine(embed(query), embed(memory_text))
  S4  query_vs_evidence_cos    numeric   cosine(embed(query), embed(evidence concat from source items))
  S5  same_source_thread       binary    query thread_ref appears in memory source threads
  S6  source_thread_recent_h   numeric   hours since memory's source thread last had an item
  S7  memory_age_days          numeric   days since memory_object.created_at
  S8  memtext_jaccard_query    numeric   jaccard(query_tokens, memory_text_tokens)
  S9  query_vs_subject_cos     numeric   cosine(embed(query), embed(memory_objects.subject)) when present
  S10 query_vs_anchorbest_cos  numeric   prior probe baseline; max cos vs anchor values

Usage:
    .venv/Scripts/python.exe -m evals.anchor_probe.signal_search \
        --container 'path:project:abc1234567' --days 30
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

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
    anchors: list[dict]
    mo_subject: str | None
    mo_created_at: str | None
    audit_thread: str | None
    evidence_text: str
    source_threads: list[str]
    source_thread_last_seen_iso: str | None
    rating_created_at: str


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _hours_between(later_iso: str | None, earlier_iso: str | None) -> float | None:
    a = _parse_dt(later_iso)
    b = _parse_dt(earlier_iso)
    if a is None or b is None:
        return None
    delta = a - b
    return delta.total_seconds() / 3600.0


def load_cases(db_path: str, container: str, days: int) -> list[Case]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT mf.id AS fid, mf.memory_object_id, mf.rating, mf.memory_type,
               mf.query_context, mf.memory_text, mf.created_at AS rated_at,
               qal.thread_ref AS audit_thread,
               mo.envelope_json, mo.subject AS mo_subject, mo.created_at AS mo_created_at
        FROM memory_feedback mf
        LEFT JOIN query_audit_log qal ON qal.id = mf.query_audit_log_id
        LEFT JOIN memory_objects mo ON mo.id = mf.memory_object_id
        WHERE mf.container_ref = ?
          AND mf.created_at > datetime('now', ?)
          AND mf.rating IN ('relevant','not_relevant')
        ORDER BY mf.created_at DESC
        """,
        (container, f"-{days} days"),
    ).fetchall()

    cases: list[Case] = []
    for r in rows:
        env = json.loads(r["envelope_json"]) if r["envelope_json"] else {}
        anchors = [
            {"kind": str(a.get("kind") or ""), "value": str(a.get("value") or "").strip()}
            for a in (env.get("subjects") or [])
            if isinstance(a, dict) and a.get("value")
        ]
        # Pull source items supporting this memory.
        evidence_rows = con.execute(
            """
            SELECT si.thread_ref, si.content, si.created_at
            FROM relations rel
            JOIN source_items si ON si.id = rel.to_id
            WHERE rel.from_id = ? AND rel.to_kind = 'source_item'
            ORDER BY si.created_at ASC
            """,
            (r["memory_object_id"],),
        ).fetchall()
        evidence_text = " ".join(
            (e["content"] or "")[:400] for e in evidence_rows[:3]
        )[:1500]
        source_threads = sorted(
            {e["thread_ref"] for e in evidence_rows if e["thread_ref"]}
        )

        # Last activity in any source thread (across all source_items, not just supporters).
        last_seen: str | None = None
        if source_threads:
            qmarks = ",".join(["?"] * len(source_threads))
            row = con.execute(
                f"""
                SELECT MAX(created_at) AS last_at FROM source_items
                WHERE thread_ref IN ({qmarks}) AND container_ref = ?
                """,
                (*source_threads, container),
            ).fetchone()
            last_seen = row["last_at"] if row else None

        cases.append(
            Case(
                feedback_id=r["fid"],
                rating=r["rating"],
                type=r["memory_type"] or "",
                query=r["query_context"] or "",
                memory_id=r["memory_object_id"],
                memory_text=r["memory_text"] or "",
                anchors=anchors,
                mo_subject=r["mo_subject"],
                mo_created_at=r["mo_created_at"],
                audit_thread=r["audit_thread"],
                evidence_text=evidence_text,
                source_threads=source_threads,
                source_thread_last_seen_iso=last_seen,
                rating_created_at=r["rated_at"],
            )
        )
    con.close()
    return cases


def build_idf(db_path: str, container: str) -> dict[str, float]:
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT envelope_json FROM memory_objects WHERE container_ref = ? AND envelope_json IS NOT NULL",
        (container,),
    ).fetchall()
    con.close()
    from collections import Counter
    df: Counter[str] = Counter()
    n = 0
    for (env_json,) in rows:
        env = json.loads(env_json)
        anchors = env.get("subjects") or []
        toks: set[str] = set()
        for a in anchors:
            for t in _tokens(str(a.get("value") or "")):
                toks.add(t)
        if toks:
            n += 1
            for t in toks:
                df[t] += 1
    if not n:
        return {}
    return {tok: math.log((n + 1) / (cnt + 0.5)) for tok, cnt in df.items()}


def _score(value: str, idf: dict[str, float]) -> float:
    toks = _tokens(value)
    if not toks:
        return 0.0
    return sum(idf.get(t, 0.0) for t in toks) / len(toks)


def trim_anchors(anchors: list[dict], idf: dict[str, float], k: int) -> list[dict]:
    if len(anchors) <= k:
        return anchors
    return sorted(anchors, key=lambda a: _score(a["value"], idf), reverse=True)[:k]


def cosine(a: list[float], b: list[float]) -> float:
    s = na = nb = 0.0
    for x, y in zip(a, b):
        s += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return s / (math.sqrt(na) * math.sqrt(nb))


# ---------- AUC ----------


def auc(scores_pos: list[float], scores_neg: list[float]) -> float:
    """Probability that a random positive scores higher than a random negative.
    AUC=1.0 perfect, 0.5 chance.
    """
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
    """Find threshold T that maximizes precision while keeping recall >= target.
    'kept' = score >= T. Returns (precision, T). NaN/0.0 if infeasible.
    """
    if not scores_pos:
        return (float("nan"), float("nan"))
    pairs = [(s, "pos") for s in scores_pos] + [(s, "neg") for s in scores_neg]
    if not pairs:
        return (float("nan"), float("nan"))
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


# ---------- Embedding helper ----------


def build_embedder():
    from providers.embedding.onnx_provider import OnnxEmbeddingProvider  # type: ignore

    return OnnxEmbeddingProvider()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        default=str(Path.home() / ".pallium" / "data" / "pallium.db"),
    )
    ap.add_argument("--container", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--no-embed", action="store_true")
    ap.add_argument("--out-json", default="")
    args = ap.parse_args()

    print(f"# Signal search — {args.container}  (last {args.days}d)\n")

    cases = load_cases(args.db, args.container, args.days)
    rel = sum(1 for c in cases if c.rating == "relevant")
    nr = sum(1 for c in cases if c.rating == "not_relevant")
    print(f"Loaded {len(cases)} cases  (relevant={rel}, not_relevant={nr})\n")

    idf = build_idf(args.db, args.container)
    print(f"anchor IDF vocab: {len(idf)}\n")

    # Embedding pre-compute.
    embeds: dict[str, list[float]] = {}
    ep = None
    if not args.no_embed:
        try:
            ep = build_embedder()
        except Exception as e:
            print(f"WARN embedder init failed: {e}")
            args.no_embed = True
    if ep is not None:
        unique_strings: set[str] = set()
        for c in cases:
            for s in (c.query, c.memory_text, c.evidence_text, c.mo_subject or ""):
                if s:
                    unique_strings.add(s)
            for a in c.anchors:
                if a["value"]:
                    unique_strings.add(a["value"])
        unique_list = sorted(unique_strings)
        print(f"Embedding {len(unique_list)} unique strings ...")
        # Use 'passage' mode for everything except query strings; embed both modes for queries.
        # Simpler: embed everything as passage; embed queries again as 'query'.
        passages = ep.embed(unique_list, mode="passage")
        for s, v in zip(unique_list, passages):
            embeds[("p", s)] = v
        unique_queries = sorted({c.query for c in cases if c.query})
        qvecs = ep.embed(unique_queries, mode="query")
        for s, v in zip(unique_queries, qvecs):
            embeds[("q", s)] = v

    # ------ Compute signals per case ------
    rows = []
    for c in cases:
        q_tokens = _token_set(c.query)
        # S1 anchor overlap full
        s1 = any(
            any(t in q_tokens for t in _tokens(a["value"])) for a in c.anchors
        )
        # S2 anchor overlap top-7
        anc7 = trim_anchors(c.anchors, idf, 7)
        s2 = any(
            any(t in q_tokens for t in _tokens(a["value"])) for a in anc7
        )
        # S3 query vs memory_text
        s3 = float("nan")
        if not args.no_embed and c.query and c.memory_text:
            qv = embeds.get(("q", c.query))
            mv = embeds.get(("p", c.memory_text))
            if qv and mv:
                s3 = cosine(qv, mv)
        # S4 query vs evidence
        s4 = float("nan")
        if not args.no_embed and c.query and c.evidence_text:
            qv = embeds.get(("q", c.query))
            ev = embeds.get(("p", c.evidence_text))
            if qv and ev:
                s4 = cosine(qv, ev)
        # S5 same source thread
        s5 = bool(c.audit_thread and c.audit_thread in c.source_threads)
        # S6 source thread last activity (hours before rating timestamp)
        s6 = _hours_between(c.rating_created_at, c.source_thread_last_seen_iso)
        # S7 memory age (days)
        if c.mo_created_at:
            hours = _hours_between(c.rating_created_at, c.mo_created_at)
            s7 = hours / 24.0 if hours is not None else float("nan")
        else:
            s7 = float("nan")
        # S8 jaccard query vs memory_text
        m_tokens = _token_set(c.memory_text)
        if q_tokens and m_tokens:
            s8 = len(q_tokens & m_tokens) / len(q_tokens | m_tokens)
        else:
            s8 = 0.0
        # S9 query vs mo.subject
        s9 = float("nan")
        if not args.no_embed and c.query and c.mo_subject:
            qv = embeds.get(("q", c.query))
            sv = embeds.get(("p", c.mo_subject))
            if qv and sv:
                s9 = cosine(qv, sv)
        # S10 max cos query vs anchor values (recap of prior probe)
        s10 = float("nan")
        if not args.no_embed and c.query and c.anchors:
            qv = embeds.get(("q", c.query))
            avs = [embeds.get(("p", a["value"])) for a in c.anchors]
            avs = [v for v in avs if v]
            if qv and avs:
                s10 = max(cosine(qv, v) for v in avs)

        rows.append(
            dict(
                rating=c.rating,
                type=c.type,
                query=c.query,
                S1=int(s1),
                S2=int(s2),
                S3=s3,
                S4=s4,
                S5=int(s5),
                S6=s6 if s6 is not None else float("nan"),
                S7=s7,
                S8=s8,
                S9=s9,
                S10=s10,
                n_source_threads=len(c.source_threads),
            )
        )

    # ------ Signal report ------
    def _split(key, drop_nan=True):
        pos = [r[key] for r in rows if r["rating"] == "relevant"]
        neg = [r[key] for r in rows if r["rating"] == "not_relevant"]
        if drop_nan:
            pos = [v for v in pos if isinstance(v, (int, float)) and not math.isnan(v)]
            neg = [v for v in neg if isinstance(v, (int, float)) and not math.isnan(v)]
        return pos, neg

    print("\n## Per-signal discrimination\n")
    print(
        f"{'signal':<28} {'n_pos':>5} {'n_neg':>5}  "
        f"{'mean(rel)':>10} {'mean(nr)':>10} {'AUC':>5}  "
        f"{'P@R=0.9':>9} {'thr':>8}"
    )
    signals = [
        ("S1 anchor_overlap_full", "S1"),
        ("S2 anchor_overlap_top7", "S2"),
        ("S3 q_vs_memtext_cos", "S3"),
        ("S4 q_vs_evidence_cos", "S4"),
        ("S5 same_source_thread", "S5"),
        ("S6 src_thread_age_hours", "S6"),
        ("S7 memory_age_days", "S7"),
        ("S8 q_vs_memtext_jaccard", "S8"),
        ("S9 q_vs_mo_subject_cos", "S9"),
        ("S10 q_vs_anchorbest_cos", "S10"),
    ]
    for label, key in signals:
        pos, neg = _split(key, drop_nan=True)
        if not pos and not neg:
            print(f"{label:<28}  no data")
            continue
        m_pos = mean(pos) if pos else float("nan")
        m_neg = mean(neg) if neg else float("nan")
        auc_score = auc(pos, neg) if pos and neg else float("nan")
        # For age signals, lower might be 'positive' - we report P@R for >= threshold orientation;
        # if AUC<0.5, the signal is inversely informative and we flip it.
        if not math.isnan(auc_score) and auc_score < 0.5:
            p_at_r, t_at = best_precision_at_recall(
                [-x for x in pos], [-x for x in neg], 0.9
            )
            t_at = -t_at if not math.isinf(t_at) else float("nan")
            note = " (inverted: smaller=better)"
        else:
            p_at_r, t_at = best_precision_at_recall(pos, neg, 0.9)
            note = ""
        print(
            f"{label:<28} {len(pos):>5} {len(neg):>5}  "
            f"{m_pos:>10.3f} {m_neg:>10.3f} {auc_score:>5.2f}  "
            f"{p_at_r:>9.2f} {t_at:>8.3f}{note}"
        )

    # ---- combined rule check ----
    print("\n## Combined rule check\n")
    print("Treats kept = signal evaluates to True/positive.")
    rules = [
        ("S1 only", lambda r: r["S1"] == 1),
        ("S5 only", lambda r: r["S5"] == 1),
        ("S1 OR S5", lambda r: r["S1"] == 1 or r["S5"] == 1),
        ("S1 AND S5", lambda r: r["S1"] == 1 and r["S5"] == 1),
        ("S8 >= 0.04", lambda r: not math.isnan(r["S8"]) and r["S8"] >= 0.04),
        ("S8 >= 0.05", lambda r: not math.isnan(r["S8"]) and r["S8"] >= 0.05),
        ("S8 >= 0.06", lambda r: not math.isnan(r["S8"]) and r["S8"] >= 0.06),
        ("S8 >= 0.08", lambda r: not math.isnan(r["S8"]) and r["S8"] >= 0.08),
        (
            "S1 OR S8 >= 0.05",
            lambda r: r["S1"] == 1
            or (not math.isnan(r["S8"]) and r["S8"] >= 0.05),
        ),
        (
            "S1 AND S8 >= 0.04",
            lambda r: r["S1"] == 1
            and not math.isnan(r["S8"]) and r["S8"] >= 0.04,
        ),
        (
            "S5 OR S8 >= 0.05",
            lambda r: r["S5"] == 1
            or (not math.isnan(r["S8"]) and r["S8"] >= 0.05),
        ),
        (
            "(S1 OR S5) AND S8 >= 0.04",
            lambda r: (r["S1"] == 1 or r["S5"] == 1)
            and not math.isnan(r["S8"]) and r["S8"] >= 0.04,
        ),
        (
            "S1 OR (S8 >= 0.08)",
            lambda r: r["S1"] == 1
            or (not math.isnan(r["S8"]) and r["S8"] >= 0.08),
        ),
    ]
    for name, fn in rules:
        tp = sum(1 for r in rows if r["rating"] == "relevant" and fn(r))
        fn_drop = sum(1 for r in rows if r["rating"] == "relevant" and not fn(r))
        fp = sum(1 for r in rows if r["rating"] == "not_relevant" and fn(r))
        tn = sum(1 for r in rows if r["rating"] == "not_relevant" and not fn(r))
        kept = tp + fp
        prec = tp / kept if kept else 0.0
        rec = tp / (tp + fn_drop) if (tp + fn_drop) else 0.0
        print(
            f"{name:<28} kept={kept:>3} tp={tp:>2} fp={fp:>2} fn={fn_drop:>2} tn={tn:>2}  P={prec:.2f} R={rec:.2f}"
        )

    # ---- per-case detail: which mechanism would catch each noise case ----
    print("\n## Per-case detail (sorted by rating then S8 desc)\n")
    by_rating = sorted(
        rows, key=lambda r: (r["rating"], -(r["S8"] if not math.isnan(r["S8"]) else 0))
    )
    print(
        f"{'rat':<13} {'S1':>2} {'S5':>2} {'S3':>5} {'S8':>5} {'#thr':>4}  query"
    )
    for r in by_rating:
        s3 = f"{r['S3']:.2f}" if not math.isnan(r['S3']) else "  -  "
        s8 = f"{r['S8']:.3f}" if not math.isnan(r['S8']) else "  -  "
        line = (
            f"{r['rating']:<13} "
            f"{r['S1']:>2} {r['S5']:>2} {s3:>5} {s8:>5} {r['n_source_threads']:>4}  "
            f"{(r['query'] or '')[:80]}"
        )
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode('ascii', 'replace').decode('ascii'))

    if args.out_json:
        Path(args.out_json).write_text(
            json.dumps(rows, indent=2, default=str), encoding="utf-8"
        )
        print(f"\nWrote {args.out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
