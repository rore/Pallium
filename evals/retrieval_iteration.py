"""Quick iteration experiments on retrieval quality.

Runs the 17 curated failure cases through Pallium with different configs,
reports which cases flip from fail to pass. ~2-3 min per config.

Usage:
    python -m evals.retrieval_iteration
"""
from __future__ import annotations

import shutil
import time
from dataclasses import replace
from pathlib import Path

from app.config import AppConfig
from app.main import create_app
from starlette.testclient import TestClient

DB_CACHE = Path("evals/locomo/db_cache/conv-26.db")
CONV_ID = "conv-26"
EXPERIMENT_DIR = Path("evals/locomo/experiments")

from evals.test_retrieval_quality import FAILURE_CASES
from evals.retrieval_experiments import (
    _copy_db_cache,
    prepare_experiment_b,
    prepare_experiment_e,
)


def _run_config(label, query_limit=10, db_path=DB_CACHE):
    """Run failure cases against a config. Vector index is always rebuilt fresh from DB."""
    # Vector index lives alongside the DB; using a sibling path avoids config-default collisions
    vector_path = Path(str(db_path).replace(".db", ".vector.index"))
    # Remove any stale vector files so reconcile starts from scratch
    for suffix in ["", ".idmap.json", ".meta.json"]:
        stale = Path(f"{vector_path}{suffix}")
        if stale.exists():
            stale.unlink()

    config = AppConfig.from_env()
    vc = replace(config.vector_index, index_path=str(vector_path))
    sc = replace(config, sqlite_url=f"sqlite:///{db_path}", default_use_case="agent_conversation_memory", vector_index=vc)
    app = create_app(sc)
    results = {"label": label, "cases": [], "passed": 0, "failed": 0, "total": len(FAILURE_CASES)}

    with TestClient(app) as client:
        # Stop background reconcile daemon to avoid concurrent save() conflicts on Windows
        stop_event = getattr(client.app.state, "_reconcile_stop", None)
        if stop_event is not None:
            stop_event.set()

        # Reconcile fully — batch_size=50, loop until 0 changes (handles 1000+ entries)
        total_reconciled = 0
        while True:
            changed = client.app.state.pallium_service.reconcile_vector_index()
            total_reconciled += changed
            if changed == 0:
                break
        if total_reconciled:
            print(f"    Reconciled {total_reconciled} vector entries")
        for case in FAILURE_CASES:
            resp = client.post("/query/debug", json={
                "text": case["q"], "limit": query_limit, "container_ref": CONV_ID,
                "visibility": "public",
                "runtime_context": {"turn_kind": "new_session", "session_has_sufficient_local_context": False},
            })
            ret = resp.json().get("results", []) if resp.status_code == 200 else []
            context_parts = []
            for r in ret:
                # source_hit: text is in excerpt
                # memory_hit: text is in payload fields (summary, statement, etc.)
                context_parts.append(r.get("excerpt") or "")
                payload = r.get("payload") or {}
                context_parts.append(payload.get("summary") or "")
                context_parts.append(payload.get("statement") or "")
                context_parts.append(payload.get("decision") or "")
                context_parts.append(payload.get("description") or "")
            context = " ".join(context_parts).lower()
            missing = [kw for kw in case["gold_keywords"] if kw.lower() not in context]
            found = len(missing) == 0
            results["cases"].append({
                "q": case["q"][:55], "found": found, "missing": missing,
                "source_hits": sum(1 for r in ret if r.get("result_kind") == "source_hit"),
                "mem_hits": sum(1 for r in ret if r.get("result_kind") == "memory_hit"),
                "total": len(ret),
            })
            if found:
                results["passed"] += 1
            else:
                results["failed"] += 1
    return results


def _print_results(all_results):
    print("\n" + "=" * 90)
    print("EXPERIMENT RESULTS")
    print("=" * 90)
    print(f"\n{'Config':<42} | {'Passed':>6} | {'Failed':>6} | {'Rate':>6}")
    print("-" * 65)
    for r in all_results:
        rate = r["passed"] / r["total"] * 100
        print(f"{r['label']:<42} | {r['passed']:>6} | {r['failed']:>6} | {rate:>5.0f}%")

    print(f"\n{'Case':<55}", end="")
    for r in all_results:
        print(f" | {r['label'][:8]:>8}", end="")
    print()
    print("-" * (55 + 11 * len(all_results)))
    for i, case in enumerate(FAILURE_CASES):
        print(f"{case['q'][:53]:<55}", end="")
        for r in all_results:
            print(f" | {'PASS' if r['cases'][i]['found'] else 'fail':>8}", end="")
        print()

    baseline = all_results[0]
    for r in all_results[1:]:
        flipped = [FAILURE_CASES[i]["q"][:60] for i, (bc, rc) in enumerate(zip(baseline["cases"], r["cases"])) if not bc["found"] and rc["found"]]
        regressed = [FAILURE_CASES[i]["q"][:60] for i, (bc, rc) in enumerate(zip(baseline["cases"], r["cases"])) if bc["found"] and not rc["found"]]
        if flipped or regressed:
            print(f"\n  {r['label']} vs baseline:")
            for q in flipped:
                print(f"    + FIXED: {q}")
            for q in regressed:
                print(f"    - REGRESSED: {q}")


def _safe_rmtree(path: Path) -> None:
    """Remove tree, ignoring errors (Windows keeps DB files open briefly after close)."""
    import time
    for _ in range(3):
        try:
            shutil.rmtree(path, ignore_errors=True)
            return
        except Exception:
            time.sleep(1)
    shutil.rmtree(path, ignore_errors=True)


def main():
    src_dir = Path("evals/locomo/db_cache")
    all_results = []

    # --- A: Baseline ---
    print("=== A: Baseline ===")
    exp_dir = EXPERIMENT_DIR / "iter_A"
    exp_dir.mkdir(parents=True, exist_ok=True)
    _copy_db_cache(src_dir, exp_dir, ["conv-26"])
    t0 = time.time()
    all_results.append(_run_config("A: baseline", db_path=exp_dir / "conv-26.db"))
    print(f"  {all_results[-1]['passed']}/{all_results[-1]['total']} passed, {time.time()-t0:.0f}s")
    _safe_rmtree(exp_dir)

    # --- B: Restore superseded atomic_facts ---
    print("\n=== B: Restore atomic_facts ===")
    exp_dir = EXPERIMENT_DIR / "iter_B"
    exp_dir.mkdir(parents=True, exist_ok=True)
    _copy_db_cache(src_dir, exp_dir, ["conv-26"])
    prepare_experiment_b(exp_dir, ["conv-26"])
    t0 = time.time()
    all_results.append(_run_config("B: restore atomic_facts", db_path=exp_dir / "conv-26.db"))
    print(f"  {all_results[-1]['passed']}/{all_results[-1]['total']} passed, {time.time()-t0:.0f}s")
    _safe_rmtree(exp_dir)

    # --- E: Fragment indexing ---
    print("\n=== E: Fragment indexing ===")
    exp_dir = EXPERIMENT_DIR / "iter_E"
    exp_dir.mkdir(parents=True, exist_ok=True)
    _copy_db_cache(src_dir, exp_dir, ["conv-26"])
    prepare_experiment_e(exp_dir, ["conv-26"])
    t0 = time.time()
    all_results.append(_run_config("E: fragment indexing", db_path=exp_dir / "conv-26.db"))
    print(f"  {all_results[-1]['passed']}/{all_results[-1]['total']} passed, {time.time()-t0:.0f}s")
    _safe_rmtree(exp_dir)

    # --- B+E: Both ---
    print("\n=== B+E: atomic_facts + fragments ===")
    exp_dir = EXPERIMENT_DIR / "iter_BE"
    exp_dir.mkdir(parents=True, exist_ok=True)
    _copy_db_cache(src_dir, exp_dir, ["conv-26"])
    prepare_experiment_b(exp_dir, ["conv-26"])
    prepare_experiment_e(exp_dir, ["conv-26"])
    t0 = time.time()
    all_results.append(_run_config("B+E: atomic_facts + fragments", db_path=exp_dir / "conv-26.db"))
    print(f"  {all_results[-1]['passed']}/{all_results[-1]['total']} passed, {time.time()-t0:.0f}s")
    _safe_rmtree(exp_dir)

    # --- B with limit=15 ---
    print("\n=== B+15: atomic_facts + limit=15 ===")
    exp_dir = EXPERIMENT_DIR / "iter_B15"
    exp_dir.mkdir(parents=True, exist_ok=True)
    _copy_db_cache(src_dir, exp_dir, ["conv-26"])
    prepare_experiment_b(exp_dir, ["conv-26"])
    t0 = time.time()
    all_results.append(_run_config("B+15: atomic_facts + limit=15", query_limit=15, db_path=exp_dir / "conv-26.db"))
    print(f"  {all_results[-1]['passed']}/{all_results[-1]['total']} passed, {time.time()-t0:.0f}s")
    _safe_rmtree(exp_dir)

    _print_results(all_results)


if __name__ == "__main__":
    main()
