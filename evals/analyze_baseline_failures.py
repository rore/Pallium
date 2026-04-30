"""Analyze baseline retrieval failures for conv-43.

For each failed question where gold is NOT in context:
1. Does the gold keyword exist in any active memory object?
2. If yes, what type? (fact_summary, atomic_fact, turn_summary, etc.)
3. What types DID get retrieved instead?
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path


def analyze_baseline_failures():
    db_path = "evals/locomo/db_cache/conv-43.db"
    # Use the ORIGINAL baseline DB — we need to rebuild it without the prompt change
    # Actually the current DB has the word-limit prompt. Let me check.
    # For now, analyze the baseline results which ran against the original DB.

    baseline_results = "evals/locomo/output/locomo-benchmark__anthropic-claude__anthropic--claude-sonnet-latest__20260417T174555Z/results.jsonl"

    # Load baseline failures for conv-43
    failures = []
    with open(baseline_results) as f:
        for line in f:
            r = json.loads(line)
            if r["sample_id"] != "conv-43":
                continue
            if r["correct"]:
                continue
            if r.get("gold_in_context"):
                continue  # readability issue, not retrieval
            failures.append(r)

    print(f"Conv-43 baseline failures with gold NOT in context: {len(failures)}")
    print()

    # For each failure, check what was retrieved
    retrieval_type_counts = Counter()
    has_fact_summary = 0
    no_fact_summary = 0

    for f in failures:
        rs = f.get("retrieval_summary", "")
        if "fact_summary" in rs:
            has_fact_summary += 1
        else:
            no_fact_summary += 1

    print(f"Of {len(failures)} retrieval failures:")
    print(f"  Had a fact_summary in retrieval: {has_fact_summary}")
    print(f"  No fact_summary in retrieval: {no_fact_summary}")
    print()

    # Group by category
    by_cat = {}
    for f in failures:
        cat = f.get("category_name", "unknown")
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(f)

    for cat in sorted(by_cat):
        items = by_cat[cat]
        print(f"\n{'='*60}")
        print(f"Category: {cat} ({len(items)} failures)")
        print(f"{'='*60}")
        for item in items[:5]:  # Show first 5 per category
            q = item["question"]
            gold = item["gold_answer"]
            pred = str(item.get("predicted_answer", ""))[:80]
            result_count = item.get("result_count", "?")
            blocks = item.get("injectable_block_count", "?")
            should_inject = item.get("should_inject", "?")
            judge = str(item.get("judge_reasoning", ""))[:120]
            print(f"\n  Q: {q}")
            print(f"  Gold: {gold}")
            print(f"  Pred: {pred}")
            print(f"  Results: {result_count}, Blocks injected: {blocks}, Should inject: {should_inject}")
            if judge:
                print(f"  Judge: {judge}")
        if len(items) > 5:
            print(f"\n  ... and {len(items) - 5} more")


if __name__ == "__main__":
    analyze_baseline_failures()
