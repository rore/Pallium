"""
Analyze injection frequency from query_audit_log.

Computes per-memory injection counts from injected_blocks_json,
correlates with memory_feedback ratings, and reports whether
injection frequency is a useful quality signal.

Usage:
    python scripts/analyze_injection_frequency.py [--db PATH]

Default DB: ~/.pallium/data/pallium.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


DEFAULT_DB = Path.home() / ".pallium" / "data" / "pallium.db"


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def analyze(db_path: Path) -> None:
    conn = connect(db_path)

    # --- Basic stats ---
    section("Audit Log Overview")
    row = conn.execute(
        "SELECT COUNT(*) as total, SUM(should_inject) as injected FROM query_audit_log"
    ).fetchone()
    total_queries = row["total"]
    injected_queries = row["injected"] or 0
    print(f"Total queries logged:      {total_queries}")
    print(f"Queries with injection:    {injected_queries} ({injected_queries*100//max(total_queries,1)}%)")

    date_range = conn.execute(
        "SELECT MIN(created_at) as earliest, MAX(created_at) as latest FROM query_audit_log"
    ).fetchone()
    print(f"Date range:                {date_range['earliest']} to {date_range['latest']}")

    # --- Per-memory injection frequency ---
    section("Injection Frequency Distribution")

    injection_counts: dict[str, int] = {}
    rows = conn.execute(
        "SELECT injected_blocks_json FROM query_audit_log WHERE should_inject = 1"
    ).fetchall()
    for r in rows:
        blocks = json.loads(r["injected_blocks_json"])
        for block in blocks:
            mid = block.get("memory_object_id")
            if mid:
                injection_counts[mid] = injection_counts.get(mid, 0) + 1

    if not injection_counts:
        print("No injection data found.")
        conn.close()
        return

    total_active = conn.execute(
        "SELECT COUNT(*) as cnt FROM memory_objects WHERE lifecycle = 'active'"
    ).fetchone()["cnt"]

    injected_count = len(injection_counts)
    never_injected = total_active - injected_count

    print(f"Active memories:           {total_active}")
    print(f"Ever injected:             {injected_count} ({injected_count*100//max(total_active,1)}%)")
    print(f"Never injected:            {never_injected} ({never_injected*100//max(total_active,1)}%)")
    print()

    # Frequency buckets
    buckets = {"1x": 0, "2-3x": 0, "4-5x": 0, "6-10x": 0, "11+": 0}
    for count in injection_counts.values():
        if count == 1:
            buckets["1x"] += 1
        elif count <= 3:
            buckets["2-3x"] += 1
        elif count <= 5:
            buckets["4-5x"] += 1
        elif count <= 10:
            buckets["6-10x"] += 1
        else:
            buckets["11+"] += 1

    print("Injection frequency buckets:")
    for bucket, count in buckets.items():
        bar = "#" * min(count, 40)
        print(f"  {bucket:>6}: {count:>4}  {bar}")

    # --- Top injected memories ---
    section("Top 15 Most-Injected Memories")
    sorted_mems = sorted(injection_counts.items(), key=lambda x: -x[1])[:15]

    print(f"{'ID':<38} {'Type':<22} {'Inj#':>4}  Subject/Preview")
    print(f"{'-'*38} {'-'*22} {'-'*4}  {'-'*30}")

    for mid, count in sorted_mems:
        info = conn.execute(
            "SELECT type, subject, payload_json FROM memory_objects WHERE id = ?",
            (mid,),
        ).fetchone()
        if info:
            mtype = info["type"]
            subject = info["subject"] or ""
            if not subject:
                try:
                    payload = json.loads(info["payload_json"])
                    subject = payload.get("title", payload.get("summary", ""))[:40]
                except (json.JSONDecodeError, TypeError):
                    subject = ""
            print(f"{mid:<38} {mtype:<22} {count:>4}  {subject[:40]}")
        else:
            print(f"{mid:<38} {'(deleted)':<22} {count:>4}")

    # --- Correlation with feedback ---
    section("Injection Frequency vs Feedback Quality")

    feedback_rows = conn.execute(
        "SELECT memory_object_id, rating FROM memory_feedback"
    ).fetchall()

    feedback_by_memory: dict[str, dict[str, int]] = {}
    for fr in feedback_rows:
        mid = fr["memory_object_id"]
        rating = fr["rating"]
        if mid not in feedback_by_memory:
            feedback_by_memory[mid] = {"relevant": 0, "not_relevant": 0}
        feedback_by_memory[mid][rating] = feedback_by_memory[mid].get(rating, 0) + 1

    # Group by injection frequency bucket and compute average feedback ratio
    freq_groups: dict[str, list[float]] = {"0x": [], "1x": [], "2-3x": [], "4+": []}

    for mid, fb in feedback_by_memory.items():
        total_fb = fb["relevant"] + fb["not_relevant"]
        if total_fb == 0:
            continue
        ratio = fb["relevant"] / total_fb
        inj_count = injection_counts.get(mid, 0)
        if inj_count == 0:
            freq_groups["0x"].append(ratio)
        elif inj_count == 1:
            freq_groups["1x"].append(ratio)
        elif inj_count <= 3:
            freq_groups["2-3x"].append(ratio)
        else:
            freq_groups["4+"].append(ratio)

    print(f"{'Inj Freq':<10} {'Memories':>8} {'Avg Relevant%':>14} {'Interpretation'}")
    print(f"{'-'*10} {'-'*8} {'-'*14} {'-'*30}")
    for bucket in ["0x", "1x", "2-3x", "4+"]:
        ratios = freq_groups[bucket]
        if ratios:
            avg = sum(ratios) / len(ratios)
            interp = "(sparse)" if len(ratios) < 5 else ""
            print(f"{bucket:<10} {len(ratios):>8} {avg*100:>13.1f}% {interp}")
        else:
            print(f"{bucket:<10} {0:>8} {'N/A':>14}")

    print()
    print("Key question: does higher injection frequency correlate with")
    print("higher relevant% (positive correlation = useful signal)?")
    print()

    # Statistical summary
    all_injected_ratios = []
    all_zero_ratios = []
    for mid, fb in feedback_by_memory.items():
        total_fb = fb["relevant"] + fb["not_relevant"]
        if total_fb == 0:
            continue
        ratio = fb["relevant"] / total_fb
        if injection_counts.get(mid, 0) > 0:
            all_injected_ratios.append(ratio)
        else:
            all_zero_ratios.append(ratio)

    if all_injected_ratios:
        avg_inj = sum(all_injected_ratios) / len(all_injected_ratios)
        print(f"  Avg relevant% for injected memories (n={len(all_injected_ratios)}):     {avg_inj*100:.1f}%")
    if all_zero_ratios:
        avg_zero = sum(all_zero_ratios) / len(all_zero_ratios)
        print(f"  Avg relevant% for never-injected memories (n={len(all_zero_ratios)}):  {avg_zero*100:.1f}%")

    # --- Auto-suppression candidates ---
    section("Auto-Suppression Candidates (high injection + poor ratings)")
    print("Memories injected 3+ times with >60% not_relevant feedback:\n")

    candidates = []
    for mid, count in injection_counts.items():
        if count < 3:
            continue
        fb = feedback_by_memory.get(mid)
        if not fb:
            continue
        total_fb = fb["relevant"] + fb["not_relevant"]
        if total_fb < 2:
            continue
        not_rel_ratio = fb["not_relevant"] / total_fb
        if not_rel_ratio > 0.6:
            candidates.append((mid, count, fb["not_relevant"], fb["relevant"], not_rel_ratio))

    if candidates:
        print(f"{'ID':<38} {'Inj':>3} {'NR':>3} {'R':>3} {'NR%':>5}")
        print(f"{'-'*38} {'-'*3} {'-'*3} {'-'*3} {'-'*5}")
        for mid, inj, nr, rel, ratio in sorted(candidates, key=lambda x: -x[4]):
            print(f"{mid:<38} {inj:>3} {nr:>3} {rel:>3} {ratio*100:>4.0f}%")
    else:
        print("  None found (insufficient data or no problematic memories yet)")

    # --- Never-injected memory types ---
    section("Never-Injected Memory Profile")
    never_injected_ids = set()
    all_active = conn.execute(
        "SELECT id, type FROM memory_objects WHERE lifecycle = 'active'"
    ).fetchall()
    type_counts: dict[str, dict[str, int]] = {}
    for row in all_active:
        mtype = row["type"]
        if mtype not in type_counts:
            type_counts[mtype] = {"injected": 0, "never": 0}
        if row["id"] in injection_counts:
            type_counts[mtype]["injected"] += 1
        else:
            type_counts[mtype]["never"] += 1

    print(f"{'Type':<24} {'Injected':>8} {'Never':>8} {'Never%':>7}")
    print(f"{'-'*24} {'-'*8} {'-'*8} {'-'*7}")
    for mtype in sorted(type_counts.keys(), key=lambda t: -type_counts[t]["never"]):
        d = type_counts[mtype]
        total = d["injected"] + d["never"]
        pct = d["never"] * 100 // max(total, 1)
        print(f"{mtype:<24} {d['injected']:>8} {d['never']:>8} {pct:>6}%")

    # --- Conclusion ---
    section("Assessment")
    if total_queries < 200:
        print(f"[!] Data is sparse ({total_queries} queries). Results are indicative, not conclusive.")
        print(f"   Recommend re-running after 2-4 weeks of accumulation (target: 500+ queries).")
    else:
        print(f"[ok] Sufficient data ({total_queries} queries) for initial assessment.")

    if all_injected_ratios and all_zero_ratios:
        diff = avg_inj - avg_zero
        if abs(diff) < 0.1:
            print(f"   Injection frequency does NOT correlate with feedback quality (diff: {diff:+.1%})")
            print(f"   -> Access count is unlikely to be a useful scoring signal.")
        elif diff > 0.1:
            print(f"   Higher injection frequency correlates with BETTER feedback ({diff:+.1%})")
            print(f"   -> Access count may be worth materializing as a quality signal.")
        else:
            print(f"   Higher injection frequency correlates with WORSE feedback ({diff:+.1%})")
            print(f"   -> Frequently-injected memories are problematic - auto-suppression signal.")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze injection frequency from Pallium audit log")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to pallium.db")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Database not found: {args.db}")
        raise SystemExit(1)

    analyze(args.db)
