"""Lexical scale + RRF weight replay eval -- measures precision impact via pipeline replay.

Replays historical queries through the real routing pipeline with different
LEXICAL_NORM_SCALE and RRF weight configurations. Unlike the gate eval (which
operates on stored scores), this eval captures non-linear pipeline interactions:
- quality_score threshold effects (floor adjustment at <0.5)
- freshness shaping interactions
- set-level gate threshold interactions

Requires the service to be instantiatable against the same DB used for audit logging.

Usage:
    python -m evals.lexical_scale_replay_eval extract-corpus [--db PATH] [--output PATH]
    python -m evals.lexical_scale_replay_eval replay [--corpus PATH] [--db PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals.retrieval_ablation.evaluate import (
    FeedbackEntry,
    build_feedback_index,
    majority_rating,
)


# ---------------------------------------------------------------------------
# Corpus extraction
# ---------------------------------------------------------------------------


def extract_corpus(db_path: str, output_path: str) -> int:
    """Extract replay corpus from query_audit_log to JSONL.

    Each line contains all fields needed to replay the query through the pipeline
    and to score the result against feedback ground truth.
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get queries with candidates (only those that have injection data)
    cur = conn.execute("""
        SELECT id, query_text, container_ref, thread_ref, actor_ref, visibility,
               decision_reason, candidate_scores_json, injected_blocks_json
        FROM query_audit_log
        WHERE candidate_scores_json IS NOT NULL
    """)

    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for row in cur:
            candidates = json.loads(row["candidate_scores_json"])
            entry = {
                "id": row["id"],
                "query_text": row["query_text"],
                "container_ref": row["container_ref"],
                "thread_ref": row["thread_ref"],
                "actor_ref": row["actor_ref"],
                "visibility": row["visibility"],
                "decision_reason": row["decision_reason"],
                "originally_injected_ids": [
                    c["memory_object_id"] for c in candidates if c.get("injected")
                ],
                "candidate_ids": [c["memory_object_id"] for c in candidates],
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            count += 1

    # Also extract feedback to corpus
    feedback_path = output_path.replace(".jsonl", "_feedback.jsonl")
    cur = conn.execute("""
        SELECT memory_object_id, rating, query_context, memory_type
        FROM memory_feedback
    """)
    fb_count = 0
    with open(feedback_path, "w", encoding="utf-8") as f:
        for row in cur:
            f.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
            fb_count += 1

    conn.close()
    print(f"Extracted {count} queries to {output_path}")
    print(f"Extracted {fb_count} feedback entries to {feedback_path}")
    return 0


# ---------------------------------------------------------------------------
# Replay configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayVariant:
    """A configuration variant to test via pipeline replay."""
    name: str
    lexical_norm_scale: float = 6.0    # Current default
    rrf_lexical_weight: float = 1.0     # Weight multiplier for lexical in RRF merge
    rrf_vector_weight: float = 1.0      # Weight multiplier for vector in RRF merge
    set_lexical_threshold: float = 0.33  # Set-level gate threshold (must recalibrate)


def build_variants() -> list[ReplayVariant]:
    """Build the matrix of variants to test."""
    variants = [
        ReplayVariant(name="baseline (current)"),
    ]

    # LEXICAL_NORM_SCALE variants (with proportionally recalibrated set threshold)
    for scale in [20, 30, 40, 50, 60]:
        # Recalibrate set_lexical_threshold: current 0.33 means BM25 >= 2.0
        # For new scale, keep same BM25 floor: 2.0 / new_scale
        recalibrated_threshold = 2.0 / scale
        variants.append(ReplayVariant(
            name=f"scale_{scale}",
            lexical_norm_scale=scale,
            set_lexical_threshold=recalibrated_threshold,
        ))

    # RRF lexical upweighting (with current scale)
    for lex_w in [1.5, 2.0, 2.5]:
        variants.append(ReplayVariant(
            name=f"rrf_lex_{lex_w:.1f}",
            rrf_lexical_weight=lex_w,
        ))

    # Combined: best scale candidates + RRF upweighting
    for scale in [30, 40, 50]:
        recalibrated_threshold = 2.0 / scale
        for lex_w in [1.5, 2.0]:
            variants.append(ReplayVariant(
                name=f"scale_{scale}_rrf_{lex_w:.1f}",
                lexical_norm_scale=scale,
                rrf_lexical_weight=lex_w,
                set_lexical_threshold=recalibrated_threshold,
            ))

    return variants


def _quick_variants() -> list[ReplayVariant]:
    """Reduced variant set for fast iteration."""
    return [
        ReplayVariant(name="baseline (current)"),
        ReplayVariant(name="scale_30", lexical_norm_scale=30, set_lexical_threshold=2.0/30),
        ReplayVariant(name="scale_50", lexical_norm_scale=50, set_lexical_threshold=2.0/50),
        ReplayVariant(name="rrf_lex_2.0", rrf_lexical_weight=2.0),
        ReplayVariant(name="scale_40_rrf_2.0", lexical_norm_scale=40,
                      rrf_lexical_weight=2.0, set_lexical_threshold=2.0/40),
    ]


# ---------------------------------------------------------------------------
# Pipeline replay
# ---------------------------------------------------------------------------


def _apply_variant_patches(variant: ReplayVariant) -> dict[str, Any]:
    """Monkey-patch pipeline constants for a variant. Returns original values."""
    import semantic.agent_conversation_memory_routing_constants as routing_consts
    import retrieval.composite as composite_mod
    import semantic.agent_conversation_memory_routing_injection as injection_mod

    originals = {
        "lexical_norm_scale": routing_consts.LEXICAL_NORM_SCALE,
        "rrf_lexical_weight": getattr(composite_mod, "RRF_LEXICAL_WEIGHT", 1.0),
        "rrf_vector_weight": getattr(composite_mod, "RRF_VECTOR_WEIGHT", 1.0),
        "default_thresholds": injection_mod._DEFAULT_THRESHOLDS,
        "should_allow_kwdefaults": injection_mod.should_allow_injection.__kwdefaults__,
        "candidate_eligible_kwdefaults": injection_mod.candidate_injection_eligible.__kwdefaults__,
    }

    # Patch LEXICAL_NORM_SCALE
    routing_consts.LEXICAL_NORM_SCALE = variant.lexical_norm_scale

    # Patch RRF weights (add module-level attributes that _rrf_merge can read)
    composite_mod.RRF_LEXICAL_WEIGHT = variant.rrf_lexical_weight
    composite_mod.RRF_VECTOR_WEIGHT = variant.rrf_vector_weight

    # Patch injection thresholds via __kwdefaults__ (call sites use default arg binding)
    new_thresholds = injection_mod.InjectionThresholds(
        set_lexical_threshold=variant.set_lexical_threshold,
    )
    injection_mod._DEFAULT_THRESHOLDS = new_thresholds
    injection_mod.should_allow_injection.__kwdefaults__ = {
        **(injection_mod.should_allow_injection.__kwdefaults__ or {}),
        "thresholds": new_thresholds,
    }
    injection_mod.candidate_injection_eligible.__kwdefaults__ = {
        **(injection_mod.candidate_injection_eligible.__kwdefaults__ or {}),
        "thresholds": new_thresholds,
    }

    return originals


def _restore_patches(originals: dict[str, Any]) -> None:
    """Restore original values after variant run."""
    import semantic.agent_conversation_memory_routing_constants as routing_consts
    import retrieval.composite as composite_mod
    import semantic.agent_conversation_memory_routing_injection as injection_mod

    routing_consts.LEXICAL_NORM_SCALE = originals["lexical_norm_scale"]
    composite_mod.RRF_LEXICAL_WEIGHT = originals["rrf_lexical_weight"]
    composite_mod.RRF_VECTOR_WEIGHT = originals["rrf_vector_weight"]
    injection_mod._DEFAULT_THRESHOLDS = originals["default_thresholds"]
    injection_mod.should_allow_injection.__kwdefaults__ = originals["should_allow_kwdefaults"]
    injection_mod.candidate_injection_eligible.__kwdefaults__ = originals["candidate_eligible_kwdefaults"]


def replay_queries(
    service: Any,
    corpus: list[dict],
) -> list[dict]:
    """Replay corpus queries through the pipeline, return injected IDs per query."""
    results = []
    for entry in corpus:
        query_result = service.query(
            text=entry["query_text"],
            limit=10,
            container_ref=entry["container_ref"],
            thread_ref=entry.get("thread_ref"),
            actor_ref=entry.get("actor_ref"),
            visibility=entry.get("visibility", "private"),
        )

        injected_ids = set()
        for block in query_result.injectable_blocks:
            mem_id = getattr(block, "memory_object_id", None)
            if mem_id:
                injected_ids.add(mem_id)

        results.append({
            "id": entry["id"],
            "injected_ids": injected_ids,
            "should_inject": query_result.should_inject,
        })

    return results


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class ReplayMetrics:
    """Results of replaying a variant across all queries."""
    name: str
    total_queries: int = 0
    total_injected: int = 0
    # Against feedback ground truth
    true_positives: int = 0
    false_positives: int = 0
    unrated: int = 0
    # Coverage: relevant memories surfaced
    relevant_surfaced: set = field(default_factory=set)
    total_relevant: int = 0
    # Regression tracking vs baseline
    regressions: int = 0  # queries where relevant memory lost vs baseline
    improvements: int = 0  # queries where false positive removed vs baseline

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 0.0

    @property
    def recall(self) -> float:
        return len(self.relevant_surfaced) / self.total_relevant if self.total_relevant else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def avg_injected(self) -> float:
        return self.total_injected / self.total_queries if self.total_queries else 0.0


def score_replay(
    variant_name: str,
    replay_results: list[dict],
    corpus: list[dict],
    feedback_index: dict[str, list[FeedbackEntry]],
    baseline_results: list[dict] | None = None,
) -> ReplayMetrics:
    """Score replay results against feedback ground truth."""
    all_relevant_ids: set[str] = set()
    for mem_id, entries in feedback_index.items():
        if majority_rating(entries) == "relevant":
            all_relevant_ids.add(mem_id)

    metrics = ReplayMetrics(name=variant_name, total_relevant=len(all_relevant_ids))

    for i, (result, entry) in enumerate(zip(replay_results, corpus)):
        metrics.total_queries += 1
        injected_ids = result["injected_ids"]
        metrics.total_injected += len(injected_ids)

        for mem_id in injected_ids:
            rating = majority_rating(feedback_index.get(mem_id, []))
            if rating == "relevant":
                metrics.true_positives += 1
                metrics.relevant_surfaced.add(mem_id)
            elif rating == "not_relevant":
                metrics.false_positives += 1
            else:
                metrics.unrated += 1

        # Regression tracking vs baseline (per-query: did we lose/gain?)
        if baseline_results:
            baseline_ids = baseline_results[i]["injected_ids"]
            dropped = baseline_ids - injected_ids
            has_regression = False
            has_improvement = False
            for mem_id in dropped:
                rating = majority_rating(feedback_index.get(mem_id, []))
                if rating == "relevant":
                    has_regression = True
                elif rating == "not_relevant":
                    has_improvement = True
            if has_regression:
                metrics.regressions += 1
            if has_improvement:
                metrics.improvements += 1

    return metrics


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_replay_results(all_metrics: list[ReplayMetrics]) -> None:
    """Print comparison table."""
    print("\n" + "=" * 110)
    print("LEXICAL SCALE + RRF REPLAY EVAL")
    print("=" * 110)

    print(f"\n{'Variant':<30} {'Prec':<7} {'Recall':<8} {'F1':<7} "
          f"{'TP':<5} {'FP':<5} {'Avg inj':<8} {'Regress':<8} {'Improve':<8}")
    print("-" * 110)

    baseline = all_metrics[0]
    for m in all_metrics:
        prec_delta = m.precision - baseline.precision
        print(
            f"{m.name:<30} "
            f"{m.precision:>5.1%}  "
            f"{m.recall:>5.1%}   "
            f"{m.f1:>5.3f}  "
            f"{m.true_positives:>4} "
            f"{m.false_positives:>4}  "
            f"{m.avg_injected:>5.1f}   "
            f"{m.regressions:>5}   "
            f"{m.improvements:>5}"
        )

    print(f"\nBaseline precision: {baseline.precision:.1%}, "
          f"recall: {baseline.recall:.1%}, F1: {baseline.f1:.3f}")
    print(f"Total relevant memories in feedback: {baseline.total_relevant}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _load_corpus(corpus_path: str) -> list[dict]:
    """Load replay corpus from JSONL."""
    corpus = []
    with open(corpus_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                corpus.append(json.loads(line))
    return corpus


def _load_feedback_from_jsonl(feedback_path: str) -> dict[str, list[FeedbackEntry]]:
    """Load feedback from JSONL (corpus companion file)."""
    rows = []
    with open(feedback_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return build_feedback_index(rows)


def cmd_extract(args: argparse.Namespace) -> int:
    """Extract corpus subcommand."""
    if args.db:
        db_path = args.db
    else:
        default_path = os.path.expanduser("~/.pallium/data/pallium.db")
        if not Path(default_path).exists():
            print(f"DB not found at {default_path}, pass --db", file=sys.stderr)
            return 1
        db_path = default_path

    output = args.output or "evals/lexical_scale_replay_corpus.jsonl"
    return extract_corpus(db_path, output)


def cmd_replay(args: argparse.Namespace) -> int:
    """Replay subcommand -- runs queries through the pipeline with variant configs."""
    corpus_path = args.corpus or "evals/lexical_scale_replay_corpus.jsonl"
    feedback_path = corpus_path.replace(".jsonl", "_feedback.jsonl")

    if not Path(corpus_path).exists():
        print(f"Corpus not found at {corpus_path}. Run 'extract-corpus' first.", file=sys.stderr)
        return 1

    if args.db:
        db_path = args.db
    else:
        default_path = os.path.expanduser("~/.pallium/data/pallium.db")
        if not Path(default_path).exists():
            print(f"DB not found at {default_path}, pass --db", file=sys.stderr)
            return 1
        db_path = default_path

    print(f"Loading corpus from: {corpus_path}")
    corpus = _load_corpus(corpus_path)
    if args.limit > 0:
        corpus = corpus[:args.limit]
    print(f"Loaded {len(corpus)} queries")

    print(f"Loading feedback from: {feedback_path}")
    feedback_index = _load_feedback_from_jsonl(feedback_path)
    print(f"Loaded feedback for {len(feedback_index)} memories")

    # Bootstrap service
    print(f"Bootstrapping service from: {db_path}")
    from app.config import AppConfig
    from app.dependencies import build_service
    from storage.vector_index import VectorIndexConfig

    base_config = AppConfig.from_env()

    # Determine vector index path (colocated with DB)
    db_dir = Path(db_path).parent
    vector_path = str(db_dir / "vector_index")

    config = AppConfig(
        storage_backend="sqlite",
        sqlite_url=f"sqlite:///{Path(db_path).as_posix()}",
        default_use_case=base_config.default_use_case,
        llm_providers=base_config.llm_providers,
        semantic_packages=base_config.semantic_packages,
        vector_index=VectorIndexConfig(
            enabled=True,
            index_path=vector_path,
            embedding_provider=base_config.vector_index.embedding_provider,
        ),
    )
    build_result = build_service(config)
    service = build_result.service
    print("Service ready.")

    # Run variants
    variants = build_variants() if not args.quick else _quick_variants()
    all_metrics: list[ReplayMetrics] = []
    baseline_results: list[dict] | None = None

    for i, variant in enumerate(variants):
        print(f"\n[{i+1}/{len(variants)}] Running variant: {variant.name}...")
        originals = _apply_variant_patches(variant)
        try:
            t0 = time.time()
            results = replay_queries(service, corpus)
            elapsed = time.time() - t0
            print(f"  Completed in {elapsed:.1f}s")

            metrics = score_replay(
                variant.name, results, corpus, feedback_index,
                baseline_results=baseline_results,
            )
            all_metrics.append(metrics)

            if baseline_results is None:
                baseline_results = results
        finally:
            _restore_patches(originals)

    print_replay_results(all_metrics)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Lexical scale + RRF replay eval")
    subparsers = parser.add_subparsers(dest="command")

    # Extract corpus
    p_extract = subparsers.add_parser("extract-corpus", help="Extract replay corpus from DB")
    p_extract.add_argument("--db", default=None, help="SQLite DB path")
    p_extract.add_argument("--output", default=None, help="Output JSONL path")

    # Replay
    p_replay = subparsers.add_parser("replay", help="Run pipeline replay with variant configs")
    p_replay.add_argument("--corpus", default=None, help="Corpus JSONL path")
    p_replay.add_argument("--db", default=None, help="SQLite DB path (for service)")
    p_replay.add_argument("--limit", type=int, default=0, help="Limit to first N queries (0=all)")
    p_replay.add_argument("--quick", action="store_true", help="Run reduced variant set for faster iteration")

    args = parser.parse_args()

    if args.command == "extract-corpus":
        return cmd_extract(args)
    elif args.command == "replay":
        return cmd_replay(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
