"""Phase 1: Fact pipeline value analysis — redundancy, viability, qualitative sample.

No LLM calls. Runs against the production DB to answer:
1. Are atomic_facts redundant with decisions/investigations?
2. Is consolidation structurally viable given subject distribution?
3. Qualitative: what do random facts look like?

Usage:
    python -m evals.fact_retrieval_value.fact_value_analysis
    python -m evals.fact_retrieval_value.fact_value_analysis --sample-size 100
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import AppConfig
from app.main import create_app
from evals.eval_common import copy_vector_index
from fastapi.testclient import TestClient

DB_PATH = Path(os.environ.get("PALLIUM_DB", r"C:\Users\I347041\.pallium\data\pallium.db"))
VECTOR_PATH = Path(os.environ.get("PALLIUM_VECTOR", r"C:\Users\I347041\.pallium\data\vector.index"))


def _token_overlap(text_a: str, text_b: str) -> float:
    """Simple token overlap ratio between two texts."""
    tokens_a = {t.lower() for t in text_a.split() if len(t) >= 3}
    tokens_b = {t.lower() for t in text_b.split() if len(t) >= 3}
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    smaller = min(len(tokens_a), len(tokens_b))
    return len(intersection) / smaller if smaller else 0.0


def _fact_covered_by_result(fact_statement: str, result: dict) -> bool:
    """Check if a retrieval result covers the same knowledge as a fact."""
    result_kind = result.get("result_kind", "")
    if result_kind == "memory_hit":
        result_type = result.get("type", "")
        if result_type not in {"decision", "investigation_outcome", "constraint_memory", "pattern_memory"}:
            return False
        payload = result.get("payload") or {}
        result_text = (
            payload.get("decision")
            or payload.get("investigation_outcome")
            or payload.get("summary")
            or payload.get("description")
            or payload.get("carry_forward_answer")
            or ""
        )
        return _token_overlap(fact_statement, result_text) > 0.45
    return False


def run_redundancy_check(
    db: sqlite3.Connection,
    sample_size: int = 50,
) -> dict:
    """Check how many facts are redundant with existing structured memories."""
    facts = db.execute("""
        SELECT id, payload_json FROM memory_objects
        WHERE type = 'atomic_fact' AND lifecycle = 'active'
        ORDER BY RANDOM() LIMIT ?
    """, (sample_size,)).fetchall()

    config = AppConfig.from_env()

    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "eval.db"
        vector_path = Path(temp_dir) / "vector.index"
        shutil.copy2(DB_PATH, db_path)
        copy_vector_index(VECTOR_PATH, vector_path)

        database_url = f"sqlite:///{db_path}"
        vector_index_config = replace(
            config.vector_index,
            index_path=str(vector_path),
        )
        scenario_config = replace(
            config,
            sqlite_url=database_url,
            default_use_case="agent_conversation_memory",
            vector_index=vector_index_config,
        )

        results = []
        with TestClient(create_app(scenario_config)) as client:
            while client.app.state.pallium_service.reconcile_vector_index() > 0:
                pass

            for fact_row in facts:
                payload = json.loads(fact_row["payload_json"])
                subject = payload.get("subject", "")
                statement = payload.get("statement", "")
                category = payload.get("category", "")
                thread_ref = payload.get("thread_ref")

                query_text = f"{subject}: {statement}" if subject else statement
                query_payload = {
                    "text": query_text[:300],
                    "limit": 10,
                    "container_ref": "git:github.com/rore/pallium",
                    "visibility": "private",
                    "runtime_context": {
                        "turn_kind": "new_session",
                        "session_has_sufficient_local_context": False,
                    },
                }
                resp = client.post("/query/debug", json=query_payload)
                resp.raise_for_status()
                mem_payload = resp.json()

                retrieval_results = mem_payload.get("results", [])
                covered_by = None
                for r in retrieval_results:
                    if r.get("memory_object_id") == fact_row["id"]:
                        continue
                    if _fact_covered_by_result(statement, r):
                        covered_by = r.get("type", "unknown")
                        break

                results.append({
                    "fact_id": fact_row["id"],
                    "subject": subject,
                    "statement": statement[:150],
                    "category": category,
                    "thread_ref": thread_ref,
                    "redundant": covered_by is not None,
                    "covered_by_type": covered_by,
                })

    return {
        "sample_size": len(results),
        "redundant_count": sum(1 for r in results if r["redundant"]),
        "redundancy_rate": sum(1 for r in results if r["redundant"]) / len(results) if results else 0,
        "covered_by_breakdown": Counter(r["covered_by_type"] for r in results if r["redundant"]),
        "details": results,
    }


def run_viability_analysis(db: sqlite3.Connection) -> dict:
    """Analyze structural viability of the consolidation pipeline."""
    total_facts = db.execute(
        "SELECT COUNT(*) FROM memory_objects WHERE type='atomic_fact' AND lifecycle='active'"
    ).fetchone()[0]

    total_subjects = db.execute("""
        SELECT COUNT(DISTINCT json_extract(payload_json, '$.subject'))
        FROM memory_objects WHERE type='atomic_fact' AND lifecycle='active'
    """).fetchone()[0]

    subjects_with_3plus = db.execute("""
        SELECT json_extract(payload_json, '$.subject') as subj, COUNT(*) as cnt
        FROM memory_objects WHERE type='atomic_fact' AND lifecycle='active'
        GROUP BY subj HAVING cnt >= 3
    """).fetchall()

    subjects_multi_thread = db.execute("""
        SELECT json_extract(payload_json, '$.subject') as subj,
               COUNT(DISTINCT json_extract(payload_json, '$.thread_ref')) as thread_cnt,
               COUNT(*) as fact_cnt
        FROM memory_objects WHERE type='atomic_fact' AND lifecycle='active'
        GROUP BY subj
        HAVING thread_cnt >= 2 AND fact_cnt >= 3
    """).fetchall()

    thread_distribution = db.execute("""
        SELECT json_extract(payload_json, '$.thread_ref') as thr, COUNT(*) as cnt
        FROM memory_objects WHERE type='atomic_fact' AND lifecycle='active'
        GROUP BY thr ORDER BY cnt DESC
    """).fetchall()

    fact_count_distribution = db.execute("""
        SELECT cnt, COUNT(*) as subjects
        FROM (
            SELECT json_extract(payload_json, '$.subject') as subj, COUNT(*) as cnt
            FROM memory_objects WHERE type='atomic_fact' AND lifecycle='active'
            GROUP BY subj
        )
        GROUP BY cnt ORDER BY cnt
    """).fetchall()

    return {
        "total_facts": total_facts,
        "total_subjects": total_subjects,
        "facts_per_subject_avg": round(total_facts / total_subjects, 2) if total_subjects else 0,
        "subjects_with_3plus_facts": len(subjects_with_3plus),
        "subjects_meeting_consolidation_criteria": len(subjects_multi_thread),
        "consolidation_eligible_subjects": [
            {"subject": row[0][:60], "threads": row[1], "facts": row[2]}
            for row in subjects_multi_thread
        ],
        "thread_distribution": [
            {"thread": (row[0] or "null")[:40], "facts": row[1]}
            for row in thread_distribution[:10]
        ],
        "fact_count_distribution": [
            {"facts_per_subject": row[0], "num_subjects": row[1]}
            for row in fact_count_distribution
        ],
        "existing_decisions": db.execute(
            "SELECT COUNT(*) FROM memory_objects WHERE type='decision' AND lifecycle='active'"
        ).fetchone()[0],
        "existing_investigations": db.execute(
            "SELECT COUNT(*) FROM memory_objects WHERE type='investigation_outcome' AND lifecycle='active'"
        ).fetchone()[0],
        "existing_fact_summaries": db.execute(
            "SELECT COUNT(*) FROM memory_objects WHERE type='fact_summary' AND lifecycle='active'"
        ).fetchone()[0],
    }


def run_qualitative_sample(db: sqlite3.Connection, count: int = 20) -> list[dict]:
    """Print a qualitative sample of random facts for human review."""
    facts = db.execute("""
        SELECT payload_json FROM memory_objects
        WHERE type = 'atomic_fact' AND lifecycle = 'active'
        ORDER BY RANDOM() LIMIT ?
    """, (count,)).fetchall()

    sample = []
    for f in facts:
        p = json.loads(f["payload_json"])
        sample.append({
            "subject": p.get("subject", ""),
            "statement": p.get("statement", ""),
            "category": p.get("category", ""),
            "thread_ref": (p.get("thread_ref") or "")[:30],
        })
    return sample


def print_report(redundancy: dict, viability: dict, qualitative: list[dict]) -> None:
    """Print the full analysis report."""
    print("=" * 70)
    print("FACT PIPELINE VALUE ANALYSIS — Phase 1")
    print("=" * 70)

    # Viability
    print("\n## Structural Viability")
    print(f"  Total atomic_facts:       {viability['total_facts']}")
    print(f"  Distinct subjects:        {viability['total_subjects']}")
    print(f"  Avg facts/subject:        {viability['facts_per_subject_avg']}")
    print(f"  Subjects with 3+ facts:   {viability['subjects_with_3plus_facts']}")
    print(f"  Consolidation-eligible:   {viability['subjects_meeting_consolidation_criteria']}")
    print(f"  Existing fact_summaries:  {viability['existing_fact_summaries']}")
    print(f"  Existing decisions:       {viability['existing_decisions']}")
    print(f"  Existing investigations:  {viability['existing_investigations']}")

    print("\n  Fact count distribution (facts per subject -> # subjects):")
    for entry in viability["fact_count_distribution"]:
        bar = "#" * min(entry["num_subjects"], 50)
        print(f"    {entry['facts_per_subject']:2d} fact(s): {entry['num_subjects']:4d} subjects  {bar}")

    if viability["consolidation_eligible_subjects"]:
        print(f"\n  Consolidation-eligible subjects (3+ facts, 2+ threads):")
        for s in viability["consolidation_eligible_subjects"]:
            print(f"    {s['subject']:50s} ({s['facts']} facts, {s['threads']} threads)")

    print(f"\n  Thread distribution (top 10):")
    for t in viability["thread_distribution"]:
        print(f"    {t['thread']:40s} {t['facts']:4d} facts")

    # Redundancy
    print(f"\n## Redundancy Check (sample={redundancy['sample_size']})")
    rate_pct = redundancy["redundancy_rate"] * 100
    print(f"  Redundant:     {redundancy['redundant_count']}/{redundancy['sample_size']} ({rate_pct:.1f}%)")
    print(f"  Unique:        {redundancy['sample_size'] - redundancy['redundant_count']}/{redundancy['sample_size']}")
    if redundancy["covered_by_breakdown"]:
        print(f"  Covered by:")
        for typ, cnt in redundancy["covered_by_breakdown"].most_common():
            print(f"    {typ}: {cnt}")

    # Qualitative
    print(f"\n## Qualitative Sample ({len(qualitative)} random facts)")
    for i, fact in enumerate(qualitative):
        print(f"\n  {i+1}. [{fact['category']}] {fact['subject'][:60]}")
        print(f"     {fact['statement'][:120]}")

    # Decision
    print("\n" + "=" * 70)
    print("## DECISION")
    if rate_pct > 70:
        print(f"  REDUNDANCY = {rate_pct:.0f}% (> 70%)")
        print("  -> Facts are largely overhead. Pipeline produces knowledge")
        print("    already captured by decisions/investigations.")
        print("  -> Consider: remove pipeline, or repurpose for non-injection use.")
    elif rate_pct < 40 and viability["subjects_meeting_consolidation_criteria"] >= 20:
        print(f"  REDUNDANCY = {rate_pct:.0f}% (< 40%), VIABLE SUBJECTS = {viability['subjects_meeting_consolidation_criteria']} (≥ 20)")
        print("  -> Facts contain unique value AND can consolidate.")
        print("  -> Proceed to Phase 2: retrieval eval with injection patching.")
    else:
        print(f"  REDUNDANCY = {rate_pct:.0f}%, VIABLE SUBJECTS = {viability['subjects_meeting_consolidation_criteria']}")
        print("  -> Middle ground. Facts have niche value but consolidation is sparse.")
        print("  -> Consider: lower consolidation threshold, or inject atomic_facts directly")
        print("    for high-value categories.")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Phase 1: Fact pipeline value analysis")
    parser.add_argument("--sample-size", type=int, default=50, help="Number of facts to sample for redundancy check")
    parser.add_argument("--qualitative-count", type=int, default=20, help="Number of facts for qualitative sample")
    parser.add_argument("--skip-redundancy", action="store_true", help="Skip redundancy check (fast viability only)")
    args = parser.parse_args()

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    print("Running viability analysis...")
    viability = run_viability_analysis(db)

    if args.skip_redundancy:
        redundancy = {"sample_size": 0, "redundant_count": 0, "redundancy_rate": 0, "covered_by_breakdown": Counter(), "details": []}
    else:
        print(f"Running redundancy check (sample={args.sample_size})...")
        redundancy = run_redundancy_check(db, sample_size=args.sample_size)

    print("Running qualitative sample...")
    qualitative = run_qualitative_sample(db, count=args.qualitative_count)

    db.close()

    print_report(redundancy, viability, qualitative)

    # Write machine-readable output
    output_dir = Path(__file__).parent
    output_path = output_dir / "analysis_results.json"
    output = {
        "viability": {k: v for k, v in viability.items()},
        "redundancy": {
            "sample_size": redundancy["sample_size"],
            "redundant_count": redundancy["redundant_count"],
            "redundancy_rate": redundancy["redundancy_rate"],
            "covered_by_breakdown": dict(redundancy["covered_by_breakdown"]),
        },
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nResults written to: {output_path}")


if __name__ == "__main__":
    main()
