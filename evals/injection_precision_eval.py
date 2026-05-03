"""Injection gate precision eval — measures precision/recall tradeoff of tightening gates.

Replays stored audit data to simulate what would happen if per-candidate injection
gates were tighter. For each variant threshold, determines which currently-injected
candidates would be BLOCKED, and scores blocked candidates against feedback ground truth.

Simulates BOTH levels:
- Per-candidate gate: would this candidate pass `candidate_injection_eligible`?
- Set-level gate: would any candidate in the query still pass `should_allow_injection`?

Limitation: Cross-script bypass cannot be tested — candidate text is not stored
in the audit log snapshot. Add cross_script field to snapshot serialization to enable.

Usage:
    python -m evals.injection_precision_eval [--db PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals.retrieval_ablation.evaluate import (
    FeedbackEntry,
    build_feedback_index,
    majority_rating,
)
from semantic.agent_conversation_memory_routing_constants import normalize_lexical_score

# Memory types that get the "high_value" per-candidate gate path.
# Mirror of semantic/agent_conversation_memory_routing_injection.py
HIGH_VALUE_MEMORY_TYPES = frozenset({
    "decision", "investigation_outcome", "task_checkpoint",
    "continuity_memory", "pattern_memory", "interest",
})


# ---------------------------------------------------------------------------
# Gate variant definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateVariant:
    """A gate configuration to evaluate."""
    name: str
    high_value_vector_floor: int = 650
    candidate_vector_override: int = 800
    set_vector_high: int = 750
    lex_only: bool = False  # If True, only inject when lex > 0 (no vector override)


GATE_VARIANTS = [
    GateVariant(name="baseline (current)", high_value_vector_floor=650),
    GateVariant(name="vec_floor_900", high_value_vector_floor=900),
    GateVariant(name="vec_floor_915", high_value_vector_floor=915),
    GateVariant(name="vec_floor_925", high_value_vector_floor=925),
    GateVariant(name="vec_floor_930", high_value_vector_floor=930),
    GateVariant(name="vec_floor_935", high_value_vector_floor=935),
    GateVariant(name="vec_floor_940", high_value_vector_floor=940),
    GateVariant(name="lex_only (no vec override)", lex_only=True),
]


# ---------------------------------------------------------------------------
# Gate simulation
# ---------------------------------------------------------------------------


def _candidate_passes_gate(candidate: dict, variant: GateVariant) -> bool:
    """Simulate per-candidate injection eligibility under a gate variant.

    Models the logic in candidate_injection_eligible() from
    semantic/agent_conversation_memory_routing_injection.py.
    """
    raw_lex = candidate.get("lexical_score")
    raw_vec = candidate.get("vector_score")
    mem_type = candidate.get("memory_type", "unknown")

    if raw_lex is None and raw_vec is None:
        return False

    lex = normalize_lexical_score(raw_lex)
    vec = float(raw_vec) if raw_vec is not None else 0.0

    if variant.lex_only:
        return lex >= 0.01

    is_high_value = mem_type in HIGH_VALUE_MEMORY_TYPES

    if is_high_value:
        return lex >= 0.01 or vec >= variant.high_value_vector_floor
    else:
        # Source hits / other: higher bar
        return (
            lex >= 0.01
            or vec >= variant.candidate_vector_override
            or (raw_lex is None and vec >= variant.set_vector_high)
        )


def _set_gate_passes(candidates: list[dict], variant: GateVariant) -> bool:
    """Simulate set-level injection gate under a variant.

    Models should_allow_injection() logic. Checks whether any candidate would
    still pass set-level conditions with the new thresholds.
    """
    if not candidates:
        return False

    best_lex = 0.0
    best_vec = 0
    has_any_lex = False
    has_supported_hv = False

    for c in candidates:
        raw_lex = c.get("lexical_score")
        raw_vec = c.get("vector_score")
        vec = int(raw_vec or 0)
        if vec > best_vec:
            best_vec = vec
        if raw_lex is not None:
            has_any_lex = True
        # Exclude turn_summary from best_lexical — their BM25 overlap
        # with the query is circular (derived from query-adjacent content)
        if c.get("memory_type") != "turn_summary":
            lex = normalize_lexical_score(raw_lex)
            if lex > best_lex:
                best_lex = lex
        if (c.get("memory_type") in HIGH_VALUE_MEMORY_TYPES
                and c.get("support_grade") in ("supported", "strong")):
            has_supported_hv = True

    # cond1: strong lexical
    cond1 = best_lex >= 0.33
    # cond2: vector + any lexical
    cond2 = best_vec >= 750 and best_lex >= 0.01
    # cond3: very strong vector, no lexical available
    cond3 = best_vec >= 800 and not has_any_lex
    # cond4: supported high-value memory + lexical + vector floor
    cond4 = (has_supported_hv and best_lex >= 0.01
             and best_vec >= variant.high_value_vector_floor)

    if variant.lex_only:
        # In lex_only mode, set gate requires lexical signal
        return cond1 or (best_vec >= 750 and best_lex >= 0.01)

    return cond1 or cond2 or cond3 or cond4


def simulate_injection(
    query: dict, variant: GateVariant
) -> tuple[set[str], set[str]]:
    """Simulate gate on a query, return (would_inject, would_block).

    Returns:
        would_inject: memory_object_ids that pass both gates
        would_block: memory_object_ids that were originally injected but would be blocked
    """
    candidates = query["candidates"]
    originally_injected = {
        c["memory_object_id"] for c in candidates if c.get("injected")
    }

    # First: set-level gate
    if not _set_gate_passes(candidates, variant):
        # Entire query blocked at set level
        return set(), originally_injected

    # Per-candidate gate
    would_inject: set[str] = set()
    for c in candidates:
        if not c.get("injected"):
            continue
        if _candidate_passes_gate(c, variant):
            would_inject.add(c["memory_object_id"])

    would_block = originally_injected - would_inject
    return would_inject, would_block


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class GateMetrics:
    """Results of applying a gate variant across all queries."""
    name: str
    total_queries: int = 0
    total_injected_baseline: int = 0
    # Queries where set-level gate blocks everything
    set_gate_blocks: int = 0
    # Per-candidate results (among originally-injected, rated candidates)
    true_positives: int = 0       # rated relevant, still injected
    false_positives: int = 0      # rated not_relevant, still injected
    tp_lost: int = 0              # rated relevant, now blocked (recall loss)
    fp_eliminated: int = 0        # rated not_relevant, now blocked (precision gain)
    # Unrated
    unrated_kept: int = 0
    unrated_blocked: int = 0
    # Per memory_type breakdown
    blocked_by_type: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    kept_by_type: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def baseline_precision(self) -> float:
        """Precision of the original (baseline) injection among rated."""
        tp = self.true_positives + self.tp_lost
        fp = self.false_positives + self.fp_eliminated
        denom = tp + fp
        return tp / denom if denom else 0.0

    @property
    def variant_precision(self) -> float:
        """Precision after applying this gate variant."""
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 0.0

    @property
    def precision_delta(self) -> float:
        return self.variant_precision - self.baseline_precision

    @property
    def recall_loss(self) -> float:
        """Fraction of relevant injections lost."""
        total_relevant = self.true_positives + self.tp_lost
        return self.tp_lost / total_relevant if total_relevant else 0.0

    @property
    def total_blocked(self) -> int:
        return self.tp_lost + self.fp_eliminated + self.unrated_blocked

    @property
    def total_kept(self) -> int:
        return self.true_positives + self.false_positives + self.unrated_kept


def evaluate_gate_variant(
    variant: GateVariant,
    queries: list[dict],
    feedback_index: dict[str, list[FeedbackEntry]],
) -> GateMetrics:
    """Score a gate variant against feedback ground truth."""
    metrics = GateMetrics(name=variant.name)

    for query in queries:
        originally_injected = {
            c["memory_object_id"] for c in query["candidates"] if c.get("injected")
        }
        if not originally_injected:
            continue

        metrics.total_queries += 1
        metrics.total_injected_baseline += len(originally_injected)

        would_inject, would_block = simulate_injection(query, variant)

        if not would_inject and originally_injected:
            metrics.set_gate_blocks += 1

        for c in query["candidates"]:
            if not c.get("injected"):
                continue
            mem_id = c["memory_object_id"]
            mem_type = c.get("memory_type", "unknown")
            rating = majority_rating(feedback_index.get(mem_id, []))

            if mem_id in would_inject:
                # Kept
                metrics.kept_by_type[mem_type] += 1
                if rating == "relevant":
                    metrics.true_positives += 1
                elif rating == "not_relevant":
                    metrics.false_positives += 1
                else:
                    metrics.unrated_kept += 1
            else:
                # Blocked
                metrics.blocked_by_type[mem_type] += 1
                if rating == "relevant":
                    metrics.tp_lost += 1
                elif rating == "not_relevant":
                    metrics.fp_eliminated += 1
                else:
                    metrics.unrated_blocked += 1

    return metrics


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_all_queries(db_path: str) -> list[dict]:
    """Load all queries with candidate data from query_audit_log."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("""
        SELECT id, query_text, decision_reason, candidate_scores_json, injected_blocks_json
        FROM query_audit_log
        WHERE candidate_scores_json IS NOT NULL
    """)
    rows = []
    for row in cur.fetchall():
        candidates = json.loads(row["candidate_scores_json"])
        # Only include queries that actually injected something
        if any(c.get("injected") for c in candidates):
            rows.append({
                "id": row["id"],
                "query_text": row["query_text"],
                "decision_reason": row["decision_reason"],
                "candidates": candidates,
            })
    conn.close()
    return rows


def load_feedback(db_path: str) -> list[dict]:
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
# Reporting
# ---------------------------------------------------------------------------


def print_results(all_metrics: list[GateMetrics]) -> None:
    """Print comparison table."""
    print("\n" + "=" * 100)
    print("INJECTION GATE PRECISION EVAL")
    print("=" * 100)

    # Header
    print(f"\n{'Variant':<30} {'Prec':<7} {'dPrec':<8} {'RecLoss':<9} "
          f"{'FP elim':<8} {'TP lost':<8} {'Blocked':<8} {'Set blk':<8}")
    print("-" * 100)

    for m in all_metrics:
        print(
            f"{m.name:<30} "
            f"{m.variant_precision:>5.1%}  "
            f"{m.precision_delta:>+5.1%}   "
            f"{m.recall_loss:>5.1%}    "
            f"{m.fp_eliminated:>5}   "
            f"{m.tp_lost:>5}   "
            f"{m.total_blocked:>5}   "
            f"{m.set_gate_blocks:>5}"
        )

    # Baseline stats
    baseline = all_metrics[0]
    print(f"\nBaseline: {baseline.total_queries} queries, "
          f"{baseline.total_injected_baseline} total injections, "
          f"precision {baseline.baseline_precision:.1%}")
    rated = (baseline.true_positives + baseline.tp_lost
             + baseline.false_positives + baseline.fp_eliminated)
    unrated = baseline.unrated_kept + baseline.unrated_blocked
    print(f"Rated coverage: {rated} rated / {rated + unrated} total "
          f"({rated/(rated+unrated):.0%} of injections have feedback)")

    # Type breakdown for best non-baseline variant
    if len(all_metrics) > 1:
        best = max(all_metrics[1:], key=lambda m: m.precision_delta)
        print(f"\n--- Best variant: {best.name} (dprec={best.precision_delta:+.1%}, "
              f"recall loss={best.recall_loss:.1%}) ---")
        print(f"\nBlocked by type:")
        for mtype, count in sorted(best.blocked_by_type.items(), key=lambda x: -x[1]):
            kept = best.kept_by_type.get(mtype, 0)
            print(f"  {mtype:<25} blocked={count:>3}, kept={kept:>3}")

    # Unrated warning
    if baseline.unrated_kept + baseline.unrated_blocked > 0:
        print(f"\nWARNING: {baseline.unrated_kept + baseline.unrated_blocked} injected candidates "
              f"have no feedback (excluded from precision calculation)")


def print_score_distribution(queries: list[dict], feedback_index: dict[str, list[FeedbackEntry]]) -> None:
    """Print vector score distribution of injected candidates by rating."""
    relevant_scores: list[float] = []
    not_relevant_scores: list[float] = []

    for query in queries:
        for c in query["candidates"]:
            if not c.get("injected"):
                continue
            mem_id = c["memory_object_id"]
            vec = c.get("vector_score") or 0
            lex = c.get("lexical_score") or 0
            rating = majority_rating(feedback_index.get(mem_id, []))
            if lex > 0:
                continue  # Only look at vector-only candidates
            if rating == "relevant":
                relevant_scores.append(vec)
            elif rating == "not_relevant":
                not_relevant_scores.append(vec)

    if not relevant_scores and not not_relevant_scores:
        return

    print("\n--- Vector-only candidate score distribution (by feedback) ---")
    if relevant_scores:
        relevant_scores.sort()
        print(f"  Relevant (n={len(relevant_scores)}): "
              f"min={min(relevant_scores):.0f} "
              f"p25={relevant_scores[len(relevant_scores)//4]:.0f} "
              f"median={relevant_scores[len(relevant_scores)//2]:.0f} "
              f"p75={relevant_scores[3*len(relevant_scores)//4]:.0f} "
              f"max={max(relevant_scores):.0f}")
    if not_relevant_scores:
        not_relevant_scores.sort()
        print(f"  Not relevant (n={len(not_relevant_scores)}): "
              f"min={min(not_relevant_scores):.0f} "
              f"p25={not_relevant_scores[len(not_relevant_scores)//4]:.0f} "
              f"median={not_relevant_scores[len(not_relevant_scores)//2]:.0f} "
              f"p75={not_relevant_scores[3*len(not_relevant_scores)//4]:.0f} "
              f"max={max(not_relevant_scores):.0f}")

    if relevant_scores and not_relevant_scores:
        # Separation analysis
        rel_med = relevant_scores[len(relevant_scores) // 2]
        nr_med = not_relevant_scores[len(not_relevant_scores) // 2]
        print(f"  Median gap: {rel_med - nr_med:.0f} "
              f"(relevant median {rel_med:.0f} vs not_relevant {nr_med:.0f})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Injection gate precision eval")
    parser.add_argument("--db", default=None, help="SQLite DB path (default: ~/.pallium/data/pallium.db)")
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
    queries = load_all_queries(db_path)
    feedback_rows = load_feedback(db_path)

    if not queries:
        print("No injection queries found.", file=sys.stderr)
        return 1

    feedback_index = build_feedback_index(feedback_rows)

    print(f"Loaded {len(queries)} queries with injections")
    print(f"Loaded {len(feedback_rows)} feedback entries ({len(feedback_index)} unique memories)")

    # Run all gate variants
    all_metrics: list[GateMetrics] = []
    for variant in GATE_VARIANTS:
        metrics = evaluate_gate_variant(variant, queries, feedback_index)
        all_metrics.append(metrics)

    print_results(all_metrics)
    print_score_distribution(queries, feedback_index)

    return 0


if __name__ == "__main__":
    sys.exit(main())
