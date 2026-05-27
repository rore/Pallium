"""Replay harness: counterfactually evaluate gating rules against rated cases.

For each rated injection in the audit log we know:
  - the candidate pool the system considered (candidate_scores_json)
  - which were injected (candidate.injected == True)
  - the user rating on the target memory (relevant / not_relevant)

A "rule" decides, given the candidate row + audit row, whether to keep it
injected. Replaying the rule across rated cases gives us:

  kept_rel    - rule kept a memory the user rated relevant   (true positive)
  kept_nr     - rule kept a memory the user rated not_relevant (false positive)
  dropped_rel - rule dropped a memory the user rated relevant (false negative)
  dropped_nr  - rule dropped a memory the user rated not_relevant (true negative)

  precision = kept_rel / (kept_rel + kept_nr)
  recall    = kept_rel / (kept_rel + dropped_rel)   (against shipped rel)
  noise_kill_rate = dropped_nr / (dropped_nr + kept_nr)

Baseline rule = "ship-as-is" reproduces the live system's measured precision.

Usage:
    .venv/Scripts/python.exe -m evals.anchor_probe.replay_harness --since 2026-05-18
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.text import normalize_for_index  # noqa: E402


def _tokens(s: str) -> set[str]:
    return {t for t in normalize_for_index(s or "").split() if t}


@dataclass
class Case:
    fid: str
    rating: str            # 'relevant' | 'not_relevant'
    rated_mid: str
    rated_type: str
    query: str
    container: str
    audit_id: str
    audit_thread: str | None
    decision_reason: str | None
    injection_method: str | None
    candidates: list[dict]
    injected_block_mids: set[str]
    target_candidate: dict | None  # the candidate row matching rated_mid
    memory_subject: str
    memory_text: str
    memory_thread: str | None  # thread_ref of source items supporting this memory


def load_cases(db: str, since: str) -> list[Case]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT mf.id AS fid, mf.rating, mf.memory_object_id AS mid,
               mf.memory_type AS rated_type, mf.query_context, mf.memory_text,
               mf.container_ref AS cont,
               qal.id AS aud_id, qal.thread_ref AS aud_thread,
               qal.decision_reason, qal.injection_method,
               qal.candidate_scores_json, qal.injected_blocks_json,
               mo.subject AS mo_subject
        FROM memory_feedback mf
        JOIN query_audit_log qal ON qal.id = mf.query_audit_log_id
        LEFT JOIN memory_objects mo ON mo.id = mf.memory_object_id
        WHERE mf.rating IN ('relevant','not_relevant')
          AND mf.created_at >= ?
          AND qal.candidate_scores_json IS NOT NULL
        """,
        (since,),
    ).fetchall()

    cases: list[Case] = []
    for r in rows:
        cands = json.loads(r["candidate_scores_json"]) or []
        blocks = json.loads(r["injected_blocks_json"]) if r["injected_blocks_json"] else []
        block_mids = {(b.get("memory_object_id") or "") for b in blocks if isinstance(b, dict)}
        target = next((c for c in cands if c.get("memory_object_id") == r["mid"]), None)

        # Pull memory thread (any source item thread the memory descends from).
        mem_thread = None
        srows = con.execute(
            """
            SELECT si.thread_ref FROM relations rel
            JOIN source_items si ON si.id = rel.to_id
            WHERE rel.from_id = ? AND rel.to_kind='source_item'
            ORDER BY si.created_at DESC LIMIT 1
            """,
            (r["mid"],),
        ).fetchone()
        if srows:
            mem_thread = srows["thread_ref"]

        cases.append(
            Case(
                fid=r["fid"],
                rating=r["rating"],
                rated_mid=r["mid"],
                rated_type=r["rated_type"] or "",
                query=r["query_context"] or "",
                container=r["cont"] or "",
                audit_id=r["aud_id"],
                audit_thread=r["aud_thread"],
                decision_reason=r["decision_reason"],
                injection_method=r["injection_method"],
                candidates=cands,
                injected_block_mids=block_mids,
                target_candidate=target,
                memory_subject=r["mo_subject"] or "",
                memory_text=r["memory_text"] or "",
                memory_thread=mem_thread,
            )
        )
    con.close()
    return cases


# -------- Rules -----------------------------------------------------------------

def rule_baseline(c: Case) -> bool:
    """Reproduce shipped behavior: rated memory was actually injected."""
    if c.target_candidate is not None:
        return bool(c.target_candidate.get("injected"))
    return c.rated_mid in c.injected_block_mids


def rule_R1_no_taskcheckpoint_in_cf(c: Case) -> bool:
    """Drop task_checkpoint when path is carry_forward_available (and not same-thread)."""
    if not rule_baseline(c):
        return False
    if c.rated_type != "task_checkpoint":
        return True
    if c.decision_reason != "carry_forward_available":
        return True
    # If memory comes from same audit thread, keep it (legit same-thread carry-forward).
    if c.memory_thread and c.audit_thread and c.memory_thread == c.audit_thread:
        return True
    return False


def rule_R2_subject_overlap(c: Case, min_overlap: int = 1) -> bool:
    """Inject only if memory subject shares >= min_overlap tokens with query."""
    if not rule_baseline(c):
        return False
    qtok = _tokens(c.query)
    stok = _tokens(c.memory_subject)
    if not qtok or not stok:
        # No subject -> fall back to memory_text overlap.
        stok = _tokens(c.memory_text)
        if not stok:
            return True  # can't judge — keep
    return len(qtok & stok) >= min_overlap


def rule_R2b_subject_overlap_2(c: Case) -> bool:
    return rule_R2_subject_overlap(c, min_overlap=2)


def rule_R3_combined(c: Case) -> bool:
    """R1 AND R2(>=1)."""
    return rule_R1_no_taskcheckpoint_in_cf(c) and rule_R2_subject_overlap(c, 1)


def rule_R4_same_thread_or_subject(c: Case) -> bool:
    """Stricter: keep iff (same thread) OR (subject token overlaps query)."""
    if not rule_baseline(c):
        return False
    same_thread = bool(
        c.memory_thread and c.audit_thread and c.memory_thread == c.audit_thread
    )
    if same_thread:
        return True
    qtok = _tokens(c.query)
    stok = _tokens(c.memory_subject) or _tokens(c.memory_text)
    return bool(qtok and stok and (qtok & stok))


def rule_R5_top1_only(c: Case) -> bool:
    """Inject only the top-ranked candidate per query."""
    if not rule_baseline(c):
        return False
    rank = (c.target_candidate or {}).get("routing_rank")
    return rank == 1


def rule_R6_top2_and_subject(c: Case) -> bool:
    """Top-2 ranked AND subject overlap >=1."""
    if not rule_baseline(c):
        return False
    rank = (c.target_candidate or {}).get("routing_rank") or 99
    if rank > 2:
        return False
    return rule_R2_subject_overlap(c, 1)


def rule_R7_strict(c: Case) -> bool:
    """Strict: same_thread OR (rank<=2 AND subject_overlap>=2)."""
    if not rule_baseline(c):
        return False
    same_thread = bool(
        c.memory_thread and c.audit_thread and c.memory_thread == c.audit_thread
    )
    if same_thread:
        return True
    rank = (c.target_candidate or {}).get("routing_rank") or 99
    if rank > 2:
        return False
    qtok = _tokens(c.query)
    stok = _tokens(c.memory_subject) or _tokens(c.memory_text)
    return bool(qtok and stok and len(qtok & stok) >= 2)


def make_rule_idf(idf: dict[str, float], min_score: float):
    """IDF-weighted subject token coverage; threshold on sum(idf of intersect)."""
    def fn(c: Case) -> bool:
        if not rule_baseline(c):
            return False
        qtok = _tokens(c.query)
        stok = _tokens(c.memory_subject) or _tokens(c.memory_text)
        if not qtok or not stok:
            return True  # cannot judge — keep
        inter = qtok & stok
        score = sum(idf.get(t, 0.0) for t in inter)
        return score >= min_score
    return fn


def build_idf(db: str, since: str) -> dict[str, float]:
    """IDF over memory subjects in the rated window."""
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, subject FROM memory_objects WHERE created_at >= ?",
        (since,),
    ).fetchall()
    con.close()
    df: Counter[str] = Counter()
    n = 0
    for r in rows:
        toks = _tokens(r["subject"] or "")
        if toks:
            n += 1
            for t in toks:
                df[t] += 1
    if not n:
        return {}
    return {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}


# -------- Eval ------------------------------------------------------------------

def evaluate(cases: list[Case], rule, name: str):
    kept_rel = kept_nr = dropped_rel = dropped_nr = 0
    n_baseline_inj = 0
    for c in cases:
        keep = rule(c)
        if rule_baseline(c):
            n_baseline_inj += 1
        if keep:
            if c.rating == "relevant":
                kept_rel += 1
            else:
                kept_nr += 1
        else:
            # only count as "dropped" if it was injected by baseline (otherwise it was never in)
            if rule_baseline(c):
                if c.rating == "relevant":
                    dropped_rel += 1
                else:
                    dropped_nr += 1

    kept = kept_rel + kept_nr
    precision = kept_rel / kept if kept else float("nan")
    base_rel = kept_rel + dropped_rel
    recall_vs_base = kept_rel / base_rel if base_rel else float("nan")
    base_nr = kept_nr + dropped_nr
    noise_kill = dropped_nr / base_nr if base_nr else float("nan")

    print(
        f"  {name:<32} kept={kept:>3} (rel={kept_rel:>3} nr={kept_nr:>3})  "
        f"dropped(rel/nr)={dropped_rel}/{dropped_nr}  "
        f"P={precision:.2f} R_vs_base={recall_vs_base:.2f} noise_kill={noise_kill:.2f}"
    )
    return {
        "name": name,
        "kept_rel": kept_rel, "kept_nr": kept_nr,
        "dropped_rel": dropped_rel, "dropped_nr": dropped_nr,
        "precision": precision, "recall_vs_base": recall_vs_base,
        "noise_kill": noise_kill,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / ".pallium" / "data" / "pallium.db"))
    ap.add_argument("--since", default="2026-05-18")
    args = ap.parse_args()

    cases = load_cases(args.db, args.since)
    rel = sum(1 for c in cases if c.rating == "relevant")
    nr = sum(1 for c in cases if c.rating == "not_relevant")
    print(f"# Replay harness — since {args.since}")
    print(f"loaded {len(cases)} rated cases (rel={rel}, nr={nr})")
    no_tgt = sum(1 for c in cases if c.target_candidate is None)
    print(f"  cases without target candidate row: {no_tgt}")
    print()

    print("## Rules")
    print(f"  {'rule':<32} {'kept':>4}  {'breakdown':<24}  metrics")
    idf = build_idf(args.db, args.since)
    print(f"  (IDF vocab: {len(idf)} subject tokens)")
    rules = [
        ("baseline", rule_baseline),
        ("R1 no-tc-in-carry_forward", rule_R1_no_taskcheckpoint_in_cf),
        ("R2 subject_overlap >=1", lambda c: rule_R2_subject_overlap(c, 1)),
        ("R2b subject_overlap >=2", rule_R2b_subject_overlap_2),
        ("R3 R1 AND R2", rule_R3_combined),
        ("R4 same_thread OR subject", rule_R4_same_thread_or_subject),
        ("R5 top1 only", rule_R5_top1_only),
        ("R6 top2 AND subject>=1", rule_R6_top2_and_subject),
        ("R7 thread OR (top2&sub>=2)", rule_R7_strict),
        ("R8 idf_subject>=1.0", make_rule_idf(idf, 1.0)),
        ("R8b idf_subject>=2.0", make_rule_idf(idf, 2.0)),
        ("R8c idf_subject>=3.0", make_rule_idf(idf, 3.0)),
    ]
    results = []
    for name, fn in rules:
        results.append(evaluate(cases, fn, name))

    # Best frontier point: highest precision with recall_vs_base >= 0.7
    print()
    print("## Frontier (recall_vs_base >= 0.70)")
    feasible = [r for r in results if not math.isnan(r["recall_vs_base"]) and r["recall_vs_base"] >= 0.7]
    feasible.sort(key=lambda r: -r["precision"])
    for r in feasible:
        print(f"  {r['name']:<32} P={r['precision']:.2f} R={r['recall_vs_base']:.2f} kill={r['noise_kill']:.2f}")

    # Per-container drill on the best non-baseline rule
    print()
    print("## Per-container breakdown for best rule")
    best = max(
        (r for r in results if r["name"] != "baseline" and r["recall_vs_base"] >= 0.7),
        key=lambda r: r["precision"],
        default=None,
    )
    if best:
        # Re-evaluate per container
        rule_fn = dict(rules)[best["name"]]
        by_cont: dict[str, list[Case]] = {}
        for c in cases:
            by_cont.setdefault(c.container, []).append(c)
        print(f"  using rule: {best['name']}")
        for cont, ccases in sorted(by_cont.items(), key=lambda x: -len(x[1])):
            kept_rel = kept_nr = drop_rel = drop_nr = 0
            for cc in ccases:
                base = rule_baseline(cc)
                keep = rule_fn(cc)
                if keep:
                    if cc.rating == "relevant":
                        kept_rel += 1
                    else:
                        kept_nr += 1
                elif base:
                    if cc.rating == "relevant":
                        drop_rel += 1
                    else:
                        drop_nr += 1
            kept = kept_rel + kept_nr
            p = kept_rel / kept if kept else float("nan")
            base_rel = kept_rel + drop_rel
            r_ = kept_rel / base_rel if base_rel else float("nan")
            print(
                f"    {cont[:42]:<42} n={len(ccases):>3} kept={kept:>3} "
                f"(rel={kept_rel:>2} nr={kept_nr:>2}) drop(r/n)={drop_rel}/{drop_nr}  "
                f"P={p:.2f} R={r_:.2f}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
