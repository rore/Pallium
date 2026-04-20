"""Deep retrieval scoring diagnostic for conv-43 failures.

For each retrieval-miss question: shows what scored in top-10,
what the gold-containing memory scored, and why it lost.
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

DIAGNOSTIC_QUESTIONS = [
    {"question": "What is John's position on the team he signed with?", "gold_keywords": ["shooting guard"]},
    {"question": "What items does John collect?", "gold_keywords": ["sneakers", "dvd", "jerseys"]},
    {"question": "What books has Tim read?", "gold_keywords": ["alchemist", "hobbit", "wheel of time"]},
    {"question": "what are John's goals with regards to his basketball career?", "gold_keywords": ["championship"]},
    {"question": "How long has John been surfing?", "gold_keywords": ["five years", "surfing"]},
    {"question": "Which outdoor gear company likely signed up John for an endorsement deal?", "gold_keywords": ["under armour"]},
    {"question": "What map does Tim show to his friend John?", "gold_keywords": ["middle-earth", "middle earth"]},
    {"question": "Which basketball team does Tim support?", "gold_keywords": ["wolves"]},
]


def _copy_vector_index(src_prefix: Path, dst_prefix: Path):
    for suffix in ["", ".idmap.json", ".meta.json"]:
        src = Path(f"{src_prefix}{suffix}")
        dst = Path(f"{dst_prefix}{suffix}")
        if src.exists():
            shutil.copy2(src, dst)


def main():
    config = AppConfig.from_env()

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

            # Build a map of memory_object_id -> (type, summary_text_snippet)
            all_active = storage.list_memory_objects(lifecycle="active")
            mo_map = {}
            for mo in all_active:
                summary = str(mo.payload.get("summary", mo.payload.get("statement", "")))
                subject = str(mo.payload.get("subject", ""))
                category = str(mo.payload.get("category", ""))
                label = f"{subject}/{category}" if subject else mo.type
                mo_map[mo.id] = {
                    "type": mo.type,
                    "label": label,
                    "text_snippet": summary[:100],
                    "full_text": summary,
                    "word_count": len(summary.split()),
                }

            for dq in DIAGNOSTIC_QUESTIONS:
                question = dq["question"]
                gold_keywords = [kw.lower() for kw in dq["gold_keywords"]]

                print(f"\n{'='*70}")
                print(f"Q: {question}")
                print(f"Gold: {gold_keywords}")

                resp = client.post("/query/debug", json={
                    "text": question, "limit": 10,
                    "container_ref": SAMPLE_ID, "visibility": "public",
                    "runtime_context": {"turn_kind": "new_session",
                                       "session_has_sufficient_local_context": False},
                })
                data = resp.json()
                results = data.get("results", [])
                trace = data.get("trace", {})
                injectable = data.get("injectable_blocks", [])

                # Show top-10 results with scores
                print(f"\nTop-{len(results)} retrieved results:")
                for i, r in enumerate(results):
                    mo_id = r.get("memory_object_id", "")
                    score = r.get("score", 0)
                    rtype = r.get("type") or "source_hit"
                    info = mo_map.get(mo_id, {})
                    label = info.get("label", "?")
                    snippet = info.get("text_snippet", "")
                    if not snippet:
                        snippet = str(r.get("excerpt", ""))[:80]
                    wc = info.get("word_count", "?")
                    has_gold = any(kw in info.get("full_text", "").lower() for kw in gold_keywords)
                    if not has_gold:
                        has_gold = any(kw in str(r.get("excerpt", "")).lower() for kw in gold_keywords)
                    gold_marker = " *** GOLD ***" if has_gold else ""
                    injected = "INJ" if any(b.get("memory_object_id") == mo_id for b in injectable) else "   "
                    print(f"  [{injected}] #{i} score={score:6.1f} {str(rtype):20s} {str(label):30s} ({wc}w) {snippet[:60]}{gold_marker}")

                # Find gold-containing objects NOT in results
                gold_objects_in_db = []
                for mo_id, info in mo_map.items():
                    if any(kw in info["full_text"].lower() for kw in gold_keywords):
                        in_results = any(r.get("memory_object_id") == mo_id for r in results)
                        gold_objects_in_db.append((mo_id, info, in_results))

                missed_gold = [(mid, info) for mid, info, in_res in gold_objects_in_db if not in_res]
                if missed_gold:
                    print(f"\n  Gold objects NOT in top-{len(results)}:")
                    for mid, info in missed_gold:
                        print(f"    {info['type']:20s} {info['label']:30s} ({info['word_count']}w) {info['text_snippet'][:60]}")

                # Show routing trace if available
                routing = trace.get("routing", {})
                if routing:
                    print(f"\n  Routing: candidates={routing.get('candidate_count_entering_routing', '?')}")
                    excluded = routing.get("excluded_high_scoring_candidates", [])
                    if excluded:
                        print(f"  Excluded high-scoring candidates: {len(excluded)}")
                        for exc in excluded[:3]:
                            print(f"    {exc}")
                    demoted = routing.get("demoted_higher_level_hits", [])
                    if demoted:
                        print(f"  Demoted higher-level hits: {len(demoted)}")

                # Show fusion trace
                fusion = trace.get("fusion_trace", {})
                if fusion:
                    print(f"\n  Fusion: {json.dumps({k: v for k, v in fusion.items() if not isinstance(v, (list, dict))}, default=str)}")

                # Show stages
                stages = trace.get("stages", [])
                for stage in stages:
                    if isinstance(stage, dict):
                        sname = stage.get("stage", stage.get("name", "?"))
                        scount = stage.get("result_count", stage.get("count", "?"))
                        print(f"  Stage: {sname} -> {scount} results")


if __name__ == "__main__":
    main()
