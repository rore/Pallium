"""Retrieval ablation eval — measures whether routing justifies itself over naive top-K.

Replays different candidate selection strategies on historical audit log data
and scores them against actual user feedback ratings.

Variants:
- full (routing): What the routing pipeline actually injected (~2 per query)
- routing_uncapped: Top-K by routing-adjusted score (tests whether injection cap is too aggressive)
- topk_vector: Top-K by raw vector similarity (true ablation: raw retrieval vs routing)
- topk_lexical: Top-K by raw BM25 score (true ablation: raw retrieval vs routing)

Note: The raw RRF fusion score is not stored in candidate_scores_json, so we cannot
test "raw RRF top-K" directly. The routing_score has already been adjusted by routing
stages (layer weights, freshness, suppression, etc.).

Usage:
    python -m evals.retrieval_ablation.runner [--db PATH] [--top-k N]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from evals.retrieval_ablation.evaluate import (
    QueryVariantResult,
    VariantMetrics,
    build_feedback_index,
    evaluate_variant,
)
from evals.retrieval_ablation.report import (
    print_routing_analysis,
    print_summary_table,
    print_type_breakdown,
)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_injection_queries(db_path: str) -> list[dict[str, Any]]:
    """Load all queries that resulted in injection from query_audit_log."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("""
        SELECT id, query_text, candidate_scores_json, injected_blocks_json
        FROM query_audit_log
        WHERE decision_reason = 'carry_forward_available'
          AND candidate_scores_json IS NOT NULL
          AND injected_blocks_json IS NOT NULL
    """)
    rows = []
    for row in cur.fetchall():
        rows.append({
            "id": row["id"],
            "query_text": row["query_text"],
            "candidates": json.loads(row["candidate_scores_json"]),
            "injected_blocks": json.loads(row["injected_blocks_json"]),
        })
    conn.close()
    return rows


def load_feedback(db_path: str) -> list[dict[str, Any]]:
    """Load all memory feedback entries."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("""
        SELECT memory_object_id, rating, query_context, memory_type
        FROM memory_feedback
    """)
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Variant strategies
# ---------------------------------------------------------------------------


def variant_full(query: dict[str, Any]) -> set[str]:
    """What routing actually injected (baseline)."""
    ids: set[str] = set()
    for block in query["injected_blocks"]:
        mem_id = block.get("memory_object_id")
        if mem_id:
            ids.add(mem_id)
    return ids


def variant_topk_routing_uncapped(query: dict[str, Any], k: int = 5) -> set[str]:
    """Top-K candidates by routing_score (post-routing adjusted score), without injection cap.

    NOTE: routing_score is NOT the raw RRF fusion score. It has been modified by
    multiple routing stages (layer weights, freshness, suppression, etc.). This variant
    tests whether the injection cap (typically ~2 per query) is too aggressive — not
    whether routing scoring itself adds value. For raw retrieval comparison, use
    variant_topk_vector or variant_topk_lexical.
    """
    candidates = query["candidates"]
    sorted_c = sorted(candidates, key=lambda c: c.get("routing_score", 0), reverse=True)
    return {c["memory_object_id"] for c in sorted_c[:k]}


def variant_topk_vector(query: dict[str, Any], k: int = 5) -> set[str]:
    """Top-K candidates by vector_score only."""
    candidates = query["candidates"]
    # Filter to those with vector scores, sort descending
    with_vector = [c for c in candidates if c.get("vector_score") is not None]
    sorted_c = sorted(with_vector, key=lambda c: c.get("vector_score", 0), reverse=True)
    return {c["memory_object_id"] for c in sorted_c[:k]}


def variant_topk_lexical(query: dict[str, Any], k: int = 5) -> set[str]:
    """Top-K candidates by lexical_score only."""
    candidates = query["candidates"]
    # Filter to those with lexical scores, sort descending
    with_lexical = [c for c in candidates if c.get("lexical_score") is not None]
    sorted_c = sorted(with_lexical, key=lambda c: c.get("lexical_score", 0), reverse=True)
    return {c["memory_object_id"] for c in sorted_c[:k]}


# ---------------------------------------------------------------------------
# Routing exclusion analysis
# ---------------------------------------------------------------------------


def find_excluded_high_score(queries: list[dict[str, Any]], threshold: int = 450) -> list[dict[str, Any]]:
    """Find candidates that routing excluded despite having high routing scores.

    These are candidates with routing_score >= threshold but injected=False.
    """
    excluded: list[dict[str, Any]] = []
    for query in queries:
        for c in query["candidates"]:
            if not c.get("injected", False) and c.get("routing_score", 0) >= threshold:
                excluded.append({
                    "query_id": query["id"],
                    "query_text": query["query_text"],
                    "memory_object_id": c["memory_object_id"],
                    "memory_type": c.get("memory_type", "unknown"),
                    "routing_score": c.get("routing_score", 0),
                    "vector_score": c.get("vector_score"),
                    "lexical_score": c.get("lexical_score"),
                    "suppression_reason_code": c.get("suppression_reason_code"),
                })
    return excluded


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Retrieval ablation eval")
    parser.add_argument("--db", default=None, help="SQLite DB path (auto-detects ~/.pallium/data/pallium.db)")
    parser.add_argument("--top-k", type=int, default=5, help="K for top-K variants (default: 5)")
    args = parser.parse_args()

    if args.db:
        db_path = args.db
    else:
        default_path = os.path.expanduser("~/.pallium/data/pallium.db")
        if not Path(default_path).exists():
            print(f"DB not found at {default_path}, pass --db", file=sys.stderr)
            return 1
        db_path = default_path

    print(f"Loading data from: {db_path}")
    queries = load_injection_queries(db_path)
    feedback_rows = load_feedback(db_path)

    if not queries:
        print("No injection queries found in query_audit_log.", file=sys.stderr)
        return 1

    print(f"Loaded {len(queries)} injection queries")
    print(f"Loaded {len(feedback_rows)} feedback entries")

    # Build feedback index
    feedback_index = build_feedback_index(feedback_rows)
    print(f"Unique memories with feedback: {len(feedback_index)}")

    # Count relevant vs not_relevant
    from evals.retrieval_ablation.evaluate import majority_rating
    relevant_count = sum(
        1 for entries in feedback_index.values()
        if majority_rating(entries) == "relevant"
    )
    not_relevant_count = sum(
        1 for entries in feedback_index.values()
        if majority_rating(entries) == "not_relevant"
    )
    print(f"Majority-rated relevant: {relevant_count}, not_relevant: {not_relevant_count}")

    k = args.top_k

    # Apply each variant strategy
    variant_strategies = {
        "full (routing)": variant_full,
        f"routing_uncapped (top-{k})": lambda q: variant_topk_routing_uncapped(q, k),
        f"topk_vector (top-{k})": lambda q: variant_topk_vector(q, k),
        f"topk_lexical (top-{k})": lambda q: variant_topk_lexical(q, k),
    }

    # Build candidates index per query for type lookups
    all_candidates_by_query: dict[int, list[dict[str, Any]]] = {}
    for query in queries:
        all_candidates_by_query[query["id"]] = query["candidates"]

    all_metrics: list[VariantMetrics] = []

    for variant_name, strategy_fn in variant_strategies.items():
        results: list[QueryVariantResult] = []
        for query in queries:
            injected_ids = strategy_fn(query)
            results.append(QueryVariantResult(
                query_id=query["id"],
                query_text=query["query_text"],
                injected_ids=injected_ids,
            ))

        metrics = evaluate_variant(
            variant_name, results, feedback_index, all_candidates_by_query
        )
        all_metrics.append(metrics)

    # Print results
    print_summary_table(all_metrics)
    print_type_breakdown(all_metrics)

    # Routing exclusion analysis
    excluded = find_excluded_high_score(queries, threshold=450)
    print_routing_analysis(excluded, feedback_index)

    # Final verdict
    print("\n" + "=" * 85)
    print("VERDICT")
    print("=" * 85)
    routing_metrics = all_metrics[0]
    best_naive = max(all_metrics[1:], key=lambda m: m.precision)
    if routing_metrics.precision > best_naive.precision:
        delta = routing_metrics.precision - best_naive.precision
        print(f"Routing IMPROVES precision by {delta:.1%} over best naive ({best_naive.name})")
        print(f"  Routing: {routing_metrics.precision:.1%} precision, "
              f"{routing_metrics.coverage:.1%} coverage")
        print(f"  Best naive: {best_naive.precision:.1%} precision, "
              f"{best_naive.coverage:.1%} coverage")
    elif routing_metrics.precision == best_naive.precision:
        print(f"Routing MATCHES best naive precision ({best_naive.name})")
        print(f"  Both: {routing_metrics.precision:.1%} precision")
        print(f"  Routing coverage: {routing_metrics.coverage:.1%} vs "
              f"naive: {best_naive.coverage:.1%}")
    else:
        delta = best_naive.precision - routing_metrics.precision
        print(f"Routing UNDERPERFORMS best naive ({best_naive.name}) by {delta:.1%}")
        print(f"  Routing: {routing_metrics.precision:.1%} precision, "
              f"{routing_metrics.coverage:.1%} coverage")
        print(f"  Best naive: {best_naive.precision:.1%} precision, "
              f"{best_naive.coverage:.1%} coverage")
        # But check if routing wins on coverage
        if routing_metrics.coverage > best_naive.coverage:
            print(f"  However, routing has BETTER coverage "
                  f"({routing_metrics.coverage:.1%} vs {best_naive.coverage:.1%})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
