"""Trace regressions through the rebuilt DB to find where gold answers were lost.

For each regressed question (correct in baseline, wrong after prompt change):
1. Check if the gold answer text exists in any active memory object in the rebuilt DB
2. If yes, check if it was retrieved (in query results)
3. If retrieved, check if it was injected (in the context the LLM saw)

This tells us the loss point: compression, retrieval, or injection.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


REGRESSIONS = [
    {"question": "How did John describe the team bond?", "gold": "Awesome", "category": "open_domain"},
    {"question": "How did John feel after being able to jog without pain?", "gold": "It was a huge success", "category": "open_domain"},
    {"question": "In which area has John's team seen the most growth during training?", "gold": "Communication and bonding", "category": "open_domain"},
    {"question": "What book recommendation did Tim give to John for the trip?", "gold": "Patrick Rothfuss", "category": "open_domain"},
    {"question": "What does John find rewarding about mentoring the younger players?", "gold": "growth, improvement, and confidence", "category": "open_domain"},
    {"question": "What is John's position on the team he signed with?", "gold": "shooting guard", "category": "open_domain"},
    {"question": "What kind of deals did John sign with Nike and Gatorade?", "gold": "Nike", "category": "open_domain"},
    {"question": "What kind of picture did Tim share as part of their Harry Potter book collection?", "gold": "MinaLima", "category": "open_domain"},
    {"question": "What map does Tim show to his friend John?", "gold": "Middle-earth", "category": "open_domain"},
    {"question": "What was the highest number of points John scored in a game recently?", "gold": "40 points", "category": "open_domain"},
    {"question": "Which basketball team does Tim support?", "gold": "Wolves", "category": "open_domain"},
    {"question": "Which two fantasy novels does Tim particularly enjoy writing about?", "gold": "Harry Potter", "category": "open_domain"},
    {"question": "Who is one of Tim's sources of inspiration for writing?", "gold": "J.K. Rowling", "category": "open_domain"},
    {"question": "What day did Tim get into his study abroad program?", "gold": "January 5", "category": "single_hop"},
    {"question": "When did John take a trip to the Rocky Mountains?", "gold": "2022", "category": "single_hop"},
    # Skipping the rate-limiter timeout one — not a real regression
]


def trace_regressions(db_path: str, results_jsonl: str):
    conn = sqlite3.connect(db_path)

    # Load all active memory objects
    rows = conn.execute("""
        SELECT id, type, payload_json, lifecycle
        FROM memory_objects
        WHERE lifecycle = 'active'
    """).fetchall()

    active_objects = []
    for row in rows:
        obj = {
            "id": row[0],
            "type": row[1],
            "payload": json.loads(row[2]),
            "lifecycle": row[3],
        }
        active_objects.append(obj)

    # Also load superseded objects to check if detail was lost at supersession
    superseded_rows = conn.execute("""
        SELECT id, type, payload_json, lifecycle
        FROM memory_objects
        WHERE lifecycle = 'superseded'
    """).fetchall()

    superseded_objects = []
    for row in superseded_rows:
        obj = {
            "id": row[0],
            "type": row[1],
            "payload": json.loads(row[2]),
            "lifecycle": row[3],
        }
        superseded_objects.append(obj)

    # Load benchmark results for retrieval context
    results_by_question = {}
    if Path(results_jsonl).exists():
        with open(results_jsonl) as f:
            for line in f:
                r = json.loads(line)
                results_by_question[r["question"]] = r

    conn.close()

    print(f"Active objects: {len(active_objects)} ({sum(1 for o in active_objects if o['type'] == 'fact_summary')} fact_summaries, "
          f"{sum(1 for o in active_objects if o['type'] == 'atomic_fact')} atomic_facts)")
    print(f"Superseded objects: {len(superseded_objects)}")
    print()

    summary_stats = {"compression_loss": 0, "supersession_loss": 0, "retrieval_miss": 0, "injection_miss": 0, "other": 0}

    for reg in REGRESSIONS:
        q = reg["question"]
        gold_keyword = reg["gold"].lower()
        print(f"Q: {q}")
        print(f"  Gold keyword: '{reg['gold']}'")

        # Step 1: Is the gold keyword in any ACTIVE memory object?
        active_matches = []
        for obj in active_objects:
            text = json.dumps(obj["payload"]).lower()
            if gold_keyword.lower() in text:
                active_matches.append(obj)

        # Step 2: Is the gold keyword in any SUPERSEDED memory object?
        superseded_matches = []
        for obj in superseded_objects:
            text = json.dumps(obj["payload"]).lower()
            if gold_keyword.lower() in text:
                superseded_matches.append(obj)

        if active_matches:
            types = [f"{o['type']}({o['id'][:8]})" for o in active_matches[:5]]
            print(f"  DB (active): FOUND in {len(active_matches)} objects: {', '.join(types)}")

            # Step 3: Was it in the benchmark retrieval results?
            bench = results_by_question.get(q)
            if bench:
                retrieval_summary = bench.get("retrieval_summary", "")
                gold_in_context = bench.get("gold_in_context", False)
                predicted = bench.get("predicted_answer", "")[:100]
                print(f"  Retrieval: gold_in_context={gold_in_context}")
                print(f"  Predicted: {predicted}")
                if gold_in_context:
                    print(f"  LOSS POINT: INJECTION/ANSWERING — detail in context but LLM missed it")
                    summary_stats["injection_miss"] += 1
                else:
                    print(f"  LOSS POINT: RETRIEVAL — detail in DB but not in top results")
                    summary_stats["retrieval_miss"] += 1
            else:
                print(f"  No benchmark result found")
                summary_stats["other"] += 1
        elif superseded_matches:
            types = [f"{o['type']}({o['id'][:8]})" for o in superseded_matches[:5]]
            print(f"  DB (active): NOT FOUND")
            print(f"  DB (superseded): FOUND in {len(superseded_matches)} objects: {', '.join(types)}")
            print(f"  LOSS POINT: SUPERSESSION — detail existed but was superseded, not in any active object")
            summary_stats["supersession_loss"] += 1
        else:
            print(f"  DB (active): NOT FOUND")
            print(f"  DB (superseded): NOT FOUND")
            print(f"  LOSS POINT: COMPRESSION — detail not in any memory object (dropped by LLM consolidation)")
            summary_stats["compression_loss"] += 1

        print()

    print("=" * 60)
    print("SUMMARY OF LOSS POINTS:")
    print(f"  Compression loss (detail not in DB at all): {summary_stats['compression_loss']}")
    print(f"  Supersession loss (in superseded but not active): {summary_stats['supersession_loss']}")
    print(f"  Retrieval miss (in active DB but not retrieved): {summary_stats['retrieval_miss']}")
    print(f"  Injection/answering miss (retrieved but LLM missed): {summary_stats['injection_miss']}")
    print(f"  Other: {summary_stats['other']}")


if __name__ == "__main__":
    db_path = "evals/locomo/db_cache/conv-43.db"
    results_dir = "evals/locomo/output/locomo-benchmark__anthropic-claude__anthropic--claude-sonnet-latest__20260420T093822Z"
    results_jsonl = f"{results_dir}/results.jsonl"
    trace_regressions(db_path, results_jsonl)
