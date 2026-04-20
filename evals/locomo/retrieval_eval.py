"""Fast retrieval-only eval for LoCoMo benchmark.

Runs the retrieval + injection pipeline against cached DBs without any LLM
calls. Measures gold_in_context using token-overlap heuristic to evaluate
retrieval/injection changes in minutes rather than hours.

Usage:
    # Baseline (unmodified cached DBs)
    python -m evals.locomo.retrieval_eval

    # With DB mutation (e.g., flip atomic_fact lifecycle)
    python -m evals.locomo.retrieval_eval --mutate unsupersede-atomic-facts

    # Single conversation for fast iteration
    python -m evals.locomo.retrieval_eval --conversations conv-43

    # Compare against a baseline run
    python -m evals.locomo.retrieval_eval --baseline evals/locomo/retrieval_eval_output/baseline/results.jsonl
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from evals.eval_common import (
    copy_vector_index as _copy_vector_index,
    format_retrieved_context as _format_retrieved_context,
    gold_in_context as _gold_in_context_heuristic,
    retrieval_summary as _retrieval_summary,
)
from evals.locomo_benchmark import CATEGORY_NAMES

DEFAULT_DATASET_PATH = Path("evals/locomo/datasets/locomo10.json")
DEFAULT_DB_CACHE_DIR = Path("evals/locomo/db_cache")
DEFAULT_OUTPUT_DIR = Path("evals/locomo/retrieval_eval_output")


def _gold_in_context_token_overlap(gold_answer: str, context: str) -> bool:
    return _gold_in_context_heuristic(gold_answer, context)


# ---------------------------------------------------------------------------
# DB mutations
# ---------------------------------------------------------------------------

def _mutate_unsupersede_atomic_facts(db_path: Path) -> int:
    """Flip all superseded atomic_fact records back to active."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "UPDATE memory_objects SET lifecycle = 'active' "
        "WHERE type = 'atomic_fact' AND lifecycle = 'superseded'"
    )
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


MUTATIONS: dict[str, Any] = {
    "unsupersede-atomic-facts": _mutate_unsupersede_atomic_facts,
}


# ---------------------------------------------------------------------------
# Code-path patches (monkey-patch at eval start, restored on exit)
# ---------------------------------------------------------------------------

def _apply_code_patch(patch_name: str) -> None:
    import semantic.agent_conversation_memory_routing_selection as sel_mod

    if patch_name == "lift-fact-summary-limit":
        # Allow up to 2 fact_summaries in injection instead of 1
        def _patched_can_select(candidate, selected):
            item = candidate["item"]
            if item.type != "fact_summary":
                return True
            fact_count = sum(
                1 for kept in selected
                if hasattr(kept.get("item"), "type") and kept["item"].type == "fact_summary"
            )
            return fact_count < 2
        sel_mod._can_select_candidate_under_fact_summary_limit = _patched_can_select

    elif patch_name == "lift-fact-summary-limit-3":
        def _patched_can_select(candidate, selected):
            item = candidate["item"]
            if item.type != "fact_summary":
                return True
            fact_count = sum(
                1 for kept in selected
                if hasattr(kept.get("item"), "type") and kept["item"].type == "fact_summary"
            )
            return fact_count < 3
        sel_mod._can_select_candidate_under_fact_summary_limit = _patched_can_select

    elif patch_name == "bypass-anchor-prefilter":
        # Allow fact_summary injection regardless of anchor prefilter status
        def _patched_fs_eligible(candidate, *, intent):
            if intent != "recall":
                return False
            return True
        sel_mod._fact_summary_is_injection_eligible = _patched_fs_eligible

    elif patch_name == "bypass-anchor-and-lift-limit":
        def _patched_fs_eligible(candidate, *, intent):
            if intent != "recall":
                return False
            return True
        sel_mod._fact_summary_is_injection_eligible = _patched_fs_eligible
        def _patched_can_select(candidate, selected):
            item = candidate["item"]
            if item.type != "fact_summary":
                return True
            fact_count = sum(
                1 for kept in selected
                if hasattr(kept.get("item"), "type") and kept["item"].type == "fact_summary"
            )
            return fact_count < 3
        sel_mod._can_select_candidate_under_fact_summary_limit = _patched_can_select


CODE_PATCHES: dict[str, Any] = {
    "lift-fact-summary-limit": "lift-fact-summary-limit",
    "lift-fact-summary-limit-3": "lift-fact-summary-limit-3",
    "bypass-anchor-prefilter": "bypass-anchor-prefilter",
    "bypass-anchor-and-lift-limit": "bypass-anchor-and-lift-limit",
}


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------

def run_retrieval_eval(
    *,
    dataset_path: Path = DEFAULT_DATASET_PATH,
    db_cache_dir: Path = DEFAULT_DB_CACHE_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    conversations: list[str] | None = None,
    mutation: str | None = None,
    code_patch: str | None = None,
    baseline_path: Path | None = None,
    query_limit: int = 10,
) -> dict[str, Any]:
    if code_patch and code_patch in CODE_PATCHES:
        _apply_code_patch(code_patch)
        print(f"  Applied code patch: {code_patch}")
    with open(dataset_path) as f:
        dataset = json.load(f)

    config = AppConfig.from_env()

    if conversations:
        dataset = [c for c in dataset if c["sample_id"] in conversations]

    tag = code_patch or mutation or "baseline"
    run_output_dir = output_dir / tag
    run_output_dir.mkdir(parents=True, exist_ok=True)

    baseline_results: dict[str, dict[str, Any]] = {}
    if baseline_path and baseline_path.exists():
        with open(baseline_path) as f:
            for line in f:
                r = json.loads(line)
                key = f"{r['sample_id']}::{r['question']}"
                baseline_results[key] = r

    all_results: list[dict[str, Any]] = []

    for conv in dataset:
        sample_id = conv["sample_id"]
        qa_pairs = conv.get("qa", [])
        cached_db = db_cache_dir / f"{sample_id}.db"
        cached_vector = db_cache_dir / f"{sample_id}.vector.index"

        if not cached_db.exists():
            print(f"  SKIP {sample_id} (no cached DB)")
            continue

        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "eval.db"
            vector_path = Path(temp_dir) / "vector.index"

            shutil.copy2(cached_db, db_path)
            _copy_vector_index(cached_vector, vector_path)

            if mutation and mutation in MUTATIONS:
                count = MUTATIONS[mutation](db_path)
                print(f"  {sample_id}: mutation '{mutation}' affected {count} rows")

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

            with TestClient(create_app(scenario_config)) as client:
                # Reconcile vector index once
                while client.app.state.pallium_service.reconcile_vector_index() > 0:
                    pass

                for qa in qa_pairs:
                    question = qa["question"]
                    gold_answer = str(qa.get("answer", ""))
                    category = qa.get("category", 0)
                    category_name = CATEGORY_NAMES.get(category, f"unknown_{category}")

                    query_payload = {
                        "text": question,
                        "limit": query_limit,
                        "container_ref": sample_id,
                        "visibility": "public",
                        "runtime_context": {
                            "turn_kind": "new_session",
                            "session_has_sufficient_local_context": False,
                        },
                    }
                    resp = client.post("/query/debug", json=query_payload)
                    resp.raise_for_status()
                    mem_payload = resp.json()

                    context = _format_retrieved_context(mem_payload)
                    gold_in_ctx = _gold_in_context_token_overlap(gold_answer, context)

                    result_key = f"{sample_id}::{question}"
                    baseline_gold = baseline_results.get(result_key, {}).get("gold_in_context")

                    injectable_blocks = mem_payload.get("injectable_blocks", [])
                    block_types = [b.get("memory_type", "") for b in injectable_blocks]
                    block_texts = [b.get("text", "")[:200] for b in injectable_blocks]

                    result: dict[str, Any] = {
                        "sample_id": sample_id,
                        "question": question,
                        "gold_answer": gold_answer,
                        "category": category,
                        "category_name": category_name,
                        "should_inject": mem_payload.get("should_inject"),
                        "decision_reason": mem_payload.get("decision_reason"),
                        "injectable_block_count": len(injectable_blocks),
                        "injectable_block_types": block_types,
                        "gold_in_context": gold_in_ctx,
                        "retrieval_summary": _retrieval_summary(mem_payload),
                    }

                    if baseline_gold is not None:
                        if not baseline_gold and gold_in_ctx:
                            result["delta"] = "IMPROVED"
                        elif baseline_gold and not gold_in_ctx:
                            result["delta"] = "REGRESSED"
                        else:
                            result["delta"] = "unchanged"

                    all_results.append(result)

        print(f"  {sample_id}: {len(qa_pairs)} questions evaluated")

    # Write results
    results_path = run_output_dir / "results.jsonl"
    with open(results_path, "w") as f:
        for r in all_results:
            f.write(json.dumps(r) + "\n")

    # Compute summary
    summary = _compute_summary(all_results, mutation=mutation, baseline_results=baseline_results)
    summary_path = run_output_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    _print_summary(summary)
    return summary


def _compute_summary(
    results: list[dict[str, Any]],
    *,
    mutation: str | None = None,
    baseline_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    total = len(results)
    gold_in = sum(1 for r in results if r.get("gold_in_context"))
    injected = sum(1 for r in results if r.get("should_inject"))

    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "gold_in_context": 0})
    by_conversation: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "gold_in_context": 0})

    for r in results:
        cat = r.get("category_name", "unknown")
        by_category[cat]["total"] += 1
        if r.get("gold_in_context"):
            by_category[cat]["gold_in_context"] += 1
        conv = r.get("sample_id", "unknown")
        by_conversation[conv]["total"] += 1
        if r.get("gold_in_context"):
            by_conversation[conv]["gold_in_context"] += 1

    improvements = sum(1 for r in results if r.get("delta") == "IMPROVED")
    regressions = sum(1 for r in results if r.get("delta") == "REGRESSED")

    summary: dict[str, Any] = {
        "mutation": mutation or "baseline",
        "total_questions": total,
        "gold_in_context": gold_in,
        "gold_in_context_rate": round(gold_in / total * 100, 1) if total else 0,
        "injection_rate": round(injected / total * 100, 1) if total else 0,
        "by_category": {
            cat: {
                "total": stats["total"],
                "gold_in_context": stats["gold_in_context"],
                "rate": round(stats["gold_in_context"] / stats["total"] * 100, 1) if stats["total"] else 0,
            }
            for cat, stats in sorted(by_category.items())
        },
        "by_conversation": {
            conv: {
                "total": stats["total"],
                "gold_in_context": stats["gold_in_context"],
                "rate": round(stats["gold_in_context"] / stats["total"] * 100, 1) if stats["total"] else 0,
            }
            for conv, stats in sorted(by_conversation.items())
        },
    }

    if baseline_results:
        summary["vs_baseline"] = {
            "improvements": improvements,
            "regressions": regressions,
            "net": improvements - regressions,
        }

    return summary


def _print_summary(summary: dict[str, Any]) -> None:
    total = summary["total_questions"]
    gold_in = summary["gold_in_context"]
    print(f"\n{'='*60}")
    print(f"Retrieval Eval: {summary['mutation']}")
    print(f"{'='*60}")
    print(f"Total questions: {total}")
    print(f"Gold in context: {gold_in}/{total} ({summary['gold_in_context_rate']}%)")
    print(f"Injection rate:  {summary['injection_rate']}%")

    print(f"\nBy category:")
    for cat, stats in summary["by_category"].items():
        print(f"  {cat:15s}: {stats['gold_in_context']:3d}/{stats['total']:3d} ({stats['rate']}%)")

    print(f"\nBy conversation:")
    for conv, stats in summary["by_conversation"].items():
        print(f"  {conv:10s}: {stats['gold_in_context']:3d}/{stats['total']:3d} ({stats['rate']}%)")

    vs = summary.get("vs_baseline")
    if vs:
        print(f"\nVs baseline:")
        print(f"  Improvements: {vs['improvements']}")
        print(f"  Regressions:  {vs['regressions']}")
        print(f"  Net:          {vs['net']:+d}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fast retrieval-only LoCoMo eval")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--db-cache-dir", type=Path, default=DEFAULT_DB_CACHE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--conversations", nargs="+", help="Limit to specific conversations")
    parser.add_argument("--mutate", choices=list(MUTATIONS.keys()), help="Apply DB mutation before eval")
    parser.add_argument("--code-patch", choices=list(CODE_PATCHES.keys()), help="Apply code-path patch for eval")
    parser.add_argument("--baseline", type=Path, help="Path to baseline results.jsonl for comparison")
    parser.add_argument("--query-limit", type=int, default=10)
    args = parser.parse_args()

    run_retrieval_eval(
        dataset_path=args.dataset,
        db_cache_dir=args.db_cache_dir,
        output_dir=args.output_dir,
        conversations=args.conversations,
        mutation=args.mutate,
        code_patch=args.code_patch,
        baseline_path=args.baseline,
        query_limit=args.query_limit,
    )


if __name__ == "__main__":
    main()
