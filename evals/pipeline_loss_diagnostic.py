"""Pipeline loss diagnostic: traces where gold answers are lost for conv-43.

Loads the cached conv-43 DB, starts a test server, runs /query/debug for
sample failing questions, and reports exactly where gold answers are lost.
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
    {"question": "What was the highest number of points John scored in a game recently?", "gold_keywords": ["40"]},
    {"question": "What books has Tim read?", "gold_keywords": ["alchemist", "hobbit", "wheel of time"]},
    {"question": "what are John's goals with regards to his basketball career?", "gold_keywords": ["championship"]},
    {"question": "How long has John been surfing?", "gold_keywords": ["five years", "surfing"]},
    {"question": "Which outdoor gear company likely signed up John for an endorsement deal?", "gold_keywords": ["under armour"]},
    {"question": "What map does Tim show to his friend John?", "gold_keywords": ["middle-earth", "middle earth"]},
    {"question": "Who is one of Tim's sources of inspiration for writing?", "gold_keywords": ["rowling"]},
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
    cached_db = DB_CACHE_DIR / f"{SAMPLE_ID}.db"
    cached_vector = DB_CACHE_DIR / f"{SAMPLE_ID}.vector.index"

    if not cached_db.exists():
        print(f"ERROR: No cached DB at {cached_db}. Run benchmark with --rebuild-db-cache first.")
        sys.exit(1)

    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "locomo.db"
        vector_path = Path(temp_dir) / "vector.index"
        shutil.copy2(cached_db, db_path)
        _copy_vector_index(cached_vector, vector_path)

        scenario_config = replace(
            config,
            sqlite_url=f"sqlite:///{db_path}",
            default_use_case="agent_conversation_memory",
            vector_index=replace(config.vector_index, index_path=str(vector_path)),
        )

        with TestClient(create_app(scenario_config)) as client:
            storage = client.app.state.pallium_service._storage

            all_fs = storage.list_memory_objects(memory_types=["fact_summary"], lifecycle="active")
            wcs = [len(str(mo.payload.get("summary", "")).split()) for mo in all_fs]
            print(f"Active fact_summaries: {len(all_fs)}, word counts: min={min(wcs)} max={max(wcs)} avg={sum(wcs)/len(wcs):.0f}")
            print()

            loss_summary = Counter()

            for dq in DIAGNOSTIC_QUESTIONS:
                question = dq["question"]
                gold_keywords = [kw.lower() for kw in dq["gold_keywords"]]

                print(f"{'='*70}")
                print(f"Q: {question}")
                print(f"Gold keywords: {gold_keywords}")

                resp = client.post("/query/debug", json={
                    "text": question,
                    "limit": 10,
                    "container_ref": SAMPLE_ID,
                    "visibility": "public",
                    "runtime_context": {"turn_kind": "new_session", "session_has_sufficient_local_context": False},
                })
                resp.raise_for_status()
                data = resp.json()

                results = data.get("results", [])
                blocks = data.get("injectable_blocks", data.get("blocks", []))

                # Check injected blocks for gold keywords
                blocks_text = json.dumps(blocks).lower()
                gold_in_blocks = any(kw in blocks_text for kw in gold_keywords)

                # Check all retrieval results for gold keywords
                gold_in_results = []
                non_injected_gold = []
                for i, r in enumerate(results):
                    rtext = json.dumps(r).lower()
                    has_gold = any(kw in rtext for kw in gold_keywords)
                    rtype = r.get("type", r.get("memory_type", "?"))
                    rid = str(r.get("memory_object_id", r.get("id", "?")))[:12]
                    injected = r.get("injected", False)
                    if has_gold:
                        gold_in_results.append((i, rtype, rid, injected))
                        if not injected:
                            non_injected_gold.append((i, rtype, rid))

                type_counts = Counter(r.get("type", r.get("memory_type", "?")) for r in results)
                print(f"Retrieved: {len(results)} results {dict(type_counts)}")
                print(f"Injected blocks: {len(blocks)}")

                if gold_in_blocks:
                    print(f">> GOLD IN INJECTED BLOCKS — loss at answering LLM")
                    loss_summary["answering"] += 1
                elif gold_in_results:
                    print(f">> GOLD RETRIEVED BUT NOT INJECTED:")
                    for idx, rtype, rid, inj in gold_in_results:
                        print(f"   Result #{idx}: {rtype} ({rid}) injected={inj}")
                    if non_injected_gold:
                        print(f">> LOSS AT INJECTION PIPELINE")
                        loss_summary["injection"] += 1
                    else:
                        print(f">> Gold in results but no match in blocks text — gold_in_context check issue")
                        loss_summary["gold_check"] += 1
                else:
                    # Check DB
                    all_active = storage.list_memory_objects(lifecycle="active")
                    db_matches = [(mo.type, mo.id[:12]) for mo in all_active
                                  if any(kw in json.dumps(mo.payload).lower() for kw in gold_keywords)]
                    if db_matches:
                        print(f">> GOLD IN DB BUT NOT RETRIEVED:")
                        for mtype, mid in db_matches[:5]:
                            print(f"   {mtype} ({mid})")
                        print(f">> LOSS AT RETRIEVAL RANKING")
                        loss_summary["retrieval"] += 1
                    else:
                        print(f">> GOLD NOT IN DB — extraction/consolidation gap")
                        loss_summary["extraction"] += 1

                # Show injected block summaries
                for b in blocks[:2]:
                    btype = b.get("memory_type", "?")
                    btitle = b.get("title", "?")
                    btext = str(b.get("text", ""))[:150]
                    print(f"  Injected [{btype}]: {btext}...")
                print()

            print("=" * 70)
            print("LOSS SUMMARY:")
            for cause, count in loss_summary.most_common():
                print(f"  {cause}: {count}/{len(DIAGNOSTIC_QUESTIONS)}")


if __name__ == "__main__":
    main()
