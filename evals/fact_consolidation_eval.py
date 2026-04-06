"""Retrieval quality eval for fact consolidation.

Tests that fact_summary objects created by consolidation actually surface
in retrieval results for multi_hop queries, using the cached conv-26.db.

Usage:
    python -m evals.fact_consolidation_eval
    python -m evals.fact_consolidation_eval --verbose
"""
from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app


DEFAULT_DB_CACHE_DIR = Path("evals/locomo/db_cache")

CONSOLIDATION_QUALITY_CHECKS = [
    {
        "query": "What activities does Melanie partake in?",
        "expect_type": "fact_summary",
        "expect_subject": "melanie",
        "expect_keywords": ["pottery", "painting", "camping", "running"],
        "min_keywords": 3,
    },
    {
        "query": "What has Melanie painted?",
        "expect_type": "fact_summary",
        "expect_subject": "melanie",
        "expect_keywords": ["sunrise", "sunset"],
        "min_keywords": 1,
    },
    {
        "query": "What types of pottery have Melanie and her kids made?",
        "expect_type": "fact_summary",
        "expect_subject": "melanie",
        "expect_keywords": ["bowl", "plate"],
        "min_keywords": 1,
    },
]


def _copy_vector_index(src_prefix: Path, dst_prefix: Path) -> None:
    """Copy vector index files (main + .idmap.json + .meta.json)."""
    for suffix in ("", ".idmap.json", ".meta.json"):
        src = Path(str(src_prefix) + suffix)
        dst = Path(str(dst_prefix) + suffix)
        if src.exists():
            shutil.copy2(src, dst)


def run_eval(*, db_cache_dir: Path, verbose: bool = False) -> bool:
    config = AppConfig.from_env()
    sample_id = "conv-26"

    cached_db_path = db_cache_dir / f"{sample_id}.db"
    cached_vector_prefix = db_cache_dir / f"{sample_id}.vector.index"

    if not cached_db_path.exists():
        print(f"ERROR: {cached_db_path} not found. Run LoCoMo benchmark first.")
        return False

    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "eval.db"
        vector_path = Path(temp_dir) / "vector.index"

        shutil.copy2(cached_db_path, db_path)
        _copy_vector_index(cached_vector_prefix, vector_path)

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
            # Step 1: Run fact consolidation
            print("Running fact consolidation pass...")
            service = client.app.state.pallium_service
            result = service.run_consolidation_pass(use_case="conversational_knowledge")

            if result is None:
                print("ERROR: Consolidation returned None — plugin not registered or no policy")
                return False

            print(f"  Candidates: {result.candidate_count}")
            print(f"  Groups: {len(result.groups)}")
            for g in result.groups:
                print(f"    {g.group_key}: created={len(g.created_memory_ids)} superseded={len(g.superseded_memory_ids)}")

            # Step 2: Reconcile vector index so new objects are searchable
            service.reconcile_vector_index()

            # Step 3: Run queries and check results
            print("\nRunning quality checks...")
            passed = 0
            failed = 0

            for check in CONSOLIDATION_QUALITY_CHECKS:
                query = check["query"]
                resp = client.post(
                    "/query/debug",
                    json={
                        "text": query,
                        "limit": 10,
                        "container_ref": sample_id,
                        "visibility": "public",
                        "runtime_context": {
                            "turn_kind": "new_session",
                            "session_has_sufficient_local_context": False,
                        },
                    },
                )
                if resp.status_code != 200:
                    print(f"  FAIL: {query}")
                    print(f"    Query failed with status {resp.status_code}")
                    failed += 1
                    continue

                data = resp.json()
                results_list = data.get("results", [])
                if verbose:
                    memory_hits = [r for r in results_list if r.get("result_kind") == "memory_hit"]
                    source_hits = [r for r in results_list if r.get("result_kind") == "source_hit"]
                    print(f"    Results: {len(results_list)} total, {len(memory_hits)} memory_hits, {len(source_hits)} source_hits")
                    for r in memory_hits[:3]:
                        mtype = r.get("memory_object_type") or r.get("payload", {}).get("type", "?")
                        print(f"      memory_hit: type={mtype} score={r.get('score')}")

                # Find fact_summary in results
                fact_summaries = [
                    r for r in results_list
                    if r.get("result_kind") == "memory_hit"
                    and r.get("payload", {}).get("consolidation_provenance", {}).get("memory_kind") == "fact_summary"
                ]

                if not fact_summaries:
                    # Also check by type field
                    fact_summaries = [
                        r for r in results_list
                        if r.get("result_kind") == "memory_hit"
                        and "fact_summary" in str(r.get("memory_type", ""))
                    ]

                if not fact_summaries:
                    print(f"  FAIL: {query}")
                    print(f"    No fact_summary in top-{len(results_list)} results")
                    if verbose:
                        for r in results_list[:5]:
                            print(f"      {r.get('memory_type', 'unknown')}: {str(r.get('payload', {}))[:100]}")
                    failed += 1
                    continue

                # Check keywords in the summary
                best_summary = fact_summaries[0]
                summary_text = str(best_summary.get("payload", {}).get("summary", "")).lower()
                subject = str(best_summary.get("payload", {}).get("subject", "")).lower()

                # Subject check
                if check["expect_subject"] not in subject:
                    print(f"  FAIL: {query}")
                    print(f"    Wrong subject: expected '{check['expect_subject']}', got '{subject}'")
                    failed += 1
                    continue

                # Keyword check
                found_keywords = [k for k in check["expect_keywords"] if k.lower() in summary_text]
                if len(found_keywords) < check["min_keywords"]:
                    print(f"  FAIL: {query}")
                    print(f"    Keywords: {len(found_keywords)}/{check['min_keywords']} required")
                    print(f"    Found: {found_keywords}")
                    print(f"    Missing: {[k for k in check['expect_keywords'] if k.lower() not in summary_text]}")
                    failed += 1
                    continue

                print(f"  PASS: {query}")
                print(f"    Keywords: {len(found_keywords)}/{len(check['expect_keywords'])} ({found_keywords})")
                if verbose:
                    print(f"    Summary: {summary_text[:200]}...")
                passed += 1

            print(f"\nResults: {passed} passed, {failed} failed out of {len(CONSOLIDATION_QUALITY_CHECKS)}")
            return failed == 0


def main():
    parser = argparse.ArgumentParser(description="Fact consolidation retrieval quality eval")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print full summaries")
    parser.add_argument("--db-cache-dir", type=Path, default=DEFAULT_DB_CACHE_DIR)
    args = parser.parse_args()

    success = run_eval(db_cache_dir=args.db_cache_dir, verbose=args.verbose)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
