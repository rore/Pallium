"""I2 — classify all NR investigation_outcome cards by container, self-referential
pattern, and extraction shape. Pure SQL, no LLM.

Question: what fraction would the P7 self-referential guard catch?

Categories:
  - container in {rore/pallium}? Y/N
  - query mentions {pallium, memory, extraction, injection, mcp, claude
    code, hooks, pre_compact, mcp tools}? (broad self-ref query)
  - body looks like meta-commentary about the system itself ("memory
    doesn't exist", "Pallium has no memory", "It doesn't exist or I
    don't have access")? Heuristic regex.
  - body mentions specific platform / library / customer entity?
    (i.e. would *not* be caught by a self-ref guard).
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB = os.path.expanduser("~/.pallium/data/pallium.db")
SINCE = "2026-05-18"
OUT = _PROJECT_ROOT / ".local" / "research" / "investigation_outcome_nr_classification_2026-05-27.md"

SELF_REF_TERMS = (
    "pallium", "memory", "extraction", "injection", "investigation",
    "mcp", "claude code", "hooks", "pre_compact", "session_start",
    "ratings", "feedback",
)

META_PATTERNS = [
    re.compile(r"genuinely doesn'?t exist", re.I),
    re.compile(r"no memory about", re.I),
    re.compile(r"i don'?t have access", re.I),
    re.compile(r"It doesn'?t exist", re.I),
    re.compile(r"never ingested", re.I),
    re.compile(r"phrase ['\"].*['\"]", re.I),
    re.compile(r"is the real bug", re.I),
    re.compile(r"What we didn'?t touch", re.I),
    re.compile(r"hooks are defined exactly once", re.I),
    re.compile(r"different luck", re.I),
    re.compile(r"can'?t see pallium tools", re.I),
]


def is_self_ref_query(q: str) -> bool:
    q = (q or "").lower()
    return any(t in q for t in SELF_REF_TERMS)


def is_meta_body(b: str) -> bool:
    return any(p.search(b or "") for p in META_PATTERNS)


def main() -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        f"""
        SELECT mf.id AS fid, mf.memory_text, mf.query_context,
               mf.container_ref, mo.subject
        FROM memory_feedback mf
        LEFT JOIN memory_objects mo ON mo.id = mf.memory_object_id
        WHERE mf.rating='not_relevant'
          AND mf.memory_type='investigation_outcome'
          AND mf.created_at >= ?
        """,
        (SINCE,),
    ).fetchall()

    n = len(rows)
    n_pallium_container = 0
    n_self_ref_query = 0
    n_meta_body = 0
    n_p7_caught = 0  # rore/pallium AND self-ref query
    n_clean_off_topic = 0  # not pallium and not self-ref
    table_lines = ["| # | container | self_ref_q | meta_body | p7_caught | query | body |", "|-|-|-|-|-|-|-|"]
    for i, r in enumerate(rows, 1):
        cont = r["container_ref"] or ""
        in_pallium = "rore/pallium" in cont
        sr_q = is_self_ref_query(r["query_context"])
        meta_b = is_meta_body(r["memory_text"])
        p7 = in_pallium and sr_q
        if in_pallium:
            n_pallium_container += 1
        if sr_q:
            n_self_ref_query += 1
        if meta_b:
            n_meta_body += 1
        if p7:
            n_p7_caught += 1
        if not in_pallium and not sr_q:
            n_clean_off_topic += 1
        cont_short = cont[-30:] if cont else ""
        q = (r["query_context"] or "")[:50].replace("|", "/").replace("\n", " ")
        b = (r["memory_text"] or "")[:50].replace("|", "/").replace("\n", " ")
        table_lines.append(
            f"| {i} | {cont_short} | {'Y' if sr_q else 'N'} | {'Y' if meta_b else 'N'} "
            f"| {'Y' if p7 else 'N'} | {q} | {b} |"
        )

    out_md = "\n".join([
        f"# I2 — investigation_outcome NR classification ({n} cases since {SINCE})",
        "",
        f"- in container `git:github.com/rore/pallium`: {n_pallium_container} ({n_pallium_container/n*100:.0f}%)",
        f"- query is self-referential (mentions pallium/memory/extraction/etc): {n_self_ref_query} ({n_self_ref_query/n*100:.0f}%)",
        f"- body is meta-commentary about the system: {n_meta_body} ({n_meta_body/n*100:.0f}%)",
        f"- **P7 (rore/pallium AND self-ref query) would catch: {n_p7_caught} ({n_p7_caught/n*100:.0f}%)**",
        f"- truly off-topic NR (not in pallium, query not self-ref): {n_clean_off_topic} ({n_clean_off_topic/n*100:.0f}%)",
        "",
        "## Per-case classification",
        "",
        *table_lines,
    ])
    print(out_md)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(out_md, encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
