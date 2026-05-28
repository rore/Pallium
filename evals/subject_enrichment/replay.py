"""Replay R2b (subject_overlap >= 2) against historical query_audit_log rows
using each of V1 / V2 / V3 enriched subjects.

This is the core counterfactual: would R2b — proposed at P=0.42→0.52, R=0.81 —
hold up if we measured *real* topic overlap instead of body-text overlap?

For each variant V1 / V2 / V3:
  1. Walk every query_audit_log row since 2026-05-18 with non-empty
     candidate_scores_json.
  2. For each candidate the system actually injected (candidate.injected = True
     OR present in injected_blocks_json), look up the variant's subject from the
     enriched dataset.
  3. Tokenize the query and the variant subject via core.text.normalize_for_index
     and compute set overlap.
  4. R2b says KEEP iff overlap >= 2 ELSE DROP.
  5. Cross-reference KEEP/DROP against memory_feedback ratings linked to the
     same audit row.

Aggregate metrics:
  precision        = relevant_in_kept / total_kept
  recall_vs_base   = relevant_in_kept / (relevant_in_kept + relevant_in_dropped)
  drop_rate        = total_dropped    / (total_kept + total_dropped)
  false_skip_rate  = relevant_in_dropped / total_dropped

Read-only on the production DB. Writes the report markdown to
.local/research/subject_enrichment_replay_2026-05-28.md.

Usage::
    python -m evals.subject_enrichment.replay
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.text import normalize_for_index  # noqa: E402

DEFAULT_DB = str(Path.home() / ".pallium" / "data" / "pallium.db")
DEFAULT_SUBJECTS = (
    _PROJECT_ROOT
    / "evals"
    / "subject_enrichment"
    / "output"
    / "subjects_2026-05-28.jsonl"
)
DEFAULT_REPORT = (
    _PROJECT_ROOT / ".local" / "research" / "subject_enrichment_replay_2026-05-28.md"
)
DEFAULT_RUN_LOG = _PROJECT_ROOT / ".local" / "research" / "_subject_enrichment_run.md"
SINCE = "2026-05-18"

VARIANTS = ("v1_fallback", "v2_deterministic", "v3_llm")
VARIANT_KEY = {
    "v1_fallback": "subject_v1_fallback",
    "v2_deterministic": "subject_v2_deterministic",
    "v3_llm": "subject_v3_llm",
}
MIN_OVERLAP = 2


def _tokens(s: str) -> set[str]:
    return {t for t in normalize_for_index(s or "").split() if t}


# ---------------------------------------------------------------------------
# Data load
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    audit_id: str
    query: str
    container: str
    memory_object_id: str
    injected: bool
    rating: str | None  # 'relevant' / 'not_relevant' / None


def _load_subjects(path: Path) -> dict[str, dict[str, str]]:
    """memory_object_id -> {v1_fallback,v2_deterministic,v3_llm,type}."""
    out: dict[str, dict[str, str]] = {}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            mid = row.get("memory_object_id")
            if not mid:
                continue
            out[mid] = {
                "v1_fallback": row.get("subject_v1_fallback") or "",
                "v2_deterministic": row.get("subject_v2_deterministic") or "",
                "v3_llm": row.get("subject_v3_llm") or "",
                "type": row.get("type") or "",
                "container": row.get("container_ref") or "",
            }
    return out


def _load_candidates(db: str) -> list[Candidate]:
    """Pull the per-audit-row injected candidates and any feedback ratings.

    The source of truth for "did the system inject this" is `injected=True`
    on the candidate row (or membership in `injected_blocks_json` as a
    fallback). We only consider injected candidates — R2b is a *gate on
    injection*, so dropped-pre-injection candidates are not in scope.
    """
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    # All ratings keyed by (audit_id, memory_object_id)
    rating_map: dict[tuple[str, str], str] = {}
    for r in con.execute(
        """SELECT query_audit_log_id, memory_object_id, rating
           FROM memory_feedback
           WHERE rating IN ('relevant','not_relevant')
             AND created_at >= ?""",
        (SINCE,),
    ).fetchall():
        if r["query_audit_log_id"]:
            rating_map[(r["query_audit_log_id"], r["memory_object_id"])] = r["rating"]

    rows = con.execute(
        """SELECT id, query_text, container_ref,
                  candidate_scores_json, injected_blocks_json
           FROM query_audit_log
           WHERE created_at >= ?
             AND candidate_scores_json IS NOT NULL""",
        (SINCE,),
    ).fetchall()

    out: list[Candidate] = []
    for r in rows:
        try:
            cands = json.loads(r["candidate_scores_json"]) or []
        except Exception:
            cands = []
        try:
            blocks = json.loads(r["injected_blocks_json"]) if r["injected_blocks_json"] else []
        except Exception:
            blocks = []
        block_mids = {(b.get("memory_object_id") or "") for b in blocks if isinstance(b, dict)}

        for c in cands:
            if not isinstance(c, dict):
                continue
            mid = c.get("memory_object_id") or ""
            if not mid:
                continue
            injected = bool(c.get("injected")) or (mid in block_mids)
            if not injected:
                continue
            rating = rating_map.get((r["id"], mid))
            out.append(
                Candidate(
                    audit_id=r["id"],
                    query=r["query_text"] or "",
                    container=r["container_ref"] or "",
                    memory_object_id=mid,
                    injected=True,
                    rating=rating,
                )
            )
    con.close()
    return out


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def _replay_variant(
    cands: list[Candidate],
    subjects: dict[str, dict[str, str]],
    variant: str,
) -> dict[str, Any]:
    kept_total = 0
    kept_rel = 0
    kept_nr = 0
    dropped_total = 0
    dropped_rel = 0
    dropped_nr = 0
    no_subject = 0
    rated_total = 0
    rel_total = 0
    missing_in_dataset = 0

    overlap_hist: Counter[int] = Counter()

    for c in cands:
        sub_row = subjects.get(c.memory_object_id)
        if sub_row is None:
            missing_in_dataset += 1
            # Treat as KEEP (cannot apply gate without a subject; fail-safe).
            keep = True
            overlap = -1
        else:
            subject = sub_row.get(variant, "") or ""
            if not subject:
                no_subject += 1
                # Same fail-safe: empty subject => KEEP.
                keep = True
                overlap = -1
            else:
                qtok = _tokens(c.query)
                stok = _tokens(subject)
                overlap = len(qtok & stok)
                keep = overlap >= MIN_OVERLAP
                overlap_hist[overlap] += 1
        if c.rating in ("relevant", "not_relevant"):
            rated_total += 1
            if c.rating == "relevant":
                rel_total += 1
        if keep:
            kept_total += 1
            if c.rating == "relevant":
                kept_rel += 1
            elif c.rating == "not_relevant":
                kept_nr += 1
        else:
            dropped_total += 1
            if c.rating == "relevant":
                dropped_rel += 1
            elif c.rating == "not_relevant":
                dropped_nr += 1

    rated_kept = kept_rel + kept_nr
    rated_dropped = dropped_rel + dropped_nr
    precision = (kept_rel / rated_kept) if rated_kept else float("nan")
    recall = (kept_rel / rel_total) if rel_total else float("nan")
    drop_rate = (dropped_total / (kept_total + dropped_total)) if (kept_total + dropped_total) else float("nan")
    # false_skip_rate as defined: fraction of dropped that were rated relevant
    false_skip = (dropped_rel / rated_dropped) if rated_dropped else float("nan")

    return {
        "variant": variant,
        "n_candidates": len(cands),
        "kept_total": kept_total,
        "kept_rel": kept_rel,
        "kept_nr": kept_nr,
        "dropped_total": dropped_total,
        "dropped_rel": dropped_rel,
        "dropped_nr": dropped_nr,
        "rated_total": rated_total,
        "rel_total": rel_total,
        "no_subject": no_subject,
        "missing_in_dataset": missing_in_dataset,
        "precision": precision,
        "recall": recall,
        "drop_rate": drop_rate,
        "false_skip_rate": false_skip,
        "overlap_hist": dict(sorted(overlap_hist.items())),
    }


def _coverage_table(subjects: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Per-variant coverage stats and per-type breakdown."""
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: {
        "n": 0,
        "v1_nonempty": 0,
        "v2_nonempty": 0,
        "v2_eq_v1": 0,
        "v3_nonempty": 0,
        "v3_eq_v2": 0,
    })
    total = {"n": 0, "v1_nonempty": 0, "v2_nonempty": 0, "v2_eq_v1": 0,
             "v3_nonempty": 0, "v3_eq_v2": 0}
    for mid, row in subjects.items():
        t = row.get("type") or "unknown"
        by_type[t]["n"] += 1
        total["n"] += 1
        v1 = row.get("v1_fallback") or ""
        v2 = row.get("v2_deterministic") or ""
        v3 = row.get("v3_llm") or ""
        if v1.strip():
            by_type[t]["v1_nonempty"] += 1
            total["v1_nonempty"] += 1
        if v2.strip():
            by_type[t]["v2_nonempty"] += 1
            total["v2_nonempty"] += 1
        if v2 == v1:
            by_type[t]["v2_eq_v1"] += 1
            total["v2_eq_v1"] += 1
        if v3.strip():
            by_type[t]["v3_nonempty"] += 1
            total["v3_nonempty"] += 1
        if v3 == v2:
            by_type[t]["v3_eq_v2"] += 1
            total["v3_eq_v2"] += 1
    return {"by_type": dict(by_type), "total": total}


def _format_pct(n: int, d: int) -> str:
    if not d:
        return "n/a"
    return f"{n}/{d} ({100 * n / d:.0f}%)"


def _format_metric(x: float) -> str:
    if math.isnan(x):
        return "n/a"
    return f"{x:.3f}"


def _sample_side_by_side(
    subjects: dict[str, dict[str, str]],
    n: int = 20,
) -> list[dict[str, str]]:
    # Pick 20 with maximum visible divergence between v1 and v3 (i.e.,
    # cases where the variants would actually behave differently).
    scored = []
    for mid, row in subjects.items():
        v1 = row.get("v1_fallback") or ""
        v2 = row.get("v2_deterministic") or ""
        v3 = row.get("v3_llm") or ""
        if not (v1 or v2 or v3):
            continue
        # Diversity score: prefer rows where v1 differs from v3 in token set.
        t1 = _tokens(v1)
        t3 = _tokens(v3)
        # Ratio of unique tokens added/removed
        union = t1 | t3
        if not union:
            continue
        diff = len(t1 ^ t3) / len(union)
        scored.append((diff, mid, row))
    scored.sort(key=lambda x: -x[0])
    # Diversify by type if possible.
    seen_types: Counter[str] = Counter()
    picks: list[dict[str, str]] = []
    for diff, mid, row in scored:
        t = row.get("type") or ""
        if seen_types[t] >= max(2, n // 5):
            continue
        seen_types[t] += 1
        picks.append({"memory_object_id": mid, "type": t, **row})
        if len(picks) >= n:
            break
    return picks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--subjects", type=Path, default=DEFAULT_SUBJECTS)
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--run-log", type=Path, default=DEFAULT_RUN_LOG)
    args = ap.parse_args()

    subjects = _load_subjects(args.subjects)
    print(f"loaded {len(subjects)} enriched memory rows from {args.subjects}")
    if not subjects:
        print("ERROR: no enriched subjects found. Run `python -m evals.subject_enrichment.enrich` first.")
        return 1

    cands = _load_candidates(args.db)
    print(f"loaded {len(cands)} injected candidates since {SINCE}")
    rated = sum(1 for c in cands if c.rating in ("relevant", "not_relevant"))
    rel = sum(1 for c in cands if c.rating == "relevant")
    nr = sum(1 for c in cands if c.rating == "not_relevant")
    print(f"  rated: {rated} (rel={rel}, nr={nr})")

    coverage = _coverage_table(subjects)
    print()
    print("## Coverage by type")
    for t, s in sorted(coverage["by_type"].items()):
        print(
            f"  {t:<25} n={s['n']:>4}  "
            f"v1={s['v1_nonempty']:>4}  "
            f"v2={s['v2_nonempty']:>4} (v2=v1: {s['v2_eq_v1']:>4})  "
            f"v3={s['v3_nonempty']:>4} (v3=v2: {s['v3_eq_v2']:>4})"
        )

    print()
    print("## Replay results (R2b: subject_overlap >= 2)")
    results: dict[str, dict[str, Any]] = {}
    for v in VARIANTS:
        res = _replay_variant(cands, subjects, v)
        results[v] = res
        print(
            f"  {v:<22} kept={res['kept_total']:>4} "
            f"(rel={res['kept_rel']:>3} nr={res['kept_nr']:>3})  "
            f"dropped={res['dropped_total']:>4} (rel={res['dropped_rel']:>3} nr={res['dropped_nr']:>3})  "
            f"P={_format_metric(res['precision'])} "
            f"R={_format_metric(res['recall'])} "
            f"drop={_format_metric(res['drop_rate'])} "
            f"fskip={_format_metric(res['false_skip_rate'])}"
        )

    samples = _sample_side_by_side(subjects, n=20)

    # ---------- Markdown report ----------
    out_lines: list[str] = []
    out_lines.append("# Subject enrichment replay — 2026-05-28")
    out_lines.append("")
    out_lines.append(f"- since: {SINCE}")
    out_lines.append(f"- enriched memories: **{len(subjects)}**")
    out_lines.append(f"- injected candidates replayed: **{len(cands)}** "
                     f"(rated rel={rel}, nr={nr})")
    out_lines.append(f"- gate: R2b (subject token overlap with query >= 2)")
    out_lines.append("")

    out_lines.append("## 1. Coverage")
    out_lines.append("")
    out_lines.append("| type | n | V1 nonempty | V2 nonempty | V2==V1 | V3 nonempty | V3==V2 |")
    out_lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for t, s in sorted(coverage["by_type"].items()):
        out_lines.append(
            f"| {t} | {s['n']} | {s['v1_nonempty']} | {s['v2_nonempty']} | "
            f"{s['v2_eq_v1']} | {s['v3_nonempty']} | {s['v3_eq_v2']} |"
        )
    tot = coverage["total"]
    out_lines.append(
        f"| **total** | {tot['n']} | {tot['v1_nonempty']} | {tot['v2_nonempty']} | "
        f"{tot['v2_eq_v1']} | {tot['v3_nonempty']} | {tot['v3_eq_v2']} |"
    )
    out_lines.append("")
    out_lines.append("V2==V1 means V2's deterministic extractor produced the same string as V1's fallback (i.e. it added no signal). "
                     "V3==V2 means the LLM was unavailable / cached fallback / produced an identical phrase.")
    out_lines.append("")

    out_lines.append("## 2. Side-by-side: 20 sampled memories (V1 vs V2 vs V3)")
    out_lines.append("")
    out_lines.append("| # | type | V1 (fallback) | V2 (deterministic) | V3 (LLM) |")
    out_lines.append("|---|---|---|---|---|")

    def _trim(s: str, n: int = 65) -> str:
        s = (s or "").replace("\n", " ").replace("|", "/")
        return (s[: n - 1] + "…") if len(s) > n else s

    for i, s in enumerate(samples, 1):
        out_lines.append(
            f"| {i} | {s['type']} | {_trim(s.get('v1_fallback', ''))} | "
            f"{_trim(s.get('v2_deterministic', ''))} | "
            f"{_trim(s.get('v3_llm', ''))} |"
        )
    out_lines.append("")

    out_lines.append("## 3. R2b replay results (overlap >= 2)")
    out_lines.append("")
    out_lines.append("| variant | kept | kept rel | kept nr | dropped | dropped rel | dropped nr | precision | recall | drop rate | false-skip |")
    out_lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for v in VARIANTS:
        res = results[v]
        out_lines.append(
            f"| **{v}** | {res['kept_total']} | {res['kept_rel']} | {res['kept_nr']} | "
            f"{res['dropped_total']} | {res['dropped_rel']} | {res['dropped_nr']} | "
            f"{_format_metric(res['precision'])} | {_format_metric(res['recall'])} | "
            f"{_format_metric(res['drop_rate'])} | {_format_metric(res['false_skip_rate'])} |"
        )
    out_lines.append("")
    out_lines.append("Definitions:")
    out_lines.append("- precision = relevant_in_kept / total_kept (rated only)")
    out_lines.append("- recall = relevant_in_kept / total_relevant (rated only)")
    out_lines.append("- drop_rate = dropped / (kept + dropped) over ALL injected candidates (rated and unrated)")
    out_lines.append("- false_skip_rate = dropped_relevant / dropped_rated (rated only)")
    out_lines.append("")
    out_lines.append("Note: when a variant subject is empty or the memory is missing from the enrichment dataset, "
                     "the gate fails-safe to KEEP. This is conservative on recall but inflates precision toward "
                     "baseline for V1 (which is more often empty in our active set, but also matches the production "
                     "fallback that uses body text).")
    out_lines.append("")

    # Compute deltas to answer the key question.
    p_v1 = results["v1_fallback"]["precision"]
    p_v2 = results["v2_deterministic"]["precision"]
    p_v3 = results["v3_llm"]["precision"]
    r_v1 = results["v1_fallback"]["recall"]
    r_v2 = results["v2_deterministic"]["recall"]
    r_v3 = results["v3_llm"]["recall"]
    d_v1 = results["v1_fallback"]["drop_rate"]
    d_v2 = results["v2_deterministic"]["drop_rate"]
    d_v3 = results["v3_llm"]["drop_rate"]

    def _delta(a: float, b: float) -> str:
        if math.isnan(a) or math.isnan(b):
            return "n/a"
        return f"{(b - a):+.3f}"

    out_lines.append("## 4. Does the LLM subject move the needle?")
    out_lines.append("")
    out_lines.append("ΔP, ΔR, Δdrop relative to V1 (the baseline / production fallback):")
    out_lines.append("")
    out_lines.append("| metric | V1 | V2 | V3 | ΔV2 | ΔV3 |")
    out_lines.append("|---|---:|---:|---:|---:|---:|")
    out_lines.append(
        f"| precision | {_format_metric(p_v1)} | {_format_metric(p_v2)} | {_format_metric(p_v3)} | {_delta(p_v1, p_v2)} | {_delta(p_v1, p_v3)} |"
    )
    out_lines.append(
        f"| recall    | {_format_metric(r_v1)} | {_format_metric(r_v2)} | {_format_metric(r_v3)} | {_delta(r_v1, r_v2)} | {_delta(r_v1, r_v3)} |"
    )
    out_lines.append(
        f"| drop_rate | {_format_metric(d_v1)} | {_format_metric(d_v2)} | {_format_metric(d_v3)} | {_delta(d_v1, d_v2)} | {_delta(d_v1, d_v3)} |"
    )
    out_lines.append("")

    # Decide a verdict programmatically.
    if not any(math.isnan(x) for x in (p_v1, p_v3, r_v1, r_v3)):
        prec_gain = p_v3 - p_v1
        recall_gap = r_v1 - r_v3
        if prec_gain >= 0.05 and recall_gap <= 0.05:
            verdict = (
                "**Yes** — V3 lifts precision by "
                f"{prec_gain:+.2f} at comparable recall (Δ={-recall_gap:+.2f}). "
                "Better subjects are a real lever."
            )
        elif prec_gain >= 0.02:
            verdict = (
                "**Marginal** — V3 lifts precision by "
                f"{prec_gain:+.2f}, but recall drops by {recall_gap:.2f}. "
                "Subject quality helps slightly; the dominant gating signal is elsewhere."
            )
        else:
            verdict = (
                "**No** — V3 does not materially beat V1. ΔP="
                f"{prec_gain:+.2f}, ΔR={-recall_gap:+.2f}. "
                "The dominant noise is not subject-extraction quality."
            )
    else:
        verdict = "**Inconclusive** — one or more metrics undefined (no rated candidates in the slice)."
    out_lines.append("**Verdict:** " + verdict)
    out_lines.append("")

    # Recommendation
    out_lines.append("## 5. Recommendation")
    out_lines.append("")
    if not any(math.isnan(x) for x in (p_v1, p_v3, r_v1, r_v3)):
        prec_gain = p_v3 - p_v1
        recall_gap = r_v1 - r_v3
        if prec_gain >= 0.05 and recall_gap <= 0.05:
            rec = (
                "Pursue subject enrichment. V3 is the clear winner on precision; "
                "ship it as a write-time prompt or post-hoc extractor and re-run R2b on production. "
                "V2 is a free fallback for memory types that already carry retrieval_context."
            )
        elif prec_gain >= 0.02:
            rec = (
                "Don't ship subject-based gating yet. The LLM-extracted subject helps a little, "
                "but the recall cost is non-trivial. Bigger lever is upstream — investigate routing/skip-override "
                "and per-type ranking ahead of subject extraction."
            )
        else:
            rec = (
                "Do not pursue subject enrichment as a gate. All three variants produce similar replay numbers, "
                "which means the dominant noise is elsewhere (likely routing/skip-override, body-overlap acting as "
                "a near-equivalent of topic-overlap, or the fail-safe-keep behavior swallowing the gate). "
                "Focus on the routing path and per-container precision instead."
            )
    else:
        rec = "Cannot recommend — insufficient rated coverage."
    out_lines.append(rec)
    out_lines.append("")

    out_lines.append("## 6. Overlap histograms (informational)")
    out_lines.append("")
    out_lines.append("| variant | overlap=0 | =1 | =2 | =3 | >=4 |")
    out_lines.append("|---|---:|---:|---:|---:|---:|")
    for v in VARIANTS:
        h = results[v]["overlap_hist"]
        c0 = h.get(0, 0); c1 = h.get(1, 0); c2 = h.get(2, 0); c3 = h.get(3, 0)
        c4 = sum(n for k, n in h.items() if k >= 4)
        out_lines.append(f"| {v} | {c0} | {c1} | {c2} | {c3} | {c4} |")
    out_lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nwrote {args.out}")

    # Append a compact run-log entry.
    rl = []
    rl.append(f"\n## replay run (R2b, since {SINCE})\n")
    rl.append(f"- candidates: {len(cands)} injected (rated rel={rel}, nr={nr})")
    for v in VARIANTS:
        res = results[v]
        rl.append(
            f"- {v}: P={_format_metric(res['precision'])} "
            f"R={_format_metric(res['recall'])} "
            f"drop={_format_metric(res['drop_rate'])} "
            f"fskip={_format_metric(res['false_skip_rate'])} "
            f"missing={res['missing_in_dataset']} no_subject={res['no_subject']}"
        )
    args.run_log.parent.mkdir(parents=True, exist_ok=True)
    with args.run_log.open("a", encoding="utf-8") as f:
        f.write("\n".join(rl) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
