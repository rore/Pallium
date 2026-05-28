"""Follow-up probes after initial fast experiments. Investigates the leads
the F1-F15 run identified.

Specifically:
  G1  what is `injection_method=simplified` vs the unlabeled path?
  G2  investigation_outcome NR — what shape are these cards? (n=16)
  G3  age 1-3d zone with P=0.20 — what types/reasons?
  G4  same_thread_context_sufficient skip path — when WAS something useful
      in the pool, why? Sample 20 of the 358 cases with the highest
      routing_score and inspect what was skipped.
  G5  vector_score-only candidates: when does vector_score exist? Does its
      AUC=0.69 hold up if we only consider candidates that have it?
  G6  per-thread breakdown of rated cases — repeat counts identify
      whether the wide slice is dominated by a few threads.
  G7  routing_score threshold sweep: what threshold on routing_score, if
      we required it for keep, would maximize precision at R>=0.85?
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.text import normalize_for_index  # noqa: E402

SINCE = "2026-05-18"
DB = os.path.expanduser("~/.pallium/data/pallium.db")
OUT = Path(_PROJECT_ROOT) / ".local" / "research" / "fast_experiments_2026-05-27_followup.md"


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    out = []

    # -----------------------------------------------------------------------
    # G1 — injection_method=simplified vs ?
    # -----------------------------------------------------------------------
    out.append("# Fast experiments — follow-up\n")

    rows = con.execute(
        f"""
        SELECT mf.rating, mf.memory_type, mf.created_at,
               qal.injection_method, qal.decision_reason,
               qal.candidate_scores_json, qal.injected_blocks_json
        FROM memory_feedback mf
        JOIN query_audit_log qal ON qal.id = mf.query_audit_log_id
        WHERE mf.rating IN ('relevant','not_relevant')
          AND mf.created_at >= ?
          AND qal.candidate_scores_json IS NOT NULL
        """,
        (SINCE,),
    ).fetchall()

    out.append("## G1 — injection_method values\n")
    by_method = Counter()
    for r in rows:
        by_method[r["injection_method"]] += 1
    out.append(f"distinct values seen: {dict(by_method)}\n")

    # Are NULLs concentrated in a date range or container?
    null_dates = [r["created_at"] for r in rows if r["injection_method"] is None]
    sim_dates = [r["created_at"] for r in rows if r["injection_method"] == "simplified"]
    out.append(f"NULL injection_method rated cases: n={len(null_dates)}, "
               f"date span: {min(null_dates) if null_dates else '-'} .. "
               f"{max(null_dates) if null_dates else '-'}")
    out.append(f"\nsimplified rated cases: n={len(sim_dates)}, "
               f"date span: {min(sim_dates) if sim_dates else '-'} .. "
               f"{max(sim_dates) if sim_dates else '-'}\n")

    # -----------------------------------------------------------------------
    # G2 — investigation_outcome NR cards: what do they look like?
    # -----------------------------------------------------------------------
    out.append("## G2 — investigation_outcome NR cards (n=16)\n")
    nr_io = con.execute(
        f"""
        SELECT mf.id AS fid, mf.memory_text, mf.query_context,
               mo.subject, mo.payload_json, mo.envelope_json
        FROM memory_feedback mf
        LEFT JOIN memory_objects mo ON mo.id = mf.memory_object_id
        WHERE mf.rating='not_relevant'
          AND mf.memory_type='investigation_outcome'
          AND mf.created_at >= ?
        """,
        (SINCE,),
    ).fetchall()
    out.append("| # | subject | query_excerpt | mtext_excerpt |")
    out.append("|-|-|-|-|")
    for i, r in enumerate(nr_io, 1):
        subj = (r["subject"] or "")[:60]
        q = (r["query_context"] or "")[:60].replace("|", "/").replace("\n", " ")
        m = (r["memory_text"] or "")[:60].replace("|", "/").replace("\n", " ")
        out.append(f"| {i} | {subj} | {q} | {m} |")

    # -----------------------------------------------------------------------
    # G3 — age 1-3d cases with P=0.20
    # -----------------------------------------------------------------------
    out.append("\n## G3 — age 1-3d cases (P=0.20, n=5)\n")
    rows_age = con.execute(
        f"""
        SELECT mf.rating, mf.memory_type, mf.created_at AS rated_at,
               mo.created_at AS mcreated, mo.subject,
               mf.query_context
        FROM memory_feedback mf
        LEFT JOIN memory_objects mo ON mo.id = mf.memory_object_id
        WHERE mf.rating IN ('relevant','not_relevant') AND mf.created_at >= ?
        """,
        (SINCE,),
    ).fetchall()
    age_13 = []
    for r in rows_age:
        if not (r["rated_at"] and r["mcreated"]): continue
        try:
            d1 = datetime.fromisoformat(r["rated_at"].replace("Z", "+00:00"))
            d2 = datetime.fromisoformat(r["mcreated"].replace("Z", "+00:00"))
            if d1.tzinfo is None: d1 = d1.replace(tzinfo=timezone.utc)
            if d2.tzinfo is None: d2 = d2.replace(tzinfo=timezone.utc)
            age = (d1 - d2).total_seconds() / 86400
        except Exception:
            continue
        if 1 <= age < 3:
            age_13.append((age, r))
    out.append("| age_d | rating | type | subject | query_excerpt |")
    out.append("|-|-|-|-|-|")
    for age, r in age_13:
        out.append(f"| {age:.2f} | {r['rating']} | {r['memory_type']} | "
                   f"{(r['subject'] or '')[:40]} | {(r['query_context'] or '')[:60].replace('|', '/').replace(chr(10), ' ')} |")

    # -----------------------------------------------------------------------
    # G4 — same_thread_context_sufficient: was a strong candidate in the pool?
    #      Sample top-20 by max routing_score
    # -----------------------------------------------------------------------
    out.append("\n## G4 — `same_thread_context_sufficient` skips: top 20 by max routing_score\n")
    skip_rows = con.execute(
        f"""
        SELECT id, query_text, candidate_scores_json, thread_ref, container_ref
        FROM query_audit_log
        WHERE created_at >= ? AND decision_reason='same_thread_context_sufficient'
          AND candidate_scores_json IS NOT NULL
        """,
        (SINCE,),
    ).fetchall()
    out.append(f"total skips: {len(skip_rows)}\n")

    skip_summaries = []
    for r in skip_rows:
        cs = json.loads(r["candidate_scores_json"]) or []
        if not cs: continue
        # find the top-routing-score candidate
        top = max(cs, key=lambda c: (c.get("routing_score") or 0))
        skip_summaries.append((top.get("routing_score") or 0, top, r))

    skip_summaries.sort(key=lambda x: -x[0])
    out.append("| rs | rank | type | subject | query_excerpt |")
    out.append("|-|-|-|-|-|")
    # Need to fetch subjects
    for rs, top, r in skip_summaries[:20]:
        mid = top.get("memory_object_id")
        m = con.execute("SELECT subject, payload_json FROM memory_objects WHERE id=?", (mid,)).fetchone()
        subj = (m["subject"] if m and m["subject"] else "") or ""
        if not subj and m and m["payload_json"]:
            try:
                pl = json.loads(m["payload_json"])
                for k in ("subject", "title", "decision", "summary", "statement"):
                    if isinstance(pl.get(k), str) and pl[k]:
                        subj = pl[k]; break
            except Exception:
                pass
        q = (r["query_text"] or "")[:60].replace("|", "/").replace("\n", " ")
        out.append(f"| {rs:.0f} | {top.get('routing_rank')} | {top.get('layer')} | {subj[:50]} | {q} |")

    # -----------------------------------------------------------------------
    # G5 — vector_score availability and AUC when present
    # -----------------------------------------------------------------------
    out.append("\n## G5 — vector_score availability\n")
    rated2 = con.execute(
        f"""
        SELECT mf.rating, mf.memory_object_id AS mid, qal.candidate_scores_json
        FROM memory_feedback mf
        JOIN query_audit_log qal ON qal.id = mf.query_audit_log_id
        WHERE mf.rating IN ('relevant','not_relevant')
          AND mf.created_at >= ?
          AND qal.candidate_scores_json IS NOT NULL
        """,
        (SINCE,),
    ).fetchall()
    vec_present = vec_absent = 0
    has_pos = []; has_neg = []
    for r in rated2:
        cs = json.loads(r["candidate_scores_json"]) or []
        t = next((c for c in cs if c.get("memory_object_id") == r["mid"]), None)
        if not t: continue
        v = t.get("vector_score")
        if v is None:
            vec_absent += 1
            continue
        vec_present += 1
        (has_pos if r["rating"] == "relevant" else has_neg).append(float(v))
    out.append(f"present={vec_present}, absent={vec_absent}\n")
    if has_pos and has_neg:
        wins = ties = 0
        for p in has_pos:
            for n in has_neg:
                if p > n: wins += 1
                elif p == n: ties += 1
        a = (wins + 0.5*ties) / (len(has_pos)*len(has_neg))
        out.append(f"AUC vector_score (target only): {a:.2f}\n")
        out.append(f"mean(rel)={mean(has_pos):.1f} mean(nr)={mean(has_neg):.1f}\n")

    # -----------------------------------------------------------------------
    # G6 — per-thread breakdown of rated cases
    # -----------------------------------------------------------------------
    out.append("\n## G6 — rated cases per thread\n")
    thread_counts = con.execute(
        f"""
        SELECT qal.thread_ref, mf.rating, COUNT(*) AS n
        FROM memory_feedback mf
        JOIN query_audit_log qal ON qal.id = mf.query_audit_log_id
        WHERE mf.rating IN ('relevant','not_relevant')
          AND mf.created_at >= ?
        GROUP BY qal.thread_ref, mf.rating
        """,
        (SINCE,),
    ).fetchall()
    by_t = defaultdict(lambda: Counter())
    for r in thread_counts:
        by_t[r["thread_ref"] or "?"][r["rating"]] = r["n"]
    out.append("| thread | rel | nr | total |")
    out.append("|-|-|-|-|")
    for t, c in sorted(by_t.items(), key=lambda kv: -(kv[1]["relevant"]+kv[1]["not_relevant"])):
        rl = c["relevant"]; nrr = c["not_relevant"]
        out.append(f"| {(t or '?')[:18]} | {rl} | {nrr} | {rl+nrr} |")

    # -----------------------------------------------------------------------
    # G7 — routing_score threshold sweep: best P at R>=0.85
    # -----------------------------------------------------------------------
    out.append("\n## G7 — routing_score threshold sweep\n")
    pos_rs = []; neg_rs = []
    for r in rated2:
        cs = json.loads(r["candidate_scores_json"]) or []
        t = next((c for c in cs if c.get("memory_object_id") == r["mid"]), None)
        rs = (t or {}).get("routing_score")
        if rs is None: continue
        (pos_rs if r["rating"] == "relevant" else neg_rs).append(float(rs))

    out.append("| threshold | kept(rel/nr) | P | R |")
    out.append("|-|-|-|-|")
    for thr in [0, 200, 300, 350, 400, 450, 500, 600, 800]:
        kr = sum(1 for v in pos_rs if v >= thr)
        kn = sum(1 for v in neg_rs if v >= thr)
        kept = kr + kn
        p = kr / kept if kept else 0
        r_ = kr / len(pos_rs) if pos_rs else 0
        out.append(f"| >={thr} | {kr}/{kn} | {p:.2f} | {r_:.2f} |")

    # -----------------------------------------------------------------------
    # G7b — combined: routing_score>=X AND subject_overlap>=1
    # -----------------------------------------------------------------------
    out.append("\n## G7b — combined: routing_score>=X AND subject_overlap>=1\n")
    rated3 = con.execute(
        f"""
        SELECT mf.rating, mf.memory_object_id AS mid, mf.query_context, mf.memory_text,
               qal.candidate_scores_json, mo.subject
        FROM memory_feedback mf
        JOIN query_audit_log qal ON qal.id = mf.query_audit_log_id
        LEFT JOIN memory_objects mo ON mo.id = mf.memory_object_id
        WHERE mf.rating IN ('relevant','not_relevant')
          AND mf.created_at >= ?
          AND qal.candidate_scores_json IS NOT NULL
        """,
        (SINCE,),
    ).fetchall()

    def toks(s): return {t for t in normalize_for_index(s or "").split() if t}
    cases3 = []
    for r in rated3:
        cs = json.loads(r["candidate_scores_json"]) or []
        t = next((c for c in cs if c.get("memory_object_id") == r["mid"]), None)
        rs = (t or {}).get("routing_score") or 0
        qt = toks(r["query_context"])
        st = toks(r["subject"]) or toks(r["memory_text"])
        ov = len(qt & st) if (qt and st) else 99  # cannot judge -> treat as keep
        cases3.append((r["rating"], rs, ov))

    out.append("| rs_thr | subj_thr | kept(rel/nr) | drop(rel/nr) | P | R |")
    out.append("|-|-|-|-|-|-|")
    base_rel = sum(1 for c in cases3 if c[0] == "relevant")
    base_nr = sum(1 for c in cases3 if c[0] == "not_relevant")
    for rs_thr in [0, 350, 400, 450, 500]:
        for sub_thr in [0, 1, 2]:
            kr = kn = dr = dn = 0
            for rating, rs, ov in cases3:
                keep = rs >= rs_thr and (sub_thr == 0 or ov >= sub_thr)
                if keep:
                    if rating == "relevant": kr += 1
                    else: kn += 1
                else:
                    if rating == "relevant": dr += 1
                    else: dn += 1
            kept = kr + kn
            p = kr / kept if kept else 0
            r_ = kr / (kr + dr) if (kr + dr) else 0
            out.append(f"| >={rs_thr} | >={sub_thr} | {kr}/{kn} | {dr}/{dn} | {p:.2f} | {r_:.2f} |")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
