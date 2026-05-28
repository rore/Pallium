"""B7 — subject specificity heuristic (no LLM).

Compare subject-text characteristics across REL vs NR rated cards. If
the subjects of NR cards are MEASURABLY MORE GENERIC than REL cards,
it confirms B5/B6's framing that subject quality is the lever.

Heuristics tested per subject:
  - length (chars)
  - token count (after normalize_for_index)
  - number of "concrete" tokens (capitalized words, hyphenated phrases,
    dotted identifiers, snake_case identifiers — proxies for code/system
    names)
  - number of "generic" tokens (from a stopword-like set: findings,
    summary, decisions, task, discussion, work, status, plan, results,
    state, system, design, approach)
  - generic_ratio = generic / total
  - any_concrete_token: 0/1

Outputs aggregate statistics for REL and NR sets.

No LLM. Pure SQL + regex.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from statistics import mean, median

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.text import normalize_for_index  # noqa: E402

GENERIC = {
    "findings", "finding", "summary", "decisions", "decision", "task",
    "tasks", "discussion", "work", "status", "plan", "results", "state",
    "system", "design", "approach", "investigation", "review", "outcome",
    "outcomes", "research", "context", "general", "various", "things",
    "items", "issues", "issue", "checkpoint", "thread",
}

# Concrete token: capitalized (Pallium), dotted (foo.bar), snake (foo_bar),
# camelCase (camelCase), or contains digits.
CONCRETE_RE = re.compile(r"^([A-Z][a-zA-Z]+|\w+[._]\w+|\w+\d\w*)$")


def _stats(label: str, subjects: list[str]) -> dict:
    rows = []
    for s in subjects:
        s = (s or "").strip()
        if not s:
            rows.append({"len": 0, "tok": 0, "conc": 0, "gen": 0, "has_conc": 0})
            continue
        toks = [t for t in normalize_for_index(s).split() if t]
        # Use ORIGINAL string for case-based concrete detection.
        orig_toks = [t for t in re.findall(r"\S+", s)]
        conc = sum(1 for t in orig_toks if CONCRETE_RE.match(t))
        gen = sum(1 for t in toks if t in GENERIC)
        rows.append({
            "len": len(s),
            "tok": len(toks),
            "conc": conc,
            "gen": gen,
            "has_conc": 1 if conc > 0 else 0,
        })
    n = len(rows)

    def _agg(field):
        vals = [r[field] for r in rows]
        return {
            "mean": mean(vals) if vals else 0,
            "median": median(vals) if vals else 0,
        }

    has_conc_rate = sum(r["has_conc"] for r in rows) / n if n else 0
    return {
        "label": label,
        "n": n,
        "len": _agg("len"),
        "tok": _agg("tok"),
        "concrete_tokens": _agg("conc"),
        "generic_tokens": _agg("gen"),
        "any_concrete_rate": has_conc_rate,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / ".pallium" / "data" / "pallium.db"))
    ap.add_argument("--since", default="2026-05-18")
    ap.add_argument("--out", type=Path,
                    default=_PROJECT_ROOT / ".local" / "research"
                    / "subject_specificity_2026-05-27.md")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT mf.rating, COALESCE(mo.subject, mf.memory_text) AS subj
        FROM memory_feedback mf
        LEFT JOIN memory_objects mo ON mo.id = mf.memory_object_id
        WHERE mf.rating IN ('relevant', 'not_relevant') AND mf.created_at >= ?
        """,
        (args.since,),
    ).fetchall()

    rel_subjects = [r["subj"] or "" for r in rows if r["rating"] == "relevant"]
    nr_subjects = [r["subj"] or "" for r in rows if r["rating"] == "not_relevant"]

    rel = _stats("relevant", rel_subjects)
    nr = _stats("not_relevant", nr_subjects)

    def fmt(s):
        return (
            f"  n={s['n']}\n"
            f"  len: mean {s['len']['mean']:.1f} med {s['len']['median']:.0f}\n"
            f"  tok: mean {s['tok']['mean']:.1f} med {s['tok']['median']:.0f}\n"
            f"  concrete tokens: mean {s['concrete_tokens']['mean']:.2f}\n"
            f"  generic tokens:  mean {s['generic_tokens']['mean']:.2f}\n"
            f"  any concrete: {s['any_concrete_rate']*100:.0f}%"
        )

    md = "\n".join([
        f"# Subject specificity heuristic (REL vs NR rated since {args.since})",
        "",
        "## Relevant",
        fmt(rel),
        "",
        "## Not relevant",
        fmt(nr),
        "",
        "## Spread",
        f"  any-concrete diff (REL - NR): {(rel['any_concrete_rate'] - nr['any_concrete_rate'])*100:+.0f}pp",
        f"  concrete-tokens-mean diff: {rel['concrete_tokens']['mean'] - nr['concrete_tokens']['mean']:+.2f}",
        f"  generic-tokens-mean diff: {rel['generic_tokens']['mean'] - nr['generic_tokens']['mean']:+.2f}",
        "",
        "(Positive deltas = REL subjects more specific than NR subjects.)",
    ])
    print(md)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
