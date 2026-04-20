"""Simulate fix impact on all conv-43 questions.

For each of 178 questions, runs /query/debug and records:
- Which fact_summaries are in results and their rank
- Which block was injected
- Whether gold keyword is in: injected blocks, non-injected results, DB but not retrieved

Then simulates:
1. Raising fact_summary injection limit from 1 to 2 or 3
2. Subject-agnostic retrieval (would the gold be found if we ignored subject?)

Outputs a CSV-like table and summary stats.
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import AppConfig
from app.main import create_app
from starlette.testclient import TestClient


SAMPLE_ID = "conv-43"
DB_CACHE_DIR = Path("evals/locomo/db_cache")
BASELINE_RESULTS = Path("evals/locomo/output/locomo-benchmark__anthropic-claude__anthropic--claude-sonnet-latest__20260417T174555Z/results.jsonl")


def _copy_vector_index(src_prefix: Path, dst_prefix: Path):
    for suffix in ["", ".idmap.json", ".meta.json"]:
        src = Path(f"{src_prefix}{suffix}")
        dst = Path(f"{dst_prefix}{suffix}")
        if src.exists():
            shutil.copy2(src, dst)


def main():
    config = AppConfig.from_env()

    # Load baseline results to get questions + gold answers
    baseline_qa = []
    with open(BASELINE_RESULTS) as f:
        for line in f:
            r = json.loads(line)
            if r["sample_id"] != SAMPLE_ID:
                continue
            baseline_qa.append(r)

    print(f"Loaded {len(baseline_qa)} questions from baseline results")

    with TemporaryDirectory(ignore_cleanup_errors=True) as td:
        db = Path(td) / "l.db"
        vp = Path(td) / "v.index"
        shutil.copy2(DB_CACHE_DIR / f"{SAMPLE_ID}.db", db)
        _copy_vector_index(DB_CACHE_DIR / f"{SAMPLE_ID}.vector.index", vp)

        sc = replace(config, sqlite_url=f"sqlite:///{db}",
                     default_use_case="agent_conversation_memory",
                     vector_index=replace(config.vector_index, index_path=str(vp)))

        with TestClient(create_app(sc)) as client:
            storage = client.app.state.pallium_service._storage

            # Build memory object index
            all_active = storage.list_memory_objects(lifecycle="active")
            mo_texts = {}
            for mo in all_active:
                text = json.dumps(mo.payload).lower()
                mo_texts[mo.id] = {"type": mo.type, "text": text,
                                   "subject": str(mo.payload.get("subject", "")).lower(),
                                   "category": str(mo.payload.get("category", "")).lower()}

            # Process each question
            results_data = []
            progress = 0
            for qa in baseline_qa:
                progress += 1
                if progress % 20 == 0:
                    print(f"  Processing {progress}/{len(baseline_qa)}...", file=sys.stderr)

                question = qa["question"]
                gold_answer = qa["gold_answer"].lower()
                gold_words = [w for w in gold_answer.split() if len(w) > 3]
                baseline_correct = qa.get("correct", False)
                category = qa.get("category_name", "")

                resp = client.post("/query/debug", json={
                    "text": question, "limit": 10,
                    "container_ref": SAMPLE_ID, "visibility": "public",
                    "runtime_context": {"turn_kind": "new_session",
                                       "session_has_sufficient_local_context": False},
                })
                data = resp.json()
                results = data.get("results", [])
                injectable = data.get("injectable_blocks", [])

                # Classify each result
                fs_results = []  # fact_summaries in results
                injected_fs = []  # injected fact_summaries
                gold_in_injected = False
                gold_in_result_fs = []  # fact_summaries with gold keyword
                gold_in_result_any = False

                injectable_text = json.dumps(injectable).lower()
                # Check if gold answer keywords are in injected blocks
                gold_match_count = sum(1 for w in gold_words if w in injectable_text)
                gold_in_injected = gold_match_count >= max(1, len(gold_words) // 3)

                for i, r in enumerate(results):
                    mo_id = r.get("memory_object_id", "")
                    rtype = r.get("type") or "source_hit"
                    score = r.get("score", 0)
                    is_injected = any(b.get("memory_object_id") == mo_id for b in injectable)

                    if rtype == "fact_summary":
                        fs_results.append({"rank": i, "id": mo_id, "score": score, "injected": is_injected})
                        if is_injected:
                            injected_fs.append(mo_id)

                    # Check if this result has gold keywords
                    r_text = json.dumps(r).lower()
                    r_gold_match = sum(1 for w in gold_words if w in r_text)
                    if r_gold_match >= max(1, len(gold_words) // 3):
                        gold_in_result_any = True
                        if rtype == "fact_summary":
                            gold_in_result_fs.append({"rank": i, "id": mo_id, "injected": is_injected})

                # Check DB for gold (across all active objects)
                gold_in_db_fs = []
                gold_in_db_other = []
                for mo_id, info in mo_texts.items():
                    text_match = sum(1 for w in gold_words if w in info["text"])
                    if text_match >= max(1, len(gold_words) // 3):
                        in_results = any(r.get("memory_object_id") == mo_id for r in results)
                        entry = {"id": mo_id, "type": info["type"], "subject": info["subject"],
                                 "in_results": in_results}
                        if info["type"] == "fact_summary":
                            gold_in_db_fs.append(entry)
                        else:
                            gold_in_db_other.append(entry)

                # Determine loss point
                if baseline_correct:
                    loss = "correct"
                elif gold_in_injected:
                    loss = "answering"
                elif gold_in_result_fs:
                    non_injected = [g for g in gold_in_result_fs if not g["injected"]]
                    if non_injected:
                        loss = "injection_limit"
                    else:
                        loss = "gold_check_mismatch"
                elif gold_in_result_any:
                    loss = "injection_non_fs"
                elif gold_in_db_fs:
                    retrieved_ids = {r.get("memory_object_id") for r in results}
                    if any(g["in_results"] for g in gold_in_db_fs):
                        loss = "injection_limit"  # in results but not identified as gold match above
                    else:
                        loss = "retrieval_miss_fs"
                elif gold_in_db_other:
                    loss = "retrieval_miss_other"
                else:
                    loss = "extraction_gap"

                # Simulate: would injecting top-2 or top-3 fact_summaries help?
                sim_top2_helps = False
                sim_top3_helps = False
                if loss in ("injection_limit", "injection_non_fs") and gold_in_result_fs:
                    for g in gold_in_result_fs:
                        if g["rank"] < len(fs_results) and any(fs["rank"] <= g["rank"] for fs in fs_results[:3]):
                            if sum(1 for fs in fs_results if fs["rank"] < g["rank"]) < 2:
                                sim_top2_helps = True
                            if sum(1 for fs in fs_results if fs["rank"] < g["rank"]) < 3:
                                sim_top3_helps = True

                results_data.append({
                    "question": question,
                    "category": category,
                    "baseline_correct": baseline_correct,
                    "loss": loss,
                    "fs_in_results": len(fs_results),
                    "fs_injected": len(injected_fs),
                    "gold_in_result_fs_count": len(gold_in_result_fs),
                    "gold_in_db_fs_count": len(gold_in_db_fs),
                    "gold_in_db_other_count": len(gold_in_db_other),
                    "sim_top2_helps": sim_top2_helps,
                    "sim_top3_helps": sim_top3_helps,
                    "gold_fs_subjects": list({g["subject"] for g in gold_in_db_fs}),
                })

            # Summary
            print(f"\n{'='*70}")
            print("LOSS POINT DISTRIBUTION (all 178 questions):")
            loss_counts = Counter(r["loss"] for r in results_data)
            for loss, count in loss_counts.most_common():
                pct = 100 * count / len(results_data)
                print(f"  {loss:25s}: {count:3d} ({pct:5.1f}%)")

            print(f"\n{'='*70}")
            print("LOSS POINTS FOR FAILURES ONLY:")
            failures = [r for r in results_data if not r["baseline_correct"]]
            fail_counts = Counter(r["loss"] for r in failures)
            for loss, count in fail_counts.most_common():
                pct = 100 * count / len(failures)
                print(f"  {loss:25s}: {count:3d}/{len(failures)} ({pct:5.1f}%)")

            print(f"\n{'='*70}")
            print("BY CATEGORY:")
            for cat in sorted(set(r["category"] for r in results_data)):
                cat_data = [r for r in results_data if r["category"] == cat]
                cat_fail = [r for r in cat_data if not r["baseline_correct"]]
                cat_loss = Counter(r["loss"] for r in cat_fail)
                print(f"\n  {cat} ({len(cat_fail)} failures of {len(cat_data)}):")
                for loss, count in cat_loss.most_common():
                    print(f"    {loss:25s}: {count}")

            print(f"\n{'='*70}")
            print("FIX SIMULATIONS:")

            # Sim 1: raise injection limit to 2
            sim2_would_fix = sum(1 for r in failures if r["sim_top2_helps"])
            sim3_would_fix = sum(1 for r in failures if r["sim_top3_helps"])
            print(f"\n  Raise fact_summary limit to 2: would fix {sim2_would_fix}/{len(failures)} failures")
            print(f"  Raise fact_summary limit to 3: would fix {sim3_would_fix}/{len(failures)} failures")

            # Sim 2: subject attribution fix
            wrong_subject = [r for r in failures if r["loss"] == "retrieval_miss_fs"
                            and r["gold_in_db_fs_count"] > 0]
            print(f"\n  Subject attribution fix (gold in DB fact_summary but not retrieved):")
            print(f"    Failures where gold IS in a fact_summary: {sum(1 for r in failures if r['gold_in_db_fs_count'] > 0)}")
            print(f"    Failures where gold is ONLY in non-fs types: {sum(1 for r in failures if r['gold_in_db_fs_count'] == 0 and r['gold_in_db_other_count'] > 0)}")
            print(f"    Failures where gold not in DB at all: {sum(1 for r in failures if r['gold_in_db_fs_count'] == 0 and r['gold_in_db_other_count'] == 0)}")

            # Injection stats
            print(f"\n{'='*70}")
            print("INJECTION STATS:")
            fs_retrieved_total = sum(r["fs_in_results"] for r in results_data)
            fs_injected_total = sum(r["fs_injected"] for r in results_data)
            print(f"  Total fact_summaries retrieved: {fs_retrieved_total}")
            print(f"  Total fact_summaries injected: {fs_injected_total}")
            print(f"  Injection rate: {100*fs_injected_total/max(fs_retrieved_total,1):.1f}%")
            print(f"  Avg fact_summaries per query: {fs_retrieved_total/len(results_data):.1f}")
            print(f"  Avg injected per query: {fs_injected_total/len(results_data):.1f}")

            # Save detailed results
            out_path = Path("evals/locomo/retrieval_eval_output/fix_simulation.jsonl")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w") as f:
                for r in results_data:
                    f.write(json.dumps(r) + "\n")
            print(f"\nDetailed results saved to {out_path}")


if __name__ == "__main__":
    main()
