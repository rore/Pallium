"""Fast retrieval-only experiments — measures gold-in-context without LLM calls.

Runs queries through Pallium's retrieval pipeline, checks if gold answer
keywords appear in the retrieved results. No justifier/judge LLM calls needed.
Takes ~2-3 minutes per config instead of ~1 hour.

Usage:
    python -m evals.retrieval_fast_experiments
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

from evals.retrieval_experiments import (
    SOURCE_DB_CACHE,
    BASELINE_RESULTS,
    EXPERIMENT_DIR,
    _copy_db_cache,
    prepare_experiment_b,
    prepare_experiment_e,
    prepare_experiment_f,
)

CONVERSATIONS = ["conv-26", "conv-43", "conv-44"]
DATASET_PATH = Path("evals/locomo/datasets/locomo10.json")

STOPWORDS = frozenset(
    "the a an is was of in to and for on at by with from that this they their have "
    "been were would could about she her his he yes no not has had are but does did "
    "will can it its who what when where how which than then also just more some very "
    "like so or if as be do my me we us our up go went get got one two new all any "
    "may much many own out say said".split()
)


def _gold_keywords(gold_answer: str) -> list[str]:
    return [
        w.strip('.,!?"\'()[]')
        for w in gold_answer.lower().split()
        if len(w.strip('.,!?"\'()[]')) > 2 and w.strip('.,!?"\'()[]') not in STOPWORDS
    ]


def _check_gold_in_context(gold_answer: str, results: list[dict]) -> bool:
    """Check if gold answer keywords are present in retrieved results."""
    keywords = _gold_keywords(gold_answer)
    if not keywords:
        return True  # trivial gold

    parts = []
    for r in results:
        parts.append(r.get("excerpt") or "")
        payload = r.get("payload") or {}
        parts.append(payload.get("summary") or "")
        parts.append(payload.get("statement") or "")
        parts.append(payload.get("decision") or "")
        parts.append(payload.get("description") or "")
    context = " ".join(parts).lower()

    found = sum(1 for k in keywords if k in context)
    return found / len(keywords) >= 0.5


def _run_retrieval_only(
    db_cache_dir: Path,
    conversations: list[str],
    dataset: list[dict],
    query_limit: int = 10,
) -> list[dict]:
    """Run queries through Pallium retrieval, return results with gold-in-context."""
    from dataclasses import replace as dc_replace

    from app.config import AppConfig
    from app.main import create_app
    from starlette.testclient import TestClient

    all_results = []

    for conv_data in dataset:
        sample_id = conv_data["sample_id"]
        if sample_id not in conversations:
            continue

        qa_pairs = conv_data.get("qa", [])
        db_path = db_cache_dir / f"{sample_id}.db"
        vector_prefix = db_cache_dir / f"{sample_id}.vector.index"

        if not db_path.exists():
            print(f"  SKIP {sample_id}: no cached DB")
            continue

        config = AppConfig.from_env()
        vector_index_config = dc_replace(
            config.vector_index,
            index_path=str(vector_prefix) if vector_prefix.exists() else None,
        )
        scenario_config = dc_replace(
            config,
            sqlite_url=f"sqlite:///{db_path}",
            default_use_case="agent_conversation_memory",
            vector_index=vector_index_config,
        )

        app = create_app(scenario_config)
        with TestClient(app) as client:
            # Wait for lifespan
            health = client.get("/health")

            for qa in qa_pairs:
                query_payload = {
                    "text": qa["question"],
                    "limit": query_limit,
                    "container_ref": sample_id,
                    "visibility": "public",
                    "runtime_context": {
                        "turn_kind": "new_session",
                        "session_has_sufficient_local_context": False,
                    },
                }
                resp = client.post("/query/debug", json=query_payload)
                if resp.status_code != 200:
                    continue

                mem_payload = resp.json()
                results_list = mem_payload.get("results", [])

                gold = str(qa.get("answer", ""))
                category = qa.get("category", 0)

                gic = _check_gold_in_context(gold, results_list)

                all_results.append({
                    "sample_id": sample_id,
                    "question": qa["question"],
                    "gold_answer": gold,
                    "category": category,
                    "category_name": {1: "multi_hop", 2: "single_hop", 3: "temporal", 4: "open_domain"}.get(category, "unknown"),
                    "gold_in_context": gic,
                    "result_count": len(results_list),
                    "result_types": [r.get("type") for r in results_list],
                })

        print(f"  {sample_id}: {len([r for r in all_results if r['sample_id'] == sample_id])} questions")

    return all_results


def _analyze(results: list[dict], label: str) -> dict:
    total = len(results)
    gic = sum(1 for r in results if r["gold_in_context"])
    by_cat = defaultdict(lambda: {"total": 0, "gic": 0})
    for r in results:
        by_cat[r["category_name"]]["total"] += 1
        if r["gold_in_context"]:
            by_cat[r["category_name"]]["gic"] += 1
    return {"label": label, "total": total, "gic": gic, "gic_rate": gic / total * 100 if total else 0, "by_category": dict(by_cat)}


def _prepare_option1(db_dir: Path, conversations: list[str], bonus: int = 30, penalty: int = 20) -> None:
    """Option 1: Score adjustment — modify routing constants temporarily.

    We can't easily modify routing scoring for a DB-only experiment.
    Instead, simulate the EFFECT: for each query, if we had subject-boosted,
    which results would change? We measure this differently — see below.
    """
    # Option 1 can't be done via DB modification alone. We'll handle it
    # by modifying the actual routing code temporarily. Skip for now.
    pass


def _prepare_option2_light(db_dir: Path, conversations: list[str]) -> None:
    """Option 2 light: Envelope bridge + reduce anchor penalty.

    Populate envelopes (like F) but also set a flag that the anchor prefilter
    can read. Since we can't modify code per-experiment, we approximate by
    populating envelopes but marking secondary facts differently.

    Actually — the simplest approximation is: populate envelopes BUT set
    all non-matching facts to unanchored_legacy by giving them empty subjects.
    This way the prefilter doesn't penalize them.
    """
    # This is hard to simulate via DB alone. Skip — we'll test option 2 differently.
    pass


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Fast retrieval-only experiments")
    parser.add_argument("--conversations", nargs="*", default=CONVERSATIONS)
    args = parser.parse_args()
    conversations = args.conversations

    # Load dataset
    with open(DATASET_PATH) as f:
        dataset = json.load(f)

    print(f"Conversations: {conversations}")
    print(f"Questions: {sum(len(c.get('qa', [])) for c in dataset if c['sample_id'] in conversations)}")

    all_analyses = []

    # --- Config A: Baseline (unmodified DBs) ---
    print("\n=== A (baseline) ===")
    t0 = time.time()
    results_a = _run_retrieval_only(SOURCE_DB_CACHE, conversations, dataset)
    print(f"  Time: {time.time() - t0:.0f}s")
    all_analyses.append(_analyze(results_a, "A (baseline)"))

    # --- Config E: Fragment indexing ---
    print("\n=== E (fragment indexing) ===")
    exp_dir = EXPERIMENT_DIR / "fast_db_E"
    _copy_db_cache(SOURCE_DB_CACHE, exp_dir, conversations)
    prepare_experiment_e(exp_dir, conversations)
    t0 = time.time()
    results_e = _run_retrieval_only(exp_dir, conversations, dataset)
    print(f"  Time: {time.time() - t0:.0f}s")
    all_analyses.append(_analyze(results_e, "E (fragment idx)"))
    shutil.rmtree(exp_dir)

    # --- Config F: Envelope bridge ---
    print("\n=== F (envelope bridge) ===")
    exp_dir = EXPERIMENT_DIR / "fast_db_F"
    _copy_db_cache(SOURCE_DB_CACHE, exp_dir, conversations)
    prepare_experiment_f(exp_dir, conversations)
    t0 = time.time()
    results_f = _run_retrieval_only(exp_dir, conversations, dataset)
    print(f"  Time: {time.time() - t0:.0f}s")
    all_analyses.append(_analyze(results_f, "F (envelope)"))
    shutil.rmtree(exp_dir)

    # --- Config B: Soft lifecycle ---
    print("\n=== B (soft lifecycle) ===")
    exp_dir = EXPERIMENT_DIR / "fast_db_B"
    _copy_db_cache(SOURCE_DB_CACHE, exp_dir, conversations)
    prepare_experiment_b(exp_dir, conversations)
    t0 = time.time()
    results_b = _run_retrieval_only(exp_dir, conversations, dataset)
    print(f"  Time: {time.time() - t0:.0f}s")
    all_analyses.append(_analyze(results_b, "B (soft lifecycle)"))
    shutil.rmtree(exp_dir)

    # --- Config B+F: Soft lifecycle + envelopes ---
    print("\n=== B+F (soft lifecycle + envelope) ===")
    exp_dir = EXPERIMENT_DIR / "fast_db_BF"
    _copy_db_cache(SOURCE_DB_CACHE, exp_dir, conversations)
    prepare_experiment_b(exp_dir, conversations)
    prepare_experiment_f(exp_dir, conversations)
    t0 = time.time()
    results_bf = _run_retrieval_only(exp_dir, conversations, dataset)
    print(f"  Time: {time.time() - t0:.0f}s")
    all_analyses.append(_analyze(results_bf, "B+F (lifecycle+env)"))
    shutil.rmtree(exp_dir)

    # --- Config E+F: Fragment + envelopes ---
    print("\n=== E+F (fragment + envelope) ===")
    exp_dir = EXPERIMENT_DIR / "fast_db_EF"
    _copy_db_cache(SOURCE_DB_CACHE, exp_dir, conversations)
    prepare_experiment_e(exp_dir, conversations)
    prepare_experiment_f(exp_dir, conversations)
    t0 = time.time()
    results_ef = _run_retrieval_only(exp_dir, conversations, dataset)
    print(f"  Time: {time.time() - t0:.0f}s")
    all_analyses.append(_analyze(results_ef, "E+F (frag+env)"))
    shutil.rmtree(exp_dir)

    # --- Option 1: Subject score adjustment (no DB changes, toggle routing flag) ---
    print("\n=== O1 (subject scoring) ===")
    import semantic.agent_conversation_memory_routing_scoring as scoring_mod
    scoring_mod.SUBJECT_MATCH_ENABLED = True
    scoring_mod.SUBJECT_MATCH_BONUS = 30
    scoring_mod.SUBJECT_MISMATCH_PENALTY = 20
    t0 = time.time()
    results_o1 = _run_retrieval_only(SOURCE_DB_CACHE, conversations, dataset)
    print(f"  Time: {time.time() - t0:.0f}s")
    all_analyses.append(_analyze(results_o1, "O1 (score +30/-20)"))
    scoring_mod.SUBJECT_MATCH_ENABLED = False

    # --- Option 1 aggressive ---
    print("\n=== O1a (aggressive scoring) ===")
    scoring_mod.SUBJECT_MATCH_ENABLED = True
    scoring_mod.SUBJECT_MATCH_BONUS = 50
    scoring_mod.SUBJECT_MISMATCH_PENALTY = 40
    t0 = time.time()
    results_o1a = _run_retrieval_only(SOURCE_DB_CACHE, conversations, dataset)
    print(f"  Time: {time.time() - t0:.0f}s")
    all_analyses.append(_analyze(results_o1a, "O1a (score +50/-40)"))
    scoring_mod.SUBJECT_MATCH_ENABLED = False

    # --- Option 1 + envelopes combined ---
    print("\n=== O1+F (scoring + envelope) ===")
    exp_dir = EXPERIMENT_DIR / "fast_db_O1F"
    _copy_db_cache(SOURCE_DB_CACHE, exp_dir, conversations)
    prepare_experiment_f(exp_dir, conversations)
    scoring_mod.SUBJECT_MATCH_ENABLED = True
    scoring_mod.SUBJECT_MATCH_BONUS = 30
    scoring_mod.SUBJECT_MISMATCH_PENALTY = 20
    t0 = time.time()
    results_o1f = _run_retrieval_only(exp_dir, conversations, dataset)
    print(f"  Time: {time.time() - t0:.0f}s")
    all_analyses.append(_analyze(results_o1f, "O1+F (score+env)"))
    scoring_mod.SUBJECT_MATCH_ENABLED = False
    shutil.rmtree(exp_dir)

    # --- Print comparison ---
    cats = ["single_hop", "multi_hop", "open_domain", "temporal"]

    print("\n" + "=" * 90)
    print("FAST EXPERIMENT COMPARISON (Gold-in-Context rate)")
    print("=" * 90)

    header = f"{'Config':<25} | {'GiC':>7} | {'Total':>5}"
    for cat in cats:
        header += f" | {cat:>12}"
    print(header)
    print("-" * len(header))

    for a in all_analyses:
        line = f"{a['label']:<25} | {a['gic_rate']:>6.1f}% | {a['total']:>5}"
        for cat in cats:
            bc = a["by_category"].get(cat, {"total": 0, "gic": 0})
            gic_rate = bc["gic"] / bc["total"] * 100 if bc["total"] else 0
            line += f" | {gic_rate:>11.1f}%"
        print(line)

    # Delta from baseline
    print(f"\n{'DELTA vs baseline':<25}", end="")
    print(f" | {'':>7} | {'':>5}", end="")
    for cat in cats:
        print(f" | {cat:>12}", end="")
    print()
    print("-" * (25 + 17 + 15 * len(cats)))
    for a in all_analyses[1:]:
        delta_total = a["gic_rate"] - all_analyses[0]["gic_rate"]
        print(f"{a['label']:<25} | {delta_total:>+6.1f}% | {'':>5}", end="")
        for cat in cats:
            bc = a["by_category"].get(cat, {"total": 0, "gic": 0})
            bb = all_analyses[0]["by_category"].get(cat, {"total": 0, "gic": 0})
            gic_a = bc["gic"] / bc["total"] * 100 if bc["total"] else 0
            gic_b = bb["gic"] / bb["total"] * 100 if bb["total"] else 0
            delta = gic_a - gic_b
            print(f" | {delta:>+11.1f}%", end="")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
