"""Run all fast experiments F1..F15 (except F10 which needs embedder) in one
pass against the live rated slice. Writes a markdown report to
.local/research/fast_experiments_2026-05-27_results.md.

Decision is data-only — no LLM, no harness changes beyond reading
audit_log.candidate_scores_json + memory_feedback + memory_objects.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.text import normalize_for_index  # noqa: E402

SINCE = "2026-05-18"
OUT = Path(_PROJECT_ROOT) / ".local" / "research" / "fast_experiments_2026-05-27_results.md"
DB = os.path.expanduser("~/.pallium/data/pallium.db")


def _toks(s: str) -> set[str]:
    return {t for t in normalize_for_index(s or "").split() if t}


def auc(pos: list[float], neg: list[float]) -> float:
    if not pos or not neg:
        return float("nan")
    wins = ties = 0
    for p in pos:
        for n in neg:
            if p > n: wins += 1
            elif p == n: ties += 1
    return (wins + 0.5 * ties) / (len(pos) * len(neg))


def load_cases(con):
    rows = con.execute(
        f"""
        SELECT mf.id AS fid, mf.rating, mf.memory_object_id AS mid,
               mf.memory_type AS mtype, mf.query_context AS query,
               mf.memory_text AS mtext,
               mf.container_ref AS cont, mf.created_at AS rated_at,
               qal.id AS aud_id, qal.thread_ref AS aud_thread,
               qal.decision_reason, qal.injection_method,
               qal.candidate_scores_json,
               qal.injected_blocks_json,
               mo.subject AS msubj, mo.payload_json, mo.created_at AS mcreated,
               mo.envelope_json
        FROM memory_feedback mf
        JOIN query_audit_log qal ON qal.id = mf.query_audit_log_id
        LEFT JOIN memory_objects mo ON mo.id = mf.memory_object_id
        WHERE mf.rating IN ('relevant','not_relevant')
          AND mf.created_at >= ?
          AND qal.candidate_scores_json IS NOT NULL
        """,
        (SINCE,),
    ).fetchall()
    return rows


def memory_thread(con, mid):
    r = con.execute(
        "SELECT si.thread_ref FROM relations rel JOIN source_items si ON si.id = rel.to_id "
        "WHERE rel.from_id=? AND rel.to_kind='source_item' ORDER BY si.created_at DESC LIMIT 1",
        (mid,),
    ).fetchone()
    return r[0] if r else None


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    rows = load_cases(con)
    rel = sum(1 for r in rows if r["rating"] == "relevant")
    nr = sum(1 for r in rows if r["rating"] == "not_relevant")

    out: list[str] = []
    out.append(f"# Fast experiments — results ({SINCE}, n={len(rows)} rel={rel} nr={nr})\n")

    # Pre-extract per-row info we'll reuse
    enriched = []
    for r in rows:
        cs = json.loads(r["candidate_scores_json"]) or []
        target = next((c for c in cs if c.get("memory_object_id") == r["mid"]), None)
        blocks = json.loads(r["injected_blocks_json"]) if r["injected_blocks_json"] else []
        block_mids = {(b.get("memory_object_id") or "") for b in blocks if isinstance(b, dict)}
        baseline_inj = bool((target or {}).get("injected")) or (r["mid"] in block_mids)
        enriched.append({
            "row": r,
            "candidates": cs,
            "target": target,
            "baseline_injected": baseline_inj,
        })

    # =========================================================================
    # F1 — internal scores predict rating? AUC + mean(rel) vs mean(nr)
    # =========================================================================
    out.append("## F1 — internal scores predict rating?\n")
    fields = ["routing_score", "lexical_score", "vector_score", "routing_rank"]
    out.append("| field | n_pos | n_neg | mean(rel) | mean(nr) | AUC |")
    out.append("|-|-|-|-|-|-|")
    for f in fields:
        pos = []
        neg = []
        for e in enriched:
            t = e["target"] or {}
            v = t.get(f)
            if v is None: continue
            (pos if e["row"]["rating"] == "relevant" else neg).append(float(v))
        if not pos or not neg:
            out.append(f"| {f} | {len(pos)} | {len(neg)} | n/a | n/a | n/a |")
            continue
        a = auc(pos, neg)
        if f == "routing_rank" and not math.isnan(a) and a < 0.5:
            a_disp = 1.0 - a
            note = " (inv)"
        else:
            a_disp = a
            note = ""
        out.append(
            f"| {f}{note} | {len(pos)} | {len(neg)} | {mean(pos):.2f} | {mean(neg):.2f} | {a_disp:.2f} |"
        )

    # support_grade is categorical
    sg_pos = Counter(); sg_neg = Counter()
    for e in enriched:
        sg = (e["target"] or {}).get("support_grade")
        if sg is None: continue
        (sg_pos if e["row"]["rating"] == "relevant" else sg_neg)[sg] += 1
    out.append("\n**support_grade distribution:**\n")
    out.append("| grade | rel | nr |")
    out.append("|-|-|-|")
    for g in sorted(set(sg_pos) | set(sg_neg)):
        out.append(f"| {g} | {sg_pos[g]} | {sg_neg[g]} |")

    # layer
    lyr_pos = Counter(); lyr_neg = Counter()
    for e in enriched:
        l = (e["target"] or {}).get("layer")
        if l is None: continue
        (lyr_pos if e["row"]["rating"] == "relevant" else lyr_neg)[l] += 1
    out.append("\n**layer distribution:**\n")
    out.append("| layer | rel | nr |")
    out.append("|-|-|-|")
    for l in sorted(set(lyr_pos) | set(lyr_neg)):
        out.append(f"| {l} | {lyr_pos[l]} | {lyr_neg[l]} |")

    # =========================================================================
    # F2 — memory-shape distribution by rating
    # =========================================================================
    out.append("\n## F2 — memory-shape distribution by rating\n")
    META_PAT = re.compile(
        r"\b(doesn'?t exist|don'?t exist|i don'?t know|cannot find|can'?t find|"
        r"no such|not sure|not applicable|n/?a)\b",
        re.IGNORECASE,
    )

    def shape(text: str, subj: str) -> str:
        t = (text or "").strip()
        s = (subj or "").strip()
        if len(t) < 20: return "empty_body"
        if s and t.lower() == s.lower(): return "title_only"
        if META_PAT.search(t): return "meta_commentary"
        return "substantive"

    counts = defaultdict(lambda: Counter())
    for e in enriched:
        r = e["row"]
        sh = shape(r["mtext"], r["msubj"])
        counts[sh][r["rating"]] += 1
    out.append("| shape | rel | nr | total | %nr |")
    out.append("|-|-|-|-|-|")
    for sh in ("substantive", "title_only", "empty_body", "meta_commentary"):
        rl = counts[sh]["relevant"]; nrr = counts[sh]["not_relevant"]
        tot = rl + nrr
        pnr = (nrr / tot * 100) if tot else 0
        out.append(f"| {sh} | {rl} | {nrr} | {tot} | {pnr:.0f}% |")

    # share of NR cards that are non-substantive
    total_nr = sum(c["not_relevant"] for c in counts.values())
    non_subst_nr = sum(counts[s]["not_relevant"] for s in ("title_only", "empty_body", "meta_commentary"))
    out.append(
        f"\n**Share of NR cards that are non-substantive:** "
        f"{non_subst_nr}/{total_nr} = {non_subst_nr/max(total_nr,1)*100:.0f}%"
    )

    # =========================================================================
    # F3 / F4 — (decision_reason × rating) pivot, container × rating, type × rating
    # =========================================================================
    out.append("\n## F4 — precision per decision_reason\n")
    by_reason = defaultdict(lambda: Counter())
    for e in enriched:
        r = e["row"]
        by_reason[r["decision_reason"] or "?"][r["rating"]] += 1
    out.append("| decision_reason | rel | nr | n | P |")
    out.append("|-|-|-|-|-|")
    for k, c in sorted(by_reason.items(), key=lambda kv: -(kv[1]["relevant"]+kv[1]["not_relevant"])):
        rl, nrr = c["relevant"], c["not_relevant"]
        n = rl + nrr
        p = rl / n if n else 0
        out.append(f"| {k} | {rl} | {nrr} | {n} | {p:.2f} |")

    out.append("\n## F4b — precision per injection_method\n")
    by_method = defaultdict(lambda: Counter())
    for e in enriched:
        r = e["row"]
        by_method[r["injection_method"] or "?"][r["rating"]] += 1
    out.append("| injection_method | rel | nr | n | P |")
    out.append("|-|-|-|-|-|")
    for k, c in sorted(by_method.items(), key=lambda kv: -(kv[1]["relevant"]+kv[1]["not_relevant"])):
        rl, nrr = c["relevant"], c["not_relevant"]
        n = rl + nrr
        p = rl / n if n else 0
        out.append(f"| {k} | {rl} | {nrr} | {n} | {p:.2f} |")

    out.append("\n## F3a — precision per memory type\n")
    by_type = defaultdict(lambda: Counter())
    for e in enriched:
        r = e["row"]
        by_type[r["mtype"] or "?"][r["rating"]] += 1
    out.append("| type | rel | nr | n | P |")
    out.append("|-|-|-|-|-|")
    for k, c in sorted(by_type.items(), key=lambda kv: -(kv[1]["relevant"]+kv[1]["not_relevant"])):
        rl, nrr = c["relevant"], c["not_relevant"]
        n = rl + nrr
        p = rl / n if n else 0
        out.append(f"| {k} | {rl} | {nrr} | {n} | {p:.2f} |")

    out.append("\n## F3b — precision per container\n")
    by_cont = defaultdict(lambda: Counter())
    for e in enriched:
        r = e["row"]
        by_cont[r["cont"] or "?"][r["rating"]] += 1
    out.append("| container | rel | nr | n | P |")
    out.append("|-|-|-|-|-|")
    for k, c in sorted(by_cont.items(), key=lambda kv: -(kv[1]["relevant"]+kv[1]["not_relevant"])):
        rl, nrr = c["relevant"], c["not_relevant"]
        n = rl + nrr
        p = rl / n if n else 0
        out.append(f"| {(k or '?')[:50]} | {rl} | {nrr} | {n} | {p:.2f} |")

    out.append("\n## F3c — precision per (type × decision_reason)\n")
    by_tr = defaultdict(lambda: Counter())
    for e in enriched:
        r = e["row"]
        key = f"{r['mtype']} / {r['decision_reason']}"
        by_tr[key][r["rating"]] += 1
    out.append("| type / decision_reason | rel | nr | n | P |")
    out.append("|-|-|-|-|-|")
    for k, c in sorted(by_tr.items(), key=lambda kv: -(kv[1]["relevant"]+kv[1]["not_relevant"])):
        rl, nrr = c["relevant"], c["not_relevant"]
        n = rl + nrr
        if n < 3: continue
        p = rl / n if n else 0
        out.append(f"| {k} | {rl} | {nrr} | {n} | {p:.2f} |")

    # =========================================================================
    # F5 — underinjection: skip-paths with high-quality candidates in pool
    # =========================================================================
    # Pull all audit rows since SINCE (not just rated ones) to see the volume.
    all_audit = con.execute(
        "SELECT id, decision_reason, candidate_scores_json, thread_ref FROM query_audit_log "
        "WHERE created_at >= ? AND candidate_scores_json IS NOT NULL",
        (SINCE,),
    ).fetchall()

    out.append("\n## F5 — underinjection probe (all audit rows, not just rated)\n")
    out.append(f"audit rows since {SINCE}: {len(all_audit)}\n")

    skip_reasons = {"no_relevant_memory", "same_thread_context_sufficient",
                    "no_qualifying_candidates", "below_routing_threshold"}
    skip_counts = Counter()
    skip_with_strong = Counter()
    skip_with_strong_threshold = 200  # routing_score >= 200 means a non-trivial candidate
    for a in all_audit:
        if a["decision_reason"] not in skip_reasons:
            continue
        skip_counts[a["decision_reason"]] += 1
        cs = json.loads(a["candidate_scores_json"]) or []
        max_rs = max((c.get("routing_score") or 0) for c in cs) if cs else 0
        if max_rs >= skip_with_strong_threshold:
            skip_with_strong[a["decision_reason"]] += 1

    out.append("| decision_reason | n | with_routing_score>=200 | %strong |")
    out.append("|-|-|-|-|")
    for k, n in skip_counts.most_common():
        s = skip_with_strong[k]
        pct = (s / n * 100) if n else 0
        out.append(f"| {k} | {n} | {s} | {pct:.0f}% |")

    # =========================================================================
    # F6 — suppression / excluded reasons
    # =========================================================================
    out.append("\n## F6 — suppression / excluded reason audit (rated cases)\n")
    sup_counts = defaultdict(lambda: Counter())
    exc_counts = defaultdict(lambda: Counter())
    for e in enriched:
        for c in e["candidates"]:
            sr = c.get("suppression_reason_code")
            ec = c.get("excluded_reason_code")
            if sr: sup_counts[sr][e["row"]["rating"]] += 1
            if ec: exc_counts[ec][e["row"]["rating"]] += 1

    out.append("**suppression_reason_code (counts across all candidates of rated audits):**\n")
    out.append("| code | rel | nr |")
    out.append("|-|-|-|")
    for k, c in sorted(sup_counts.items(), key=lambda kv: -(kv[1]["relevant"]+kv[1]["not_relevant"])):
        out.append(f"| {k} | {c['relevant']} | {c['not_relevant']} |")

    out.append("\n**excluded_reason_code:**\n")
    out.append("| code | rel | nr |")
    out.append("|-|-|-|")
    for k, c in sorted(exc_counts.items(), key=lambda kv: -(kv[1]["relevant"]+kv[1]["not_relevant"])):
        out.append(f"| {k} | {c['relevant']} | {c['not_relevant']} |")

    # =========================================================================
    # F7 — routing_rank histogram by rating
    # =========================================================================
    out.append("\n## F7 — routing_rank histogram\n")
    hist = defaultdict(lambda: Counter())
    for e in enriched:
        r = (e["target"] or {}).get("routing_rank")
        if r is None: continue
        bucket = "1" if r == 1 else "2" if r == 2 else "3-5" if r <= 5 else ">5"
        hist[bucket][e["row"]["rating"]] += 1
    out.append("| rank | rel | nr | P |")
    out.append("|-|-|-|-|")
    for k in ("1", "2", "3-5", ">5"):
        c = hist[k]
        n = c["relevant"] + c["not_relevant"]
        p = c["relevant"] / n if n else 0
        out.append(f"| {k} | {c['relevant']} | {c['not_relevant']} | {p:.2f} |")

    # =========================================================================
    # F8 — pool size vs precision
    # =========================================================================
    out.append("\n## F8 — pool size (n_candidates) vs precision\n")
    pool_buckets = defaultdict(lambda: Counter())
    for e in enriched:
        sz = len(e["candidates"])
        b = "1-3" if sz <= 3 else "4-7" if sz <= 7 else "8-15" if sz <= 15 else ">15"
        pool_buckets[b][e["row"]["rating"]] += 1
    out.append("| pool_size | rel | nr | P |")
    out.append("|-|-|-|-|")
    for k in ("1-3", "4-7", "8-15", ">15"):
        c = pool_buckets[k]
        n = c["relevant"] + c["not_relevant"]
        p = c["relevant"] / n if n else 0
        out.append(f"| {k} | {c['relevant']} | {c['not_relevant']} | {p:.2f} |")

    # =========================================================================
    # F9 — memory age vs rating
    # =========================================================================
    out.append("\n## F9 — memory age (days) vs rating\n")
    age_buckets = defaultdict(lambda: Counter())
    from datetime import datetime, timezone
    for e in enriched:
        rated_at = e["row"]["rated_at"]
        m_at = e["row"]["mcreated"]
        if not (rated_at and m_at): continue
        try:
            d1 = datetime.fromisoformat(rated_at.replace("Z","+00:00"))
            d2 = datetime.fromisoformat(m_at.replace("Z","+00:00"))
            if d1.tzinfo is None: d1 = d1.replace(tzinfo=timezone.utc)
            if d2.tzinfo is None: d2 = d2.replace(tzinfo=timezone.utc)
            age = (d1 - d2).total_seconds() / 86400
        except Exception:
            continue
        b = "<1d" if age < 1 else "1-3d" if age < 3 else "3-7d" if age < 7 else "7-14d" if age < 14 else ">=14d"
        age_buckets[b][e["row"]["rating"]] += 1
    out.append("| age | rel | nr | P |")
    out.append("|-|-|-|-|")
    for k in ("<1d", "1-3d", "3-7d", "7-14d", ">=14d"):
        c = age_buckets[k]
        n = c["relevant"] + c["not_relevant"]
        p = c["relevant"] / n if n else 0
        out.append(f"| {k} | {c['relevant']} | {c['not_relevant']} | {p:.2f} |")

    # =========================================================================
    # F11 — fallback vs primary layer
    # =========================================================================
    out.append("\n## F11 — layer (primary vs fallback) precision\n")
    out.append("(see F1 layer distribution; computing P explicitly)\n")
    out.append("| layer | rel | nr | P |")
    out.append("|-|-|-|-|")
    for l in sorted(set(lyr_pos) | set(lyr_neg)):
        rl, nrr = lyr_pos[l], lyr_neg[l]
        n = rl + nrr
        p = rl / n if n else 0
        out.append(f"| {l} | {rl} | {nrr} | {p:.2f} |")

    # =========================================================================
    # F12 — same-thread injection precision
    # =========================================================================
    out.append("\n## F12 — same-thread injection precision\n")
    same_thread = Counter(); diff_thread = Counter()
    for e in enriched:
        r = e["row"]
        mt = memory_thread(con, r["mid"])
        same = bool(mt and r["aud_thread"] and mt == r["aud_thread"])
        (same_thread if same else diff_thread)[r["rating"]] += 1
    for label, c in [("same_thread", same_thread), ("diff_thread", diff_thread)]:
        n = c["relevant"] + c["not_relevant"]
        p = c["relevant"] / n if n else 0
        out.append(f"- {label}: rel={c['relevant']}, nr={c['not_relevant']}, n={n}, P={p:.2f}")

    # =========================================================================
    # F13 — container heterogeneity vs noise rate
    # =========================================================================
    out.append("\n## F13 — container heterogeneity vs noise rate\n")
    out.append("Per container: distinct threads in audit log, distinct rated-memory subjects.\n")
    cont_threads = defaultdict(set)
    cont_subjects = defaultdict(set)
    for a in all_audit:
        if a["thread_ref"]: cont_threads[a["thread_ref"]].add(a["thread_ref"])
    # Recompute per container properly
    rows_audit = con.execute(
        "SELECT thread_ref, container_ref FROM query_audit_log "
        "WHERE created_at >= ? AND thread_ref IS NOT NULL AND container_ref IS NOT NULL",
        (SINCE,),
    ).fetchall()
    cont_threads = defaultdict(set)
    for r in rows_audit:
        cont_threads[r["container_ref"]].add(r["thread_ref"])
    rows_mem = con.execute(
        "SELECT subject, container_ref FROM memory_objects WHERE created_at >= ?",
        (SINCE,),
    ).fetchall()
    cont_subjects = defaultdict(set)
    for r in rows_mem:
        if r["subject"]: cont_subjects[r["container_ref"]].add(r["subject"])

    out.append("| container | n_rated | rel | nr | %nr | n_threads | n_subjects |")
    out.append("|-|-|-|-|-|-|-|")
    cont_rated = defaultdict(lambda: Counter())
    for e in enriched:
        cont_rated[e["row"]["cont"] or "?"][e["row"]["rating"]] += 1
    for cont, c in sorted(cont_rated.items(), key=lambda kv: -(kv[1]["relevant"]+kv[1]["not_relevant"])):
        rl, nrr = c["relevant"], c["not_relevant"]
        n = rl + nrr
        pnr = (nrr/n*100) if n else 0
        nt = len(cont_threads.get(cont, set()))
        ns = len(cont_subjects.get(cont, set()))
        out.append(f"| {cont[:50]} | {n} | {rl} | {nrr} | {pnr:.0f}% | {nt} | {ns} |")

    # =========================================================================
    # F14 — magnet memories
    # =========================================================================
    out.append("\n## F14 — magnet memories (top injected) and their rated precision\n")
    # Count how often each memory was actually injected (across all audits)
    inj_counts = Counter()
    for a in all_audit:
        cs = json.loads(a["candidate_scores_json"]) or []
        for c in cs:
            if c.get("injected") and c.get("memory_object_id"):
                inj_counts[c["memory_object_id"]] += 1
    # Build a lookup of rated outcomes for each memory
    rated_per_mid = defaultdict(lambda: Counter())
    for e in enriched:
        rated_per_mid[e["row"]["mid"]][e["row"]["rating"]] += 1

    top_n = 15
    out.append(f"top-{top_n} magnets by injection count:\n")
    out.append("| mid_short | injections | rated_rel | rated_nr |")
    out.append("|-|-|-|-|")
    total_inj = sum(inj_counts.values())
    for mid, n in inj_counts.most_common(top_n):
        c = rated_per_mid.get(mid, Counter())
        out.append(f"| {mid[:8]} | {n} | {c['relevant']} | {c['not_relevant']} |")

    # share of injections concentrated in top-N
    cum_top = sum(n for _, n in inj_counts.most_common(top_n))
    out.append(f"\nTop-{top_n}/{len(inj_counts)} memories = {cum_top}/{total_inj} injections "
               f"({cum_top/max(total_inj,1)*100:.0f}%)")

    # =========================================================================
    # F15 — re-run replay rules with stricter recall floor (run via subprocess
    # is overkill; rules are simple so re-implement frontier with R2/R2b/R5/R7
    # plus a few new ones)
    # =========================================================================
    out.append("\n## F15 — replay rules ranked by P at recall>=0.85\n")

    def baseline_inj_for(e): return e["baseline_injected"]

    def r_baseline(e): return baseline_inj_for(e)

    def r_R2_subj_overlap(e, n=1):
        if not baseline_inj_for(e): return False
        qtok = _toks(e["row"]["query"])
        stok = _toks(e["row"]["msubj"]) or _toks(e["row"]["mtext"])
        if not qtok or not stok: return True
        return len(qtok & stok) >= n

    def r_R2b(e): return r_R2_subj_overlap(e, 2)

    def r_R5_top1(e):
        if not baseline_inj_for(e): return False
        return ((e["target"] or {}).get("routing_rank") or 99) == 1

    def r_R7(e):
        if not baseline_inj_for(e): return False
        same = False
        # we'd need memory_thread; reuse F12 logic inline
        if (e["target"] or {}).get("routing_rank") == 1:
            return True
        qtok = _toks(e["row"]["query"])
        stok = _toks(e["row"]["msubj"]) or _toks(e["row"]["mtext"])
        return bool(qtok and stok and len(qtok & stok) >= 2)

    def r_substantive_only(e):
        if not baseline_inj_for(e): return False
        return shape(e["row"]["mtext"], e["row"]["msubj"]) == "substantive"

    def r_substantive_AND_R2(e):
        return r_substantive_only(e) and r_R2_subj_overlap(e, 1)

    def r_top2_substantive(e):
        if not baseline_inj_for(e): return False
        if ((e["target"] or {}).get("routing_rank") or 99) > 2: return False
        return shape(e["row"]["mtext"], e["row"]["msubj"]) == "substantive"

    def r_no_const_in_low_thread(e):
        # Skip constraint_memory in same_thread_context_sufficient path? Or any "fallback" layer?
        if not baseline_inj_for(e): return False
        if (e["row"]["mtype"] == "constraint_memory" and
            e["row"]["decision_reason"] != "carry_forward_available"):
            # we keep it; placeholder rule
            return True
        return True

    rules = [
        ("baseline", r_baseline),
        ("R2 subj>=1", r_R2_subj_overlap),
        ("R2b subj>=2", r_R2b),
        ("R5 top1", r_R5_top1),
        ("R7 top1 OR (subj>=2)", r_R7),
        ("substantive_only", r_substantive_only),
        ("substantive AND subj>=1", r_substantive_AND_R2),
        ("top2 AND substantive", r_top2_substantive),
    ]

    def evalrule(fn):
        kr = kn = dr = dn = 0
        for e in enriched:
            keep = fn(e)
            base = baseline_inj_for(e)
            if keep:
                if e["row"]["rating"] == "relevant": kr += 1
                else: kn += 1
            elif base:
                if e["row"]["rating"] == "relevant": dr += 1
                else: dn += 1
        kept = kr + kn
        p = kr / kept if kept else float("nan")
        rec = kr / (kr + dr) if (kr + dr) else float("nan")
        nk = dn / (kn + dn) if (kn + dn) else float("nan")
        return kr, kn, dr, dn, p, rec, nk

    out.append("| rule | kept(rel/nr) | drop(rel/nr) | P | R | noise_kill |")
    out.append("|-|-|-|-|-|-|")
    results = []
    for name, fn in rules:
        kr, kn, dr, dn, p, rec, nk = evalrule(fn)
        results.append((name, p, rec, nk))
        out.append(f"| {name} | {kr}/{kn} | {dr}/{dn} | {p:.2f} | {rec:.2f} | {nk:.2f} |")

    out.append("\n**Frontier @ R>=0.85:**\n")
    out.append("| rule | P | R | kill |")
    out.append("|-|-|-|-|")
    feas = sorted([r for r in results if not math.isnan(r[2]) and r[2] >= 0.85],
                  key=lambda r: -r[1])
    for n, p, r, nk in feas:
        out.append(f"| {n} | {p:.2f} | {r:.2f} | {nk:.2f} |")

    # =========================================================================
    # Write
    # =========================================================================
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"n cases: {len(rows)} (rel={rel} nr={nr})")


if __name__ == "__main__":
    main()
