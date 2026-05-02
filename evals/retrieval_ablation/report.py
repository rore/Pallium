"""Report generation for retrieval ablation eval."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from evals.retrieval_ablation.evaluate import VariantMetrics


def print_summary_table(all_metrics: list[VariantMetrics]) -> None:
    """Print the main comparison table."""
    print("\n" + "=" * 85)
    print("RETRIEVAL ABLATION EVAL — VARIANT COMPARISON")
    print("=" * 85)
    header = (
        f"{'Variant':<20} | {'Precision':>9} | {'Coverage':>8} | "
        f"{'Avg inj':>7} | {'Rated':>12} | {'Unknown':>7}"
    )
    print(header)
    print("-" * 85)
    for m in all_metrics:
        row = (
            f"{m.name:<20} | {m.precision:>8.1%} | {m.coverage:>7.1%} | "
            f"{m.avg_injected:>7.1f} | "
            f"{m.rated_relevant}r/{m.rated_not_relevant}nr | "
            f"{m.rated_unknown:>7}"
        )
        print(row)
    print("-" * 85)
    print(f"Total queries: {all_metrics[0].total_queries if all_metrics else 0}")
    print(f"Total relevant-rated memories in corpus: "
          f"{all_metrics[0].total_relevant_memories if all_metrics else 0}")


def print_type_breakdown(all_metrics: list[VariantMetrics]) -> None:
    """Print per memory_type precision for each variant."""
    # Collect all types seen
    all_types: set[str] = set()
    for m in all_metrics:
        all_types.update(m.type_relevant.keys())
        all_types.update(m.type_not_relevant.keys())

    if not all_types:
        return

    print("\n" + "=" * 85)
    print("PER MEMORY_TYPE BREAKDOWN")
    print("=" * 85)

    sorted_types = sorted(all_types)
    header = f"{'Type':<25} | " + " | ".join(f"{m.name:>12}" for m in all_metrics)
    print(header)
    print("-" * (28 + 15 * len(all_metrics)))

    for mem_type in sorted_types:
        parts = []
        for m in all_metrics:
            r = m.type_relevant.get(mem_type, 0)
            nr = m.type_not_relevant.get(mem_type, 0)
            total = r + nr
            if total > 0:
                prec = r / total
                parts.append(f"{prec:>5.0%} ({r}/{total})")
            else:
                parts.append(f"{'--':>12}")
        row = f"{mem_type:<25} | " + " | ".join(parts)
        print(row)


def print_routing_analysis(
    excluded_high_score: list[dict[str, Any]],
    feedback_index: dict[str, list[Any]],
) -> None:
    """Analyze memories that routing excluded despite high retrieval scores."""
    from evals.retrieval_ablation.evaluate import majority_rating

    print("\n" + "=" * 85)
    print("ROUTING EXCLUSION ANALYSIS")
    print("(Memories excluded by routing but with high retrieval scores)")
    print("=" * 85)

    if not excluded_high_score:
        print("No high-score exclusions found.")
        return

    # Group by whether they have feedback and what it says
    has_relevant = []
    has_not_relevant = []
    no_feedback = []

    for entry in excluded_high_score:
        mem_id = entry["memory_object_id"]
        entries = feedback_index.get(mem_id, [])
        rating = majority_rating(entries)
        if rating == "relevant":
            has_relevant.append(entry)
        elif rating == "not_relevant":
            has_not_relevant.append(entry)
        else:
            no_feedback.append(entry)

    print(f"\nTotal high-score exclusions: {len(excluded_high_score)}")
    print(f"  - Have 'relevant' feedback elsewhere: {len(has_relevant)}")
    print(f"  - Have 'not_relevant' feedback elsewhere: {len(has_not_relevant)}")
    print(f"  - No feedback available: {len(no_feedback)}")

    if has_relevant:
        print(f"\n  Relevant exclusions (routing filtered a memory the user liked):")
        for entry in has_relevant[:10]:
            vs = entry.get('vector_score')
            ls = entry.get('lexical_score')
            print(f"    {entry['memory_type']:<25} "
                  f"routing={entry['routing_score']:>4} "
                  f"vector={vs if vs is not None else '--':>4} "
                  f"lexical={ls if ls is not None else '--'}")

    if has_not_relevant:
        print(f"\n  Not-relevant exclusions (routing correctly filtered):")
        for entry in has_not_relevant[:10]:
            vs = entry.get('vector_score')
            ls = entry.get('lexical_score')
            print(f"    {entry['memory_type']:<25} "
                  f"routing={entry['routing_score']:>4} "
                  f"vector={vs if vs is not None else '--':>4} "
                  f"lexical={ls if ls is not None else '--'}")

    # Summary: what fraction of high-score exclusions were correct?
    total_rated = len(has_relevant) + len(has_not_relevant)
    if total_rated > 0:
        correct_exclusions = len(has_not_relevant) / total_rated
        print(f"\n  Routing exclusion accuracy (among rated): {correct_exclusions:.0%}")
        print(f"  ({len(has_not_relevant)}/{total_rated} exclusions were correctly filtered)")
