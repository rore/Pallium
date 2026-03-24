"""
Invariant evaluation runner for automated exploratory QA.

Loads scenarios from JSON, executes them against a fresh Pallium instance,
and evaluates hard invariants on query results. Supports both simple
(prior_events + current_query) and multi-step scenario formats.

Usage:
    python -m evals.generated_exploratory.invariant_runner \
        --scenario-file evals/generated_exploratory/scenarios/seed_invariant_scenarios.json

    python -m evals.generated_exploratory.invariant_runner \
        --scenario-file ... --tier P0 --output-dir evals/generated_exploratory/output/
"""
from __future__ import annotations

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from evals.generated_exploratory.invariants import ALL_INVARIANTS, run_invariants
from evals.generated_exploratory.taxonomy import infer_priority_tier

logger = logging.getLogger(__name__)


DEFAULT_SCENARIO_FILE = Path("evals/generated_exploratory/scenarios/seed_invariant_scenarios.json")
DEFAULT_OUTPUT_DIR = Path("evals/generated_exploratory/output")
DEFAULT_CACHE_DIR = Path(".local/llm-cache")
DEFAULT_TIERS = ["P0", "P1"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run invariant evaluation on exploratory QA scenarios."
    )
    parser.add_argument(
        "--scenario-file", type=Path, default=DEFAULT_SCENARIO_FILE,
        help="Path to JSON scenario file",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help="Output directory for results",
    )
    parser.add_argument(
        "--tier", nargs="*", default=None,
        help="Priority tiers to run (P0, P1, P2). Default: P0 P1",
    )
    parser.add_argument("--run-name", default=None)
    parser.add_argument(
        "--composite-retrieval", action="store_true",
        help="Enable composite (lexical + vector) retrieval. Slower but tests the production path.",
    )
    parser.add_argument(
        "--workers", type=int, default=1,
        help="Number of parallel workers for scenario execution (default: 1 = sequential).",
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=None,
        help=f"Directory for LLM response cache. Defaults to {DEFAULT_CACHE_DIR} if it exists. Use --no-cache to disable.",
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Disable LLM response cache even if the default cache directory exists.",
    )
    args = parser.parse_args()

    tiers = args.tier or DEFAULT_TIERS

    # Resolve cache dir: explicit flag > --no-cache > default if exists.
    cache_dir = args.cache_dir
    if cache_dir is None and not args.no_cache and DEFAULT_CACHE_DIR.exists():
        cache_dir = DEFAULT_CACHE_DIR

    run_dir = run_invariant_evaluation(
        scenario_file=args.scenario_file,
        output_root=args.output_dir,
        config=AppConfig.from_env(),
        tiers=tiers,
        run_name=args.run_name,
        composite_retrieval=args.composite_retrieval,
        max_workers=args.workers,
        cache_dir=cache_dir,
    )
    print(run_dir)
    return 0


def run_invariant_evaluation(
    *,
    scenario_file: Path,
    output_root: Path,
    config: AppConfig,
    tiers: list[str] | None = None,
    run_name: str | None = None,
    composite_retrieval: bool = False,
    max_workers: int = 1,
    cache_dir: Path | None = None,
) -> Path:
    """Run invariant checks on all scenarios in the file.

    When ``composite_retrieval`` is True, enables vector + lexical retrieval
    per scenario (slower, requires ONNX model). This tests the production
    retrieval path including the relevance floor.

    When ``max_workers`` > 1, runs scenarios in parallel using a thread pool.
    Each scenario is fully isolated (own DB, own TestClient) so parallelism
    is safe. The bottleneck is LLM network latency during drain, so threads
    (not processes) are the right primitive.

    Returns the path to the output directory containing results.jsonl and
    summary.json.
    """
    allowed_tiers = set(tiers) if tiers else {"P0", "P1"}
    scenarios = _load_scenarios(scenario_file)

    # Filter scenarios by tier before dispatching to workers.
    eligible: list[tuple[dict[str, Any], str]] = []
    for scenario in scenarios:
        tier = _scenario_tier(scenario)
        if tier in allowed_tiers:
            eligible.append((scenario, tier))

    run_id = run_name or _build_run_id()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    logger.info(
        "Running %d scenarios (workers=%d, composite=%s)",
        len(eligible), max_workers, composite_retrieval,
    )

    all_results: list[dict[str, Any]] = []

    if max_workers <= 1:
        # Sequential execution (original path).
        all_results = _run_sequential(eligible, config, composite_retrieval, cache_dir)
    else:
        all_results = _run_parallel(eligible, config, composite_retrieval, max_workers, cache_dir)

    # Write results.
    with results_path.open("w", encoding="utf-8") as results_file:
        for result in all_results:
            results_file.write(json.dumps(result, default=str) + "\n")

    summary = _build_summary(all_results, scenario_file, run_id)
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    return run_dir


def _run_sequential(
    eligible: list[tuple[dict[str, Any], str]],
    config: AppConfig,
    composite_retrieval: bool,
    cache_dir: Path | None,
) -> list[dict[str, Any]]:
    """Run scenarios sequentially (original behavior)."""
    results: list[dict[str, Any]] = []
    for scenario, tier in eligible:
        result = _execute_one(scenario, tier, config, composite_retrieval, cache_dir)
        results.append(result)
    return results


def _run_parallel(
    eligible: list[tuple[dict[str, Any], str]],
    config: AppConfig,
    composite_retrieval: bool,
    max_workers: int,
    cache_dir: Path | None,
) -> list[dict[str, Any]]:
    """Run scenarios in parallel using a thread pool."""
    results: list[dict[str, Any]] = [None] * len(eligible)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(_execute_one, scenario, tier, config, composite_retrieval, cache_dir): idx
            for idx, (scenario, tier) in enumerate(eligible)
        }
        completed = 0
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            results[idx] = future.result()
            completed += 1
            if completed % 10 == 0 or completed == len(eligible):
                logger.info("  %d/%d scenarios completed", completed, len(eligible))
    return results


def _execute_one(
    scenario: dict[str, Any],
    tier: str,
    config: AppConfig,
    composite_retrieval: bool,
    cache_dir: Path | None,
) -> dict[str, Any]:
    """Execute a single scenario with error handling. Used by both sequential and parallel paths."""
    scenario_id = scenario.get("scenario_id", "unknown")
    try:
        result = _run_scenario(scenario=scenario, config=config, composite_retrieval=composite_retrieval, cache_dir=cache_dir)
    except Exception as exc:
        result = {
            "scenario_id": scenario_id,
            "description": scenario.get("description", ""),
            "step_results": [],
            "all_passed": False,
            "violated_invariants": [],
            "taxonomy_cell": (scenario.get("_generation_metadata") or {}).get("taxonomy_cell"),
            "invariant_count": 0,
            "query_contract_consistent": False,
            "runner_error": f"{type(exc).__name__}: {exc}",
        }
    result["priority_tier"] = tier
    return result


def _run_scenario(
    *,
    scenario: dict[str, Any],
    config: AppConfig,
    composite_retrieval: bool = False,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute a single scenario and return invariant results."""
    scenario_id = scenario.get("scenario_id", "unknown")

    with TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'scenario.db'}"
        vector_index_config = replace(
            config.vector_index,
            index_path=str(Path(temp_dir) / "vector.index"),
            enabled=composite_retrieval,
        )
        scenario_config = replace(
            config,
            sqlite_url=database_url,
            default_use_case="agent_conversation_memory",
            vector_index=vector_index_config,
        )

        with TestClient(create_app(scenario_config)) as client:
            # Optionally wrap LLM providers with cache.
            if cache_dir is not None:
                _wrap_providers_with_cache(client, cache_dir)

            if "steps" in scenario:
                step_results = _run_multi_step(scenario, client)
            else:
                step_results = _run_simple(scenario, client)

            engine = getattr(
                client.app.state.pallium_service._storage, "_engine", None
            )
            if engine is not None:
                engine.dispose()

    all_invariant_results = []
    for sr in step_results:
        all_invariant_results.extend(sr.get("invariant_results", []))

    violated = [
        ir["invariant_id"]
        for ir in all_invariant_results
        if not ir["passed"]
    ]

    # Detect malformed scenarios that ran no invariants (e.g., only ingest steps).
    has_invariants = len(all_invariant_results) > 0
    all_passed = has_invariants and len(violated) == 0

    meta = scenario.get("_generation_metadata") or {}
    return {
        "scenario_id": scenario_id,
        "description": scenario.get("description", ""),
        "step_results": step_results,
        "all_passed": all_passed,
        "violated_invariants": violated,
        "taxonomy_cell": meta.get("taxonomy_cell"),
        "invariant_count": len(all_invariant_results),
        # Emit query_contract_consistent so benchmark_architecture._contract_success
        # recognises this result in the CONTRACT lane.
        "query_contract_consistent": all_passed,
        "runner_error": None if has_invariants else "no_invariants_executed",
    }


def _run_simple(
    scenario: dict[str, Any],
    client: TestClient,
) -> list[dict[str, Any]]:
    """Run a simple scenario: prior_events → drain → query → check."""
    for event in scenario.get("prior_events", []):
        response = client.post("/items", json=[_with_default_visibility(event)])
        response.raise_for_status()

    _drain(client)

    query_request = _with_default_visibility(scenario["current_query"])
    query_payload = _post_query(client, query_request)
    debug_payload = _post_query_debug(client, query_request)

    invariant_ids = _applicable_invariants(scenario)
    results = run_invariants(scenario, query_payload, debug_payload, invariant_ids=invariant_ids)

    soft = _check_soft_expectations(
        scenario.get("_generation_metadata", {}).get("soft_expectations"),
        query_payload,
        debug_payload,
    )

    return [{
        "step_id": "query",
        "invariant_results": [asdict(r) for r in results],
        "soft_expectation_results": soft,
    }]


def _run_multi_step(
    scenario: dict[str, Any],
    client: TestClient,
) -> list[dict[str, Any]]:
    """Run a multi-step scenario, processing ingest and query steps in order."""
    step_results: list[dict[str, Any]] = []

    for step in scenario["steps"]:
        action = step.get("action")

        if action == "ingest":
            for event in step.get("events", []):
                response = client.post(
                    "/items", json=[_with_default_visibility(event)]
                )
                response.raise_for_status()
            _drain(client)

        elif action == "query":
            query_request = _with_default_visibility(step["query"])
            query_payload = _post_query(client, query_request)
            debug_payload = _post_query_debug(client, query_request)

            # Build a per-step scenario view so invariant helpers
            # (_query_container_ref, _query_actor_ref, _query_visibility)
            # resolve from THIS step's query, not the last query step.
            step_scenario = {**scenario, "current_query": step["query"]}

            invariant_ids = step.get("invariant_assertions") or _applicable_invariants(scenario)
            results = run_invariants(
                step_scenario, query_payload, debug_payload, invariant_ids=invariant_ids
            )

            soft = _check_soft_expectations(
                step.get("soft_expectations"),
                query_payload,
                debug_payload,
            )

            step_results.append({
                "step_id": step.get("step_id", f"step_{len(step_results)}"),
                "invariant_results": [asdict(r) for r in results],
                "soft_expectation_results": soft,
            })

    return step_results


# ---------------------------------------------------------------------------
# Soft expectations (must_include / must_not_include)
# ---------------------------------------------------------------------------

def _check_soft_expectations(
    expectations: dict[str, Any] | None,
    query_payload: dict[str, Any],
    debug_payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Check must_include / must_not_include against injectable blocks + results."""
    if not expectations:
        return None

    # Build searchable text from injectable blocks and result excerpts.
    text_parts: list[str] = []
    for block in query_payload.get("injectable_blocks", []):
        text_parts.append((block.get("text") or "").lower())
    for result in debug_payload.get("results", []):
        text_parts.append((result.get("excerpt") or "").lower())
        payload = result.get("payload") or {}
        text_parts.append((payload.get("summary") or "").lower())
    combined = " ".join(text_parts)

    must_include = expectations.get("must_include", [])
    must_not_include = expectations.get("must_not_include", [])

    included = [term for term in must_include if term.lower() in combined]
    missing = [term for term in must_include if term.lower() not in combined]
    forbidden_found = [term for term in must_not_include if term.lower() in combined]

    return {
        "must_include_ok": len(missing) == 0,
        "included": included,
        "missing": missing,
        "must_not_include_ok": len(forbidden_found) == 0,
        "forbidden_found": forbidden_found,
    }


# ---------------------------------------------------------------------------
# LLM cache integration
# ---------------------------------------------------------------------------

def _wrap_providers_with_cache(client: TestClient, cache_dir: Path) -> None:
    """Wrap all LLM providers in the app's semantic plugins with a file cache.

    This caches drain-time LLM calls (write_extraction, thread_rebuild,
    consolidation) so repeat runs skip network calls. The cache is shared
    across scenarios since prompt+content deterministically produces the
    same response.

    Note: the query-time resolver provider (_resolver_config["provider"])
    is intentionally NOT wrapped — it runs during query, not drain, and
    its caching would mask query-time behavior changes.
    """
    from providers.llm.cached import CachedLLMProvider

    service = client.app.state.pallium_service
    for plugin in service._semantic_plugins.values():
        # Wrap the default provider.
        if hasattr(plugin, "_provider") and not isinstance(plugin._provider, CachedLLMProvider):
            plugin._provider = CachedLLMProvider(plugin._provider, cache_dir)
        # Wrap role-specific providers.
        if hasattr(plugin, "_providers_by_role"):
            for role, prov in plugin._providers_by_role.items():
                if not isinstance(prov, CachedLLMProvider):
                    plugin._providers_by_role[role] = CachedLLMProvider(prov, cache_dir)
        # Wrap the delegate's provider (LLMAgentMemoryPlugin).
        if hasattr(plugin, "_delegate") and hasattr(plugin._delegate, "_provider"):
            if not isinstance(plugin._delegate._provider, CachedLLMProvider):
                plugin._delegate._provider = CachedLLMProvider(plugin._delegate._provider, cache_dir)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _drain(client: TestClient) -> None:
    """Drain the processing queue synchronously."""
    client.app.state.pallium_service.drain_processing_queue(
        worker_id="invariant-runner"
    )


def _post_query(client: TestClient, query_request: dict[str, Any]) -> dict[str, Any]:
    """POST /query and return parsed response."""
    response = client.post("/query", json=query_request)
    response.raise_for_status()
    return response.json()


def _post_query_debug(client: TestClient, query_request: dict[str, Any]) -> dict[str, Any]:
    """POST /query/debug and return parsed response."""
    response = client.post("/query/debug", json=query_request)
    response.raise_for_status()
    return response.json()


def _with_default_visibility(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure visibility is set (default: public)."""
    updated = dict(payload)
    updated.setdefault("visibility", "public")
    return updated


def _applicable_invariants(scenario: dict[str, Any]) -> list[str]:
    """Determine which invariants to run for this scenario.

    If the scenario metadata specifies invariant_assertions, use those.
    Otherwise run all invariants.
    """
    meta = scenario.get("_generation_metadata") or {}
    assertions = meta.get("invariant_assertions")
    if assertions:
        return assertions
    return list(ALL_INVARIANTS)


def _scenario_tier(scenario: dict[str, Any]) -> str:
    """Determine the priority tier of a scenario."""
    meta = scenario.get("_generation_metadata") or {}
    if meta.get("priority_tier"):
        return meta["priority_tier"]
    # Infer from invariant assertions.
    assertions = meta.get("invariant_assertions") or []
    if assertions:
        return infer_priority_tier(assertions)
    # Default: P1 for authored scenarios without metadata.
    return "P1"


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    """Load scenarios from a JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def _build_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"invariant-eval__{timestamp}"


def _build_summary(
    results: list[dict[str, Any]],
    scenario_file: Path,
    run_id: str,
) -> dict[str, Any]:
    """Build summary report from all scenario results."""
    total = len(results)
    passed = sum(1 for r in results if r["all_passed"])
    violated = total - passed

    # Aggregate by tier.
    by_tier: dict[str, dict[str, int]] = {}
    for r in results:
        tier = r.get("priority_tier", "P2")
        if tier not in by_tier:
            by_tier[tier] = {"total": 0, "passed": 0, "violated": 0}
        by_tier[tier]["total"] += 1
        if r["all_passed"]:
            by_tier[tier]["passed"] += 1
        else:
            by_tier[tier]["violated"] += 1

    # Aggregate violations by invariant ID.
    by_invariant: dict[str, int] = {}
    for r in results:
        for inv_id in r.get("violated_invariants", []):
            by_invariant[inv_id] = by_invariant.get(inv_id, 0) + 1

    # Collect failed scenario IDs.
    failed_scenarios = [
        {"scenario_id": r["scenario_id"], "violated": r["violated_invariants"]}
        for r in results
        if not r["all_passed"]
    ]

    return {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario_file": str(scenario_file),
        "scenarios_total": total,
        "scenarios_passed": passed,
        "scenarios_violated": violated,
        "by_tier": by_tier,
        "by_invariant": by_invariant,
        "failed_scenarios": failed_scenarios,
    }


if __name__ == "__main__":
    raise SystemExit(main())
